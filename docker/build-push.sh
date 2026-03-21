#!/usr/bin/env bash
# ── Build and push LabClaw GPU image to GitHub Container Registry ────────────
#
# Usage:
#   ./docker/build-push.sh              # build + push :latest
#   ./docker/build-push.sh v0.19.0      # build + push :v0.19.0 + :latest
#   BUILD_ONLY=1 ./docker/build-push.sh # build only, no push
#
# Requires:
#   - docker login ghcr.io (use GITHUB_TOKEN with packages:write scope)
#   - or: echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

IMAGE="ghcr.io/opencurelabs/labclaw-gpu"
TAG="${1:-latest}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

echo "Building $IMAGE:$TAG ..."
docker build \
    -f "$SCRIPT_DIR/Dockerfile.gpu" \
    -t "$IMAGE:$TAG" \
    "$REPO_ROOT"

# Always also tag as latest when a version tag is given
if [[ "$TAG" != "latest" ]]; then
    docker tag "$IMAGE:$TAG" "$IMAGE:latest"
fi

if [[ "${BUILD_ONLY:-0}" == "1" ]]; then
    echo "Build complete (BUILD_ONLY=1, skipping push)"
    exit 0
fi

echo "Pushing $IMAGE:$TAG ..."
docker push "$IMAGE:$TAG"
if [[ "$TAG" != "latest" ]]; then
    docker push "$IMAGE:latest"
fi

echo "Done: $IMAGE:$TAG"
