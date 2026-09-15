# Deploying the InnoRenew application

Step-by-step test of the Swarm Agent with a second application, to show the
agent is not tied to `stressng`. Run every command on the control-plane node.

## What this tests, and what it does not

**Tests:** the SAT is parsed, its manifest is generated and deployed, its
metrics are subscribed, its SLO constraints are evaluated, and the pod-to-node
mapping is built - all for an application whose name appears nowhere in the
agent's code.

**Does not test:** the Optimiser. The InnoRenew SAT declares no
`swch:Reconfiguration` policy, so there is no rule for the Optimiser to solve.
The agent will log `SAT declares no reconfiguration policy` and skip it. Adding
a rule is a separate question, raised with the application and Optimiser owners.

**Expect some metrics to stay empty.** That is part of what we are measuring,
not a fault to fix during the run. See "What may not work" at the end.

---

## Files

| File | What it is |
| ---- | ---------- |
| `innorenew_SAT.yaml` | The SAT, as its author wrote it, with one change: the image |
| `simulated_metrics.json` | File-backed metric values, for the separate test in Part 6 |

**The one change to the SAT.** The original pins the image by digest, and that
digest is the **arm64** build - correct for the edge devices this application
targets, but it cannot start on an x86-64 cluster. This copy uses the `latest`
tag, which is a multi-architecture index, so Kubernetes pulls the build that
matches the node. Nothing else was changed.

---

## Part 1 - Before you start (one-time)

### 1.1 Registry credentials

The image is in a private Harbor registry, so Kubernetes needs a login. The
secret must be called `regcred` in the `default` namespace, because that name
is what the agent passes to the manifest generator.

The password contains `&`, `!` and `^`, which the shell interprets, so do not
type it into the command. Read it into a variable first:

```bash
read -rs PASS
```

Nothing appears on screen. Paste the password, press Enter. `-s` keeps it off
the screen and out of the shell history.

Then create the secret and clear the variable:

```bash
kubectl create secret docker-registry regcred \
  --docker-server=cloud-193-225-250-99.sztaki.science-cloud.hu \
  --docker-username=gkotak \
  --docker-password="$PASS" \
  -n default

unset PASS
```

Check it exists, and that the registry name went in correctly:

```bash
kubectl get secret regcred -n default
kubectl get secret regcred -n default -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d
```

If an earlier attempt left an incomplete secret, remove it first with
`kubectl delete secret regcred -n default --ignore-not-found` and try again.

### 1.2 Node label

The application's pod carries an affinity requiring a node labelled
`ms_id = audio-class`. Without it the pod stays in `Pending` forever. Put it on
the worker, which is where the application will run:

```bash
kubectl label node sajid-swarm-agent-worker-node-1 \
  labels.swarmchestrate.eu/ms_id=audio-class --overwrite
```

Check both nodes:

```bash
kubectl get nodes -o custom-columns='NODE:.metadata.name,MS_ID:.metadata.labels.labels\.swarmchestrate\.eu/ms_id'
```

Expect:

```
NODE                              MS_ID
sajid-swarm-agent-interfaces      sajid-swarm-agent-interfaces
sajid-swarm-agent-worker-node-1   audio-class
```

The control-plane keeps its own name so it can still be a placement target.

---

## Part 2 - Remove stressng

```bash
cd ~/swarm-agent/scripts
bash clear-cluster.sh stressng-v1
```

The argument matters: the script defaults to `stressng-v1`, and here we are
naming it explicitly because the next deploy uses a different application.

Check the namespace is empty:

```bash
kubectl get pods -n default
```

---

## Part 3 - Deploy InnoRenew

```bash
cd ~/swarm-agent/scripts
bash deploy-sa.sh innorenew ../KB/innorenew/innorenew_SAT.yaml
```

The first argument names the output folder, the second is the SAT. Wait for:

```
daemon set "swarm-agent" successfully rolled out
```

---

## Part 4 - Watch it

```bash
LEADER=$(kubectl get pods -n swarm-system -o name \
  --field-selector spec.nodeName=$(hostname) | grep swarm-agent | sed 's|pod/||')

kubectl logs -f -n swarm-system $LEADER | grep --line-buffered -E \
  "MonitoringDeploy|AppDeploy|poll interval|subscribed|microservice|reconfiguration|Cluster status|poll done"
```

Expected within the first minute:

```
[MonitoringDeploy] deploying monitoring stack from /tosca/tosca.yaml into namespace 'swarm-system'
[MonitoringDeploy] monitoring stack deployed successfully
[AppDeploy] applied ./application-manifest.yaml via k3s-client lib
[MonitoringLoop] application microservice(s) from SAT: ['audio-class']
[MonitoringLoop] SAT declares no reconfiguration policy
[MonitoringLoop] poll interval 60s
[MonitoringLoop] subscribed to 4 metric(s); polling every 60s
```

**Read those two lines carefully.** `['audio-class']` and `4 metric(s)` both
come from the InnoRenew SAT. With stressng the same agent printed `['stressng']`
and `8 metric(s)`. Same image, same code, different application.

