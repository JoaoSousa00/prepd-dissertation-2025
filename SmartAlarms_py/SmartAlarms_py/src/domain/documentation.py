from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class RelatedPage:
    title: str
    url: str


@dataclass
class DocumentationPage:
    id: str
    title: str
    url: str
    body: Optional[str] = None


class DocumentationSourceUnauthorizedError(RuntimeError):
    """Raised when documentation source credentials are missing or rejected."""


class DocumentationSourceUnavailableError(RuntimeError):
    """Raised when documentation source cannot serve a request."""


@runtime_checkable
class DocumentationSourceAdapter(Protocol):
    def search_pages(self, search_query: str, limit: Optional[int] = None) -> list[DocumentationPage]:
        """Search documentation source for matching pages."""
