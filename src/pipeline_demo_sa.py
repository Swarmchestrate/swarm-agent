"""4-step pipeline anatomy demo - runs INSIDE the Swarm Agent leader pod,
using the very SAT the SA translates and deploys (/tosca/tosca.yaml)."""
import logging, json
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
import monitoring_input as m

SAT = "/tosca/tosca.yaml"   # the SA's own mounted SAT - single source of truth

print("========== STEP 1: SA's own SAT -> Sardou get_monitoring() ==========")
print(json.dumps(m.get_monitoring_details(SAT), indent=2, default=str))
print("========== STEP 2: List of metrics from SAT ==========")
names = m.metric_names_from_sat(SAT)
print("metrics to subscribe:", names)
print("========== STEP 3: subscribe + poll (standard, 90s) ==========")
data = m.get_monitoring_data(names, mode="standard", collect_seconds=90, poll_interval_seconds=5)
print(json.dumps(data, indent=2))
print("========== STEP 4: SLO check (SAT constraints via Sardou) ==========")
print(json.dumps(m.slo_violations_from_sat(data, SAT), indent=2))
