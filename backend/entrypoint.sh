#!/bin/sh
set -e

# Run Alembic migrations unless explicitly disabled. The default (RUN_MIGRATIONS
# unset or anything other than "false") RUNS migrations, preserving the local
# `docker compose` dev UX (backend + scheduler both migrate on boot; benign
# idempotent race on the alembic_version row lock). In Swarm production the
# backend migrates on boot too (RUN_MIGRATIONS unset -> runs alembic; safe
# because replicas:1 + stop-first means only one backend exists at a time), and
# the scheduler sets RUN_MIGRATIONS=false so it doesn't duplicate the work.
# The entrypoint's `exec "$@"` then runs the CMD (uvicorn / scheduler) directly.
if [ "$RUN_MIGRATIONS" != "false" ]; then
    uv run alembic upgrade head
fi

exec "$@"
