from base64 import b64encode
import json, os
import sys

from kubernetes import client, config, utils
from kubernetes.client import ApiClient
import subprocess

import yaml
import logging
import asyncio
from typing import Dict, Any, Optional
from utility import load_configuration
from swchp2pcom import SwchPeer
import threading
from twisted.internet import reactor


#from sardou.manifestGenerator import get_kubernetes_manifest
from k3s_client.utils.manifest import get_kubernetes_manifest
#from k3s_client.api.applications import ApplicationManager
from ruamel.yaml import YAML
from io import StringIO
from pathlib import Path

# from tosca_to_k8s.converter import (
#     parse_tosca,
#     convert_node_to_deployment,
#     convert_node_to_service,
#     convert_node_to_pvcs,
#     convert_node_to_configmap,
# )

logger = logging.getLogger("SwarmAgent") 
def ensure_namespace(v1: client.CoreV1Api, ns: str):
    print("ensure_namespace_1")
    try:
        v1.read_namespace(ns)
    except client.exceptions.ApiException as e:
        if e.status == 404:
            v1.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(name=ns)))
        else:
            raise
    print("ensure_namespace_2")

def ensure_docker_registry_secret(v1: client.CoreV1Api, ns: str, name: str,
                                  server: str, username: str, password: str, email: str = "unused@example.com"):
    log = logger
    log.info("Ensuring image pull secret %s in ns %s (server=%s, user=%s)", name, ns, server, username)
    dockercfg = {
        "auths": {
            server: {
                "username": username,
                "password": password,
                "email": email,
                "auth": b64encode(f"{username}:{password}".encode()).decode(),
            }
        }
    }
    data = {".dockerconfigjson": b64encode(json.dumps(dockercfg).encode()).decode()}
    meta = client.V1ObjectMeta(name=name, namespace=ns)
    secret = client.V1Secret(
        api_version="v1",
        kind="Secret",
        metadata=meta,
        data=data,
        type="kubernetes.io/dockerconfigjson",
    )
    try:
        v1.create_namespaced_secret(ns, secret)
    except client.exceptions.ApiException as e:
        if e.status == 409:  # Already exists → replace
            v1.replace_namespaced_secret(name, ns, secret)
        else:
            raise
    print("ensure_docker_registry_secret_2")

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
        #self.tosca = load_configuration(tosca_path)
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

        # Latest monitoring data collected by the leader's monitoring loop
        # (inputs for the Optimiser; None until the first cycle completes)
        self.latest_monitoring = None
        self.latest_slo_violations = []
        # Latest pod->node mapping from the k3s-client lib (Optimiser input 3)
        self.latest_cluster_status = None
        # Reconfiguration rule + constants declared in the SAT (Sardou)
        self.latest_reconfiguration = {}
        # Which rule variables we can fill, and which are still missing
        self.rule_input_report = {}
        # Per cycle: the subset of metric values + constants each rule needs
        self.latest_rule_inputs = {}
        # Per cycle: what the Optimiser decided, translated to k3s-client calls
        self.latest_decision = {}
        # Per cycle: load per node, ordered to match the Optimiser's node numbers
        self.latest_node_load = None

        self.logger.info(f"SwarmAgent {self.sa_id} initialised with role: {self.sa_role}, SAT locates at {self.tosca_path}")

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
        # Ze-TODO: this requires further work to integrate with RA
        #self._initialise_p2p_network()

        #self.logger.info("P2P initialised, expecting sending resource request")

        # Step 3: Initialise SA with app TOSCA
        #self._process_app_TOSCA()
        print("[DEBUG] Now enter convert application tosca!")
        self.logger.info("[DEBUG] Now enter convert application tosca")
        self._convert_application_tosca_to_k3s()


        # Step 4: Deploy the monitoring stack from the same SAT (autonomous;
        # needs deployer RBAC on the swarm-agent service account). Best-effort.
        self._deploy_monitoring_stack()

        # Step 5: Deploy applications using the converted manifests
        self._deploy_application()

        # Step 6: Start collecting the SAT-declared metrics (monitoring lib)
        self._start_monitoring_loop()

    def _deploy_monitoring_stack(self):
        """
        Leader deploys the monitoring stack from the same SAT, so the whole flow
        (monitoring stack + application + metric subscription) runs autonomously.

        Requires the deployer RBAC on the swarm-agent service account. Idempotent
        (deploy_monitoring is create-or-patch), so restarts are safe. Best-effort:
        a failure here does NOT stop the SA — the monitoring loop keeps retrying
        once the broker is up.

        Controlled by env vars:
          SA_DEPLOY_MONITORING (default "true")  -> set to "false" to skip
          SA_MON_USE_KB        (default "false") -> deploy_monitoring use_kb mode
        """
        if os.getenv("SA_DEPLOY_MONITORING", "true").strip().lower() not in ("true", "1", "yes"):
            self.logger.info("[MonitoringDeploy] disabled (SA_DEPLOY_MONITORING); skipping stack deploy")
            return
        try:
            from swchmonclient import deploy_monitoring
            use_kb = os.getenv("SA_MON_USE_KB", "false").strip().lower() in ("true", "1", "yes")
            self.logger.info(
                f"[MonitoringDeploy] deploying monitoring stack from {self.tosca_path} (use_kb={use_kb})"
            )
            rc = deploy_monitoring(sat_file=self.tosca_path, use_kb=use_kb)
            if rc == 0:
                self.logger.info("[MonitoringDeploy] monitoring stack deployed successfully")
            else:
                self.logger.error(f"[MonitoringDeploy] deploy_monitoring returned {rc} (non-zero)")
        except Exception as e:
            self.logger.error(
                f"[MonitoringDeploy] failed: {e}; continuing — monitoring loop will retry once the broker is up"
            )

    def _run_optimiser(self, mode: str = "shadow"):
        """
        One decision cycle: hand the Optimiser this cycle's inputs and log what
        it wants done, translated back into k3s-client calls.

        In "shadow" mode nothing is executed - the decision is logged only. That
        keeps the loop safe to run while the rule content is still being agreed;
        an "auto" mode that carries the calls out is the next step.
        """
        from optimizer_interface import (
            actions_to_k3s_calls,
            describe_inputs,
            to_system_input,
        )
        from k3s_client_input import get_node_names
        from swch_optimiser import SwchOptimiser

        mapping = self.latest_cluster_status or {}
        if not mapping:
            return
        system, index = to_system_input(mapping, get_node_names())

        for policy, inputs in self.latest_rule_inputs.items():
            if not inputs["ready"]:
                continue                      # already warned about by the caller
            body = (self.latest_reconfiguration.get(policy) or {})

            opt = SwchOptimiser(body.get("rule", ""), mslist=sorted(mapping))
            if opt.get_error():
                self.logger.warning(
                    f"[Optimiser] rule '{policy}' could not be loaded: {opt.get_error()}"
                )
                continue

            opt.add_input_system(system)
            opt.add_input_constants(inputs["constants"])
            opt.add_input_metrics(inputs["metrics"])
            # Everything the Optimiser receives this cycle, in the three groups
            # its API takes them in. Logged in full so the inputs can be read
            # straight from the log, without re-running anything by hand.
            constants_shown = json.dumps(inputs["constants"])
            metrics_shown = json.dumps(inputs["metrics"])
            self.logger.info(f"[Optimiser] input 1/3 system:    {json.dumps(system)}")
            self.logger.info(f"[Optimiser] input 2/3 constants: {constants_shown}")
            self.logger.info(f"[Optimiser] input 3/3 metrics:   {metrics_shown}")
            opt.validate_inputs()
            result = opt.solve(time_limit_milliseconds=10000)

            shown = describe_inputs(inputs["metrics"])
            if result is None or result.solution is None:
                self.logger.warning(
                    f"[Optimiser] rule '{policy}': no solution ({shown}) - "
                    f"the rule cannot be satisfied with the current mapping"
                )
                continue

            calls = actions_to_k3s_calls(opt.generate_actions(), index)
            self.latest_decision[policy] = calls
            if not calls:
                self.logger.info(
                    f"[Optimiser] rule '{policy}': no change needed ({shown}, "
                    f"solved in {opt.time_taken()} ms)"
                )
                continue

            for c in calls:
                target = f"{c['method']}({c['kwargs']})" if c["method"] else c["description"]
                if mode == "shadow":
                    self.logger.info(
                        f"[Optimiser] rule '{policy}' decided: {target} "
                        f"({shown}) - NOT executed, shadow mode"
                    )
                else:
                    self.logger.info(f"[Optimiser] rule '{policy}' decided: {target} ({shown})")

    def _start_monitoring_loop(self, interval_seconds: int = 60):
        """
        1. identify the metrics to subscribe (from the SAT, via the Sardou lib)
        2. subscribe once
        3. poll at the slowest SAT collection_frequency (floor
           `interval_seconds`), so every metric has values in every poll;
           metric values are logged at DEBUG level
        4. evaluate the SAT slo-constraints on each snapshot
        Latest results are kept on self.latest_monitoring /
        self.latest_slo_violations as inputs for the Optimiser.
        """
        import time
        from monitoring_input import (
            get_monitoring_details,
            get_reconfiguration_details,
            microservice_names_from_details,
            metric_names_from_details,
            poll_interval_from_details,
            subscribe_metrics,
            poll_metrics,
            evaluate_slo,
        )
        from k3s_client_input import get_cluster_status

        def loop():
            # The SAT does not change at runtime: process it once and cache
            # names + slo details (also avoids concurrent Sardou cache races).
            cached_names = None
            cached_details = None
            cached_microservices = None
            subscribed = False
            
            poll_seconds = interval_seconds
            while self.is_running:
                try:
                    if cached_names is None:
                        cached_details = get_monitoring_details(self.tosca_path)
                        names = metric_names_from_details(cached_details)
                        if not names:
                            self.logger.warning(
                                "[MonitoringLoop] SAT declares no metrics; retrying next cycle"
                            )
                            time.sleep(poll_seconds)
                            continue
                        cached_names = names
                        poll_seconds = poll_interval_from_details(
                            cached_details, floor_seconds=interval_seconds
                        )
                        cached_microservices = microservice_names_from_details(cached_details)
                        self.logger.info(f"[MonitoringLoop] metrics from SAT: {cached_names}")
                        self.logger.info(f"[MonitoringLoop] poll interval {poll_seconds}s")
                        self.logger.info(
                            f"[MonitoringLoop] application microservice(s) from SAT: "
                            f"{sorted(cached_microservices)}"
                        )

                        # Optimiser inputs from the SAT: the reconfiguration rule
                        # and its constants (Sardou get_reconfiguration).
                        try:
                            self.latest_reconfiguration = get_reconfiguration_details(self.tosca_path)
                        except Exception as e:
                            self.logger.warning(f"[MonitoringLoop] reconfiguration unavailable: {e}")
                            self.latest_reconfiguration = {}
                        if self.latest_reconfiguration:
                            for policy, body in self.latest_reconfiguration.items():
                                rule = body.get("rule") or ""
                                consts = body.get("constants") or {}
                                self.logger.info(
                                    f"[MonitoringLoop] reconfiguration '{policy}': "
                                    f"rule {len(rule)} char(s), {len(consts)} constant(s) "
                                    f"{sorted(consts)}; targets {body.get('targets', [])}"
                                )

                            # Ask the Optimiser which variables the rule refers to,
                            # and check we can fill every one of them: the Optimiser
                            # cannot calculate while a variable has no value.
                            try:
                                from optimizer_interface import check_rule_inputs
                                from monitoring_input import (
                                    NODE_LOAD_SOURCE,
                                    subscribe_node_metric,
                                )

                                # Per-node load is not one of the SAT's declared
                                # metrics - it is derived from a raw metric that
                                # keeps its per-node origin (see monitoring_input),
                                # so the rule can reason about individual machines.
                                node_metric_names = []
                                try:
                                    subscribe_node_metric(NODE_LOAD_SOURCE)
                                    node_metric_names = ["node_load"]
                                except Exception as e:
                                    self.logger.warning(
                                        f"[MonitoringLoop] per-node load unavailable "
                                        f"({e}); rules referring to node_load cannot run"
                                    )

                                self.rule_input_report = check_rule_inputs(
                                    self.latest_reconfiguration,
                                    cached_names,
                                    node_metric_names=node_metric_names,
                                )
                                for policy, rep in self.rule_input_report.items():
                                    filled = ", ".join(
                                        f"{n}={src}" for n, src in sorted(rep["sources"].items())
                                    ) or "none"
                                    missing = rep["missing"]
                                    self.logger.info(
                                        f"[MonitoringLoop] rule '{policy}' needs "
                                        f"{len(rep['sources']) + len(missing)} input(s): {filled}"
                                    )
                                    if missing:
                                        self.logger.warning(
                                            f"[MonitoringLoop] rule '{policy}' has unfilled "
                                            f"variable(s): {missing} - the Optimiser cannot run "
                                            f"until these have values"
                                        )
                            except Exception as e:
                                self.logger.warning(
                                    f"[MonitoringLoop] could not query the Optimiser for the "
                                    f"rule's variables: {e}"
                                )
                        else:
                            self.logger.info(
                                "[MonitoringLoop] SAT declares no reconfiguration policy"
                            )

                    if not subscribed:
                        subscribe_metrics(cached_names)
                        subscribed = True
                        self.logger.info(
                            f"[MonitoringLoop] subscribed to {len(cached_names)} metric(s); "
                            f"polling every {poll_seconds}s"
                        )

                    time.sleep(poll_seconds)
                    snapshot = poll_metrics(cached_names)
                    envelope = {"source": "monitoring", "mode": "standard", "metrics": snapshot}
                    violations = evaluate_slo(envelope, cached_details)
                    self.latest_monitoring = envelope
                    self.latest_slo_violations = violations

                    # Optimiser input 3: refresh the pod->node mapping (k3s-client
                    # lib). Best-effort — cluster status must never break monitoring.
                    try:
                        self.latest_cluster_status = get_cluster_status(
                            microservices=cached_microservices
                        )
                    except Exception as e:
                        self.logger.warning(f"[MonitoringLoop] cluster status unavailable: {e}")

                    # Optimiser inputs for this cycle: the subset of metrics each
                    # rule refers to, plus its constants, ready to hand over.
                    if self.rule_input_report:
                        try:
                            from optimizer_interface import (
                                build_rule_inputs,
                                describe_inputs,
                                node_load_array,
                            )

                            # Load per node, in the same order as the node numbers
                            # the Optimiser sees. None means at least one node
                            # reported nothing, and a short array would renumber
                            # the nodes - so no value is passed at all.
                            self.latest_node_load = None
                            try:
                                from k3s_client_input import get_node_ips, get_node_names
                                from monitoring_input import node_loads

                                self.latest_node_load = node_load_array(
                                    node_loads(), get_node_names(), get_node_ips()
                                )
                                if self.latest_node_load is None:
                                    self.logger.warning(
                                        "[MonitoringLoop] per-node load incomplete this "
                                        "cycle - not every node reported a value"
                                    )
                            except Exception as e:
                                self.logger.warning(
                                    f"[MonitoringLoop] per-node load unavailable: {e}"
                                )

                            self.latest_rule_inputs = build_rule_inputs(
                                self.latest_reconfiguration,
                                self.rule_input_report,
                                envelope,
                                node_metrics=(
                                    {"node_load": self.latest_node_load}
                                    if self.latest_node_load else None
                                ),
                            )
                            for policy, inputs in self.latest_rule_inputs.items():
                                if inputs["ready"]:
                                    shown = describe_inputs(
                                        {**inputs["metrics"], **inputs["constants"]}
                                    )
                                    self.logger.info(
                                        f"[MonitoringLoop] rule '{policy}' inputs ready: {shown}"
                                    )
                                else:
                                    self.logger.warning(
                                        f"[MonitoringLoop] rule '{policy}' not ready: no value "
                                        f"this cycle for {inputs['unavailable']}"
                                    )
                        except Exception as e:
                            self.logger.warning(
                                f"[MonitoringLoop] could not build the rule inputs: {e}"
                            )

                    # Ask the Optimiser what to do with this cycle's inputs.
                    # SA_RECONF_MODE: "shadow" (default) decides and logs but
                    # changes nothing; "off" skips it entirely.
                    mode = os.getenv("SA_RECONF_MODE", "shadow").strip().lower()
                    if mode != "off" and self.latest_rule_inputs:
                        try:
                            self._run_optimiser(mode)
                        except Exception as e:
                            self.logger.warning(f"[Optimiser] cycle skipped: {e}")

                    total = sum(len(v) for v in snapshot.values())
                    missing = [m for m in cached_names if not snapshot.get(m)]
                    violated = [v["name"] for v in violations if v["violated"]]
                    self.logger.info(
                        f"[MonitoringLoop] poll done: {total} value(s); "
                        f"missing: {missing if missing else 'none'}; "
                        f"SLO violated: {violated if violated else 'none'}"
                    )
                except Exception as e:
                    self.logger.error(f"[MonitoringLoop] cycle failed: {e}; will resubscribe")
                    subscribed = False
                    time.sleep(poll_seconds)

        threading.Thread(target=loop, name="sa-monitoring", daemon=True).start()
        self.logger.info("[MonitoringLoop] started (SAT-driven metric collection)")

    def _start_as_worker(self):
        """Start as Worker Swarm Agent"""
        self.logger.info("Starting as Worker Swarm Agent (SA)")

        # Step 2: Join P2P network
        #self._initialise_p2p_network()

        # Step 3: Translate TOSCA into K3s applications
        #self._convert_application_tosca_to_k3s()

        # Step 5: Deploy applications using the converted manifests
        #self._deploy_application()

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
        print("[DEBUG] Now inside convert application tosca")
        self.logger.info("Converting Tosca into k3s manifests.")
        #tpl = parse_tosca(self.tosca_path)
        yaml_parser = YAML()
        yaml_parser.default_flow_style = False

        TOSCA_FILE = self.tosca_path
        OUTPUT_FILE = "application-manifest.yaml"
        IMAGE_PULL_SECRET = "regcred"

        path = Path(TOSCA_FILE)
        if not path.exists():
            sys.exit(f"Error: TOSCA file '{TOSCA_FILE}' not found.")

        try:
            with open(path, "r") as f:
                tosca_yaml = f.read()
            
            #manifests = get_kubernetes_manifest(tosca_yaml)
            self.logger.info("Calling get_k8s_manifest function")
            # k3s_client function:
            manifests = get_kubernetes_manifest(tosca_file=TOSCA_FILE, image_pull_secret=IMAGE_PULL_SECRET)
            #manifests = get_kubernetes_manifest(tosca_yaml, image_pull_secret=IMAGE_PULL_SECRET)
            
            if not manifests:
                self.logger.info("No Manifests!")
                sys.exit("Warning: No Kubernetes manifests generated.")
            self.logger.info(" Manifest is there, now dump the output!")
            with open(OUTPUT_FILE, "w") as f:
                self.logger.info("Manifests have been translated! We now dump manifests into {OUTPUT_FILE}")
                yaml_parser.dump_all(manifests, f)
        except Exception as e:
            sys.exit(f"Error: {e}")

        self.logger.info("✅ Kubernetes manifests written to '{OUTPUT_FILE}' ({len(manifests)} items)")

    def _deploy_application(self):
        """Step 5/6: Initialise application by loading TOSCA and deploying resources"""
        self.logger.info(f"Initialising application {self.app_id}")
        #self.logger.info(f"Loading TOSCA for resource {self.resource_id}")

        try:
            config.load_incluster_config()
            k8s_client = ApiClient()
            v1 = client.CoreV1Api(k8s_client)

            #folder = "k3s"
            namespace = "default"   # <-- use the namespace you want
            ensure_namespace(v1, namespace)
        # Create/refresh the regcred secret first (equivalent to your kubectl command)
           
            folder = "./"
            for fname in os.listdir(folder):
                if not fname.endswith(".yaml"):
                    continue
                fpath = os.path.join(folder, fname)

                self.logger.info(f"Applying {fpath}")
                # Prefer the k3s-client lib: apply_manifest is create-or-patch,
                # AlreadyExists. Falls back to the direct apply below if the
                # lib call fails for any reason.
                try:
                    from k3s_client_input import get_application_manager
                    get_application_manager().apply_manifest(fpath)
                    self.logger.info(f"[AppDeploy] applied {fpath} via k3s-client lib")
                    continue
                except Exception as e:
                    self.logger.warning(
                        f"[AppDeploy] k3s-client apply failed for {fpath}: {e}; "
                        f"falling back to direct apply"
                    )
                try:
                    # Can apply multi-doc yaml (--- separators)
                    utils.create_from_yaml(k8s_client, fpath, namespace="default")
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



