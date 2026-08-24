from typing import Optional, List
from dataclasses import dataclass


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
    resolution_suggestions: List[ResolutionSuggestion] = None
    related_log_ids: List[str] = None

    def __post_init__(self):
        if self.resolution_suggestions is None:
            self.resolution_suggestions = []
        if self.related_log_ids is None:
            self.related_log_ids = []
