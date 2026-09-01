from dataclasses import dataclass, field
from typing import List, Optional, Protocol, runtime_checkable

from src.domain.llm import LlmUsage


@dataclass(frozen=True)
class BaseIncident:
    id: str
    short_description: Optional[str] = None
    description: Optional[str] = None


class IncidentSourceUnavailableError(RuntimeError):
    """Raised when the incident source cannot serve a request."""


class IncidentSourceUnauthorizedError(RuntimeError):
    """Raised when the incident source credentials are missing or rejected."""


@runtime_checkable
class IncidentSourceAdapter(Protocol):
    def fetch_base_incident(self, incident_id: str) -> Optional[BaseIncident]:
        """Fetch a single incident record by id."""


@dataclass
class ResolutionSuggestion:
    suggestion: str
    related_incidents: List[str]
    related_log_ids: List[str]


@dataclass
class IncidentDetails:
    id: str
    short_description: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    related_incidents: List[str] = field(default_factory=list)
    resolution_suggestions: List[ResolutionSuggestion] = field(default_factory=list)
    related_log_ids: List[str] = field(default_factory=list)
    request_latency_ms: Optional[float] = None
    llm_usage: Optional[LlmUsage] = None
