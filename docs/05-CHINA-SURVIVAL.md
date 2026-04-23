# 05 — China survival guide (long-term GFW tips)

Reality + Hysteria2 is currently the strongest free self-hosted combo for China. But the GFW is an adversarial, constantly-updating system. Over months and years, you should expect **occasional disruptions**. This doc is the playbook for keeping your VPN alive long-term.

---

## The threat model

The GFW does three main things:

1. **Static blocklists** — known VPN provider IP ranges are simply dropped.
2. **Deep packet inspection (DPI)** — inspects traffic to identify protocol fingerprints (OpenVPN, WireGuard, Shadowsocks-vanilla, etc.) and drops/throttles them.
3. **Active probing** — when the GFW sees a suspicious TLS handshake, it probes the port from a GFW machine pretending to be a client. If the server responds in a non-standard way, the IP gets tagged.

Our design sidesteps all three:
- **Static blocklists:** your Oracle IP is likely not on any blocklist when you start — and you can rotate IPs for free.
- **DPI fingerprinting:** Reality produces a handshake indistinguishable from a real connection to www.microsoft.com; Hysteria2+salamander produces QUIC traffic with randomized framing.
- **Active probing:** Reality's authenticated handshake rejects all probes silently — a probe from the GFW sees the exact same response www.microsoft.com would have given.

But nothing is perfectly future-proof. Here's how to stay ahead.

---

## Routine maintenance (do these monthly)

1. **Log into Oracle Cloud console.** Oracle deletes idle "always-free" resources after ~60 days of inactivity.
2. **Update the server:**
   ```bash
   sudo apt update && sudo apt upgrade -y
   sudo systemctl restart xray hysteria-server
   ```
3. **Update Xray & Hysteria2** (every 2–3 months, or when a security/stealth release comes out):
   ```bash
   bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install
   bash <(curl -fsSL https://get.hy2.sh/)
   sudo systemctl restart xray hysteria-server
   ```

---

## When your IP gets blocked (it will, eventually)

### Signal: `ping <ip>` from China returns 100% loss, but `ping 8.8.8.8` works.

#### Option 1 — Rotate the public IP (free, 5 min)

Oracle gives you 2 free reserved public IPv4 addresses. You can swap between them:

1. Console → Compute → Instances → your VM → Attached VNICs → primary VNIC → IP addresses.
2. Delete the current "ephemeral" public IP (or detach the reserved one).
3. Create/attach a new reserved public IP.
4. Wait 1–2 minutes. Get new IP.
5. On server: `sudo rm /etc/diyvpn/credentials.env` and re-run `install.sh` to regenerate share links with the new IP — or just edit `PUBLIC_IP=` in the file and run `sudo ./scripts/generate-client-links.sh`.
6. Update share links on all your clients.

If Oracle's IP pool was contaminated (all their Seoul IPs got blocked, etc.), you may still get a bad IP. Try the next option.

#### Option 2 — Redeploy in a different region

1. Terminate the current VM.
2. Create a new VM in a different region (Korea → Japan → Singapore → US West).
3. `scp` the `scripts/` and `configs/` folders to the new VM.
4. Run `install.sh`. Update clients with new share links.

This is also your answer if a **whole region** is currently contaminated, which does happen.

#### Option 3 — Switch to IPv6 primary

Oracle assigns a `/56` IPv6 block per VCN for free. If you enable IPv6 on the VCN + subnet + VNIC, your server has a public IPv6 address. IPv6 is less aggressively filtered by the GFW. Most Chinese ISPs (China Telecom especially) now give IPv6 at home. Your clients can prefer v6:
- In client apps, enter the IPv6 address wrapped in brackets: `[2603:c020:...]:443`.
- Enabling IPv6 on Oracle: Console → Networking → VCN → Edit → Enable IPv6; Subnet → Edit → Enable IPv6; VNIC → IPv6 addresses → Assign.

This alone can resurrect a "dead" server in minutes.

---

## Advanced: add Cloudflare as a front (for VLESS-WebSocket fallback)

If your server IP is totally burned and even new IPs get blocked quickly, a Cloudflare-fronted WebSocket is a nuclear option:

1. Put your server behind a domain you own (a free `.tk` / `.ga` / `.xyz` domain works).
2. Point the domain's A record at your server via **Cloudflare's proxy (orange cloud)**.
3. Change Xray to expose an additional inbound on port 80/443 with `vless + ws + tls`, with the same UUID.
4. Clients connect to your domain on port 443 → Cloudflare's edge terminates TLS → Cloudflare connects to your server's origin → Xray decrypts WS + VLESS.
5. To the GFW, this looks like a normal HTTPS request to Cloudflare — and Cloudflare has tens of millions of IPs.

Trade-offs: Cloudflare limits WebSocket to 100s idle timeout (Hysteria2 / Reality do not work through CF proxy — they're not HTTP). You'd use this as an emergency fallback alongside Reality + Hy2, not as the primary. The extra inbound costs nothing; I can provide the config if you need it.

---

## Avoid behaviors that get your IP burned

- **Don't publish your config** on GitHub, Telegram channels, Twitter, etc. The GFW crawls public VPN configs. Sharing with 3 friends privately is fine.
- **Don't let lots of people use it**. GFW monitors IPs with many unique clients.
- **Don't BitTorrent on it**. Our config blocks bittorrent by default anyway — leave that block in.
- **Don't run port scans or anything "noisy"** from the server. It flags your IP on external threat feeds.
- **Change `REALITY_SNI`** every few months. Microsoft's cert chain very rarely rotates; but you don't want your server's Reality handshake to be identified as "always says it's Microsoft" over years.

---

## Pre-holiday / sensitive dates

The GFW tightens significantly around:
- **October 1** (PRC National Day) — weeks before and during
- **June 4** (Tiananmen anniversary) — 1-2 weeks before/during
- **Two Sessions** (March, annual NPC meeting)
- **Major Party Congresses**

During these windows, expect more aggressive blocking, including brand-new server IPs getting blocked within hours. Have a second server (different region) pre-provisioned as backup. The whole install is scriptable in 5 minutes — keep your Ansible/script ready.

---

## A note on "free forever"

Oracle's Always-Free is the best deal on the internet right now, but:
- Oracle has quietly tightened rules multiple times (region restrictions on new signups, capacity limits).
- If you rely on this for work, **don't have only one server**. Have a plan to move to paid infrastructure (Hetzner €4.5/mo) if Oracle ever forces an upgrade or you get caught in a billing glitch.

Backup strategies that cost $0:
- Keep your `install.sh` and `credentials.env` in a private Git repo so redeploy is 3 commands.
- Keep a Fly.io account as a hot spare (tiny, but buys you hours of access while you redeploy somewhere better).

---

## Psychological note

Anti-censorship is not a "set and forget" project. It's a moving target. Expect to spend maybe 30 minutes/month on maintenance in normal times, and more during sensitive dates. If that's too much, consider a paid commercial service (Mullvad, Proton) — though those are blocked faster inside China than a private setup like this.

Your private Reality + Hy2 setup will outlast 99% of commercial services inside China for one reason: **you are one person, not a target worth burning a GFW rule on.**

---

That's it. Back to [README](../README.md).
