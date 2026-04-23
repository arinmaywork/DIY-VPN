# 02 — Server setup & installation

You have an Oracle Cloud VM with a public IP. You can SSH in as `ubuntu`. Good.

This document walks through:

1. Copy the project's `scripts/` folder to the server
2. Run the one-shot installer
3. Verify both services are up
4. Output the client share links

The installer handles **everything else**: Xray, Hysteria2, systemd services, firewall, BBR, log rotation, fail2ban, SSH hardening. You don't need to type each command yourself — but this doc explains what's happening so you can troubleshoot.

---

## Step 1 — Copy the scripts to your server

From your **local machine**, inside this repo's folder:

```bash
# Replace <IP> with your Oracle VM's public IP
scp -i ~/.ssh/diyvpn_ed25519 -r scripts configs ubuntu@<IP>:~/diyvpn/
```

(On Windows, use the same command in PowerShell — `scp` ships with modern Windows 10+.)

Then SSH in:

```bash
ssh -i ~/.ssh/diyvpn_ed25519 ubuntu@<IP>
```

---

## Step 2 — Run the installer

On the server:

```bash
cd ~/diyvpn
chmod +x scripts/*.sh
sudo ./scripts/install.sh
```

The installer will:

1. **Update the system** (`apt update && apt upgrade -y`)
2. **Install dependencies**: `curl`, `jq`, `qrencode`, `iptables-persistent`, `fail2ban`, `unzip`, `ca-certificates`
3. **Download Xray-core** (latest stable release, ARM64 build auto-detected)
4. **Download Hysteria2** (latest stable release)
5. **Generate credentials**:
   - A UUID for VLESS
   - A Reality X25519 keypair (private key stays on server, public key goes to clients)
   - A random `shortId` for Reality
   - A random Hysteria2 password
   - A random Hysteria2 obfuscation password
6. **Pick the Reality "steal-from" target**. Default is `www.microsoft.com` (stable, global, well-provisioned). You can change this.
7. **Write `/usr/local/etc/xray/config.json`** and **`/etc/hysteria/config.yaml`**
8. **Create systemd services**: `xray.service`, `hysteria.service`
9. **Fix Oracle's iptables** — Oracle's stock Ubuntu has aggressive DROP rules on `INPUT`. The script:
   - Inserts ACCEPT rules for TCP 443 and UDP 443 + the port-hop range **before** the DROP rule
   - Persists them with `netfilter-persistent save`
10. **Enable BBR** congestion control + kernel tuning (huge latency & throughput win)
11. **Harden SSH**: disables password auth, disables root login. (It won't change the port — you can do that manually.)
12. **Install fail2ban** with SSH jail
13. **Enable + start both services**
14. **Print a summary** with the server IP and both share URIs
15. **Print QR codes** to the terminal for phone clients

---

## Step 3 — What the installer prints at the end

You'll see a block like this:

```
════════════════════════════════════════════════════════════════════
  DIY-VPN install complete
════════════════════════════════════════════════════════════════════

  Server IP:          203.0.113.42
  Reality port:       443/tcp
  Hysteria2 port:     443/udp (+ 20000-50000 port hopping)

  VLESS + Reality share link:
  vless://c4a3...@203.0.113.42:443?security=reality&sni=www.microsoft.com&...

  Hysteria2 share link:
  hysteria2://p4ssw0rd@203.0.113.42:443/?obfs=salamander&obfs-password=...

  [QR CODE for VLESS]
  [QR CODE for Hysteria2]

  Configs:
    /usr/local/etc/xray/config.json
    /etc/hysteria/config.yaml

  Regenerate share links anytime:   sudo ./scripts/generate-client-links.sh
════════════════════════════════════════════════════════════════════
```

**Save these share links somewhere safe.** They are the credentials for your VPN. Anyone with these can use your server.

---

## Step 4 — Verify both services are running

```bash
sudo systemctl status xray --no-pager
sudo systemctl status hysteria --no-pager
```

Both should be **active (running)**. If not, check logs:

```bash
sudo journalctl -u xray -n 50 --no-pager
sudo journalctl -u hysteria -n 50 --no-pager
```

Quick port sanity check from the server itself:

```bash
sudo ss -tlnp | grep ':443'       # should show xray listening on TCP 443
sudo ss -ulnp | grep ':443'       # should show hysteria listening on UDP 443
```

From your **local machine** (a quick "can I even reach the ports?" check):

```bash
nc -vz <IP> 443                    # TCP 443 should say "succeeded"
nc -vzu <IP> 443                   # UDP check is less reliable; use client to verify
```

If TCP 443 fails from outside → you have a firewall issue (re-check Oracle VCN security list).

---

## Step 5 — Add the VPN to your clients

Continue to **[03-CLIENT-SETUP.md](03-CLIENT-SETUP.md)**.

---

## Manual / advanced: what if I want to do it myself?

If you'd rather configure by hand (or understand every moving piece), here's the overview.

### SSH hardening (optional but recommended)

```bash
sudo nano /etc/ssh/sshd_config
```

Set / uncomment:
```
PasswordAuthentication no
PermitRootLogin no
Port 62022        # or another non-standard port
```

Also add the new port to Oracle's VCN security list **before** you restart sshd, or you'll lock yourself out.

```bash
sudo systemctl restart ssh
```

### BBR + TCP tuning

```bash
cat <<'EOF' | sudo tee /etc/sysctl.d/99-diyvpn.conf
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
EOF
sudo sysctl --system
sysctl net.ipv4.tcp_congestion_control  # should output "bbr"
```

### Oracle iptables fix

Oracle's Ubuntu image has this infuriating default:
```
-A INPUT -j REJECT --reject-with icmp-host-prohibited
```
…right after accepting SSH. Anything you try to listen on after that is rejected despite VCN allowing it.

Fix:
```bash
sudo iptables -I INPUT 6 -p tcp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -p udp --dport 443 -j ACCEPT
sudo iptables -I INPUT 6 -p udp --dport 20000:50000 -j ACCEPT
sudo netfilter-persistent save
```

(`-I INPUT 6` inserts at position 6, which puts us before the REJECT line. Verify with `sudo iptables -L INPUT --line-numbers`.)

### Manually install Xray

```bash
bash -c "$(curl -L https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
```

### Manually install Hysteria2

```bash
bash <(curl -fsSL https://get.hy2.sh/)
```

Then edit configs (templates in `configs/`) and start services:
```bash
sudo systemctl enable --now xray hysteria
```

---

Next → [03-CLIENT-SETUP.md](03-CLIENT-SETUP.md)
