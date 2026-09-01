# monitoring_input.py
"""
Monitoring lib input for the Optimiser.

Wraps the Swarmchestrate monitor client (`swchmonclient`) and returns the
"monitoring data" the Optimiser expects (LSA sequence, step 4).

The monitor client is *stateful*: `subscribe_metric` starts a background STOMP
listener that buffers samples, and `query_metric_values` drains that buffer.
So a single "get" here means: subscribe -> wait a collection window -> query ->
unsubscribe.

Two flows are supported:
- "standard": composite/standard metrics            -> {metric: [values]}
- "raw":      per-node EPA raw metrics              -> {metric: {ip: [{timestamp, value}]}}

Broker config comes from the environment (read by swchmonclient itself):
    MON_CLIENT_STOMP_HOST  (default 127.0.0.1)
    MON_CLIENT_STOMP_PORT  (default 61610)
"""

import re
import time
import logging

logger = logging.getLogger("MonitoringInput")

# `swchmonclient` and `sardou` are imported lazily inside the functions that use
# them, so this module stays importable where those libs are not installed yet.

DEFAULT_METRIC = "cpu_util_instance"


def get_monitoring_details(tosca_path: str) -> dict:
    """
    Full per-microservice monitoring details (metrics + slo-constraints) from the
    SAT, via the official Sardou TOSCA lib — we do not parse the SAT ourselves.

    Returns e.g. {"<ms>": {"metrics": {"raw": [...], "composite": [...]},
                           "slo-constraints": {...}}}

    Requires the `puccini-tosca` binary (already present in the SA image).
    Retries transient failures: concurrent Sardou runs in one container can race
    on its profile cache (~/.cache/sardou) and hit a truncated file (EOF).
    """
    from sardou import Sardou
    last_err = RuntimeError(f"Sardou failed for '{tosca_path}'")
    for attempt in range(1, 4):
        try:
            sat = Sardou(tosca_path)
            return sat.get_monitoring() or {}
        except Exception as e:
            last_err = e
            if attempt < 3:
                logger.warning(
                    f"Sardou attempt {attempt}/3 failed for '{tosca_path}': {e}; retrying"
                )
                time.sleep(2)
    raise last_err


def get_reconfiguration_details(tosca_path: str) -> dict:
    """
    Reconfiguration policies declared in the SAT, via the Sardou lib's
    get_reconfiguration(). Each policy carries the Optimiser's rule and its
    constants:

        {"<policy>": {"rule": "<minizinc text>",
                      "constants": {"<name>": "<value>"},
                      "targets": ["<microservice>"]}}

    Returns {} when the SAT declares no reconfiguration policy. Same transient
    retry as get_monitoring_details (concurrent Sardou runs can race on the
    profile cache).
    """
    from sardou import Sardou
    last_err = RuntimeError(f"Sardou failed for '{tosca_path}'")
    for attempt in range(1, 4):
        try:
            return Sardou(tosca_path).get_reconfiguration() or {}
        except Exception as e:
            last_err = e
            if attempt < 3:
                logger.warning(
                    f"Sardou reconfiguration attempt {attempt}/3 failed for "
                    f"'{tosca_path}': {e}; retrying"
                )
                time.sleep(2)
    raise last_err


def microservice_names_from_details(details: dict) -> set:
    """
    Application microservice names declared in the SAT (the keys of a
    get_monitoring() result). Used to keep only application microservices in
    the cluster-status mapping - the monitoring stack's own pods are
    infrastructure and are not orchestrated by the Optimiser.
    """
    return set(details.keys())


def metric_names_from_details(details: dict) -> list:
    """Metric names (raw + composite) from an already-fetched get_monitoring() result."""
    names = []
    for entry in details.values():
        metrics = entry.get("metrics") or {}
        for group in ("raw", "composite"):
            for m in metrics.get(group) or []:
                name = m.get("name")
                if name:
                    names.append(name)
    return names


def metric_names_from_sat(tosca_path: str) -> list:
    """
    Metric names (raw + composite) declared in a SAT, obtained via the Sardou
    lib's get_monitoring(). Falls back to [DEFAULT_METRIC] if the SAT cannot
    be processed.

    Whatever metrics an application's SAT declares (CPU, memory, ...) are
    returned dynamically — nothing is hardcoded here.
    """
    try:
        details = get_monitoring_details(tosca_path)
    except Exception as e:
        logger.warning(
            f"Sardou could not process SAT '{tosca_path}': {e}; using default metric"
        )
        return [DEFAULT_METRIC]

    return metric_names_from_details(details) or [DEFAULT_METRIC]


