#!/bin/bash
# One-command health check for the Swarm Agent stack.
#
# Shows: pods, which library handled the app deploy, monitoring loop health,
# the latest cluster-status mapping, and any errors - all in one run.
#
# Usage:  bash sa-status.sh            (run on the control-plane node)

LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName="$(hostname)" 2>/dev/null | grep swarm-agent | sed "s|pod/||")

echo "==================== SWARM AGENT STATUS ===================="
echo "Leader pod: ${LEADER:-NOT FOUND}"
echo ""

echo "--- Pods (swarm-system) ---"
kubectl get pods -n swarm-system -o wide 2>/dev/null || echo "namespace missing - SA not deployed"
echo ""
echo "--- Pods (default: app + monitoring stack) ---"
kubectl get pods -n default 2>/dev/null

if [ -z "$LEADER" ]; then
  echo ""
  echo "No leader pod found - deploy with: bash deploy-sa.sh"
  exit 1
fi

LOGS=$(kubectl logs -n swarm-system "$LEADER" 2>/dev/null)

echo ""
echo "--- Startup: what did the leader do? ---"
echo "$LOGS" | grep -E "MonitoringDeploy|AppDeploy|Applying |Application initialised|poll interval|subscribed to" | head -8

echo ""
echo "--- Last 3 poll results (monitoring + SLO) ---"
echo "$LOGS" | grep "poll done" | tail -3

echo ""
echo "--- Last cluster status (pod->node input for the Optimiser) ---"
echo "$LOGS" | grep "Cluster status" | tail -2

echo ""
echo "--- Warnings/errors in the leader log (last 5) ---"
echo "$LOGS" | grep -E "WARNING|ERROR" | tail -5 || echo "none"

echo ""
echo "--- Known-issue check ---"
N409=$(echo "$LOGS" | grep -c "AlreadyExists")
echo "409 AlreadyExists count: $N409 (expect 0 since apply_manifest)"
FB=$(echo "$LOGS" | grep -c "using direct-API fallback")
echo "k3s-client mapping fallback used: $FB time(s) (goes to 0 once the lib fix is released)"
echo "============================================================"
