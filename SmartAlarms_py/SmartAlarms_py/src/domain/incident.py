from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from src.domain.llm import LlmUsage


@dataclass(frozen=True)
class BaseIncident:
    id: str
    short_description: Optional[str] = None
    description: Optional[str] = None
    number: Optional[str] = None
    state: Optional[str] = None
    close_notes: Optional[str] = None
    closed_at: Optional[str] = None
    close_code: Optional[str] = None
    hold_reason: Optional[str] = None
    comments: List[str] = field(default_factory=list)
    work_notes: List[str] = field(default_factory=list)
    raw: Optional[Dict[str, Any]] = None


class IncidentSourceUnavailableError(RuntimeError):
    """Raised when the incident source cannot serve a request."""


class IncidentSourceUnauthorizedError(RuntimeError):
    """Raised when the incident source credentials are missing or rejected."""


@runtime_checkable
class IncidentSourceAdapter(Protocol):
    def fetch_base_incident(self, incident_id: str) -> Optional[BaseIncident]:
        """Fetch a single incident record by id."""

    def fetch_same_title_incidents(self, short_description: str, limit: Optional[int] = None) -> List[BaseIncident]:
        """Fetch same-title incident history."""

    def fetch_related_incident_details(self, incident_ids: List[str]) -> List[BaseIncident]:
        """Fetch multiple incident records by number."""


@dataclass
class ResolutionSuggestion:
    confidence: Optional[str] = None
    investigation: Optional[str] = None
    mitigation: Optional[str] = None
    resolution_note: Optional[str] = None
    related_incidents: List[str] = field(default_factory=list)


@dataclass
class IncidentDetails:
    id: str
    short_description: Optional[str] = None
    description: Optional[str] = None
    summary: Optional[str] = None
    related_incidents: List[str] = field(default_factory=list)
    resolution_suggestions: List[ResolutionSuggestion] = field(default_factory=list)
    request_latency_ms: Optional[float] = None
    llm_usage: Optional[LlmUsage] = None
