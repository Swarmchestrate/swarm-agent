# Swarmchestrate - Swarm Agent

This repository contains the implementation of the swarm agents (SA).
As a user, you do not need to worry about setting up SA, as the resource agent prepares everything required and launches the swarm agents.
This README file is intended only to help you understand the system’s purpose, setup, and workflow.

## Setup

An SA will be deployed as a DaemonSet running on each node of the k3s cluster.

Each SA takes two ConfigMaps as inputs, i.e., config.yaml, and tosca.yaml.
The config.yaml defines SA-specific data for its initialisation.
The tosca.yaml stores application's tosca file. This is identical for all SAs.

These configuration files are prepared by the resource agent; therefore, users do not need to worry about them.

<!--
//To configure the SA correctly, modify the config.json file inside the scripts folder. 


//The config.json contains the P2P IP, P2P port, and the names of the k3s cluster’s nodes. Enter these values according to your own setup.

//After that, you can run build-and-deploy.sh, which will build a swarm-agent image that matches your platform and deploy the SA by applying the k3s manifests in the k3s folder.




//###### LSA implementation

//### Step1: deployment
//(Done) LSA is a python3 implementation which will be deployed as a Daemonset inside a single node of k3s cluster. The first SA is deployed as LSA.
//(Done) After the deployment, it first loads the configuration file defined in the config/config.yaml, and then the ADT defined in config/tosca.yaml.

//### Step2: p2p network initialisation
//(Done) With the configuration file loaded, LSA knows the p2p network ip and port, it then joins in it.

//### Step3: tosca translation
//(Done) It uses tosca library to convert application's tosca file into k3s manitests.
////This is done by tosca_converter library: https://github.com/ZeWang42/tosca_converter.git

////(TODO) Version 2: It iterates the TOSCA node templates defined in ADT and converts them into either resource requests or k3s manifests accordingly.
////The converson will be done by the scripts provided in the node template interface section.

////### Step4: request for resources (This function has been removed)
////(TODO) LSA initialises required resource one by one. This will be done by communicating with corresponding RA through the p2p network.

//### Step4: deploys k3s manifests of MicroSVC
//(Done) LSA deploys k3s manifests of microservices that are assigned on its node.

//###### 
-->


## Workflow

### Step1: deployment
(Done) SA is deployed as a Daemonset inside a freshly initialised k3s node.
(Done) After the deployment, it first loads the configuration file defined in the config/config.yaml, and then the ADT defined in config/tosca.yaml.

### Step2: p2p network initialisation
(Done) With the configuration file loaded, SA knows the p2p network ip and port, it then joins in it.


### Step3: tosca translation
(Done) It uses tosca library to convert application's tosca file into k3s manitests.


### Step4: deploys k3s manifests of MicroSVC
(Done) SA deploys k3s manifests of microservices that are assigned on its node.

###### 
