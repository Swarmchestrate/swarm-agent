# build-and-deploy.sh
#!/bin/bash
set -e


### Building image

cd .. 
set -euo pipefail

# -------- Config --------
IMAGE_NAME="swarm-agent-7.0"          # <-- set this
NAMESPACE="zewang42"                  # docker hub / ghcr namespace
# ------------------------

# detect architecture
ARCH=$(uname -m)
case "$ARCH" in
  x86_64)  PLATFORM="linux/amd64"; SUFFIX="amd" ;;
  aarch64|arm64) PLATFORM="linux/arm64"; SUFFIX="arm" ;;
  *) echo "❌ Unsupported architecture: $ARCH"; exit 1 ;;
esac

TAG="${SUFFIX}"
REMOTE="${NAMESPACE}/${IMAGE_NAME}:${TAG}"

echo "✅ Detected architecture: $ARCH"
echo "✅ Building for ${PLATFORM}"
echo "✅ Tagging as ${REMOTE}"

# check for buildx availability
if docker buildx version >/dev/null 2>&1; then
  # ensure a builder is selected
  if ! docker buildx inspect >/dev/null 2>&1; then
    echo "ℹ️  No active buildx builder; creating one..."
    docker buildx create --use
  fi

  echo "🚧 Using buildx..."
  docker buildx build \
    --platform "${PLATFORM}" \
    -t "${REMOTE}" \
    --push .
else
  echo "⚠️ buildx not found; falling back to classic docker build (current arch only)"
  docker build -t "${REMOTE}" .
  docker push "${REMOTE}"
fi

echo "🎉 Done: pushed ${REMOTE}"


