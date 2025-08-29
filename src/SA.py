import os
from kubernetes import client, config, utils
from kubernetes.client import ApiClient
import subprocess
from pathlib import Path
import yaml
import logging
import asyncio
from typing import Dict, Any, Optional
from utility import load_configuration
from swchp2pcom import SwchPeer
import threading
from twisted.internet import reactor
from tosca_to_k8s.converter import (
    parse_tosca,
    convert_node_to_deployment,
    convert_node_to_service,
    convert_node_to_pvcs,
    convert_node_to_configmap,
)
class SwarmAgent:
    """
    Swarm Agent implementation
    """

    def __init__(self, config_path: str = "config.yaml", tosca_path: str = "tosca.yaml"):
        """
        Initialise Swarm Agent

        Args:
            config_path: Path to configuration file
        """
        self.logger = logging.getLogger("SwarmAgent")
        self.config: Optional[Dict[str, Any]] = None
        self.is_running = False
        self.p2p_agent: Optional[SwchPeer] = None

        # Load configuration
        self.config = load_configuration(config_path)
        if not self.config:
            raise ValueError("Failed to load configuration")
        self.tosca = load_configuration(tosca_path)
        self.tosca_path = tosca_path
        # Extract configuration values
        self.sa_id = self.config['SA_id']
        self.password = self.config['password']
        self.universe_id = self.config['universe_id']
        self.api_ip = self.config['api_ip']
        self.api_port = self.config['api_port']
        self.p2p_public_ip = self.config['p2p_public_ip']
        self.p2p_public_port = self.config['p2p_public_port']
        self.p2p_listen_ip = self.config['p2p_listen_ip']
        self.p2p_listen_port = self.config['p2p_listen_port']
        self.app_id = self.config['app_id']
        self.resource_id = self.config['resource_id']
        self.sa_role = self.config['SA_role']

        self.logger.info(f"SwarmAgent {self.sa_id} initialised with role: {self.sa_role}")

    def start(self):
        """
        Start the Swarm Agent
        """
        try:
            self.logger.info(f"Starting Swarm Agent {self.sa_id}")
            self.is_running = True

            # Print configuration for verification
            self._print_config()

            # Initialise based on role
            if self.sa_role.lower() == 'leader':
                self._start_as_leader()
            else:
                self._start_as_worker()

        except Exception as e:
            self.logger.error(f"Error starting Swarm Agent: {e}")
            self.is_running = False
            raise

    def _print_config(self):
        """Print current configuration (excluding sensitive data)"""
        self.logger.info("=== Swarm Agent Configuration ===")
        self.logger.info(f"SA ID: {self.sa_id}")
        self.logger.info(f"Universe ID: {self.universe_id}")
        self.logger.info(f"API Endpoint: {self.api_ip}:{self.api_port}")
        self.logger.info(f"P2P Public: {self.p2p_public_ip}:{self.p2p_public_port}")
        self.logger.info(f"P2P Listen: {self.p2p_listen_ip}:{self.p2p_listen_port}")
        self.logger.info(f"Application ID: {self.app_id}")
        self.logger.info(f"Resource ID: {self.resource_id}")
        self.logger.info(f"Role: {self.sa_role}")
        self.logger.info("================================")

    def _start_as_leader(self):
        """Start as Lead Swarm Agent (LSA)"""
        self.logger.info("Starting as Lead Swarm Agent (LSA)")

 
        # Step 2: Initialise P2P network and wait for agents
        self._initialise_p2p_network()

        self.logger.info("P2P initialised, expecting sending resource request")

        # Step 3: Initialise SA with app TOSCA
        self._process_app_TOSCA()
        self._convert_application_tosca_to_k3s()

        # Step 4: Request VM, k3s, SA cluster initialisation.
        # This is critical since it requests precise information parsing
        self._resource_request()

        # Step test: Broadcast welcome messages to SAs for testing
        self._broadcast_tosca()
       
        # Step 5: Deploy applications using the converted manifests
        self._deploy_application()

    def _start_as_worker(self):
        """Start as Worker Swarm Agent"""
        self.logger.info("Starting as Worker Swarm Agent 111111111111111")

        # Step 2: Join P2P network
        self._initialise_p2p_network()

        # Step 3: Translate TOSCA into K3s applications
        self._convert_application_tosca_to_k3s()

        # Step 5: Deploy applications using the converted manifests
        self._deploy_application()

    def _process_app_TOSCA(self):
        """Step 1:  Initialise connection to RA API servers"""
        self.logger.info(f"Initialising API connection to {self.api_ip}:{self.api_port}")
        # TODO: Implement actual API connection
        self.logger.info("API connection initialised")

    def _initialise_p2p_network(self):
        """Step 2: Setup P2P network metadata, MSG handler, and Join the network"""
        self.logger.info(f"Setting up P2P network on {self.p2p_listen_ip}:{self.p2p_listen_port}")
        try:
            self.p2p_agent = SwchPeer(
                    peer_id=self.sa_id,
                    listen_ip=self.p2p_listen_ip,  # Listen on all interfaces
                    listen_port=self.p2p_listen_port,
                    public_ip=self.p2p_public_ip,  # Listen on all interfaces
                    public_port=self.p2p_public_port,
                    metadata={
                        "peer_type": self.sa_role,
                        "appid": self.app_id
                        }
                    )

            # Register event callbacks
            #self.p2p_agent.on("peer:connected", self._on_peer_connected)
            #self.p2p_agent.on("peer:disconnected", self._on_peer_disconnected)

            self.logger.info(f"P2P agent initialised on port {self.p2p_listen_ip}:{self.p2p_listen_port}")

        except Exception as e:
            self.logger.error(f"Failed to initialise P2P agent: {str(e)}")
            raise

        # Register core message handlers
        def _on_getstate(peer_id, message):
            logging.info(f"Sending state for application: {message['appid']}")
            self.p2p_agent.send(peer_id, "MSG_STATE", {"appid": message['appid'], "state": "running"})
            return
        self.p2p_agent.register_message_handler("MSG_GETSTATE", _on_getstate)

        def _on_resource_response(peer_id, message):
            logging.info(f"Resource response arrived from RA: {peer_id}, for application: {message['appid']}")
            return
        self.p2p_agent.register_message_handler("MSG_RESOURCE_RESPONSE", _on_resource_response)


        if self.sa_role.lower() == 'leader':
            # self._bootstrap_network()
            Truth = self._join_p2p_network()
            self.logger.info(f"LSA joined P2P network {Truth}")
            connected = self.p2p_agent.get_connected_peers()
            self.logger.info(f"Connected to {len(connected)} peers")
        else:
            self._join_p2p_network()
            self.logger.info(f"SA {self.sa_id} joined P2P network")
        return

    def _start_reactor_bg(self):
        """Run Twisted reactor in a background thread."""
        def run_reactor():
            reactor.run(installSignalHandlers=False)
        threading.Thread(target=run_reactor, name="twisted-reactor", daemon=True).start()

    def _join_p2p_network(self):
        self.logger.info(f"Try joining on {self.p2p_public_ip}:{self.p2p_public_port}")

        # Start Twisted reactor in background
        self._start_reactor_bg()

        join_done = threading.Event()
        join_success = [False]

        # Ensure join happens inside reactor's thread
        def join_on_reactor():
            deferred = self.p2p_agent.enter(self.p2p_public_ip, self.p2p_public_port)

            #def on_join_success(protocol):
            def on_join_success(_):
                self.logger.info("Joined P2P network successfully")
            # Start listening/servicing inside reactor thread
                #self.p2p_agent.start()
                join_success[0] = True
                join_done.set()

            def on_join_failure(f):
                self.logger.error(f"Join failed: {getattr(f, 'getErrorMessage', lambda: f)()}")
                join_success[0] = False
                join_done.set()

            deferred.addCallback(on_join_success)
            deferred.addErrback(on_join_failure)

        reactor.callFromThread(join_on_reactor)
        join_done.wait()
        return join_success[0]

    def _resource_request(self):
        """
        Send resource initialisation requests to all needed resources' RAs.
           This should initialise:
           cluster of VMs;
           cluster of k3s;
           cluster of SAs.
        """
        try:
            self.logger.info("Start sending resource intialisation request...")
            #sa_id=com.findPeers({"appid":args.getstate, "peer_type":"leader"})
            # No need to join - we're the first node
            self.p2p_agent.send("wmin.ac.uk", "MSG_RESOURCE_REQUEST", {"cpu": "2"})
            self.logger.info("Resource request send successfully!")
        except Exception as e:
            self.logger.error(f"Sending resource request failed: {str(e)}")
            raise

    def _handle_broadcast(self):
        """Broadcast handler (test)"""
        self.logger.info("!!! BROADCAST TEST SUCCESSFUL !!!")

    def _broadcast_tosca(self):
        """Step 4: broadcast tosca to SAs"""
        self.logger.info("Broadcasting app TOSCA to SAs through P2P network")
        # TODO: Implement TOSCA broadcasting using P2P
        self.logger.info("TOSCA broadcasted")

    def _convert_application_tosca_to_k3s(self):
        self.logger.info("Converting Tosca into k8s manifests.")
        tpl = parse_tosca(self.tosca_path)
        #tpl = parse_tosca("/config/tosca.yaml")
        
        outdir = Path("k3s")
        outdir.mkdir(exist_ok=True)
        for node in tpl.nodetemplates:
            dep = convert_node_to_deployment(node, namespace="swarm-system")
            if dep:
                print("---\n" + yaml.safe_dump(dep))
                filename = outdir / f"Deployment-{node.name.lower()}.yaml"
                with open(filename, "w") as f:
                    yaml.safe_dump(dep, f)
                print(f"Saved {filename}")

            svc = convert_node_to_service(node, namespace="demo")
            if svc:
                print("---\n" + yaml.safe_dump(svc))

            for pvc in convert_node_to_pvcs(node, namespace="demo"):
                print("---\n" + yaml.safe_dump(pvc))

            cm = convert_node_to_configmap(node, namespace="demo")
            if cm:
                print("---\n" + yaml.safe_dump(cm))

    def _deploy_application(self):
        """Step 5/6: Initialise application by loading TOSCA and deploying resources"""
        self.logger.info(f"Initialising application {self.app_id}")
        self.logger.info(f"Loading TOSCA for resource {self.resource_id}")

        try:
            # Load in-cluster config (uses ServiceAccount mounted in pod)
            config.load_incluster_config()
            k8s_client = ApiClient()

            folder = "k3s"
            for fname in os.listdir(folder):
                if not fname.endswith(".yaml"):
                    continue
                fpath = os.path.join(folder, fname)

                self.logger.info(f"Applying {fpath}")
                try:
                    # Can apply multi-doc yaml (--- separators)
                    utils.create_from_yaml(k8s_client, fpath, namespace="demo")
                except Exception as e:
                    self.logger.error(f"Failed applying {fpath}: {e}")

            self.logger.info("Application initialised")

        except Exception as e:
            self.logger.error(f"Error starting Swarm Agent: {e}")


    def _wait_for_tosca(self):
        """Step SA-5: Wait for TOSCA broadcast from LSA"""
        self.logger.info("Waiting for TOSCA broadcast from LSA")
        # TODO: Implement TOSCA reception
        self.logger.info("TOSCA received")

    def stop(self):
        """Stop the Swarm Agent"""
        self.logger.info("Stopping Swarm Agent")
        self.is_running = False

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the Swarm Agent"""
        return {
                'sa_id': self.sa_id,
                'role': self.sa_role,
                'is_running': self.is_running,
                'universe_id': self.universe_id,
                'app_id': self.app_id,
                'resource_id': self.resource_id
                }



