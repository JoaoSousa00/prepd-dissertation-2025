import logging
import os
import time
from typing import Optional

import httpx2 as httpx

from src.domain.documentation import (
    DocumentationPage,
    DocumentationSourceUnauthorizedError,
    DocumentationSourceUnavailableError,
)
from src.shared.observability import get_current_request_context
from src.shared.tracing import set_span_status_error, set_span_status_ok, start_span

logger = logging.getLogger(__name__)
DEFAULT_CONFLUENCE_SPACE_KEY = "CDLOS"


class ConfluenceClient:
    """Minimal PAT-based Confluence adapter implementing DocumentationSourceAdapter for the CD Location Services space."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        pat_token: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        transport: Optional[httpx.BaseTransport] = None,
    ):
        raw_base_url = (base_url or os.getenv("CONFLUENCE_BASE_URL", "https://atc.bmwgroup.net/confluence")).strip()
        self.base_url = self._normalize_base_url(raw_base_url)
        self.space_key = (os.getenv("CONFLUENCE_SPACE_KEY", DEFAULT_CONFLUENCE_SPACE_KEY) or DEFAULT_CONFLUENCE_SPACE_KEY).strip()
        self.pat_token = self._normalize_token(
            pat_token or os.getenv("CONFLUENCE_PAT_TOKEN") or os.getenv("CONFLUENCE_API_TOKEN") or ""
        )
        self.timeout_seconds = float(timeout_seconds or os.getenv("CONFLUENCE_TIMEOUT_SECONDS", "30"))
        self._transport = transport

    def search_pages(self, search_query: str, limit: Optional[int] = None) -> list[DocumentationPage]:
        if not search_query or not search_query.strip():
            return []
        if not self.pat_token:
            raise DocumentationSourceUnauthorizedError("Confluence PAT token is missing")

        context = get_current_request_context()
        with start_span(
            "confluence.search",
            request_id=context.request_id if context is not None else None,
            workflow="incident_summary",
            component="confluence",
            attributes={
                "operation": "search_pages",
                "space_key": self.space_key,
                "query": search_query,
                "limit": limit or 25,
                "langfuse.observation.type": "span",
            },
        ) as span:
            started_at = time.perf_counter()
            try:
                query = f'space="{self._escape_cql(self.space_key)}" AND type=page AND text ~ "{self._escape_cql(search_query)}"'
                params = {
                    "cql": query,
                    "limit": str(limit or 25),
                    "expand": "space,version,body.storage.value",
                }

                response = self._request("GET", self._api_url("/content/search"), params=params)
                payload = response.json()
                results = []
                for item in payload.get("results", []):
                    page_id = str(item.get("id") or item.get("_id") or "").strip()
                    title = str(item.get("title") or "Untitled page").strip()
                    if not page_id:
                        continue
                    page = DocumentationPage(
                        id=page_id,
                        title=title,
                        url=self._page_url(page_id),
                        body=self._extract_body(item),
                    )
                    results.append(page)
                set_span_status_ok(span, (time.perf_counter() - started_at) * 1000)
                return results
            except Exception as exc:
                set_span_status_error(
                    span,
                    error_code="confluence_search_failure",
                    error_message=str(exc),
                    latency_ms=(time.perf_counter() - started_at) * 1000,
                )
                raise

    def _request(self, method: str, url: str, params: Optional[dict] = None) -> httpx.Response:
        logger.debug("Confluence %s request url=%s params=%s", method.upper(), url, params)
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.pat_token}",
        }
        try:
            with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
                response = client.request(method.upper(), url, headers=headers, params=params)
                logger.debug(
                    "Confluence %s response status=%s body=%s",
                    method.upper(),
                    response.status_code,
                    self._safe_body_preview(response.text),
                )
                if response.status_code == 401:
                    auth_hint = response.headers.get("www-authenticate", "")
                    raise DocumentationSourceUnauthorizedError(
                        f"Confluence unauthorized (401) for {url}; "
                        f"www-authenticate={auth_hint!r}; "
                        f"response={self._safe_body_preview(response.text, max_chars=200)}"
                    )
                if response.status_code >= 400:
                    raise DocumentationSourceUnavailableError(
                        f"Confluence request failed with status {response.status_code}: {response.text[:500]}"
                    )
                return response
        except httpx.HTTPError as exc:
            raise DocumentationSourceUnavailableError(f"Confluence request failed: {exc}") from exc

    def _api_url(self, path: str) -> str:
        return f"{self.base_url}/rest/api{path}"

    @staticmethod
    def _normalize_base_url(value: str) -> str:
        normalized = value.rstrip("/")
        for suffix in ("/rest/api/content", "/rest/api"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return normalized.rstrip("/")

    @staticmethod
    def _normalize_token(value: str) -> str:
        normalized = value.strip().strip('"').strip("'")
        if normalized.lower().startswith("bearer "):
            normalized = normalized[7:].strip()
        return normalized

    @staticmethod
    def _page_url(page_id: str) -> str:
        base = os.getenv("CONFLUENCE_BASE_URL", "https://atc.bmwgroup.net/confluence").rstrip("/")
        return f"{base}/pages/viewpage.action?pageId={page_id}"

    def _map_page(self, payload: dict) -> Optional[DocumentationPage]:
        page_id = str(payload.get("id") or payload.get("_id") or "").strip()
        title = str(payload.get("title") or "Untitled page").strip()
        if not page_id:
            return None
        return DocumentationPage(
            id=page_id,
            title=title,
            url=self._page_url(page_id),
            body=self._extract_body(payload),
        )

    @staticmethod
    def _extract_body(payload: dict) -> Optional[str]:
        body_data = payload.get("body") or {}
        storage = body_data.get("storage") if isinstance(body_data, dict) else None
        if isinstance(storage, dict):
            text = storage.get("value")
            if isinstance(text, str):
                return text
        return None

    @staticmethod
    def _escape_cql(value: str) -> str:
        return value.replace('"', '\\"')

    @staticmethod
    def _safe_body_preview(text: str, max_chars: int = 500) -> str:
        if len(text) <= max_chars:
            return text
        return f"{text[:max_chars]}...(truncated)"
