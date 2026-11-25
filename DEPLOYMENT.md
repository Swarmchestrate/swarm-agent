# Deploying the Swarm Agent

The Swarm Agent (SA) runs on a k3s cluster and drives the whole monitoring flow
from a single SAT (Swarm Application Template): the leader deploys the monitoring
stack, deploys the application, subscribes to the SAT's metrics, and keeps a
fresh snapshot of all metric values ready for the Optimiser.

Everything below is a single bootstrap command; after that the SA runs on its own.

## Prerequisites

- A k3s cluster (one control-plane node + one or more workers), both `Ready`.
- **Outbound internet** on the nodes: the SA downloads the monitoring manifests
  and the TOSCA profiles at startup.
- The SA container image present on every node (built locally and imported into
  k3s, or pulled from a registry the cluster can reach). Default tag:
  `swarm-agent:metrics_collector`.
- The deployer RBAC in `k3s/01-rbac-swarm-agent.yaml` (already included). This is
  what lets the SA deploy the monitoring stack itself.

## Deploy

From `scripts/`:

```bash
bash deploy-sa.sh
```

This one command:
1. generates the cluster manifests (`generate-configMaps.py`),
2. applies them (`kubectl apply`),
3. waits for the SA to roll out.

Optional arguments: `bash deploy-sa.sh <job-id> <sat-path> <leader-hostname>`
(defaults: `stressng`, `../KB/stressng_SAT_monitoring.yaml`, `$(hostname)`).

After it finishes, the SA leader does the rest automatically.

## What happens next (autonomous flow)

On the leader, in order:

1. **Read the SAT** and convert it into Kubernetes manifests.
2. **Deploy the monitoring stack** — `deploy_monitoring()` from the same SAT
   (netdata sensors, the EMS server, and the collectors).
3. **Deploy the application** from the same SAT.
4. **Subscribe** to every metric the SAT declares, by name, on the broker.
5. **Poll** on a fixed rhythm and keep the latest complete snapshot in memory for
   the Optimiser. The poll interval is read from the SAT's `collection_frequency`
   values (slowest one, with a 60-second floor), so it adapts to any SAT with no
   code change.

Watch it:

```bash
kubectl logs -n swarm-system -f \
  $(kubectl get pods -n swarm-system -o name --field-selector spec.nodeName=<LEADER> | grep swarm-agent) \
  | grep --line-buffered -E "MonitoringDeploy|Application initialised|poll interval|subscribed to|poll done"
```

A healthy run ends with repeated `poll done: N value(s); missing: none`.

## Teardown

From `scripts/`:

```bash
bash clear-cluster.sh
```

Removes the SA, the application, and the monitoring stack — back to a clean
cluster. Leaves the k3s system components untouched.

## Configuration (environment variables on the daemonset)

| Variable | Default | Purpose |
| --- | --- | --- |
| `SA_DEPLOY_MONITORING` | `true` | Set `false` to skip the automatic monitoring-stack deploy (e.g. if the stack is managed separately). |
| `SA_USE_EMS` | `true` | Set `false` to run without EMS: no monitoring-stack deploy, no live metrics, no SLO checks. Metrics then come only from the simulated file given to `deploy-sa.sh` as `SIM_METRICS`, which can supply per-node (array) rule inputs only. |
| `SA_MON_USE_KB` | `false` | `deploy_monitoring` resolves the SAT from the local ConfigMap (`false`) or the knowledgebase (`true`). |
| `SA_LOG_LEVEL` | `INFO` | `DEBUG` also logs each metric value per poll. |
| `SA_SIM_METRICS_FILE` | `/simdata/metrics.json` | Replay file mounted from the `swarm-agent-simdata` ConfigMap; used only when `deploy-sa.sh` was given `SIM_METRICS`. |
| `SA_TEST_SLO_PROBABILITY` | `0` | Test mode. Above 0, each 5 s SLO check fakes an SLO message with this probability, so the SLO path of the decision loop can be tested without EMS. Not in the daemonset file; set it with `kubectl set env` (see below). |

