# DIY-VPN

> Your own self-hosted VPN — VLESS+Reality and Hysteria2 on one container,
> controlled end-to-end from a Telegram chat, running effectively free on
> Fly.io's included credits. China-resistant by design.

If you've ever wanted a VPN that (1) doesn't log you, (2) can't be fingerprinted
by the Great Firewall, (3) costs ~$0/month, and (4) you can start/stop from
your phone without opening a terminal — this repo builds it.

---

## What you get

**Two stealth protocols on one machine, both on port 443:**

- **VLESS + Reality** (TCP/443) — the current state-of-the-art anti-censorship
  protocol. To an observer, every connection is indistinguishable from a real
  TLS handshake with `microsoft.com` (because it literally is one, up until the
  auth step).
- **Hysteria2** (UDP/443 with Salamander obfuscation) — QUIC-based, much faster
  than TCP on lossy or high-latency links (e.g. trans-Pacific). Great for 4K
  streaming and video calls.

**A Telegram bot that fronts the whole system**, so a new device goes from zero
to connected in under a minute:

```
You (in Telegram):  /setup ios
Bot:                [step-by-step iOS walkthrough + App Store link]
You:                /qr iphone
Bot:                [VLESS QR] [Hysteria2 QR]
You (in V2Box):     tap +, scan, connect. Done.
```

