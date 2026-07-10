#!/usr/bin/env python3
"""Best-effort NULL-row seed for the migration round-trip gate.

Connects to the DB at ``DATABASE_URL``, reflects all tables, and inserts ONE
row per table with every nullable column set to ``NULL``. Non-nullable columns
without a default receive a type-appropriate placeholder (``""``, ``0``, ...) so
the INSERT can succeed. Tables that reject the row (FK ordering, unique
constraints, NOT-NULL with no plausible placeholder, ...) are SKIPPED — this is
defense-in-depth, not a correctness fixture.

Why
---
After this seed, a subsequent ``alembic downgrade -1`` + ``alembic upgrade head``
FAILS if the re-applied migration tightens a nullable column to NOT NULL while
NULL data is present. The static op-scan (``check_migrations.py``) is the
AUTHORITY for nullable->non-null; this seed is belt-and-suspenders.

Engine-agnostic (reflects the schema via SQLAlchemy); CI runs it against the
Postgres service container in the additive-migration-gate job, e.g.::

    DATABASE_URL=postgresql+asyncpg://turbolog:turbolog@localhost:5432/turbolog \\
        uv run python ../scripts/seed_scratch_nulls.py
"""
from __future__ import annotations

import asyncio
import os
import sys

import sqlalchemy as sa
from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import create_async_engine


async def main() -> int:
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("error: DATABASE_URL is not set", file=sys.stderr)
        return 2

    engine = create_async_engine(url)
    seeded = 0
    skipped = 0
    try:
        async with engine.connect() as conn:

            def reflect(connection):
                md = MetaData()
                md.reflect(connection)
                return md

            md = await conn.run_sync(reflect)
            for tname, tbl in md.tables.items():
                row: dict[str, object] = {}
                for col in tbl.columns:
                    if col.nullable:
                        row[col.name] = None
                        continue
                    if col.default is not None or col.server_default is not None:
                        # Let the Python/DB default fire.
                        continue
                    if isinstance(col.type, sa.String):
                        row[col.name] = ""
                    elif isinstance(col.type, (sa.Integer, sa.Numeric)):
                        row[col.name] = 0
                    elif isinstance(col.type, sa.Boolean):
                        row[col.name] = False
                    elif isinstance(col.type, sa.Date):
                        row[col.name] = "1970-01-01"
                    elif isinstance(col.type, sa.DateTime):
                        row[col.name] = "1970-01-01 00:00:00"
                    else:
                        row[col.name] = None
                try:
                    await conn.execute(tbl.insert().values(row))
                    seeded += 1
                except Exception as exc:  # best-effort: skip constrained tables
                    skipped += 1
                    print(f"skip {tname}: {exc.__class__.__name__}: {exc}", file=sys.stderr)
            await conn.commit()
    finally:
        await engine.dispose()

    print(f"seeded {seeded} table(s) with NULL rows ({skipped} skipped)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
