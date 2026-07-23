#!/bin/bash
# One-command bootstrap for the Swarm Agent.
#
# Wraps the three manual steps (generate configs -> apply -> wait) so a fresh
# deploy is a single command. After this, the SA leader autonomously deploys the
# monitoring stack, deploys the application, and starts collecting metrics.
#
# Usage:
#   bash deploy-sa.sh                 # defaults: job=stressng, seconds SAT, leader=$(hostname)
#   bash deploy-sa.sh <job> <sat> <leader>
#
# Run this from the scripts/ directory (or anywhere - it cd's to its own dir).
set -e

cd "$(dirname "$0")"

JOB_ID="${1:-stressng}"
TOSCA="${2:-../KB/stressng_SAT_monitoring.yaml}"
LEADER="${3:-$(hostname)}"
OUT="../output/cluster_${JOB_ID}"

echo "=== 1/3 Generating SA configs (job=$JOB_ID, sat=$TOSCA, leader=$LEADER) ==="
python3 generate-configMaps.py --job-id "$JOB_ID" --tosca-path "$TOSCA" --hub-ra-ip localhost --leader "$LEADER"

echo "=== 2/3 Applying manifests ==="
kubectl apply -f "$OUT/"

echo "=== 3/3 Waiting for the SA to roll out ==="
kubectl rollout status daemonset/swarm-agent -n swarm-system

echo ""
echo "Swarm Agent deployed. It now auto-deploys the monitoring stack + app and starts collecting."
echo "Watch it with:"
echo "  kubectl logs -n swarm-system -f \$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$LEADER | grep swarm-agent) | grep --line-buffered -E 'MonitoringDeploy|Application initialised|poll interval|subscribed to|poll done'"
