#!/usr/bin/env bash
# DIY-VPN one-shot installer
# Installs Xray (VLESS+Reality) and Hysteria2 side-by-side on Ubuntu 22.04+/Debian 12+.
# Tested on: Oracle Cloud Always Free Ampere A1 (ARM64) and amd64 VPS.
# Run as root:  sudo ./scripts/install.sh

set -euo pipefail

#─── Colors ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYA='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
log()   { echo -e "${CYA}[*]${RST} $*"; }
ok()    { echo -e "${GRN}[✓]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
fatal() { echo -e "${RED}[✗]${RST} $*" >&2; exit 1; }

#─── Pre-flight ───────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]] || fatal "Run as root: sudo $0"

if ! grep -qiE 'ubuntu|debian' /etc/os-release; then
  warn "This installer is tested on Ubuntu 22.04+/Debian 12+. Other distros may need tweaks."
fi

ARCH="$(uname -m)"
case "$ARCH" in
  x86_64)  XRAY_ARCH="64";        HY2_ARCH="amd64" ;;
  aarch64) XRAY_ARCH="arm64-v8a"; HY2_ARCH="arm64" ;;
  armv7l)  XRAY_ARCH="arm32-v7a"; HY2_ARCH="arm"   ;;
  *) fatal "Unsupported architecture: $ARCH" ;;
esac
log "Detected arch: $ARCH"

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
CONFIG_DIR="$( cd -- "$SCRIPT_DIR/../configs" &> /dev/null && pwd )"
[[ -d "$CONFIG_DIR" ]] || fatal "configs/ directory not found next to scripts/. Did you copy both?"

#─── 1) System update + dependencies ──────────────────────────────────────────
log "Updating apt and installing dependencies…"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq \
  curl wget jq qrencode unzip ca-certificates \
  iptables iptables-persistent netfilter-persistent \
  fail2ban openssl uuid-runtime \
  >/dev/null
ok "Dependencies installed."

#─── 2) Generate credentials ──────────────────────────────────────────────────
log "Generating credentials…"

UUID="$(uuidgen)"
HY2_PASSWORD="$(openssl rand -base64 24 | tr -d '+/=' | head -c 32)"
SHORT_ID="$(openssl rand -hex 4)"   # 8 hex chars
# Note: Salamander obfuscation is NOT used. We rely on Bing masquerade + cert
# CN=bing.com for cover. Obfs breaks the masquerade fall-through to Bing.

# Reality "steal-from" target. Must be:
#  - A real, popular HTTPS site
#  - TLS 1.3 + X25519 capable
#  - NOT a CDN that does TLS termination weirdly
# www.microsoft.com, www.icloud.com, www.lovelive-anime.jp, www.yahoo.co.jp are all good.
REALITY_DEST="${REALITY_DEST:-www.microsoft.com}"
REALITY_SNI="${REALITY_SNI:-$REALITY_DEST}"

ok "Generated UUID, Hysteria2 passwords, and Reality shortId."

#─── 3) Install Xray ──────────────────────────────────────────────────────────
log "Installing Xray-core (latest stable)…"
# Use the official installer
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install >/dev/null
[[ -x /usr/local/bin/xray ]] || fatal "Xray install failed"
ok "Xray installed: $(/usr/local/bin/xray version | head -1)"

# Generate Reality X25519 keypair using xray itself
log "Generating Reality X25519 keypair…"
KEYPAIR="$(/usr/local/bin/xray x25519)"
REALITY_PRIVATE_KEY="$(echo "$KEYPAIR" | awk '/Private/ {print $NF; exit}')"
REALITY_PUBLIC_KEY="$(echo "$KEYPAIR" | awk '/Public/ {print $NF; exit}')"
[[ -n "$REALITY_PRIVATE_KEY" && -n "$REALITY_PUBLIC_KEY" ]] || fatal "Failed to generate Reality keys"
ok "Reality keypair generated."

