"""Tests for JiraClient normalization and ADF -> HTML parsing.

Covers:
- `_normalize_tasks()` emitting `created`, `duedate`, and `description`.
- `_adf_to_html()` converting Atlassian Document Format (ADF) to an
  HTML-escaped string (REQ: JIRA /search/jql does NOT return renderedFields;
  `fields.description` is ADF JSON and must be parsed backend-side).
"""
from unittest.mock import MagicMock, patch

from app.services.jira_client import JiraClient, _adf_to_html


def _normalize(issues: list[dict]) -> list[dict]:
    """Call _normalize_tasks via a real instance (it now reads self._base_url)."""
    return JiraClient("example.atlassian.net", "dev@example.com", "tok")._normalize_tasks(issues)


def _sample_issue(
    key: str = "PROJ-1",
    created: str = "2024-01-15T10:00:00.000+0000",
    duedate: str | None = "2024-07-01",
    description_adf: dict | None = {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Test para Tutbolog"}]},
        ],
    },
) -> dict:
    """A minimal JIRA issue shape matching what /rest/api/3/search/jql returns.

    `fields.description` carries the ADF dict (the only shape JIRA returns from
    /search/jql — there are NO renderedFields). No `renderedFields` key is set
    to assert the normalize path never relies on it.
    """
    return {
        "key": key,
        "fields": {
            "summary": "Sample task",
            "status": {"name": "To Do", "statusCategory": {"key": "new"}},
            "priority": {"name": "Medium"},
            "project": {"key": "PROJ", "name": "Project Alpha"},
            "updated": "2024-06-01T12:00:00.000+0000",
            "created": created,
            "duedate": duedate,
            "description": description_adf,
        },
    }


class TestNormalizeTasksEmitsCreated:
    """REQ-SYNC-01: created is fetched and emitted for each normalized issue."""

    def test_normalize_includes_created_iso_string(self):
        issue = _sample_issue(created="2024-01-15T10:00:00.000+0000")

        result = _normalize([issue])

        assert len(result) == 1
        assert result[0]["created"] == "2024-01-15T10:00:00.000+0000"

    def test_normalize_created_distinct_per_issue(self):
        # Triangulation: different created values flow through unchanged.
        issues = [
            _sample_issue(key="PROJ-1", created="2024-01-15T10:00:00.000+0000"),
            _sample_issue(key="PROJ-2", created="2023-05-20T08:30:00.000+0000"),
        ]

        result = _normalize(issues)

        assert result[0]["created"] == "2024-01-15T10:00:00.000+0000"
        assert result[1]["created"] == "2023-05-20T08:30:00.000+0000"


class TestNormalizeTasksEmitsDuedateAndDescription:
    """`duedate` and `description` both come from `fields`.

    `description` is ADF in `fields.description` and is parsed to HTML by
    `_adf_to_html`. There is no `renderedFields` source anymore.
    """

    def test_normalize_duedate_passes_through_from_fields(self):
        issue = _sample_issue(duedate="2024-07-01")

        result = _normalize([issue])

        assert result[0]["duedate"] == "2024-07-01"

    def test_normalize_description_is_parsed_adf_html_from_fields(self):
        issue = _sample_issue(
            description_adf={
                "type": "doc",
                "version": 1,
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "HTML body"}]},
                ],
            },
        )

        result = _normalize([issue])

        # ADF paragraph+text is parsed to <p>...</p>; NOT the raw ADF dict.
        assert result[0]["description"] == "<p>HTML body</p>"

    def test_normalize_duedate_and_description_distinct_per_issue(self):
        # Triangulation: different values flow through unchanged for both fields.
        issues = [
            _sample_issue(
                key="PROJ-1",
                duedate="2024-07-01",
                description_adf={
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "First"}]},
                    ],
                },
            ),
            _sample_issue(
                key="PROJ-2",
                duedate="2025-01-15",
                description_adf={
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Second"}]},
                    ],
                },
            ),
        ]

        result = _normalize(issues)

        assert result[0]["duedate"] == "2024-07-01"
        assert result[0]["description"] == "<p>First</p>"
        assert result[1]["duedate"] == "2025-01-15"
        assert result[1]["description"] == "<p>Second</p>"

    def test_normalize_duedate_and_description_default_when_absent(self):
        # Edge case: JIRA omits duedate and description entirely.
        issue = {
            "key": "PROJ-9",
            "fields": {
                "summary": "Bare task",
                "status": {"name": "To Do", "statusCategory": {"key": "new"}},
                "priority": {"name": "Low"},
                "project": {"key": "PROJ", "name": "Project Alpha"},
                "updated": "2024-06-01T12:00:00.000+0000",
                "created": "2024-01-15T10:00:00.000+0000",
            },
        }

        result = _normalize([issue])

        assert result[0]["duedate"] is None
        # No ADF -> parser returns "" (empty HTML string), not None.
        assert result[0]["description"] == ""


