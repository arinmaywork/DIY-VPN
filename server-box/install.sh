#!/usr/bin/env bash
# DIY-VPN end-to-end installer for a fresh Oracle Always Free box.
#
# Run as root on a freshly-provisioned Ubuntu 22.04+ / Debian 12+ instance:
#
#     git clone https://github.com/<you>/DIY-VPN.git
#     cd DIY-VPN/server-box
#     sudo ./install.sh
#
# What it does, end to end:
#   1) Runs ../scripts/install.sh:
#        - apt deps, Xray-core + Hysteria2 binaries
#        - self-signed TLS cert (CN=bing.com)
#        - base hy2 + xray configs (single-user bootstrap)
#        - iptables (Oracle-friendly), BBR + kernel tuning
#        - SSH hardening (no password auth) + fail2ban
#        - services enabled
#   2) Ensures a dedicated `xray` system user exists (for config ownership)
#      and installs a hardening drop-in for xray.service.
#   3) Runs ./setup.sh:
#        - installs the multi-user scaffolding (/data/users.json,
#          /data/credentials.env, diyvpn-render, diyvpn-auth backend)
#        - re-renders configs through diyvpn-render and starts everything.
#   4) Prints the public IP + a ready-to-paste line for the bot's
#      VPN_BOXES env so you can wire this box into the Telegram bot.
#
# Idempotent: re-running upgrades hardening + re-renders configs.

set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'; CYA='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
log()   { echo -e "${CYA}[*]${RST} $*"; }
ok()    { echo -e "${GRN}[✓]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
fatal() { echo -e "${RED}[✗]${RST} $*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fatal "Run as root: sudo $0"

HERE="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
REPO_ROOT="$( cd -- "$HERE/.." &> /dev/null && pwd )"
BASE_INSTALL="$REPO_ROOT/scripts/install.sh"
[[ -x "$BASE_INSTALL" ]] || fatal "Missing $BASE_INSTALL — clone the full repo, not just server-box/"

#─── Optional box label ───────────────────────────────────────────────────────
# Use BOX_NAME=... ./install.sh to label this box (toronto, london, …).
# Defaults to the hostname.
BOX_NAME="${BOX_NAME:-$(hostname -s)}"

#─── 1) Base install ──────────────────────────────────────────────────────────
echo -e "${BLD}════════════ Stage 1/3: base installer (xray + hy2 + hardening) ════════════${RST}"
bash "$BASE_INSTALL"

#─── 2) Xray hardening: dedicated system user + drop-in ───────────────────────
echo
echo -e "${BLD}════════════ Stage 2/3: xray system user + hardening drop-in ════════════${RST}"
log "Ensuring xray system user exists…"
if ! id -u xray >/dev/null 2>&1; then
  useradd --system --no-create-home --shell /usr/sbin/nologin xray
  ok "Created system user 'xray'."
else
  ok "User 'xray' already exists."
fi

# Make the xray config dir readable by the xray user.
chown -R xray:xray /usr/local/etc/xray
chmod 750 /usr/local/etc/xray
chmod 644 /usr/local/etc/xray/config.json

# Hardening drop-in. Runs xray as the dedicated user with reduced caps,
# but allows it to bind :443 via CAP_NET_BIND_SERVICE.
log "Installing xray.service hardening drop-in…"
install -d -m 755 /etc/systemd/system/xray.service.d
cat > /etc/systemd/system/xray.service.d/10-hardening.conf <<'EOF'
[Service]
User=xray
Group=xray

# Allow binding privileged ports while staying unprivileged otherwise.
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictRealtime=true
RestrictNamespaces=true
LockPersonality=true
MemoryDenyWriteExecute=true

# diyvpn-render writes the config as root then chowns to xray.
# xray itself never writes to disk.
ReadWritePaths=
ReadOnlyPaths=/usr/local/etc/xray
EOF
systemctl daemon-reload
systemctl restart xray
sleep 1
if systemctl is-active --quiet xray; then
  ok "xray.service running under hardened drop-in."
else
  warn "xray.service not active after hardening — last logs:"
  journalctl -u xray -n 20 --no-pager
fi

#─── 3) Multi-user scaffolding ────────────────────────────────────────────────
echo
echo -e "${BLD}════════════ Stage 3/3: multi-user scaffolding (diyvpn-render + auth) ════════════${RST}"
bash "$HERE/setup.sh"

#─── 4) Public IP + bot wiring hint ───────────────────────────────────────────
PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org \
            || curl -fsS --max-time 5 https://ifconfig.me \
            || hostname -I | awk '{print $1}')"

echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo -e "${BLD}  DIY-VPN install complete on box: ${BOX_NAME}${RST}"
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
echo
echo -e "${BLD}Public IPv4:${RST} ${PUBLIC_IP}"
echo
echo -e "${BLD}Wire this box into the Telegram bot${RST} (on the bot host):"
echo
echo -e "  ${CYA}# Single-box setup:${RST}"
echo "  VPN_HOST=${PUBLIC_IP}"
echo
echo -e "  ${CYA}# Multi-box setup (preferred — survives any single-box outage):${RST}"
echo "  VPN_BOXES=${BOX_NAME}:${PUBLIC_IP}[,<other-name>:<other-ip>...]"
echo
echo -e "${BLD}Then on the bot host:${RST}"
echo "  systemctl restart diyvpn-bot"
echo
echo -e "${BLD}Verify from the bot host:${RST}"
echo "  ssh -i ~/.ssh/diyvpn-oracle ubuntu@${PUBLIC_IP} sudo systemctl is-active diyvpn-auth hysteria-server xray"
echo
echo -e "${BLD}════════════════════════════════════════════════════════════════════${RST}"
