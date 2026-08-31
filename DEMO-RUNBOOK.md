# Live demo runbook

A 12-minute demo of the Swarm Agent running on its own: one command starts
everything, and from then on the agent collects metrics, reads the cluster,
and asks the Optimiser what to do - every cycle, with nobody typing.

`DEMO-k3s-client.md` is the reference guide with every command. This file is
the script for standing in front of people.

**What the audience should walk away with:** the Swarm Agent is autonomous, and
the SAT is the thing that steers it. Change the SAT, the behaviour changes. No
code change, no redeploy by hand.

---

## Terminal layout

Three terminals, all SSH'd to the control-plane node:

```bash
ssh -i ~/.ssh/sztaki_ssh_key.pem ubuntu@193.225.250.53
```

| Terminal | Name it | What it shows |
|---|---|---|
| **1** | The story | The leader's log, filtered. This is the terminal people watch. |
| **2** | The cluster | `kubectl get pods`, refreshing. Proof the log matches reality. |
| **3** | The driver | Where you type. Should be quiet most of the time. |

Make Terminal 1 the biggest one. It carries the whole demo.

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

## Before the audience arrives (10 minutes)

Do this early. The first start takes a few minutes to produce metric values,
and you do not want people watching a blank screen.

```bash
cd /home/ubuntu/swarm-agent/scripts
bash clear-cluster.sh                                        # ~1 min
bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml   # ~2 min
```

Then wait until Terminal 1 shows a full cycle with a decision in it:

```
[Optimiser] rule 'stressng_reconfiguration': no change needed (cpu_util_prct=57.78, solved in 548 ms)
```

Once you see that line, you are ready. Check the SAT threshold is back at 70:

```bash
grep threshold_max_node_load ../KB/stressng_SAT_reconfiguration.yaml | head -1
#           threshold_max_node_load: "70.0"
```

If it says 50, put it back to 70 - the demo starts from "everything is fine".

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

**What to say:** "That was one command. The agent read the SAT, deployed the
monitoring system itself, turned the SAT into a Kubernetes manifest and
deployed the application, then subscribed to the metrics the SAT asks for. The
60-second poll rate is not hard-coded - it comes from the collection
frequencies written in the SAT."

**Point at Terminal 2:** the application pod and the monitoring stack pods are
there. Nobody deployed them by hand.

---

## Part 2 - The loop runs by itself (3 min)

Now just wait. A new cycle appears every 60 seconds. Let one land while people
are watching:

```
K3sClientInput - Cluster status: 1 microservice(s), 1 pod(s); 4 system entries filtered out
[MonitoringLoop] rule 'stressng_reconfiguration' inputs ready: cpu_util_prct=57.78, threshold_max_node_load=70.00, threshold_min_node_load=40.00
[Optimiser] rule 'stressng_reconfiguration': no change needed (cpu_util_prct=57.78, solved in 548 ms)
[MonitoringLoop] poll done: 8 value(s); missing: none; SLO violated: none
```

**What to say, line by line:**

1. **Cluster status** - the agent asks the k3s-client library which pod is on
   which node. The "4 system entries filtered out" is the monitoring stack's own
   pods being dropped, because the SAT says the application is `stressng` and
   nothing else. The Optimiser should only reason about the application.
2. **inputs ready** - the live CPU value from the monitoring system, next to the
   two thresholds. Both thresholds were read out of the SAT, not from our code.
3. **Optimiser** - the rule from the SAT went to the Optimiser library with those
   numbers. It solved in half a second and said nothing needs to change.
4. **poll done** - all 8 metrics arrived, no SLO breach.

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

**What to say:** "Nobody told the agent about that. It reads the real cluster
every cycle, so the Optimiser always gets the current picture."

Put it back:

```bash
kubectl scale deployment stressng-v1 -n default --replicas=1
```

---

## Part 4 - The SAT is the steering wheel (4 min)

