import base64
import re
from datetime import datetime, timezone

import httpx

from app.config import settings


class JiraClient:
    """Client for JIRA Cloud REST API v3 using Basic Auth (email + API token)."""

    def __init__(self, jira_domain: str, email: str, api_token: str):
        self.jira_domain = jira_domain
        self.email = email
        self.api_token = api_token
        clean = re.sub(r'^https?://', '', jira_domain).rstrip('/')
        domain = clean.replace(".atlassian.net", "")
        self._base_url = f"https://{domain}.atlassian.net"
        self._auth_header = self._make_auth_header()

    def _make_auth_header(self) -> str:
        credentials = base64.b64encode(f"{self.email}:{self.api_token}".encode()).decode()
        return f"Basic {credentials}"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": self._auth_header,
            "Accept": "application/json",
        }

    async def get_myself(self) -> dict:
        """Fetch authenticated user's JIRA profile. Validates credentials."""
        async with httpx.AsyncClient(timeout=settings.JIRA_REQUEST_TIMEOUT) as client:
            response = await client.get(
                f"{self._base_url}/rest/api/3/myself",
                headers=self._headers(),
            )

        if response.status_code == 401:
            raise JiraAuthError("Invalid JIRA credentials")
        if response.status_code == 403:
            raise JiraAuthError("JIRA access forbidden")
        if response.status_code == 429:
            raise JiraRateLimitError("JIRA rate limit exceeded")
        response.raise_for_status()
        return response.json()

    async def _find_account_id(self, email: str) -> str:
        """Look up a JIRA user's accountId by email."""
        async with httpx.AsyncClient(timeout=settings.JIRA_REQUEST_TIMEOUT) as client:
            response = await client.get(
                f"{self._base_url}/rest/api/3/user/search",
                params={"query": email},
                headers=self._headers(),
            )

        if response.status_code != 200:
            raise JiraError(f"JIRA user lookup failed for {email}: {response.status_code} {response.text}")

        users = response.json()
        if not users:
            raise JiraError(f"No JIRA user found for email: {email}")

        return users[0]["accountId"]

    async def get_assigned_tasks(self, assignee_email: str | None = None) -> list[dict]:
        """Fetch tasks assigned to a specific user (or currentUser if None), ordered by most recently updated."""
        if assignee_email:
            account_id = await self._find_account_id(assignee_email)
            jql = f"assignee={account_id} AND statusCategory != Done ORDER BY updated DESC"
        else:
            jql = "assignee=currentUser() ORDER BY updated DESC"
        fields = ["summary", "status", "priority", "project", "updated"]

        async with httpx.AsyncClient(timeout=settings.JIRA_REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{self._base_url}/rest/api/3/search/jql",
                json={"jql": jql, "fields": fields},
                headers={**self._headers(), "Content-Type": "application/json"},
            )

        if response.status_code == 401:
            raise JiraAuthError("Invalid JIRA credentials")
        if response.status_code == 429:
            raise JiraRateLimitError("JIRA rate limit exceeded")
        if response.status_code != 200:
            raise JiraError(f"JIRA search error: {response.status_code} {response.text}")

        data = response.json()
        return self._normalize_tasks(data.get("issues", []))

    async def test_connection(self) -> bool:
        """Verify credentials by calling get_myself. Returns True on success."""
        try:
            await self.get_myself()
            return True
        except JiraAuthError:
            return False

    @staticmethod
    def _normalize_tasks(issues: list[dict]) -> list[dict]:
        """Transform JIRA issues into a normalized task list."""
        tasks = []
        for issue in issues:
            fields = issue.get("fields", {})
            status_field = fields.get("status", {})
            priority_field = fields.get("priority", {})
            project_field = fields.get("project", {})

            status_category = status_field.get("statusCategory", {}).get("key")
            tasks.append({
                "jira_key": issue.get("key", ""),
                "summary": fields.get("summary", ""),
                "status": status_field.get("name", ""),
                "status_category": status_category,
                "priority": priority_field.get("name") if priority_field else None,
                "project_key": project_field.get("key") if project_field else None,
                "project_name": project_field.get("name") if project_field else None,
                "updated": fields.get("updated", ""),
            })
        return tasks


class JiraError(Exception):
    """Base JIRA client error."""
    pass


class JiraAuthError(JiraError):
    """JIRA credentials are invalid or expired."""
    pass


class JiraRateLimitError(JiraError):
    """JIRA API rate limit exceeded."""
    pass
