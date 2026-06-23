import base64
import html
import re
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from app.config import settings


# Mark types supported by `_apply_marks`. `subsup` is handled specially because
# it requires an attrs.subtype (`sub` or `sup`); the rest are 1:1 tag mappings.
_SIMPLE_MARK_TAGS: dict[str, str] = {
    "strong": "strong",
    "em": "em",
    "code": "code",
    "underline": "u",
    "strike": "s",
    "strikethrough": "s",
}


def _apply_marks(text: str, marks: list[dict] | None) -> str:
    """Wrap an already-escaped text string in the HTML tags for its ADF marks.

    Marks nest in their declared order (first mark = outermost tag). `link`
    and `subsup` are special-cased because they carry attrs.
    """
    if not marks:
        return text
    wrapped = text
    # Iterate in reverse so the first mark becomes the outermost tag.
    for mark in reversed(marks):
        mtype = mark.get("type")
        attrs = mark.get("attrs", {}) or {}
        if mtype in _SIMPLE_MARK_TAGS:
            tag = _SIMPLE_MARK_TAGS[mtype]
            wrapped = f"<{tag}>{wrapped}</{tag}>"
        elif mtype == "link":
            href = html.escape(str(attrs.get("href", "")), quote=True)
            wrapped = f'<a href="{href}">{wrapped}</a>'
        elif mtype == "subsup":
            sub = attrs.get("type")
            if sub == "sub":
                wrapped = f"<sub>{wrapped}</sub>"
            elif sub == "sup":
                wrapped = f"<sup>{wrapped}</sup>"
        # Unknown mark types are ignored (graceful degradation).
    return wrapped


def _adf_to_html(node) -> str:
    """Convert an Atlassian Document Format (ADF) node into an HTML string.

    JIRA Cloud's `/rest/api/3/search/jql` returns `fields.description` as ADF
    JSON (there are NO `renderedFields` — that expand is rejected with HTTP
    400). This parser walks the ADF tree and emits best-effort HTML.

    Guarantees:
    - ALL text content is HTML-escaped via `html.escape` (XSS neutralization),
      including link `href` attrs and mention display text.
    - Never raises on malformed/unknown input; returns "" when there is nothing
      renderable.
    - `None` or non-dict input -> "".
    - `listItem` children are rendered inline WITHOUT extra <p> nesting so a
      list item reads `<li>text</li>` rather than `<li><p>text</p></li>`.
    """
    if not isinstance(node, dict):
        return ""

    ntype = node.get("type")
    content = node.get("content")
    # Helper to render child nodes and join their output.
    def render_children() -> str:
        if not content or not isinstance(content, list):
            return ""
        return "".join(_adf_to_html(child) for child in content)

    if ntype in ("doc",) or ntype is None and isinstance(content, list):
        # Container nodes just concatenate their children.
        return render_children()

    if ntype == "paragraph":
        return f"<p>{render_children()}</p>"

    if ntype == "text":
        raw_text = node.get("text", "")
        if not isinstance(raw_text, str):
            raw_text = str(raw_text)
        escaped = html.escape(raw_text, quote=False)
        return _apply_marks(escaped, node.get("marks"))

    if ntype == "heading":
        level = node.get("attrs", {}).get("level", 1) if isinstance(node.get("attrs"), dict) else 1
        try:
            level = int(level)
        except (TypeError, ValueError):
            level = 1
        # Clamp to valid HTML heading range 1-6.
        level = max(1, min(6, level))
        return f"<h{level}>{render_children()}</h{level}>"

    if ntype == "bulletList":
        return f"<ul>{render_children()}</ul>"

    if ntype in ("orderedList", "numberedList"):
        return f"<ol>{render_children()}</ol>"

    if ntype == "listItem":
        # Render listItem children inline. A listItem's children are usually
        # paragraphs; we strip the surrounding <p> to avoid <li><p>..</p></li>.
        if not content or not isinstance(content, list):
            return "<li></li>"
        inline_parts: list[str] = []
        for child in content:
            if isinstance(child, dict) and child.get("type") == "paragraph":
                # Render the paragraph's children directly, skipping the <p>.
                pcontent = child.get("content")
                if pcontent and isinstance(pcontent, list):
                    inline_parts.append(
                        "".join(_adf_to_html(c) for c in pcontent)
                    )
            else:
                inline_parts.append(_adf_to_html(child))
        return f"<li>{''.join(inline_parts)}</li>"

    if ntype == "codeBlock":
        # Concatenate text children; wrap in <pre><code>.
        parts: list[str] = []
        if content and isinstance(content, list):
            for child in content:
                if isinstance(child, dict) and child.get("type") == "text":
                    raw = child.get("text", "")
                    if not isinstance(raw, str):
                        raw = str(raw)
                    parts.append(html.escape(raw, quote=False))
        return f"<pre><code>{''.join(parts)}</code></pre>"

    if ntype == "blockquote":
        return f"<blockquote>{render_children()}</blockquote>"

    if ntype == "hardBreak":
        return "<br />"

    if ntype in ("rule", "horizontalRule"):
        return "<hr />"

    if ntype == "mention":
        attrs = node.get("attrs", {}) if isinstance(node.get("attrs"), dict) else {}
        label = attrs.get("text") or attrs.get("displayName") or "@mention"
        if not isinstance(label, str):
            label = str(label)
        return html.escape(label, quote=False)

    if ntype == "emoji":
        return ""

    # Unknown node type: if it has content, recurse; else degrade to "".
    if content and isinstance(content, list):
        return render_children()
    return ""


