import json

from src.shared.observability import RequestLogContext, bind_request_context, log_request_summary


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
