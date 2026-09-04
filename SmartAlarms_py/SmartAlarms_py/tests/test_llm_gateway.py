import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.domain.llm import (
    LlmGatewayConfigurationError,
    LlmGatewayDisabledError,
    LlmGatewayUnavailableError,
)
from src.infrastructure.llm_config import LlmGatewaySettings
from src.infrastructure.llm_gateway import GaiaLlmGatewayAdapter, _resolve_cert


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

    def setup_method(self):
        GaiaLlmGatewayAdapter._shared_token_cache = None
        GaiaLlmGatewayAdapter._shared_token_expiry = 0
    
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
            mock_client_class.assert_called_once_with(
                timeout=llm_settings.auth_timeout_seconds,
                verify="/path/to/cert",
            )
            mock_instance.post.assert_called_once()
            _, kwargs = mock_instance.post.call_args
            assert kwargs["data"] == {
                "client_id": "test-api-key",
                "client_secret": "test-secret",
                "grant_type": "client_credentials",
                "scope": "machine2machine",
            }
            assert kwargs["headers"]["Content-Type"] == "application/x-www-form-urlencoded"
            if "traceparent" in kwargs["headers"]:
                assert kwargs["headers"]["traceparent"].startswith("00-")
    
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

    def test_get_access_token_uses_shared_cache_across_instances(self, llm_settings):
        GaiaLlmGatewayAdapter._shared_token_cache = None
        GaiaLlmGatewayAdapter._shared_token_expiry = 0
        token_response = httpx.Response(
            status_code=200,
            json={
                "access_token": "shared-token-123",
                "expires_in": 3600,
                "token_type": "Bearer",
            },
        )
        adapter_a = GaiaLlmGatewayAdapter(settings=llm_settings)
        adapter_b = GaiaLlmGatewayAdapter(settings=llm_settings)

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = token_response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None

            token_a = adapter_a._get_access_token()
            token_b = adapter_b._get_access_token()

            assert token_a == "shared-token-123"
            assert token_b == "shared-token-123"
            assert mock_instance.post.call_count == 1


