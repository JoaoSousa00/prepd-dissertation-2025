import contextvars
import json
import logging
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterable, Optional

logger = logging.getLogger("smartalarms.observability")

_request_context_var: contextvars.ContextVar[Optional["RequestLogContext"]] = (
    contextvars.ContextVar("smartalarms_request_context", default=None)
)
_summary_emitted_var: contextvars.ContextVar[bool] = (
    contextvars.ContextVar("smartalarms_summary_emitted", default=False)
)


def get_current_request_context() -> Optional["RequestLogContext"]:
    return _request_context_var.get()


@contextmanager
def bind_request_context(context: Optional["RequestLogContext"] = None):
    previous_context = _request_context_var.get()
    previous_emitted = _summary_emitted_var.get()
    effective_context = context or RequestLogContext()
    token_context = _request_context_var.set(effective_context)
    token_emitted = _summary_emitted_var.set(False)
    try:
        yield effective_context
    finally:
        _request_context_var.reset(token_context)
        _summary_emitted_var.reset(token_emitted)
        if previous_context is not None:
            _request_context_var.set(previous_context)
        _summary_emitted_var.set(previous_emitted)


@dataclass
class RequestLogContext:
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    itsm_status_codes: list[int] = field(default_factory=list)
    itsm_errors: list[str] = field(default_factory=list)
    llm_status_codes: list[int] = field(default_factory=list)
    llm_errors: list[str] = field(default_factory=list)
    fetched_incidents: list[str] = field(default_factory=list)
    fetched_incidents_by_title: list[str] = field(default_factory=list)
    main_incident: Optional[str] = None
    summary_completed: bool = False
    suggestions_number: int = 0
    latency_ms: Optional[float] = None
    llm_tokens_in: int = 0
    llm_tokens_out: int = 0
    llm_cost_usd: float = 0.0

    @property
    def itsm_status(self) -> Optional[int]:
        if not self.itsm_status_codes:
            return None
        return _effective_status(self.itsm_status_codes)

    @property
    def llm_status(self) -> Optional[int]:
        if not self.llm_status_codes:
            return None
        return _effective_status(self.llm_status_codes)

    @property
    def itsm_error(self) -> str:
        return _join_failures(self.itsm_errors)

    @property
    def llm_error(self) -> str:
        return _join_failures(self.llm_errors)

    def record_itsm_status(self, status_code: Optional[int]) -> None:
        if status_code is None:
            return
        self.itsm_status_codes.append(int(status_code))

    def record_itsm_error(self, message: Optional[str], status_code: Optional[int] = None) -> None:
        if message and message.strip():
            self.itsm_errors.append(message.strip())
        if status_code is not None:
            self.record_itsm_status(status_code)

    def record_llm_status(self, status_code: Optional[int]) -> None:
        if status_code is None:
            return
        self.llm_status_codes.append(int(status_code))

    def record_llm_error(self, message: Optional[str], status_code: Optional[int] = None) -> None:
        if message and message.strip():
            self.llm_errors.append(message.strip())
        if status_code is not None:
            self.record_llm_status(status_code)

    def record_fetched_incident(self, incident_id: Optional[str]) -> None:
        if incident_id and incident_id.strip() and incident_id.strip() not in self.fetched_incidents:
            self.fetched_incidents.append(incident_id.strip())

    def record_title_related_incident(self, incident_id: Optional[str]) -> None:
        if incident_id and incident_id.strip() and incident_id.strip() not in self.fetched_incidents_by_title:
            self.fetched_incidents_by_title.append(incident_id.strip())

    def record_llm_usage(self, tokens_in: Optional[int], tokens_out: Optional[int], cost_usd: Optional[float]) -> None:
        if tokens_in is not None:
            self.llm_tokens_in += int(tokens_in)
        if tokens_out is not None:
            self.llm_tokens_out += int(tokens_out)
        if cost_usd is not None:
            self.llm_cost_usd += float(cost_usd)

    def build_summary_payload(self) -> dict:
        return {
            "request_id": self.request_id,
            "itsm_summary": {
                "status": str(self.itsm_status) if self.itsm_status is not None else "",
                "error": self.itsm_error,
                "main_incident": self.main_incident or "",
                "fetched_incidents": list(self.fetched_incidents),
                "fetched_incidents_by_title": list(self.fetched_incidents_by_title),
                "summary": bool(self.summary_completed),
                "suggestions_number": int(self.suggestions_number),
            },
            "llm_summary": {
                "status": str(self.llm_status) if self.llm_status is not None else "",
                "error": self.llm_error,
                "tokens_in": int(self.llm_tokens_in),
                "tokens_out": int(self.llm_tokens_out),
                "cost_usd": round(float(self.llm_cost_usd), 12),
            },
            "latency_ms": round(float(self.latency_ms or 0.0), 2),
        }

    def log_event(
        self,
        level: str,
        component: str,
        status: Optional[int | str],
        error: Optional[str] = None,
        workflow: str = "incident_summary",
        latency_ms: Optional[float] = None,
    ) -> None:
        payload = {
            "request_id": self.request_id,
            "level": level.upper(),
            "component": component,
            "status": str(status) if status is not None else "",
            "error": error.strip() if error and error.strip() else "",
            "workflow": workflow,
            "latency_ms": round(float(latency_ms or 0.0), 2),
        }
        if level.upper() == "ERROR":
            logger.error(json.dumps(payload, separators=(",", ":")))
        else:
            logger.debug(json.dumps(payload, separators=(",", ":")))


def _effective_status(status_codes: Iterable[int]) -> int:
    values = [int(code) for code in status_codes if code is not None]
    if not values:
        return 200
    if any(code >= 400 for code in values):
        return max(values)
    if any(200 < code < 400 for code in values):
        return 400
    return 200


def _join_failures(messages: Iterable[str]) -> str:
    items = [str(item).strip() for item in messages if str(item).strip()]
    return " | ".join(items)


def log_request_summary() -> None:
    context = get_current_request_context()
    if context is None or _summary_emitted_var.get():
        return
    _summary_emitted_var.set(True)
    logger.info(json.dumps(context.build_summary_payload(), separators=(",", ":")))


def set_request_id(request_id: Optional[str]) -> Optional[str]:
    context = get_current_request_context()
    if context is None:
        return None
    normalized = str(request_id).strip() if request_id else context.request_id
    if normalized:
        context.request_id = normalized
    return context.request_id
