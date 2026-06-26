#!/usr/bin/env bash
set -euo pipefail

TUNNEL_NAME="turbolog-test"
TUNNEL_URL="turbolog-test.infositio.dev"
LOCAL_PORT="8081"

if ! command -v cloudflared &>/dev/null; then
  echo "❌ cloudflared no encontrado. Instalalo con: yay -S cloudflared"
  exit 1
fi

echo "⏳ Verificando backend en localhost:${LOCAL_PORT}..."
if ! curl -sf --max-time 5 "http://localhost:${LOCAL_PORT}/api/health" &>/dev/null; then
  echo "❌ El backend no responde en localhost:${LOCAL_PORT}"
  echo "   Levantalo primero con: docker compose up -d"
  exit 1
fi

echo "✅ Backend activo"
echo "🌐 Túnel: https://${TUNNEL_URL}"
echo "   Ctrl+C para detener"
echo ""

cloudflared tunnel run "${TUNNEL_NAME}"
