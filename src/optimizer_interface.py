# optimizer_interface.py
"""
Optimiser input contract + orchestration.

The Optimiser (Opt) consumes three per-cycle inputs and returns a list of
reconfiguration actions (LSA sequence, step 4):

    (predicted values, monitoring data, cluster status)  ->  list of actions

Current reality:
- Monitoring data  -> BUILT (monitoring_input.get_monitoring_data)
- Cluster status   -> BUILT (k3s_client_input.get_cluster_status, k3s-client lib)
- Predicted values -> AI component PENDING (stubbed, returns None)
- Opt itself       -> being built (optimize() is a stub)

This module is the single seam: when the Opt lib lands, wire it into optimize().
The next downstream consumer is the DT (digital twin, step 5), also pending.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from monitoring_input import get_monitoring_data, metric_names_from_sat
from k3s_client_input import get_cluster_status
# Cluster status now comes from the official k3s-client library
# (k3s_client_input.py wraps ApplicationManager.get_pod_node_mapping):
# {"<msid>": {"<pod>": "<node>"}}. The lib's action methods (create_pod,
# delete_pod, scale_to, migrate_pod) use the same msid/pod/node identifiers,
# so future Optimiser actions can reference this mapping directly.

logger = logging.getLogger("OptimizerInterface")


@dataclass
class OptimizerInputs:
    """The three inputs handed to the Optimiser (names mirror the diagram)."""
    predicted_values: Optional[dict]   # from AI component (PENDING -> None)
    monitoring_data: dict              # from the monitor client
    cluster_status: dict               # {msid: {pod: node}} from the k3s-client lib


def rule_required_inputs(rule: str, mslist: list = None) -> dict:
    """
    Ask the Optimiser which variables a reconfiguration rule refers to, by
    handing it the rule text (swchoptimiser builds the MiniZinc model and
    reports its parameters).

    Returns {"system": [...], "app": [...], "outputs": [...]} where "app" is the
    list the Swarm Agent has to fill: the rule's constants and metrics.

    Raises RuntimeError if the Optimiser cannot load the rule (a bad rule is a
    SAT authoring error worth surfacing, not something to hide).
    """
    from swch_optimiser import SwchOptimiser

    opt = SwchOptimiser(rule, mslist=mslist or [])
    err = opt.get_error()
    if err:
        raise RuntimeError(f"Optimiser could not load the rule: {err}")
    return {
        "system": sorted(opt.query_system_inputs().keys()),
        "app": sorted(opt.query_appspec_inputs().keys()),
        "outputs": sorted(opt.query_outputs().keys()),
    }


def check_rule_inputs(reconfiguration: dict, metric_names, node_metric_names=None) -> dict:
    """
    Work out, per reconfiguration policy, where each application input its rule
    needs comes from: a constant declared in the SAT, one of the metrics we
    subscribe to, or nothing at all.

    The Optimiser cannot start a calculation while a variable it refers to has
    no value, so the "missing" list is the one to act on.

    Args:
        reconfiguration: a get_reconfiguration_details() result.
        metric_names: the metric names the SAT declares (and we subscribe to).
        node_metric_names: names the Swarm Agent supplies per node rather than
            as a single value (node_load), which the SAT does not declare.

    Returns {"<policy>": {"sources": {"<var>": "constant"|"metric"|"node-metric"},
                          "missing": ["<var>", ...],
                          "outputs": [...]}}
    """
    metrics = set(metric_names or [])
    node_metrics = set(node_metric_names or [])
    report = {}
    for policy, body in (reconfiguration or {}).items():
        rule = body.get("rule") or ""
        constants = body.get("constants") or {}
        needed = rule_required_inputs(rule, body.get("targets"))
        sources, missing = {}, []
        for name in needed["app"]:
            if name in constants:
                sources[name] = "constant"
            elif name in metrics:
                sources[name] = "metric"
            elif name in node_metrics:
                sources[name] = "node-metric"
            else:
                missing.append(name)
        report[policy] = {
            "sources": sources,
            "missing": missing,
            "outputs": needed["outputs"],
        }
    return report


def build_rule_inputs(reconfiguration: dict, rule_report: dict, monitoring_data: dict,
                      node_metrics: dict = None) -> dict:
    """
    Build the application inputs a reconfiguration rule needs for one cycle:
    the subset of the collected metrics the rule actually refers to, plus its
    constants, in the shape the Optimiser takes them
    (add_input_metrics / add_input_constants).

    A poll returns a list of values per metric (whatever arrived in that window),
    while a rule variable is a single number, so the values are averaged - the
    same reduction evaluate_slo() already applies to SLO checks.

    Constants come back from the SAT as strings ("80"), so they are converted to
    numbers here; anything non-numeric is passed through untouched.

    A metric can be subscribed and still have no value in a given cycle. Those
    are listed under "unavailable" and "ready" is False: the Optimiser cannot
    calculate while one of its variables has no value.

    `node_metrics` carries values that are one-per-node rather than one number
    ({"node_load": [11.0, 98.8]}), already ordered to match the node numbering
    in to_system_input. They are passed through as arrays, which is what the
    rule declares them as.

    Returns {"<policy>": {"metrics": {...}, "constants": {...},
                          "unavailable": [...], "ready": bool}}
    """
    values = (monitoring_data or {}).get("metrics", {})

    def as_number(raw):
        try:
            return float(raw)
        except (TypeError, ValueError):
            return raw

    bundle = {}
    for policy, report in (rule_report or {}).items():
        declared = (reconfiguration.get(policy) or {}).get("constants") or {}
        metrics, constants, unavailable = {}, {}, []

        for name, source in report.get("sources", {}).items():
            if source == "constant":
                constants[name] = as_number(declared.get(name))
                continue
            if source == "node-metric":
                per_node = (node_metrics or {}).get(name)
                if per_node:
                    metrics[name] = per_node
                else:
                    unavailable.append(name)
                continue
            samples = values.get(name) or []
            if samples:
                metrics[name] = sum(samples) / len(samples)
            else:
                unavailable.append(name)

        # variables nothing can fill at all (reported once at startup) also
        # block the Optimiser, so they count as unavailable every cycle
        unavailable.extend(report.get("missing", []))

        bundle[policy] = {
            "metrics": metrics,
            "constants": constants,
            "unavailable": sorted(unavailable),
            "ready": not unavailable,
        }
    return bundle


def node_load_array(loads_by_key: dict, node_names: list, node_ips: dict = None) -> list:
    """
    Per-node loads ordered to match the node numbering to_system_input uses, so
    node_load[n] describes the same machine as node number n in the mapping.

    The monitoring stack keys its values by IP address, so `node_ips`
    (name -> IP, from get_node_ips) is used to look each node up; a value keyed
    by node name is accepted too.

    Returns None when any node has no value. A short array would silently
    renumber the nodes, and a guessed value would be worse than none - the
    caller should skip the cycle instead.
    """
    ips = node_ips or {}
    ordered = []
    for name in node_names:
        value = loads_by_key.get(name)
        if value is None:
            value = loads_by_key.get(ips.get(name))
        if value is None:
            return None
        ordered.append(float(value))
    return ordered


def describe_inputs(metrics: dict) -> str:
    """
    One-line rendering of a rule's metric inputs for the log, handling both a
    single number and a per-node array.
    """
    parts = []
    for name, value in sorted((metrics or {}).items()):
        if isinstance(value, (list, tuple)):
            parts.append(f"{name}=[{', '.join(f'{v:.2f}' for v in value)}]")
        else:
            parts.append(f"{name}={value:.2f}")
    return ", ".join(parts)


def to_system_input(
    cluster_status: dict,
    node_names: list,
    pod_count_max: int = None,
    node_count_max: int = None,
    headroom: int = 4,
) -> tuple:
    """
    Convert the pod->node mapping into the numeric system input the Optimiser
    takes, and return the index needed to read its answer back.

    Ours (names):        {"stressng": {"stressng-v1-abc": "node-a"}}
    The Optimiser's:     {"sys_pod_count_max": 5, "sys_node_count_max": 2,
                          "sys_node_count_actual": 2,
                          "sys_mapping_actual": [1, 0, 0, 0, 0]}

    Nodes become numbers by their position in `node_names` (1-based), pods take
    a slot in the mapping array, and 0 means "no pod in this slot". With more
    than one microservice the Optimiser expects one array each, suffixed with
    the microservice name (sys_mapping_actual_<ms>), which is the convention its
    generate_actions() reads back.

    Both orderings are sorted by name so the same cluster always produces the
    same numbering - the Optimiser's answer is meaningless if the indices move
    between cycles.

    Args:
        cluster_status: {msid: {pod: node}}, already filtered to the application.
        node_names: every node in the cluster, sorted (see get_node_names).
        pod_count_max: array length. Defaults to the current pod count plus
            `headroom`, since the Optimiser can only add pods into free slots.
        node_count_max: defaults to the number of nodes - the Swarm Agent cannot
            create nodes, so it does not offer the Optimiser more than exist.
        headroom: spare slots when pod_count_max is not given.

    Returns (system, index) where index is
        {"nodes": [...], "slots": {msid: [pod-or-None, ...]},
         "deployments": {msid: deployment-name}}
    """
    nodes = list(node_names)
    node_number = {name: i + 1 for i, name in enumerate(nodes)}

    pods_total = sum(len(p) for p in cluster_status.values())
    slots_per_ms = pod_count_max or (pods_total + headroom)

    system = {
        "sys_pod_count_max": slots_per_ms,
        "sys_node_count_max": node_count_max or len(nodes),
        "sys_node_count_actual": len(nodes),
    }
    index = {"nodes": nodes, "slots": {}, "deployments": {}}

    multi = len(cluster_status) > 1
    for msid in sorted(cluster_status):
        pods = cluster_status[msid]
        ordered = sorted(pods)
        mapping, slots = [], []
        for pod in ordered[:slots_per_ms]:
            mapping.append(node_number.get(pods[pod], 0))
            slots.append(pod)
        while len(mapping) < slots_per_ms:      # free slots the Optimiser may fill
            mapping.append(0)
            slots.append(None)

        key = f"sys_mapping_actual_{msid}" if multi else "sys_mapping_actual"
        system[key] = mapping
        index["slots"][msid] = slots
        index["deployments"][msid] = deployment_name_of(ordered[0]) if ordered else msid

    if multi:
        # Every rule declares the plain sys_mapping_actual in the system block it
        # must carry, so the Optimiser needs a value for it even when the rule
        # tracks a mapping per microservice instead. An empty array satisfies it
        # without claiming any pod placement of its own.
        system.setdefault("sys_mapping_actual", [0] * slots_per_ms)

    return system, index


def deployment_name_of(pod_name: str) -> str:
    """
    Deployment a pod belongs to, from its name.

    Kubernetes names a Deployment's pods "<deployment>-<replicaset>-<random>",
    so dropping the last two parts gives the Deployment. This matters because
    the k3s-client action methods take the deployment name ("stressng-v1")
    while the mapping is keyed by the microservice label ("stressng").
    """
    parts = pod_name.rsplit("-", 2)
    return parts[0] if len(parts) == 3 else pod_name


def actions_to_k3s_calls(actions: list, index: dict) -> list:
    """
    Translate the Optimiser's actions back into k3s-client calls.

    The Optimiser answers in numbers - "create_ms name=stressng pod=3 node=2" -
    which the index turns back into the names the k3s-client needs.

    Node-level actions are reported but not translated: creating or destroying a
    node is the Resource Agent's job, not something the Swarm Agent can do.

    Returns one record per action:
        {"action": ..., "method": "scale_to"|"create_pod"|"delete_pod"|None,
         "kwargs": {...}, "description": "...", "supported": bool}
    """
    nodes = index.get("nodes", [])
    slots = index.get("slots", {})
    deployments = index.get("deployments", {})
    calls = []

    for act in actions or []:
        kind = act.get("action")
        msid = act.get("name")
        deployment = deployments.get(msid, msid)

        if kind == "create_ms":
            node_no = act.get("node", 0)
            node = nodes[node_no - 1] if 0 < node_no <= len(nodes) else None
            calls.append({
                "action": kind,
                "method": "create_pod",
                "kwargs": {"msid": deployment, "nodeid": node},
                "description": f"add a pod of '{msid}' on node '{node}'",
                "supported": node is not None,
            })

        elif kind == "destroy_ms":
            slot = act.get("pod", 0) - 1
            ms_slots = slots.get(msid, [])
            pod = ms_slots[slot] if 0 <= slot < len(ms_slots) else None
            calls.append({
                "action": kind,
                "method": "delete_pod",
                "kwargs": {"msid": deployment, "podid": pod},
                "description": f"remove pod '{pod}' of '{msid}'",
                "supported": pod is not None,
            })

        elif kind in ("create_node", "destroy_node"):
            calls.append({
                "action": kind,
                "method": None,
                "kwargs": {"nodeid": act.get("nodeid")},
                "description": f"{kind} is a resource-level action (Resource Agent)",
                "supported": False,
            })

        else:
            calls.append({
                "action": kind,
                "method": None,
                "kwargs": {},
                "description": f"unknown action '{kind}'",
                "supported": False,
            })

    return calls


def get_predicted_values() -> Optional[dict]:
    """
    AI component input. Status: PENDING — the AI agent is still being built.

    When ready it returns the "list of predicted values" for the parameters the
    AI is configured to predict. Until then this returns None so the Optimiser
    can treat predictions as unavailable.
    """
    logger.info("AI component PENDING; predicted_values = None")
    return None


def collect_inputs(
    tosca_path: str,
    label_selector: str = None,
    mode: str = "standard",
    collect_seconds: int = 60,
) -> OptimizerInputs:
    """
    Assemble the Optimiser inputs (LSA steps 1-4, minus the Opt call):
    collect monitoring data, read cluster status, and gather AI predictions
    (currently None).

    Metric names are taken from the SAT. `label_selector` optionally restricts
    the cluster-status mapping (e.g. "app=stressng"); None = all pods.
    """
    metrics = metric_names_from_sat(tosca_path)
    monitoring_data = get_monitoring_data(
        metrics, mode=mode, collect_seconds=collect_seconds
    )
    cluster = get_cluster_status(label_selector=label_selector)
    predictions = get_predicted_values()

    return OptimizerInputs(
        predicted_values=predictions,
        monitoring_data=monitoring_data,
        cluster_status=cluster,
    )


def optimize(inputs: OptimizerInputs):
    """
    Call the Optimiser to get the reconfiguration decision (list of actions:
    new mappings, new/delete resources).

    STUB: the Opt library is still being built. This is the single place to wire
    it in — pass `inputs` through and return its list of actions. The result
    then feeds the DT (step 5) for ranking before the SA's final decision.
    """
    logger.info(
        "optimize() called with %d cluster pods, monitoring mode=%s, predictions=%s",
        len(inputs.cluster_status),
        inputs.monitoring_data.get("mode"),
        "present" if inputs.predicted_values is not None else "PENDING",
    )
    raise NotImplementedError(
        "Optimiser library not yet available. Wire the real Opt call here: "
        "optimize(predicted_values, monitoring_data, cluster_status) -> list of actions."
    )
