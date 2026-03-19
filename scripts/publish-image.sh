#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
VOICE_GATEWAY_TAG="${VOICE_GATEWAY_TAG:-latest}"
VOICE_GATEWAY_IMAGE="${VOICE_GATEWAY_IMAGE:-${REGISTRY_URL}/openhax/voice-gateway:${VOICE_GATEWAY_TAG}}"

"$SCRIPT_DIR/build-image.sh"
docker push "$VOICE_GATEWAY_IMAGE"

echo "published: $VOICE_GATEWAY_IMAGE"
