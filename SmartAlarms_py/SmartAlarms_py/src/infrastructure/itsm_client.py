import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from src.domain.incident import (
    BaseIncident,
    IncidentSourceAdapter,
    IncidentSourceUnauthorizedError,
    IncidentSourceUnavailableError,
)
from src.shared.observability import get_current_request_context

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.int.gcp.bmw.cloud/nowplatform/v1"
DEFAULT_HOST = "api.int.gcp.bmw.cloud"
DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ItsmClientSettings:
    base_url: str = DEFAULT_BASE_URL
    host: str = DEFAULT_HOST
    authorization: str = ""
    api_key: str = ""
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS


def load_itsm_client_settings() -> ItsmClientSettings:
    return ItsmClientSettings(
        base_url=os.getenv("ITSM_BASE_URL", DEFAULT_BASE_URL),
        host=os.getenv("ITSM_HOST", DEFAULT_HOST),
        authorization=os.getenv("ITSM_AUTHORIZATION", ""),
        api_key=os.getenv("ITSM_API_KEY", ""),
        timeout_seconds=float(os.getenv("ITSM_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
    )


class ItsmIncidentSourceAdapter(IncidentSourceAdapter):
    def __init__(
        self,
        settings: Optional[ItsmClientSettings] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        self._settings = settings or load_itsm_client_settings()
        self._client = httpx.Client(
            base_url=self._settings.base_url.rstrip("/"),
            timeout=self._settings.timeout_seconds,
            transport=transport,
        )

    def fetch_base_incident(self, incident_id: str) -> Optional[BaseIncident]:
        self._validate_credentials()
        context = get_current_request_context()
        started_at = time.perf_counter()
        try:
            response = self._client.get(
                f"/incident/{incident_id}",
                headers=self._headers(),
            )
        except httpx.HTTPError as exc:
            if context is not None:
                context.record_itsm_error(f"ITSM incident source is unavailable: {exc}", 500)
                context.log_event(
                    "ERROR",
                    "itsm",
                    500,
                    f"ITSM incident source is unavailable: {exc}",
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                )
            raise IncidentSourceUnavailableError("ITSM incident source is unavailable") from exc

        latency_ms = (time.perf_counter() - started_at) * 1000
        logger.debug("ITSM %s → HTTP %s", incident_id, response.status_code)
        if context is not None:
            context.record_itsm_status(response.status_code)
            context.log_event(
                "DEBUG",
                "itsm",
                response.status_code,
                "",
                latency_ms=latency_ms,
            )

        if response.status_code == 404:
            return None
        if response.status_code in {401, 403}:
            if context is not None:
                context.record_itsm_error("ITSM credentials are missing or were rejected", response.status_code)
            raise IncidentSourceUnauthorizedError(
                "ITSM credentials are missing or were rejected"
            )
        if response.status_code >= 400:
            logger.warning("ITSM returned %s for %s — body: %s", response.status_code, incident_id, response.text[:500])
            if context is not None:
                context.record_itsm_error(
                    f"ITSM incident source returned {response.status_code}",
                    response.status_code,
                )
                context.log_event(
                    "ERROR",
                    "itsm",
                    response.status_code,
                    f"ITSM incident source returned {response.status_code}",
                    latency_ms=latency_ms,
                )
            raise IncidentSourceUnavailableError(
                f"ITSM incident source returned {response.status_code}"
            )

        payload = response.json()
        logger.debug("ITSM body for %s: %s", incident_id, payload)
        record = self._extract_record(payload)
        if record is None:
            logger.warning("ITSM payload for %s could not be extracted: %s", incident_id, payload)
            if context is not None:
                context.record_itsm_error("ITSM incident payload is empty", 500)
            raise IncidentSourceUnavailableError("ITSM incident payload is empty")

        record_id = str(record.get("id") or record.get("number") or incident_id)
        short_description = record.get("shortDescription") or record.get("short_description")
        description = record.get("description")

        if context is not None:
            context.record_fetched_incident(record_id)

        return BaseIncident(
            id=record_id,
            short_description=short_description,
            description=description,
        )

    def _validate_credentials(self) -> None:
        if not self._settings.authorization or not self._settings.api_key:
            raise IncidentSourceUnauthorizedError(
                "ITSM credentials are missing. Set ITSM_AUTHORIZATION and ITSM_API_KEY."
            )

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Host": self._settings.host,
        }
        if self._settings.authorization:
            headers["Authorization"] = self._settings.authorization
        if self._settings.api_key:
            headers["x-apikey"] = self._settings.api_key
        return headers

    @staticmethod
    def _extract_record(payload: Any) -> Optional[dict[str, Any]]:
        if isinstance(payload, dict):
            result = payload.get("result")
            if isinstance(result, dict):
                return result
            if isinstance(result, list) and result and isinstance(result[0], dict):
                return result[0]
            return payload
        return None
