# utility.py

import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional


def load_configuration(config_path: str = "config.yaml") -> Optional[Dict[str, Any]]:
    """
    Load configuration from YAML file
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Dictionary containing configuration or None if failed
    """
    try:
        config_file = Path(config_path)
        
        if not config_file.exists():
            logging.error(f"Configuration file not found: {config_path}")
            return None
            
        with open(config_file, 'r') as file:
            config = yaml.safe_load(file)
#            print("Loaded configuration:", config)

        # Validate required fields
        required_fields = [
            'SA_id', 
            'password', 
            'universe_id', 
            'api_ip', 
            'api_port', 
            'p2p_public_ip', 
            'p2p_listen_ip', 
            'p2p_public_port', 
            'p2p_listen_port',
            'app_id', 
            'resource_id', 
            'SA_role'
        ]
        
        missing_fields = []
        for field in required_fields:
            if field not in config:
                missing_fields.append(field)
                
        if missing_fields:
            logging.error(f"Missing required fields in config: {missing_fields}")
            return None
            
        logging.info(f"Configuration loaded successfully from {config_path}")
        return config
        
    except yaml.YAMLError as e:
        logging.error(f"Error parsing YAML file: {e}")
        return None
    except Exception as e:
        logging.error(f"Error loading configuration: {e}")
        return None


def setup_logging(log_level: str = "INFO") -> None:
    """
    Setup logging configuration
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
    """
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler('swarm_agent.log')
        ]
    )

