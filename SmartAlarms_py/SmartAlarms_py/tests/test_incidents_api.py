import httpx
import pytest
from fastapi.testclient import TestClient

from src.application.incident_details import IncidentDetailsService
from src.application.incident_fetching import IncidentFetchingService
from src.domain.llm import IncidentEnrichment, LlmGatewayUnavailableError, LlmSummary, MitigationSuggestion
from src.infrastructure.itsm_client import ItsmClientSettings, ItsmIncidentSourceAdapter
from src.main import app

AUTHORIZED_HEADER = "test-authorization"
AUTHORIZED_API_KEY = "test-api-key"
AUTHORIZED_HOST = "api.int.gcp.bmw.cloud"


def build_itsm_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["accept"] == "application/json"
        assert request.headers["authorization"] == AUTHORIZED_HEADER
        assert request.headers["x-apikey"] == AUTHORIZED_API_KEY
        assert request.headers["host"] == AUTHORIZED_HOST

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


def build_authorized_adapter():
    return ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            authorization=AUTHORIZED_HEADER,
            api_key=AUTHORIZED_API_KEY,
            host=AUTHORIZED_HOST,
        ),
        transport=build_itsm_transport(),
    )


@pytest.fixture
def client():
    app.state.incident_details_service = IncidentDetailsService(
        IncidentFetchingService(build_authorized_adapter())
    )
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_details_service


@pytest.fixture
def unauthorized_client():
    adapter = ItsmIncidentSourceAdapter(
        settings=ItsmClientSettings(
            authorization="",
            api_key="",
            host=AUTHORIZED_HOST,
        ),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})),
    )
    app.state.incident_details_service = IncidentDetailsService(
        IncidentFetchingService(adapter)
    )
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_details_service


class FakeLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None):
        return IncidentEnrichment(
            summary=LlmSummary(text=f"Summary for {incident_id}"),
            related_incidents=["INC000000000111", "INC000000000222"],
            mitigation_suggestions=[
                MitigationSuggestion(
                    suggestion="Restart impacted worker pods",
                    related_incidents=["INC000000000111"],
                    related_log_ids=["txn-1"],
                )
            ],
        )


class FailingLlmGateway:
    def enrich_incident(self, incident_id, short_description, description, max_tokens=None):
        raise LlmGatewayUnavailableError("gateway unavailable")


@pytest.fixture
def enriched_client():
    app.state.incident_details_service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(build_authorized_adapter()),
        llm_gateway=FakeLlmGateway(),
    )
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_details_service


@pytest.fixture
def failing_llm_client():
    app.state.incident_details_service = IncidentDetailsService(
        incident_fetching_service=IncidentFetchingService(build_authorized_adapter()),
        llm_gateway=FailingLlmGateway(),
    )
    with TestClient(app) as test_client:
        yield test_client
    del app.state.incident_details_service


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


class TestIncidentDetailsLlmEnrichment:
    def test_returns_llm_enrichment_when_available(self, enriched_client):
        response = enriched_client.get(
            "/incident/details", params={"incidentIds": "INC000000000001"}
        )
        assert response.status_code == 200
        assert response.json() == {
            "incidents": [
                {
                    "id": "INC000000000001",
                    "shortDescription": "Billing API latency spike",
                    "description": "Billing API requests exceeded the expected latency threshold.",
                    "summary": "Summary for INC000000000001",
                    "relatedIncidents": ["INC000000000111", "INC000000000222"],
                    "resolutionSuggestions": [
                        {
                            "suggestion": "Restart impacted worker pods",
                            "relatedIncidents": ["INC000000000111"],
                            "relatedLogIds": ["txn-1"],
                        }
                    ],
                }
            ]
        }

    def test_returns_base_data_when_llm_fails(self, failing_llm_client):
        response = failing_llm_client.get(
            "/incident/details", params={"incidentIds": "INC000000000001"}
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


class TestIncidentDetailsHealthCheck:
    def test_health_endpoint_exists(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
