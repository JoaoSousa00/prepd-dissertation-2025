import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LLM_ENDPOINT = "https://llm.gateway/v1"
DEFAULT_MODEL = "gpt-4"
DEFAULT_LLM_MAX_RETRIES = 3
DEFAULT_LLM_RETRY_BASE_DELAY_SECONDS = 1.0
DEFAULT_LLM_DEFAULT_MAX_TOKENS = 100000
DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS = 240.0
DEFAULT_LLM_AUTH_TIMEOUT_SECONDS = 30.0
DEFAULT_LLM_GATEWAY_ENABLED = True


@dataclass(frozen=True)
class LlmGatewaySettings:
    """Configuration for LLM gateway connection to GAIA."""
    
    # Required settings
    endpoint: str
    model: str
    auth_endpoint: str
    api_key: str
    client_secret: str
    ca_cert_path: str
    ca_cert_url: str
    
    # Optional settings with defaults
    x_api_key: Optional[str] = None
    max_retries: int = DEFAULT_LLM_MAX_RETRIES
    retry_base_delay_seconds: float = DEFAULT_LLM_RETRY_BASE_DELAY_SECONDS
    default_max_tokens: int = DEFAULT_LLM_DEFAULT_MAX_TOKENS
    request_timeout_seconds: Optional[float] = DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
    auth_timeout_seconds: Optional[float] = DEFAULT_LLM_AUTH_TIMEOUT_SECONDS
    gateway_enabled: bool = DEFAULT_LLM_GATEWAY_ENABLED
    
    def __post_init__(self):
        # Validate required settings are present
        if not self.endpoint:
            raise ValueError("GAIA_LLM_ENDPOINT is required")
        if not self.model:
            raise ValueError("GAIA_MODEL is required")
        if not self.auth_endpoint:
            raise ValueError("GAIA_AUTH_ENDPOINT is required")
        if not self.api_key:
            raise ValueError("LLM_API_KEY is required")
        if not self.client_secret:
            raise ValueError("LLM_CLIENT_SECRET is required")
        if not self.ca_cert_path:
            raise ValueError("CA_CERT_PATH is required")
        if not self.ca_cert_url:
            raise ValueError("CA_CERT_URL is required")
    
    def get_api_key(self) -> str:
        """Get the API key, preferring x_api_key if set, otherwise api_key."""
        return self.x_api_key or self.api_key


def _parse_timeout(value: Optional[str]) -> Optional[float]:
    """Parse timeout value from environment, handling special cases."""
    if value is None or value == "":
        return None
    if value.lower() in {"none", "0"}:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def load_llm_gateway_settings() -> LlmGatewaySettings:
    """Load LLM gateway settings from environment variables."""
    # Parse request timeout: empty, 0, or "none" disables it
    request_timeout_str = os.getenv("LLM_REQUEST_TIMEOUT_SECONDS")
    if request_timeout_str is None or request_timeout_str == "":
        request_timeout = DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
    else:
        parsed = _parse_timeout(request_timeout_str)
        # If _parse_timeout returns None, it means disabled (special case)
        # If it's a valid number, use it; otherwise use default
        if parsed is None and request_timeout_str.lower() in {"none", "0"}:
            request_timeout = None
        else:
            request_timeout = parsed if parsed is not None else DEFAULT_LLM_REQUEST_TIMEOUT_SECONDS
    
    # Parse auth timeout: 0 or "none" disables it
    auth_timeout_str = os.getenv("LLM_AUTH_TIMEOUT_SECONDS")
    if auth_timeout_str is None or auth_timeout_str == "":
        auth_timeout = DEFAULT_LLM_AUTH_TIMEOUT_SECONDS
    else:
        parsed = _parse_timeout(auth_timeout_str)
        # If _parse_timeout returns None, it means disabled (special case)
        # If it's a valid number, use it; otherwise use default
        if parsed is None and auth_timeout_str.lower() in {"none", "0"}:
            auth_timeout = None
        else:
            auth_timeout = parsed if parsed is not None else DEFAULT_LLM_AUTH_TIMEOUT_SECONDS
    
    # Parse gateway enabled flag
    gateway_enabled_str = os.getenv("LLM_GATEWAY_ENABLED", "true").lower()
    gateway_enabled = gateway_enabled_str in {"true", "1", "yes", "on"}
    
    return LlmGatewaySettings(
        endpoint=os.getenv("GAIA_LLM_ENDPOINT", DEFAULT_LLM_ENDPOINT),
        model=os.getenv("GAIA_MODEL", DEFAULT_MODEL),
        auth_endpoint=os.getenv("GAIA_AUTH_ENDPOINT", ""),
        api_key=os.getenv("LLM_API_KEY", ""),
        client_secret=os.getenv("LLM_CLIENT_SECRET", ""),
        ca_cert_path=os.getenv("CA_CERT_PATH", ""),
        ca_cert_url=os.getenv("CA_CERT_URL", ""),
        x_api_key=os.getenv("LLM_X_API_KEY"),
        max_retries=int(os.getenv("LLM_MAX_RETRIES", str(DEFAULT_LLM_MAX_RETRIES))),
        retry_base_delay_seconds=float(
            os.getenv("LLM_RETRY_BASE_DELAY_SECONDS", str(DEFAULT_LLM_RETRY_BASE_DELAY_SECONDS))
        ),
        default_max_tokens=int(
            os.getenv("LLM_DEFAULT_MAX_TOKENS", str(DEFAULT_LLM_DEFAULT_MAX_TOKENS))
        ),
        request_timeout_seconds=request_timeout,
        auth_timeout_seconds=auth_timeout,
        gateway_enabled=gateway_enabled,
    )
