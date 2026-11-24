#!/usr/bin/env bash
# =============================================================================
# Swarmchestrate — Docker Registry Secret Creator
# Run this directly on the K3s master node.
#
# Creates Kubernetes docker-registry secrets using the local kubectl.
#
# Config file (recommended):
#   ./create-registry-secrets.sh --config registry-config.yaml
#
# CLI flags:
#   ./create-registry-secrets.sh \
#     --registry docker.io \
#     --username myuser \
#     --password mypassword \
#     --secret-name regcred-dockerhub
#
# Config file + CLI override:
#   ./create-registry-secrets.sh --config registry-config.yaml --namespace staging
#
# Config file format (YAML):
#   namespace: default
#   registries:
#     - registry: docker.io
#       username: myuser
#       password: mypassword
#       secret_name: regcred-dockerhub   # optional — defaults to regcred-0, regcred-1...
#     - registry: ghcr.io
#       username: ghuser
#       password: ghtoken
#
# Optional flags:
#   --namespace   Kubernetes namespace (default: default)
#   --dry-run     Print what would be run without applying anything
# =============================================================================
set -euo pipefail

# ── colour helpers ─────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; BOLD='\033[1m'; RESET='\033[0m'
info()    { echo -e "${CYAN}[INFO]${RESET}  $*"; }
success() { echo -e "${GREEN}[OK]${RESET}    $*"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $*"; }
die()     { echo -e "${RED}[ERROR]${RESET} $*" >&2; exit 1; }

# ── kubectl wrapper — always uses K3s kubeconfig ──────────────────────────────
KUBECONFIG_PATH="/etc/rancher/k3s/k3s.yaml"
kctl() { sudo KUBECONFIG="$KUBECONFIG_PATH" kubectl "$@"; }

# ── defaults ──────────────────────────────────────────────────────────────────
CONFIG_FILE=""
NAMESPACE="default"
DRY_RUN=false

REGISTRIES=()
USERNAMES=()
PASSWORDS=()
SECRET_NAMES=()

# ── pure-bash YAML parser ─────────────────────────────────────────────────────
yaml_get() {
  local key="$1" file="$2"
  grep -E "^${key}:" "$file" \
    | head -1 \
    | sed "s/^${key}:[[:space:]]*//" \
    | sed 's/^["'"'"']\(.*\)["'"'"']$/\1/' \
    | sed 's/[[:space:]]*$//'
}

parse_registries_from_yaml() {
  local file="$1"
  local in_registries=false
  local cur_registry="" cur_username="" cur_password="" cur_secret=""

  _flush() {
    if [[ -n "$cur_registry" ]]; then
      REGISTRIES+=("$cur_registry")
      USERNAMES+=("$cur_username")
      PASSWORDS+=("$cur_password")
      SECRET_NAMES+=("$cur_secret")
      cur_registry=""; cur_username=""; cur_password=""; cur_secret=""
    fi
  }

  while IFS= read -r line; do
    if [[ "$line" =~ ^registries: ]]; then
      in_registries=true; continue
    fi
    if [[ "$in_registries" == true && "$line" =~ ^[a-z_]+: ]]; then
      _flush; in_registries=false; continue
    fi
    if [[ "$in_registries" == true ]]; then
      if [[ "$line" =~ ^[[:space:]]+-[[:space:]]+registry:[[:space:]]*(.*) ]]; then
        _flush
        cur_registry="${BASH_REMATCH[1]//\"/}"; cur_registry="${cur_registry//\'/}"
      elif [[ "$line" =~ ^[[:space:]]+registry:[[:space:]]*(.*) ]]; then
        cur_registry="${BASH_REMATCH[1]//\"/}"; cur_registry="${cur_registry//\'/}"
      elif [[ "$line" =~ ^[[:space:]]+username:[[:space:]]*(.*) ]]; then
        cur_username="${BASH_REMATCH[1]//\"/}"; cur_username="${cur_username//\'/}"
      elif [[ "$line" =~ ^[[:space:]]+password:[[:space:]]*(.*) ]]; then
        cur_password="${BASH_REMATCH[1]//\"/}"; cur_password="${cur_password//\'/}"
      elif [[ "$line" =~ ^[[:space:]]+secret_name:[[:space:]]*(.*) ]]; then
        cur_secret="${BASH_REMATCH[1]//\"/}"; cur_secret="${cur_secret//\'/}"
      fi
    fi
  done < "$file"

  # flush last entry
  if [[ -n "$cur_registry" ]]; then
    REGISTRIES+=("$cur_registry")
    USERNAMES+=("$cur_username")
    PASSWORDS+=("$cur_password")
    SECRET_NAMES+=("$cur_secret")
  fi
}

load_config_file() {
  local file="$1"
  [[ -f "$file" ]] || die "Config file not found: $file"
  info "Loading config from $file"
  local val
  val="$(yaml_get namespace "$file")"; [[ -n "$val" ]] && NAMESPACE="$val"
  parse_registries_from_yaml "$file"
  success "Config loaded — ${#REGISTRIES[@]} registry entry/entries found"
}

# ── arg parsing ───────────────────────────────────────────────────────────────
_cur_registry=""; _cur_username=""; _cur_password=""; _cur_secret=""

_flush_cli_entry() {
  if [[ -n "$_cur_registry" ]]; then
    [[ -n "$_cur_username" ]] || die "Missing --username for registry '${_cur_registry}'"
    [[ -n "$_cur_password" ]] || die "Missing --password for registry '${_cur_registry}'"
    REGISTRIES+=("$_cur_registry")
    USERNAMES+=("$_cur_username")
    PASSWORDS+=("$_cur_password")
    SECRET_NAMES+=("$_cur_secret")
    _cur_registry=""; _cur_username=""; _cur_password=""; _cur_secret=""
  fi
}

usage() {
  grep '^#' "$0" | grep -v '#!/' | sed 's/^# \{0,2\}//' | head -45
  exit 0
}

# First pass: load config file before CLI overrides
ARGS=("$@")
for i in "${!ARGS[@]}"; do
  if [[ "${ARGS[$i]}" == "--config" ]]; then
    CONFIG_FILE="${ARGS[$((i+1))]}"
    load_config_file "$CONFIG_FILE"
    break
  fi
done

# Second pass: CLI args (override config file)
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config)      shift 2 ;;
    --namespace)   NAMESPACE="$2";       shift 2 ;;
    --dry-run)     DRY_RUN=true;         shift ;;
    --registry)    _flush_cli_entry; _cur_registry="$2";  shift 2 ;;
    --username)    _cur_username="$2";   shift 2 ;;
    --password)    _cur_password="$2";   shift 2 ;;
    --secret-name) _cur_secret="$2";     shift 2 ;;
    -h|--help)     usage ;;
    *) die "Unknown argument: $1" ;;
  esac
