import httpx
import pytest
from fastapi.testclient import TestClient

from src.application.incident_fetching import IncidentFetchingService
from src.infrastructure.itsm_client import ItsmClientSettings, ItsmIncidentSourceAdapter
from src.main import app


def build_itsm_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["accept"] == "application/json"
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.headers["x-apikey"] == "test-api-key"
        assert request.headers["host"] == "api.int.gcp.bmw.cloud"

        incident_id = request.url.path.rsplit("/", 1)[-1]
        if incident_id == "INC999999999999":
            return httpx.Response(404, json={"result": None})
        if incident_id == "INC000000000002":
            return httpx.Response(
                200,
                json={
                    "result": {
                        "number": "INC000000000002",
                        "shortDescription": "Checkout timeout surge",
                        "description": "Checkout requests timed out while calling downstream services.",
                    }
                },
            )
        if incident_id == "INC000000000003":
            raise httpx.ConnectError("connection failed", request=request)
        return httpx.Response(
            200,
            json={
                "result": {
                    "number": incident_id,
                    "shortDescription": "Billing API latency spike",
                    "description": "Billing API requests exceeded the expected latency threshold.",
                }
            },
        )

    return httpx.MockTransport(handler)


@pytest.fixture
def client():
    transport = build_itsm_transport()
    adapter = ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            authorization="Bearer test-token",
            api_key="test-api-key",
            host="api.int.gcp.bmw.cloud",
        ),
        transport=transport,
    )
    app.state.incident_fetching_service = IncidentFetchingService(adapter)
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_fetching_service


@pytest.fixture
def unauthorized_client():
    adapter = ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            authorization="",
            api_key="",
            host="api.int.gcp.bmw.cloud",
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    app.state.incident_fetching_service = IncidentFetchingService(adapter)
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_fetching_service


class TestIncidentDetailsEndpoint:
    def test_endpoint_exists_with_valid_incident_ids(self, client):
        response = client.get("/incident/details", params={"incidentIds": "INC000000000001"})
        assert response.status_code == 200
        assert response.json() == {
            "incidents": [
                {
                    "id": "INC000000000001",
                    "shortDescription": "Billing API latency spike",
                    "description": "Billing API requests exceeded the expected latency threshold.",
                }
            ]
        }

    def test_endpoint_returns_contract_aligned_response(self, client):
        response = client.get(
            "/incident/details",
            params={"incidentIds": ["INC000000000001", "INC000000000002"]},
        )
        assert response.status_code == 200
        assert response.json() == {
            "incidents": [
                {
                    "id": "INC000000000001",
                    "shortDescription": "Billing API latency spike",
                    "description": "Billing API requests exceeded the expected latency threshold.",
                },
                {
                    "id": "INC000000000002",
                    "shortDescription": "Checkout timeout surge",
                    "description": "Checkout requests timed out while calling downstream services.",
                },
            ]
        }

    def test_endpoint_accepts_multiple_incident_ids(self, client):
        response = client.get(
            "/incident/details",
            params={"incidentIds": ["INC000000000001", "INC000000000002", "INC000000000003"]},
        )
        assert response.status_code == 200
        assert len(response.json()["incidents"]) == 2

    def test_missing_incident_id_is_skipped(self, client):
        response = client.get(
            "/incident/details",
            params={"incidentIds": ["INC000000000001", "INC999999999999"]},
        )
        assert response.status_code == 200
        assert response.json() == {
            "incidents": [
                {
                    "id": "INC000000000001",
                    "shortDescription": "Billing API latency spike",
                    "description": "Billing API requests exceeded the expected latency threshold.",
                }
            ]
        }

    def test_missing_credentials_return_401(self, unauthorized_client):
        response = unauthorized_client.get(
            "/incident/details", params={"incidentIds": "INC000000000001"}
        )
        assert response.status_code == 401
        assert response.json() == {
            "message": "ITSM credentials are missing. Set ITSM_AUTHORIZATION and ITSM_API_KEY.",
            "code": "UNAUTHORIZED",
            "details": [],
        }


class TestIncidentDetailsValidation:
    def test_missing_incident_ids_returns_400(self, client):
        response = client.get("/incident/details")
        assert response.status_code == 400
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"

    def test_empty_string_incident_id_returns_400(self, client):
        response = client.get("/incident/details", params={"incidentIds": ""})
        assert response.status_code == 400
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"

    def test_whitespace_only_incident_id_returns_400(self, client):
        response = client.get("/incident/details", params={"incidentIds": "   "})
        assert response.status_code == 400
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"


class TestIncidentDetailsEmptyResponse:
    def test_valid_request_with_no_data_returns_200(self, client):
        response = client.get("/incident/details", params={"incidentIds": "INC999999999999"})
        assert response.status_code == 200
        assert response.json() == {"incidents": []}


class TestIncidentDetailsHealthCheck:
    def test_health_endpoint_exists(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
