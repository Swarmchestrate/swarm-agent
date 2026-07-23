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
| `SA_MON_USE_KB` | `false` | `deploy_monitoring` resolves the SAT from the local ConfigMap (`false`) or the knowledgebase (`true`). |
| `SA_LOG_LEVEL` | `INFO` | `DEBUG` also logs each metric value per poll. |

To use a different SAT, pass its path to `deploy-sa.sh` (it is loaded into the
SA's ConfigMap and used by both the SA and the monitoring stack).

## Notes

- Only the **leader** deploys the stack and runs the monitoring loop; workers stay
  idle for monitoring.
- The monitoring-stack deploy is best-effort: if it fails, the SA keeps running
  and the monitoring loop retries once the broker is up.
- On some clusters the EMS server can restart a few times on first boot before it
  settles (a slow-startup vs. health-probe race). If it never becomes `Ready`,
  check the EMS server's health-probe settings.

## Future work: cluster-status input (k3s-client library)

The Optimiser consumes three inputs: AI predictions, monitoring data (this
component), and **cluster status** (the current pod-to-node mapping). Cluster
status will be provided by the **k3s-client library** (built by another team, in
progress). `src/cluster_status.py` is a local placeholder until then. When the
library is available, wire it into `get_cluster_status()` in
`src/optimizer_interface.py`; `collect_inputs()` already treats it as one of the
three Optimiser inputs, so no other change is required.
