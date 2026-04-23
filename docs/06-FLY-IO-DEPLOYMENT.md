# 06 — Fly.io deployment (Oracle alternative, ~$0–3/month)

Oracle's signup is notoriously flaky. This is the backup path, and it's simple:
one script on your laptop deploys a container to Fly.io that runs Xray
(VLESS+Reality) and Hysteria2 together. Credentials generate automatically and
persist on a Fly volume.

## What it costs

Fly restructured its free tier in late 2024. Here's the real math as of 2026:

| Item | Monthly |
|---|---|
| `shared-cpu-1x` with 256 MB RAM (always on) | ~$1.94 |
| 1 GB persistent volume | ~$0.15 |
| Outbound bandwidth (first 100 GB from NA/EU regions) | $0 |
| Outbound bandwidth (first ~30 GB from Asia regions) | $0 |
| Dedicated IPv6 | $0 |
| Dedicated IPv4 (**only if your network is v4-only**) | ~$2 |
| **Typical total** | **$2–4/month, inside Fly's $5/mo included credits** |

So effectively **free** for normal browsing/work. If you stream 4K all day you'll
burn through the free egress and pay a few dollars. Still way cheaper than any
commercial VPN.

If this breaks your "$0 forever" requirement, fall back to **Hetzner CX22
€4.51/mo** — our main `scripts/install.sh` works there unchanged.

---

## Prerequisites (5 minutes, one-time)

### 1. Install `flyctl`

**macOS:**
```bash
brew install flyctl
# or:  curl -L https://fly.io/install.sh | sh
```

**Windows (PowerShell):**
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

**Linux:**
```bash
curl -L https://fly.io/install.sh | sh
```

Restart your terminal after install. Verify: `flyctl version`.

### 2. Install `jq`

macOS: `brew install jq` · Debian/Ubuntu: `sudo apt install jq` · Windows: `winget install jqlang.jq`

### 3. Create a Fly account (free, card required)

```bash
flyctl auth signup
```

This opens a browser. You'll need:
- Email (a fresh one is fine)
- **Credit/debit card** — Fly does NOT let you skip this even for the free tier.
  They verify with a small auth hold. Unlike Oracle, Fly's card verification
  is much more permissive and rarely rejects.

If you already have an account:
```bash
flyctl auth login
```

Confirm it worked:
```bash
flyctl auth whoami
```

---

## Pick a region

Fly has regions worldwide. For China access, in priority order:

| Code | Location | Notes |
|---|---|---|
| **`nrt`** | Tokyo | Best default for China |
| **`sin`** | Singapore | Solid second choice |
| `hkg` | Hong Kong | Was best-for-China; Fly has scaled back HK availability |
| `sjc` | San Jose, US West | Good if Tokyo is crowded |
| `lax` | Los Angeles, US West | Fine |
| `fra` | Frankfurt | Good for Europe; high latency to China |

List all regions: `flyctl platform regions`.

For **users in India**, `sin` (Singapore) and `bom` (Mumbai) are closest. Mumbai
(`bom`) has great latency from India but routes to China are worse.

---

## Deploy (one command)

From your local copy of this repo:

```bash
cd flyio
chmod +x deploy.sh
./deploy.sh
```

It will:
1. Check that `flyctl` and `jq` are installed and you're logged in
2. Prompt for an app name (or auto-generate one)
3. Create the Fly app
4. Create a 1 GB persistent volume called `diyvpn_data`
5. Allocate a dedicated IPv6 (free). If you set `ALLOCATE_V4=yes`, also allocate dedicated IPv4 ($2/mo)
6. Render `fly.toml` from the template
7. Build the Docker image and deploy it
8. Wait for the container to generate credentials
9. SSH in, pull the credentials, and print share links for your clients

**To pick region or add IPv4:**
```bash
REGION=sin ALLOCATE_V4=yes ./deploy.sh
```

**Expected output at the end:**
```
════════════════════════════════════════════════════════════════════
  DIY-VPN deployed to Fly.io
════════════════════════════════════════════════════════════════════
  App:     https://fly.io/apps/diyvpn-abc123
  Region:  nrt
  IPv6:    2a09:8280:1::xxxx
  IPv4:    66.241.xxx.xxx  (dedicated, $2/mo)

VLESS (IPv4):
vless://...@66.241.xxx.xxx:443?security=reality&...#DIY-VPN Reality (IPv4)

Hysteria2 (IPv4):
hysteria2://...@66.241.xxx.xxx:443/?obfs=salamander&...#DIY-VPN Hy2 (IPv4)
```

Copy those links into your clients per **[03-CLIENT-SETUP.md](03-CLIENT-SETUP.md)**.

---

## IPv4 vs IPv6 — which do you actually need?

- **IPv6 (free)** is fine IF your network supports it:
  - Most US/EU home broadband in 2026: yes
  - Most mobile data in 2026: yes
  - Office wifi: often no
  - Chinese home broadband: yes on China Telecom/China Mobile, patchy on China Unicom
- **IPv4 ($2/mo)** is universal. If in doubt, allocate it.

