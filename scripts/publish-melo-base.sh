#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
MELO_BASE_TAG="${MELO_BASE_TAG:-2026-03-19}"
ML_BASE_IMAGE="${ML_BASE_IMAGE:-${REGISTRY_URL}/shibboleth/ml-base:cuda12.4-2026-03-18}"
MELO_BASE_IMAGE="${MELO_BASE_IMAGE:-${REGISTRY_URL}/openhax/melo-voice-base:${MELO_BASE_TAG}}"
MELO_BASE_IMAGE_LATEST="${MELO_BASE_IMAGE_LATEST:-${REGISTRY_URL}/openhax/melo-voice-base:latest}"

docker pull "$ML_BASE_IMAGE" >/dev/null

cd "$SERVICE_DIR"
docker build \
  -f Dockerfile.melo-base \
  --build-arg ML_BASE_IMAGE="$ML_BASE_IMAGE" \
  -t "$MELO_BASE_IMAGE" \
  -t "$MELO_BASE_IMAGE_LATEST" \
  .

docker push "$MELO_BASE_IMAGE"
docker push "$MELO_BASE_IMAGE_LATEST"

echo "published: $MELO_BASE_IMAGE"
echo "published: $MELO_BASE_IMAGE_LATEST"