To use a different SAT, pass its path to `deploy-sa.sh` (it is loaded into the
SA's ConfigMap and used by both the SA and the monitoring stack).

## Decision loop test run (Ai-integration branch)

The leader runs a decision loop: every 5 s it checks for an SLO message, and
after 300 s without one it starts a timed round. In each round the Optimiser
gets the rule and its constants from the SAT, the metric values, and the
current pod-to-node mapping from the cluster, and the SA carries out the
actions it returns. After an action the SA waits 30 s before the next wait
starts.

### 1. Build the image and load it into k3s on every node

```bash
docker build -t swarm-agent:ai-integration .
docker save swarm-agent:ai-integration -o swarm-agent-ai-integration.tar
sudo k3s ctr -n k8s.io images import swarm-agent-ai-integration.tar
```

Run the import on every node (copy the `.tar` file to each worker first).
The image contains `swchoptimiser` 0.2.0 and `Sardou` 0.13.1 (`requirements.txt`);
Sardou 0.14.0 rejects `-` in node names such as `audio-class`.

### 2. Deploy

From `scripts/`:

```bash
bash deploy-ai-test.sh
```

This clears the cluster, puts the replay data in place, deploys the SA with the
test SAT `KB/innorenew/innorenew-sat-combined-test.yaml` (InnoRenew rule,
`threshold_max_node_load` 40) and `SA_USE_EMS=false`, then follows the leader's
log. The leader node is found automatically (`LEADER=<node>` overrides it).

| Option | Default | Purpose |
| --- | --- | --- |
| 1st argument | `../KB/innorenew/innorenew-sat-combined-test.yaml` | SAT to deploy |
| 2nd argument | `../KB/innorenew/simulated_nodes_metrics_cluster.json` | Replay file (used only without EMS) |
| `USE_EMS` | `false` | `true` deploys EMS and uses live metrics and SLOs |
| `IMAGE` | `docker.io/library/swarm-agent:ai-integration` | SA image |
| `LEADER` | the control-plane node | Node that runs the leader |

For a run with live EMS data: `USE_EMS=true bash deploy-ai-test.sh`.

### 3. What a working run logs

Without EMS (node names shortened):

```
[MonitoringDeploy] SA_USE_EMS is false, so EMS is not deployed; metrics come only from the simulated file
[DecisionLoop] EMS not deployed; SLOs are not checked, only periodic rounds
[MonitoringLoop] replay file /simdata/metrics.json defines ['node_load', 'node_temp']
[DecisionLoop] round started: 300 s passed; the optimiser gets the predicted values
[MonitoringLoop] rule 'audio_class_reconfiguration' inputs ready: node_load=[53.91, 31.21, 39.37], threshold_max_node_load=40.00, threshold_min_node_load=20.00
[DecisionLoop] AI prediction not available yet; the predicted values are the latest actual values
[Optimiser] input 1/3 system:    {"sys_pod_count_max": 5, "sys_node_count_max": 3, "sys_node_count_actual": 3, "sys_mapping_actual": [1, 0, 0, 0, 0]}
[Optimiser] input 2/3 constants: {"threshold_max_node_load": 40.0, "threshold_min_node_load": 20.0}
[Optimiser] input 3/3 metrics:   {"node_load": [53.912, 31.209, 39.367]}
[Optimiser] rule 'audio_class_reconfiguration' decided: create_pod({'msid': 'audio-class-v1', 'nodeid': '<worker-1>'})
[Optimiser] executed: create_pod({'msid': 'audio-class-v1', 'nodeid': '<worker-1>'}) -> ok
[DecisionLoop] cooldown 30 s
```

The next rounds add a pod on the second worker while the average load stays
above 40, then report `no change needed` once it is within 20 to 40. With
`USE_EMS=true` the log shows `SLOs from SAT: [...]` and `subscribed to ...`
instead of the replay lines, and a round can also start with
`round started: SLO '...' fired; the optimiser gets the actual values`.

Where the values come from: `node_load` from the replay file (or EMS), the
thresholds from the SAT, and `sys_mapping_actual` from the cluster. The AI
prediction is still a placeholder that returns the latest actual values.

### 4. Test the SLO path without EMS (optional)

```bash
kubectl -n swarm-system set env daemonset/swarm-agent SA_TEST_SLO_PROBABILITY=0.02
```

The SA pods restart. Look for `simulated SLO violation (test mode)` followed by
`round started: SLO 'simulated' fired`. Set it back to `0` to stop. This tests
how the SA reacts to an SLO message, not EMS itself.

### 5. Stop

```bash
bash clear-cluster.sh audio-class-v1
```

## Notes

- Only the **leader** deploys the stack and runs the monitoring loop; workers stay
  idle for monitoring.
- The monitoring-stack deploy is best-effort: if it fails, the SA keeps running
  and the monitoring loop retries once the broker is up.

## Future work: cluster-status input (k3s-client library)

The Optimiser consumes three inputs: AI predictions, monitoring data (this
component), and **cluster status** (the current pod-to-node mapping). Cluster
status will be provided by the **k3s-client library** (built by another team, in
progress). `src/cluster_status.py` is a local placeholder until then. When the
library is available, wire it into `get_cluster_status()` in
`src/optimizer_interface.py`; `collect_inputs()` already treats it as one of the
three Optimiser inputs, so no other change is required.
