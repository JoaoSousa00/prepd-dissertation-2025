import os
from unittest.mock import patch

import pytest

from src.infrastructure.llm_config import (
    LlmGatewaySettings,
    load_llm_gateway_settings,
    _parse_timeout,
)


class TestTimeoutParsing:
    """Tests for timeout value parsing."""
    
    def test_parse_timeout_with_none(self):
        assert _parse_timeout(None) is None
    
    def test_parse_timeout_with_empty_string(self):
        assert _parse_timeout("") is None
    
    def test_parse_timeout_with_none_string(self):
        assert _parse_timeout("none") is None
        assert _parse_timeout("NONE") is None
    
    def test_parse_timeout_with_zero(self):
        assert _parse_timeout("0") is None
    
    def test_parse_timeout_with_valid_float(self):
        assert _parse_timeout("30.5") == 30.5
        assert _parse_timeout("10") == 10.0
    
    def test_parse_timeout_with_invalid_value(self):
        assert _parse_timeout("invalid") is None


class TestLlmGatewaySettingsValidation:
    """Tests for LlmGatewaySettings validation."""
    
    def test_settings_with_all_required_values(self):
        settings = LlmGatewaySettings(
            endpoint="https://gaia.api/v1",
            model="gpt-4",
            auth_endpoint="https://auth.api/token",
            api_key="test-api-key",
            client_secret="test-secret",
            ca_cert_path="/path/to/cert",
            ca_cert_url="https://ca.url/cert.pem",
        )
        
        assert settings.endpoint == "https://gaia.api/v1"
        assert settings.model == "gpt-4"
        assert settings.gateway_enabled is True
    
    def test_settings_with_optional_x_api_key(self):
        settings = LlmGatewaySettings(
            endpoint="https://gaia.api/v1",
            model="gpt-4",
            auth_endpoint="https://auth.api/token",
            api_key="test-api-key",
            client_secret="test-secret",
            ca_cert_path="/path/to/cert",
            ca_cert_url="https://ca.url/cert.pem",
            x_api_key="alternate-api-key",
        )
        
        assert settings.get_api_key() == "alternate-api-key"
    
    def test_settings_fallback_to_api_key_when_x_api_key_not_set(self):
        settings = LlmGatewaySettings(
            endpoint="https://gaia.api/v1",
            model="gpt-4",
            auth_endpoint="https://auth.api/token",
            api_key="test-api-key",
            client_secret="test-secret",
            ca_cert_path="/path/to/cert",
            ca_cert_url="https://ca.url/cert.pem",
        )
        
        assert settings.get_api_key() == "test-api-key"
    
    def test_settings_missing_endpoint_raises_error(self):
        with pytest.raises(ValueError, match="GAIA_LLM_ENDPOINT is required"):
            LlmGatewaySettings(
                endpoint="",
                model="gpt-4",
                auth_endpoint="https://auth.api/token",
                api_key="test-api-key",
                client_secret="test-secret",
                ca_cert_path="/path/to/cert",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_model_raises_error(self):
        with pytest.raises(ValueError, match="GAIA_MODEL is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="",
                auth_endpoint="https://auth.api/token",
                api_key="test-api-key",
                client_secret="test-secret",
                ca_cert_path="/path/to/cert",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_auth_endpoint_raises_error(self):
        with pytest.raises(ValueError, match="GAIA_AUTH_ENDPOINT is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="gpt-4",
                auth_endpoint="",
                api_key="test-api-key",
                client_secret="test-secret",
                ca_cert_path="/path/to/cert",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_api_key_raises_error(self):
        with pytest.raises(ValueError, match="LLM_API_KEY is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="gpt-4",
                auth_endpoint="https://auth.api/token",
                api_key="",
                client_secret="test-secret",
                ca_cert_path="/path/to/cert",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_client_secret_raises_error(self):
        with pytest.raises(ValueError, match="LLM_CLIENT_SECRET is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="gpt-4",
                auth_endpoint="https://auth.api/token",
                api_key="test-api-key",
                client_secret="",
                ca_cert_path="/path/to/cert",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_ca_cert_path_raises_error(self):
        with pytest.raises(ValueError, match="CA_CERT_PATH is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="gpt-4",
                auth_endpoint="https://auth.api/token",
                api_key="test-api-key",
                client_secret="test-secret",
                ca_cert_path="",
                ca_cert_url="https://ca.url/cert.pem",
            )
    
    def test_settings_missing_ca_cert_url_raises_error(self):
        with pytest.raises(ValueError, match="CA_CERT_URL is required"):
            LlmGatewaySettings(
                endpoint="https://gaia.api/v1",
                model="gpt-4",
                auth_endpoint="https://auth.api/token",
                api_key="test-api-key",
                client_secret="test-secret",
                ca_cert_path="/path/to/cert",
                ca_cert_url="",
            )


class TestLoadLlmGatewaySettings:
    """Tests for loading LLM gateway settings from environment."""
    
    def test_load_with_all_env_vars_set(self):
        env_vars = {
            "GAIA_LLM_ENDPOINT": "https://gaia.api/v1",
            "GAIA_MODEL": "gpt-4",
            "GAIA_AUTH_ENDPOINT": "https://auth.api/token",
            "LLM_API_KEY": "test-api-key",
            "LLM_CLIENT_SECRET": "test-secret",
            "CA_CERT_PATH": "/path/to/cert",
            "CA_CERT_URL": "https://ca.url/cert.pem",
            "LLM_X_API_KEY": "alt-key",
            "LLM_MAX_RETRIES": "5",
            "LLM_RETRY_BASE_DELAY_SECONDS": "2.0",
            "LLM_DEFAULT_MAX_TOKENS": "4096",
            "LLM_REQUEST_TIMEOUT_SECONDS": "60.0",
            "LLM_AUTH_TIMEOUT_SECONDS": "15.0",
            "LLM_GATEWAY_ENABLED": "true",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            settings = load_llm_gateway_settings()
            
            assert settings.endpoint == "https://gaia.api/v1"
            assert settings.model == "gpt-4"
            assert settings.auth_endpoint == "https://auth.api/token"
            assert settings.api_key == "test-api-key"
            assert settings.client_secret == "test-secret"
            assert settings.ca_cert_path == "/path/to/cert"
            assert settings.ca_cert_url == "https://ca.url/cert.pem"
            assert settings.x_api_key == "alt-key"
            assert settings.max_retries == 5
            assert settings.retry_base_delay_seconds == 2.0
            assert settings.default_max_tokens == 4096
            assert settings.request_timeout_seconds == 60.0
            assert settings.auth_timeout_seconds == 15.0
            assert settings.gateway_enabled is True
    
    def test_load_with_gateway_disabled(self):
        env_vars = {
            "GAIA_LLM_ENDPOINT": "https://gaia.api/v1",
            "GAIA_MODEL": "gpt-4",
            "GAIA_AUTH_ENDPOINT": "https://auth.api/token",
            "LLM_API_KEY": "test-api-key",
            "LLM_CLIENT_SECRET": "test-secret",
            "CA_CERT_PATH": "/path/to/cert",
            "CA_CERT_URL": "https://ca.url/cert.pem",
            "LLM_GATEWAY_ENABLED": "false",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            settings = load_llm_gateway_settings()
            assert settings.gateway_enabled is False

    def test_load_without_request_timeout_uses_four_minute_default(self):
        env_vars = {
            "GAIA_LLM_ENDPOINT": "https://gaia.api/v1",
            "GAIA_MODEL": "gpt-4",
            "GAIA_AUTH_ENDPOINT": "https://auth.api/token",
            "LLM_API_KEY": "test-api-key",
            "LLM_CLIENT_SECRET": "test-secret",
            "CA_CERT_PATH": "/path/to/cert",
            "CA_CERT_URL": "https://ca.url/cert.pem",
        }

        with patch.dict(os.environ, env_vars, clear=True):
            settings = load_llm_gateway_settings()
            assert settings.request_timeout_seconds == 240.0
            assert settings.auth_timeout_seconds == 30.0
    
    def test_load_with_no_timeout_disables_request_timeout(self):
        env_vars = {
            "GAIA_LLM_ENDPOINT": "https://gaia.api/v1",
            "GAIA_MODEL": "gpt-4",
            "GAIA_AUTH_ENDPOINT": "https://auth.api/token",
            "LLM_API_KEY": "test-api-key",
            "LLM_CLIENT_SECRET": "test-secret",
            "CA_CERT_PATH": "/path/to/cert",
            "CA_CERT_URL": "https://ca.url/cert.pem",
            "LLM_REQUEST_TIMEOUT_SECONDS": "none",
            "LLM_AUTH_TIMEOUT_SECONDS": "0",
        }
        
        with patch.dict(os.environ, env_vars, clear=False):
            settings = load_llm_gateway_settings()
            assert settings.request_timeout_seconds is None
            assert settings.auth_timeout_seconds is None
    
    def test_load_with_missing_required_vars_raises_error(self):
        env_vars = {
            "GAIA_LLM_ENDPOINT": "https://gaia.api/v1",
            "GAIA_MODEL": "gpt-4",
        }
        
        with patch.dict(os.environ, env_vars, clear=True):
            with pytest.raises(ValueError):
                load_llm_gateway_settings()
