# Phase 2 - real load, simulated temperature

The second of three demo phases:

| Phase | Application | Node load | Node temperature |
| ----- | ----------- | --------- | ---------------- |
| 1 | stress-ng | real | - |
| **2** | **stress-ng** | **real** | **simulated** |
| 3 | InnoRenew | simulated | simulated |

stress-ng generates real CPU load on the cluster. Cloud VMs have no temperature
sensor, so temperature comes from a file instead. The Swarm Agent reads both,
hands them to the Optimiser, and carries out its decision.

Run every command on the control-plane node. Commands are on single lines so
they paste safely.

---

## What should happen

The file makes the **worker** hot (about 85 C) and the **control-plane** cool
(about 45 C). stress-ng starts on the worker, which pushes its load to 100%.

The rule forbids pods on a node at or above 80 C, so the Optimiser moves the pod
off the hot worker onto the cool control-plane. After the move the rule is
satisfied and nothing more happens.

---

## Files

| File | What it is |
| ---- | ---------- |
| `stressng_SAT_phase2.yaml` | stress-ng with a temperature-aware reconfiguration rule |
| `simulated_node_temp.json` | temperature per node, keyed by node IP |

**The rule** is derived from the InnoRenew SAT v0.11 rule, with two changes that
let it work on a small cluster: the per-node arrays are sized by the nodes that
exist, and scaling up stops once every cool node already holds a pod. Without
the second change the model has no solution as soon as the cluster is full.

**The temperature file** names each node by its IP address. The monitoring
client matches a profile to the node with the same IP, which is what makes the
worker the hot one. On a different cluster, change the two IPs to that cluster's
node addresses (`kubectl get nodes -o wide`, INTERNAL-IP column).

---

## Part 1 - Node labels (one-time)

The application's pod needs a node labelled `ms_id = stressng`, and a pod moved
by the Optimiser needs its target node labelled with the node's own name.

```bash
kubectl label node sajid-swarm-agent-worker-node-1 labels.swarmchestrate.eu/ms_id=stressng --overwrite
```

```bash
kubectl label node sajid-swarm-agent-interfaces labels.swarmchestrate.eu/ms_id=sajid-swarm-agent-interfaces --overwrite
```

Check:

```bash
kubectl get nodes -o custom-columns='NODE:.metadata.name,MS_ID:.metadata.labels.labels\.swarmchestrate\.eu/ms_id'
```

Expect:

```
NODE                              MS_ID
sajid-swarm-agent-interfaces      sajid-swarm-agent-interfaces
sajid-swarm-agent-worker-node-1   stressng
```

---

## Part 2 - Clear the cluster

```bash
cd ~/swarm-agent && git pull
```

```bash
cd ~/swarm-agent/scripts && bash clear-cluster.sh
```

---

## Part 3 - Deploy

`SIM_METRICS` points `deploy-sa.sh` at the temperature file. It is placed into
the agent as a ConfigMap and mounted at `/simdata/metrics.json`.

```bash
cd ~/swarm-agent/scripts && SIM_METRICS=../KB/phase2/simulated_node_temp.json bash deploy-sa.sh stressng ../KB/phase2/stressng_SAT_phase2.yaml
```

Expect, among the output:

```
=== Simulated metrics from ../KB/phase2/simulated_node_temp.json ===
configmap/swarm-agent-simdata created
daemon set "swarm-agent" successfully rolled out
```

---

## Part 4 - Watch

```bash
LEADER=$(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=$(hostname) | grep swarm-agent | sed 's|pod/||')
```

```bash
kubectl logs -f -n swarm-system $LEADER | grep --line-buffered -E "replay file|per-node|inputs ready|Optimiser|poll done"
```

**At startup**, the agent says where each per-node input comes from:

```
[MonitoringLoop] replay file /simdata/metrics.json defines ['node_temp']
[MonitoringLoop] per-node 'node_load': derived from live 'cpu_idle_instance'
[MonitoringLoop] per-node 'node_temp': replayed from /simdata/metrics.json
```

That is the hybrid: load live, temperature from the file.

**After about three minutes**, once live load has collected enough samples:

```
inputs ready: node_load=[45.10, 100.00], node_temp=[45.50, 85.20], threshold_...
decided: create_pod({'msid': 'stressng-v1', 'nodeid': 'sajid-swarm-agent-interfaces'})
decided: delete_pod({'msid': 'stressng-v1', 'podid': 'stressng-v1-...'})
executed: create_pod(...) -> ok
executed: delete_pod(...) -> ok
```

Node order is alphabetical: the first value is the control-plane, the second is
the worker. The new pod is started before the old one is removed, so the
application is never without a pod.

---

## Part 5 - Check

```bash
kubectl get pods -n default -o wide
```

Expect a single pod named `stressng-v1-pinned-sajid-swarm-agent-interfaces-...`
on the control-plane. The original pod on the worker is gone.

The next cycles log `no change`: the pod is now on the only cool node, so the
rule is satisfied.

---

## Part 6 - Change the temperature

Edit `simulated_node_temp.json`, for example swap the two sets of values so the
control-plane becomes the hot one, then deploy again with the same command as
Part 3. The file is read when the agent starts.

---

## Part 7 - Back to Phase 1

Deploy without `SIM_METRICS`. The temperature ConfigMap is removed and the
Phase 1 SAT is used.

```bash
cd ~/swarm-agent/scripts && bash clear-cluster.sh && bash deploy-sa.sh
```

---

## Known limits

| Situation | What happens |
| --------- | ------------ |
| Every node at or above 80 C | The rule has no solution: no node may hold a pod, yet at least one must run. The agent logs `no solution` and changes nothing. |
| Load stays at 100% after the move | stress-ng saturates whichever node it runs on, so moving it does not lower load. The rule still settles, because no cool node is left for another pod. |
| `node_load` never arrives | Live load needs `cpu_idle_instance` from the monitoring stack. Check `poll done` shows 8 values with nothing missing. |
| `not executed: node ... carries ms_id=...` | The target node's label is not its own name. Repeat Part 1. |