**Full lifecycle control from Telegram:** `/status`, `/up`, `/down`, `/restart`,
`/ipv4_add`, `/ipv4_release`, `/adduser`, `/kick`, `/rotate`, `/devices`,
`/logs` — see the [command reference](#telegram-bot-commands) below.

---

## Cost

On Fly.io, using their $5/month included credit:

| Component | Monthly |
|---|---|
| VPN machine (`shared-cpu-1x@256MB`, Singapore/Tokyo) | ~$1.94 |
| Telegram bot machine (same size, always-on) | ~$1.94 |
| 1 GB persistent volume (for credentials) | ~$0.15 |
| Dedicated IPv6 | $0 |
| Outbound bandwidth (first 100 GB NA/EU, ~30 GB Asia) | $0 |
| Dedicated IPv4 (**only if you need it**) | $2 |
| **Typical total** | **$2–4/month, fully inside the $5 included credit → $0 out of pocket** |

If you're a heavy streamer who'll blow past the bandwidth allowance, `/down`
the VPN from Telegram when you're not using it and you cap yourself at ~$0.

**Comparison**: commercial VPNs are $5–12/month with worse jurisdiction
guarantees and shared IPs that streaming services already block. This is
cheaper, private, and the IP is yours alone.

---

## Quick start (≈20 minutes, end to end)

Prerequisites on your machine: `flyctl`, `jq`, a credit card for Fly signup,
a Telegram account.

### 1. Deploy the VPN

```bash
git clone https://github.com/arinmaywork/DIY-VPN.git
cd DIY-VPN/flyio
chmod +x deploy.sh
REGION=sin ./deploy.sh         # pick nrt/sin/hkg/sjc/fra — see docs/06 for guidance
```

The script creates a Fly app, persistent volume, allocates a dedicated IPv6,
builds the container, deploys it, and prints your share links. **~5–10 min.**

If your network is IPv4-only (most mobile carriers in India/China), add
`ALLOCATE_V4=yes` — costs an extra $2/month, still inside the free credit:

```bash
REGION=sin ALLOCATE_V4=yes ./deploy.sh
```

### 2. Create a Telegram bot

Open [@BotFather](https://t.me/BotFather) in Telegram → `/newbot` → pick a
name and username → save the token (looks like `1234567890:ABC-DEF...`).

Find your own Telegram user ID via [@userinfobot](https://t.me/userinfobot).

### 3. Deploy the bot

```bash
cd ../telegram-bot
chmod +x deploy.sh
VPN_APP_NAME=diyvpn-xxxxx ./deploy.sh    # use the app name from step 1
```

The script prompts for the bot token + your user ID, mints a Fly API token,
creates a second Fly app, sets all three as secrets, and deploys. **~3 min.**

### 4. Test

In Telegram, find your bot and send `/start`. If it replies, send `/help` for
the full menu. Typical first flow:

```
/setup ios       — walkthrough for iPhone
/qr              — QR codes to scan into your client
/status          — confirm the VPN is up
```

---

## Architecture

```
┌──────────────┐    Telegram Bot API    ┌────────────────────────┐
│  You (TG)    │ ───────────────────▶   │  Bot machine            │
│  /qr, /up …  │ ◀───────────────────   │  diyvpn-sgad-bot        │
└──────────────┘                        │  python-telegram-bot   │
                                        │  + flyctl               │
                                        └───────────┬─────────────┘
                                                    │ Fly Machines API
                                                    │ + flyctl ssh exec
                                                    ▼
       Your device ─┬─ VLESS Reality (TCP 443) ─▶ ┌──────────────────┐
       (V2Box, etc) │                             │ VPN machine       │
                    └─ Hysteria2 (UDP 443) ─────▶ │ diyvpn-sgad       │
                                                  │ Xray + Hysteria2   │
                                                  │ (Alpine container) │
                                                  └────────┬───────────┘
                                                           ▼
                                                     Open Internet
```

The bot lives in its own Fly app. When you `/down` the VPN to save bandwidth,
the bot stays up so you can `/up` it later from anywhere.

---

## Telegram bot commands

| Category | Command | What it does |
|---|---|---|
| **Power** | `/status` | Machine state, IPs, region |
| | `/up` | Start the VPN machine |
| | `/down` | Stop the VPN machine (no traffic billed) |
| | `/restart` | Rolling restart |
| **Share links / QR** | `/links [name]` | Paste-able `vless://` and `hysteria2://` URIs |
| | `/qr [name]` | Sends scannable QR PNGs for both protocols |
| **IPv4** | `/ipv4` | List current IPs |
| | `/ipv4_add` | Allocate dedicated IPv4 (+$2/mo) |
| | `/ipv4_release` | Drop the dedicated IPv4 |
| **Devices** | `/devices` | List users + live online sessions + byte counters |
| | `/adduser <name>` | Provision a fresh UUID (new device) |
| | `/kick <name>` | Remove a device |
| | `/rotate yes` | Wipe all credentials + regenerate (nuclear) |
| **Clients** | `/apps` | One-line overview of recommended clients per OS |
| | `/setup <platform>` | Step-by-step walkthrough (`ios`, `android`, `windows`, `macos`, `linux`) |
| **Misc** | `/logs` | Last 50 lines of VPN logs |
| | `/whoami` | Your Telegram user ID |
| | `/help` | Full command list |

Access is restricted to the Telegram user IDs listed in `TG_ALLOWED_USERS`
(set at deploy time). Every other user gets a polite refusal.

---

## Client apps per platform

The bot's `/setup <platform>` replies with the full walkthrough, but for
reference:

| Platform | Recommended | Why |
|---|---|---|
| iPhone / iPad | [V2Box](https://apps.apple.com/app/v2box-v2ray-client/id6446814690) | Free, App Store, both protocols |
| macOS | [V2Box](https://apps.apple.com/app/v2box-v2ray-client/id6446814690) | Same app as iOS, menu bar toggle |
| Android | [v2rayNG](https://github.com/2dust/v2rayNG/releases/latest) | Reference VLESS+Reality client |
| Windows | [Nekoray](https://github.com/MatsuriDayo/nekoray/releases/latest) | Portable, full protocol support |
| Linux | [Nekoray (AppImage)](https://github.com/MatsuriDayo/nekoray/releases/latest) | Same UI, single binary |

Each platform's `/setup` walkthrough gives you 2 alternative clients in case
the primary one breaks or gets delisted.

---

## Repository layout

```
DIY-VPN/
├── README.md                          ← you are here
├── LICENSE                            ← MIT
│
├── flyio/                             ── PRIMARY DEPLOYMENT PATH ──
│   ├── Dockerfile                     Alpine + Xray + Hysteria2 + python3
│   ├── entrypoint.sh                  Boot: generate creds, seed users.json, start both daemons
│   ├── fly.toml.template              Fly app manifest (rendered by deploy.sh)
│   ├── deploy.sh                      One-shot deployer for the VPN container
│   └── config-templates/
│       ├── xray.json.template         VLESS+Reality + stats API + multi-client support
│       └── hysteria2.yaml.template    Hysteria2 (Salamander obfs, bing.com masquerade)
│
├── telegram-bot/                      ── BOT DEPLOYMENT PATH ──
│   ├── Dockerfile                     python:3.12-slim + flyctl + openssh-client
│   ├── fly.toml.template              Bot's own Fly app manifest
│   ├── deploy.sh                      One-shot deployer for the bot
│   ├── bot.py                         Entry point — all command handlers
│   ├── requirements.txt               python-telegram-bot + httpx + qrcode + pyyaml
│   ├── lib/
│   │   ├── auth.py                    Telegram user-ID allowlist decorator
│   │   ├── fly_api.py                 Fly Machines REST + GraphQL + flyctl shell-outs
│   │   ├── vpn_ops.py                 users.json, Xray stats, rotate
│   │   ├── links.py                   vless:// and hysteria2:// URI builders
│   │   ├── qr.py                      In-memory PNG QR codes
│   │   └── clients.py                 Per-OS client recommendations + setup steps
│   └── README.md                      Bot-specific quick-start
│
├── docs/                              ── EXTENDED REFERENCE ──
│   ├── 01-HOSTING.md                  Oracle Cloud / Hetzner / GCP / AWS alt hosts
│   ├── 02-SERVER-SETUP.md             SSH + installer walkthrough (VPS path)
│   ├── 03-CLIENT-SETUP.md             Long-form client setup (all 4 OSes)
│   ├── 04-TROUBLESHOOTING.md          Diagnostics + common failures
│   ├── 05-CHINA-SURVIVAL.md           Long-term GFW survival tips
│   ├── 06-FLY-IO-DEPLOYMENT.md        Detailed Fly.io reference (region picks, etc.)
│   └── 07-TELEGRAM-BOT.md             Bot deep dive — how `/devices` and `/adduser` work
│
├── scripts/                           ── VPS-PATH HELPERS (Oracle/Hetzner) ──
│   ├── install.sh                     One-shot installer for a bare Ubuntu VM
│   ├── generate-client-links.sh       Print share URIs & QR codes on the server
│   ├── health-check.sh                Diagnose a sick installation
│   ├── enable-bbr.sh                  TCP BBR + kernel tuning
│   └── uninstall.sh                   Clean removal
│
└── configs/                           ── VPS-PATH TEMPLATES ──
    ├── xray-config.json.template
    └── hysteria2-config.yaml.template
```

The `flyio/` + `telegram-bot/` pair is what most people want. `scripts/` + `configs/`
are for the self-hosted VPS path (cheaper long-term if you already run a VPS,
but more moving parts — documented in `docs/01` and `docs/02`).

---

## Alternative deployment paths

If Fly.io doesn't work for you or you want a different cost profile:

| Path | Cost | Best when |
|---|---|---|
| **Fly.io + bot (this repo, primary)** | ~$0/mo (inside $5 credit) | You want the Telegram UX and don't already have a VPS |
| **Oracle Cloud Always Free** | $0/mo forever (if signup works) | You can get past Oracle's picky card verification; you want 10 TB egress |
| **Hetzner CX22** | €4.51/mo | You want predictable EU billing and no tier math |
| **Any other VPS (RackNerd, Vultr, etc.)** | Varies | You already have one |

See [docs/01-HOSTING.md](docs/01-HOSTING.md) for the full rundown. The
`scripts/install.sh` in this repo works on any of the VPS paths.

---

## Protocol choices — why these, not others

| Protocol | Verdict | Reason |
|---|---|---|
| OpenVPN | ❌ | GFW fingerprints OpenVPN handshakes in ~60 seconds |
| WireGuard | ❌ | Same — trivially identified by packet patterns |
| Shadowsocks | ⚠️ | Partially blocked by GFW since 2019; active probing |
| VMess | ⚠️ | Legacy; Reality is strictly better |
| Trojan | ⚠️ | Requires a domain + cert; Reality obsoletes it |
| **VLESS + Reality** | ✅ | No domain, no cert, impersonates a real website |
| **Hysteria2** | ✅ | UDP + BBR-like cc + Salamander obfuscation; best for speed |

Running both means if one fails on your current network (e.g. UDP throttled
at a hotel), you flip to the other in your client with one tap.

---

## Customization knobs

| What | Where | How |
|---|---|---|
| Region (where the VPN lives) | `flyio/deploy.sh` | `REGION=sjc ./deploy.sh` |
| Memory allocation | `flyio/fly.toml.template` | change `memory_mb = 256` |
| Reality masquerade target (which website the VPN mimics) | container env | `flyctl secrets set REALITY_DEST=www.apple.com REALITY_SNI=www.apple.com --app <vpn-app>` then `/restart` |
| Telegram allowlist | bot env | `flyctl secrets set TG_ALLOWED_USERS="111,222" --app <bot-app>` |

---

## Security notes

- Credentials (UUIDs, Reality private key, Hysteria2 passwords) are generated
  inside the VPN container on first boot and persisted to the Fly volume.
  Never in git, never in the image.
- Telegram bot token and Fly API token live only as Fly secrets on the bot
  machine — not visible in the repo or in `flyctl status`.
- Xray access logs and Hysteria2 file logs are disabled by default (`loglevel:
  warning`, `access: none`). The container sees traffic flow through but
  doesn't record destinations.
- The Xray stats API (used by `/devices`) listens on `127.0.0.1:10085` only —
  never reachable from outside the container.
- Only Telegram user IDs listed in `TG_ALLOWED_USERS` can run any command.
- Your share links encode all credentials — treat them like passwords. If one
  leaks, run `/rotate yes` in the bot; every client immediately stops working
  and you re-scan with fresh codes.

---

## Troubleshooting quick index

- **Fly deploy fails with "transport: authentication handshake failed"** →
  Fly's remote builder hiccup. Retry. If persistent, `flyctl deploy --local-only`.
- **Container crashes on boot, logs show missing env var** →
  `docs/04-TROUBLESHOOTING.md § Container crash loop`
- **VPN is up but client can't connect** →
  You're using `.fly.dev` hostname instead of the raw IP. See `/status` in the bot.
- **UDP/Hysteria2 fails on a specific network** →
  Hotel wifi / corporate LAN throttling UDP. Switch the client to the VLESS
  Reality profile. Both are already in your app from the QR codes.
- **Inside China, connection drops after a few hours** →
  See `docs/05-CHINA-SURVIVAL.md` — usually rotating the Reality masquerade
  target or restarting the machine fixes it.

Full guide: [docs/04-TROUBLESHOOTING.md](docs/04-TROUBLESHOOTING.md).

---

## Legal & ethical note

Running a VPN server is legal in the jurisdictions where Fly operates.
Using it from inside a country that prohibits circumventing national
censorship (PRC, Iran, UAE, Russia, etc.) is your own legal risk calculation.
This project is for educational, personal freedom-of-information, and
remote-work use. Don't use it to attack other networks, distribute the share
links publicly, or sell access — you'll exhaust your bandwidth and invite abuse.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Contributing

Issues and PRs welcome. If you find a better stealth protocol, a cheaper host,
or a Telegram UX improvement, open an issue first to discuss. For client-app
updates (App Store delistings, new recommendations), edit
[`telegram-bot/lib/clients.py`](telegram-bot/lib/clients.py) and send a PR.
