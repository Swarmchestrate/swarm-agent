import os
import subprocess
import sys
import signal
import logging
from SA import SwarmAgent
from utility import setup_logging


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    print(f"\nReceived signal {signum}, shutting down...")
    global sa
    if sa:
        sa.stop()
    sys.exit(0)


def get_node_role():
    node_name = os.getenv("NODE_NAME")
    if not node_name:
        return "default"

    try:
        role = subprocess.check_output([
            "kubectl", "get", "node", node_name,
            "-o", "jsonpath={.metadata.labels.role}"
        ]).decode("utf-8").strip()
        return role or "default"
    except Exception as e:
        print(f"⚠️ Could not fetch node role: {e}")
        return "default"


def main():
    """Main entry point"""

    # Setup logging
    setup_logging("INFO")
    logger = logging.getLogger("Main")

    logger.info("Starting Swarm Agent Application")

    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    global sa
    sa = None

    try:
        # Get config file path from command line or use default
    # Read node role from env
      #  node_role = get_node_role()
        node_role = os.getenv("NODE_NAME")  # default fallback
        print(f"node role is {node_role}")

    # Build file paths based on role
        default_config = f"/config/config/config-{node_role}.yaml"
        default_tosca  = f"/config/tosca/tosca-{node_role}.yaml"

    # Allow overrides from command line
        config_path = sys.argv[1] if len(sys.argv) > 1 else default_config
        tosca_path = sys.argv[2] if len(sys.argv) > 2 else default_tosca

        print(f"✅ Using config: {config_path}")
        print(f"✅ Using tosca: {tosca_path}")



     # config_path = sys.argv[1] if len(sys.argv) > 1 else "./config.yaml"
      #  tosca_path = sys.argv[2] if len(sys.argv) > 2 else "./tosca.yaml"
        #config_path = sys.argv[1] if len(sys.argv) > 1 else "../config/config.yaml"

        # Create and start Swarm Agent
        sa = SwarmAgent(config_path=config_path, tosca_path=tosca_path)
        sa.start()

        # Keep the application running
        logger.info("Swarm Agent is running. Press Ctrl+C to stop.")

        # Simple main loop
        while sa.is_running:
            try:
                # Print status periodically
                status = sa.get_status()
                logger.info(f"Status: SA {status['sa_id']} ({status['role']}) - Running: {status['is_running']}")

                # Sleep for 30 seconds
                import time
                time.sleep(30)
                
            except KeyboardInterrupt:
                break
                
    except Exception as e:
        logger.error(f"Error in main: {e}")
        return 1
    
    finally:
        if sa:
            sa.stop()
        logger.info("Swarm Agent Application stopped")
    
    return 0


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

