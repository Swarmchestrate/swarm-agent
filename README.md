# Swarmchestrate - Swarm Agent

This repository contains the implementation of the Swarm Agent (SA), a core component of the Swarmchestrate platform.

In a typical Swarmchestrate deployment, users do not need to interact directly with the SA. The Resource Agent (RA) automatically prepares the required configuration files and deploys the SA to the target Kubernetes cluster.

This document provides an overview of the SA architecture, workflow, and standalone deployment procedure.

---

## Overview

The Swarm Agent is deployed as a Kubernetes DaemonSet, ensuring that one instance runs on every node of a K3s cluster.

Each SA instance is initialized using two ConfigMaps:

* **config.yaml** – contains SA-specific configuration parameters.
* **tosca.yaml** – contains the application's Swarm Application Template (SAT) written in TOSCA.

In a standard Swarmchestrate workflow, these ConfigMaps are generated automatically by the Resource Agent.

---

## Feature Status

### Supported Features

* Translation of application TOSCA templates into Kubernetes manifests
* Deployment of generated Kubernetes manifests
* Distributed deployment through Kubernetes DaemonSets

### Current Limitations

#### Runtime Reconfiguration

The following capabilities are not yet supported:

* Pod-level scaling
* VM-level scaling
* Pod migration

---

## Workflow

### Step 1: Deployment

The Swarm Agent is deployed as a Kubernetes DaemonSet in a K3s cluster.

Upon startup, each SA instance loads:

* `config/config.yaml`
* `config/tosca.yaml`

These files provide the runtime configuration and application description required for deployment.

### Step 2: TOSCA Translation

The SA translates the application's SAT (Swarm Application Template) into Kubernetes manifests using the TOSCA translation framework.

### Step 3: Application Deployment

The SA deploys the generated Kubernetes manifests corresponding to the microservices assigned to its node.

---

# Standalone Mode Quick Start

The Swarm Agent can also be executed as a standalone component without a Resource Agent.

In standalone mode, the SA can translate and deploy a SAT directly onto a Kubernetes cluster.

Since the SA is deployed as a Kubernetes DaemonSet, you must prepare the required deployment manifests before deployment.

---

## Prerequisites

* A running Kubernetes or K3s cluster
* Swarm Agent deployment manifests
* Access to `kubectl`

---

## Install K3s

> **Standalone mode only.** In a standard Swarmchestrate deployment the Resource Agent provisions the cluster automatically.

Installs K3s on a pre-provisioned node and registers it with the Swarmchestrate node label.

```bash
# Master
sudo ./scripts/install-k3s.sh --role master --node-name my-master --cluster-name my-cluster

# Worker (use token and IP printed by the master)
sudo ./scripts/install-k3s.sh --role worker --node-name my-worker --cluster-name my-cluster \
  --token <token> --master-ip <master-ip>
```

Optional flags: `--k3s-version`, `--flannel-iface`, `--node-ip`, `--tls-san`, `--extra-labels`, `--dry-run`.

---

## Build and Push the Swarm Agent Image

The provided build script creates a multi-architecture Docker image supporting both AMD64 and ARM64 platforms.

From the repository root:

```bash
cd scripts
./build-and-push.sh
```

The image is pushed to the configured container registry and can be used on heterogeneous Kubernetes clusters.

---

## Create Registry Secrets

> **Standalone mode only.** In a standard Swarmchestrate deployment registry credentials are managed by the Resource Agent.

Creates Kubernetes `docker-registry` secrets on the master node. Run after K3s is installed.

```bash
# Via config file (recommended)
sudo ./scripts/create-registry-secrets.sh --config registry-config.yaml

# Via CLI flags
sudo ./scripts/create-registry-secrets.sh \
  --registry docker.io --username myuser --password mypassword --secret-name regcred-dockerhub
```

`registry-config.yaml` format:

```yaml
namespace: default
registries:
  - registry: docker.io
    username: myuser
    password: mypassword
    secret_name: regcred-dockerhub  # optional, defaults to regcred-0, regcred-1...
```

Optional flags: `--namespace`, `--dry-run`.

---

## Generate Deployment Manifests

Before deploying the SA, generate the required ConfigMaps and deployment manifests.

The generation script requires:

* A unique application identifier (`job_id`)
* The path to the SAT/TOSCA file
* The Hub RA IP address (optional, defaults to localhost)
* The Kubernetes leader node name (optional, defaults to `master`)

Example:

```bash
cd scripts

python3 generate-configMaps.py \
  --job-id stressng \
  --tosca-path ../KB/stressng_tosca.yaml \
  --hub-ra-ip localhost \
  --leader master
```
One can also edit and run the run-generate-configMaps.sh to achieve the above step. 

The script automatically:

1. Reads the Kubernetes node names from the cluster.
2. Generates the Swarm Agent configuration.
3. Creates the TOSCA ConfigMap.
4. Copies the base Kubernetes deployment manifests.

Generated files are placed in:

```bash
output/cluster_<job_id>/
```

Example:

```bash
output/cluster_stressng/
```

Contents:

```text
00-namespace-swarm-system.yaml
01-rbac-swarm-agent.yaml
02-daemonset-swarm-agent.yaml
03-configmap-swarm-agent-tosca.yaml
04-configmap-swarm-agent-config.yaml
```

---

## Deploy the Swarm Agent

Apply the generated manifests:

```bash
kubectl apply -f output/cluster_stressng/
```


---

## Verify Deployment

Verify that the Swarm Agents are running:

```bash
kubectl get pods -n swarm-system -o wide
```

Expected output:

```text
swarm-agent-xxxxx   1/1   Running
```

View logs:

```bash
kubectl logs -n swarm-system -l app=swarm-agent -f
```

---

## Verify Application Deployment

Once the Swarm Agents have started, they automatically translate and deploy the SAT.

List deployed workloads:

```bash
kubectl get pods -A
```

For the stress-ng example:

```bash
kubectl get pods -l app=stressng -o wide
```

Inspect logs:

```bash
kubectl logs -l app=stressng
```

---

## Notes

### Kubernetes Node Discovery

The generated Swarm configuration uses the Kubernetes node names obtained from:

```bash
kubectl get nodes
```

Example:

```text
master
worker-1
worker-2
worker-3
worker-4
```

### SAT Input

The generated TOSCA ConfigMap is created from the SAT specified via:

```bash
--tosca-path
```

### Hub RA IP

The Hub RA IP is configured through:

```bash
--hub-ra-ip
```

When running in standalone mode without an external Resource Agent, `localhost` can be used.
