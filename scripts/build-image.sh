#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVICE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
VOICE_GATEWAY_TAG="${VOICE_GATEWAY_TAG:-latest}"
VOICE_GATEWAY_BASE_IMAGE="${VOICE_GATEWAY_BASE_IMAGE:-${REGISTRY_URL}/openhax/melo-voice-base:2026-03-19}"
VOICE_GATEWAY_IMAGE="${VOICE_GATEWAY_IMAGE:-${REGISTRY_URL}/openhax/voice-gateway:${VOICE_GATEWAY_TAG}}"

cd "$SERVICE_DIR"
docker build \
  -f Dockerfile \
  --build-arg VOICE_GATEWAY_BASE_IMAGE="$VOICE_GATEWAY_BASE_IMAGE" \
  -t "$VOICE_GATEWAY_IMAGE" \
  .

echo "built: $VOICE_GATEWAY_IMAGE"