#─── 4) Write Xray config ─────────────────────────────────────────────────────
log "Writing Xray config…"
mkdir -p /usr/local/etc/xray
sed \
  -e "s|__UUID__|${UUID}|g" \
  -e "s|__REALITY_DEST__|${REALITY_DEST}|g" \
  -e "s|__REALITY_SNI__|${REALITY_SNI}|g" \
  -e "s|__REALITY_PRIVATE_KEY__|${REALITY_PRIVATE_KEY}|g" \
  -e "s|__REALITY_SHORT_ID__|${SHORT_ID}|g" \
  "$CONFIG_DIR/xray-config.json.template" > /usr/local/etc/xray/config.json

# Validate
/usr/local/bin/xray run -test -c /usr/local/etc/xray/config.json >/dev/null \
  || fatal "Xray config failed validation. Check $CONFIG_DIR/xray-config.json.template"
ok "Xray config valid."

#─── 5) Install Hysteria2 ─────────────────────────────────────────────────────
log "Installing Hysteria2…"
# Official installer drops binary in /usr/local/bin/hysteria + creates hysteria-server.service
bash <(curl -fsSL https://get.hy2.sh/) >/dev/null
[[ -x /usr/local/bin/hysteria ]] || fatal "Hysteria2 install failed"
ok "Hysteria2 installed: $(/usr/local/bin/hysteria version | grep -i version | head -1 || true)"

#─── 6) Generate self-signed TLS cert for Hysteria2 ───────────────────────────
log "Generating self-signed TLS cert for Hysteria2…"
mkdir -p /etc/hysteria
openssl ecparam -genkey -name prime256v1 -out /etc/hysteria/server.key 2>/dev/null
openssl req -new -x509 -days 36500 -key /etc/hysteria/server.key \
  -out /etc/hysteria/server.crt \
  -subj "/CN=bing.com" 2>/dev/null
chmod 600 /etc/hysteria/server.key
chown hysteria:hysteria /etc/hysteria/server.key /etc/hysteria/server.crt 2>/dev/null || true
ok "Self-signed TLS cert created (CN=bing.com, valid 100 years)."

#─── 7) Write Hysteria2 config ────────────────────────────────────────────────
log "Writing Hysteria2 config…"
sed \
  -e "s|__HY2_PASSWORD__|${HY2_PASSWORD}|g" \
  "$CONFIG_DIR/hysteria2-config.yaml.template" > /etc/hysteria/config.yaml
chown hysteria:hysteria /etc/hysteria/config.yaml 2>/dev/null || true
ok "Hysteria2 config written."

#─── 8) Fix Oracle / strict iptables ──────────────────────────────────────────
log "Configuring iptables (Oracle-friendly)…"

# Detect Oracle's REJECT-after-SSH rule and insert ACCEPTs above it.
# Strategy: insert at top of INPUT chain so we always come before any REJECT.
iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT
iptables -C INPUT -p udp --dport 20000:50000 -j ACCEPT 2>/dev/null || \
  iptables -I INPUT 1 -p udp --dport 20000:50000 -j ACCEPT

# IPv6 too (best effort)
ip6tables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null || \
  ip6tables -I INPUT 1 -p tcp --dport 443 -j ACCEPT 2>/dev/null || true
ip6tables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null || \
  ip6tables -I INPUT 1 -p udp --dport 443 -j ACCEPT 2>/dev/null || true
ip6tables -C INPUT -p udp --dport 20000:50000 -j ACCEPT 2>/dev/null || \
  ip6tables -I INPUT 1 -p udp --dport 20000:50000 -j ACCEPT 2>/dev/null || true

netfilter-persistent save >/dev/null
ok "iptables rules added and persisted."

#─── 9) Enable BBR + kernel tuning ────────────────────────────────────────────
log "Enabling BBR and tuning kernel for high-BDP links…"
cat > /etc/sysctl.d/99-diyvpn.conf <<'EOF'
# DIY-VPN kernel tuning
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr
net.core.rmem_max = 26214400
net.core.wmem_max = 26214400
net.ipv4.tcp_rmem = 4096 87380 26214400
net.ipv4.tcp_wmem = 4096 65536 26214400
net.ipv4.tcp_fastopen = 3
net.core.netdev_max_backlog = 5000
net.ipv4.tcp_max_syn_backlog = 8192
net.ipv4.udp_mem = 65536 131072 262144
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
fs.file-max = 1000000
EOF
sysctl --system >/dev/null 2>&1 || true
CC="$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null || echo unknown)"
[[ "$CC" == "bbr" ]] && ok "BBR enabled." || warn "BBR not active (cc=$CC). Kernel may not support it."

#─── 10) SSH hardening ────────────────────────────────────────────────────────
log "Hardening SSH (disabling password auth)…"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/'                /etc/ssh/sshd_config
sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
# Disable cloud-init's password auth re-enabler (Oracle's image)
if [[ -f /etc/ssh/sshd_config.d/50-cloud-init.conf ]]; then
  sed -i 's/^PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config.d/50-cloud-init.conf
fi
systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
ok "SSH hardened. (Port unchanged — change manually if you want.)"

#─── 11) fail2ban for SSH ─────────────────────────────────────────────────────
log "Enabling fail2ban…"
cat > /etc/fail2ban/jail.d/sshd.local <<'EOF'
[sshd]
enabled = true
port = ssh
maxretry = 5
findtime = 600
bantime = 3600
EOF
systemctl enable --now fail2ban >/dev/null 2>&1 || true
ok "fail2ban active for SSH."

#─── 12) Enable + start services ──────────────────────────────────────────────
log "Starting services…"
systemctl daemon-reload
systemctl enable --now xray.service       >/dev/null 2>&1
systemctl enable --now hysteria-server.service >/dev/null 2>&1 || \
  systemctl enable --now hysteria.service >/dev/null 2>&1 || true

sleep 2

# Sanity
if ! systemctl is-active --quiet xray; then
  warn "Xray failed to start. Last log:"
  journalctl -u xray -n 20 --no-pager
fi
if ! (systemctl is-active --quiet hysteria-server || systemctl is-active --quiet hysteria); then
  warn "Hysteria2 failed to start. Last log:"
  journalctl -u hysteria-server -n 20 --no-pager 2>/dev/null || journalctl -u hysteria -n 20 --no-pager
fi

#─── 13) Persist credentials for the link generator ───────────────────────────
log "Saving credentials to /etc/diyvpn/credentials.env…"
mkdir -p /etc/diyvpn
PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || curl -fsS --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')"

cat > /etc/diyvpn/credentials.env <<EOF
# DIY-VPN credentials — generated $(date -u +%Y-%m-%dT%H:%M:%SZ)
# KEEP THIS FILE PRIVATE.
PUBLIC_IP="${PUBLIC_IP}"
UUID="${UUID}"
REALITY_PRIVATE_KEY="${REALITY_PRIVATE_KEY}"
REALITY_PUBLIC_KEY="${REALITY_PUBLIC_KEY}"
REALITY_SHORT_ID="${SHORT_ID}"
REALITY_DEST="${REALITY_DEST}"
REALITY_SNI="${REALITY_SNI}"
HY2_PASSWORD="${HY2_PASSWORD}"
HY2_PORT="443"
REALITY_PORT="443"
EOF
chmod 600 /etc/diyvpn/credentials.env
ok "Credentials saved."

#─── 14) Print summary + share links ──────────────────────────────────────────
echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo -e "${BLD}  DIY-VPN install complete${RST}"
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo

# Run the link generator (which also prints QR codes)
"$SCRIPT_DIR/generate-client-links.sh"

echo
echo -e "${BLD}Configs:${RST}"
echo "  /usr/local/etc/xray/config.json"
echo "  /etc/hysteria/config.yaml"
echo "  /etc/diyvpn/credentials.env  (keep private)"
echo
echo -e "${BLD}Service controls:${RST}"
echo "  sudo systemctl restart xray"
echo "  sudo systemctl restart hysteria-server"
echo "  sudo journalctl -u xray -f"
echo "  sudo journalctl -u hysteria-server -f"
echo
echo -e "${BLD}Re-print share links anytime:${RST}"
echo "  sudo $SCRIPT_DIR/generate-client-links.sh"
echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
