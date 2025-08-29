# Swarmchestrate - Swarm Agent

This is the repo for the implementation of swarm agents (LSA and SA).

###### LSA implementation

### Step1: deployment
(Done) LSA is a python3 implementation which will be deployed as a Daemonset inside a single node of k3s cluster. The first SA is deployed as LSA.
(Done) After the deployment, it first loads the configuration file defined in the config/config.yaml, and then the ADT defined in config/tosca.yaml.

### Step2: p2p network initialisation
(Done) With the configuration file loaded, LSA knows the p2p network ip and port, it then joins in it.

### Step3: tosca translation
(Done) Version 1: It iterates the TOSCA node templates defined in ADT and converts them into either resource requests or k3s manifests accordingly.
This is done by tosca_converter library: https://github.com/ZeWang42/tosca_converter.git

(TODO) Version 2: It iterates the TOSCA node templates defined in ADT and converts them into either resource requests or k3s manifests accordingly.
The converson will be done by the scripts provided in the node template interface section.

### Step4: request for resources
(TODO) LSA initialises required resource one by one. This will be done by communicating with corresponding RA through the p2p network.

### Step5: deploys k3s manifests of MicroSVC
(Done) LSA deploys k3s manifests of microservices that are assigned on its node.

###### 



###### SA implementation

### Step1: deployment
(Done) SA is deployed as a Daemonset inside a freshly initialised k3s node.
(Done) After the deployment, it first loads the configuration file defined in the config/config.yaml, and then the ADT defined in config/tosca.yaml.

### Step2: p2p network initialisation
(Done) With the configuration file loaded, SA knows the p2p network ip and port, it then joins in it.

### Step5: deploys k3s manifests of MicroSVC
(Done) SA deploys k3s manifests of microservices that are assigned on its node.

###### 
