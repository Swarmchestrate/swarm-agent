# Live demo runbook

A 12-minute demo of the Swarm Agent running on its own: one command starts
everything, and from then on the agent collects metrics, reads the cluster, and
asks the Optimiser what to do - every cycle, with nobody typing.

`DEMO-k3s-client.md` is the reference guide with every command. This file is the
script for presenting the system to an audience.

**What the audience should walk away with:** the Swarm Agent is autonomous, and
the SAT is the thing that steers it. Change the SAT, the behaviour changes. No
code change, no redeploy by hand.

## Before reading further

Fill in three values for the cluster being demonstrated:

| Placeholder       | Meaning                                           | Example                      |
| ----------------- | ------------------------------------------------- | ---------------------------- |
| `<key>`         | SSH private key for the cluster                   | `~/.ssh/cluster_key.pem`   |
| `<user>@<host>` | Login on the control-plane node                   | `ubuntu@192.0.2.10`        |
| `<repo>`        | Where this repository is checked out on that node | `/home/ubuntu/swarm-agent` |

Every log sample below is example output. Node names, pod-name suffixes and
metric values differ on any other cluster - `swarm-node-1` stands for the
control-plane node.

---

## Terminal layout

Three terminals, all logged in to the control-plane node:

```bash
ssh -i <key> <user>@<host>
```

| Terminal    | Name it     | What it shows                                                    |
| ----------- | ----------- | ---------------------------------------------------------------- |
| **1** | The story   | The leader's log, filtered. This is the terminal people watch.   |
| **2** | The cluster | `kubectl get pods`, refreshing. Proof the log matches reality. |
| **3** | The driver  | Where the presenter types. Quiet most of the time.               |

Terminal 1 should be the largest. It carries the whole demo.

**Terminal 1** - start this and leave it running:

```bash
LEADER=$(kubectl get pods -n swarm-system -o name \
  --field-selector spec.nodeName=$(hostname) | grep swarm-agent | sed 's|pod/||')

kubectl logs -f -n swarm-system $LEADER | grep --line-buffered -E \
  "MonitoringDeploy|AppDeploy|poll interval|subscribed|Cluster status|inputs ready|Optimiser|poll done"
```

**Terminal 2**:

```bash
watch -n 5 kubectl get pods -n default
```

---

## Do this early. A first start takes a few minutes to produce metric values, and

-------------------------------------------

```bash
cd <repo>/scripts
bash clear-cluster.sh                                               # ~1 min
bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml  # ~2 min
```

Then wait until Terminal 1 shows a full cycle with a decision in it:

```
[Optimiser] rule 'stressng_reconfiguration': no change needed (cpu_util_prct=57.78, solved in 548 ms)
```

Once that line appears the demo is ready. Check the SAT threshold is at 70:

```bash
grep threshold_max_node_load ../KB/stressng_SAT_reconfiguration.yaml | head -1
#           threshold_max_node_load: "70.0"
```

If it reads 50, set it back to 70 - the demo starts from "everything is fine".

### The first three minutes are always quiet

The rule needs `cpu_util_prct`, and that is a composite metric: the monitoring
system has to collect several raw samples before it can work out a percentage.
Values arrive in waves, and the log shows it happening:

```
poll done: 2 value(s); missing: ['cpu_idle_instance', ..., 'cpu_util_prct', ...]
poll done: 6 value(s); missing: ['cpu_util_prct', 'ram_util_prct']
poll done: 8 value(s); missing: none
```

Until `cpu_util_prct` arrives the agent skips the Optimiser rather than guess a
value, so no `[Optimiser]` line appears at all. This is normal. Do not start
presenting until one does.

### Then decide whether Part 4 is needed

Read that first `[Optimiser]` line and pick one:

- **It says `decided: create_pod`** - the load is already above the threshold.
  Part 4 is not needed. The demo makes its point without any edit.
- **It says `no change needed`** - the load is below the threshold and every
  cycle will keep saying so. Run **Part 4 now, before the audience arrives.**
  It costs about four minutes of redeploying, which is dead air during a demo
  but free beforehand. The agent is then already logging `decided: create_pod`
  when the demo starts, and the system looks alive from the first second.

