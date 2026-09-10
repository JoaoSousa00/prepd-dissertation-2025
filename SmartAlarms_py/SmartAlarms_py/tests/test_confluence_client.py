from unittest.mock import MagicMock, patch

import httpx2 as httpx

from src.infrastructure.confluence_client import ConfluenceClient


def test_search_pages_restricts_to_cd_location_services_space_and_uses_pat():
    client = ConfluenceClient(base_url="https://example.com/confluence", pat_token="token-123")

    with patch("src.infrastructure.confluence_client.httpx.Client") as mock_client_class:
        mock_instance = MagicMock()
        mock_response = httpx.Response(
            status_code=200,
            json={
                "results": [
                    {"id": "42", "title": "Service health", "body": {"storage": {"value": "body text"}}}
                ]
            },
        )
        mock_instance.request.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_instance
        mock_client_class.return_value.__exit__.return_value = None

        pages = client.search_pages("billing api timeout")

        assert pages[0].title == "Service health"
        assert pages[0].url.endswith("pageId=42")
        args, kwargs = mock_instance.request.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer token-123"
        assert args[1] == "https://example.com/confluence/rest/api/content/search"
        assert 'space="CDLOS"' in kwargs["params"]["cql"]
        assert "type=page" in kwargs["params"]["cql"]
        assert 'text ~ "billing api timeout"' in kwargs["params"]["cql"]
        assert kwargs["params"]["limit"] == "25"
        assert kwargs["params"]["expand"] == "space,version"


def test_search_pages_normalizes_rest_api_content_base_url_and_token():
    client = ConfluenceClient(
        base_url="https://example.com/confluence/rest/api/content/",
        pat_token=' "Bearer token-123" ',
    )

    with patch("src.infrastructure.confluence_client.httpx.Client") as mock_client_class:
        mock_instance = MagicMock()
        mock_response = httpx.Response(status_code=200, json={"results": []})
        mock_instance.request.return_value = mock_response
        mock_client_class.return_value.__enter__.return_value = mock_instance
        mock_client_class.return_value.__exit__.return_value = None

        client.search_pages("places-public")

        args, kwargs = mock_instance.request.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer token-123"
        assert args[1] == "https://example.com/confluence/rest/api/content/search"


def test_fetch_page_tree_returns_parent_and_child_pages():
    client = ConfluenceClient(base_url="https://example.com/confluence", pat_token="token-123")

    parent_response = httpx.Response(
        status_code=200,
        json={"id": "10", "title": "Parent", "body": {"storage": {"value": "parent body"}}, "children": {"page": [{"id": "11"}]}},
    )
    child_response = httpx.Response(
        status_code=200,
        json={"results": [{"id": "11", "title": "Child", "body": {"storage": {"value": "child body"}}}]},
    )

    with patch("src.infrastructure.confluence_client.httpx.Client") as mock_client_class:
        mock_instance = MagicMock()
        mock_instance.request.side_effect = [parent_response, child_response]
        mock_client_class.return_value.__enter__.return_value = mock_instance
        mock_client_class.return_value.__exit__.return_value = None

        page = client.fetch_page_tree("10")

        assert page is not None
        assert page.title == "Parent"
        assert len(page.children) == 1
        assert page.children[0].title == "Child"
