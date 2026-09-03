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
    LlmUsage,
    LlmSummary,
    MitigationSuggestion,
)
from src.infrastructure.llm_config import LlmGatewaySettings, load_llm_gateway_settings
from src.shared.observability import get_current_request_context
from src.shared.tracing import inject_trace_context, set_span_status_error, set_span_status_ok, start_span

logger = logging.getLogger(__name__)
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parent / "prompt" / "incident_enrichment_prompt.txt"
)
DEFAULT_CA_DOWNLOAD_TIMEOUT_SECONDS = 30.0

MODEL_PRICING = {
    "gpt-5": {
        "prompt_tokens": 1.38e-5,
        "cached_prompt_tokens": 1.4e-6,
        "reasoning_tokens": 1.38e-5,
        "completion_tokens": 1.10e-4,
    },
    "claude-haiku-4-5": {
        "prompt_tokens": 1.1e-5,
        "cached_prompt_tokens": 1.1e-6,
        "reasoning_tokens": 5.5e-5,
        "completion_tokens": 5.5e-5,
    },
    "claude-haiku-4.5": {
        "prompt_tokens": 1.1e-5,
        "cached_prompt_tokens": 1.1e-6,
        "reasoning_tokens": 5.5e-5,
        "completion_tokens": 5.5e-5,
    },
}