def get_monitoring_data(
    metrics: list,
    mode: str = "standard",
    collect_seconds: int = 60,
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
                    # metric values are debugging detail: DEBUG, not INFO
                    logger.debug(f"[poll {i}/{polls}] '{metric}': {batch}")

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
                    logger.debug(f"[poll {i}/{polls}] '{metric}': {fresh if fresh else 'no new samples'}")

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


# --- persistent-subscription primitives (subscribe once, poll periodically) ---
# The Optimiser needs a complete snapshot per poll: subscribe once at startup,
# then poll at an interval >= the SAT's collection frequencies (e.g. 60s), so
# every metric has values in every poll.

def poll_interval_from_details(details: dict, floor_seconds: int = 60) -> int:
    """
    Poll interval derived from the SAT: the slowest collection_frequency
    (raw or composite) in seconds, never below min_seconds. A poll is only
    complete once the slowest metric has had time to publish a value.
    """
    units = {"sec": 1, "min": 60}
    slowest = 0
    for entry in details.values():
        metrics = entry.get("metrics") or {}
        for group in ("raw", "composite"):
            for m in metrics.get(group) or []:
                match = re.match(r"\s*(\d+)\s*(sec|min)", str(m.get("collection_frequency", "")))
                if match:
                    slowest = max(slowest, int(match.group(1)) * units[match.group(2)])
    return max(slowest, floor_seconds)


# Raw source for per-node load. The Optimiser needs load per node (see the
# node_load parameter its examples take), but a composite metric only publishes
# per node when the SAT sets "grouping: per_host" - and that was measured to
# stop every other metric arriving on the standard subscriptions. So the per-node
# figure is derived here from the raw idle metric instead, using the same
# formula the SAT's cpu_util_prct composite uses: 100 - mean(cpu_idle_instance).
NODE_LOAD_SOURCE = "cpu_idle_instance"

_raw_manager = None


def _get_raw_manager():
    """
    A subscription manager of our own, for raw (per-node) metrics.

    The library's module-level manager refuses a metric in raw mode when it is
    already subscribed in standard mode, and the Swarm Agent subscribes every
    SAT metric that way. A separate instance keeps the two sets independent.
    """
    global _raw_manager
    if _raw_manager is None:
        from swchmonclient.metrics import MetricSubscriptionManager
        _raw_manager = MetricSubscriptionManager()
    return _raw_manager


def subscribe_node_metric(metric: str = NODE_LOAD_SOURCE) -> list:
    """
    Subscribe `metric` in raw mode on every node, so its values arrive keyed by
    node instead of averaged into one number. Returns the node keys subscribed.
    """
    threads = _get_raw_manager().subscribe_metric_raw(metric, "all") or {}
    nodes = sorted(threads.keys())
    logger.info(f"Subscribed to raw metric '{metric}' on {len(nodes)} node(s): {nodes}")
    return nodes


def node_loads(metric: str = NODE_LOAD_SOURCE, seconds: int = 300) -> dict:
    """
    Load percentage per node, as {node-key: load}.

    `metric` is an idle percentage, so load is 100 minus its mean over the
    window - the same formula the SAT's cpu_util_prct composite applies, just
    kept per node rather than averaged across the cluster.

    Nodes that reported nothing in the window are left out; the caller decides
    what an incomplete picture means.
    """
    raw = _get_raw_manager().query_metric_values_raw(metric, seconds) or {}
    loads = {}
    for node, samples in raw.items():
        values = [
            sample.get("value") for sample in samples
            if isinstance(sample.get("value"), (int, float))
        ]
        if values:
            loads[node] = 100.0 - (sum(values) / len(values))
    logger.debug(f"node loads from '{metric}': {loads}")
    return loads


def subscribe_metrics(metrics: list) -> None:
    """Start (or reuse) standard-metric subscriptions for all given metrics."""
    from swchmonclient import subscribe_metric
    for metric in metrics:
        logger.info(f"Subscribing to standard metric '{metric}'")
        subscribe_metric(metric)


def poll_metrics(metrics: list) -> dict:
    """
    One snapshot: drain each subscribed metric's buffer once.
    Returns {metric: [values]}. Values are logged at DEBUG level.
    """
    from swchmonclient import query_metric_values
    snapshot = {}
    for metric in metrics:
        values = query_metric_values(metric)
        snapshot[metric] = values
        logger.debug(f"poll '{metric}': {values}")
    return snapshot


def unsubscribe_metrics(metrics: list) -> None:
    """Stop the subscriptions (best effort)."""
    from swchmonclient import unsubscribe_metric
    for metric in metrics:
        try:
            unsubscribe_metric(metric)
        except Exception as e:
            logger.warning(f"Unsubscribe failed for '{metric}': {e}")


_OPERATORS = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
}


def slo_violations_from_sat(monitoring_data: dict, tosca_path: str) -> list:
    """
    Evaluate the SAT `slo-constraints` (obtained via the Sardou lib) against
    already-collected standard monitoring data (the diagram's second
    monitor-client output).

    Compares the mean of the collected values for the constraint's metric to its
    threshold using the declared operator. Returns a list of violation records:
        [{"name", "metric", "operator", "threshold", "observed", "violated"}]

    Minimal by design: derives from data we already have; adds no new source.
    Only meaningful for mode="standard" (list-of-values per metric).
    """
    try:
        details = get_monitoring_details(tosca_path)
    except Exception as e:
        logger.warning(f"Sardou could not process SAT '{tosca_path}': {e}; no SLO check")
        return []

    return evaluate_slo(monitoring_data, details)


def evaluate_slo(monitoring_data: dict, details: dict) -> list:
    """
    Evaluate slo-constraints (an already-fetched get_monitoring() result)
    against collected standard monitoring data — no SAT re-processing.
    """
    metrics_values = monitoring_data.get("metrics", {})
    results = []

    for entry in details.values():
        slo = entry.get("slo-constraints")
        if not slo:
            continue

        # Sardou may return a single constraint (dict) or several (list).
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
