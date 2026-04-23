#!/usr/bin/env bash
# Enable BBR + tune kernel for high-BDP links (China ↔ overseas).
# Idempotent — safe to re-run. Run as root.

set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0"; exit 1; }

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

sysctl --system >/dev/null
CC="$(sysctl -n net.ipv4.tcp_congestion_control)"
QD="$(sysctl -n net.core.default_qdisc)"

echo "tcp_congestion_control = $CC"
echo "default_qdisc          = $QD"

if [[ "$CC" == "bbr" ]]; then
  echo "✓ BBR active"
else
  echo "✗ BBR is NOT active. Your kernel may not support it."
  echo "  Check: lsmod | grep bbr   /   modinfo tcp_bbr"
  exit 1
fi
