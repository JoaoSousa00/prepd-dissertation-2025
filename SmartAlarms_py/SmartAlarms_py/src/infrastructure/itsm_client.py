import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Iterable, Optional

import httpx

from src.domain.incident import (
    BaseIncident,
    IncidentSourceAdapter,
    IncidentSourceUnauthorizedError,
    IncidentSourceUnavailableError,
)
from src.shared.observability import get_current_request_context
from src.shared.tracing import inject_trace_context, set_span_status_error, set_span_status_ok, start_span

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.int.gcp.bmw.cloud/nowplatform/v1"
DEFAULT_HOST = "api.int.gcp.bmw.cloud"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ItsmClientSettings:
    base_url: str = DEFAULT_BASE_URL
    host: str = DEFAULT_HOST
    authorization: str = ""
    api_key: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    related_incidents_max_same_title: int = 100
    related_incidents_recent_same_title_limit: int = 10
    related_incidents_fallback_fetch_limit: int = 100
    related_incidents_fallback_recent_limit: int = 10
    include_related_incident_comments: bool = True
    include_related_incident_work_notes: bool = True


def _parse_bool(value: Optional[str], default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def load_itsm_client_settings() -> ItsmClientSettings:
    return ItsmClientSettings(
        base_url=os.getenv("ITSM_BASE_URL", DEFAULT_BASE_URL),
        host=os.getenv("ITSM_HOST", DEFAULT_HOST),
        authorization=os.getenv("ITSM_AUTHORIZATION", ""),
        api_key=os.getenv("ITSM_API_KEY", ""),
        timeout_seconds=float(os.getenv("ITSM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
        related_incidents_max_same_title=max(
            1,
            int(os.getenv("RELATED_INCIDENTS_MAX_SAME_TITLE", "100")),
        ),
        related_incidents_recent_same_title_limit=max(
            1,
            int(os.getenv("RELATED_INCIDENTS_RECENT_SAME_TITLE_LIMIT", "10")),
        ),
        related_incidents_fallback_fetch_limit=max(
            1,
            int(os.getenv("RELATED_INCIDENTS_FALLBACK_FETCH_LIMIT", "100")),
        ),
        related_incidents_fallback_recent_limit=max(
            1,
            int(os.getenv("RELATED_INCIDENTS_FALLBACK_RECENT_LIMIT", "10")),
        ),
        include_related_incident_comments=_parse_bool(
            os.getenv("RELATED_INCIDENTS_INCLUDE_COMMENTS"),
            True,
        ),
        include_related_incident_work_notes=_parse_bool(
            os.getenv("RELATED_INCIDENTS_INCLUDE_WORK_NOTES"),
            True,
        ),
    )


class ItsmIncidentSourceAdapter(IncidentSourceAdapter):
    def __init__(
        self,
        settings: Optional[ItsmClientSettings] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._settings = settings or load_itsm_client_settings()
        self._client = httpx.Client(
            base_url=self._settings.base_url.rstrip("/"),
            timeout=self._settings.timeout_seconds,
            transport=transport,
        )

    def fetch_base_incident(self, incident_id: str) -> Optional[BaseIncident]:
        self._validate_credentials()
        context = get_current_request_context()
        started_at = time.perf_counter()
        headers = self._headers()
        inject_trace_context(headers)
        with start_span(
            "itsm.fetch_incident",
            request_id=context.request_id if context is not None else None,
            component="itsm",
            attributes={
                "operation": "fetch_incident",
                "endpoint": f"/incident/{incident_id}",
                "resource_id": incident_id,
            },
        ) as span:
            try:
                response = self._client.get(
                    f"/incident/{incident_id}",
                    headers=headers,
                )
            except httpx.HTTPError as exc:
                latency_ms = (time.perf_counter() - started_at) * 1000
                set_span_status_error(
                    span,
                    error_code="itsm_http_error",
                    error_message=str(exc),
                    latency_ms=latency_ms,
                )
                if context is not None:
                    context.record_itsm_error(f"ITSM incident source is unavailable: {exc}", 500)
                    context.log_event(
                        "ERROR",
                        "itsm",
                        500,
                        f"ITSM incident source is unavailable: {exc}",
                        latency_ms=latency_ms,
                    )
                raise IncidentSourceUnavailableError("ITSM incident source is unavailable") from exc

            latency_ms = (time.perf_counter() - started_at) * 1000
            if response.status_code >= 400:
                set_span_status_error(
                    span,
                    error_code=f"http_{response.status_code}",
                    error_message=f"ITSM returned HTTP {response.status_code}",
                    latency_ms=latency_ms,
                )
            else:
                set_span_status_ok(span, latency_ms)
            if span is not None:
                span.set_attribute("status_code", response.status_code)

        logger.debug("ITSM %s → HTTP %s", incident_id, response.status_code)
        if context is not None:
            context.record_itsm_status(response.status_code)
            context.log_event(
                "DEBUG",
                "itsm",
                response.status_code,
                "",
                latency_ms=latency_ms,
            )

        if response.status_code == 404:
            return None
        if response.status_code in {401, 403}:
            if context is not None:
                context.record_itsm_error("ITSM credentials are missing or were rejected", response.status_code)
            raise IncidentSourceUnauthorizedError(
                "ITSM credentials are missing or were rejected"
            )
        if response.status_code >= 400:
            logger.warning("ITSM returned %s for %s — body: %s", response.status_code, incident_id, response.text[:500])
            if context is not None:
                context.record_itsm_error(
                    f"ITSM incident source returned {response.status_code}",
                    response.status_code,
                )
                context.log_event(
                    "ERROR",
                    "itsm",
                    response.status_code,
                    f"ITSM incident source returned {response.status_code}",
                    latency_ms=latency_ms,
                )
            raise IncidentSourceUnavailableError(
                f"ITSM incident source returned {response.status_code}"
            )

        payload = response.json()
        logger.debug("ITSM body for %s: %s", incident_id, payload)
        record = self._extract_record(payload)
        if record is None:
            logger.warning("ITSM payload for %s could not be extracted: %s", incident_id, payload)
            if context is not None:
                context.record_itsm_error("ITSM incident payload is empty", 500)
            raise IncidentSourceUnavailableError("ITSM incident payload is empty")

        record_id = str(record.get("id") or record.get("number") or incident_id)
        short_description = record.get("shortDescription") or record.get("short_description")
        description = record.get("description")

        return BaseIncident(
            id=record_id,
            short_description=short_description,
            description=description,
            number=str(record.get("number") or record_id),
            state=record.get("state"),
            resolved_at=record.get("resolved_at") or record.get("resolvedAt"),
            close_notes=record.get("close_notes") or record.get("closeNotes"),
            closed_at=record.get("closed_at") or record.get("closedAt"),
            close_code=record.get("close_code") or record.get("closeCode"),
            hold_reason=record.get("hold_reason") or record.get("holdReason"),
            comments=self._as_string_list(record.get("comments")),
            work_notes=self._as_string_list(record.get("work_notes") or record.get("workNotes")),
            raw=record,
        )

    def fetch_same_title_incidents(self, short_description: str, limit: Optional[int] = None) -> list[BaseIncident]:
        if not short_description or not short_description.strip():
            return []
        self._validate_credentials()
        max_results = max(1, limit or self._settings.related_incidents_max_same_title)
        encoded = short_description.strip()
        query = f"short_description={encoded}"
        response = self._client.get(
            "/incident",
            params={"query": query, "limit": max_results},
            headers=self._headers(),
        )
        if response.status_code in {401, 403}:
            raise IncidentSourceUnauthorizedError("ITSM credentials are missing or were rejected")
        if response.status_code >= 400:
            logger.warning("Same-title ITSM lookup failed: %s", response.text[:500])
            return []
        payload = response.json()
        incidents: list[BaseIncident] = []
        for record in self._extract_records(payload):
            parsed = self._parse_incident_record(record)
            if parsed is not None:
                incidents.append(parsed)
        return incidents

    def fetch_recent_assignment_group_incidents(
        self,
        assignment_group: str,
        limit: Optional[int] = None,
    ) -> list[BaseIncident]:
        group_name = (assignment_group or "").strip()
        if not group_name:
            return []
        self._validate_credentials()
        max_results = max(1, limit or self._settings.related_incidents_fallback_fetch_limit)
        query = f"assignment_group={group_name}"
        response = self._client.get(
            "/incident",
            params={"query": query, "limit": max_results},
            headers=self._headers(),
        )
        if response.status_code in {401, 403}:
            raise IncidentSourceUnauthorizedError("ITSM credentials are missing or were rejected")
        if response.status_code >= 400:
            logger.warning("Assignment-group fallback ITSM lookup failed: %s", response.text[:500])
            return []
        payload = response.json()
        incidents: list[BaseIncident] = []
        for record in self._extract_records(payload):
            parsed = self._parse_incident_record(record)
            if parsed is not None:
                incidents.append(parsed)
        return incidents

    def _parse_incident_record(self, record: dict[str, Any]) -> Optional[BaseIncident]:
        record_id = str(record.get("number") or record.get("id") or "")
        if not record_id:
            return None
        return BaseIncident(
            id=record_id,
            short_description=record.get("shortDescription") or record.get("short_description"),
            description=record.get("description"),
            number=record.get("number") or record_id,
            state=record.get("state"),
            resolved_at=record.get("resolved_at") or record.get("resolvedAt"),
            close_notes=record.get("close_notes") or record.get("closeNotes"),
            closed_at=record.get("closed_at") or record.get("closedAt"),
            close_code=record.get("close_code") or record.get("closeCode"),
            hold_reason=record.get("hold_reason") or record.get("holdReason"),
            comments=self._as_string_list(record.get("comments")),
            work_notes=self._as_string_list(record.get("work_notes") or record.get("workNotes")),
            raw=record,
        )

    def find_related_incidents(self, incident: BaseIncident, include_main_id: bool = False) -> list[str]:
        if incident.raw is None:
            return []
        return self._extract_related_incident_numbers(incident.raw, incident.id if not include_main_id else None)

    def fetch_related_incident_details(self, incident_ids: Iterable[str]) -> list[BaseIncident]:
        concrete_ids = [candidate.strip() for candidate in incident_ids if candidate and candidate.strip()]
        if not concrete_ids:
            return []
        unique_ids = list(dict.fromkeys((candidate.upper() for candidate in concrete_ids)))
        headers = self._headers()
        results: list[BaseIncident] = []

        def _fetch_one(incident_id: str) -> Optional[BaseIncident]:
            response = self._client.get(f"/incident/{incident_id}", headers=headers)
            if response.status_code == 404:
                return None
            if response.status_code in {401, 403}:
                raise IncidentSourceUnauthorizedError("ITSM credentials are missing or were rejected")
            if response.status_code >= 400:
                logger.warning("ITSM fetch for %s failed: %s", incident_id, response.text[:500])
                return None
            payload = response.json()
            record = self._extract_record(payload)
            if record is None:
                return None
            return BaseIncident(
                id=str(record.get("id") or record.get("number") or incident_id),
                short_description=record.get("shortDescription") or record.get("short_description"),
                description=record.get("description"),
                number=str(record.get("number") or record.get("id") or incident_id),
                state=record.get("state"),
                resolved_at=record.get("resolved_at") or record.get("resolvedAt"),
                close_notes=record.get("close_notes") or record.get("closeNotes"),
                closed_at=record.get("closed_at") or record.get("closedAt"),
                close_code=record.get("close_code") or record.get("closeCode"),
                hold_reason=record.get("hold_reason") or record.get("holdReason"),
                comments=self._as_string_list(record.get("comments")),
                work_notes=self._as_string_list(record.get("work_notes") or record.get("workNotes")),
                raw=record,
            )

        with ThreadPoolExecutor(max_workers=min(8, len(unique_ids))) as executor:
            futures = [executor.submit(_fetch_one, incident_id) for incident_id in unique_ids]
            for future in futures:
                incident = future.result()
                if incident is not None:
                    results.append(incident)
        return results

    @staticmethod
    def _extract_related_incident_numbers(payload: dict[str, Any], excluded_id: Optional[str] = None) -> list[str]:
        values: list[str] = []
        if not isinstance(payload, dict):
            return values
        for key in ("parent_incident", "description", "close_notes", "comments", "work_notes", "hold_reason"):
            item = payload.get(key)
            if item is None:
                continue
            if isinstance(item, list):
                combined = "\n".join(str(part) for part in item)
            elif isinstance(item, dict):
                combined = str(item.get("number") or item.get("sys_id") or item.get("value") or item)
            else:
                combined = str(item)
            values.append(combined)
        if isinstance(payload.get("parent"), list):
            for item in payload["parent"]:
                if isinstance(item, dict):
                    values.append(str(item.get("number") or item.get("value") or item.get("sys_id") or ""))
        matches = []
        for text in values:
            matches.extend(re.findall(r"INC[0-9]+", text, flags=re.IGNORECASE))
        normalized = [match.upper() for match in matches]
        if excluded_id:
            normalized = [value for value in normalized if value.upper() != excluded_id.upper()]
        return list(dict.fromkeys(normalized))

    @staticmethod
    def _as_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        if isinstance(value, str):
            return [value]
        return [str(value)]

    @staticmethod
    def _extract_records(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, list):
                return [item for item in result if isinstance(item, dict)]
            if isinstance(result, dict):
                return [result]
        elif isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        return []

    def _validate_credentials(self) -> None:
        if not self._settings.authorization or not self._settings.api_key:
            raise IncidentSourceUnauthorizedError(
                "ITSM credentials are missing. Set ITSM_AUTHORIZATION and ITSM_API_KEY."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Host": self._settings.host,
        }
        if self._settings.authorization:
            headers["Authorization"] = self._settings.authorization
        if self._settings.api_key:
            headers["x-apikey"] = self._settings.api_key
        return headers

    @staticmethod
    def _extract_record(payload: Any) -> Optional[dict[str, Any]]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                return result
            if isinstance(result, list) and result and isinstance(result[0], dict):
                return result[0]
            return payload
        return None
