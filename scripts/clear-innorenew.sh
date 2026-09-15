#!/bin/bash

set -e
cd "$(dirname "$0")"

bash clear-cluster.sh audio-class-v1

echo ""
echo "=== Removing any stress-ng application left from a Phase 1 run ==="
kubectl delete deployment stressng-v1 -n default --ignore-not-found

echo ""
echo "Cleared. Deploy InnoRenew with:  bash deploy-innorenew.sh"
