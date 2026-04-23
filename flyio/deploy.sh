#!/usr/bin/env bash
# DIY-VPN deployer for Fly.io
# Run this from the flyio/ directory on YOUR LOCAL MACHINE (not a server).
#
# Prereqs:
#   - flyctl installed  →  curl -L https://fly.io/install.sh | sh
#   - jq installed      →  brew install jq   (macOS)  |   apt install jq   (Linux)
#   - signed in to Fly  →  flyctl auth signup    (or  flyctl auth login)
#
# Env vars you can override:
#   APP_NAME        (default: diyvpn-<random>)      Fly app name, must be globally unique
#   REGION          (default: nrt)                  Fly region code
#   ALLOCATE_V4     (default: no)                   "yes" to also get a dedicated IPv4 ($2/mo)
#
# Examples:
#   ./deploy.sh
#   REGION=sin ALLOCATE_V4=yes ./deploy.sh

set -euo pipefail

#─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYA='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
log()   { echo -e "${CYA}[*]${RST} $*"; }
ok()    { echo -e "${GRN}[✓]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
fatal() { echo -e "${RED}[✗]${RST} $*" >&2; exit 1; }

#─── Pre-flight ───────────────────────────────────────────────────────────────
SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

command -v flyctl >/dev/null 2>&1 || fatal "flyctl not installed. Run: curl -L https://fly.io/install.sh | sh  (then restart your shell)"
command -v jq     >/dev/null 2>&1 || fatal "jq not installed. Install with: brew install jq   (macOS)  |   apt install jq   (Linux)"

flyctl auth whoami >/dev/null 2>&1 || fatal "Not signed in to Fly. Run: flyctl auth signup    (or: flyctl auth login)"

FLY_USER="$(flyctl auth whoami 2>/dev/null | head -1)"
ok "Signed in as: ${FLY_USER}"

#─── Inputs ───────────────────────────────────────────────────────────────────
APP_NAME="${APP_NAME:-}"
REGION="${REGION:-nrt}"
ALLOCATE_V4="${ALLOCATE_V4:-no}"

if [[ -z "$APP_NAME" ]]; then
  DEFAULT="diyvpn-$(openssl rand -hex 3)"
  read -rp "App name [${DEFAULT}]: " APP_NAME
  APP_NAME="${APP_NAME:-$DEFAULT}"
fi

# Sanity-check the app name
[[ "$APP_NAME" =~ ^[a-z][a-z0-9-]{1,28}[a-z0-9]$ ]] \
  || fatal "App name must be 3–30 chars, lowercase, start with a letter, end with letter/digit."

log "Plan:"
echo "  App name:    $APP_NAME"
echo "  Region:      $REGION    (Fly region code; see: flyctl platform regions)"
echo "  IPv6:        dedicated (free)"
echo "  IPv4:        ${ALLOCATE_V4}  (set ALLOCATE_V4=yes to enable, \$2/mo)"
echo

read -rp "Proceed? [y/N] " confirm
# Bash 3.2 on macOS doesn't support ${var,,} — use regex match instead.
[[ "$confirm" =~ ^[Yy]$ ]] || { echo "Cancelled."; exit 0; }

#─── 1) Create the app ────────────────────────────────────────────────────────
log "Creating Fly app..."
if flyctl apps list --json 2>/dev/null | jq -e --arg n "$APP_NAME" '.[] | select(.Name == $n)' >/dev/null; then
  ok "App $APP_NAME already exists — reusing."
else
  flyctl apps create "$APP_NAME" --org personal
  ok "App $APP_NAME created."
fi

#─── 2) Create persistent volume ──────────────────────────────────────────────
log "Creating 1 GB persistent volume 'diyvpn_data' in region ${REGION}..."
if flyctl volumes list --app "$APP_NAME" --json | jq -e '.[] | select(.Name == "diyvpn_data")' >/dev/null 2>&1; then
  ok "Volume diyvpn_data already exists — reusing."
else
  flyctl volumes create diyvpn_data \
    --app "$APP_NAME" --region "$REGION" --size 1 --yes
  ok "Volume created."
fi

#─── 3) Allocate dedicated IPs ────────────────────────────────────────────────
log "Allocating dedicated IPv6 (free)..."
flyctl ips allocate-v6 --app "$APP_NAME" >/dev/null || warn "IPv6 allocation may have already been done."

# Bash 3.2 on macOS doesn't support ${var,,} — use tr for lowercase conversion.
ALLOCATE_V4_LC="$(printf '%s' "$ALLOCATE_V4" | tr '[:upper:]' '[:lower:]')"
if [[ "$ALLOCATE_V4_LC" == "yes" ]]; then
  log "Allocating dedicated IPv4 (\$2/month)..."
  flyctl ips allocate-v4 --app "$APP_NAME" --yes >/dev/null || warn "IPv4 allocation may have failed (capacity or billing)."
fi

#─── 4) Render fly.toml from template ─────────────────────────────────────────
log "Rendering fly.toml..."
sed \
  -e "s|APP_NAME_PLACEHOLDER|${APP_NAME}|g" \
  -e "s|REGION_PLACEHOLDER|${REGION}|g" \
  fly.toml.template > fly.toml
ok "fly.toml written."

#─── 5) Deploy ────────────────────────────────────────────────────────────────
log "Deploying (builds container + launches machine; ~2–4 min)..."
flyctl deploy --app "$APP_NAME" --ha=false --config fly.toml

ok "Deploy finished."

#─── 6) Wait for the container to have generated credentials ─────────────────
log "Waiting for container to generate credentials on the volume..."
ATTEMPTS=0
CREDS_RAW=""
while [[ $ATTEMPTS -lt 12 ]]; do
  sleep 5
  if CREDS_RAW="$(flyctl ssh console --app "$APP_NAME" -C "cat /data/credentials.env" 2>/dev/null)" && \
     echo "$CREDS_RAW" | grep -q '^UUID='; then
    break
  fi
  ATTEMPTS=$((ATTEMPTS + 1))
  echo -n "."
done
echo
[[ -n "$CREDS_RAW" ]] || fatal "Couldn't fetch /data/credentials.env. Try:  flyctl ssh console --app $APP_NAME"

# Parse credentials safely (no eval — just awk)
get_cred() { echo "$CREDS_RAW" | awk -F= -v k="$1" '$1==k {sub(/\r$/,"",$2); print $2; exit}'; }
UUID="$(get_cred UUID)"
REALITY_PUBLIC_KEY="$(get_cred REALITY_PUBLIC_KEY)"
REALITY_SHORT_ID="$(get_cred REALITY_SHORT_ID)"
REALITY_SNI="$(get_cred REALITY_SNI)"
HY2_PASSWORD="$(get_cred HY2_PASSWORD)"
HY2_OBFS_PASSWORD="$(get_cred HY2_OBFS_PASSWORD)"

for var in UUID REALITY_PUBLIC_KEY REALITY_SHORT_ID HY2_PASSWORD HY2_OBFS_PASSWORD; do
  [[ -n "${!var}" ]] || fatal "Missing $var in credentials — the container may have failed mid-boot."
done
ok "Credentials fetched."

#─── 7) Get dedicated IPs ─────────────────────────────────────────────────────
IPS_JSON="$(flyctl ips list --app "$APP_NAME" --json)"
IPV6="$(echo "$IPS_JSON" | jq -r '.[] | select(.Type=="v6") | .Address' | head -1)"
IPV4="$(echo "$IPS_JSON" | jq -r '.[] | select(.Type=="v4" and .Region!="global") | .Address' | head -1)"

#─── 8) Build share links ────────────────────────────────────────────────────
urlencode() {
  local LC_ALL=C s="$1" out="" c
  for ((i=0; i<${#s}; i++)); do
    c="${s:$i:1}"
    case "$c" in
      [a-zA-Z0-9.~_-]) out+="$c" ;;
      *) out+=$(printf '%%%02X' "'$c") ;;
    esac
  done
  printf '%s' "$out"
}

build_links() {
  local HOST="$1" LABEL="$2"
  local REMARK_V="$(urlencode "DIY-VPN Reality (${LABEL})")"
  local REMARK_H="$(urlencode "DIY-VPN Hy2 (${LABEL})")"
  local HY2_PWD_ENC="$(urlencode "${HY2_PASSWORD}")"
  local HY2_OBFS_ENC="$(urlencode "${HY2_OBFS_PASSWORD}")"

  echo "VLESS (${LABEL}):"
  echo "vless://${UUID}@${HOST}:443?security=reality&encryption=none&pbk=${REALITY_PUBLIC_KEY}&fp=chrome&type=tcp&flow=xtls-rprx-vision&sni=${REALITY_SNI}&sid=${REALITY_SHORT_ID}#${REMARK_V}"
  echo
  echo "Hysteria2 (${LABEL}):"
  echo "hysteria2://${HY2_PWD_ENC}@${HOST}:443/?obfs=salamander&obfs-password=${HY2_OBFS_ENC}&sni=bing.com&insecure=1#${REMARK_H}"
  echo
}

#─── 9) Summary ───────────────────────────────────────────────────────────────
echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo -e "${BLD}  DIY-VPN deployed to Fly.io${RST}"
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo "  App:       https://fly.io/apps/${APP_NAME}"
echo "  Region:    ${REGION}"
echo "  IPv6:      ${IPV6:-<not allocated>}"
[[ -n "$IPV4" ]] && echo "  IPv4:      ${IPV4}  (dedicated, \$2/mo)"
echo
echo -e "${BLD}Share links:${RST}"
echo "--------------------------------------------------------------------"

if [[ -n "$IPV6" ]]; then
  build_links "[${IPV6}]" "IPv6"
fi
if [[ -n "$IPV4" ]]; then
  build_links "${IPV4}" "IPv4"
fi

echo "--------------------------------------------------------------------"
echo
echo -e "${BLD}Which to add to your clients?${RST}"
echo "  - If your home/mobile network has IPv6, prefer the IPv6 link."
echo "  - If your network is v4-only (most in India/China), you need the"
echo "    IPv4 link. Re-run with ALLOCATE_V4=yes if you haven't."
echo "  - DO NOT use the ${APP_NAME}.fly.dev hostname — it resolves to Fly's"
echo "    edge, not your dedicated IP. Reality/Hy2 will fail."
echo
echo -e "${BLD}Useful commands:${RST}"
echo "  Logs (live):      flyctl logs --app ${APP_NAME}"
echo "  Restart machine:  flyctl machine restart \$(flyctl machines list --app ${APP_NAME} --json | jq -r '.[0].id')"
echo "  SSH into box:     flyctl ssh console --app ${APP_NAME}"
echo "  Destroy all:      flyctl apps destroy ${APP_NAME}"
echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
