#!/usr/bin/env bash
# DIY-VPN container entrypoint
# - On first boot: generate credentials + seed users.json, save to /data
# - On every boot: substitute creds + clients into config templates, start xray + hysteria
# - If either process dies, exit so Fly restarts the machine

set -euo pipefail

CRED=/data/credentials.env
SHARELINKS=/data/share-links.txt
CERT_DIR=/data/tls
USERS=/data/users.json

mkdir -p /data "$CERT_DIR"

#─── 1) Generate credentials once, persist on /data volume ────────────────────
if [[ ! -f "$CRED" ]]; then
  echo "[*] First boot: generating fresh credentials..."

  UUID="$(cat /proc/sys/kernel/random/uuid)"
  HY2_PASSWORD="$(openssl rand -base64 24 | tr -d '+/=' | head -c 32)"
  HY2_OBFS_PASSWORD="$(openssl rand -base64 24 | tr -d '+/=' | head -c 32)"
  SHORT_ID="$(openssl rand -hex 4)"

  # Reality X25519 keypair via xray
  KP="$(/usr/local/bin/xray x25519)"
  REALITY_PRIVATE_KEY="$(echo "$KP" | awk '/Private/ {print $NF; exit}')"
  REALITY_PUBLIC_KEY="$(echo "$KP" | awk '/Public/  {print $NF; exit}')"

  # Defaults — can be overridden by env vars from fly.toml or `flyctl secrets set`
  REALITY_DEST="${REALITY_DEST:-www.microsoft.com}"
  REALITY_SNI="${REALITY_SNI:-$REALITY_DEST}"

  cat > "$CRED" <<EOF
UUID=${UUID}
REALITY_PRIVATE_KEY=${REALITY_PRIVATE_KEY}
REALITY_PUBLIC_KEY=${REALITY_PUBLIC_KEY}
REALITY_SHORT_ID=${SHORT_ID}
REALITY_DEST=${REALITY_DEST}
REALITY_SNI=${REALITY_SNI}
HY2_PASSWORD=${HY2_PASSWORD}
HY2_OBFS_PASSWORD=${HY2_OBFS_PASSWORD}
EOF
  chmod 600 "$CRED"
  echo "[OK] Credentials generated and saved to $CRED"
fi

# Load credentials
set -a
# shellcheck source=/dev/null
. "$CRED"
set +a

#─── 1b) Seed users.json on first boot (single user "default" = the master UUID)
# The Telegram bot edits this file via flyctl ssh to add/remove device-specific
# UUIDs. Each entry: { "name": "iphone", "uuid": "...", "flow": "xtls-rprx-vision" }
if [[ ! -f "$USERS" ]]; then
  echo "[*] Seeding default user list..."
  cat > "$USERS" <<EOF
[
  {"name": "default", "uuid": "${UUID}", "flow": "xtls-rprx-vision", "email": "default@diyvpn"}
]
EOF
  chmod 600 "$USERS"
fi

#─── 2) Self-signed TLS cert for Hysteria2 (one time) ─────────────────────────
if [[ ! -f "$CERT_DIR/server.crt" ]]; then
  echo "[*] Generating self-signed TLS cert for Hysteria2..."
  openssl ecparam -genkey -name prime256v1 -out "$CERT_DIR/server.key" 2>/dev/null
  openssl req -new -x509 -days 36500 -key "$CERT_DIR/server.key" \
    -out "$CERT_DIR/server.crt" -subj "/CN=bing.com" 2>/dev/null
  chmod 600 "$CERT_DIR/server.key"
fi

#─── 3) Render configs from templates ─────────────────────────────────────────
# Build the clients array from users.json. Each user becomes a VLESS client
# entry with id/flow/email. Email = unique tag for stats lookups.
export CLIENTS_JSON
CLIENTS_JSON="$(jq -c '[.[] | {id: .uuid, flow: (.flow // "xtls-rprx-vision"), email: (.email // (.name + "@diyvpn"))}]' "$USERS")"
echo "[*] Rendering xray config with $(echo "$CLIENTS_JSON" | jq 'length') user(s)"

# Render via python so we can inject the clients array verbatim (sed chokes on
# JSON with special chars). Fails loudly if any required env var is missing.
if ! python3 - > /etc/xray/config.json <<'PYEOF'
import json, os, pathlib, sys
required = ["CLIENTS_JSON", "UUID", "REALITY_DEST", "REALITY_SNI",
            "REALITY_PRIVATE_KEY", "REALITY_SHORT_ID"]
missing = [k for k in required if not os.environ.get(k)]
if missing:
    sys.stderr.write(f"[!] Missing env vars: {missing}\n")
    sys.exit(1)
