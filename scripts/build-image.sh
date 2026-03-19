#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
VOXX_TAG="${VOXX_TAG:-${VOICE_GATEWAY_TAG:-latest}}"
VOXX_BASE_IMAGE="${VOXX_BASE_IMAGE:-${VOICE_GATEWAY_BASE_IMAGE:-${REGISTRY_URL}/openhax/melo-voice-base:2026-03-19}}"
VOXX_IMAGE="${VOXX_IMAGE:-${VOICE_GATEWAY_IMAGE:-${REGISTRY_URL}/openhax/voxx:${VOXX_TAG}}}"

cd "$SERVICE_DIR"
docker build \
  -f Dockerfile \
  --build-arg VOXX_BASE_IMAGE="$VOXX_BASE_IMAGE" \
  -t "$VOXX_IMAGE" \
  .

echo "built: $VOXX_IMAGE"
