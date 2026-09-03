import base64
import json
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, Optional

logger = logging.getLogger("smartalarms.tracing")

try:
    from opentelemetry import propagate, trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via runtime fallback
    propagate = None
    trace = None
    OTLPSpanExporter = None
    Resource = None
    TracerProvider = None
    BatchSpanProcessor = None
    Status = None
    StatusCode = None
    _OTEL_AVAILABLE = False

_TRACING_INITIALIZED = False
_TRACING_ACTIVE = False
_TRACING_INIT_ERROR: Optional[str] = None

DEFAULT_WORKFLOW = "incident_summary"
DEFAULT_OTEL_SERVICE_NAME = "smartalarms-api"


def _as_bool(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _langfuse_otlp_endpoint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if not normalized:
        return ""
    return f"{normalized}/api/public/otel/v1/traces"


def get_langfuse_config() -> dict[str, Any]:
    tracing_enabled = _as_bool(os.getenv("TRACING_ENABLED"))
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    base_url = os.getenv("LANGFUSE_BASE_URL", "").strip()
    otlp_endpoint = _langfuse_otlp_endpoint(base_url)
    service_name = os.getenv("OTEL_SERVICE_NAME", DEFAULT_OTEL_SERVICE_NAME).strip() or DEFAULT_OTEL_SERVICE_NAME

    return {
        "enabled": tracing_enabled or bool(public_key and secret_key and base_url),
        "tracing_enabled_env": tracing_enabled,
        "base_url": base_url,
        "public_key": public_key,
        "secret_key": secret_key,
        "otlp_endpoint": otlp_endpoint,
        "service_name": service_name,
    }


def is_langfuse_configured() -> bool:
    config = get_langfuse_config()
    return bool(
        config["enabled"]
        and config["public_key"]
        and config["secret_key"]
        and config["base_url"]
        and config["otlp_endpoint"]
    )


def _build_otlp_auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _sanitize_attribute_value(value: Any) -> str | bool | int | float:
    if isinstance(value, (str, bool, int, float)):
        return value
    return str(value)


def _set_span_attributes(span: Any, attributes: dict[str, Any]) -> None:
    for key, value in attributes.items():
        if value is None:
            continue
        span.set_attribute(key, _sanitize_attribute_value(value))


def initialize_tracing() -> bool:
    global _TRACING_INITIALIZED, _TRACING_ACTIVE, _TRACING_INIT_ERROR
    if _TRACING_INITIALIZED:
        return _TRACING_ACTIVE

    _TRACING_INITIALIZED = True
    config = get_langfuse_config()

    if not config["enabled"]:
        _TRACING_ACTIVE = False
        return False

    if not (config["public_key"] and config["secret_key"] and config["base_url"]):
        _TRACING_INIT_ERROR = "missing_langfuse_configuration"
        _TRACING_ACTIVE = False
        return False

    if not _OTEL_AVAILABLE:
        _TRACING_INIT_ERROR = "opentelemetry_dependencies_missing"
        _TRACING_ACTIVE = False
        return False

    try:
        existing_provider = trace.get_tracer_provider()
        if existing_provider.__class__.__name__ != "ProxyTracerProvider":
            _TRACING_ACTIVE = True
            return True

        resource = Resource.create(
            {
                "service.name": config["service_name"],
                "deployment.environment": os.getenv("SERVER_ENV", "unknown"),
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(
            endpoint=config["otlp_endpoint"],
            headers={
                "Authorization": _build_otlp_auth_header(config["public_key"], config["secret_key"]),
                "x-langfuse-ingestion-version": "4",
            },
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _TRACING_ACTIVE = True
        return True
    except Exception as exc:  # pragma: no cover - hard to deterministically trigger in unit tests
        _TRACING_INIT_ERROR = str(exc)
        _TRACING_ACTIVE = False
        logger.error("Langfuse tracing initialization failed: %s", exc)
        return False


def is_tracing_active() -> bool:
    return bool(_TRACING_ACTIVE)


def reset_tracing_state_for_tests() -> None:
    global _TRACING_INITIALIZED, _TRACING_ACTIVE, _TRACING_INIT_ERROR
    _TRACING_INITIALIZED = False
    _TRACING_ACTIVE = False
    _TRACING_INIT_ERROR = None


@contextmanager
def start_span(
    span_name: str,
    *,
    request_id: Optional[str] = None,
    workflow: str = DEFAULT_WORKFLOW,
    component: Optional[str] = None,
    attributes: Optional[dict[str, Any]] = None,
) -> Iterator[Any]:
    if not _TRACING_ACTIVE or not _OTEL_AVAILABLE:
        yield None
        return

    tracer = trace.get_tracer("smartalarms")
    with tracer.start_as_current_span(span_name) as span:
        safe_component = component or span_name.split(".", 1)[0]
        safe_workflow = workflow or DEFAULT_WORKFLOW
        langfuse_attrs = {
            "langfuse.observation.name": span_name,
            "langfuse.observation.type": "span",
            "langfuse.trace.name": safe_workflow,
            "request_id": request_id or "",
            "workflow": safe_workflow,
            "component": safe_component,
        }
        if attributes:
            langfuse_attrs.update(attributes)
        if "langfuse.observation.type" not in langfuse_attrs:
            langfuse_attrs["langfuse.observation.type"] = "span"
        _set_span_attributes(span, langfuse_attrs)
        yield span


def set_span_status_ok(span: Any, latency_ms: float) -> None:
    if span is None or not _TRACING_ACTIVE or not _OTEL_AVAILABLE:
        return
    span.set_status(Status(StatusCode.OK))
    _set_span_attributes(
        span,
        {
            "status": "ok",
            "latency_ms": round(float(latency_ms), 2),
        },
    )


def set_span_status_error(span: Any, *, error_code: str, error_message: str, latency_ms: float) -> None:
    if span is None or not _TRACING_ACTIVE or not _OTEL_AVAILABLE:
        return
    span.set_status(Status(StatusCode.ERROR))
    span.record_exception(Exception(error_message))
    _set_span_attributes(
        span,
        {
            "status": "error",
            "error.code": error_code,
            "error.message": error_message,
            "latency_ms": round(float(latency_ms), 2),
        },
    )


def inject_trace_context(headers: dict[str, str]) -> None:
    if not _TRACING_ACTIVE or not _OTEL_AVAILABLE:
        return
    propagate.inject(headers)


def log_langfuse_startup_status() -> None:
    config = get_langfuse_config()
    initialized = initialize_tracing()
    configured = is_langfuse_configured()

    missing_fields: list[str] = []
    if not config["public_key"]:
        missing_fields.append("LANGFUSE_PUBLIC_KEY")
    if not config["secret_key"]:
        missing_fields.append("LANGFUSE_SECRET_KEY")
    if not config["base_url"]:
        missing_fields.append("LANGFUSE_BASE_URL")

    logger.debug(
        json.dumps(
            {
                "event": "langfuse_startup_debug",
                "tracing_enabled_env": bool(config["tracing_enabled_env"]),
                "effective_enabled": bool(config["enabled"]),
                "otel_available": bool(_OTEL_AVAILABLE),
                "initialized": bool(initialized),
                "configured": bool(configured),
                "has_public_key": bool(config["public_key"]),
                "has_secret_key": bool(config["secret_key"]),
                "has_base_url": bool(config["base_url"]),
                "otlp_endpoint": config["otlp_endpoint"],
                "service_name": config["service_name"],
            },
            separators=(",", ":"),
        )
    )

    payload = {
        "event": "langfuse_startup",
        "enabled": bool(config["enabled"]),
        "status": "connected" if initialized else "not_connected",
        "base_url": config["base_url"],
        "otlp_endpoint": config["otlp_endpoint"],
    }
    if not initialized:
        if not config["enabled"]:
            payload["reason"] = "tracing_disabled"
        elif missing_fields:
            payload["reason"] = "missing_langfuse_configuration"
            payload["missing_fields"] = missing_fields
        elif not _OTEL_AVAILABLE:
            payload["reason"] = "opentelemetry_dependencies_missing"
        else:
            payload["reason"] = "tracing_initialization_failed"
            if _TRACING_INIT_ERROR:
                payload["error"] = _TRACING_INIT_ERROR
        logger.error(json.dumps(payload, separators=(",", ":")))
        return

    logger.info(json.dumps(payload, separators=(",", ":")))
