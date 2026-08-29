import json
import logging
import time
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


class GaiaLlmGatewayAdapter(LlmGateway):
    """LLM gateway adapter for GAIA integration.
    
    Handles OAuth authentication, retries, timeouts, and CA certificate verification.
    """
    
    def __init__(
        self,
        settings: Optional[LlmGatewaySettings] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._settings = settings or load_llm_gateway_settings()
        self._transport = transport
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
            with httpx.Client(timeout=self._settings.auth_timeout_seconds) as client:
                response = client.post(
                    self._settings.auth_endpoint,
                    json={
                        "client_id": self._settings.api_key,
                        "client_secret": self._settings.client_secret,
                        "grant_type": "client_credentials",
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
        return f"""Analyze the following incident and provide:
1. A natural-language summary (1-2 sentences)
2. Related incident references if applicable
3. Mitigation suggestions

Incident ID: {incident_id}
Short Description: {short_description or 'N/A'}
Description: {description or 'N/A'}

Respond in JSON format with keys: summary, related_incidents (array of IDs), mitigation_suggestions (array of objects with 'suggestion', 'related_incidents', 'related_log_ids')."""
    
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
            )
        except (KeyError, TypeError) as exc:
            logger.error("Failed to parse LLM response: %s", exc)
            raise LlmGatewayUnavailableError("Invalid LLM response format") from exc