done
_flush_cli_entry

# ── validation ────────────────────────────────────────────────────────────────
[[ ${#REGISTRIES[@]} -gt 0 ]] || die "At least one registry entry is required"

# ── resolve default secret names ──────────────────────────────────────────────
resolve_secret_names() {
  for i in "${!REGISTRIES[@]}"; do
    [[ -z "${SECRET_NAMES[$i]}" ]] && SECRET_NAMES[$i]="regcred-${i}"
  done
}

# ── check kubectl is reachable ────────────────────────────────────────────────
check_kubectl() {
  info "Checking kubectl..."
  [[ -f "$KUBECONFIG_PATH" ]] || die "Kubeconfig not found at $KUBECONFIG_PATH — is K3s installed?"
  kctl get nodes &>/dev/null || die "kubectl not working — check: systemctl status k3s"
  success "kubectl OK"
}

# ── create secrets ────────────────────────────────────────────────────────────
create_secrets() {
  local total=${#REGISTRIES[@]}
  info "Creating ${total} registry secret(s) in namespace '${NAMESPACE}'..."

  # Ensure namespace exists
  kctl create namespace "${NAMESPACE}" --dry-run=client -o yaml \
    | kctl apply -f - &>/dev/null || true

  for i in "${!REGISTRIES[@]}"; do
    local registry="${REGISTRIES[$i]}"
    local username="${USERNAMES[$i]}"
    local password="${PASSWORDS[$i]}"
    local secret_name="${SECRET_NAMES[$i]}"

    info "[$((i+1))/${total}] '${secret_name}' → ${registry}"

    kctl create secret docker-registry "${secret_name}" \
      --docker-server="${registry}" \
      --docker-username="${username}" \
      --docker-password="${password}" \
      --namespace="${NAMESPACE}" \
      --dry-run=client -o yaml | kctl apply -f -

    success "Secret '${secret_name}' applied"
  done
}

# ── verify ────────────────────────────────────────────────────────────────────
verify_secrets() {
  info "Verifying secrets in namespace '${NAMESPACE}'..."
  kctl get secrets -n "${NAMESPACE}" \
    --field-selector type=kubernetes.io/dockerconfigjson \
    -o custom-columns='NAME:.metadata.name,REGISTRY:.metadata.annotations.kubectl\.kubernetes\.io/last-applied-configuration' \
    2>/dev/null || kctl get secrets -n "${NAMESPACE}" \
    --field-selector type=kubernetes.io/dockerconfigjson
}

# ── summary ───────────────────────────────────────────────────────────────────
print_summary() {
  echo ""
  echo -e "${BOLD}╔══════════════════════════════════════════════════╗${RESET}"
  echo -e "${BOLD}║        REGISTRY SECRETS CREATION COMPLETE       ║${RESET}"
  echo -e "${BOLD}╠══════════════════════════════════════════════════╣${RESET}"
  echo -e "${BOLD}║${RESET}  Namespace  : ${NAMESPACE}"
  echo -e "${BOLD}║${RESET}"
  echo -e "${BOLD}║${RESET}  Secrets created:"
  for i in "${!REGISTRIES[@]}"; do
    echo -e "${BOLD}║${RESET}    ${GREEN}✓${RESET}  ${SECRET_NAMES[$i]}  →  ${REGISTRIES[$i]}"
  done
  echo -e "${BOLD}║${RESET}"
  echo -e "${BOLD}║${RESET}  Verify with:"
  echo -e "${BOLD}║${RESET}  ${CYAN}kubectl get secrets -n ${NAMESPACE}${RESET}"
  echo -e "${BOLD}╚══════════════════════════════════════════════════╝${RESET}"
  echo ""
}

# ── dry run ───────────────────────────────────────────────────────────────────
dry_run_summary() {
  echo ""
  echo -e "${BOLD}═══════════════ DRY RUN SUMMARY ═══════════════${RESET}"
  echo -e "  Namespace    : ${NAMESPACE}"
  echo -e "  Kubeconfig   : ${KUBECONFIG_PATH}"
  echo ""
  echo -e "${BOLD}Registry entries (${#REGISTRIES[@]}):${RESET}"
  for i in "${!REGISTRIES[@]}"; do
    echo -e "  [$((i+1))]  secret_name : ${SECRET_NAMES[$i]}"
    echo -e "       registry    : ${REGISTRIES[$i]}"
    echo -e "       username    : ${USERNAMES[$i]}"
    echo -e "       password    : ***"
    echo ""
    echo -e "  Command that would run:"
    echo    "  ---"
    echo    "  kubectl create secret docker-registry ${SECRET_NAMES[$i]} \\"
    echo    "    --docker-server=${REGISTRIES[$i]} \\"
    echo    "    --docker-username=${USERNAMES[$i]} \\"
    echo    "    --docker-password=*** \\"
    echo    "    --namespace=${NAMESPACE} \\"
    echo    "    --dry-run=client -o yaml | kubectl apply -f -"
    echo    "  ---"
    echo ""
  done
}

# ── main ──────────────────────────────────────────────────────────────────────
main() {
  echo ""
  echo -e "${BOLD}Swarmchestrate — Registry Secret Creator${RESET}"
  echo -e "Namespace: ${NAMESPACE} | Secrets: ${#REGISTRIES[@]}"
  echo ""

  resolve_secret_names

  if [[ "$DRY_RUN" == true ]]; then
    dry_run_summary
    exit 0
  fi

  check_kubectl
  create_secrets
  verify_secrets
  print_summary
}

main
