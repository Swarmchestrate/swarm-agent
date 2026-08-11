# k3s_client_input.py
"""
Cluster-status input for the Optimiser, via the official k3s-client library.

Provides the "actual mapping" the Optimiser expects (LSA sequence, step 4):
which pods of each microservice currently run on which node. This is the third
Optimiser input, next to the AI predictions and the monitoring data.

Wraps k3s_client.api.applications.ApplicationManager.get_pod_node_mapping(),
which returns:

    {"<msid>": {"<pod-name>": "<node-name>", ...}, ...}

where msid is the pod's "service" label, falling back to "app", then the pod
name (the same identifiers the lib's action methods — create_pod, delete_pod,
scale_to, migrate_pod — take as input, so Optimiser actions can refer to them
directly).

Requirements (both already in place for the Swarm Agent):
- the kubectl binary in the image (the lib shells out to kubectl; in-cluster it
  authenticates as the pod's ServiceAccount)
- pods get/list RBAC (k3s/01-rbac-swarm-agent.yaml)
"""

import logging

logger = logging.getLogger("K3sClientInput")

# k3s_client is imported lazily so this module stays importable where the lib
# (or the kubectl binary) is not installed yet — same pattern as
# monitoring_input.py.

_manager = None


def _get_manager():
    """Create (once) and reuse the lib's ApplicationManager."""
    global _manager
    if _manager is None:
        from k3s_client.api.applications import ApplicationManager
        _manager = ApplicationManager()
    return _manager


def get_cluster_status(label_selector: str = None) -> dict:
    """
    Current pod->node mapping grouped by microservice, from the k3s-client lib.

    Args:
        label_selector: optional kubectl label selector (e.g. "app=stressng")
            to restrict which pods are included; None = all.

    Returns {"<msid>": {"<pod>": "<node>"}} — {} if nothing matches.
    """
    mapping = _get_manager().get_pod_node_mapping(label_selector=label_selector) or {}
    pods = sum(len(p) for p in mapping.values())
    logger.info(f"Cluster status: {len(mapping)} microservice(s), {pods} pod(s)")
    logger.debug(f"pod->node mapping: {mapping}")
    return mapping
