# monitoring_input.py
"""
Monitoring lib input for the Optimiser.

Wraps the Swarmchestrate monitor client (`swchmonclient`) and returns the
"monitoring data" the Optimiser expects (LSA sequence, step 4).

The monitor client is *stateful*: `subscribe_metric` starts a background STOMP
listener that buffers samples, and `query_metric_values` drains that buffer.
So a single "get" here means: subscribe -> wait a collection window -> query ->
unsubscribe.

Two flows are supported (both are in the architecture diagram):
- "standard": composite/standard metrics            -> {metric: [values]}
- "raw":      per-node EPA raw metrics              -> {metric: {ip: [{timestamp, value}]}}

Broker config comes from the environment (read by swchmonclient itself):
    MON_CLIENT_STOMP_HOST  (default 127.0.0.1)
    MON_CLIENT_STOMP_PORT  (default 61610)
"""

import time
import logging

import yaml

logger = logging.getLogger("MonitoringInput")

# `swchmonclient` is imported inside get_monitoring_data so the pure
# helpers below (metric_names_from_sat, slo_violations_from_sat) stay usable even
# where the monitor client lib is not installed yet.

DEFAULT_METRIC = "cpu_util_instance"


def metric_names_from_sat(tosca_path: str) -> list:
    """
    Extract the metric names declared in a SAT's `capabilities.metrics`
    (raw + composite). Falls back to [DEFAULT_METRIC] if none are found or the
    file cannot be read.

    The SA already knows its SAT path, so metric names need not be hardcoded.
    """
    try:
        with open(tosca_path, "r") as f:
            sat = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Could not read SAT '{tosca_path}': {e}; using default metric")
        return [DEFAULT_METRIC]

    names = []
    node_templates = (
        sat.get("service_template", {}).get("node_templates", {})
    )
    for node in node_templates.values():
        metrics = (
            node.get("capabilities", {})
            .get("metrics", {})
            .get("properties", {})
        )
        for group in ("raw", "composite"):
            for entry in metrics.get(group, []) or []:
                name = entry.get("name")
                if name:
                    names.append(name)

    return names or [DEFAULT_METRIC]


def get_monitoring_data(
    metrics: list,
    mode: str = "standard",
    collect_seconds: int = 30,
    nodes="all",
    raw_window_seconds: int = None,
    poll_interval_seconds: int = 5,
) -> dict:
    """
    Collect monitoring data for `metrics` from the monitor client.

    Polls (and logs) every `poll_interval_seconds` during the collection window
    so EVERY received value is visible in the logs, then returns all of them
    accumulated — not just a final snapshot.

    Args:
        metrics: metric names to collect (see `metric_names_from_sat`).
        mode: "standard" (composite/standard) or "raw" (per-node EPA).
        collect_seconds: total collection window.
        nodes: raw-mode node selector ("all", "local", or list of IPs).
        raw_window_seconds: raw-mode lookback window per poll (defaults to collect_seconds).
        poll_interval_seconds: how often to query + log during the window.

    Returns a stable envelope so the Optimiser contract never depends on lib
    internals:
        {"source": "monitoring", "mode": mode, "metrics": {...}}
    """
    if mode not in ("standard", "raw"):
        raise ValueError(f"Unsupported mode '{mode}' (expected 'standard' or 'raw')")

    if not metrics:
        metrics = [DEFAULT_METRIC]

    from swchmonclient import (
        subscribe_metric,
        query_metric_values,
        subscribe_metric_raw,
        query_metric_values_raw,
        unsubscribe_metric,
    )

    polls = max(1, collect_seconds // poll_interval_seconds)

    if mode == "standard":
        collected = {metric: [] for metric in metrics}
        try:
            for metric in metrics:
                logger.info(f"Subscribing to standard metric '{metric}'")
                subscribe_metric(metric)

            logger.info(
                f"Collecting for {collect_seconds}s, polling every "
                f"{poll_interval_seconds}s ({polls} polls)..."
            )
            for i in range(1, polls + 1):
                time.sleep(poll_interval_seconds)
                for metric in metrics:
                    batch = query_metric_values(metric)
                    if batch:
                        collected[metric].extend(batch)
                    logger.info(f"[poll {i}/{polls}] '{metric}': {batch}")

            for metric in metrics:
                logger.info(
                    f"Metric '{metric}': {len(collected[metric])} value(s) total"
                )
        finally:
            for metric in metrics:
                try:
                    unsubscribe_metric(metric)
                except Exception as e:
                    logger.warning(f"Unsubscribe failed for '{metric}': {e}")

    else:  # raw
        window = raw_window_seconds if raw_window_seconds is not None else collect_seconds
        collected = {metric: {} for metric in metrics}
        try:
            for metric in metrics:
                logger.info(f"Subscribing to raw metric '{metric}' on nodes={nodes}")
                subscribe_metric_raw(metric, nodes)

            logger.info(
                f"Collecting for {collect_seconds}s, polling every "
                f"{poll_interval_seconds}s ({polls} polls)..."
            )
            for i in range(1, polls + 1):
                time.sleep(poll_interval_seconds)
                for metric in metrics:
                    # query consumes the buffer, so each poll returns only new samples
                    batch = query_metric_values_raw(metric, window)
                    fresh = {}
                    for ip, samples in batch.items():
                        collected[metric].setdefault(ip, [])
                        if samples:
                            collected[metric][ip].extend(samples)
                            fresh[ip] = samples
                    logger.info(f"[poll {i}/{polls}] '{metric}': {fresh if fresh else 'no new samples'}")

            for metric in metrics:
                total = sum(len(s) for s in collected[metric].values())
                logger.info(
                    f"Metric '{metric}': {total} sample(s) from {len(collected[metric])} node(s)"
                )
        finally:
            for metric in metrics:
                try:
                    unsubscribe_metric(metric)
                except Exception as e:
                    logger.warning(f"Unsubscribe failed for '{metric}': {e}")

    return {"source": "monitoring", "mode": mode, "metrics": collected}


_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def slo_violations_from_sat(monitoring_data: dict, tosca_path: str) -> list:
    """
    Evaluate the SAT `slo-constraints` against already-collected standard
    monitoring data (the diagram's second monitor-client output).

    Compares the mean of the collected values for the constraint's metric to its
    threshold using the declared operator. Returns a list of violation records:
        [{"name", "metric", "operator", "threshold", "observed", "violated"}]

    Minimal by design: derives from data we already have; adds no new source.
    Only meaningful for mode="standard" (list-of-values per metric).
    """
    try:
        with open(tosca_path, "r") as f:
            sat = yaml.safe_load(f)
    except Exception as e:
        logger.warning(f"Could not read SAT '{tosca_path}': {e}; no SLO check")
        return []

    metrics_values = monitoring_data.get("metrics", {})
    results = []

    node_templates = sat.get("service_template", {}).get("node_templates", {})
    for node in node_templates.values():
        slo = (
            node.get("capabilities", {})
            .get("slo-constraints", {})
            .get("properties")
        )
        if not slo:
            continue

        # A node may declare a single constraint (dict) or several (list).
        constraints = slo if isinstance(slo, list) else [slo]
        for c in constraints:
            metric = c.get("metric")
            operator = c.get("operator")
            threshold = c.get("threshold")
            values = metrics_values.get(metric)

            if not values or operator not in _OPERATORS or threshold is None:
                continue

            observed = sum(values) / len(values)
            results.append({
                "name": c.get("name"),
                "metric": metric,
                "operator": operator,
                "threshold": threshold,
                "observed": observed,
                "violated": _OPERATORS[operator](observed, threshold),
            })

    return results
