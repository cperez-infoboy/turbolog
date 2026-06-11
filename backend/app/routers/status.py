import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.dependencies import get_current_user
from app.models.status_report import StatusReport
from app.models.task import Task
from app.models.user import User

router = APIRouter(prefix="/api/status", tags=["status"])


@router.post("")
async def create_report(
    body: dict,
    user: User = Depends(get_current_user),
):
    """Create or update (upsert) a status report for a task on a date.
    If a report already exists for the same user+task_key+date, updates content.
    """
    task_key = body.get("task_key", "").strip()
    report_date = body.get("date", "").strip()
    content = body.get("content", "").strip()

    if not task_key or not report_date:
        raise HTTPException(400, "task_key and date are required")
    if not content:
        raise HTTPException(400, "Content cannot be empty")

    now = datetime.now(timezone.utc).isoformat()

    async with async_session() as session:
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


async def _get_reports_by_date(user_id: str, date: str) -> list[dict]:
    """Fetch reports for a user on a date, enriched with task summary."""
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

    return [
        {
            "id": r.id,
            "task_key": r.task_key,
            "task_summary": task_summaries.get(r.task_key, ""),
            "content": r.content,
            "date": r.report_date,
            "updated_at": r.updated_at,
        }
        for r in reports
    ]


@router.put("/{report_id}")
async def update_report(
    report_id: str,
    body: dict,
    user: User = Depends(get_current_user),
):
    """Update content of an existing report. Ownership check enforced."""
    content = body.get("content", "").strip()
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
    """Delete a report. Ownership check enforced."""
    async with async_session() as session:
        result = await session.execute(
            select(StatusReport).where(StatusReport.id == report_id)
        )
        report = result.scalar_one_or_none()

        if not report:
            raise HTTPException(404, "Report not found")
        if report.user_id != user.id:
            raise HTTPException(403, "Not authorized")

        await session.delete(report)
        await session.commit()

    return {"status": "deleted"}
