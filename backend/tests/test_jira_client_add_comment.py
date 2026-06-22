"""Unit tests for `JiraClient.add_comment` (RED phase).

Validates:
- Correct URL: `{base}/rest/api/3/issue/{issue_key}/comment`
- Body is the Atlassian Document Format doc wrapping the text.
- Headers include Content-Type: application/json.
- Returns the comment id from the response JSON.
- Error mapping mirrors the existing methods:
    401 -> JiraAuthError
    403 -> JiraAuthError
    429 -> JiraRateLimitError
    other non-2xx -> JiraError
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.jira_client import (
    JiraAuthError,
    JiraClient,
    JiraError,
    JiraRateLimitError,
)


def _client() -> JiraClient:
    return JiraClient("example.atlassian.net", "dev@example.com", "tok")


def _fake_response(status_code: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {}
    resp.text = "err body"
    return resp


def _fake_async_client_post(captured: dict, response: MagicMock):
    """Builds an AsyncClient-like object whose .post records args + returns response."""

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None, headers=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return response

    return _FakeAsyncClient()


class TestAddCommentSuccess:
    async def test_returns_comment_id_from_response(self):
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1001", "body": {}})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            result = await _client().add_comment("PROJ-1", "hello world")

        assert result == "cmt-1001"

    async def test_posts_to_issue_comment_endpoint(self):
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1"})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            await _client().add_comment("PROJ-42", "x")

        assert captured["url"] == "https://example.atlassian.net/rest/api/3/issue/PROJ-42/comment"

    async def test_body_is_adf_doc_wrapping_text(self):
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1"})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            await _client().add_comment("PROJ-1", "my status update")

        assert captured["json"] == {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "my status update"}]}
                ],
            }
        }

    async def test_headers_include_json_content_type(self):
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1"})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            await _client().add_comment("PROJ-1", "x")

        assert captured["headers"]["Content-Type"] == "application/json"
        # Authorization must still be present.
        assert captured["headers"]["Authorization"].startswith("Basic ")


class TestAddCommentErrorMapping:
    async def test_401_raises_jira_auth_error(self):
        captured: dict = {}
        response = _fake_response(401)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            with pytest.raises(JiraAuthError):
                await _client().add_comment("PROJ-1", "x")

    async def test_403_raises_jira_auth_error(self):
        captured: dict = {}
        response = _fake_response(403)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            with pytest.raises(JiraAuthError):
                await _client().add_comment("PROJ-1", "x")

    async def test_429_raises_jira_rate_limit_error(self):
        captured: dict = {}
        response = _fake_response(429)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            with pytest.raises(JiraRateLimitError):
                await _client().add_comment("PROJ-1", "x")

    async def test_500_raises_jira_error(self):
        captured: dict = {}
        response = _fake_response(500)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            with pytest.raises(JiraError) as exc_info:
                await _client().add_comment("PROJ-1", "x")

        # Must NOT be a JiraAuthError or JiraRateLimitError — plain JiraError.
        assert type(exc_info.value) is JiraError
        # Error message references the status code.
        assert "500" in str(exc_info.value)


class TestAddCommentHardening:
    async def test_url_quotes_issue_key(self):
        """A malformed key with a path-unsafe char must be quoted so it cannot
        corrupt the URL path structure."""
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1"})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            await _client().add_comment("PROJ/evil", "x")

        # The slash must have been percent-encoded.
        assert "/issue/PROJ%2Fevil/comment" in captured["url"]
        # And the raw slash path must NOT appear.
        assert "/issue/PROJ/evil/comment" not in captured["url"]

    async def test_normal_key_is_preserved_in_url(self):
        """A standard JIRA key like PROJ-1 must pass through unchanged."""
        captured: dict = {}
        response = _fake_response(201, body={"id": "cmt-1"})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            await _client().add_comment("PROJ-1", "x")

        assert captured["url"] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/comment"

    async def test_error_does_not_leak_response_body(self):
        """The raised JiraError must NOT embed raw response.text (data leak)."""
        captured: dict = {}
        # Sentinel body string that must NOT appear in the exception message.
        response = _fake_response(500)
        response.text = "INTERNAL-INFRA-SECRET-TOKEN-LEAKED"

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client_post(captured, response),
        ):
            with pytest.raises(JiraError) as exc_info:
                await _client().add_comment("PROJ-1", "x")

        msg = str(exc_info.value)
        assert "INTERNAL-INFRA-SECRET-TOKEN-LEAKED" not in msg
        # Still references the status code so it's useful.
        assert "500" in msg
        assert "PROJ-1" in msg
