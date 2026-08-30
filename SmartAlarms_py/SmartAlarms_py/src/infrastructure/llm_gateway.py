import json
import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from src.domain.llm import (
    IncidentEnrichment,
    LlmGateway,
    LlmGatewayConfigurationError,
    LlmGatewayDisabledError,
    LlmGatewayUnavailableError,
    LlmSummary,
    MitigationSuggestion,
)
from src.infrastructure.llm_config import LlmGatewaySettings, load_llm_gateway_settings

logger = logging.getLogger(__name__)
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompt" / "incident_enrichment_prompt.txt"
)
DEFAULT_CA_DOWNLOAD_TIMEOUT_SECONDS = 30.0


def _download_bmw_ca_cert(path: Path, ca_cert_url: str) -> str:
    """Download the BMW CA certificate when it is not present locally."""
    if path.exists():
        return str(path)

    if not ca_cert_url:
        raise LlmGatewayConfigurationError(
            "CA_CERT_URL is required when the BMW CA certificate is missing"
        )

    logger.info("Downloading BMW CA certificate from %s to %s", ca_cert_url, path)
    try:
        response = httpx.get(ca_cert_url, timeout=DEFAULT_CA_DOWNLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise LlmGatewayConfigurationError(
            f"Failed to download BMW CA certificate from '{ca_cert_url}'"
        ) from exc

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    return str(path)


def _cert_candidates(relative: Path) -> list[Path]:
    """Return candidate locations for a relative BMW CA certificate path."""
    here = Path(__file__).resolve()
    return [
        Path.cwd() / relative,
        Path("/app/certs") / relative,
        Path("/app") / relative,
        here.parents[2] / "certs" / relative,
        here.parents[3] / "SmartAlarms_py" / "SmartAlarms_py" / "certs" / relative,
    ]


def _resolve_cert(ca_cert_path: str, ca_cert_url: str) -> str | bool:
    """Resolve the TLS certificate path for the BMW internal CA."""
    cert_path = ca_cert_path.strip()
    if cert_path:
        resolved = Path(cert_path)
        if resolved.is_absolute():
            return str(resolved)

        candidates = _cert_candidates(resolved)
        found = next((candidate for candidate in candidates if candidate.exists()), None)
        if found:
            logger.debug("Resolved BMW CA certificate via %s", found)
            return str(found)

        logger.warning(
            "CA_CERT_PATH=%r could not be resolved to an existing file; tried: %s",
            cert_path,
            candidates,
        )
        return str(candidates[0])

    default = Path(__file__).resolve().parents[2] / "certs" / "BMW_Trusted_Certificates_Latest.pem"
    try:
        return _download_bmw_ca_cert(default, ca_cert_url.strip())
    except LlmGatewayConfigurationError as exc:
        logger.warning(
            "Could not obtain BMW CA certificate (%s); falling back to system CA bundle.",
            exc,
        )
        return True


class GaiaLlmGatewayAdapter(LlmGateway):
    """LLM gateway adapter for GAIA integration.
    
    Handles OAuth authentication, retries, timeouts, and CA certificate verification.
    """
    
    def __init__(
        self,
        settings: Optional[LlmGatewaySettings] = None,
        transport: Optional[httpx.BaseTransport] = None,
        prompt_path: Optional[Path] = None,
    ):
        self._settings = settings or load_llm_gateway_settings()
        self._transport = transport
        self._prompt_path = prompt_path or DEFAULT_PROMPT_PATH
        self._prompt_template = self._load_prompt_template(self._prompt_path)
        self._verify = _resolve_cert(
            self._settings.ca_cert_path,
            self._settings.ca_cert_url,
        )
        self._token_cache: Optional[str] = None
        self._token_expiry: float = 0
    
    def enrich_incident(
        self,
        incident_id: str,
        short_description: Optional[str],
        description: Optional[str],
        max_tokens: Optional[int] = None,
    ) -> IncidentEnrichment:
        """Enrich an incident with LLM-generated content."""
        if not self._settings.gateway_enabled:
            raise LlmGatewayDisabledError("LLM gateway is disabled")
        
        try:
            token = self._get_access_token()
        except (LlmGatewayUnavailableError, LlmGatewayConfigurationError):
            raise
        
        prompt = self._build_prompt(incident_id, short_description, description)
        
        try:
            response = self._call_llm(
                prompt=prompt,
                token=token,
                max_tokens=max_tokens or self._settings.default_max_tokens,
            )
        except LlmGatewayUnavailableError:
            raise
        
        return self._parse_llm_response(response)
    
    def _get_access_token(self) -> str:
        """Get OAuth access token from GAIA auth endpoint."""
        # Return cached token if still valid
        if self._token_cache and time.time() < self._token_expiry:
            return self._token_cache
        
        try:
            with httpx.Client(
                timeout=self._settings.auth_timeout_seconds,
                verify=self._verify,
            ) as client:
                response = client.post(
                    self._settings.auth_endpoint,
                    data={
                        "client_id": self._settings.api_key,
                        "client_secret": self._settings.client_secret,
                        "grant_type": "client_credentials",
                        "scope": "machine2machine",
                    },
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
        except httpx.HTTPError as exc:
            logger.error("Failed to connect to LLM auth endpoint: %s", exc)
            raise LlmGatewayUnavailableError(
                f"Failed to authenticate with LLM gateway: {exc}"
            ) from exc
        
        if response.status_code != 200:
            logger.error(
                "LLM auth endpoint returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            raise LlmGatewayUnavailableError(
                f"LLM authentication failed with status {response.status_code}"
            )
        
        try:
            payload = response.json()
            token = payload.get("access_token")
            expires_in = payload.get("expires_in", 3600)
            
            if not token:
                raise ValueError("No access_token in response")
            
            self._token_cache = token
            self._token_expiry = time.time() + (expires_in * 0.9)  # Refresh at 90%
            return token
        except (ValueError, KeyError) as exc:
            logger.error("Invalid LLM auth response: %s", exc)
            raise LlmGatewayConfigurationError(
                "Invalid authentication response from LLM gateway"
            ) from exc
    
    def _call_llm(self, prompt: str, token: str, max_tokens: int) -> dict:
        """Call LLM gateway with retry logic."""
        for attempt in range(self._settings.max_retries):
            try:
                with httpx.Client(
                    timeout=self._settings.request_timeout_seconds,
                    transport=self._transport,
                    verify=self._verify,
                ) as client:
                    response = client.post(
                        f"{self._settings.endpoint.rstrip('/')}/chat/completions",
                        headers=self._get_llm_headers(token),
                        json={
                            "model": self._settings.model,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": prompt,
                                }
                            ],
                            "max_tokens": max_tokens,
                        },
                    )
            except httpx.HTTPError as exc:
                if attempt < self._settings.max_retries - 1:
                    delay = self._settings.retry_base_delay_seconds * (2 ** attempt)
                    logger.warning(
                        "LLM request failed (attempt %d/%d), retrying in %.1fs: %s",
                        attempt + 1,
                        self._settings.max_retries,
                        delay,
                        exc,
                    )
                    time.sleep(delay)
                    continue
                logger.error("LLM request failed after %d attempts: %s", attempt + 1, exc)
                raise LlmGatewayUnavailableError(
                    f"LLM gateway unavailable after {attempt + 1} attempts"
                ) from exc
            
            if response.status_code >= 500:
                if attempt < self._settings.max_retries - 1:
                    delay = self._settings.retry_base_delay_seconds * (2 ** attempt)
                    logger.warning(
                        "LLM returned %s (attempt %d/%d), retrying in %.1fs",
                        response.status_code,
                        attempt + 1,
                        self._settings.max_retries,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                logger.error(
                    "LLM returned %s after %d attempts: %s",
                    response.status_code,
                    attempt + 1,
                    response.text[:500],
                )
                raise LlmGatewayUnavailableError(
                    f"LLM gateway returned status {response.status_code}"
                )
            
            if response.status_code >= 400:
                logger.error("LLM returned error %s: %s", response.status_code, response.text[:500])
                raise LlmGatewayUnavailableError(
                    f"LLM request failed with status {response.status_code}"
                )
            
            return response.json()
        
        raise LlmGatewayUnavailableError("Failed to get response from LLM gateway")
    
    def _get_llm_headers(self, token: str) -> dict[str, str]:
        """Build headers for LLM API request."""
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        # Add x-apikey header if configured
        api_key = self._settings.get_api_key()
        if api_key:
            headers["x-apikey"] = api_key
        
        return headers
    
    def _build_prompt(
        self,
        incident_id: str,
        short_description: Optional[str],
        description: Optional[str],
    ) -> str:
        """Build prompt for LLM enrichment."""
        return self._prompt_template.format(
            incident_id=incident_id,
            short_description=short_description or "N/A",
            description=description or "N/A",
        )

    @staticmethod
    def _load_prompt_template(prompt_path: Path) -> str:
        try:
            template = prompt_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise LlmGatewayConfigurationError(
                f"Could not read LLM prompt template: {prompt_path}"
            ) from exc
        if not template:
            raise LlmGatewayConfigurationError(
                f"LLM prompt template is empty: {prompt_path}"
            )
        return template
    
    def _parse_llm_response(self, response: dict) -> IncidentEnrichment:
        """Parse LLM response into IncidentEnrichment."""
        try:
            # Extract the content from the response
            choices = response.get("choices", [])
            if not choices:
                logger.warning("LLM response has no choices")
                return IncidentEnrichment()
            
            message = choices[0].get("message", {})
            content = message.get("content", "")
            
            # Try to parse as JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                logger.warning("Could not parse LLM response as JSON: %s", content[:500])
                # Fallback: use the raw content as summary
                return IncidentEnrichment(
                    summary=LlmSummary(text=content),
                )
            
            # Extract summary
            summary = None
            if "summary" in data:
                summary = LlmSummary(text=data["summary"])

            related_incidents = [
                related_id
                for related_id in data.get("related_incidents", [])
                if isinstance(related_id, str) and related_id.strip()
            ]
            
            # Extract mitigation suggestions
            suggestions = []
            if "mitigation_suggestions" in data:
                for sugg_data in data.get("mitigation_suggestions", []):
                    suggestions.append(
                        MitigationSuggestion(
                            suggestion=sugg_data.get("suggestion", ""),
                            related_incidents=sugg_data.get("related_incidents", []),
                            related_log_ids=sugg_data.get("related_log_ids", []),
                        )
                    )
            
            return IncidentEnrichment(
                summary=summary,
                mitigation_suggestions=suggestions,
                related_incidents=related_incidents,
            )
        except (KeyError, TypeError) as exc:
            logger.error("Failed to parse LLM response: %s", exc)
            raise LlmGatewayUnavailableError("Invalid LLM response format") from exc
