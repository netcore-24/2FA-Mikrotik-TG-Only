#!/usr/bin/env bash
set -euo pipefail

# Usage:
#   ./routeros/build-arm64.sh docker.io/<user>/mikrotik-2fa-telegram-only:arm64

IMAGE="${1:-}"
if [[ -z "${IMAGE}" ]]; then
  echo "Usage: $0 <image>"
  echo "Example: $0 docker.io/<user>/mikrotik-2fa-telegram-only:arm64"
  exit 1
fi

docker buildx build --platform linux/arm64 -t "${IMAGE}" --push .
