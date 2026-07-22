"""Unit tests for `JiraClient.transition_to_done` (RED phase).

Mirrors `test_jira_client_add_comment.py`. Validates the two-step flow:
  GET  /rest/api/3/issue/{key}/transitions  -> list transitions
  POST /rest/api/3/issue/{key}/transitions  -> {"transition": {"id": <id>}}

Contract:
- Selects the transition whose `to.statusCategory.key == "done"`.
- Returns the destination status name (from `to.name`).
- Raises `JiraNoDoneTransitionError` when no transition leads to Done.
- Error mapping mirrors `add_comment`:
    401/403 -> JiraAuthError
    429     -> JiraRateLimitError
    other   -> JiraError  (NO response.text leak)
"""
from unittest.mock import MagicMock, patch

import pytest

from app.services.jira_client import (
    JiraAuthError,
    JiraClient,
    JiraError,
    JiraNoDoneTransitionError,
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


def _transition(
    tid: str,
    name: str,
    to_name: str | None = None,
    category: str = "indeterminate",
) -> dict:
    """Build a single JIRA transition payload."""
    return {
        "id": tid,
        "name": name,
        "to": {"name": to_name or name, "statusCategory": {"key": category}},
    }


def _fake_async_client(captured: dict, get_response: MagicMock, post_response: MagicMock):
    """AsyncClient-like object handling BOTH .get (transitions) and .post (do)."""

    class _FakeAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, headers=None):
            captured["get_url"] = url
            captured["get_headers"] = headers
            return get_response

        async def post(self, url, json=None, headers=None):
            captured["post_url"] = url
            captured["post_json"] = json
            captured["post_headers"] = headers
            return post_response

    return _FakeAsyncClient()


class TestTransitionToDoneSuccess:
    async def test_returns_destination_status_name(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("31", "Done", category="done")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            result = await _client().transition_to_done("PROJ-1")

        assert result == "Done"

    async def test_accepts_200_response_with_body_from_post(self):
        # JIRA may answer 200 (not only 204) on a successful transition.
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(200, body={})

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            result = await _client().transition_to_done("PROJ-1")

        assert result == "Done"

    async def test_gets_transitions_then_posts_selected_id(self):
        captured: dict = {}
        get_resp = _fake_response(
            200,
            body={"transitions": [_transition("21", "In Progress"), _transition("41", "Done", category="done")]},
        )
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            await _client().transition_to_done("PROJ-42")

        # POST body carries the id of the Done transition only.
        assert captured["post_json"] == {"transition": {"id": "41"}}

    async def test_posts_to_transitions_endpoint(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            await _client().transition_to_done("PROJ-1")

        assert captured["post_url"] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/transitions"
        assert captured["get_url"] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/transitions"

    async def test_post_headers_include_json_content_type(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            await _client().transition_to_done("PROJ-1")

        assert captured["post_headers"]["Content-Type"] == "application/json"
        assert captured["post_headers"]["Authorization"].startswith("Basic ")

    async def test_prefers_canonical_done_name_when_multiple_done_transitions(self):
        """When several transitions lead to the done category, prefer the one
        whose name is in {Done, Closed, Resolved}."""
        captured: dict = {}
        get_resp = _fake_response(
            200,
            body={
                "transitions": [
                    _transition("51", "Declined", to_name="Declined", category="done"),
                    _transition("41", "Done", to_name="Done", category="done"),
                ]
            },
        )
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            result = await _client().transition_to_done("PROJ-1")

        assert captured["post_json"] == {"transition": {"id": "41"}}
        assert result == "Done"


class TestTransitionToDoneNoDoneTransition:
    async def test_raises_jira_no_done_transition_error(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("21", "In Progress")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraNoDoneTransitionError):
                await _client().transition_to_done("PROJ-1")

    async def test_does_not_post_when_no_done_transition(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("21", "In Progress")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraNoDoneTransitionError):
                await _client().transition_to_done("PROJ-1")

        assert "post_url" not in captured

    async def test_empty_transitions_raises_jira_no_done_transition_error(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": []})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraNoDoneTransitionError):
                await _client().transition_to_done("PROJ-1")


class TestTransitionToDoneErrorMapping:
    async def test_401_on_get_raises_jira_auth_error(self):
        captured: dict = {}
        get_resp = _fake_response(401)
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraAuthError):
                await _client().transition_to_done("PROJ-1")

    async def test_403_on_post_raises_jira_auth_error(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(403)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraAuthError):
                await _client().transition_to_done("PROJ-1")

    async def test_429_on_post_raises_jira_rate_limit_error(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(429)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraRateLimitError):
                await _client().transition_to_done("PROJ-1")

    async def test_500_on_post_raises_jira_error(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(500)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraError) as exc_info:
                await _client().transition_to_done("PROJ-1")

        assert type(exc_info.value) is JiraError
        assert "500" in str(exc_info.value)


class TestTransitionToDoneHardening:
    async def test_url_quotes_issue_key(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            await _client().transition_to_done("PROJ/evil")

        assert "/issue/PROJ%2Fevil/transitions" in captured["get_url"]
        assert "/issue/PROJ/evil/transitions" not in captured["get_url"]

    async def test_normal_key_preserved_in_url(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            await _client().transition_to_done("PROJ-1")

        assert captured["get_url"] == "https://example.atlassian.net/rest/api/3/issue/PROJ-1/transitions"

    async def test_error_does_not_leak_response_body(self):
        captured: dict = {}
        get_resp = _fake_response(200, body={"transitions": [_transition("11", "Done", category="done")]})
        post_resp = _fake_response(500)
        post_resp.text = "INTERNAL-INFRA-SECRET-TOKEN-LEAKED"

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraError) as exc_info:
                await _client().transition_to_done("PROJ-1")

        msg = str(exc_info.value)
        assert "INTERNAL-INFRA-SECRET-TOKEN-LEAKED" not in msg
        assert "500" in msg
        assert "PROJ-1" in msg

    async def test_transition_missing_id_raises_jira_error(self):
        # Defensive: a done-category transition without an id must NOT KeyError.
        captured: dict = {}
        get_resp = _fake_response(
            200,
            body={
                "transitions": [
                    {"name": "Done", "to": {"name": "Done", "statusCategory": {"key": "done"}}}
                ]
            },
        )
        post_resp = _fake_response(204)

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_fake_async_client(captured, get_resp, post_resp),
        ):
            with pytest.raises(JiraError) as exc_info:
                await _client().transition_to_done("PROJ-1")

        assert type(exc_info.value) is JiraError
        # Must not have fired the POST since we could not build its body.
        assert "post_url" not in captured
