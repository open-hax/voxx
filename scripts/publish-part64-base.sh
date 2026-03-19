#!/usr/bin/env bash
set -euo pipefail

echo "deprecated: the voice gateway now reuses localhost:5000/shibboleth/ml-base:cuda12.4-2026-03-18 as its ML base" >&2
echo "use ./scripts/publish-melo-base.sh instead" >&2
exit 1
