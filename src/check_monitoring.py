# check_monitoring.py
"""
Standalone driver to verify the monitoring-lib integration end-to-end and LOG
every metric value.

Run this INSIDE the cluster / SA pod, where the EMS/STOMP broker is reachable
(MON_CLIENT_STOMP_HOST / MON_CLIENT_STOMP_PORT). It does NOT touch the Optimiser
or k8s — it only exercises monitoring_input.

Usage:
    python3 check_monitoring.py [SAT_PATH] [MODE] [COLLECT_SECONDS]

    SAT_PATH         default: ../KB/stressng_SAT.yaml
    MODE             "standard" (default) or "raw"
    COLLECT_SECONDS  default: 15
"""

import sys
import logging

from utility import setup_logging
from monitoring_input import (
    metric_names_from_sat,
    get_monitoring_data,
    slo_violations_from_sat,
)


def main():
    setup_logging("INFO")
    log = logging.getLogger("CheckMonitoring")

    sat_path = sys.argv[1] if len(sys.argv) > 1 else "../KB/stressng_SAT.yaml"
    mode = sys.argv[2] if len(sys.argv) > 2 else "standard"
    collect_seconds = int(sys.argv[3]) if len(sys.argv) > 3 else 15

    metrics = metric_names_from_sat(sat_path)
    log.info(f"SAT: {sat_path}")
    log.info(f"Metrics from SAT: {metrics}")
    log.info(f"Mode: {mode}, collecting {collect_seconds}s...")

    try:
        data = get_monitoring_data(metrics, mode=mode, collect_seconds=collect_seconds)
    except Exception as e:
        log.error(f"Monitoring collection failed (broker reachable?): {e}")
        return 1

    # Log EVERY value, not just counts.
    log.info("================ MONITORING DATA ================")
    for metric, values in data["metrics"].items():
        if mode == "standard":
            log.info(f"[{metric}] {len(values)} value(s): {values}")
        else:  # raw: dict keyed by node IP
            for ip, samples in values.items():
                log.info(f"[{metric}] node {ip}: {len(samples)} sample(s)")
                for s in samples:
                    log.info(f"    ts={s.get('timestamp')} value={s.get('value')}")
    log.info("=================================================")

    # SLO check is only meaningful for standard mode (list of values).
    if mode == "standard":
        violations = slo_violations_from_sat(data, sat_path)
        log.info(f"SLO checks: {len(violations)} constraint(s) evaluated")
        for v in violations:
            flag = "VIOLATED" if v["violated"] else "ok"
            log.info(
                f"    [{flag}] {v['name']}: {v['metric']} {v['operator']} "
                f"{v['threshold']} (observed mean={v['observed']:.2f})"
            )

    log.info("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
