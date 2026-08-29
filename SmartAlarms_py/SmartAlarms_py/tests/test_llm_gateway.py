import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.domain.llm import (
    IncidentEnrichment,
    LlmGatewayConfigurationError,
    LlmGatewayDisabledError,
    LlmGatewayUnavailableError,
    LlmSummary,
    MitigationSuggestion,
)
from src.infrastructure.llm_config import LlmGatewaySettings
from src.infrastructure.llm_gateway import GaiaLlmGatewayAdapter


@pytest.fixture
def llm_settings():
    """Fixture for LLM settings."""
    return LlmGatewaySettings(
        endpoint="https://gaia.api/v1",
        model="gpt-4",
        auth_endpoint="https://auth.api/token",
        api_key="test-api-key",
        client_secret="test-secret",
        ca_cert_path="/path/to/cert",
        ca_cert_url="https://ca.url/cert.pem",
    )


@pytest.fixture
def disabled_llm_settings():
    """Fixture for disabled LLM settings."""
    return LlmGatewaySettings(
        endpoint="https://gaia.api/v1",
        model="gpt-4",
        auth_endpoint="https://auth.api/token",
        api_key="test-api-key",
        client_secret="test-secret",
        ca_cert_path="/path/to/cert",
        ca_cert_url="https://ca.url/cert.pem",
        gateway_enabled=False,
    )


class TestGaiaLlmGatewayAdapterDisabled:
    """Tests for disabled LLM gateway."""
    
    def test_enrich_incident_when_gateway_disabled(self, disabled_llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=disabled_llm_settings)
        
        with pytest.raises(LlmGatewayDisabledError):
            adapter.enrich_incident(
                incident_id="INC001",
                short_description="Test incident",
                description="Test description",
            )


class TestGaiaLlmGatewayAdapterAuthentication:
    """Tests for OAuth authentication."""
    
    def test_get_access_token_success(self, llm_settings):
        token_response = httpx.Response(
            status_code=200,
            json={
                "access_token": "test-token-123",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = token_response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            token = adapter._get_access_token()
            
            assert token == "test-token-123"
            mock_instance.post.assert_called_once()
    
    def test_get_access_token_caches_token(self, llm_settings):
        token_response = httpx.Response(
            status_code=200,
            json={
                "access_token": "test-token-123",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = token_response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            token1 = adapter._get_access_token()
            token2 = adapter._get_access_token()
            
            assert token1 == token2
            assert mock_instance.post.call_count == 1
    
    def test_get_access_token_auth_endpoint_unavailable(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.side_effect = httpx.NetworkError("Connection failed")
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            with pytest.raises(LlmGatewayUnavailableError):
                adapter._get_access_token()
    
    def test_get_access_token_auth_endpoint_error_response(self, llm_settings):
        error_response = httpx.Response(status_code=401)
        
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = error_response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            with pytest.raises(LlmGatewayUnavailableError):
                adapter._get_access_token()
    
    def test_get_access_token_missing_access_token_in_response(self, llm_settings):
        invalid_response = httpx.Response(
            status_code=200,
            json={
                "expires_in": 3600,
            },
        )
        
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = invalid_response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            with pytest.raises(LlmGatewayConfigurationError):
                adapter._get_access_token()


class TestGaiaLlmGatewayAdapterPromptBuilding:
    """Tests for prompt building."""
    
    def test_build_prompt_with_all_fields(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        prompt = adapter._build_prompt(
            incident_id="INC001",
            short_description="API latency",
            description="API responses are slow",
        )
        
        assert "INC001" in prompt
        assert "API latency" in prompt
        assert "API responses are slow" in prompt
        assert "JSON" in prompt
    
    def test_build_prompt_with_missing_descriptions(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        prompt = adapter._build_prompt(
            incident_id="INC001",
            short_description=None,
            description=None,
        )
        
        assert "INC001" in prompt
        assert "N/A" in prompt


class TestGaiaLlmGatewayAdapterResponseParsing:
    """Tests for LLM response parsing."""
    
    def test_parse_llm_response_with_complete_json(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "The API is experiencing latency issues.",
                            "related_incidents": ["INC002", "INC003"],
                            "mitigation_suggestions": [
                                {
                                    "suggestion": "Scale up the API servers",
                                    "related_incidents": ["INC002"],
                                    "related_log_ids": ["log1", "log2"],
                                }
                            ],
                        })
                    }
                }
            ]
        }
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is not None
        assert enrichment.summary.text == "The API is experiencing latency issues."
        assert len(enrichment.mitigation_suggestions) == 1
        assert enrichment.mitigation_suggestions[0].suggestion == "Scale up the API servers"
    
    def test_parse_llm_response_with_empty_suggestions(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "The API is experiencing latency issues.",
                            "related_incidents": [],
                            "mitigation_suggestions": [],
                        })
                    }
                }
            ]
        }
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is not None
        assert len(enrichment.mitigation_suggestions) == 0
    
    def test_parse_llm_response_with_invalid_json(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {
            "choices": [
                {
                    "message": {
                        "content": "This is not JSON but raw text"
                    }
                }
            ]
        }
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is not None
        assert enrichment.summary.text == "This is not JSON but raw text"
    
    def test_parse_llm_response_with_missing_choices(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {}
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is None
        assert len(enrichment.mitigation_suggestions) == 0
    
    def test_parse_llm_response_with_empty_choices(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {"choices": []}
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is None
        assert len(enrichment.mitigation_suggestions) == 0


class TestGaiaLlmGatewayAdapterRetries:
    """Tests for retry logic."""
    
    def test_call_llm_retries_on_5xx_error(self, llm_settings):
        settings = LlmGatewaySettings(
            endpoint="https://gaia.api/v1",
            model="gpt-4",
            auth_endpoint="https://auth.api/token",
            api_key="test-api-key",
            client_secret="test-secret",
            ca_cert_path="/path/to/cert",
            ca_cert_url="https://ca.url/cert.pem",
            max_retries=2,
            retry_base_delay_seconds=0.01,
        )
        
        adapter = GaiaLlmGatewayAdapter(settings=settings)
        
        responses = [
            httpx.Response(status_code=503),
            httpx.Response(status_code=200, json={"choices": [{"message": {"content": "ok"}}]}),
        ]
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.side_effect = responses
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            result = adapter._call_llm(prompt="test", token="token", max_tokens=100)
            
            assert result == {"choices": [{"message": {"content": "ok"}}]}
            assert mock_instance.post.call_count == 2
    
    def test_call_llm_fails_after_max_retries(self, llm_settings):
        settings = LlmGatewaySettings(
            endpoint="https://gaia.api/v1",
            model="gpt-4",
            auth_endpoint="https://auth.api/token",
            api_key="test-api-key",
            client_secret="test-secret",
            ca_cert_path="/path/to/cert",
            ca_cert_url="https://ca.url/cert.pem",
            max_retries=2,
            retry_base_delay_seconds=0.01,
        )
        
        adapter = GaiaLlmGatewayAdapter(settings=settings)
        
        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.side_effect = [
                httpx.Response(status_code=503),
                httpx.Response(status_code=503),
            ]
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None
            
            with pytest.raises(LlmGatewayUnavailableError):
                adapter._call_llm(prompt="test", token="token", max_tokens=100)
            
            assert mock_instance.post.call_count == 2
