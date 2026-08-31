# Demo: k3s-client integration & simulated optimiser actions


## Part 0 — Start from a clean cluster (2 min)

```bash
cd ~/swarm-agent/scripts
bash clear-cluster.sh
kubectl get pods -n default
```

**Expect:** everything removed.

The cluster is empty — no application, no monitoring, no Swarm Agent.
Only Kubernetes itself is running.



## Part 1 — One command deploys everything (3 min)

```bash
bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

This installs **only the Swarm Agent**. Everything after that, the agent does itself.

```bash
kubectl get pods -n default
```

**Expect:** within ~1 minute the monitoring stack (EMS server, netdata, ems-clients)
and the application (stressng) appear — deployed by the agent, not by us.



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
| `reconfiguration '...': rule N char(s), 2 constant(s)` | **Sardou (`get_reconfiguration`)** |
| `rule '...' needs 3 input(s): ...` | **swchoptimiser** (rule parameters) |
| `Cluster status: 1 microservice(s), 1 pod(s)` | **k3s-client (`get_pod_node_mapping`)** |

Every interaction with Kubernetes goes through the k3s-client library.
The monitoring client handles metrics. The Swarm Agent coordinates both.

Note: metrics need ~3 minutes to warm up after a fresh deploy. Early polls showing
`missing: [...]` are normal — use that time for the Part 3 explanation.



## Part 3 — The inputs the Optimiser will receive (4 min)

Everything the Optimiser needs comes from the same SAT. `sa-status.sh` shows it
in one place:

```bash
bash sa-status.sh
```

Look at the section titled **"Optimiser inputs read from the SAT"**:

```
[MonitoringLoop] application microservice(s) from SAT: ['stressng']
[MonitoringLoop] reconfiguration 'stressng_reconfiguration': rule 1392 char(s),
  2 constant(s) ['threshold_max_node_load', 'threshold_min_node_load']; targets ['stressng']
[MonitoringLoop] rule 'stressng_reconfiguration' needs 3 input(s):
  cpu_util_prct=metric, threshold_max_node_load=constant, threshold_min_node_load=constant
```

Three separate things happen there.

### 3a. The reconfiguration rule and its constants come out of the SAT

The SAT carries a `swch:Reconfiguration` policy holding the rule and the
constants it refers to. The agent extracts both with the Sardou library
(`get_reconfiguration`), once at startup. The log prints the rule's length
rather than its text, so the log stays readable.

If a SAT declares no such policy the agent says
`SAT declares no reconfiguration policy` and carries on — nothing breaks.

### 3b. The agent asks the Optimiser what its rule needs

The rule text is handed to the Optimiser library, which reports the variables
the rule refers to. The agent then resolves each one to its source:

| Variable | Comes from |
| --- | --- |
| `cpu_util_prct` | a metric we already subscribe to |
| `threshold_max_node_load` | a constant declared in the SAT |
| `threshold_min_node_load` | a constant declared in the SAT |

Anything that nothing can fill is logged as a warning, because the Optimiser
cannot start a calculation while one of its variables has no value.

### 3c. Only application microservices reach the Optimiser

```bash
LEADER_NODE=$(kubectl get nodes -o name | sed "s|node/||" | grep -x "$(hostname)" || kubectl get nodes -o name | sed "s|node/||" | head -1)
LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$LEADER_NODE | grep swarm-agent | sed "s|pod/||")

kubectl exec -n swarm-system $LEADER -- python3 -c "
from monitoring_input import get_monitoring_details, microservice_names_from_details
from k3s_client_input import get_cluster_status
import json
ms = microservice_names_from_details(get_monitoring_details('/tosca/tosca.yaml'))
print('all pods:'); print(json.dumps(get_cluster_status(), indent=2))
print('what the Optimiser gets:'); print(json.dumps(get_cluster_status(microservices=ms), indent=2))"
```

**Expect:** the first mapping lists the monitoring stack's own pods as well
(`ems-client`, `emsserver`, `netdata`); the second contains only `stressng`.

The agent's log reports the same thing every cycle:

```
Cluster status: 1 microservice(s), 1 pod(s); 4 system entries filtered out
```

The filter is driven by the SAT, not a hard-coded list of names: the agent keeps
the microservices the SAT declares, so a different application needs no code
change.

---

## Part 4 — Simulated optimiser: issue actions by hand (5 min)

This is what the project asked for: exercise the k3s-client action methods
**without** the optimiser, so we know the execution path works on its own.

Set the leader pod name first (skip it if you already did so in Part 3):

```bash
LEADER_NODE=$(kubectl get nodes -o name | sed "s|node/||" | grep -x "$(hostname)" || kubectl get nodes -o name | sed "s|node/||" | head -1)
LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$LEADER_NODE | grep swarm-agent | sed "s|pod/||")
echo $LEADER
```

### 4a. Scale up (1 → 2 copies)

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().scale_to(msid='stressng-v1', count=2))"

kubectl get pods -n default | grep stressng
```

**Expect:** `deployment/stressng-v1 scaled`, then two stressng pods.

### 4b. The closed loop — the agent notices by itself

Wait up to 60 seconds (one monitoring cycle), then:

```bash
kubectl logs -n swarm-system $LEADER | grep "Cluster status" | tail -2
```

**Expect:** the pod count rises from 6 to 7 with nobody telling the agent.

Nothing told the Swarm Agent about that change. It reads the cluster state
every cycle, so the optimiser will always see the current mapping.

### 4c. Scale back down

```bash
kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().scale_to(msid='stressng-v1', count=1))"
```

### 4d. Remove one specific pod

```bash
PODID=$(kubectl get pods -n default -o name | grep "stressng-v1-" | head -1 | sed "s|pod/||")
echo "removing $PODID"

kubectl exec -n swarm-system $LEADER -- python3 -c "
from k3s_client.api.applications import ApplicationManager
print(ApplicationManager().delete_pod(msid='stressng-v1', podid='$PODID'))"
```

the deployment count goes down by one (with one replica that means zero
— the library reduces the count by one, it does not wipe the application).

Restore it:

```bash
kubectl scale deployment stressng-v1 -n default --replicas=1
```

---

## Part 5 — Issues found during testing (3 min)

Two real findings, already reported to the library author.

### Finding 1: preview mode (`dry_run`) failed on three methods — now fixed

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

**Expect on k3s-client 0.3.1 and earlier:** `DRY-RUN FAILED: 'NoneType' object
has no attribute 'items'`. On **0.3.2** the same call succeeds — the library team
fixed it after this was reported.

The whole set can be re-checked at any time with:

```bash
bash test-k3s-client.sh
```

**Expect:** `9/9 dry-run calls passed`.

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

## Part 6 — Clean up (1 min)

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
> the optimiser, and they work. The SAT also carries the reconfiguration rule and its
> constants, and the agent asks the Optimiser which variables that rule needs and
> checks it can fill every one of them. Issues found and reported along the way: the
> preview mode crashed on three methods (fixed in 0.3.2), and node pinning requires a
> node label that is not documented.
