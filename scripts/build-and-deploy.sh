# build-and-deploy.sh
#!/bin/bash
set -e

echo "Building and deploying Swarm Agent to K3s..."

kubectl delete all --all -n swarm-system

### Building image

cd .. 
set -euo pipefail

IMAGE_NAME="swarm-agent"
VERSION="7.0"

# detect architecture
ARCH=$(uname -m)
case "$ARCH" in
    x86_64)
        PLATFORM="linux/amd64"
        SUFFIX="amd"
        ;;
    aarch64 | arm64)
        PLATFORM="linux/arm64"
        SUFFIX="arm"
        ;;
    *)
        echo "❌ Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

TAG="${VERSION}.${SUFFIX}"
REMOTE="zewang42/${IMAGE_NAME}:${TAG}"

echo "✅ Detected architecture: $ARCH"
echo "✅ Building for $PLATFORM"
echo "✅ Tagging as $REMOTE"

# build & push
docker buildx build \
    --platform "$PLATFORM" \
    -t "$REMOTE" \
    --push .

echo "🎉 Done: pushed $REMOTE"


# Apply SA's Kubernetes manifests
echo "3. Deploying SA to K3s..."
kubectl apply -f k3s/

echo "4. Deployment completed!"

# Show status
echo "5. Current status:"
kubectl get all -n swarm-system

