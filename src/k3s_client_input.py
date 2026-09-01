# k3s_client_input.py


import logging

logger = logging.getLogger("K3sClientInput")

_manager = None


def _get_manager():
    """Create (once) and reuse the lib's ApplicationManager."""
    global _manager
    if _manager is None:
        from k3s_client.api.applications import ApplicationManager
        _manager = ApplicationManager()
    return _manager


def get_application_manager():
    return _get_manager()

def _fallback_mapping(label_selector: str = None) -> dict:
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


def get_node_names() -> list:
    """
    Every node in the cluster, sorted by name.

    The pod->node mapping only names nodes that currently host a pod, but the
    Optimiser needs the full set: a node with nothing on it is still somewhere a
    pod can be placed.
    """
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()
    return sorted(n.metadata.name for n in client.CoreV1Api().list_node().items)


def get_node_ips() -> dict:
    """
    Node name -> internal IP address.

    The monitoring stack keys its per-node values by IP, while the Optimiser
    numbers nodes by their position in get_node_names(). This is the lookup
    between the two, so a per-node metric can be placed in the right slot.
    """
    from kubernetes import client, config
    try:
        config.load_incluster_config()
    except Exception:
        config.load_kube_config()

    addresses = {}
    for node in client.CoreV1Api().list_node().items:
        for address in node.status.addresses or []:
            if address.type == "InternalIP":
                addresses[node.metadata.name] = address.address
                break
    return addresses


def get_cluster_status(label_selector: str = None, microservices: set = None) -> dict:
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
    # Keep only the application's microservices when the caller passes the set
    # declared in the SAT. The monitoring stack's own pods (ems*, netdata) are
    # infrastructure, not something the Optimiser orchestrates.
    dropped = 0
    if microservices is not None:
        full = mapping
        mapping = {ms: pods for ms, pods in full.items() if ms in microservices}
        dropped = len(full) - len(mapping)

    pods = sum(len(p) for p in mapping.values())
    suffix = f"; {dropped} system entr{'y' if dropped == 1 else 'ies'} filtered out" if dropped else ""
    logger.info(f"Cluster status: {len(mapping)} microservice(s), {pods} pod(s){suffix}")
    logger.debug(f"pod->node mapping: {mapping}")
    return mapping
