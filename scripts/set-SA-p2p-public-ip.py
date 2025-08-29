#!/usr/bin/env python3
import ipaddress
import shutil
from pathlib import Path

FILE = "../k3s/configMap-config-SA.yaml"

def main():
    ip = input("Enter your RA's public IPv4 (e.g., 143.125.23.25): ").strip()

    # validate IPv4
    try:
        ipaddress.IPv4Address(ip)
    except Exception:
        print("❌ Invalid IPv4 address")
        return

    path = Path(FILE)
    if not path.exists():
        print(f"❌ File not found: {FILE}")
        return

    # backup
    backup = path.with_suffix(path.suffix + ".bak")
    shutil.copy(path, backup)
    print(f"✅ Backup saved to {backup}")

    new_lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "p2p_public_ip:" in line:
            indent = line[:line.index("p2p_public_ip:")]
            new_line = f'{indent}p2p_public_ip: "{ip}"'
            new_lines.append(new_line)
        else:
            new_lines.append(line)

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"✅ Updated p2p_public_ip to {ip} in {FILE}")

if __name__ == "__main__":
    main()

