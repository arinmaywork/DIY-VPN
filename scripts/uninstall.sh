#!/usr/bin/env bash
# Cleanly remove DIY-VPN: stops services, removes binaries, configs, and rules.
# DOES NOT touch SSH hardening, fail2ban, or kernel sysctl tuning (those are general goodies).

set -uo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0"; exit 1; }

echo "This will remove Xray, Hysteria2, their configs, and the iptables rules"
echo "added by DIY-VPN. SSH hardening, fail2ban, and BBR will be kept."
read -rp "Continue? [y/N] " ans
[[ "${ans,,}" == "y" ]] || { echo "Cancelled."; exit 0; }

echo "[*] Stopping services…"
systemctl disable --now xray.service              2>/dev/null || true
systemctl disable --now hysteria-server.service   2>/dev/null || true
systemctl disable --now hysteria.service          2>/dev/null || true

echo "[*] Removing Xray…"
bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ remove --purge 2>/dev/null || true
rm -rf /usr/local/etc/xray /var/log/xray

echo "[*] Removing Hysteria2…"
bash <(curl -fsSL https://get.hy2.sh/) --remove 2>/dev/null || true
rm -rf /etc/hysteria

echo "[*] Removing iptables rules…"
iptables -D INPUT -p tcp --dport 443 -j ACCEPT          2>/dev/null || true
iptables -D INPUT -p udp --dport 443 -j ACCEPT          2>/dev/null || true
iptables -D INPUT -p udp --dport 20000:50000 -j ACCEPT  2>/dev/null || true
ip6tables -D INPUT -p tcp --dport 443 -j ACCEPT         2>/dev/null || true
ip6tables -D INPUT -p udp --dport 443 -j ACCEPT         2>/dev/null || true
ip6tables -D INPUT -p udp --dport 20000:50000 -j ACCEPT 2>/dev/null || true
netfilter-persistent save >/dev/null 2>&1 || true

echo "[*] Removing credentials…"
rm -rf /etc/diyvpn

echo "[✓] DIY-VPN removed."
echo "    To also revert SSH/fail2ban/BBR, edit /etc/ssh/sshd_config,"
echo "    remove /etc/fail2ban/jail.d/sshd.local, and"
echo "    remove /etc/sysctl.d/99-diyvpn.conf."