---

## Part 5 - Check the result

### 5.1 Is the application running?

```bash
kubectl get pods -n default -o wide
```

Expect one `audio-class-v1-...` pod on the worker node.

If it is not `Running`, that is useful information rather than a failure of the
integration - see "What may not work".

### 5.2 Which metrics actually arrived?

```bash
kubectl logs -n swarm-system $LEADER | grep "poll done" | tail -3
```

The `missing:` list names the metrics that produced no value. Write down which
ones. This is the main measurement of the run.

### 5.3 The pod-to-node mapping

```bash
kubectl logs -n swarm-system $LEADER | grep "Cluster status" | tail -2
```

Expect `1 microservice(s), 1 pod(s)`, with nothing filtered: the monitoring
stack is in `swarm-system`, so only the application appears.

### 5.4 Everything at once

```bash
cd ~/swarm-agent/scripts && bash sa-status.sh
```

Under "Last Optimiser decision" expect:

```
none - this SAT has no reconfiguration policy, so the Optimiser is not used
```

That is correct for this SAT, not an error.

---

## Part 6 - Simulated metrics (separate test)

This does not need the application. It shows that metric values can come from a
file instead of the monitoring system, which is how we will drive metrics that
no cloud VM can produce.

```bash
kubectl cp ../KB/innorenew/simulated_metrics.json \
  swarm-system/$LEADER:/tmp/simulated_metrics.json

kubectl exec -n swarm-system $LEADER -- python3 -c "
import time, logging; logging.disable(logging.CRITICAL)
from swchmonclient.metrics import MetricSubscriptionManager
m = MetricSubscriptionManager()
print('subscribed:', sorted(m.subscribe_metric_raw('cpu_util_instance', 'cluster',
      source_file='/tmp/simulated_metrics.json').keys()))
time.sleep(25)
for node, s in sorted(m.query_metric_values_raw('cpu_util_instance', 300).items()):
    v = [x['value'] for x in s]
    print(' ', node, len(v), 'samples', v[:6])
m.unsubscribe_metric('cpu_util_instance')
"
```

Expect the file's two profiles to appear against the cluster's **real node IPs**,
replaying the values from the file:

```
subscribed: ['192.168.0.205', '192.168.0.90']
  192.168.0.205  6 samples [42.0, 44.5, 41.2, 42.0, 44.5, 41.2]
  192.168.0.90   6 samples [65.0, 65.0, 65.0, 65.0, 65.0, 65.0]
```

The `"cluster"` argument is what maps the file's profiles onto real nodes. Without
it the values arrive under the file's own names and match no node.

---

## Part 7 - Go back to stressng

```bash
cd ~/swarm-agent/scripts
bash clear-cluster.sh audio-class-v1
kubectl label node sajid-swarm-agent-worker-node-1 \
  labels.swarmchestrate.eu/ms_id=stressng --overwrite
bash deploy-sa.sh
```

`deploy-sa.sh` with no arguments uses the stressng reconfiguration SAT.

---

## What may not work, and why

None of these are integration faults. Record what happens.

| Thing | Why it may fail |
| ----- | --------------- |
| `cpu_temp_instance` | Reads `dev.cpu.temperature`. These cloud VMs have **no temperature sensor** - no thermal zones, no hwmon chips. This metric cannot produce a value here. On the Raspberry Pi devices the SAT targets, it would. |
| `mean_cpu_temp` | Computed from the metric above, so it cannot produce a value either. |
| `cpu_util_instance` | Reads `k8s.cgroup.cpu`, which is a different Netdata source from the one stressng uses. Untested on this cluster. |
| `mean_cpu_temp` grouping | Uses `grouping: per_instance`. We measured that `per_host` stops the standard subscriptions delivering; `per_instance` is untested and may behave the same way. |
| The application pod | The SAT mounts `/home/gunjan/classification-conf/configuration.ini` from the host. That file does not exist on these nodes, so Kubernetes creates an empty one and the application may exit on start. The monitoring and mapping parts still work if it does. |
| SLO always violated | The SAT's SLO reads `mean_cpu_temp < 80.0`. The other two entries describe the unwanted condition (util above 60, util below 30), so this one reads as "breached when the temperature is below 80", which looks inverted for a heat limit. Since it is an `or_list`, a single breach breaches the whole SLO. Raised with the SAT's author; not changed here. |

---

## If something goes wrong

**Pod stuck in `ImagePullBackOff`** - the `regcred` secret is missing, wrong, or
in the wrong namespace. Check with `kubectl get secret regcred -n default` and
`kubectl describe pod <pod> -n default | tail -20`.

**Pod stuck in `Pending`** - no node carries `ms_id = audio-class`. Re-run
step 1.2 and check with `kubectl describe pod <pod> -n default | grep -A5 Events`.

**`exec format error`** - the arm64 image was pulled onto an x86-64 node. Check
the SAT uses the `latest` tag, not the digest.

**No metric values at all after five minutes** - check the monitoring stack is
up with `kubectl get pods -n swarm-system`, then `bash sa-status.sh`.
