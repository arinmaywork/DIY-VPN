# 04 — Troubleshooting

Work through these in order — most issues are in the first three sections.

If stuck, run the health check:
```bash
sudo ./scripts/health-check.sh
```
It will flag most problems automatically.

---

## A — Connection fails (can't connect to server at all)

### A.1 — Services not running

```bash
sudo systemctl status xray --no-pager
sudo systemctl status hysteria-server --no-pager
```

If either says "failed" or "inactive":
```bash
sudo journalctl -u xray -n 50 --no-pager
sudo journalctl -u hysteria-server -n 50 --no-pager
```

Common causes:
- **Config file syntax error** → `sudo /usr/local/bin/xray test -c /usr/local/etc/xray/config.json` (for Xray); `/usr/local/bin/hysteria server -c /etc/hysteria/config.yaml` (for Hysteria2).
- **Port in use** → `sudo ss -tlnp | grep :443` to see what's squatting on 443.
- **Bad Reality keys** → re-run the installer, or regenerate with `/usr/local/bin/xray x25519`.

### A.2 — Firewall (the #1 cause)

Oracle Cloud has TWO firewalls. Check BOTH.

**Host iptables:**
```bash
sudo iptables -L INPUT --line-numbers
```
You should see `ACCEPT` lines for `tcp dpt:443`, `udp dpt:443`, and `udp dpts:20000:50000` BEFORE any `DROP` or `REJECT` line. If not:
```bash
sudo iptables -I INPUT 1 -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 1 -p udp --dport 443 -j ACCEPT
sudo iptables -I INPUT 1 -p udp --dport 20000:50000 -j ACCEPT
sudo netfilter-persistent save
```

**Oracle VCN security list:**
Console → Networking → Virtual Cloud Networks → *(your VCN)* → Security Lists → *Default Security List* → Ingress Rules. Make sure you have:
- TCP 443, source 0.0.0.0/0
- UDP 443, source 0.0.0.0/0
- UDP 20000-50000, source 0.0.0.0/0

### A.3 — Outside probe

From your **local machine**:
```bash
nc -vz <SERVER_IP> 443          # TCP 443 reachable?
```
- Says "succeeded" → firewall is open, look at config/protocol.
- Says "refused" → something on server refused (service down).
- Says "timed out" → firewall is blocking (VCN or iptables).

---

## B — Connects, but "no internet" in browser

### B.1 — Wrong routing mode in client

In v2rayN / v2rayNG / FoxRay / NekoBox / Shadowrocket / Streisand, switch to **Global** routing to rule out geo-routing. If it works in Global, your previous mode was routing your target domain as "direct" (bypassing VPN).

### B.2 — DNS issue

Some clients require you to enable "DNS through VPN". Check client settings → DNS. Set DNS to `1.1.1.1` or `8.8.8.8` for the tunnel.

### B.3 — Reality SNI unreachable from server

If the Reality target is blocked from your server's network, Reality breaks. Test from the server:
```bash
openssl s_client -connect www.microsoft.com:443 -servername www.microsoft.com < /dev/null
```
You should see a successful TLS handshake + certificate chain. If not, pick a different target and re-run installer (or edit `/usr/local/etc/xray/config.json` — replace `www.microsoft.com` in `dest` and `serverNames`):

Good alternatives (stable, TLS 1.3 + X25519):
- `www.apple.com`
- `www.icloud.com`
- `www.yahoo.co.jp` (good for Asia)
- `www.bing.com`
- `www.lovelive-anime.jp`

Avoid: Google/Gmail (aggressive TLS fingerprinting), Cloudflare-fronted sites (they do weird TLS things), any CDN edge.

---

## C — Connects, but extremely slow

### C.1 — Is BBR enabled?

```bash
sysctl net.ipv4.tcp_congestion_control    # should print "bbr"
```
If not: `sudo ./scripts/enable-bbr.sh`.

### C.2 — Route quality (the usual culprit from China)

You can't control the route from your ISP to your VM — but you can **measure** it.

