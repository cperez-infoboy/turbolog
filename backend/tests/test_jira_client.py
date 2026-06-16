"""Tests for JiraClient normalization (REQ-SYNC-01).

Covers `_normalize_tasks()` requesting and emitting the `created` field.
"""
from app.services.jira_client import JiraClient


def _sample_issue(
    key: str = "PROJ-1",
    created: str = "2024-01-15T10:00:00.000+0000",
    duedate: str | None = "2024-07-01",
    description_html: str | None = "<p>Rendered description</p>",
) -> dict:
    """A minimal JIRA issue shape matching what /rest/api/3/search/jql returns.

    `description_html` is placed under `renderedFields.description` (the HTML
    projection); `fields.description` is left as ADF to assert we never read it.
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
            "description": {"type": "doc", "version": 1, "content": []},
        },
        "renderedFields": {
            "description": description_html,
        },
    }


class TestNormalizeTasksEmitsCreated:
    """REQ-SYNC-01: created is fetched and emitted for each normalized issue."""

    def test_normalize_includes_created_iso_string(self):
        issue = _sample_issue(created="2024-01-15T10:00:00.000+0000")

        result = JiraClient._normalize_tasks([issue])

        assert len(result) == 1
        assert result[0]["created"] == "2024-01-15T10:00:00.000+0000"

    def test_normalize_created_distinct_per_issue(self):
        # Triangulation: different created values flow through unchanged.
        issues = [
            _sample_issue(key="PROJ-1", created="2024-01-15T10:00:00.000+0000"),
            _sample_issue(key="PROJ-2", created="2023-05-20T08:30:00.000+0000"),
        ]

        result = JiraClient._normalize_tasks(issues)

        assert result[0]["created"] == "2024-01-15T10:00:00.000+0000"
        assert result[1]["created"] == "2023-05-20T08:30:00.000+0000"


class TestNormalizeTasksEmitsDuedateAndDescription:
    """`duedate` comes from fields, `description` from renderedFields."""

    def test_normalize_duedate_passes_through_from_fields(self):
        issue = _sample_issue(duedate="2024-07-01")

        result = JiraClient._normalize_tasks([issue])

        assert result[0]["duedate"] == "2024-07-01"

    def test_normalize_description_comes_from_rendered_fields_not_fields(self):
        issue = _sample_issue(description_html="<p>HTML body</p>")

        result = JiraClient._normalize_tasks([issue])

        # Must be the rendered HTML, NOT the ADF object sitting in fields.description.
        assert result[0]["description"] == "<p>HTML body</p>"

    def test_normalize_duedate_and_description_distinct_per_issue(self):
        # Triangulation: different values flow through unchanged for both fields.
        issues = [
            _sample_issue(
                key="PROJ-1",
                duedate="2024-07-01",
                description_html="<p>First</p>",
            ),
            _sample_issue(
                key="PROJ-2",
                duedate="2025-01-15",
                description_html="<p>Second</p>",
            ),
        ]

        result = JiraClient._normalize_tasks(issues)

        assert result[0]["duedate"] == "2024-07-01"
        assert result[0]["description"] == "<p>First</p>"
        assert result[1]["duedate"] == "2025-01-15"
        assert result[1]["description"] == "<p>Second</p>"

    def test_normalize_duedate_and_description_default_to_none_when_absent(self):
        # Edge case: JIRA omits both (no renderedFields, no duedate in fields).
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

        result = JiraClient._normalize_tasks([issue])

        assert result[0]["duedate"] is None
        assert result[0]["description"] is None
