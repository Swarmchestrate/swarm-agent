#!/bin/bash

set -e
cd "$(dirname "$0")"

SAT="../KB/innorenew/ir_sat_madrid.yaml"

if [ ! -f "$SAT" ]; then
  echo "ERROR: $SAT not found. Run 'git pull' in the repository first." >&2
  exit 1
fi

SIM="../KB/innorenew/simulated_nodes_metrics_fixed.json"
if [ ! -f "$SIM" ]; then
  echo "ERROR: $SIM not found. Run 'git pull' in the repository first." >&2
  exit 1
fi

echo "=== Node labels ==="
kubectl get nodes -o custom-columns='NODE:.metadata.name,MS_ID:.metadata.labels.labels\.swarmchestrate\.eu/ms_id'
echo ""

SIM_METRICS="$SIM" bash deploy-sa.sh innorenew "$SAT"

echo ""
echo "Watch the decisions with:"
echo "  LEADER=\$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=\$(hostname) | grep swarm-agent | sed 's|pod/||')"
echo "  kubectl logs -f -n swarm-system \$LEADER | grep --line-buffered -E 'Cluster status|inputs ready|Optimiser'"
