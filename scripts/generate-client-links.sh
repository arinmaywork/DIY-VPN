#!/usr/bin/env bash
# Print VLESS+Reality and Hysteria2 share URIs for client apps.
# Outputs:
#   - one VLESS share link  (works in v2rayN, v2rayNG, FoxRay, Shadowrocket, NekoBox, …)
#   - one Hysteria2 share link
#   - QR codes printed to terminal for each
# Run:  sudo ./scripts/generate-client-links.sh

set -euo pipefail

CRED=/etc/diyvpn/credentials.env
[[ -r "$CRED" ]] || { echo "Cannot read $CRED. Run install.sh first (as root)."; exit 1; }

# shellcheck source=/dev/null
source "$CRED"

CYA='\033[0;36m'; BLD='\033[1m'; YLW='\033[1;33m'; GRN='\033[0;32m'; RST='\033[0m'

# URL-encode helper (pure bash)
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

# ─── VLESS + Reality URI ──────────────────────────────────────────────────────
# vless://<UUID>@<host>:<port>?
#   security=reality
#   &encryption=none
#   &pbk=<reality-public-key>
#   &fp=chrome
#   &type=tcp
#   &flow=xtls-rprx-vision
#   &sni=<reality-sni>
#   &sid=<short-id>
#   #<remark>
VLESS_REMARK="$(urlencode "DIY-VPN Reality (${PUBLIC_IP})")"
VLESS_URI="vless://${UUID}@${PUBLIC_IP}:${REALITY_PORT}"
VLESS_URI+="?security=reality"
VLESS_URI+="&encryption=none"
VLESS_URI+="&pbk=${REALITY_PUBLIC_KEY}"
VLESS_URI+="&fp=chrome"
VLESS_URI+="&type=tcp"
VLESS_URI+="&flow=xtls-rprx-vision"
VLESS_URI+="&sni=${REALITY_SNI}"
VLESS_URI+="&sid=${REALITY_SHORT_ID}"
VLESS_URI+="#${VLESS_REMARK}"

# ─── Hysteria2 URI ────────────────────────────────────────────────────────────
# hysteria2://<password>@<host>:<port>/?
#   obfs=salamander
#   &obfs-password=<obfs-password>
#   &sni=bing.com
#   &insecure=1
#   #<remark>
HY2_REMARK="$(urlencode "DIY-VPN Hysteria2 (${PUBLIC_IP})")"
HY2_PWD_ENC="$(urlencode "${HY2_PASSWORD}")"
HY2_OBFS_ENC="$(urlencode "${HY2_OBFS_PASSWORD}")"
HY2_URI="hysteria2://${HY2_PWD_ENC}@${PUBLIC_IP}:${HY2_PORT}/"
HY2_URI+="?obfs=salamander"
HY2_URI+="&obfs-password=${HY2_OBFS_ENC}"
HY2_URI+="&sni=bing.com"
HY2_URI+="&insecure=1"
HY2_URI+="#${HY2_REMARK}"

echo -e "${BLD}Server IP:${RST}        ${PUBLIC_IP}"
echo -e "${BLD}Reality port:${RST}     ${REALITY_PORT}/tcp"
echo -e "${BLD}Hysteria2 port:${RST}   ${HY2_PORT}/udp  (+ port-hop range 20000–50000)"
echo -e "${BLD}Reality SNI:${RST}      ${REALITY_SNI}"
echo

echo -e "${CYA}── VLESS + Reality share link ───────────────────────────────────────${RST}"
echo "${VLESS_URI}"
echo

echo -e "${CYA}── Hysteria2 share link ─────────────────────────────────────────────${RST}"
echo "${HY2_URI}"
echo

if command -v qrencode >/dev/null 2>&1; then
  echo -e "${YLW}── QR: VLESS + Reality (scan in v2rayNG / FoxRay / Shadowrocket) ──${RST}"
  qrencode -t ansiutf8 "${VLESS_URI}"
  echo
  echo -e "${YLW}── QR: Hysteria2 ──────────────────────────────────────────────────${RST}"
  qrencode -t ansiutf8 "${HY2_URI}"
  echo
else
  echo -e "${YLW}qrencode not installed — skipping QR codes. (apt install qrencode)${RST}"
fi

echo -e "${GRN}Tip:${RST} If your terminal mangles the QR, copy each URI above into a"
echo "       client app on your desktop, then use the desktop client's"
echo "       'Share / QR Code' feature to scan onto your phone."
echo
echo -e "${GRN}Tip:${RST} On Hysteria2, 'insecure=1' is required because we use a"
echo "       self-signed cert (no domain). Traffic is still fully encrypted."
