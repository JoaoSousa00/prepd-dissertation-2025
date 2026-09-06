import httpx
import pytest

from src.domain.incident import IncidentSourceUnauthorizedError, IncidentSourceUnavailableError
from src.infrastructure.itsm_client import ItsmClientSettings, ItsmIncidentSourceAdapter


def make_adapter(handler):
    transport = httpx.MockTransport(handler)
    return ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            base_url="https://api.int.gcp.bmw.cloud/nowplatform/v1",
            host="api.int.gcp.bmw.cloud",
            authorization="Bearer test-token",
            api_key="test-api-key",
        ),
        transport=transport,
    )


def test_fetch_base_incident_maps_top_level_payload():
    adapter = make_adapter(
        lambda request: httpx.Response(
            200,
            json={
                "id": "INC000000000001",
                "shortDescription": "Billing API latency spike",
                "description": "Billing API requests exceeded the expected latency threshold.",
            },
        )
    )

    incident = adapter.fetch_base_incident("INC000000000001")

    assert incident is not None
    assert incident.id == "INC000000000001"
    assert incident.short_description == "Billing API latency spike"
    assert incident.description == "Billing API requests exceeded the expected latency threshold."


def test_fetch_base_incident_maps_nested_result_payload():
    adapter = make_adapter(
        lambda request: httpx.Response(
            200,
            json={
                "result": {
                    "number": "INC000000000002",
                    "shortDescription": "Checkout timeout surge",
                    "description": "Checkout requests timed out while calling downstream services.",
                }
            },
        )
    )

    incident = adapter.fetch_base_incident("INC000000000002")

    assert incident is not None
    assert incident.id == "INC000000000002"
    assert incident.short_description == "Checkout timeout surge"
    assert incident.description == "Checkout requests timed out while calling downstream services."


def test_fetch_base_incident_returns_none_for_missing_record():
    adapter = make_adapter(lambda request: httpx.Response(404, json={"result": None}))

    assert adapter.fetch_base_incident("INC999999999999") is None


def test_fetch_base_incident_raises_for_unavailable_source():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    adapter = make_adapter(handler)

    with pytest.raises(IncidentSourceUnavailableError):
        adapter.fetch_base_incident("INC000000000003")


def test_fetch_base_incident_raises_for_missing_credentials():
    adapter = ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            base_url="https://api.int.gcp.bmw.cloud/nowplatform/v1",
            host="api.int.gcp.bmw.cloud",
            authorization="",
            api_key="",
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )

    with pytest.raises(IncidentSourceUnauthorizedError):
        adapter.fetch_base_incident("INC000000000004")


def test_fetch_base_incident_raises_for_rejected_credentials():
    adapter = make_adapter(lambda request: httpx.Response(401, json={"message": "Unauthorized"}))

    with pytest.raises(IncidentSourceUnauthorizedError):
        adapter.fetch_base_incident("INC000000000005")


def test_fetch_base_incident_injects_traceparent_header():
    captured_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_headers.update(dict(request.headers))
        return httpx.Response(
            200,
            json={
                "id": "INC000000000001",
                "shortDescription": "Billing API latency spike",
                "description": "Billing API requests exceeded the expected latency threshold.",
            },
        )

    adapter = make_adapter(handler)

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "src.infrastructure.itsm_client.inject_trace_context",
            lambda headers: headers.__setitem__("traceparent", "00-test"),
        )
        adapter.fetch_base_incident("INC000000000001")

    assert captured_headers["traceparent"] == "00-test"


def test_fetch_same_title_incidents_uses_default_fetch_limit_and_maps_resolved_at():
    captured_query_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_query_params["query"] = request.url.params.get("query")
        captured_query_params["limit"] = request.url.params.get("limit")
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "number": "INC000000000010",
                        "short_description": "Billing API latency spike",
                        "description": "Historical incident record.",
                        "resolved_at": "2026-09-05T10:20:00Z",
                    }
                ]
            },
        )

    adapter = make_adapter(handler)
    incidents = adapter.fetch_same_title_incidents("Billing API latency spike")

    assert captured_query_params["query"] == "short_description=Billing API latency spike"
    assert captured_query_params["limit"] == "100"
    assert len(incidents) == 1
    assert incidents[0].resolved_at == "2026-09-05T10:20:00Z"


def test_fetch_recent_assignment_group_incidents_uses_assignment_group_query():
    captured_query_params = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_query_params["query"] = request.url.params.get("query")
        captured_query_params["limit"] = request.url.params.get("limit")
        return httpx.Response(
            200,
            json={
                "result": [
                    {
                        "number": "INC000000000020",
                        "short_description": "API feed delay",
                        "assignment_group": {"name": "FT_LOS-CTW-Force-Devopsteam"},
                        "resolved_at": "2026-09-05T15:00:00Z",
                    }
                ]
            },
        )

    adapter = make_adapter(handler)
    incidents = adapter.fetch_recent_assignment_group_incidents("FT_LOS-CTW-Force-Devopsteam", limit=25)

    assert captured_query_params["query"] == "assignment_group=FT_LOS-CTW-Force-Devopsteam"
    assert captured_query_params["limit"] == "25"
    assert len(incidents) == 1
    assert incidents[0].number == "INC000000000020"
    assert incidents[0].resolved_at == "2026-09-05T15:00:00Z"
