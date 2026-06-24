import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import get_current_user, get_jira_client
from app.models.daily_closure import DailyClosure
from app.models.status_report import StatusReport
from app.models.task import Task
from app.models.user import User
from app.services.audit_service import compute_user_month_summary
from app.services.jira_client import strip_html
from app.services.llm_client import (
    LlmAuthError,
    LlmConfigError,
    LlmError,
    LlmRateLimitError,
    improve_status_text,
)

router = APIRouter(prefix="/api/status", tags=["status"])


@router.post("")
async def create_report(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Create or update (upsert) a status report for a task on a date.
    If a report already exists for the same user+task_key+date, updates content.
    """
    task_key = _str_field(body, "task_key")
    report_date = _str_field(body, "date")
    content = _str_field(body, "content")

    if not task_key or not report_date:
        raise HTTPException(400, "task_key and date are required")
    if not content:
        raise HTTPException(400, "Content cannot be empty")

    now = datetime.now(timezone.utc).isoformat()

    async with async_session() as session:
        await _assert_day_open(session, user.id, report_date)

        # Check for existing report (upsert on duplicate)
        result = await session.execute(
            select(StatusReport).where(
                StatusReport.user_id == user.id,
                StatusReport.task_key == task_key,
                StatusReport.report_date == report_date,
            )
        )
        existing = result.scalar_one_or_none()

        if existing:
            existing.content = content
            existing.updated_at = now
            await session.commit()

            return {
                "id": existing.id,
                "task_key": existing.task_key,
                "content": existing.content,
                "date": existing.report_date,
                "updated_at": existing.updated_at,
            }

        report = StatusReport(
            id=secrets.token_hex(16),
            user_id=user.id,
            task_key=task_key,
            report_date=report_date,
            content=content,
        )
        session.add(report)
        await session.commit()
        await session.refresh(report)

        return {
            "id": report.id,
            "task_key": report.task_key,
            "content": report.content,
            "date": report.report_date,
            "created_at": report.created_at,
        }


@router.post("/improve")
async def improve_status(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Improve a status draft using an OpenAI-compatible LLM.

    Sends the user's draft plus the cached task context (title, description,
    status, dates, comments) to the LLM and returns an improved version. Does
    NOT persist anything — the result is applied to the editor for the user to
    review and save explicitly.
    """
    draft = _str_field(body, "content")
    task_key = _str_field(body, "task_key")
    if not task_key:
        raise HTTPException(400, "task_key is required")
    if not draft:
        raise HTTPException(400, "Draft content is required")

    # Load the cached task to build grounding context for the LLM. If the task
    # isn't cached (edge case), the LLM still improves the draft's grammar with
    # empty context — never raises.
    async with async_session() as session:
        result = await session.execute(
            select(Task).where(
                Task.user_id == user.id,
                Task.jira_key == task_key,
            )
        )
        task = result.scalar_one_or_none()

    context = {
        "summary": task.summary if task else "",
        "status": task.status if task else "",
        "priority": task.priority if task else None,
        "project_name": task.project_name if task else None,
        "created": task.created if task else None,
        "duedate": task.duedate if task else None,
        # description is cached as HTML; flatten to plain text for the prompt.
        "description": strip_html(task.description) if task else "",
        "comments": task.comments if task else "",
    }

    try:
        improved = await improve_status_text(draft, context)
    except LlmConfigError:
        raise HTTPException(503, "IA no configurada en el servidor")
    except LlmRateLimitError:
        raise HTTPException(503, "El servicio de IA está saturado, intenta nuevamente")
    except LlmAuthError:
        raise HTTPException(500, "Error de autenticación con la IA")
    except LlmError:
        # Fixed message: LlmError may wrap httpx internals (URLs, bodies) we
        # never want to echo to the client.
        raise HTTPException(502, "Error al contactar el servicio de IA")

    return {"content": improved}


@router.post("/finalize")
async def finalize_day(
    body: dict,
    user: User = Depends(get_current_user),
    jira_client=Depends(get_jira_client),
):
    """Close the day: post all non-empty status reports as JIRA comments and
    record a DailyClosure row that locks the date.

    Race-condition-safe "closure-as-mutex" flow:
    1. Validate date, then claim the day by inserting a DailyClosure and
       committing. The unique constraint `uq_daily_closures_user_date` makes
       this atomic — two concurrent finalize calls cannot both pass; the
       second hits IntegrityError -> 409. No JIRA comment is posted until
       the claim succeeds, so duplicate posts are impossible.
    2. Re-query reports (fresh, after the claim commit).
    3. For each report with no jira_comment_id and non-empty content, post a
       JIRA comment. Each success is committed per-report so retry is
       idempotent. ANY exception (JIRA, network, malformed response) is
       captured into `failed` and the loop continues.
    4. If `failed` is non-empty: delete the claim (unlock the day so the user
       can retry) and return 502. Already-posted reports keep their
       jira_comment_id, so retry skips them.
    5. If `failed` is empty: the claim from step 1 stands; return 200.
    """
    raw_date = body.get("date")
    if not isinstance(raw_date, str) or not raw_date.strip():
        raise HTTPException(400, "Fecha requerida")
    report_date = raw_date.strip()

    async with async_session() as session:
        # Fast-path pre-check: if a closure already exists, 409 before we
        # attempt the claim. The IntegrityError below remains the source of
        # truth for the concurrent case.
        existing_closure = await session.execute(
            select(DailyClosure).where(
                DailyClosure.user_id == user.id,
                DailyClosure.report_date == report_date,
            )
        )
        if existing_closure.scalar_one_or_none() is not None:
            raise HTTPException(409, "El día ya está cerrado")

        # Status-coverage validation: every in-progress task
        # (status_category == "indeterminate") for the user must have a
        # StatusReport with non-empty content for this date. If any is
        # missing, reject with 422 BEFORE claiming the mutex or calling JIRA.
        in_progress_result = await session.execute(
            select(Task.jira_key, Task.summary).where(
                Task.user_id == user.id,
                Task.status_category == "indeterminate",
            )
        )
        in_progress_tasks = in_progress_result.all()

        if in_progress_tasks:
            # Build the set of task keys whose report content is non-empty.
            # Content emptiness is filtered in Python to mirror the finalize
            # loop's own content.strip() check.
            covered_rows = (
                await session.execute(
                    select(StatusReport.task_key, StatusReport.content).where(
                        StatusReport.user_id == user.id,
                        StatusReport.report_date == report_date,
                    )
                )
            ).all()
            keys_with_content: set[str] = {
                key
                for key, content in covered_rows
                if content and content.strip()
            }

            missing = [
                {"task_key": key, "task_summary": summary}
                for (key, summary) in in_progress_tasks
                if key not in keys_with_content
            ]
            if missing:
                return JSONResponse(
                    status_code=422,
                    content={"finalized": False, "missing": missing},
                )

        # CLAIM: insert closure first. Atomic via the unique constraint.
        closure = DailyClosure(
            id=secrets.token_hex(16),
            user_id=user.id,
            report_date=report_date,
            finalized_at=datetime.now(timezone.utc).isoformat(),
        )
        session.add(closure)
        try:
            await session.commit()
        except IntegrityError:
            # A concurrent finalize beat us to the claim.
            await session.rollback()
            raise HTTPException(409, "El día ya está cerrado")

        # Claim succeeded. Re-query reports fresh, after the claim commit.
        result = await session.execute(
            select(StatusReport)
            .where(
                StatusReport.user_id == user.id,
                StatusReport.report_date == report_date,
            )
            .order_by(StatusReport.task_key)
        )
        reports = result.scalars().all()

        posted = 0
        failed: list[dict] = []

        for report in reports:
            if report.jira_comment_id is not None:
                # Already posted in a prior (partial) finalize attempt.
                continue
            if not report.content.strip():
                continue

            text = f"📊 Estado diario ({report_date}):\n\n{report.content}"
            try:
                comment_id = await jira_client.add_comment(report.task_key, text)
            except Exception as e:
                # Broad catch: JIRA errors, httpx network/timeout errors,
                # malformed JSON / KeyError on response — anything. Summarize
                # so we never leak raw internals to the user.
                failed.append({"task_key": report.task_key, "error": _summarize_error(e)})
                continue

            report.jira_comment_id = comment_id
            await session.commit()
            posted += 1

        if failed:
            # Unlock the day so the user can retry. Already-posted reports
            # retain their jira_comment_id, so retry is idempotent.
            await session.execute(
                delete(DailyClosure).where(
                    DailyClosure.user_id == user.id,
                    DailyClosure.report_date == report_date,
                )
            )
            await session.commit()
            return JSONResponse(
                status_code=502,
                content={
                    "finalized": False,
                    "posted": posted,
                    "failed": failed,
                },
            )

        # Full success: the claim from above is the final closure.
        return {"finalized": True, "posted": posted, "finalized_at": closure.finalized_at}


@router.get("/summary")
async def get_month_summary(user: User = Depends(get_current_user)):
    """Current-month audit summary for the authenticated user.

    Returns expected/reported/faltas counts and the specific falta dates for the
    current month (per ``settings.AUDIT_TIMEZONE``). Available to any user —
    this is the user's own data, not an admin-only report.
    """
    summary = await compute_user_month_summary(async_session, user.id)
    return summary


@router.get("/today")
async def get_today_reports(user: User = Depends(get_current_user)):
    """Convenience endpoint: get all reports for today."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return await _get_reports_by_date(user.id, today)


@router.get("")
async def get_reports_by_date(
    date: str,
    user: User = Depends(get_current_user),
):
    """Get all status reports for the authenticated user on a given date.
    Includes task summary from the Task cache table.
    """
    return await _get_reports_by_date(user.id, date)


async def _get_reports_by_date(user_id: str, date: str) -> dict:
    """Fetch reports for a user on a date, enriched with task summary and the
    day's finalization status."""
    async with async_session() as session:
        result = await session.execute(
            select(StatusReport).where(
                StatusReport.user_id == user_id,
                StatusReport.report_date == date,
            )
        )
        reports = result.scalars().all()

        # Collect task keys for summary lookup
        task_keys = [r.task_key for r in reports]
        task_summaries: dict[str, str] = {}
        if task_keys:
            task_result = await session.execute(
                select(Task).where(
                    Task.user_id == user_id,
                    Task.jira_key.in_(task_keys),
                )
            )
            for task in task_result.scalars().all():
                task_summaries[task.jira_key] = task.summary

        closure_result = await session.execute(
            select(DailyClosure).where(
                DailyClosure.user_id == user_id,
                DailyClosure.report_date == date,
            )
        )
        closure = closure_result.scalar_one_or_none()

    return {
        "reports": [
            {
                "id": r.id,
                "task_key": r.task_key,
                "task_summary": task_summaries.get(r.task_key, ""),
                "content": r.content,
                "date": r.report_date,
                "updated_at": r.updated_at,
                "jira_comment_id": r.jira_comment_id,
            }
            for r in reports
        ],
        "finalized": closure is not None,
        "finalized_at": closure.finalized_at if closure else None,
    }


@router.put("/{report_id}")
async def update_report(
    report_id: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Update content of an existing report. Ownership check enforced.
    Refused if the day is closed or the report was already sent to JIRA.
    """
    content = _str_field(body, "content")
    if not content:
        raise HTTPException(400, "Content cannot be empty")

    async with async_session() as session:
        result = await session.execute(
            select(StatusReport).where(StatusReport.id == report_id)
        )
        report = result.scalar_one_or_none()

        if not report:
            raise HTTPException(404, "Report not found")
        if report.user_id != user.id:
            raise HTTPException(403, "Not authorized")

        await _assert_day_open(session, user.id, report.report_date)
        if report.jira_comment_id is not None:
            raise HTTPException(409, "El status ya fue enviado a JIRA")

        report.content = content
        report.updated_at = datetime.now(timezone.utc).isoformat()
        await session.commit()

        return {
            "id": report.id,
            "task_key": report.task_key,
            "content": report.content,
            "date": report.report_date,
            "updated_at": report.updated_at,
        }


@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a report. Ownership check enforced.
    Refused if the day is closed or the report was already sent to JIRA.
    """
    async with async_session() as session:
        result = await session.execute(
            select(StatusReport).where(StatusReport.id == report_id)
        )
        report = result.scalar_one_or_none()

        if not report:
            raise HTTPException(404, "Report not found")
        if report.user_id != user.id:
            raise HTTPException(403, "Not authorized")

        await _assert_day_open(session, user.id, report.report_date)
        if report.jira_comment_id is not None:
            raise HTTPException(409, "El status ya fue enviado a JIRA")

        await session.delete(report)
        await session.commit()

    return {"status": "deleted"}


async def _assert_day_open(session: AsyncSession, user_id: str, date: str) -> None:
    """Raise HTTPException(409) if the (user_id, date) day is already closed."""
    result = await session.execute(
        select(DailyClosure).where(
            DailyClosure.user_id == user_id,
            DailyClosure.report_date == date,
        )
    )
    if result.scalar_one_or_none() is not None:
        raise HTTPException(409, "Día cerrado, no se pueden modificar los statuses")


def _str_field(body: dict, key: str) -> str:
    """Extract a string field from a JSON body, returning "" for missing or
    non-string values. Guards against AttributeError when a client sends a
    non-string payload (e.g. {"date": 123} or {"date": null}).
    """
    value = body.get(key)
    if not isinstance(value, str):
        return ""
    return value.strip()


def _summarize_error(exc: Exception) -> str:
    """Short, leak-free summary of an exception for user-facing `failed` entries.

    Uses the exception's class name + message. Truncates to keep responses
    compact. Never surfaces arbitrary HTTP response bodies (those are already
    filtered out by JiraClient.add_comment, which now raises without
    `response.text`).
    """
    name = type(exc).__name__
    msg = str(exc).strip()
    if not msg:
        return name
    summary = f"{name}: {msg}"
    return summary[:200]
