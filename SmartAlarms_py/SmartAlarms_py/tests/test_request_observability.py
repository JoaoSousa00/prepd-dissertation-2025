import json

from src.shared import tracing as tracing_module
from src.shared.observability import RequestLogContext, bind_request_context, log_request_summary
from src.shared.tracing import (
    get_langfuse_config,
    is_langfuse_configured,
    log_langfuse_startup_status,
    reset_tracing_state_for_tests,
)


def test_request_log_summary_formats_required_payload(caplog):
    with bind_request_context(RequestLogContext(request_id="req-123")) as context:
        context.record_itsm_status(200)
        context.record_itsm_status(302)
        context.record_itsm_error("First ITSM error", 400)
        context.record_itsm_error("Second ITSM error", 500)
        context.record_llm_status(200)
        context.record_llm_status(302)
        context.record_llm_error("LLM failed", 400)
        context.record_llm_error("LLM retry failed", 503)
        context.record_llm_usage(tokens_in=333, tokens_out=3000, cost_usd=0.0333213)
        context.main_incident = "INC001"
        context.record_fetched_incident("INC002")
        context.record_fetched_incident("INC003")
        context.record_title_related_incident("INC003")
        context.record_title_related_incident("INC004")
        context.suggestions_number = 7
        context.latency_ms = 40000.23
        context.summary_completed = True

        with caplog.at_level("INFO", logger="smartalarms.observability"):
            log_request_summary()

    assert len(caplog.records) == 1
    payload = json.loads(caplog.records[0].message)
    assert payload["request_id"] == "req-123"
    assert payload["itsm_summary"]["status"] == "500"
    assert payload["itsm_summary"]["error"] == "First ITSM error | Second ITSM error"
    assert payload["itsm_summary"]["main_incident"] == "INC001"
    assert payload["itsm_summary"]["fetched_incidents"] == ["INC002", "INC003"]
    assert payload["itsm_summary"]["fetched_incidents_by_title"] == ["INC003", "INC004"]
    assert payload["itsm_summary"]["summary"] is True
    assert payload["itsm_summary"]["suggestions_number"] == 7
    assert payload["llm_summary"]["status"] == "503"
    assert payload["llm_summary"]["error"] == "LLM failed | LLM retry failed"
    assert payload["llm_summary"]["tokens_in"] == 333
    assert payload["llm_summary"]["tokens_out"] == 3000
    assert payload["llm_summary"]["cost_usd"] == 0.0333213
    assert payload["latency_ms"] == 40000.23


def test_request_log_context_keeps_worst_status_for_200_300_range():
    context = RequestLogContext(request_id="req-456")
    context.record_itsm_status(200)
    context.record_itsm_status(302)
    context.record_llm_status(200)
    context.record_llm_status(204)

    assert context.itsm_status == 400
    assert context.llm_status == 400


def test_request_summary_false_when_itm_request_fails():
    with bind_request_context(RequestLogContext(request_id="req-789")) as context:
        context.record_itsm_error("ITSM credentials are missing or were rejected", 401)
        context.main_incident = "INC001"
        context.summary_completed = False

        payload = context.build_summary_payload()
        assert payload["itsm_summary"]["summary"] is False
        assert payload["itsm_summary"]["status"] == "401"
        assert payload["llm_summary"]["status"] == ""


def test_start_span_sets_langfuse_trace_and_observation_names(monkeypatch):
    class FakeSpan:
        def __init__(self):
            self.attributes = {}

        def set_attribute(self, key, value):
            self.attributes[key] = value

    class FakeScope:
        def __init__(self, span):
            self.span = span

        def __enter__(self):
            return self.span

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeTracer:
        def start_as_current_span(self, _name):
            return FakeScope(FakeSpan())

    monkeypatch.setattr(tracing_module, "_TRACING_ACTIVE", True)
    monkeypatch.setattr(tracing_module, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(tracing_module.trace, "get_tracer", lambda _name: FakeTracer())

    with tracing_module.start_span(
        "request.analysis",
        request_id="req-123",
        workflow="incident_summary",
        component="request",
    ) as request_span:
        assert request_span.attributes["langfuse.trace.name"] == "incident_summary"
        assert request_span.attributes["langfuse.observation.name"] == "request.analysis"
        assert request_span.attributes["langfuse.observation.type"] == "span"

    with tracing_module.start_span(
        "llm.complete",
        request_id="req-123",
        workflow="incident_summary",
        component="llm",
        attributes={"langfuse.observation.type": "generation"},
    ) as generation_span:
        assert generation_span.attributes["langfuse.trace.name"] == "incident_summary"
        assert generation_span.attributes["langfuse.observation.name"] == "llm.complete"
        assert generation_span.attributes["langfuse.observation.type"] == "generation"


def test_langfuse_config_enables_from_public_and_secret_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.setenv("TRACING_ENABLED", "true")

    config = get_langfuse_config()

    assert config["enabled"] is True
    assert config["base_url"] == "https://langfuse.example.com"
    assert config["public_key"] == "pk-test"
    assert config["secret_key"] == "sk-test"
    assert config["otlp_endpoint"] == "https://langfuse.example.com/api/public/otel/v1/traces"
    assert is_langfuse_configured() is True


def test_langfuse_config_works_without_otlp_endpoint(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.delenv("TRACING_ENABLED", raising=False)

    config = get_langfuse_config()

    assert config["enabled"] is True
    assert config["otlp_endpoint"] == "https://langfuse.example.com/api/public/otel/v1/traces"
    assert is_langfuse_configured() is True


def test_langfuse_startup_logs_connected_status(monkeypatch, caplog):
    reset_tracing_state_for_tests()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.setenv("TRACING_ENABLED", "true")

    with caplog.at_level("DEBUG", logger="smartalarms.tracing"):
        log_langfuse_startup_status()

    payloads = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    startup_payload = next(item for item in payloads if item.get("event") == "langfuse_startup")
    assert startup_payload["enabled"] is True
    assert startup_payload["status"] in {"connected", "not_connected"}


def test_langfuse_startup_logs_not_connected_status(monkeypatch, caplog):
    reset_tracing_state_for_tests()
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.setenv("TRACING_ENABLED", "true")

    with caplog.at_level("DEBUG", logger="smartalarms.tracing"):
        log_langfuse_startup_status()

    payloads = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    startup_payload = next(item for item in payloads if item.get("event") == "langfuse_startup")
    assert startup_payload["status"] == "not_connected"
    assert startup_payload["reason"] == "missing_langfuse_configuration"


def test_langfuse_startup_emits_debug_diagnostics(monkeypatch, caplog):
    reset_tracing_state_for_tests()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://langfuse.example.com")
    monkeypatch.setenv("TRACING_ENABLED", "true")

    with caplog.at_level("DEBUG", logger="smartalarms.tracing"):
        log_langfuse_startup_status()

    payloads = [json.loads(record.message) for record in caplog.records if record.message.startswith("{")]
    debug_payload = next(item for item in payloads if item.get("event") == "langfuse_startup_debug")
    startup_payload = next(item for item in payloads if item.get("event") == "langfuse_startup")

    assert debug_payload["tracing_enabled_env"] is True
    assert debug_payload["effective_enabled"] is True
    assert debug_payload["has_public_key"] is True
    assert debug_payload["has_secret_key"] is False
    assert debug_payload["has_base_url"] is True
    assert startup_payload["status"] == "not_connected"
    assert "LANGFUSE_SECRET_KEY" in startup_payload["missing_fields"]
