#!/usr/bin/env bash
# Remote deploy via SSH (P3-5). Secrets stay in GitHub Actions env — never echoed.
#
# Required env:
#   DEPLOY_HOST          target hostname or IP
#   DEPLOY_KEY_PATH      path to private key file (600)
# Optional:
#   DEPLOY_USER          default: deploy
#   DEPLOY_PATH          default: /opt/vita
#   GIT_SHA              image tag (default: latest)

set -euo pipefail

: "${DEPLOY_HOST:?DEPLOY_HOST is required}"
: "${DEPLOY_KEY_PATH:?DEPLOY_KEY_PATH is required}"

DEPLOY_USER="${DEPLOY_USER:-deploy}"
DEPLOY_PATH="${DEPLOY_PATH:-/opt/vita}"
GIT_SHA="${GIT_SHA:-latest}"
IMAGE_TAG="vita-api:${GIT_SHA}"

SSH_OPTS=(-i "${DEPLOY_KEY_PATH}" -o StrictHostKeyChecking=accept-new -o BatchMode=yes)

echo "[DEPLOY] Target ${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH} (image ${IMAGE_TAG})"

# Backup remote compose env before replace (rollback support)
ssh "${SSH_OPTS[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" bash -s <<EOF
set -euo pipefail
mkdir -p "${DEPLOY_PATH}/config"
if [ -f "${DEPLOY_PATH}/config/.env.compose" ]; then
  cp "${DEPLOY_PATH}/config/.env.compose" "${DEPLOY_PATH}/config/.env.compose.backup"
fi
EOF

# Sync generated compose env (materialized on runner, gitignored pattern)
scp "${SSH_OPTS[@]}" config/.env.compose "${DEPLOY_USER}@${DEPLOY_HOST}:${DEPLOY_PATH}/config/.env.compose"

# Pull/up on remote (image must be available on host registry or pre-loaded)
ssh "${SSH_OPTS[@]}" "${DEPLOY_USER}@${DEPLOY_HOST}" bash -s <<EOF
set -euo pipefail
cd "${DEPLOY_PATH}"
export VITA_API_IMAGE="${IMAGE_TAG}"
docker tag "${IMAGE_TAG}" vita-api:latest
docker compose --env-file config/.env.compose build postgres
docker compose \
  --env-file config/.env.compose \
  -f docker-compose.yml \
  -f docker-compose.smoke.yml \
  up -d postgres redis vita-api --no-build --wait
bash scripts/deploy/smoke_check.sh
EOF

echo "[OK] Remote deploy finished"
