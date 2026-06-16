"""Tests for JiraClient normalization (REQ-SYNC-01).

Covers `_normalize_tasks()` requesting and emitting the `created` field.
"""
from app.services.jira_client import JiraClient


def _sample_issue(key: str = "PROJ-1", created: str = "2024-01-15T10:00:00.000+0000") -> dict:
    """A minimal JIRA issue shape matching what /rest/api/3/search/jql returns."""
    return {
        "key": key,
        "fields": {
            "summary": "Sample task",
            "status": {"name": "To Do", "statusCategory": {"key": "new"}},
            "priority": {"name": "Medium"},
            "project": {"key": "PROJ", "name": "Project Alpha"},
            "updated": "2024-06-01T12:00:00.000+0000",
            "created": created,
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
