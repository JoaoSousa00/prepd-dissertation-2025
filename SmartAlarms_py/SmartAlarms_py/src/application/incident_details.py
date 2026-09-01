import logging
import time
from typing import Iterable, List, Optional

from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import IncidentDetails, ResolutionSuggestion
from src.domain.llm import LlmGateway, LlmGatewayError

logger = logging.getLogger(__name__)


class IncidentDetailsService:
    def __init__(
        self,
        incident_fetching_service: IncidentFetchingService,
        llm_gateway: Optional[LlmGateway] = None,
    ):
        self._incident_fetching_service = incident_fetching_service
        self._llm_gateway = llm_gateway

    def fetch_incident_details(self, incident_ids: Iterable[str]) -> List[IncidentDetails]:
        base_incidents = self._incident_fetching_service.fetch_base_incidents(incident_ids)
        details: List[IncidentDetails] = []

        for incident in base_incidents:
            started_at = time.perf_counter()
            detail = IncidentDetails(
                id=incident.id,
                short_description=incident.short_description,
                description=incident.description,
            )

            if self._llm_gateway is not None:
                try:
                    enrichment = self._llm_gateway.enrich_incident(
                        incident_id=incident.id,
                        short_description=incident.short_description,
                        description=incident.description,
                    )
                except LlmGatewayError as exc:
                    logger.warning(
                        "Skipping LLM enrichment for incident %s: %s",
                        incident.id,
                        exc,
                    )
                else:
                    detail.summary = enrichment.summary.text if enrichment.summary else None
                    detail.related_incidents = list(dict.fromkeys(enrichment.related_incidents))
                    detail.resolution_suggestions = [
                        ResolutionSuggestion(
                            suggestion=suggestion.suggestion,
                            related_incidents=suggestion.related_incidents,
                            related_log_ids=suggestion.related_log_ids,
                        )
                        for suggestion in enrichment.mitigation_suggestions
                    ]
                    detail.llm_usage = enrichment.usage
            detail.request_latency_ms = (time.perf_counter() - started_at) * 1000
            details.append(detail)

        return details
