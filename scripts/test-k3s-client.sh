#!/bin/bash
# Exercise the k3s-client library from inside the Swarm Agent leader pod.
#
# Follows the library team's test guide: every action method is called in
# dry-run mode and checked against three criteria - no exception, mode
# "dry-run", executed false, and a non-null result.
#
# Usage:
#   bash test-k3s-client.sh           # dry-runs only - changes nothing
#   bash test-k3s-client.sh --real    # also does a real scale 1 -> 2 -> 1
#
# Run on the control-plane node.

REAL=false
[ "$1" = "--real" ] && REAL=true

# Leader node: hostname when it is also a node name, else the only node.
NODES=$(kubectl get nodes -o name 2>/dev/null | sed "s|node/||")
if echo "$NODES" | grep -qx "$(hostname)"; then
  LEADER_NODE="$(hostname)"
elif [ -n "$NODES" ] && [ "$(echo "$NODES" | wc -l)" -eq 1 ]; then
  LEADER_NODE="$NODES"
else
  LEADER_NODE="$(hostname)"
fi
LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName="$LEADER_NODE" 2>/dev/null | grep swarm-agent | sed "s|pod/||")

if [ -z "$LEADER" ]; then
  echo "No Swarm Agent pod found - deploy with: bash deploy-sa.sh"
  exit 1
fi

echo "=============== k3s-client TEST ==============="
echo "leader pod: $LEADER"
kubectl exec -n swarm-system "$LEADER" -- pip show k3s-client 2>/dev/null | grep -i "^version"
echo ""

kubectl exec -i -n swarm-system "$LEADER" -- python3 - <<'PY' 2>/dev/null
import json, logging, traceback
logging.disable(logging.CRITICAL)   # the library logs its own errors; keep output readable
from k3s_client.api.applications import ApplicationManager

m = ApplicationManager()
MS = "stressng-v1"
mapping = m.get_pod_node_mapping()
POD = next(iter(mapping.get("stressng", {})), None)
here = mapping.get("stressng", {}).get(POD)
NODES = sorted({n for pods in mapping.values() for n in pods.values()})
OTHER = next((n for n in NODES if n != here), NODES[0] if NODES else here)
print("pod under test:", POD)
print("target node   :", OTHER)
print()

results = []

def check(label, fn):
    try:
        r = fn()
    except Exception:
        lines = [l.strip() for l in traceback.format_exc().splitlines()
                 if "k3s_client" in l or l.startswith(("AttributeError", "K3sClientError", "k3s_client.exceptions"))]
        print(f"FAIL  {label}")
        for l in lines[-2:]:
            print("         ", l)
        results.append(False)
        return
    ok = (isinstance(r, dict) and r.get("mode") == "dry-run"
          and r.get("executed") is False and r.get("result") is not None)
    print(f"{'PASS ' if ok else 'CHECK'} {label}")
    if not ok:
        print("         ", json.dumps(r, default=str)[:180])
    results.append(ok)

print("--- dry-run calls (nothing is changed) ---")
check("get_pod_node_mapping()",           lambda: m.get_pod_node_mapping(dry_run=True))
check("create_pod(nodeid=None)",          lambda: m.create_pod(MS, nodeid=None, dry_run=True))
check("create_pod(nodeid=<node>)",        lambda: m.create_pod(MS, nodeid=OTHER, dry_run=True))
check("scale_to(count=2)",                lambda: m.scale_to(MS, 2, dry_run=True))
check("delete_pod(podid=None)",           lambda: m.delete_pod(MS, podid=None, dry_run=True))
check("delete_pod(podid=<pod>)",          lambda: m.delete_pod(MS, podid=POD, dry_run=True))
check("migrate_pod(podid, nodeid=<node>)",lambda: m.migrate_pod(MS, podid=POD, nodeid=OTHER, dry_run=True))
check("apply_manifest(application-manifest.yaml)",  lambda: m.apply_manifest("application-manifest.yaml", dry_run=True))
check("delete_manifest(application-manifest.yaml)", lambda: m.delete_manifest("application-manifest.yaml", dry_run=True))

print()
print(f"==== {sum(results)}/{len(results)} dry-run calls passed ====")
PY

if [ "$REAL" = true ]; then
  echo ""
  echo "--- real calls: scale 1 -> 2 -> 1 (the cluster does change) ---"
  kubectl exec -n swarm-system "$LEADER" -- python3 -c "
from k3s_client.api.applications import ApplicationManager
import json, time
m = ApplicationManager()
print('scale_to(2):', m.scale_to('stressng-v1', 2, dry_run=False)['result'])
time.sleep(12)
print('pods now   :', json.dumps(m.get_pod_node_mapping().get('stressng', {}), indent=2))
print('scale_to(1):', m.scale_to('stressng-v1', 1, dry_run=False)['result'])
" 2>/dev/null
  echo ""
  echo "Within one monitoring cycle (<=60s) the agent should report the change itself:"
  echo "  kubectl logs -n swarm-system $LEADER | grep 'Cluster status' | tail -2"
fi
