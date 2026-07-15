#!/bin/sh
# ============================================================================
# Turbolog — one-time Docker Swarm secrets bootstrap
# ============================================================================
# Run ONCE on a Swarm manager. Creates the 7 versioned secrets (`_v1`) that
# docker-stack.yml.tmpl references as `external: true`.
#
# The operator supplies each secret value via a secure prompt (echo disabled
# for line secrets). NEVER commit real secret values to the repo — only this
# script is version-controlled.
#
# Idempotent-ish: every `docker secret create ... || true` does NOT abort on a
# name conflict, so re-running after a partial bootstrap creates the remaining
# secrets. To ROTATE a value, create a NEW versioned secret (e.g.
# `jwt_secret_v2`) — do NOT try to recreate `_v1` (Swarm rejects overwriting an
# existing secret name, and `docker secret rm` FAILS while a service uses it).
#
# ROTATION (live, no rebuild, no rm-while-in-use, keeps the field-named file):
#   docker service update \
#     --secret-rm jwt_secret_v1 \
#     --secret-add source=jwt_secret_v2,target=jwt_secret \
#     turbolog_backend
# (apply to every service that mounts the secret: turbolog_backend,
#  turbolog_scheduler; for auth-proxy/cloudflared use their single secret.)
#
# The `target=<field>` alias is MANDATORY. pydantic `secrets_dir` reads the
# file named after the FIELD (/run/secrets/jwt_secret), NOT the versioned name
# (/run/secrets/jwt_secret_v2). A bare `--secret-add jwt_secret_v2` (no target)
# makes the field-named file vanish and pydantic falls back to its insecure
# default — the very failure `assert_prod_secrets` exists to catch.
#
# The 7 genuine secrets (lowercase, underscore — these are the pydantic field
# names AND the Swarm source base names, versioned with `_v1`):
#   database_url google_client_secret jwt_secret jira_api_token
#   llm_api_key telegram_bot_token cloudsql_sa_key
# NOTE: the Cloudflare tunnel token is NOT here — Turbolog reuses the swarm's
# shared `cf` tunnel (no dedicated cloudflared service, no CLOUDFLARE_TOKEN).
# ============================================================================

set -eu

# Require a Swarm manager.
if ! docker info --format '{{.Swarm.ControlManager}}' 2>/dev/null | grep -q true; then
  echo "ERROR: this node is not a Swarm manager." >&2
  echo "       Run 'docker swarm init' (or join as a manager) first." >&2
  exit 1
fi

# Restore terminal echo no matter how we exit (in case read is interrupted).
trap '[ -t 0 ] && stty echo 2>/dev/null || true' EXIT

printf '%s\n' "Turbolog Swarm secrets bootstrap — creating 7 *_v1 secrets."
printf '%s\n' "Re-runs skip secrets that already exist (|| true on each create)."
printf '%s\n\n' "Line inputs are hidden. NEVER commit real values."

# read_secret_line <swarm_name> <prompt_label>
# Reads a single-line secret (echo off) and pipes it (no trailing newline) to
# `docker secret create`. `|| true` keeps going on a name conflict.
read_secret_line() {
  name="$1"; label="$2"
  printf '%s' "$label: "
  if [ -t 0 ]; then stty -echo 2>/dev/null || true; fi
  read -r value
  if [ -t 0 ]; then stty echo 2>/dev/null || true; fi
  printf '\n'
  printf '%s' "$value" | docker secret create "$name" - 2>&1 | sed "s/^/  /" \
    || echo "  (skipped: $name already exists or create failed)"
  unset value
}

# read_secret_file <swarm_name> <prompt_label>
# For multi-line secrets (the service-account JSON). Reads a FILE PATH from the
# operator and streams the file bytes verbatim into `docker secret create`.
read_secret_file() {
  name="$1"; label="$2"
  printf '%s' "$label (path to file): "
  read -r path
  if [ ! -r "$path" ]; then
    echo "ERROR: cannot read '$path' for $name" >&2
    exit 1
  fi
  docker secret create "$name" - < "$path" 2>&1 | sed "s/^/  /" \
    || echo "  (skipped: $name already exists or create failed)"
}

# NOTE: database_url value = the full asyncpg URL pointing at the auth-proxy,
# e.g.  postgresql+asyncpg://turbolog:<password>@auth-proxy:5432/turbolog
read_secret_line database_url_v1       "DATABASE_URL (postgresql+asyncpg://user:pass@auth-proxy:5432/turbolog)"
read_secret_line google_client_secret_v1 "GOOGLE_CLIENT_SECRET"
read_secret_line jwt_secret_v1          "JWT_SECRET (>=32 chars, NOT dev-secret-change-me)"
read_secret_line jira_api_token_v1      "JIRA_API_TOKEN"
read_secret_line llm_api_key_v1         "LLM_API_KEY (empty is valid — feature disabled)"
read_secret_line telegram_bot_token_v1  "TELEGRAM_BOT_TOKEN"
read_secret_file cloudsql_sa_key_v1     "CLOUDSQL_SA_KEY (Cloud SQL service-account JSON)"

printf '\n%s\n' "Done."
printf '%s\n' "Verify:   docker secret ls | grep '_v1'"
printf '%s\n' "Deploy:   docker stack deploy -c docker-stack.yml turbolog"
