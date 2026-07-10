#!/bin/sh
set -e

# Run Alembic migrations unless explicitly disabled. The default (RUN_MIGRATIONS
# unset or anything other than "false") RUNS migrations, preserving the local
# `docker compose` dev UX (backend + scheduler both migrate on boot; benign
# idempotent race on the alembic_version row lock). Docker Swarm production sets
# RUN_MIGRATIONS=false on backend and scheduler so a dedicated one-shot migrate
# service owns migrations exclusively and the entrypoint's `exec "$@"` runs the
# CMD (uvicorn / scheduler) directly.
if [ "$RUN_MIGRATIONS" != "false" ]; then
    uv run alembic upgrade head
fi

exec "$@"
