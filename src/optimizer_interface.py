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