def strip_html(s: str | None) -> str:
    """Collapse an HTML string to readable plain text (for LLM context).

    Used to flatten ADF→HTML output (descriptions, comment bodies) into clean
    text for the prompt. Strips tags, unescapes entities, collapses runs of
    spaces/tabs. Block boundaries (<p>, <li>, <br>) are flattened to spaces.
    """
    text = re.sub(r"<[^>]+>", " ", s or "")
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def extract_comments(comment_field) -> str:
    """Flatten JIRA `fields.comment` into a compact plain-text block.

    Each comment becomes one line: "Author (YYYY-MM-DD): body". Bodies are
    ADF, rendered via `_adf_to_html` then flattened via `strip_html`. Capped to
    the last 20 comments to bound prompt size. Returns "" when there is nothing
    usable (never raises).
    """
    if not isinstance(comment_field, dict):
        return ""
    comments = comment_field.get("comments")
    if not isinstance(comments, list) or not comments:
        return ""
    lines: list[str] = []
    for comment in comments[-20:]:
        if not isinstance(comment, dict):
            continue
        author = (comment.get("author") or {}).get("displayName", "Anónimo")
        created = str(comment.get("created") or "")[:10]
        body = strip_html(_adf_to_html(comment.get("body")))
        if not body:
            continue
        label = f"{author} ({created}):" if created else f"{author}:"
        lines.append(f"{label} {body}")
    return "\n".join(lines)


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
        fields = ["summary", "status", "priority", "project", "updated", "created", "duedate", "description", "comment"]

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

    async def add_comment(self, issue_key: str, comment_text: str) -> str:
        """Post a comment on an issue and return the created comment id.

        The comment body is wrapped in Atlassian Document Format (ADF) as a
        single text paragraph. Raises JiraAuthError / JiraRateLimitError /
        JiraError mirroring the other methods.
        """
        body = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment_text}],
                    }
                ],
            }
        }
        async with httpx.AsyncClient(timeout=settings.JIRA_REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{self._base_url}/rest/api/3/issue/{quote(issue_key, safe='')}/comment",
                json=body,
                headers={**self._headers(), "Content-Type": "application/json"},
            )

        if response.status_code in (401, 403):
            raise JiraAuthError("Invalid JIRA credentials")
        if response.status_code == 429:
            raise JiraRateLimitError("JIRA rate limit exceeded")
        if response.status_code not in (200, 201):
            raise JiraError(
                f"JIRA add comment failed for {issue_key}: HTTP {response.status_code}"
            )

        return response.json()["id"]

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
                "created": fields.get("created", ""),
                "duedate": fields.get("duedate"),
                "description": _adf_to_html(fields.get("description")),
                "comments": extract_comments(fields.get("comment")),
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
