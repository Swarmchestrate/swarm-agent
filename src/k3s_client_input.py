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

The lib uses the kubernetes Python SDK with in-cluster auth (the pod's
ServiceAccount); pods get/list RBAC is already granted
(k3s/01-rbac-swarm-agent.yaml).
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


def _fallback_mapping(label_selector: str = None) -> dict:
    """
    TEMPORARY workaround for a k3s-client 0.3.0 bug (reported to its team):
    Kubectl.get() passes the dynamic-client response to
    sanitize_for_serialization(), which crashes with kubernetes==35.0.0
    ("'NoneType' object has no attribute 'items'"). Until the lib is fixed,
    build the mapping directly from the kubernetes SDK with the SAME output
    shape, the SAME msid rule (service label -> app label -> pod name) and the
    SAME namespace scope ("default") as the lib, so nothing downstream changes.
    """
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    v1 = client.CoreV1Api()
    pods = v1.list_namespaced_pod("default", label_selector=label_selector).items
    grouped = {}
    for pod in pods:
        labels = pod.metadata.labels or {}
        msid = labels.get("service") or labels.get("app") or pod.metadata.name
        grouped.setdefault(msid, {})[pod.metadata.name] = pod.spec.node_name
    return grouped


def get_cluster_status(label_selector: str = None) -> dict:
    """
    Current pod->node mapping grouped by microservice, from the k3s-client lib.

    Args:
        label_selector: optional label selector (e.g. "app=stressng")
            to restrict which pods are included; None = all.

    Returns {"<msid>": {"<pod>": "<node>"}} — {} if nothing matches.
    """
    try:
        mapping = _get_manager().get_pod_node_mapping(label_selector=label_selector) or {}
    except Exception as e:
        logger.warning(
            f"k3s-client get_pod_node_mapping failed ({e}); using direct-API fallback "
            f"(known 0.3.0 serialization bug)"
        )
        mapping = _fallback_mapping(label_selector)
    pods = sum(len(p) for p in mapping.values())
    logger.info(f"Cluster status: {len(mapping)} microservice(s), {pods} pod(s)")
    logger.debug(f"pod->node mapping: {mapping}")
    return mapping
