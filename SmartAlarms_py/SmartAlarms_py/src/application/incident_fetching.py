import logging
from typing import Iterable, List

from src.domain.incident import (
    BaseIncident,
    IncidentSourceAdapter,
    IncidentSourceUnavailableError,
)
from src.shared.observability import get_current_request_context

logger = logging.getLogger(__name__)


class IncidentFetchingService:
    def __init__(self, incident_source: IncidentSourceAdapter):
        self._incident_source = incident_source

    def fetch_base_incidents(self, incident_ids: Iterable[str]) -> List[BaseIncident]:
        incidents: List[BaseIncident] = []
        context = get_current_request_context()
        if context is not None:
            ordered_ids = [value.strip() for value in incident_ids if value and value.strip()]
            if ordered_ids:
                context.main_incident = context.main_incident or ordered_ids[0]
        for incident_id in incident_ids:
            normalized_id = incident_id.strip()
            if not normalized_id:
                continue
            try:
                incident = self._incident_source.fetch_base_incident(normalized_id)
            except IncidentSourceUnavailableError as exc:
                logger.warning("Skipping incident %s — source unavailable: %s", normalized_id, exc)
                continue
            if incident is not None:
                incidents.append(incident)
                if context is not None:
                    context.record_fetched_incident(incident.id)
        return incidents
