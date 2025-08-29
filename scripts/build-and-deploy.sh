# build-and-deploy.sh
#!/bin/bash
set -e

echo "Building and deploying Swarm Agent to K3s..."

kubectl delete all --all -n swarm-system

cd /Users/wangze/Desktop/Swarmchestrate/git/SA 

# Build Docker image
echo "1. Building Docker image..."
docker build -t swarm-agent:7.0.arm .
# Load image into k3s (if using local k3s)

#echo "2. Pushing image into DockerHub..."
#docker tag swarm-agent:7.0.arm swarm-agent:7.0.arm
docker tag swarm-agent:7.0.arm zewang42/swarm-agent:7.0.arm
docker push zewang42/swarm-agent:7.0.arm


#docker buildx create --use

#docker buildx build --platform linux/amd64 \
#    -t zewang42/swarm-agent:6.0.amd \
#    --push .




# Apply Kubernetes manifests
echo "3. Deploying to K3s..."
kubectl apply -f k3s_test/

# Wait for deployments
echo "4. Waiting for deployments to be ready..."
kubectl wait --for=condition=available deployment/swarm-agent-leader -n swarm-system --timeout=20s
kubectl wait --for=condition=available deployment/swarm-agent-worker -n swarm-system --timeout=20s

echo "5. Deployment completed!"

# Show status
echo "6. Current status:"
kubectl get all -n swarm-system

echo ""
echo "To check logs:"
echo "  Leader: kubectl logs -f deployment/swarm-agent-leader -n swarm-system"
echo "  Worker: kubectl logs -f deployment/swarm-agent-worker -n swarm-system"


