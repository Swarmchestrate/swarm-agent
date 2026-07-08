# cluster_status.py
"""
Cluster-status input for the Optimiser.

Provides the "actual mapping" the Optimiser expects (LSA sequence, step 4):
which pods are currently running and on which node. This is the k3s_client /
k8s side of the three Optimiser inputs.

Reuses the in-cluster client pattern already used by the Swarm Agent
(see src/SA.py:_deploy_application), so it runs from inside an SA pod using its
mounted ServiceAccount. RBAC already grants pods get/list/watch
(k3s/01-rbac-swarm-agent.yaml).
"""

import logging

from kubernetes import client, config

logger = logging.getLogger("ClusterStatus")


def _container_resources(container):
    """Compact CPU/memory requests for a container (None if unset)."""
    requests = {}
    if container.resources and container.resources.requests:
        requests = container.resources.requests
    return {
        "name": container.name,
        "image": container.image,
        "cpu_request": requests.get("cpu"),
        "mem_request": requests.get("memory"),
    }


def get_cluster_status(namespace: str = None, only_running: bool = True) -> list:
    """
    List pods (the current pod->node mapping) from the k8s API.

    Args:
        namespace: restrict to one namespace; None = all namespaces.
        only_running: keep only pods in phase "Running".

    Returns a list of pod dicts:
        {name, namespace, node, phase, pod_ip, containers: [{name, image,
         cpu_request, mem_request}]}
    """
    # Same init as src/SA.py:352-355 — in-cluster ServiceAccount credentials.
    config.load_incluster_config()
    v1 = client.CoreV1Api()

    if namespace:
        pods = v1.list_namespaced_pod(namespace).items
    else:
        pods = v1.list_pod_for_all_namespaces().items

    result = []
    for pod in pods:
        phase = pod.status.phase
        if only_running and phase != "Running":
            continue

        result.append({
            "name": pod.metadata.name,
            "namespace": pod.metadata.namespace,
            "node": pod.spec.node_name,
            "phase": phase,
            "pod_ip": pod.status.pod_ip,
            "containers": [_container_resources(c) for c in pod.spec.containers],
        })

    logger.info(f"Cluster status: {len(result)} pod(s)")
    return result
