from typing import Optional
import logging

from src.domain.documentation import DocumentationPage, DocumentationSourceAdapter
from src.infrastructure.llm_gateway import GaiaLlmGatewayAdapter

logger = logging.getLogger(__name__)


class DocumentationEnrichmentService:
    """Service to search, filter, and summarize documentation pages."""

    def __init__(
        self,
        documentation_adapter: DocumentationSourceAdapter,
        llm_gateway: GaiaLlmGatewayAdapter,
    ):
        self.documentation = documentation_adapter
        self.llm = llm_gateway

    def fetch_and_filter_relevant_pages(
        self,
        incident_id: str,
        incident_description: str,
        search_query: str,
        max_pages: int = 10,
    ) -> list[dict]:
        """
        Search documentation, evaluate relevance per page, return extracted content of relevant ones.
        
        Returns:
            List of dicts with keys: title, url, extracted_content
        """
        if not search_query or not search_query.strip():
            return []
        
        try:
            # 1. Search documentation (response already includes body.storage.value)
            pages = self.documentation.search_pages(search_query, limit=max_pages)
        except Exception as exc:
            logger.error(f"Documentation search failed: {exc}")
            return []
        
        relevant_pages = []
        
        # 2. For each page: 1 LLM call to check relevance and extract content
        for page in pages:
            try:
                result = self.llm.check_documentation_relevance(
                    incident_id=incident_id,
                    incident_description=incident_description,
                    page_title=page.title,
                    page_body=page.body or "",
                )
                
                if result.get("is_relevant") and result.get("extracted_content"):
                    relevant_pages.append({
                        "title": page.title,
                        "url": page.url,
                        "extracted_content": result["extracted_content"],
                    })
            except Exception as exc:
                logger.warning(f"Relevance check failed for page {page.title}: {exc}")
                continue
        
        return relevant_pages
