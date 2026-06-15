#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE_NAME="swarm-agent-7.0"
NAMESPACE="zewang42"

TAG_VERSION="7.0"
REMOTE_VERSION="${NAMESPACE}/${IMAGE_NAME}:${TAG_VERSION}"
REMOTE_LATEST="${NAMESPACE}/${IMAGE_NAME}:standalone"

BUILDER_NAME="multiarch"

echo "Building multi-arch image"
echo "Image: ${REMOTE_VERSION}"
echo "Also tagging: ${REMOTE_LATEST}"

if ! docker buildx version >/dev/null 2>&1; then
  echo "docker buildx is required for multi-arch builds"
  exit 1
fi

if ! docker buildx inspect "${BUILDER_NAME}" >/dev/null 2>&1; then
  echo "Creating buildx builder: ${BUILDER_NAME}"
  docker buildx create --name "${BUILDER_NAME}" --use
else
  docker buildx use "${BUILDER_NAME}"
fi

docker buildx inspect --bootstrap

docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -t "${REMOTE_VERSION}" \
  -t "${REMOTE_LATEST}" \
  --push \
  .

echo "Done"
echo "Pushed:"
echo "  ${REMOTE_VERSION}"
echo "  ${REMOTE_LATEST}"

echo "Verify with:"
echo "  docker buildx imagetools inspect ${REMOTE_LATEST}"
