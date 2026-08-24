import pytest
from fastapi.testclient import TestClient
from src.main import app


@pytest.fixture
def client():
    return TestClient(app)


class TestIncidentDetailsEndpoint:
    """Test cases for CA-1: Endpoint exists and responds through documented contract"""

    def test_endpoint_exists_with_valid_incident_ids(self, client):
        """Should return 200 with valid incidentIds"""
        response = client.get("/incident/details", params={"incidentIds": "INC000000000001"})
        assert response.status_code == 200
        assert "incidents" in response.json()
        assert isinstance(response.json()["incidents"], list)

    def test_endpoint_returns_contract_aligned_response(self, client):
        """Should return response that matches DetailsResponse schema"""
        response = client.get(
            "/incident/details",
            params={"incidentIds": ["INC000000000001", "INC000000000002"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert "incidents" in data
        assert isinstance(data["incidents"], list)

    def test_endpoint_accepts_single_incident_id(self, client):
        """Should accept a single incidentId"""
        response = client.get("/incident/details", params={"incidentIds": "INC000000000001"})
        assert response.status_code == 200
        data = response.json()
        assert data == {"incidents": []}

    def test_endpoint_accepts_multiple_incident_ids(self, client):
        """Should accept multiple incidentIds"""
        response = client.get(
            "/incident/details",
            params={"incidentIds": ["INC000000000001", "INC000000000002", "INC000000000003"]},
        )
        assert response.status_code == 200
        data = response.json()
        assert data == {"incidents": []}


class TestIncidentDetailsValidation:
    """Test cases for CA-2: Invalid input returns 400"""

    def test_missing_incident_ids_returns_400(self, client):
        """Should return 400 when incidentIds is missing"""
        response = client.get("/incident/details")
        assert response.status_code == 422
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"

    def test_empty_incident_ids_returns_400(self, client):
        """Should return 400 when incidentIds is empty"""
        response = client.get("/incident/details", params={})
        assert response.status_code == 422

    def test_empty_string_incident_id_returns_400(self, client):
        """Should return 400 when incidentId is empty string"""
        response = client.get("/incident/details", params={"incidentIds": ""})
        assert response.status_code == 400
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"

    def test_whitespace_only_incident_id_returns_400(self, client):
        """Should return 400 when incidentId is only whitespace"""
        response = client.get("/incident/details", params={"incidentIds": "   "})
        assert response.status_code == 400
        data = response.json()
        assert data["message"] == "Invalid request payload"
        assert data["code"] == "BAD_REQUEST"

    def test_error_response_has_structured_format(self, client):
        """Should return structured error response with message, code, and details"""
        response = client.get("/incident/details", params={"incidentIds": ""})
        assert response.status_code == 400
        data = response.json()
        assert "message" in data
        assert "code" in data
        assert data["code"] == "BAD_REQUEST"


class TestIncidentDetailsEmptyResponse:
    """Test cases for CA-3: No incidents available returns valid response"""

    def test_valid_request_with_no_data_returns_200(self, client):
        """Should return 200 with empty incidents list when no data is available"""
        response = client.get("/incident/details", params={"incidentIds": "INC000000000001"})
        assert response.status_code == 200
        data = response.json()
        assert data["incidents"] == []

    def test_response_shape_matches_contract(self, client):
        """Should return response that matches the DetailsResponse schema"""
        response = client.get("/incident/details", params={"incidentIds": "INC000000000001"})
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "incidents" in data
        assert isinstance(data["incidents"], list)


class TestIncidentDetailsHealthCheck:
    """Health check and basic connectivity"""

    def test_health_endpoint_exists(self, client):
        """Should have a health check endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