tpl = pathlib.Path("/etc/templates/xray.json.template").read_text()
out = (tpl
  .replace("__CLIENTS_JSON__",        os.environ["CLIENTS_JSON"])
  .replace("__UUID__",                os.environ["UUID"])
  .replace("__REALITY_DEST__",        os.environ["REALITY_DEST"])
  .replace("__REALITY_SNI__",         os.environ["REALITY_SNI"])
  .replace("__REALITY_PRIVATE_KEY__", os.environ["REALITY_PRIVATE_KEY"])
  .replace("__REALITY_SHORT_ID__",    os.environ["REALITY_SHORT_ID"])
)
# Validate JSON before handing to xray.
json.loads(out)
print(out)
PYEOF
then
  echo "[!] Python renderer failed. Dumping template + env for inspection:"
  cat /etc/templates/xray.json.template
  env | grep -E '^(CLIENTS_JSON|UUID|REALITY_)' || true
  exit 1
fi

sed \
  -e "s|__HY2_PASSWORD__|${HY2_PASSWORD}|g" \
  -e "s|__HY2_OBFS_PASSWORD__|${HY2_OBFS_PASSWORD}|g" \
  -e "s|__CERT_DIR__|${CERT_DIR}|g" \
  /etc/templates/hysteria2.yaml.template > /etc/hysteria/config.yaml

# Validate (note: modern xray uses `-test` as a top-level flag, not a subcommand)
/usr/local/bin/xray -test -c /etc/xray/config.json || {
  echo "[!] Xray config validation failed -- dumping config for inspection:"
  cat /etc/xray/config.json
  exit 1
}
echo "[OK] Xray config OK"

#─── 4) Write share-links.txt for the user to read after deploy ───────────────
# (We can't know the public IP until Fly assigns it, but FLY_APP_NAME is in env)
APP_HOSTNAME="${FLY_APP_NAME:-app}.fly.dev"
PUBLIC_IPV6="${FLY_PUBLIC_IPV6:-(allocate via flyctl ips list)}"

# URL-encode helper
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

VLESS_REMARK="$(urlencode "DIY-VPN Reality (fly)")"
HY2_REMARK="$(urlencode "DIY-VPN Hysteria2 (fly)")"
HY2_PWD_ENC="$(urlencode "$HY2_PASSWORD")"
HY2_OBFS_ENC="$(urlencode "$HY2_OBFS_PASSWORD")"

cat > "$SHARELINKS" <<EOF
# DIY-VPN share links (written $(date -u +%Y-%m-%dT%H:%M:%SZ))
#
# Replace HOST below with your Fly IP. Get them with:
#   flyctl ips list --app ${FLY_APP_NAME:-YOUR-APP}
#
# For IPv4 (if allocated):  use the bare IP, e.g.  1.2.3.4
# For IPv6:                 wrap in brackets, e.g. [2606:1234::1]
# (DO NOT use the .fly.dev hostname -- it's a CNAME at Fly's edge,
#  Reality and Hysteria2 need a direct connection to your machine's IP.)

HOST_IPV4="<paste IPv4 here, or omit if v6-only>"
HOST_IPV6="${PUBLIC_IPV6}"

VLESS_v6=vless://${UUID}@[\${HOST_IPV6}]:443?security=reality&encryption=none&pbk=${REALITY_PUBLIC_KEY}&fp=chrome&type=tcp&flow=xtls-rprx-vision&sni=${REALITY_SNI}&sid=${REALITY_SHORT_ID}#${VLESS_REMARK}

HYSTERIA2_v6=hysteria2://${HY2_PWD_ENC}@[\${HOST_IPV6}]:443/?obfs=salamander&obfs-password=${HY2_OBFS_ENC}&sni=bing.com&insecure=1#${HY2_REMARK}
EOF
chmod 600 "$SHARELINKS"

#─── 5) Start both daemons; exit if either dies (Fly restarts on exit) ───────
echo "[*] Starting xray and hysteria..."

/usr/local/bin/xray run -c /etc/xray/config.json &
XRAY_PID=$!

/usr/local/bin/hysteria server -c /etc/hysteria/config.yaml &
HY_PID=$!

# Forward SIGTERM cleanly
shutdown() {
  echo "[*] Caught signal, stopping..."
  kill -TERM "$XRAY_PID" "$HY_PID" 2>/dev/null || true
  wait "$XRAY_PID" "$HY_PID" 2>/dev/null || true
  exit 0
}
trap shutdown SIGTERM SIGINT

# Wait for either child to exit
wait -n
EXIT=$?
echo "[!] One process exited with code $EXIT -- terminating the other."
kill -TERM "$XRAY_PID" "$HY_PID" 2>/dev/null || true
wait 2>/dev/null || true
exit "$EXIT"
