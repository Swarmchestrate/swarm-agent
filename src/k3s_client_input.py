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


def _nodes() -> list:
    """Every Node object in the cluster, via the k3s-client's list_nodes()."""
    return get_application_manager().pod_manager.list_nodes() or []


def get_node_names() -> list:
    """
    Every node in the cluster, sorted by name.

    The pod->node mapping only names nodes that currently host a pod, but the
    Optimiser needs the full set: a node with nothing on it is still somewhere a
    pod can be placed.
    """
    return sorted(n.get("metadata", {}).get("name") for n in _nodes())


def get_node_ips() -> dict:
    """
    Node name -> internal IP address.

    The monitoring stack keys its per-node values by IP, while the Optimiser
    numbers nodes by their position in get_node_names(). This is the lookup
    between the two, so a per-node metric can be placed in the right slot.
    """
    addresses = {}
    for node in _nodes():
        name = node.get("metadata", {}).get("name")
        for address in node.get("status", {}).get("addresses") or []:
            if address.get("type") == "InternalIP":
                addresses[name] = address.get("address")
                break
    return addresses


def get_node_labels(key: str = "labels.swarmchestrate.eu/ms_id") -> dict:
    """Node name -> value of one node label (None when the node lacks it)."""
    return {
        n.get("metadata", {}).get("name"): (n.get("metadata", {}).get("labels") or {}).get(key)
        for n in _nodes()
    }


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
    # The namespace is the real boundary: system components (the Swarm Agent,
    # the monitoring stack) live in swarm-system and the mapping is read from the
    # application namespace, so normally nothing here needs filtering. The SAT's
    # microservice set is kept as a safety net for anything else that turns up in
    # the application namespace - and it is never silent about what it drops.
    dropped = 0
    if microservices is not None:
        full = mapping
        mapping = {ms: pods for ms, pods in full.items() if ms in microservices}
        dropped = len(full) - len(mapping)
        if dropped:
            unexpected = sorted(ms for ms in full if ms not in microservices)
            logger.warning(
                f"Cluster status: {dropped} entr{'y' if dropped == 1 else 'ies'} in the "
                f"application namespace not declared by the SAT, left out of the "
                f"Optimiser input: {unexpected}"
            )

    pods = sum(len(p) for p in mapping.values())
    suffix = f"; {dropped} system entr{'y' if dropped == 1 else 'ies'} filtered out" if dropped else ""
    logger.info(f"Cluster status: {len(mapping)} microservice(s), {pods} pod(s){suffix}")
    logger.debug(f"pod->node mapping: {mapping}")
    return mapping
