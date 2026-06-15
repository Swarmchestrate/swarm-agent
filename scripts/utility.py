# utility.py
import yaml
from pathlib import Path

"""

Utility functions for YAML handling
dictionary conversion, QoS extraction,

 and ConfigMap generation.
prepare Kubernetes ConfigMaps that contains TOSCA files.
prepare Kubernetes ConfigMaps that configures Swarm Agent.
 
"""

def dict_to_yaml(data: dict, filename: str):
    """
    Convert a Python dictionary to a YAML file.

    Args:
        data (dict): The dictionary to convert.
        filename (str): Output YAML file name (e.g., 'output.yaml')
    """
    with open(filename, 'w') as f:
        yaml.dump(data, f, sort_keys=False, indent=2)



def get_resource_capacity(capacity_config_path, res_id):
    with open(capacity_config_path, "r") as f:
        config = yaml.safe_load(f)

    node_types = config.get("node_types", {})

    resource_type = node_types.get(res_id)
    if not resource_type:
        return None

    host_props = (
        resource_type
        .get("capabilities", {})
        .get("host", {})
        .get("properties", {})
    )

    cpu = host_props.get("num-cpus", {}).get("default", 0)
    memory = host_props.get("mem-size", {}).get("default", 0)

    return cpu, memory

def extract_qos_priorities(qos_data):
    qos_priority = {}

    if not qos_data:
        return qos_priority

    # Case 1: qos_data is already a dict:
    # {"bandwidth": {...}, "cost": {...}, "energy": {...}}
    if isinstance(qos_data, dict):
        iterator = qos_data.items()

    # Case 2: qos_data is a list:
    # [{"bandwidth": {...}}, {"cost": {...}}]
    elif isinstance(qos_data, list):
        iterator = []
        for item in qos_data:
            if isinstance(item, dict):
                iterator.extend(item.items())
    else:
        print(f"[WARNING] Unexpected QoS format: {type(qos_data)}")
        return qos_priority

    for key, val in iterator:
        if not isinstance(val, dict):
            continue

        priority = val.get("priority")
        if priority is None:
            priority = val.get("properties", {}).get("priority")

        if priority is not None:
            normalized_key = "price" if key == "cost" else key
            qos_priority[normalized_key] = priority

    return qos_priority

def generate_tosca_configmap(
    tosca_path: str,
    output_file: str = "swarm-tosca-configmap.yaml",
    configmap_name: str = "swarm-agent-tosca",
    namespace: str = "swarm-system",
    key_prefix: str = "tosca-",
) -> None:
    """
    Read a TOSCA/manifest file from `tosca_path` and wrap it into a
    Kubernetes ConfigMap using block-style `|` under data:.
    """

    path = Path(tosca_path)

    if not path.is_file():
        raise FileNotFoundError(f"TOSCA file not found: {tosca_path}")

    # Read the original TOSCA / manifest content
    with path.open("r", encoding="utf-8") as f:
        content = f.read().rstrip("\n")

    # Key name inside data: (e.g. tosca-lead-worker.yaml)
    #key_name = f"{key_prefix}{path.name}"
    key_name = "tosca.yaml"
    lines = []
    lines.append("apiVersion: v1")
    lines.append("kind: ConfigMap")
    lines.append("metadata:")
    lines.append(f"  name: {configmap_name}")
    lines.append(f"  namespace: {namespace}")
    lines.append("data:")
    lines.append(f"  {key_name}: |")

    # Indent each line of the file content by 4 spaces (2 for data key, 2 more for block content)
    for line in content.splitlines():
        lines.append(f"    {line}")

    final_yaml = "\n".join(lines) + "\n"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(final_yaml)

    print(f"✅ TOSCA ConfigMap written to: {output_file}")
    print(f"   - data key: {key_name}")
    print(f"   - source file: {tosca_path}")

#!/usr/bin/env python3

def generate_swarm_configmap(resource_dict, application_id, ra_ip, output_file="swarm-config.yaml"):
    leader_name = resource_dict.get("LEADER")
    workers = resource_dict.get("Worker", [])

    def make_block(sa_id, role, resource_id):
        return f"""SA_id: "{sa_id}"
SA_role: "{role}"
password: "secure_password_123"
universe_id: "universe_prod_001"
app_id: "{application_id}"
resource_id: "{resource_id}"
api_ip: "ra-service.swarm-system.svc.cluster.local"
api_port: 8080
p2p_public_ip: "{ra_ip}"
p2p_public_port: 5000
p2p_listen_ip: "127.0.0.1"
p2p_listen_port: 5000

"""

    lines = []
    lines.append("apiVersion: v1")
    lines.append("kind: ConfigMap")
    lines.append("metadata:")
    lines.append("  name: swarm-agent-config")
    lines.append("  namespace: swarm-system")
    lines.append("data:")

    # ✅ Leader
    if leader_name:
        filename = f"config-{leader_name}.yaml"
        sa_id = f"SA-{leader_name}"
        block = make_block(sa_id, "leader", leader_name)

        lines.append(f"  {filename}: |")
        for line in block.splitlines():
            lines.append(f"    {line}")

    # ✅ Workers
    for worker in workers:
        filename = f"config-{worker}.yaml"
        sa_id = f"SA-{worker}"
        block = make_block(sa_id, "worker", worker)

        lines.append(f"  {filename}: |")
        for line in block.splitlines():
            lines.append(f"    {line}")

    final_yaml = "\n".join(lines) + "\n"

    with open(output_file, "w") as f:
        f.write(final_yaml)

    print(f"✅ Correct block-style ConfigMap written to: {output_file}")
