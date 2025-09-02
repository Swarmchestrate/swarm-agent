#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def read_text(path: Path) -> str:
    with path.open("r", encoding="utf-8") as f:
        return f.read()

def write_text_with_backup(path: Path, content: str):
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        path.replace(backup)
    with path.open("w", encoding="utf-8", newline="") as f:
        f.write(content)

def try_update_json_p2p_ip(text: str, new_value: str):
    """If text is JSON and has 'p2p_public_ip', update and return new JSON text; else return None."""
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if "p2p_public_ip" in obj:
        obj["p2p_public_ip"] = new_value
        # Keep it readable; you can tweak indent/separators if needed
        return json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    return None

def regex_replace_p2p_ip(text: str, new_value: str):
    """
    Replace common forms of assigning p2p_public_ip across YAML/ENV/INI-like files.
    Always wraps the new value in double quotes.
    """
    quoted_value = f"\"{new_value}\""
    replaced = False
    patterns = [
        # JSON with quotes
        (r'("p2p_public_ip"\s*:\s*)"(?:[^"\\]|\\.)*"', r'\1' + quoted_value),
        # YAML with or without quotes
        (r'(\bp2p_public_ip\s*:\s*)(?!#).*$',
         lambda m: m.group(1) + quoted_value),
        # .env lowercase
        (r'(\bp2p_public_ip\s*=\s*)(?!#).*$',
         lambda m: m.group(1) + quoted_value),
        # .env uppercase
        (r'(\bP2P_PUBLIC_IP\s*=\s*)(?!#).*$',
         lambda m: m.group(1) + quoted_value),
    ]

    new_text = text
    for pat, repl in patterns:
        new_new_text, n = re.subn(pat, repl, new_text, flags=re.MULTILINE)
        if n > 0:
            replaced = True
            new_text = new_new_text

    return new_text, replaced



def replace_literals(text: str, mapping: dict):
    """Replace whole-word literals like 'config-lsa' safely."""
    new_text = text
    total = 0
    for old, new in mapping.items():
        # Word boundary around the whole token; allow hyphens inside token
        pattern = r'(?<![\w-])' + re.escape(old) + r'(?![\w-])'
        new_text, n = re.subn(pattern, new, new_text)
        total += n
    return new_text, total

def main():
    ap = argparse.ArgumentParser(description="Update CONFIG_FILE and TOSCA_FILE from config.json values.")
    ap.add_argument("CONFIG_JSON", help="Path to config.json containing the source values")
    ap.add_argument("CONFIG_FILE", help="Path to the config file to update (p2p_public_ip + 'config-*' tokens)")
    ap.add_argument("TOSCA_FILE", help="Path to the TOSCA file to update ('tosca-*' tokens)")
    args = ap.parse_args()

    config_json_path = Path(args.CONFIG_JSON)
    config_file_path = Path(args.CONFIG_FILE)
    tosca_file_path = Path(args.TOSCA_FILE)

    cfg = load_json(config_json_path)

    # Required keys in config.json
    required = [
        "p2p-public-ip",
        "p2p-public-port",
        "node-name-lsa",
        "node-name-sa-1",
        "node-name-sa-2",
    ]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise SystemExit(f"Missing keys in {config_json_path}: {', '.join(missing)}")

    p2p_public_ip = str(cfg["p2p-public-ip"])
    node_lsa = str(cfg["node-name-lsa"])
    node_sa1 = str(cfg["node-name-sa-1"])
    node_sa2 = str(cfg["node-name-sa-2"])

    # --- Update CONFIG_FILE ---
    cfg_text = read_text(config_file_path)

    # 1) Try JSON update first (cleanest if file is JSON)
    updated_text = try_update_json_p2p_ip(cfg_text, p2p_public_ip)
    if updated_text is None:
        # 2) Fallback: regex replace in YAML/.env/INI-like text
        cfg_text, replaced = regex_replace_p2p_ip(cfg_text, p2p_public_ip)
        if not replaced:
            # If nothing matched, you can choose to append, warn, or leave as-is.
            # Here we just warn to stdout and continue with literal replacements.
            print(f"Warning: did not find a recognizable 'p2p_public_ip' assignment in {config_file_path}.")
        updated_text = cfg_text

    # Literal replacements for CONFIG_FILE
    config_mapping = {
        "config-lsa": f"config-{node_lsa}",
        "config-sa-1": f"config-{node_sa1}",
        "config-sa-2": f"config-{node_sa2}",
    }
    updated_text, count_cfg = replace_literals(updated_text, config_mapping)

    write_text_with_backup(config_file_path, updated_text)
    print(f"Updated {config_file_path} (backed up as {config_file_path.with_suffix(config_file_path.suffix + '.bak')}).")
    print(f"Replaced {count_cfg} 'config-*' tokens.")
    print(f"Set p2p_public_ip = {p2p_public_ip}")

    # --- Update TOSCA_FILE ---
    tosca_text = read_text(tosca_file_path)
    tosca_mapping = {
        "tosca-lsa": f"tosca-{node_lsa}",
        "tosca-sa-1": f"tosca-{node_sa1}",
        "tosca-sa-2": f"tosca-{node_sa2}",
    }
    tosca_text, count_tosca = replace_literals(tosca_text, tosca_mapping)
    write_text_with_backup(tosca_file_path, tosca_text)
    print(f"Updated {tosca_file_path} (backed up as {tosca_file_path.with_suffix(tosca_file_path.suffix + '.bak')}).")
    print(f"Replaced {count_tosca} 'tosca-*' tokens.")

if __name__ == "__main__":
    main()

