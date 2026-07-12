#!/usr/bin/env bash
# Roll back vita-api to a previous image tag on the deploy host (P3-5).
#
# Usage (on host with config/.env.compose present):
#   PREVIOUS_IMAGE_TAG=abc1234 bash scripts/deploy/rollback.sh
#
# Optional env:
#   COMPOSE_ENV          default: config/.env.compose
#   COMPOSE_EXTRA_FILES  e.g. "-f docker-compose.smoke.yml" for smoke stack
#
# Requires: docker compose, prior env snapshot at config/.env.compose.backup (optional).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${ROOT}"

PREVIOUS_IMAGE_TAG="${PREVIOUS_IMAGE_TAG:-}"
COMPOSE_ENV="${COMPOSE_ENV:-config/.env.compose}"
COMPOSE_EXTRA_FILES="${COMPOSE_EXTRA_FILES:-}"

if [ -z "${PREVIOUS_IMAGE_TAG}" ]; then
  echo "[FAIL] Set PREVIOUS_IMAGE_TAG to the git SHA or tag to restore (e.g. export PREVIOUS_IMAGE_TAG=50a3c6e)" >&2
  exit 1
fi

if [ ! -f "${COMPOSE_ENV}" ]; then
  echo "[FAIL] Compose env missing: ${COMPOSE_ENV}" >&2
  exit 1
fi

BACKUP="${COMPOSE_ENV}.backup"
if [ -f "${BACKUP}" ]; then
  echo "[ROLLBACK] Restoring compose env snapshot from ${BACKUP}"
  cp "${BACKUP}" "${COMPOSE_ENV}"
fi

IMAGE="vita-api:${PREVIOUS_IMAGE_TAG}"
echo "[ROLLBACK] Tagging ${IMAGE} as vita-api:latest"
docker tag "${IMAGE}" vita-api:latest 2>/dev/null || {
  echo "[ROLLBACK] Local tag missing; pulling vita-api:${PREVIOUS_IMAGE_TAG} if registry configured"
  docker pull "${IMAGE}" || {
    echo "[FAIL] Cannot resolve image ${IMAGE}" >&2
    exit 1
  }
  docker tag "${IMAGE}" vita-api:latest
}

# Ensure compose uses retagged latest (smoke override reads VITA_API_IMAGE when set).
export VITA_API_IMAGE="vita-api:latest"

echo "[ROLLBACK] Recreating vita-api via compose"
# shellcheck disable=SC2086
docker compose --env-file "${COMPOSE_ENV}" ${COMPOSE_EXTRA_FILES} up -d vita-api --no-build --wait

bash scripts/deploy/smoke_check.sh
echo "[OK] Rollback complete (vita-api -> ${PREVIOUS_IMAGE_TAG})"