Quick test from the client:
- macOS/Linux: `curl -6 https://ifconfig.co` — if you get an IPv6, you have v6.
- Windows: `curl -6 https://ifconfig.co` in PowerShell.
- iPhone/Android: visit [https://test-ipv6.com](https://test-ipv6.com).

If v6 test gives nothing, you need IPv4.

---

## Add to your clients

Same procedure as the main flow → follow **[03-CLIENT-SETUP.md](03-CLIENT-SETUP.md)**. Two small changes when the VPN is on Fly.io:

1. **Use the raw IP, never the `.fly.dev` hostname.** The hostname resolves to
   Fly's shared edge, which doesn't speak Reality/Hysteria2. Connections will
   just fail silently.
2. **For IPv6, wrap in brackets** in client apps that accept `host:port` form
   — e.g., `[2a09:8280:1::xxxx]:443`. Client apps that parse share-link URIs
   (scan a QR, paste a `vless://` link) handle this automatically.

---

## Daily operations

| Task | Command |
|---|---|
| Live log tail | `flyctl logs --app YOUR-APP` |
| Restart the VPN | `flyctl machine restart $(flyctl machines list --app YOUR-APP --json \| jq -r '.[0].id')` |
| SSH into the container | `flyctl ssh console --app YOUR-APP` |
| Re-read your credentials | `flyctl ssh console --app YOUR-APP -C "cat /data/credentials.env"` |
| Re-read share links | `flyctl ssh console --app YOUR-APP -C "cat /data/share-links.txt"` |
| Stop the app (no billing) | `flyctl apps destroy YOUR-APP` |
| Check costs | `flyctl orgs show personal` → dashboard |

---

## Upgrade Xray / Hysteria2

The Dockerfile pulls the **latest release** at build time. To bump:

```bash
cd flyio
flyctl deploy --app YOUR-APP --no-cache
```

`--no-cache` forces a fresh image so the latest binaries are downloaded.

---

## Rotate credentials

If your UUID/password got leaked:

```bash
flyctl ssh console --app YOUR-APP
# inside the container:
rm /data/credentials.env
exit
flyctl machine restart $(flyctl machines list --app YOUR-APP --json | jq -r '.[0].id')
# wait ~30s, then on your laptop:
flyctl ssh console --app YOUR-APP -C "cat /data/credentials.env"
```

Then regenerate share links (or just re-run `deploy.sh` — it's idempotent).

---

## Common Fly-specific issues

### "Your organization doesn't have a payment method"

Add a card in the Fly dashboard first: https://fly.io/dashboard/personal/billing

### "The app requires an IPv4 address"

You didn't allocate one. Run:
```bash
flyctl ips allocate-v4 --app YOUR-APP
```
This costs $2/month.

### Deploy fails with "volume not in region"

The volume is tied to the region you created it in. If you change regions later, recreate the volume:
```bash
flyctl volumes destroy diyvpn_data --app YOUR-APP
flyctl volumes create diyvpn_data --app YOUR-APP --region NEW_REGION --size 1 --yes
flyctl deploy --app YOUR-APP
```

### "Machine launch failed: capacity"

The region is full. Pick another: `REGION=sin ./deploy.sh`.

### Connection fails but `flyctl logs` shows xray running

Check whether you're connecting to the `.fly.dev` hostname by accident — this
**will not work**. The share links already use the raw IP. Verify:
```bash
flyctl ips list --app YOUR-APP
```
and make sure the IP in your client matches.

### Container OOMs on deploy / keeps restarting

256 MB is tight when Xray is fetching geo-databases on boot. Bump to 512 MB in `fly.toml`:
```toml
[[vm]]
  cpu_kind    = "shared"
  cpus        = 1
  memory_mb   = 512
```
Then `flyctl deploy --app YOUR-APP`. Cost increase: ~$2/month.

### Hysteria2 QR fails but VLESS QR works

Some Chinese networks drop UDP above 443 — Hysteria2 stops working even though
port 443 is open. This is your cue to use VLESS+Reality until you're on a
different network. Both share links are already in your client — just flip to
the Reality server with one tap.

---

## When to move off Fly.io

Fly is great for personal VPN but has real limits:

- **Bandwidth:** 100 GB free from NA/EU, less from Asia. Streaming burns through this fast.
- **Egress cost:** if you exceed free allowance, $0.02/GB (NA) to $0.12/GB (ROW).
- **UDP port hopping:** Fly only forwards UDP 443 (not 20000–50000). If your
  ISP throttles UDP 443 specifically, Hysteria2 on Fly loses its port-hopping
  advantage.
- **IPv4 is $2/mo:** paying for v4 means it's not quite $0.

If any of these bite, your next stop is **Hetzner CX22 at €4.51/month**. Our
main [scripts/install.sh](../scripts/install.sh) works on Hetzner unchanged —
port hopping, unmetered bandwidth, and free IPv4+IPv6 included. See
[01-HOSTING.md](01-HOSTING.md) for the Hetzner signup walkthrough.

---

Next → [07-TELEGRAM-BOT.md](07-TELEGRAM-BOT.md) to deploy the bot and run the
whole thing from Telegram (recommended — `/setup ios`, `/qr`, `/up`, `/down`,
`/devices`, etc.)

If you'd rather drive it by hand → [03-CLIENT-SETUP.md](03-CLIENT-SETUP.md) to
paste the share links from deploy output into your Windows/macOS/Android/iOS
clients.

Troubleshooting general connection / speed / GFW issues → [04-TROUBLESHOOTING.md](04-TROUBLESHOOTING.md)
