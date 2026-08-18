# Demo: k3s-client integration & simulated optimiser actions

A step-by-step walkthrough to run in front of colleagues. Everything runs on the
control-plane node, from `~/swarm-agent/scripts`. Total time: about 15 minutes.

---

## Part 0 — Start from a clean cluster (2 min)

```bash
cd ~/swarm-agent/scripts
bash clear-cluster.sh
kubectl get pods -n default
```

**Expect:** everything removed.

Say: *"The cluster is empty — no application, no monitoring, no Swarm Agent.
Only Kubernetes itself is running."*

---

## Part 1 — One command deploys everything (3 min)

```bash
bash deploy-sa.sh
```

This installs **only the Swarm Agent**. Everything after that, the agent does itself.

```bash
kubectl get pods -n default
```

**Expect:** within ~1 minute the monitoring stack (EMS server, netdata, ems-clients)
and the application (stressng) appear — deployed by the agent, not by us.

Say: *"I deployed only the Swarm Agent. It read the SAT file and then deployed the
monitoring system and the application on its own."*

---

## Part 2 — Which library did what (2 min)

```bash
bash sa-status.sh
```

Point at the "Startup" section:

| Log line | Which library did the work |
| --- | --- |
| `Converting Tosca into k3s manifests` | k3s-client (`get_kubernetes_manifest`) |
| `[MonitoringDeploy] monitoring stack deployed successfully` | monitoring client (`deploy_monitoring`) |
| `[AppDeploy] applied ... via k3s-client lib` | **k3s-client (`apply_manifest`)** |
| `subscribed to 8 metric(s); polling every 60s` | monitoring client + Sardou (metric names from the SAT) |
| `Cluster status: 5 microservice(s), 6 pod(s)` | **k3s-client (`get_pod_node_mapping`)** |

Say: *"Every interaction with Kubernetes goes through the k3s-client library.
The monitoring client handles metrics. The Swarm Agent coordinates both."*

Note: metrics need ~3 minutes to warm up after a fresh deploy. Early polls showing
`missing: [...]` are normal — use that time for the Part 3 explanation.

---

## Part 3 — Simulated optimiser: issue actions by hand (5 min)

This is what the project asked for: exercise the k3s-client action methods
**without** the optimiser, so we know the execution path works on its own.

Set the leader pod name first (needed by every command below):

```bash
LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$(hostname) | grep swarm-agent | sed "s|pod/||")
echo $LEADER
```

### 3a. Scale up (1 → 2 copies)

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().scale_to(msid='stressng-v1', count=2))"

kubectl get pods -n default | grep stressng
```

**Expect:** `deployment/stressng-v1 scaled`, then two stressng pods.

### 3b. The closed loop — the agent notices by itself

Wait up to 60 seconds (one monitoring cycle), then:

```bash
kubectl logs -n swarm-system $LEADER | grep "Cluster status" | tail -2
```

**Expect:** the pod count rises from 6 to 7 with nobody telling the agent.

Say: *"Nothing told the Swarm Agent about that change. It reads the cluster state
every cycle, so the optimiser will always see the current mapping."*

### 3c. Scale back down

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().scale_to(msid='stressng-v1', count=1))"
```

### 3d. Remove one specific pod

```bash
PODID=$(kubectl get pods -n default -o name | grep "stressng-v1-" | head -1 | sed "s|pod/||")
echo "removing $PODID"

kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().delete_pod(msid='stressng-v1', podid='$PODID'))"
```

**Expect:** the deployment count goes down by one (with one replica that means zero
— the library reduces the count by one, it does not wipe the application).

Restore it:

```bash
kubectl scale deployment stressng-v1 -n default --replicas=1
```

---

## Part 4 — Issues found during testing (3 min)

Two real findings, already reported to the library author.

### Finding 1: preview mode (`dry_run`) fails on three methods

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
m = ApplicationManager()
pod = next(iter(m.get_pod_node_mapping().get('stressng', {})), None)
try:
    m.migrate_pod(msid='stressng-v1', podid=pod, nodeid='sajid-swarm-agent-worker-node-1', dry_run=True)
except Exception as e:
    print('DRY-RUN FAILED:', e)" 2>/dev/null
```

**Expect:** `DRY-RUN FAILED: 'NoneType' object has no attribute 'items'`

Then show the same call **without** dry-run works (Part 3 already proved that for
`scale_to` and `delete_pod`).

Say: *"The real calls all work — only the preview mode is affected. It is the same
pattern that was fixed in one place in version 0.3.1; two more call sites still
have it."*

### Finding 2: pinning a pod to a node needs an undocumented node label

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().create_pod(msid='stressng-v1', nodeid='sajid-swarm-agent-worker-node-1')['ok'])"

sleep 15
kubectl get pods -n default | grep pinned
```

**Expect:** the pod stays `Pending`. Why:

```bash
kubectl describe $(kubectl get pods -n default -o name | grep pinned | head -1) -n default | sed -n '/Events/,$p'
```

**Expect:** `FailedScheduling ... didn't match Pod's node affinity/selector` — the
pod requires the label `labels.swarmchestrate.eu/ms_id=<node name>`, which our nodes
do not have.

Prove it works once the label exists:

```bash
kubectl label node sajid-swarm-agent-worker-node-1 labels.swarmchestrate.eu/ms_id=sajid-swarm-agent-worker-node-1 --overwrite
sleep 20
kubectl get pods -n default -o wide | grep pinned
```

**Expect:** now `Running`, on the worker node.

---

## Part 5 — Clean up (1 min)

```bash
kubectl label node sajid-swarm-agent-worker-node-1 labels.swarmchestrate.eu/ms_id-
bash clear-cluster.sh
bash deploy-sa.sh
```

Leaves the cluster fresh and healthy.

---

## One-line summary for the meeting

> The Swarm Agent deploys the monitoring system and the application from a single
> SAT file, then keeps two live inputs for the optimiser: the metric values and the
> pod-to-node mapping. All Kubernetes operations go through the k3s-client library.
> The action methods (scale, create, delete, migrate) were exercised by hand, without
> the optimiser, and they work — two issues were found and reported: preview mode
> fails on three methods, and node pinning requires a node label that is not
> documented.
