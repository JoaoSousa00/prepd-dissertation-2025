from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class RelatedPage:
    title: str
    url: str


@dataclass
class ConfluencePage:
    id: str
    title: str
    url: str
    body: Optional[str] = None
    children: list["ConfluencePage"] = field(default_factory=list)


class ConfluenceSourceUnauthorizedError(RuntimeError):
    """Raised when Confluence credentials are missing or rejected."""


class ConfluenceSourceUnavailableError(RuntimeError):
    """Raised when Confluence cannot serve a request."""


@runtime_checkable
class ConfluenceSourceAdapter(Protocol):
    def search_pages(self, search_query: str, limit: Optional[int] = None) -> list[ConfluencePage]:
        """Search Confluence for matching documentation pages."""

    def fetch_page_tree(self, page_id: str) -> Optional[ConfluencePage]:
        """Fetch a page and its child pages."""