def _download_bmw_ca_cert(path: Path, ca_cert_url: str) -> str:
    """Download the BMW CA certificate when it is not present locally."""
    if path.exists():
        return str(path)

    if not ca_cert_url:
        raise LlmGatewayConfigurationError(
            "CA_CERT_URL is required when the BMW CA certificate is missing"
        )

    logger.debug("Downloading BMW CA certificate from %s to %s", ca_cert_url, path)
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
    
    _shared_token_cache: Optional[str] = None
    _shared_token_expiry: float = 0

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
        context = get_current_request_context()
        if context is not None:
            context.main_incident = context.main_incident or incident_id
        if not self._settings.gateway_enabled:
            if context is not None:
                context.record_llm_error("LLM gateway is disabled", 503)
            raise LlmGatewayDisabledError("LLM gateway is disabled")
        
        with start_span(
            "llm.complete",
            request_id=context.request_id if context is not None else None,
            component="llm",
            attributes={
                "operation": "complete",
                "provider": "gaia",
                "model": self._settings.model,
                "retry_count": 0,
                "langfuse.observation.type": "generation",
                "gen_ai.operation.name": "chat",
                "gen_ai.system": "gaia",
                "gen_ai.request.model": self._settings.model,
            },
        ) as llm_span:
            started_at = time.perf_counter()
            try:
                token = self._get_access_token()
                prompt = self._build_prompt(incident_id, short_description, description)
                requested_max_tokens = max_tokens or self._settings.default_max_tokens
                response, retry_count = self._call_llm(
                    prompt=prompt,
                    token=token,
                    max_tokens=requested_max_tokens,
                )
                enrichment = self._parse_llm_response(response)
                if llm_span is not None:
                    llm_content = self._extract_message_content(
                        (response.get("choices") or [{}])[0].get("message", {}).get("content")
                    )
                    llm_span.set_attribute("langfuse.observation.model.name", self._settings.model)
                    llm_span.set_attribute(
                        "langfuse.observation.model.parameters",
                        json.dumps({"max_tokens": requested_max_tokens}, ensure_ascii=True),
                    )
                    llm_span.set_attribute(
                        "langfuse.observation.input",
                        json.dumps(
                            {
                                "incident_id": incident_id,
                                "short_description": short_description,
                                "description": description,
                                "prompt": prompt,
                            },
                            ensure_ascii=True,
                        ),
                    )
                    llm_span.set_attribute("gen_ai.prompt", prompt)
                    llm_span.set_attribute("provider", "gaia")
                    llm_span.set_attribute("model", self._settings.model)
                    llm_span.set_attribute("llm.model_name", self._settings.model)
                    llm_span.set_attribute("retry_count", retry_count)
                    llm_span.set_attribute("gen_ai.request.max_tokens", requested_max_tokens)
                    llm_span.set_attribute("gen_ai.response.model", self._settings.model)
                    if enrichment.usage is not None:
                        usage_details: dict[str, int | float] = {}
                        if enrichment.usage.tokens_in is not None:
                            llm_span.set_attribute("tokens_in", enrichment.usage.tokens_in)
                            llm_span.set_attribute("gen_ai.usage.input_tokens", enrichment.usage.tokens_in)
                            llm_span.set_attribute("llm.token_count.prompt", enrichment.usage.tokens_in)
                            usage_details["input_tokens"] = enrichment.usage.tokens_in
                        if enrichment.usage.tokens_out is not None:
                            llm_span.set_attribute("tokens_out", enrichment.usage.tokens_out)
                            llm_span.set_attribute("gen_ai.usage.output_tokens", enrichment.usage.tokens_out)
                            llm_span.set_attribute("llm.token_count.completion", enrichment.usage.tokens_out)
                            usage_details["output_tokens"] = enrichment.usage.tokens_out
                        if enrichment.usage.tokens_total is not None:
                            llm_span.set_attribute("gen_ai.usage.total_tokens", enrichment.usage.tokens_total)
                            llm_span.set_attribute("llm.token_count.total", enrichment.usage.tokens_total)
                            usage_details["total_tokens"] = enrichment.usage.tokens_total
                        if usage_details:
                            llm_span.set_attribute(
                                "langfuse.observation.usage_details",
                                json.dumps(usage_details, ensure_ascii=True),
                            )
                        if enrichment.usage.estimated_cost is not None:
                            llm_span.set_attribute("cost_usd", enrichment.usage.estimated_cost)
                            llm_span.set_attribute("gen_ai.usage.cost", enrichment.usage.estimated_cost)
                            llm_span.set_attribute(
                                "langfuse.observation.cost_details",
                                json.dumps({"total": enrichment.usage.estimated_cost}, ensure_ascii=True),
                            )
                    if llm_content.strip():
                        llm_span.set_attribute(
                            "langfuse.observation.output",
                            llm_content,
                        )
                        llm_span.set_attribute("gen_ai.completion", llm_content)
                set_span_status_ok(llm_span, (time.perf_counter() - started_at) * 1000)
                return enrichment
            except (LlmGatewayUnavailableError, LlmGatewayConfigurationError) as exc:
                set_span_status_error(
                    llm_span,
                    error_code="llm_failure",
                    error_message=str(exc),
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                )
                raise
    
    def _get_access_token(self) -> str:
        """Get OAuth access token from GAIA auth endpoint."""
        context = get_current_request_context()
        started_at = time.perf_counter()
        if self._token_cache and time.time() < self._token_expiry:
            return self._token_cache

        if self.__class__._shared_token_cache and time.time() < self.__class__._shared_token_expiry:
            self._token_cache = self.__class__._shared_token_cache
            self._token_expiry = self.__class__._shared_token_expiry
            return self._token_cache

        # Return cached token if still valid
        if self._token_cache and time.time() < self._token_expiry:
            return self._token_cache

        with start_span(
            "llm.fetch_token",
            request_id=context.request_id if context is not None else None,
            component="llm",
            attributes={
                "operation": "fetch_token",
                "endpoint": self._settings.auth_endpoint,
            },
        ) as auth_span:
            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
            }
            inject_trace_context(headers)
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
                        headers=headers,
                    )
            except httpx.HTTPError as exc:
                latency_ms = (time.perf_counter() - started_at) * 1000
                set_span_status_error(
                    auth_span,
                    error_code="llm_auth_http_error",
                    error_message=str(exc),
                    latency_ms=latency_ms,
                )
                if context is not None:
                    context.record_llm_error(f"Failed to authenticate with LLM gateway: {exc}", 500)
                    context.log_event(
                        "ERROR",
                        "llm",
                        500,
                        f"Failed to authenticate with LLM gateway: {exc}",
                        latency_ms=latency_ms,
                    )
                logger.error("Failed to connect to LLM auth endpoint: %s", exc)
                raise LlmGatewayUnavailableError(
                    f"Failed to authenticate with LLM gateway: {exc}"
                ) from exc

            latency_ms = (time.perf_counter() - started_at) * 1000
            if response.status_code >= 400:
                set_span_status_error(
                    auth_span,
                    error_code=f"http_{response.status_code}",
                    error_message=f"LLM auth returned HTTP {response.status_code}",
                    latency_ms=latency_ms,
                )
            else:
                set_span_status_ok(auth_span, latency_ms)
            if auth_span is not None:
                auth_span.set_attribute("status_code", response.status_code)

        if context is not None:
            context.record_llm_status(response.status_code)
            context.log_event(
                "DEBUG",
                "llm",
                response.status_code,
                "",
                latency_ms=latency_ms,
            )
        
        if response.status_code != 200:
            logger.error(
                "LLM auth endpoint returned %s: %s",
                response.status_code,
                response.text[:500],
            )
            if context is not None:
                context.record_llm_error(
                    f"LLM authentication failed with status {response.status_code}",
                    response.status_code,
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
            self.__class__._shared_token_cache = token
            self.__class__._shared_token_expiry = self._token_expiry
            return token
        except (ValueError, KeyError) as exc:
            if context is not None:
                context.record_llm_error("Invalid authentication response from LLM gateway", 500)
            logger.error("Invalid LLM auth response: %s", exc)
            raise LlmGatewayConfigurationError(
                "Invalid authentication response from LLM gateway"
            ) from exc
    
    def _call_llm(self, prompt: str, token: str, max_tokens: int) -> tuple[dict, int]:
        """Call LLM gateway with retry logic."""
        context = get_current_request_context()
        endpoint = f"{self._settings.endpoint.rstrip('/')}/chat/completions"
        base_headers = self._get_llm_headers(token)
        base_headers["Authorization"] = f"Bearer {token}"
        request_body = {
            "model": self._settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            "max_tokens": max_tokens,
        }

        for attempt in range(self._settings.max_retries):
            started_at = time.perf_counter()
            headers = dict(base_headers)
            inject_trace_context(headers)
            span_request_id = context.request_id if context is not None else None
            with start_span(
                "llm.request_attempt",
                request_id=span_request_id,
                component="llm",
                attributes={
                    "operation": "request_attempt",
                    "endpoint": endpoint,
                    "retry_count": attempt,
                    "provider": "gaia",
                    "model": self._settings.model,
                },
            ) as attempt_span:
                try:
                    with httpx.Client(
                        timeout=self._settings.request_timeout_seconds,
                        transport=self._transport,
                        verify=self._verify,
                    ) as client:
                        logger.debug(
                            "Sending LLM request. url=%s headers=%s body=%s",
                            endpoint,
                            self._sanitize_headers(headers),
                            self._safe_preview(request_body),
                        )
                        response = client.post(
                            endpoint,
                            headers=headers,
                            json=request_body,
                        )
                        logger.debug(
                            "Received LLM response. status=%s headers=%s body=%s",
                            response.status_code,
                            self._sanitize_headers(dict(response.headers)),
                            self._safe_preview(response.text),
                        )
                except httpx.HTTPError as exc:
                    set_span_status_error(
                        attempt_span,
                        error_code="llm_request_http_error",
                        error_message=str(exc),
                        latency_ms=(time.perf_counter() - started_at) * 1000,
                    )
                    if context is not None:
                        context.record_llm_error(f"LLM gateway unavailable after {attempt + 1} attempts: {exc}", 500)
                        context.log_event(
                            "ERROR",
                            "llm",
                            500,
                            f"LLM gateway unavailable after {attempt + 1} attempts: {exc}",
                            latency_ms=(time.perf_counter() - started_at) * 1000,
                        )
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

                latency_ms = (time.perf_counter() - started_at) * 1000
                if response.status_code >= 400:
                    set_span_status_error(
                        attempt_span,
                        error_code=f"http_{response.status_code}",
                        error_message=f"LLM returned HTTP {response.status_code}",
                        latency_ms=latency_ms,
                    )
                else:
                    set_span_status_ok(attempt_span, latency_ms)
                if attempt_span is not None:
                    attempt_span.set_attribute("status_code", response.status_code)

            if context is not None:
                context.record_llm_status(response.status_code)
                context.log_event(
                    "DEBUG",
                    "llm",
                    response.status_code,
                    "",
                    latency_ms=latency_ms,
                )
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
                if context is not None:
                    context.record_llm_error(
                        f"LLM gateway returned status {response.status_code}",
                        response.status_code,
                    )
                raise LlmGatewayUnavailableError(
                    f"LLM gateway returned status {response.status_code}"
                )
            
            if response.status_code >= 400:
                logger.error("LLM returned error %s: %s", response.status_code, response.text[:500])
                if context is not None:
                    context.record_llm_error(
                        f"LLM request failed with status {response.status_code}",
                        response.status_code,
                    )
                raise LlmGatewayUnavailableError(
                    f"LLM request failed with status {response.status_code}"
                )
            
            return response.json(), attempt
        
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
            usage = self._parse_usage(response)
            if not choices:
                logger.warning(
                    "LLM response has no choices. response=%s",
                    self._safe_preview(response),
                )
                return IncidentEnrichment(usage=usage)
            
            message = choices[0].get("message", {})
            content = self._extract_message_content(message.get("content"))
            if not content.strip():
                finish_reason = choices[0].get("finish_reason")
                logger.warning(
                    "LLM returned empty message content. finish_reason=%s response=%s",
                    finish_reason,
                    self._safe_preview(response),
                )
                return IncidentEnrichment(usage=usage)
            
            # Try to parse as JSON
            try:
                data = json.loads(content)
            except json.JSONDecodeError:
                logger.warning(
                    "Could not parse LLM response as JSON. content=%s response=%s",
                    content[:500],
                    self._safe_preview(response),
                )
                # Fallback: use the raw content as summary
                return IncidentEnrichment(
                    summary=LlmSummary(text=content),
                    usage=usage,
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
                usage=usage,
            )
        except (KeyError, TypeError) as exc:
            logger.error("Failed to parse LLM response: %s", exc)
            raise LlmGatewayUnavailableError("Invalid LLM response format") from exc

    @staticmethod
    def _extract_message_content(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = content.get("text")
            return text if isinstance(text, str) else json.dumps(content)
        if isinstance(content, list):
            chunks: list[str] = []
            for item in content:
                if isinstance(item, str):
                    if item.strip():
                        chunks.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text)
                        continue
                    value = item.get("content")
                    if isinstance(value, str) and value.strip():
                        chunks.append(value)
            return "\n".join(chunks)
        return ""

    @staticmethod
    def _safe_preview(payload: object, max_chars: int = 1200) -> str:
        try:
            serialized = json.dumps(payload, ensure_ascii=True)
        except TypeError:
            serialized = str(payload)
        if len(serialized) <= max_chars:
            return serialized
        return f"{serialized[:max_chars]}...(truncated)"

    @staticmethod
    def _sanitize_headers(headers: dict[str, object]) -> dict[str, str]:
        redacted_headers = {
            "authorization",
            "proxy-authorization",
            "x-apikey",
            "api-key",
            "x-api-key",
        }
        sanitized: dict[str, str] = {}
        for key, value in headers.items():
            sanitized[key] = "******" if key.lower() in redacted_headers else str(value)
        return sanitized

    def _parse_usage(self, response: dict) -> Optional[LlmUsage]:
        usage_data_raw = response.get("usage")
        usage_data = usage_data_raw if isinstance(usage_data_raw, dict) else {}

        tokens_in = self._coerce_int(
            self._first_non_none(
                usage_data.get("prompt_tokens"),
                usage_data.get("input_tokens"),
                usage_data.get("tokens_in"),
            )
        )
        tokens_out = self._coerce_int(
            self._first_non_none(
                usage_data.get("completion_tokens"),
                usage_data.get("output_tokens"),
                usage_data.get("tokens_out"),
            )
        )
        tokens_total = self._coerce_int(
            self._first_non_none(
                usage_data.get("total_tokens"),
                usage_data.get("tokens_total"),
            )
        )
        if tokens_total is None and tokens_in is not None and tokens_out is not None:
            tokens_total = tokens_in + tokens_out

        model = self._first_non_none(
            response.get("model"),
            usage_data.get("model"),
            self._settings.model,
        )

        estimated_cost = self._extract_reported_cost(response, usage_data)
        if estimated_cost is None:
            estimated_cost = self._estimate_usage_cost(model, usage_data)

        if all(
            value is None
            for value in (model, tokens_in, tokens_out, tokens_total, estimated_cost)
        ):
            return None

        return LlmUsage(
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            tokens_total=tokens_total,
            estimated_cost=estimated_cost,
        )

    def _extract_reported_cost(self, response: dict, usage_data: dict) -> Optional[float]:
        response_cost = response.get("cost")
        usage_cost = usage_data.get("cost")
        candidates = (
            self._deep_get(response_cost, "total"),
            self._deep_get(response_cost, "interaction", "total"),
            usage_data.get("estimated_cost"),
            usage_data.get("total_cost"),
            self._deep_get(usage_cost, "total"),
            self._deep_get(usage_cost, "interaction", "total"),
            usage_cost,
            response_cost,
        )
        for candidate in candidates:
            parsed = self._coerce_float(candidate)
            if parsed is not None:
                return parsed
        return None

    def _estimate_usage_cost(self, model: object, usage_data: dict) -> Optional[float]:
        """Estimate LLM usage cost from model pricing when the provider omits it."""
        normalized_model = self._normalize_model_name(model)
        if normalized_model is None:
            return None

        pricing = self._lookup_model_pricing(normalized_model)
        if pricing is None:
            return None

        tokens_in = self._coerce_int(
            self._first_non_none(
                usage_data.get("prompt_tokens"),
                usage_data.get("input_tokens"),
                usage_data.get("tokens_in"),
            )
        )
        tokens_out = self._coerce_int(
            self._first_non_none(
                usage_data.get("completion_tokens"),
                usage_data.get("output_tokens"),
                usage_data.get("tokens_out"),
            )
        )
        cached_prompt_tokens = self._coerce_int(
            self._first_non_none(
                usage_data.get("cached_prompt_tokens"),
                usage_data.get("cached_input_tokens"),
                usage_data.get("cached_tokens_in"),
                self._deep_get(usage_data, "prompt_tokens_details", "cached_tokens"),
            )
        )
        reasoning_tokens = self._coerce_int(
            self._first_non_none(
                usage_data.get("reasoning_tokens"),
                usage_data.get("reasoning_tokens_in"),
                self._deep_get(usage_data, "completion_tokens_details", "reasoning_tokens"),
            )
        )

        total_cost = 0.0
        if tokens_in is not None:
            total_cost += tokens_in * pricing.get("prompt_tokens", 0.0)
        if cached_prompt_tokens is not None:
            total_cost += cached_prompt_tokens * pricing.get("cached_prompt_tokens", pricing.get("prompt_tokens", 0.0))
        if tokens_out is not None:
            total_cost += tokens_out * pricing.get("completion_tokens", 0.0)
        if reasoning_tokens is not None:
            total_cost += reasoning_tokens * pricing.get("reasoning_tokens", pricing.get("completion_tokens", 0.0))

        return round(total_cost, 12) if total_cost > 0 else None

    @staticmethod
    def _normalize_model_name(model: object) -> Optional[str]:
        if model is None:
            return None
        normalized = str(model).strip().lower()
        if not normalized:
            return None
        for prefix in ("openai/", "anthropic/", "azure-openai/", "azure/", "aws/", "bedrock/"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]
                break
        return normalized.replace(" ", "")

    @staticmethod
    def _lookup_model_pricing(model_name: str) -> Optional[dict[str, float]]:
        if not model_name:
            return None
        for key, pricing in MODEL_PRICING.items():
            if model_name == key or model_name.startswith(key):
                return pricing
        return None

    @staticmethod
    def _first_non_none(*values: object) -> object:
        for value in values:
            if value is not None:
                return value
        return None

    @staticmethod
    def _deep_get(value: object, *keys: str) -> object:
        current = value
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current

    @staticmethod
    def _coerce_int(value: object) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return int(stripped)
            except ValueError:
                return None
        return None

    @staticmethod
    def _coerce_float(value: object) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            try:
                return float(stripped)
            except ValueError:
                return None
        return None
