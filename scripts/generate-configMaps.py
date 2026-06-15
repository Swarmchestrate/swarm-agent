#!/usr/bin/env python3

import argparse
import json
import shutil
import subprocess
from pathlib import Path

from utility import generate_tosca_configmap as write_tosca_configmap
from utility import generate_swarm_configmap as write_swarm_configmap


def get_k8s_node_names():
    result = subprocess.run(
        ["kubectl", "get", "nodes", "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    )

    data = json.loads(result.stdout)
    return [item["metadata"]["name"] for item in data["items"]]


def copy_base_k3s_yamls(k3s_dir, output_dir):
    k3s_dir = Path(k3s_dir)
    output_dir = Path(output_dir)

    files_to_copy = [
        "00-namespace-swarm-system.yaml",
        "01-rbac-swarm-agent.yaml",
        "02-daemonset-swarm-agent.yaml",
    ]

    for filename in files_to_copy:
        src = k3s_dir / filename
        dst = output_dir / filename

        if not src.exists():
            raise FileNotFoundError(f"Missing required K3s YAML: {src}")

        shutil.copy2(src, dst)
        print(f"Copied: {dst}")


def generate_configs(
    job_id,
    tosca_path,
    hub_ra_ip,
    leader=None,
    output_base="../output",
    k3s_dir="../k3s",
):
    tosca_path = Path(tosca_path)

    if not tosca_path.exists():
        raise FileNotFoundError(f"TOSCA file not found: {tosca_path}")

    node_names = get_k8s_node_names()

    if not node_names:
        raise RuntimeError("No Kubernetes nodes found")

    if leader is None:
        leader = node_names[0]

    if leader not in node_names:
        raise ValueError(
            f"Leader '{leader}' is not a Kubernetes node. "
            f"Available nodes: {node_names}"
        )

    resource_input = {
        "LEADER": leader,
        "Worker": [node for node in node_names if node != leader],
    }

    output_dir = Path(output_base) / f"cluster_{job_id}"
    output_dir.mkdir(parents=True, exist_ok=True)

    copy_base_k3s_yamls(
        k3s_dir=k3s_dir,
        output_dir=output_dir,
    )

    tosca_configmap_path = output_dir / "03-configmap-swarm-agent-tosca.yaml"
    swarm_configmap_path = output_dir / "04-configmap-swarm-agent-config.yaml"

    write_tosca_configmap(
        str(tosca_path),
        output_file=str(tosca_configmap_path),
    )

    write_swarm_configmap(
        resource_input,
        application_id=job_id,
        output_file=str(swarm_configmap_path),
        ra_ip=hub_ra_ip,
    )

    print("Generated configs successfully")
    print(f"Output folder: {output_dir}")
    print(f"TOSCA ConfigMap: {tosca_configmap_path}")
    print(f"Swarm ConfigMap: {swarm_configmap_path}")
    print(f"Leader: {leader}")
    print(f"Workers: {resource_input['Worker']}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate Swarmchestrate K3s YAMLs and ConfigMaps."
    )

    parser.add_argument("--job-id", required=True)
    parser.add_argument("--tosca-path", required=True)
    parser.add_argument("--hub-ra-ip", required=True)
    parser.add_argument("--leader", default=None)
    parser.add_argument("--output-base", default="../output")
    parser.add_argument("--k3s-dir", default="../k3s")

    args = parser.parse_args()

    generate_configs(
        job_id=args.job_id,
        tosca_path=args.tosca_path,
        hub_ra_ip=args.hub_ra_ip,
        leader=args.leader,
        output_base=args.output_base,
        k3s_dir=args.k3s_dir,
    )


if __name__ == "__main__":
    main()