Run `mtr` from the server back to a known China host (requires installing mtr: `sudo apt install mtr-tiny`):
```bash
mtr -rwc 50 114.114.114.114       # 114 DNS, a China Telecom DNS
```
Packet loss > 5% at any hop = bad. If loss is on your provider's hops, the only fix is to try another **region** (re-deploy). If loss is on the China side, try a different protocol — Hysteria2 is much more forgiving of loss than TCP.

### C.3 — Oracle's network egress is throttled

Oracle's Always-Free has a soft throttle when sustained high throughput is detected to prevent abuse. Short bursts (e.g., a Zoom call) are unaffected. Long sustained 500+ Mbps downloads may be slowed. Splitting traffic across Hysteria2 + Reality helps.

### C.4 — Use Hysteria2 if on mobile data or lossy wifi

Hy2's QUIC + custom BBR-like cc handles loss dramatically better than TCP Reality.

### C.5 — Turn off Hysteria's bandwidth cap

If you set `bandwidth.up/down` too low in the config, the client gets slowed. Our default is `1 gbps` — if you edited it down, fix it.

---

## D — Works for a while, then stops

This is the classic "GFW detected my server and blocked the IP" symptom, especially for heavy users. Signs:
- TCP SYNs from you reach server but server's SYN-ACKs never make it back to you (you can confirm by checking `sudo tcpdump -i any port 443` on the server — if you see SYNs from your IP, you're reachable).
- `ping` from China gets 100% loss to the server, but other servers work.

### Mitigations

1. **Change the public IP.** In Oracle: detach the ephemeral public IP from the VNIC, attach a new reserved public IP (free), reboot if needed. Note: Oracle caps you at 2 free reserved IPv4s, and heavy rotation may trip abuse checks. See [05-CHINA-SURVIVAL.md](05-CHINA-SURVIVAL.md) for the long-term strategy.
2. **Spin up a new VM** in a different region and reinstall. Old VM can be deleted.
3. **Switch to IPv6.** Most Chinese ISPs now provide IPv6 and many GFW devices are less effective on IPv6. Our configs listen on IPv6 automatically (the `0.0.0.0` listener also accepts v4, and ensure you added the IPv6 address to clients).
4. **Add Cloudflare Tunnel as a front.** Described in [05-CHINA-SURVIVAL.md](05-CHINA-SURVIVAL.md).

### Blocked only on some networks?

If your home wifi can't reach the VPN but your phone data can → your ISP or router is blocking. Check router DNS settings (some Chinese routers have built-in censorship).

---

## E — Reading logs

```bash
# Live-tail both services
sudo journalctl -u xray -u hysteria-server -f

# Last 200 lines
sudo journalctl -u xray -n 200 --no-pager
```

Xray log level is set to `warning` by default — you'll only see problems. If you need more detail temporarily, edit `/usr/local/etc/xray/config.json`, change `"loglevel": "warning"` to `"debug"`, `sudo systemctl restart xray`. **Switch back to `warning` after you finish debugging** — debug logs can be verbose and potentially log endpoints.

---

## F — Oracle instance got deleted / "always free" no longer free?

Oracle has been known to delete long-idle always-free accounts. Mitigations:
- Log into the Oracle Cloud console at least once every 30 days.
- Keep some low-level activity on the VM — SSH in occasionally, run `apt upgrade`.
- Don't attach a paid trial credit to the account — some accounts auto-convert to a paid hibernation state when trial credits expire, which counterintuitively deletes always-free resources. You want a **pure always-free** account, never upgraded.

If your account is suddenly billed or VMs deleted, your options are:
1. Create a new Oracle account with a different email + card.
2. Move to Plan B (Google e2-micro) or Plan E (cheap Hetzner / RackNerd).

---

## G — SSH locked myself out

Remember the `ubuntu` user's home, `~/.ssh/authorized_keys`. If you still have the Oracle console:

1. Console → Compute → Instances → your instance → **Console Connection** (serial console).
2. Create a console connection, open it in the browser.
3. Log in as the `ubuntu` user (if a password was ever set) or enter via serial.

If all else fails, destroy and recreate the VM. Save your `credentials.env` first if possible (scp before locking out).

---

Still stuck? Open `sudo ./scripts/health-check.sh` output and check each failed line against this doc's section with the same keyword.

---

Next → [05-CHINA-SURVIVAL.md](05-CHINA-SURVIVAL.md)
