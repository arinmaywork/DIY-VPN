#!/usr/bin/env bash
# DIY-VPN health check — diagnose a sick server.
# Run:  sudo ./scripts/health-check.sh

set -uo pipefail

GRN='\033[0;32m'; RED='\033[0;31m'; YLW='\033[1;33m'; CYA='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'

pass() { echo -e "  ${GRN}✓${RST} $*"; }
fail() { echo -e "  ${RED}✗${RST} $*"; }
warn() { echo -e "  ${YLW}!${RST} $*"; }
hdr()  { echo -e "\n${BLD}${CYA}▶ $*${RST}"; }

[[ $EUID -eq 0 ]] || { echo "Run as root: sudo $0"; exit 1; }

#─── Public IP ────────────────────────────────────────────────────────────────
hdr "Public IP"
PUBLIC_IP="$(curl -fsS --max-time 5 https://api.ipify.org || echo unknown)"
echo "  $PUBLIC_IP"

#─── Services ─────────────────────────────────────────────────────────────────
hdr "Services"
for svc in xray hysteria-server hysteria fail2ban; do
  if systemctl list-unit-files | grep -q "^${svc}\."; then
    if systemctl is-active --quiet "$svc"; then
      pass "$svc is active"
    else
      fail "$svc is NOT active — try: sudo systemctl status $svc"
    fi
  fi
done

#─── Listening sockets ────────────────────────────────────────────────────────
hdr "Listening sockets"
if ss -tlnp 2>/dev/null | grep -q ':443 .*xray'; then
  pass "TCP/443 listening (xray)"
else
  fail "TCP/443 NOT listening for xray. Check: sudo journalctl -u xray -n 50"
fi
if ss -ulnp 2>/dev/null | grep -q ':443 .*hysteria'; then
  pass "UDP/443 listening (hysteria)"
else
  fail "UDP/443 NOT listening for hysteria. Check: sudo journalctl -u hysteria-server -n 50"
fi

#─── iptables ─────────────────────────────────────────────────────────────────
hdr "iptables (host firewall)"
if iptables -C INPUT -p tcp --dport 443 -j ACCEPT 2>/dev/null; then
  pass "TCP/443 ACCEPT rule present"
else
  fail "TCP/443 ACCEPT rule MISSING — run: sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT"
fi
if iptables -C INPUT -p udp --dport 443 -j ACCEPT 2>/dev/null; then
  pass "UDP/443 ACCEPT rule present"
else
  fail "UDP/443 ACCEPT rule MISSING — run: sudo iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT"
fi
if iptables -C INPUT -p udp --dport 20000:50000 -j ACCEPT 2>/dev/null; then
  pass "UDP 20000-50000 ACCEPT rule present"
else
  warn "UDP 20000-50000 ACCEPT rule missing (port-hopping won't work)"
fi

#─── Reachability test (loopback) ─────────────────────────────────────────────
hdr "Local reachability"
if timeout 3 bash -c "</dev/tcp/127.0.0.1/443" 2>/dev/null; then
  pass "Can connect to 127.0.0.1:443/tcp"
else
  fail "127.0.0.1:443/tcp not connectable — xray probably down"
fi

#─── BBR ──────────────────────────────────────────────────────────────────────
hdr "TCP congestion control"
CC="$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null)"
if [[ "$CC" == "bbr" ]]; then
  pass "BBR enabled"
else
  warn "Current cc is '$CC' (BBR not active). Run: sudo $(dirname "$0")/enable-bbr.sh"
fi

#─── Resource usage ───────────────────────────────────────────────────────────
hdr "Resource usage"
echo "  Load:    $(uptime | awk -F'load average:' '{print $2}')"
echo "  Memory:  $(free -h | awk '/Mem:/ {print $3 " used / " $2 " total"}')"
echo "  Disk:    $(df -h / | awk 'NR==2 {print $3 " used / " $2 " total ("$5")"}')"
echo "  Conns:   $(ss -s | head -1)"

#─── Reality target reachability ──────────────────────────────────────────────
hdr "Reality 'steal-from' target reachability"
if [[ -r /etc/diyvpn/credentials.env ]]; then
  # shellcheck source=/dev/null
  source /etc/diyvpn/credentials.env
  if timeout 5 openssl s_client -connect "${REALITY_DEST}:443" -servername "${REALITY_SNI}" </dev/null >/dev/null 2>&1; then
    pass "${REALITY_DEST}:443 reachable from this server (TLS handshake OK)"
  else
    fail "Cannot TLS-handshake to ${REALITY_DEST}:443. Reality clients will fail. Pick a different REALITY_DEST in /usr/local/etc/xray/config.json."
  fi
fi

#─── Public reachability test (best effort) ───────────────────────────────────
hdr "External reachability (best-effort, requires internet)"
if [[ "$PUBLIC_IP" != "unknown" ]]; then
  # We can't truly self-test from outside, but we can check open-port aggregator
  # Many of those are flaky/blocked, so we only print guidance
  echo "  From your laptop, try:"
  echo "    nc -vz $PUBLIC_IP 443"
  echo "    curl -v --max-time 5 https://$PUBLIC_IP/ -k"
  echo "  (curl will fail TLS — expected; we just want to see the connection open)"
fi

echo
echo -e "${BLD}Done.${RST} Share link: ${BLD}sudo ./scripts/generate-client-links.sh${RST}"