Either way, the demo begins with the agent visibly working.

---

## Part 1 - One command starts everything (2 min)

Scroll Terminal 1 back to the start and walk through what the agent did on its
own, in order:

```
[MonitoringDeploy] deploying the monitoring stack from the SAT ...
[MonitoringDeploy] monitoring stack deployed
[AppDeploy] Applying manifest via k3s-client apply_manifest
[AppDeploy] Application initialised
[MonitoringLoop] subscribed to 8 metric(s)
[MonitoringLoop] poll interval 60s
```

That was one command. The agent read the SAT, deployed the
monitoring system itself, turned the SAT into a Kubernetes manifest and deployed
the application, then subscribed to the metrics the SAT asks for. The 60-second
poll rate is not hard-coded - it comes from the collection frequencies written in
the SAT.

**Point at Terminal 2:** the application pod and the monitoring stack pods are
there. 

---

## Part 2 - The loop runs by itself (3 min)

Now just wait. A new cycle appears every 60 seconds. Let one land while the
audience is watching:

```
K3sClientInput - Cluster status: 1 microservice(s), 1 pod(s); 4 system entries filtered out
[MonitoringLoop] rule 'stressng_reconfiguration' inputs ready: cpu_util_prct=72.12, threshold_max_node_load=70.00, threshold_min_node_load=40.00
[Optimiser] input 1/3 system:    {"sys_pod_count_max": 5, "sys_node_count_max": 2, "sys_node_count_actual": 2, "sys_mapping_actual": [1, 0, 0, 0, 0]}
[Optimiser] input 2/3 constants: {"threshold_max_node_load": 70.0, "threshold_min_node_load": 40.0}
[Optimiser] input 3/3 metrics:   {"cpu_util_prct": 72.11894640000001}
[Optimiser] rule 'stressng_reconfiguration' decided: create_pod({'msid': 'stressng-v1', 'nodeid': 'swarm-node-1'}) (cpu_util_prct=72.12) - NOT executed, shadow mode
[MonitoringLoop] poll done: 8 value(s); missing: none; SLO violated: none
```

**What to say, line by line:**

1. **Cluster status** - the agent asks the k3s-client library which pod is on
   which node. The "4 system entries filtered out" is the monitoring stack's own
   pods being dropped, because the SAT says the application is `stressng` and
   nothing else. The Optimiser should only reason about the application.
2. **inputs ready** - the live CPU value from the monitoring system, next to the
   two thresholds. Both thresholds were read out of the SAT, not from any code.
3. **input 1/3, 2/3, 3/3** - everything handed to the Optimiser this cycle, in
   the three groups its API takes: the cluster picture, the SAT's constants, and
   the live metrics. Nothing is hidden; this is the whole input.
4. **Optimiser decided** - the rule from the SAT was solved with those numbers.
   Above the threshold it asks for another pod, and it names a real deployment
   and a real node, so this is a call the k3s-client could carry out directly.
   Below the threshold the same line reads `no change needed`.
5. **poll done** - all 8 metrics arrived, no SLO breach.

**If someone asks about `sys_mapping_actual: [1, 0, 0, 0, 0]`** - the Optimiser
only speaks numbers. Five slots: the one running pod plus four spare. Slot 1
holds `1`, meaning node number 1. The zeros are empty slots the Optimiser is free
to fill. Its answer comes back in the same number language and the Swarm Agent
translates it back into names.

---

## Part 3 - It notices cluster changes on its own (2 min)

In **Terminal 3**, add a replica:

```bash
kubectl scale deployment stressng-v1 -n default --replicas=2
```

Watch Terminal 2: a second pod appears. Then wait for the next cycle in
Terminal 1 - within 60 seconds it says:

```
Cluster status: 1 microservice(s), 2 pod(s); 4 system entries filtered out
```

Nobody told the agent about that. It reads the real cluster
every cycle, so the Optimiser always gets the current picture."

Put it back:

```bash
kubectl scale deployment stressng-v1 -n default --replicas=1
```

---

## Part 4 - The SAT is the steering wheel (4 min, optional)

**Check first: is this part needed?** Look at the last few cycles in Terminal 1.
If `cpu_util_prct` is already above 70 and the log says `decided: create_pod`,
the demo has already made this point - the load crossed the threshold on its own,
which is more convincing than any edit. Skip to the closing lines below and save
four minutes.

Run this part only when the CPU is sitting *below* the threshold and every cycle
says `no change needed`. Then lower the threshold in the SAT, and the same
cluster, with the same load, produces a decision.

In **Terminal 3**:

```bash
cd <repo>

# show the audience the line about to change
grep -n threshold_max_node_load KB/stressng_SAT_reconfiguration.yaml | head -1

sed -i 's/threshold_max_node_load: "70.0"/threshold_max_node_load: "50.0"/' \
  KB/stressng_SAT_reconfiguration.yaml

cd scripts && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

Terminal 1 will drop out when the pod restarts. Restart it with the same two
commands from the layout section (the pod name changes).

Redeploying takes about 2 minutes, then another 1-2 minutes before values flow.
Use that gap to explain what is about to happen - or capture this part in advance
and present it as scroll-back for a tighter demo.

When the cycle lands:

```
[MonitoringLoop] rule 'stressng_reconfiguration' inputs ready: cpu_util_prct=60.01, threshold_max_node_load=50.00, threshold_min_node_load=40.00
[Optimiser] rule 'stressng_reconfiguration' decided: create_pod({'msid': 'stressng-v1', 'nodeid': 'swarm-node-1'}) (cpu_util_prct=60.01) - NOT executed, shadow mode
```

**What to say:** "Same cluster, same load, same code. The only thing that changed
is one number in the SAT. The agent now decides to add a pod of `stressng-v1` on
that node - and it names a real deployment and a real node, so this is a call the
k3s-client can carry out directly."

**Then point at the end of the line:** "It says NOT executed. The agent is
running in shadow mode - it decides and logs, but changes nothing. That is
deliberate while the rule content is still being agreed. Executing the decision
is the next step."

---

## After the demo - put the SAT back

Only needed if Part 4 was run.

```bash
cd <repo>
sed -i 's/threshold_max_node_load: "50.0"/threshold_max_node_load: "70.0"/' \
  KB/stressng_SAT_reconfiguration.yaml
cd scripts && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

---

## Questions to expect

**"Is it really automatic, or are commands being run?"**
One command at the start. Everything in Parts 2-4 happens on a timer inside the
agent. The only commands typed during the demo are the ones that change the
cluster or the SAT - to prove the agent reacts to them.

**"Why does it not actually add the pod?"**
Shadow mode, on purpose. The decision is real; carrying it out is switched off
until the rule content is agreed. The translation from the Optimiser's answer to
a k3s-client call is already built and shown in the log.

**"Where does the rule come from?"**
The SAT, in the `swch:Reconfiguration` policy. The Sardou library parses it and
hands back the rule and its constants. The Optimiser solves it. The Swarm Agent's
code contains neither the rule nor any threshold.

**"Which parts are the Swarm Agent and which are libraries?"**
Four libraries do the work: Sardou parses the SAT, the monitoring client collects
metrics, the k3s-client reads and changes the cluster, and the Optimiser decides.
The Swarm Agent wires them together and runs the loop - including the format
conversions between them, because they do not speak the same language.

**"What if a metric is missing?"**
The cycle logs which rule variable is unfilled and skips the Optimiser for that
rule. It does not guess a value.

---

## If something goes wrong

**Terminal 1 shows nothing** - the pod restarted, so its name changed. Re-run the
two commands from the layout section.

**No metric values, `missing:` lists everything** - the monitoring stack needs a
few more minutes after a fresh deploy. Check with `bash sa-status.sh`.

**Nothing works and there are two minutes left** - fall back to a full reset:

```bash
cd <repo>/scripts
bash clear-cluster.sh && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

Then talk through `DEMO-k3s-client.md` until values arrive.
