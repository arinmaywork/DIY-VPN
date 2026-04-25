#!/bin/bash
# DIY-VPN server-side scaffolding installer.
#
# Run ONCE on the VPN server (Oracle box) AFTER hysteria + xray are installed
# and have working configs. Bootstraps:
#   • /data/credentials.env       — server-wide secrets, derived from current xray + hy2
#   • /data/users.json            — single 'default' user matching current credentials
#   • /usr/local/bin/diyvpn-render — config generator
#   • /usr/local/bin/diyvpn-auth.py — Hy2 HTTP auth backend
#   • diyvpn-auth.service          — systemd unit for the backend
#
# After this, every adduser/kick/rotate is just: edit /data/users.json,
# then run /usr/local/bin/diyvpn-render. The bot does both via SSH.
#
# Idempotent: safe to re-run; will not overwrite existing users.json.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "must run as root: sudo bash $0" >&2
  exit 1
fi

cd "$(dirname "$0")"

echo ">>> 1/7  apt: python3-aiohttp jq"
DEBIAN_FRONTEND=noninteractive apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3-aiohttp jq

echo ">>> 2/7  /data dir + perms"
install -d -m 750 -g hysteria /data 2>/dev/null || install -d -m 750 /data

if [[ ! -f /data/credentials.env ]]; then
  echo ">>> 3/7  bootstrap /data/credentials.env from current xray + hysteria"
  if [[ ! -f /usr/local/etc/xray/config.json ]]; then
    echo "FATAL: /usr/local/etc/xray/config.json missing — install xray first" >&2
    exit 1
  fi
  REAL_PRIV=$(jq -r '.inbounds[]|select(.protocol=="vless").streamSettings.realitySettings.privateKey' /usr/local/etc/xray/config.json)
  REAL_SNI=$(jq -r  '.inbounds[]|select(.protocol=="vless").streamSettings.realitySettings.serverNames[0]' /usr/local/etc/xray/config.json)
  REAL_SID=$(jq -r  '.inbounds[]|select(.protocol=="vless").streamSettings.realitySettings.shortIds[0]' /usr/local/etc/xray/config.json)
  REAL_PUB=$(/usr/local/bin/xray x25519 -i "$REAL_PRIV" | awk -F': ' '/[Pp]ublic/{print $2}')
  HY2_STATS_SECRET=$(openssl rand -hex 16)
  cat > /data/credentials.env <<EOF
HY2_STATS_SECRET=${HY2_STATS_SECRET}
REALITY_PRIVATE_KEY=${REAL_PRIV}
REALITY_PUBLIC_KEY=${REAL_PUB}
REALITY_SNI=${REAL_SNI}
REALITY_SHORT_ID=${REAL_SID}
EOF
  chmod 640 /data/credentials.env
  chgrp hysteria /data/credentials.env 2>/dev/null || true
else
  echo ">>> 3/7  /data/credentials.env exists, leaving alone"
fi

if [[ ! -f /data/users.json ]]; then
  echo ">>> 4/7  bootstrap /data/users.json with current credentials as 'default' user"
  CURRENT_HY2=$(cat /etc/hysteria/.password 2>/dev/null || openssl rand -base64 24 | tr -d '/+=' | head -c 32)
  CURRENT_UUID=$(jq -r '.inbounds[]|select(.protocol=="vless").settings.clients[0].id' /usr/local/etc/xray/config.json)
  cat > /data/users.json <<EOF
[
  {
    "name": "default",
    "uuid": "${CURRENT_UUID}",
    "hy2_password": "${CURRENT_HY2}",
    "email": "default@diyvpn",
    "flow": "xtls-rprx-vision",
    "created_at": $(date +%s),
    "expires_at": null,
    "priority": "normal"
  }
]
EOF
  chmod 640 /data/users.json
  chgrp hysteria /data/users.json 2>/dev/null || true
else
  echo ">>> 4/7  /data/users.json exists, leaving alone"
fi

echo ">>> 5/7  install scripts"
install -m 755 bin/diyvpn-render.py /usr/local/bin/diyvpn-render
install -m 755 bin/diyvpn-auth.py   /usr/local/bin/diyvpn-auth.py

echo ">>> 6/7  install systemd unit"
install -m 644 systemd/diyvpn-auth.service /etc/systemd/system/diyvpn-auth.service
systemctl daemon-reload
systemctl enable diyvpn-auth.service

echo ">>> 7/7  render configs + start auth backend + restart hy2/xray"
/usr/local/bin/diyvpn-render
systemctl start diyvpn-auth.service
sleep 1

echo ""
echo "=== service health ==="
for svc in diyvpn-auth hysteria-server xray; do
  state=$(systemctl is-active "$svc" || true)
  echo "  $svc: $state"
done
echo ""
echo "=== auth backend smoke test ==="
curl -s --max-time 3 http://127.0.0.1:8080/health || echo "(auth backend not responding)"
echo ""
echo "=== listening sockets on :443 + :8080 + :25413 ==="
ss -lntup | grep -E ':(443|8080|25413)\b' || true

echo ""
echo "✅ Server-side scaffolding installed."
echo "Next: tell the bot to SSH in and manage /data/users.json."
