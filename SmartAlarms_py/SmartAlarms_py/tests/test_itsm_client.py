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
