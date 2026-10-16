"""4-step pipeline anatomy demo - runs INSIDE the Swarm Agent leader pod,
using the very SAT the SA translates and deploys (/tosca/tosca.yaml).

Presentation tool only: the SA itself monitors via its built-in MonitoringLoop.
DEBUG level is enabled here on purpose so metric values are visible live;
prints are flushed so stdout/stderr ordering stays correct in piped output.
"""
import logging, json
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logging.getLogger("stomp.py").setLevel(logging.INFO)
import monitoring_input as m

SAT = "/tosca/tosca.yaml"   # the SA own mounted SAT - single source of truth

print("========== STEP 1: SA own SAT -> Sardou get_monitoring() ==========", flush=True)
details = m.get_monitoring_details(SAT)
print(json.dumps(details, indent=2, default=str), flush=True)
print("========== STEP 2: List of metrics from SAT ==========", flush=True)
names = m.metric_names_from_details(details)
print("metrics to subscribe:", names, flush=True)
print("========== STEP 3: subscribe once + one snapshot poll after 60s ==========", flush=True)
import time
m.subscribe_metrics(names)
time.sleep(60)
snapshot = m.poll_metrics(names)
envelope = {"source": "monitoring", "mode": "standard", "metrics": snapshot}
print(json.dumps(envelope, indent=2), flush=True)
m.unsubscribe_metrics(names)
print("========== STEP 4: SLO check (SAT constraints via Sardou) ==========", flush=True)
print(json.dumps(m.evaluate_slo(envelope, details), indent=2), flush=True)
