#!/usr/bin/env bash
# ============================================================================
# deploy.sh — instalá una nueva versión de turbolog en el swarm con UN comando.
# ============================================================================
# ── CÓMO USAR (flujo completo de deploy) ─────────────────────────────────────
#
#   1. git push origin main        # GitHub buildea + publica la imagen (auto)
#   2. esperá ~3-5 min al workflow build-image (tilde verde en Actions)
#   3. ./deploy.sh                 # deploya :latest al swarm
#
#   ./deploy.sh <sha>              # rollback a un build específico
#
# Requisitos: gcloud logueado (`gcloud auth login`). La imagen TIENE que
# existir en GHCR antes del paso 3; si lo corrés antes, el rollout falla y el
# script aborta limpio (nada se rompe, reintentá cuando termine el build).
#
# ── Qué hace por dentro ─────────────────────────────────────────────────────
#   - Túnel IAP hasta un nodo manager (los nodos no tienen IP pública).
#   - Registra la imagen actual (para saber a qué volver si algo falla).
#   - docker service update --detach=false → BLOQUEA hasta que el rollout
#     converge y sale non-zero si falla (set -e lo detecta → aborta).
#   - Muestra el estado final real de los servicios.
# ============================================================================
set -euo pipefail

TAG="${1:-latest}"
IMAGE="ghcr.io/cperez-infoboy/turbolog:${TAG}"

# ── Ajustá estos 3 valores a tu swarm (el nombre del manager lo sacás con
#    `gcloud compute instances list`). Cualquier nodo manager sirve para
#    service update, no tiene que ser el Leader. ──────────────────────────────
MANAGER="swarm-node-1"
ZONE="southamerica-west1-a"
PROJECT="dockerswarm-491114"

# Wrapper de SSH reutilizable. StrictHostKeyChecking=no + KnownHosts vacío
# evitan que se cuelgue pidiendo confirmar la host key (script no-interactivo).
SSH_OPTS=(
  gcloud compute ssh "$MANAGER"
  --tunnel-through-iap --zone="$ZONE" --project="$PROJECT"
  --ssh-flag="-o StrictHostKeyChecking=no"
  --ssh-flag="-o UserKnownHostsFile=/dev/null"
)

echo "→ Rolling turbolog a ${IMAGE}"

# Imagen actual del backend (para rollback). Si falla la consulta, seguimos
# igual con "unknown" — no es razón para frenar el deploy.
PREV="$("${SSH_OPTS[@]}" -- \
  "docker service inspect turbolog_backend --format '{{.Spec.TaskTemplate.ContainerSpec.Image}}'" \
  2>/dev/null || echo "unknown")"
echo "  imagen actual: ${PREV}"

# --detach=false: el comando ESPERA a que el rollout converja (en vez de
# devolver el control al instante) y sale non-zero si no llega a 1/1.
# backend primero; si falla, set -e aborta y NO tocamos el scheduler
# (mejor un scheduler con imagen vieja que dos servicios rotos).
echo "→ Actualizando turbolog_backend (esperando convergencia)..."
"${SSH_OPTS[@]}" -- "docker service update --detach=false --image ${IMAGE} turbolog_backend"

echo "→ Actualizando turbolog_scheduler (esperando convergencia)..."
"${SSH_OPTS[@]}" -- "docker service update --detach=false --image ${IMAGE} turbolog_scheduler"

echo "✓ Rollout convergió. Estado actual:"
"${SSH_OPTS[@]}" -- \
  "docker service ls --filter name=turbolog --format 'table {{.Name}}\t{{.Replicas}}\t{{.Image}}'"
echo
echo "  Si algo falló, volvé con: ./deploy.sh <tag>"
echo "  (la imagen anterior era: ${PREV})"