This is the part that matters. The CPU is sitting near 60%. The SAT currently
says "act above 70", so the agent keeps saying no change. Lower the threshold
in the SAT and the same cluster, with the same load, produces a decision.

In **Terminal 3**:

```bash
cd /home/ubuntu/swarm-agent

# show the audience the line you are about to change
grep -n threshold_max_node_load KB/stressng_SAT_reconfiguration.yaml | head -1

sed -i 's/threshold_max_node_load: "70.0"/threshold_max_node_load: "50.0"/' \
  KB/stressng_SAT_reconfiguration.yaml

cd scripts && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

Terminal 1 will drop out when the pod restarts. Restart it with the same two
commands from the layout section (the pod name changes).

Redeploying takes about 2 minutes, then another 1-2 minutes before values flow.
Use that gap to explain what is about to happen - or run Part 4 first as a
pre-recorded scroll-back if you want a tight demo.

When the cycle lands:

```
[MonitoringLoop] rule 'stressng_reconfiguration' inputs ready: cpu_util_prct=60.01, threshold_max_node_load=50.00, threshold_min_node_load=40.00
[Optimiser] rule 'stressng_reconfiguration' decided: create_pod({'msid': 'stressng-v1', 'nodeid': 'sajid-swarm-agent-interfaces'}) (cpu_util_prct=60.01) - NOT executed, shadow mode
```

**What to say:** "Same cluster, same load, same code. The only thing that
changed is one number in the SAT. The agent now decides to add a pod of
`stressng-v1` on that node - and it names a real deployment and a real node,
so this is a call the k3s-client can carry out directly."

**Then point at the end of the line:** "It says NOT executed. The agent is
running in shadow mode - it decides and logs, but changes nothing. That is
deliberate while the rule content is still being agreed. Turning it into
action is a one-line switch, and it is the next thing to do."

---

## After the demo - put the SAT back

```bash
cd /home/ubuntu/swarm-agent
sed -i 's/threshold_max_node_load: "50.0"/threshold_max_node_load: "70.0"/' \
  KB/stressng_SAT_reconfiguration.yaml
cd scripts && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

---

## Questions you should expect

**"Is it really automatic, or are you running commands?"**
One command at the start. Everything in Parts 2-4 happens on a timer inside the
agent. The only commands typed during the demo are the ones that change the
cluster or the SAT - to prove the agent reacts to them.

**"Why does it not actually add the pod?"**
Shadow mode, on purpose. The decision is real; carrying it out is switched off
until the rule content is agreed with the team. The translation from the
Optimiser's answer to a k3s-client call is already built and shown in the log.

**"Where does the rule come from?"**
The SAT, in the `swch:Reconfiguration` policy. The Sardou library parses it and
hands back the rule and its constants. The Optimiser solves it. Our code does
not contain the rule or any threshold.

**"Which parts are yours and which are libraries?"**
Four libraries do the work: Sardou parses the SAT, the monitoring client
collects metrics, the k3s-client reads and changes the cluster, and the
Optimiser decides. The Swarm Agent is what wires them together and runs the
loop - including the format conversions between them, because they do not speak
the same language.

**"What if a metric is missing?"**
The cycle logs which rule variable is unfilled and skips the Optimiser for that
rule. It does not guess a value.

---

## If something goes wrong

**Terminal 1 shows nothing** - the pod restarted, so the name changed. Re-run the
two commands from the layout section.

**No metric values, `missing:` lists everything** - the monitoring stack needs a
few more minutes after a fresh deploy. Check with `bash sa-status.sh`.

**Nothing works and you have two minutes** - fall back to a full reset:

```bash
cd /home/ubuntu/swarm-agent/scripts
bash clear-cluster.sh && bash deploy-sa.sh stressng ../KB/stressng_SAT_reconfiguration.yaml
```

Then talk over `DEMO-k3s-client.md` until values arrive.
