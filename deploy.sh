#!/usr/bin/env bash
# ============================================================================
# deploy.sh — instalá una nueva versión en el swarm con UN comando.
# ============================================================================
# Uso (desde tu notebook, con gcloud ya logueado):
#   ./deploy.sh              → instala la imagen :latest (la última que buildó GitHub)
#   ./deploy.sh <tag>        → instala un tag específico (ej: un sha, para rollback)
#
# Qué hace: entra al nodo manager por túnel IAP (los nodos no tienen IP pública)
# y le dice al swarm "actualizá el backend y el scheduler a esta imagen".
# El swarm descarga la imagen nueva y reinicia los servicios solito.
# ============================================================================
set -euo pipefail

TAG="${1:-latest}"
IMAGE="ghcr.io/cperez-infoboy/turbolog:${TAG}"

# ── Ajustá estos 3 valores a tu swarm (el nombre del manager lo sacás con
#    `gcloud compute instances list`). ────────────────────────────────────────
MANAGER="NOMBRE_DEL_MANAGER"          # TODO operador: nombre de tu nodo manager
ZONE="southamerica-west1-a"
PROJECT="dockerswarm-491114"

echo "→ Actualizando turbolog_backend y turbolog_scheduler a ${IMAGE}"
gcloud compute ssh "$MANAGER" --tunnel-through-iap --zone="$ZONE" --project="$PROJECT" -- \
  "docker service update --image ${IMAGE} turbolog_backend && \
   docker service update --image ${IMAGE} turbolog_scheduler"

echo "✓ Listo. El swarm está descargando la imagen y reiniciando los servicios."
echo "  Mirá el estado con: gcloud compute ssh $MANAGER -- docker service ls"
