#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REGISTRY_URL="${REGISTRY_URL:-localhost:5000}"
VOXX_TAG="${VOXX_TAG:-${VOICE_GATEWAY_TAG:-latest}}"
VOXX_IMAGE="${VOXX_IMAGE:-${VOICE_GATEWAY_IMAGE:-${REGISTRY_URL}/openhax/voxx:${VOXX_TAG}}}"

"$SCRIPT_DIR/build-image.sh"
docker push "$VOXX_IMAGE"

echo "published: $VOXX_IMAGE"
