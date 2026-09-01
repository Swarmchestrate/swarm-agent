#!/bin/bash
# One-command bootstrap for the Swarm Agent.
#
# Wraps the three manual steps (generate configs -> apply -> wait) so a fresh
# deploy is a single command. After this, the SA leader autonomously deploys the
# monitoring stack, deploys the application, and starts collecting metrics.
#
# Usage:
#   bash deploy-sa.sh                 # defaults: job=stressng, seconds SAT, leader auto-detected
#   bash deploy-sa.sh <job> <sat> <leader>
#
# Run this from the scripts/ directory (or anywhere - it cd's to its own dir).
set -e

cd "$(dirname "$0")"

JOB_ID="${1:-stressng}"
TOSCA="${2:-../KB/stressng_SAT_monitoring.yaml}"
# Leader node name. Given explicitly as the 3rd argument, otherwise detected:
# this machine's hostname when it is also a Kubernetes node name, else the only
# node of a single-node cluster. (Hostname and node name are not always equal.)
LEADER="${3:-}"
if [ -z "$LEADER" ]; then
  NODES=$(kubectl get nodes -o name 2>/dev/null | sed "s|node/||")
  if [ -z "$NODES" ]; then
    echo "ERROR: cannot list Kubernetes nodes - is the cluster reachable?" >&2
    exit 1
  elif echo "$NODES" | grep -qx "$(hostname)"; then
    LEADER="$(hostname)"
  elif [ "$(echo "$NODES" | wc -l)" -eq 1 ]; then
    LEADER="$NODES"
    echo "note: hostname '$(hostname)' is not a node name; using the only node '$LEADER'"
  else
    echo "ERROR: could not determine the leader node." >&2
    echo "  hostname '$(hostname)' does not match any Kubernetes node." >&2
    echo "  Pass it explicitly:  bash deploy-sa.sh <job-id> <sat-path> <leader-node>" >&2
    echo "  Available nodes:" >&2
    echo "$NODES" | sed "s|^|    |" >&2
    exit 1
  fi
fi
OUT="../output/cluster_${JOB_ID}"

echo "=== 1/3 Generating SA configs (job=$JOB_ID, sat=$TOSCA, leader=$LEADER) ==="
python3 generate-configMaps.py --job-id "$JOB_ID" --tosca-path "$TOSCA" --hub-ra-ip localhost --leader "$LEADER"

echo "=== 2/3 Applying manifests ==="
kubectl apply -f "$OUT/"

# Restart even when the manifests are unchanged: the image tag is mutable
# (CI republishes :optimizer-interfaces) and the SAT is read at startup, so
# without this a new image or a changed SAT would not be picked up.
echo "=== 3/3 Restarting the SA and waiting for it to roll out ==="
kubectl rollout restart daemonset/swarm-agent -n swarm-system
kubectl rollout status daemonset/swarm-agent -n swarm-system

echo ""
echo "Swarm Agent deployed. It now auto-deploys the monitoring stack + app and starts collecting."
echo "Watch it with:"
echo "  kubectl logs -n swarm-system -f \$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$LEADER | grep swarm-agent) | grep --line-buffered -E 'MonitoringDeploy|AppDeploy|poll interval|subscribed|Cluster status|inputs ready|Optimiser|poll done'"