class TestAdfToHtml:
    """Direct tests for the `_adf_to_html` ADF -> HTML parser.

    The parser MUST HTML-escape all text (XSS neutralization) and degrade
    gracefully on unknown / malformed input (never raise).
    """

    def test_paragraph_with_text(self):
        adf = {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "Hello world"}]},
            ],
        }

        assert _adf_to_html(adf) == "<p>Hello world</p>"

    def test_text_with_strong_mark(self):
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "bold", "marks": [{"type": "strong"}]},
            ],
        }

        assert _adf_to_html(adf) == "<p><strong>bold</strong></p>"

    def test_text_with_em_mark(self):
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "ital", "marks": [{"type": "em"}]},
            ],
        }

        assert _adf_to_html(adf) == "<p><em>ital</em></p>"

    def test_text_with_code_mark(self):
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "x", "marks": [{"type": "code"}]},
            ],
        }

        assert _adf_to_html(adf) == "<p><code>x</code></p>"

    def test_text_with_link_mark_escapes_href(self):
        adf = {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "click",
                    "marks": [{"type": "link", "attrs": {"href": "https://ex.com?a=1&b=2"}}],
                },
            ],
        }

        # Both the visible text and the href are HTML-escaped.
        assert _adf_to_html(adf) == '<p><a href="https://ex.com?a=1&amp;b=2">click</a></p>'

    def test_text_with_multiple_marks_nest_in_order(self):
        adf = {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "bi",
                    "marks": [{"type": "strong"}, {"type": "em"}],
                },
            ],
        }

        # Marks nest in their declared order: outer = strong, inner = em.
        assert _adf_to_html(adf) == "<p><strong><em>bi</em></strong></p>"

    def test_heading_level_2(self):
        adf = {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Title"}],
        }

        assert _adf_to_html(adf) == "<h2>Title</h2>"

    def test_heading_level_clamped_when_out_of_range(self):
        # Defensive: ADF spec says 1-6; an out-of-range level must clamp, not crash.
        adf = {
            "type": "heading",
            "attrs": {"level": 9},
            "content": [{"type": "text", "text": "Big"}],
        }

        assert _adf_to_html(adf) == "<h6>Big</h6>"

    def test_bullet_list_with_two_items(self):
        adf = {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "one"}]},
                ]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "two"}]},
                ]},
            ],
        }

        # listItem children are paragraphs; their inline text is rendered
        # directly inside <li> WITHOUT extra <p> nesting (cleaner HTML output).
        assert _adf_to_html(adf) == "<ul><li>one</li><li>two</li></ul>"

    def test_ordered_list(self):
        adf = {
            "type": "orderedList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "first"}]},
                ]},
            ],
        }

        assert _adf_to_html(adf) == "<ol><li>first</li></ol>"

    def test_code_block(self):
        adf = {
            "type": "codeBlock",
            "content": [{"type": "text", "text": "print('hi')"}],
        }

        assert _adf_to_html(adf) == "<pre><code>print('hi')</code></pre>"

    def test_hard_break(self):
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "a"},
                {"type": "hardBreak"},
                {"type": "text", "text": "b"},
            ],
        }

        assert _adf_to_html(adf) == "<p>a<br />b</p>"

    def test_blockquote(self):
        adf = {
            "type": "blockquote",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "quoted"}]},
            ],
        }

        assert _adf_to_html(adf) == "<blockquote><p>quoted</p></blockquote>"

    def test_rule(self):
        assert _adf_to_html({"type": "rule"}) == "<hr />"

    def test_mention_uses_attrs_text(self):
        adf = {
            "type": "paragraph",
            "content": [
                {"type": "mention", "attrs": {"text": "@alice"}},
            ],
        }

        assert _adf_to_html(adf) == "<p>@alice</p>"

    def test_html_injection_in_text_is_escaped(self):
        # CRITICAL: a malicious / accidental script tag in ADF text must be
        # HTML-escaped so it cannot execute when rendered via {@html}.
        adf = {
            "type": "paragraph",
            "content": [{"type": "text", "text": "<script>x</script>"}],
        }

        assert _adf_to_html(adf) == "<p>&lt;script&gt;x&lt;/script&gt;</p>"

    def test_html_injection_in_mention_text_is_escaped(self):
        adf = {"type": "mention", "attrs": {"text": "<img src=x onerror=alert(1)>"}}

        assert _adf_to_html(adf) == "&lt;img src=x onerror=alert(1)&gt;"

    def test_none_input_returns_empty_string(self):
        assert _adf_to_html(None) == ""

    def test_non_dict_input_returns_empty_string(self):
        assert _adf_to_html("not a dict") == ""
        assert _adf_to_html([]) == ""
        assert _adf_to_html(42) == ""

    def test_unknown_node_with_content_recurses(self):
        # Unknown node type but has content -> degrade by recursing into children.
        adf = {
            "type": "someFutureNode",
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": "ok"}]},
            ],
        }

        assert _adf_to_html(adf) == "<p>ok</p>"

    def test_unknown_node_without_content_returns_empty(self):
        assert _adf_to_html({"type": "mysteryNode"}) == ""

    def test_empty_paragraph(self):
        # paragraph with no content -> empty <p></p>.
        assert _adf_to_html({"type": "paragraph"}) == "<p></p>"

    def test_text_without_text_field(self):
        # Defensive: a text node missing its `text` field must not raise.
        adf = {"type": "paragraph", "content": [{"type": "text"}]}
        assert _adf_to_html(adf) == "<p></p>"


class TestSearchRequestFields:
    """Regression guard (W2): the JIRA /search/jql POST MUST request
    `description`, `created`, and `duedate` in its `fields` list.

    A prior bug omitted `description` from the request, so descriptions arrived
    empty even though `_normalize_tasks` knew how to parse them. Tests of
    `_normalize_tasks` cannot catch this — they mock the response with
    `description` already present, which masks the omission. This test pins the
    actual outbound request payload.
    """

    async def test_search_post_requests_description_created_and_duedate(self):
        captured: dict = {}

        class _FakeAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def post(self, url, json=None, headers=None):
                captured["json"] = json
                response = MagicMock(status_code=200)
                response.json.return_value = {"issues": []}
                return response

        client = JiraClient("example.atlassian.net", "dev@example.com", "tok")

        with patch(
            "app.services.jira_client.httpx.AsyncClient",
            return_value=_FakeAsyncClient(),
        ):
            # currentUser() path — skips _find_account_id, so only the POST fires.
            await client.get_assigned_tasks()

        fields = captured["json"]["fields"]
        assert "description" in fields, "JIRA search must request the description field"
        assert "created" in fields
        assert "duedate" in fields
