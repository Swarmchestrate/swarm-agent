#!/bin/bash
set -e
cd "$(dirname "$0")"

SAT="${1:-../KB/innorenew/innorenew-sat-combined-test.yaml}"
SIM="${2:-../KB/innorenew/simulated_nodes_metrics_cluster.json}"
USE_EMS="${USE_EMS:-false}"
IMAGE="${IMAGE:-docker.io/library/swarm-agent:ai-integration}"
LEADER="${LEADER:-$(kubectl get nodes -l node-role.kubernetes.io/control-plane -o jsonpath='{.items[0].metadata.name}')}"
DS=../k3s/02-daemonset-swarm-agent.yaml

if [ -z "$LEADER" ]; then
  echo "No control-plane node found; run again with LEADER=<node name>"
  exit 1
fi
echo "Leader: $LEADER   SAT: $SAT   image: $IMAGE   SA_USE_EMS: $USE_EMS"

echo "=== 1/4 Clean the cluster ==="
bash clear-cluster.sh audio-class-v1
kubectl label node "$LEADER" labels.swarmchestrate.eu/ms_id=audio-class --overwrite

if [ "$USE_EMS" = "false" ]; then
  echo "=== 2/4 Put the replay data in place before the SA starts ==="
  export SIM_METRICS="$SIM"
  kubectl create namespace swarm-system
  kubectl create configmap swarm-agent-simdata -n swarm-system --from-file=metrics.json="$SIM_METRICS"
else
  echo "=== 2/4 Live EMS data: no replay file ==="
fi

echo "=== 3/4 Deploy with $SAT, $IMAGE and SA_USE_EMS=$USE_EMS ==="
cp "$DS" "$DS.orig"
trap 'mv -f "$DS.orig" "$DS" 2>/dev/null || true' EXIT
sed -i -e "s|^\( *\)image: ghcr.io/swarmchestrate/swarm-agent:optimizer-interfaces|\1image: $IMAGE|" \
       -e "s|imagePullPolicy: Always|imagePullPolicy: IfNotPresent|" \
       -e "/name: SA_USE_EMS/{n;s|value: \"true\"|value: \"$USE_EMS\"|}" "$DS"
bash deploy-sa.sh innorenew-test "$SAT" "$LEADER"
mv -f "$DS.orig" "$DS"

echo "=== 4/4 Check ==="
echo "SA image: $(kubectl get daemonset swarm-agent -n swarm-system -o jsonpath='{.spec.template.spec.containers[0].image}')"
echo "SA_USE_EMS: $(kubectl get daemonset swarm-agent -n swarm-system -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="SA_USE_EMS")].value}')"
sleep 30
echo "--- pods in swarm-system"
kubectl get pods -n swarm-system
echo "--- EMS pods: $(kubectl get pods -n swarm-system --no-headers | grep -cE 'emsserver|ems-client|netdata' || true)"
kubectl get pods -o wide

echo ""
echo "=== Log (press Ctrl+C to stop watching; the SA keeps running) ==="
L=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName="$LEADER" --sort-by=.metadata.creationTimestamp | grep swarm-agent | tail -1)
kubectl logs -n swarm-system -f "$L" | grep --line-buffered -E "MonitoringDeploy|replay|per-node|SLOs from SAT|subscribed|DecisionLoop|inputs ready|Optimiser"
