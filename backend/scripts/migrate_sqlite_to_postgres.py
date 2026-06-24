"""One-shot migration: copy rows from the legacy SQLite DB into PostgreSQL.

Run AFTER `alembic upgrade head` has built the schema in the target Postgres.

    # 1. extract the live SQLite file out of the running container
    docker cp turbolog-backend-1:/app/data/turbolog.db /tmp/turbolog-source.db

    # 2. run from backend/ (DATABASE_URL must point at the Postgres target)
    uv run python scripts/migrate_sqlite_to_postgres.py            # fail-safe
    uv run python scripts/migrate_sqlite_to_postgres.py --force    # truncate first

The target is the database in settings.DATABASE_URL, which MUST be a
`postgresql+asyncpg://` URL. PKs/FKs and timestamps are preserved verbatim
(all timestamp columns are String ISO values, so no type coercion is needed).

Safety: by default the script REFUSES to run if the target already has users,
so it can't silently clobber a populated database. Pass --force to TRUNCATE the
four tables (CASCADE) before copying. The whole copy runs in one transaction;
any integrity error rolls everything back.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Make `app.*` importable when run as a script (e.g. `uv run python scripts/...`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, select, text  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import DailyClosure, StatusReport, Task, User  # noqa: E402

# FK parents first. tasks / status_reports / daily_closures depend only on users.
ORDER = [User, Task, StatusReport, DailyClosure]
TABLES = ", ".join(m.__tablename__ for m in ORDER)  # users, tasks, status_reports, daily_closures


async def main(src_url: str, force: bool) -> None:
    if not settings.DATABASE_URL.startswith("postgresql"):
        raise SystemExit(
            f"Refusing to migrate: DATABASE_URL is not PostgreSQL ({settings.DATABASE_URL!r})."
        )

    src = create_engine(src_url)  # sync read of the SQLite source
    dst = create_async_engine(settings.DATABASE_URL)
    dst_session = async_sessionmaker(dst, expire_on_commit=False)

    # Fail-safe guard OUTSIDE the copy transaction so it never clobbers data.
    if not force:
        async with dst_session() as session:
            existing = (await session.execute(text("SELECT count(*) FROM users"))).scalar()
        if existing:
            raise SystemExit(
                f"Target already has {existing} users. Re-run with --force to "
                f"TRUNCATE {TABLES} and reload."
            )

    try:
        async with dst_session() as session, session.begin():
            if force:
                await session.execute(text(f"TRUNCATE {TABLES} CASCADE"))

            with src.connect() as conn:
                for model in ORDER:
                    rows = [
                        dict(row._mapping)
                        for row in conn.execute(select(model.__table__)).all()
                    ]
                    if rows:
                        await session.execute(model.__table__.insert(), rows)
                    print(f"{model.__tablename__}: {len(rows)} rows copied")
    except IntegrityError as exc:
        # session.begin() auto-rolls-back on exception.
        print(f"Integrity error during migration (rolled back): {exc.orig}", file=sys.stderr)
        raise
    finally:
        await dst.dispose()
        src.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate SQLite -> PostgreSQL (Turbolog).")
    parser.add_argument(
        "--src",
        default="sqlite:////tmp/turbolog-source.db",
        help="Source SQLite URL (default: sqlite:////tmp/turbolog-source.db).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"TRUNCATE {TABLES} before copying.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.src, args.force))