class TestGaiaLlmGatewayAdapterPromptBuilding:
    """Tests for prompt building."""
    
    def test_build_prompt_with_all_fields(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        prompt = adapter._build_prompt(
            incident_id="INC001",
            short_description="API latency",
            description="API responses are slow",
            main_incident_context="Main incident fields:\n- number: INC001\n- state: New",
            related_incident_context="Incident INC002 | state=Closed",
            same_title_incident_context="Incident INC003 | state=Closed",
        )
        
        assert "INC001" in prompt
        assert "API latency" in prompt
        assert "API responses are slow" in prompt
        assert "Main incident fields:" in prompt
        assert "number: INC001" in prompt
        assert "Incident INC002" in prompt
        assert "Incident INC003" in prompt
        assert "Return at least 3 mitigation suggestions whenever possible." in prompt
        assert "Sources: current_incident_analysis" in prompt
    
    def test_build_prompt_with_missing_descriptions(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        prompt = adapter._build_prompt(
            incident_id="INC001",
            short_description=None,
            description=None,
        )
        
        assert "INC001" in prompt
        assert "N/A" in prompt
        assert "No additional main-incident context was provided." in prompt

    def test_build_prompt_uses_template_file(self, llm_settings, tmp_path):
        prompt_file = tmp_path / "incident_enrichment_prompt.txt"
        prompt_file.write_text(
            "ID={incident_id}|SHORT={short_description}|DESC={description}|MAIN={main_incident_context}",
            encoding="utf-8",
        )
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings, prompt_path=prompt_file)

        prompt = adapter._build_prompt("INC123", "Short text", "Detailed text", "Main context")

        assert prompt == "ID=INC123|SHORT=Short text|DESC=Detailed text|MAIN=Main context"


class TestGaiaLlmGatewayAdapterHeaders:
    def test_llm_headers_match_gaia_gateway_shape(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        headers = adapter._get_llm_headers("test-token")

        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"
        assert headers["Accept"] == "application/json"
        assert headers["x-apikey"] == "test-api-key"

    def test_sanitize_headers_masks_sensitive_values(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        sanitized = adapter._sanitize_headers(
            {
                "Authorization": "Bearer test-token",
                "x-apikey": "secret",
                "Accept": "application/json",
            }
        )

        assert sanitized["Authorization"] == "******"
        assert sanitized["x-apikey"] == "******"
        assert sanitized["Accept"] == "application/json"


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
                                    "Confidence": "evidence-based",
                                    "Investigation": "Check API pod saturation and latency percentiles.",
                                    "Mitigation": "Scale API replicas and clear stuck connections.",
                                    "Resolution_note": "Scaled replicas and stabilized API latency.",
                                    "related_incidents": ["INC002"],
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
        assert enrichment.related_incidents == ["INC002", "INC003"]
        assert len(enrichment.mitigation_suggestions) == 1
        suggestion = enrichment.mitigation_suggestions[0]
        assert suggestion.confidence == "evidence-based"
        assert suggestion.investigation == "Check API pod saturation and latency percentiles."
        assert suggestion.mitigation == "Scale API replicas and clear stuck connections."
        assert suggestion.resolution_note == "Scaled replicas and stabilized API latency."
        assert suggestion.related_incidents == ["INC002"]

    def test_parse_llm_response_handles_structured_suggestion_without_combined_text(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "Latency increased.",
                            "related_incidents": ["INC002"],
                            "mitigation_suggestions": [
                                {
                                    "Confidence": "reasoned fallback",
                                    "Investigation": "Check upstream error rates.",
                                    "Mitigation": "Temporarily increase worker replicas.",
                                    "Resolution_note": "Increased replicas and monitored stabilization.",
                                    "related_incidents": ["INC002"],
                                }
                            ],
                        })
                    }
                }
            ]
        }

        enrichment = adapter._parse_llm_response(response)

        assert len(enrichment.mitigation_suggestions) == 1
        suggestion = enrichment.mitigation_suggestions[0]
        assert suggestion.confidence == "reasoned fallback"
        assert suggestion.investigation == "Check upstream error rates."
        assert suggestion.mitigation == "Temporarily increase worker replicas."
        assert suggestion.resolution_note == "Increased replicas and monitored stabilization."
        assert suggestion.related_incidents == ["INC002"]

    def test_parse_llm_response_filters_non_inc_related_incident_values(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "Latency increased.",
                            "related_incidents": [
                                "Sources: current_incident_analysis",
                                "inc001",
                                "INC002",
                            ],
                            "mitigation_suggestions": [
                                {
                                    "Confidence": "reasoned fallback",
                                    "Investigation": "Check upstream error rates.",
                                    "Mitigation": "Temporarily increase worker replicas.",
                                    "Resolution_note": "Increased replicas and monitored stabilization.",
                                    "related_incidents": [
                                        "Sources: current_incident_analysis",
                                        "INC002",
                                        "src=inc003 and note",
                                    ],
                                }
                            ],
                        })
                    }
                }
            ]
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.related_incidents == ["INC001", "INC002"]
        assert enrichment.mitigation_suggestions[0].related_incidents == ["INC002", "INC003"]

    def test_parse_llm_response_extracts_usage_metadata(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "cost": 0.021,
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "The API is experiencing latency issues.",
                        })
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.model == "openai/gpt-5"
        assert enrichment.usage.tokens_in == 120
        assert enrichment.usage.tokens_out == 80
        assert enrichment.usage.tokens_total == 200
        assert enrichment.usage.estimated_cost == 0.021

    def test_parse_llm_response_estimates_cost_from_model_pricing(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps({
                            "summary": "The API is experiencing latency issues.",
                        })
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.estimated_cost == pytest.approx(0.010456)

    def test_parse_llm_response_extracts_text_from_content_blocks(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "text",
                                "text": "{\"summary\":\"Latency increased after deployment\"}",
                            }
                        ]
                    }
                }
            ]
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.summary is not None
        assert enrichment.summary.text == "Latency increased after deployment"

    def test_parse_llm_response_logs_response_body_on_invalid_json(self, llm_settings, caplog):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "id": "resp-1",
            "choices": [{"message": {"content": "not-json"}}],
        }

        with caplog.at_level("WARNING"):
            enrichment = adapter._parse_llm_response(response)

        assert enrichment.summary is not None
        assert enrichment.summary.text == "not-json"
        assert "response=" in caplog.text
        assert "\"id\": \"resp-1\"" in caplog.text

    def test_parse_llm_response_handles_empty_content_with_usage(self, llm_settings, caplog):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "id": "resp-empty",
            "model": "openai/gpt-5",
            "choices": [
                {
                    "finish_reason": "length",
                    "message": {"content": "", "role": "assistant"},
                }
            ],
            "usage": {
                "prompt_tokens": 212,
                "completion_tokens": 2048,
                "total_tokens": 2260,
            },
        }

        with caplog.at_level("WARNING"):
            enrichment = adapter._parse_llm_response(response)

        assert enrichment.summary is None
        assert enrichment.usage is not None
        assert enrichment.usage.tokens_total == 2260
        assert "LLM returned empty message content" in caplog.text
        assert "finish_reason=length" in caplog.text

    def test_parse_llm_response_uses_nested_cost_total(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "usage": {
                "prompt_tokens": 212,
                "completion_tokens": 2048,
                "total_tokens": 2260,
            },
            "cost": {
                "interaction": {"total": 0.0228206, "currency": "USD"},
                "total": 0.0228206,
                "currency": "USD",
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"summary": "Latency incident summary"}),
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.estimated_cost == pytest.approx(0.0228206)

    def test_parse_llm_response_prioritizes_response_total_cost(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
                "estimated_cost": 0.12345,
            },
            "cost": {
                "interaction": {"total": 0.0000574, "currency": "USD"},
                "total": 0.0000574,
                "currency": "USD",
            },
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"summary": "Latency incident summary"}),
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.estimated_cost == pytest.approx(0.0000574)

    def test_parse_llm_response_uses_reported_cost_without_usage_object(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "cost": {"total": 0.0000574, "currency": "USD"},
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"summary": "Latency incident summary"}),
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.model == "openai/gpt-5"
        assert enrichment.usage.tokens_in is None
        assert enrichment.usage.tokens_out is None
        assert enrichment.usage.tokens_total is None
        assert enrichment.usage.estimated_cost == pytest.approx(0.0000574)

    def test_parse_llm_response_estimates_cost_when_reported_cost_is_empty(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response = {
            "model": "openai/gpt-5",
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 80,
                "total_tokens": 200,
            },
            "cost": {"total": "", "currency": "USD"},
            "choices": [
                {
                    "message": {
                        "content": json.dumps({"summary": "Latency incident summary"}),
                    }
                }
            ],
        }

        enrichment = adapter._parse_llm_response(response)

        assert enrichment.usage is not None
        assert enrichment.usage.estimated_cost == pytest.approx(0.010456)

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
        assert enrichment.related_incidents == []
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
        assert enrichment.related_incidents == []
    
    def test_parse_llm_response_with_missing_choices(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {}
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is None
        assert enrichment.related_incidents == []
        assert len(enrichment.mitigation_suggestions) == 0
    
    def test_parse_llm_response_with_empty_choices(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        
        response = {"choices": []}
        
        enrichment = adapter._parse_llm_response(response)
        
        assert enrichment.summary is None
        assert enrichment.related_incidents == []
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
            
            result, retry_count = adapter._call_llm(prompt="test", token="token", max_tokens=100)
            
            assert result == {"choices": [{"message": {"content": "ok"}}]}
            assert retry_count == 1
            assert mock_client_class.call_count == 2
            for call in mock_client_class.call_args_list:
                assert call.kwargs == {
                    "timeout": settings.request_timeout_seconds,
                    "transport": None,
                    "verify": "/path/to/cert",
                }
            assert mock_instance.post.call_count == 2

    def test_call_llm_logs_request_and_response_payloads(self, llm_settings, caplog):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)

        response_payload = {"choices": [{"message": {"content": "ok"}}]}
        response = httpx.Response(
            status_code=200,
            headers={"x-request-id": "abc-123"},
            json=response_payload,
        )

        with patch("httpx.Client") as mock_client_class:
            mock_instance = MagicMock()
            mock_instance.post.return_value = response
            mock_client_class.return_value.__enter__.return_value = mock_instance
            mock_client_class.return_value.__exit__.return_value = None

            with caplog.at_level("DEBUG"):
                adapter._call_llm(prompt="test prompt", token="token-123", max_tokens=100)

        assert "Sending LLM request." in caplog.text
        assert "Received LLM response." in caplog.text
        assert "headers={'Authorization': '******'" in caplog.text
        assert "\"content\": \"test prompt\"" in caplog.text
    
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
            
            assert mock_client_class.call_count == 2
            for call in mock_client_class.call_args_list:
                assert call.kwargs == {
                    "timeout": settings.request_timeout_seconds,
                    "transport": None,
                    "verify": "/path/to/cert",
                }
            assert mock_instance.post.call_count == 2

    def test_call_llm_injects_traceparent_header(self, llm_settings):
        captured_headers: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured_headers.update(dict(request.headers))
            return httpx.Response(
                status_code=200,
                json={"choices": [{"message": {"content": "ok"}}]},
            )

        adapter = GaiaLlmGatewayAdapter(
            settings=llm_settings,
            transport=httpx.MockTransport(handler),
        )

        with patch("src.infrastructure.llm_gateway.inject_trace_context") as inject:
            inject.side_effect = lambda headers: headers.__setitem__("traceparent", "00-test")
            _, _ = adapter._call_llm(prompt="test", token="token", max_tokens=100)

        assert captured_headers["traceparent"] == "00-test"


class TestGaiaLlmGatewayAdapterTracing:
    def test_enrich_incident_creates_llm_complete_span(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        span_names: list[str] = []

        class DummySpan:
            def set_attribute(self, *_args, **_kwargs):
                return None

            def set_status(self, *_args, **_kwargs):
                return None

            def record_exception(self, *_args, **_kwargs):
                return None

        @contextmanager
        def fake_start_span(span_name, **_kwargs):
            span_names.append(span_name)
            yield DummySpan()

        with patch("src.infrastructure.llm_gateway.start_span", side_effect=fake_start_span):
            with patch.object(adapter, "_get_access_token", return_value="token"):
                with patch.object(
                    adapter,
                    "_call_llm",
                    return_value=(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": json.dumps({"summary": "ok"}),
                                    }
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                                "cost": 0.001,
                            },
                        },
                        0,
                    ),
                ):
                    adapter.enrich_incident("INC001", "short", "desc")

        assert "llm.complete" in span_names

    def test_enrich_incident_sets_langfuse_generation_attributes(self, llm_settings):
        adapter = GaiaLlmGatewayAdapter(settings=llm_settings)
        captured_attributes: dict[str, object] = {}

        class DummySpan:
            def set_attribute(self, key, value):
                captured_attributes[key] = value

            def set_status(self, *_args, **_kwargs):
                return None

            def record_exception(self, *_args, **_kwargs):
                return None

        @contextmanager
        def fake_start_span(span_name, **_kwargs):
            captured_attributes.update(_kwargs.get("attributes", {}))
            if span_name == "llm.complete":
                yield DummySpan()
                return
            yield DummySpan()

        with patch("src.infrastructure.llm_gateway.start_span", side_effect=fake_start_span):
            with patch.object(adapter, "_get_access_token", return_value="token"):
                with patch.object(
                    adapter,
                    "_call_llm",
                    return_value=(
                        {
                            "choices": [
                                {
                                    "message": {
                                        "content": json.dumps({"summary": "Latency incident summary"}),
                                    }
                                }
                            ],
                            "usage": {
                                "prompt_tokens": 12,
                                "completion_tokens": 7,
                                "total_tokens": 19,
                                "cost": 0.0021,
                            },
                        },
                        1,
                    ),
                ):
                    adapter.enrich_incident("INC001", "short", "desc")

        assert captured_attributes["langfuse.observation.type"] == "generation"
        assert "langfuse.observation.input" in captured_attributes
        assert "langfuse.observation.output" in captured_attributes
        assert captured_attributes["gen_ai.usage.input_tokens"] == 12
        assert captured_attributes["gen_ai.usage.output_tokens"] == 7
        assert captured_attributes["gen_ai.usage.total_tokens"] == 19
        assert captured_attributes["gen_ai.usage.cost"] == 0.0021


class TestCertResolution:
    def test_resolve_cert_uses_relative_path_from_cwd(self, monkeypatch, tmp_path):
        cert_name = "BMW_Trusted_Certificates_Latest.pem"
        cert_path = tmp_path / cert_name
        cert_path.write_text("dummy cert", encoding="utf-8")
        monkeypatch.chdir(tmp_path)

        resolved = _resolve_cert(cert_name, "https://ca.url/cert.pem")

        assert resolved == str(cert_path)
