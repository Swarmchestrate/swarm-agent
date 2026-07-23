#!/bin/bash
# Clear the cluster back to a fresh slate (the reverse of deploy-sa.sh).
#
# Removes the Swarm Agent, the application it deployed, and the monitoring stack
# it deployed. Does NOT touch k3s system pods or python-shell. Safe to run when
# some pieces are already gone (uses --ignore-not-found).
#
# Usage:
#   bash clear-cluster.sh            # app defaults to stressng-v1
#   bash clear-cluster.sh <app-deployment-name>

APP="${1:-stressng-v1}"

echo "=== 1/3 Removing the Swarm Agent ==="
kubectl delete namespace swarm-system --ignore-not-found
kubectl delete clusterrole swarm-agent-role --ignore-not-found
kubectl delete clusterrolebinding swarm-agent-binding --ignore-not-found

echo "=== 2/3 Removing the application ($APP) ==="
kubectl delete deployment "$APP" -n default --ignore-not-found

echo "=== 3/3 Removing the monitoring stack ==="
if kubectl get pod python-shell -n default >/dev/null 2>&1; then
  echo "  python-shell found -> clean undeploy_monitoring"
  kubectl exec python-shell -n default -- python3 -c "from swchmonclient import undeploy_monitoring; import sys; sys.exit(undeploy_monitoring(namespace='default'))" || true
else
  echo "  python-shell not found -> deleting monitoring resources by name"
  kubectl delete deployment emsserver-ems-server -n default --ignore-not-found
  kubectl delete service emsserver-ems-server -n default --ignore-not-found
  kubectl delete daemonset netdata-child ems-client-daemonset -n default --ignore-not-found
  kubectl delete serviceaccount netdata ems-server-service-account -n default --ignore-not-found
  kubectl delete configmap emsconfig tosca-model-configmap tosca-script-config \
      netdata-conf-child netdata-child-sd-config-map ems-client-configmap monitoring-configmap \
      -n default --ignore-not-found
  kubectl delete role ems-server-role -n default --ignore-not-found
  kubectl delete rolebinding ems-server-role-binding -n default --ignore-not-found
  kubectl delete clusterrole netdata ems-server-cluster-role --ignore-not-found
  kubectl delete clusterrolebinding netdata ems-server-cluster-role-binding --ignore-not-found
fi

echo ""
echo "Waiting a few seconds for pods to terminate ..."
sleep 6
echo "=== default namespace (expect empty, or just python-shell if kept) ==="
kubectl get pods -n default
echo "=== namespaces (swarm-system should be gone) ==="
kubectl get ns
echo ""
echo "Cluster cleared. Redeploy with:  bash deploy-sa.sh"
