import logging
import time
from typing import Iterable, List, Optional

from src.application.incident_fetching import IncidentFetchingService
from src.domain.incident import IncidentDetails, ResolutionSuggestion
from src.domain.llm import LlmGateway, LlmGatewayError
from src.shared.observability import bind_request_context, get_current_request_context, log_request_summary

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
        context = get_current_request_context()
        if context is None:
            with bind_request_context():
                return self._fetch_incident_details(incident_ids, emit_summary=True)
        return self._fetch_incident_details(incident_ids, emit_summary=False)

    def _fetch_incident_details(self, incident_ids: Iterable[str], emit_summary: bool = False) -> List[IncidentDetails]:
        context = get_current_request_context()
        ordered_ids = [value.strip() for value in incident_ids if value and value.strip()]
        if context is not None and ordered_ids:
            context.main_incident = context.main_incident or ordered_ids[0]

        base_incidents = self._incident_fetching_service.fetch_base_incidents(ordered_ids)
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
                    if context is not None:
                        context.record_llm_error(str(exc), 500)
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
                    if context is not None:
                        if enrichment.related_incidents:
                            for related_id in detail.related_incidents:
                                context.record_title_related_incident(related_id)
                        if enrichment.usage is not None:
                            context.record_llm_usage(
                                tokens_in=enrichment.usage.tokens_in,
                                tokens_out=enrichment.usage.tokens_out,
                                cost_usd=enrichment.usage.estimated_cost,
                            )
            detail.request_latency_ms = (time.perf_counter() - started_at) * 1000
            details.append(detail)

        if context is not None:
            context.suggestions_number += sum(len(item.resolution_suggestions) for item in details)
            context.latency_ms = (
                context.latency_ms
                if context.latency_ms is not None
                else sum(item.request_latency_ms or 0 for item in details)
            )
            context.summary_completed = bool(details)
            if not context.fetched_incidents and ordered_ids:
                context.fetched_incidents.extend(ordered_ids)

        if emit_summary:
            log_request_summary()
        return details
