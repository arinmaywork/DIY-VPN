# DIY-VPN Telegram Bot

Control your Fly.io-hosted DIY-VPN from any device — start/stop the machine,
fetch QR codes, manage IPv4, list connected devices, add/kick clients — all
from a Telegram chat.

> **Looking for the full reference?** See [../docs/07-TELEGRAM-BOT.md](../docs/07-TELEGRAM-BOT.md)
> for the complete command table, how the internals work, and operating notes.
> This file is the quick-start.

## Architecture

```
┌──────────────────┐  Telegram Bot API   ┌─────────────────────┐
│  You (Telegram)  │ ───────────────────►│  Bot machine        │
│                  │ ◄─────────────────── │  (this repo)        │
└──────────────────┘                     │  - python-tg-bot     │
                                         │  - flyctl            │
                                         └──────────┬───────────┘
                                                    │ Fly Machines API
                                                    │ + flyctl ssh exec
                                                    ▼
                                         ┌─────────────────────┐
                                         │  VPN machine        │
                                         │  (../flyio/)        │
                                         │  - Xray + Hysteria2  │
                                         └─────────────────────┘
```

The bot runs on its own tiny Fly app (separate from the VPN), so when you
`/down` the VPN machine to save money, the bot stays alive to `/up` it later.

## Cost

The bot is one `shared-cpu-1x@256mb` machine with no volumes and no
allocated IPs (it polls Telegram outbound, no inbound traffic). At the
time of writing that's roughly **$1.94/month**, fully covered by Fly's
$5 included credit alongside the VPN itself.

## Prerequisites

1. The DIY-VPN itself is already deployed (you have an app like `diyvpn-sgad`)
2. `flyctl` installed and logged in
3. `jq` installed
4. A Telegram bot created via [@BotFather](https://t.me/BotFather)
5. Your Telegram user ID (use [@userinfobot](https://t.me/userinfobot))

## One-shot deploy

```bash
cd telegram-bot/
VPN_APP_NAME=diyvpn-sgad ./deploy.sh
```

The script will:

1. Prompt for your bot token + Telegram user ID(s)
2. Create a new Fly app (`<vpn-app>-bot` by default)
3. Mint a 1-year Fly API token scoped to your org
4. Stage all three secrets (`TG_BOT_TOKEN`, `TG_ALLOWED_USERS`, `FLY_API_TOKEN`)
5. Build + deploy the bot container
6. Print where to view logs

Then open Telegram, find your bot, send `/start`. If it replies, send `/help`
for the full command list.

## Commands

### VPN power
- `/status` — machine state, IPs, region
- `/up` — start the VPN machine
- `/down` — stop the VPN machine (saves $)
- `/restart` — restart the machine

### Share links & QR codes
- `/links` — paste-able vless:// + hysteria2:// URIs (text)
- `/qr` — sends QR codes for VLESS + Hysteria2 (one image per IP × per protocol)
- `/links iphone` / `/qr iphone` — for a specific named device

### IPv4 management
- `/ipv4` — show current IPs
- `/ipv4_add` — allocate a dedicated IPv4 ($2/mo)
- `/ipv4_release` — release dedicated IPv4

### Devices / users
- `/devices` — list configured users with traffic + online session counts
- `/adduser <name>` — provision a new device (e.g. `/adduser iphone`); use
  `/qr iphone` afterwards to get its share-links
- `/kick <name>` — remove a device (you can't remove the last one)
- `/rotate yes` — wipe ALL credentials and regenerate (kicks every device)

### Misc
- `/logs` — last 50 lines of VPN logs
- `/whoami` — show your Telegram user ID
- `/help` — full command list

## Updating the allowlist

```bash
flyctl secrets set --app <vpn-app>-bot TG_ALLOWED_USERS="111,222,333"
```

The bot machine will restart automatically.

## Updating the bot itself

```bash
cd telegram-bot/
flyctl deploy --app <vpn-app>-bot --config fly.toml
```

## Tearing it down

```bash
flyctl apps destroy <vpn-app>-bot --yes
```

The VPN itself is untouched.

## How `/devices` works

The VPN's Xray config exposes a stats API on `127.0.0.1:10085` (localhost
inside the container only — never reachable from outside). The bot SSHes
into the VPN container via `flyctl ssh console -C "xray api ..."` to query:

- per-user uplink/downlink bytes
- per-user online session counts

If you call `/devices` while the VPN is stopped, you'll just see the
configured user list (no live stats).

## How `/adduser` works

User entries live in `/data/users.json` on the VPN's persistent volume:

```json
[
  {"name": "default", "uuid": "...", "flow": "xtls-rprx-vision", "email": "default@diyvpn"},
  {"name": "iphone",  "uuid": "...", "flow": "xtls-rprx-vision", "email": "iphone@diyvpn"}
]
```

The bot edits this file via `flyctl ssh`, then triggers a machine restart.
The VPN's `entrypoint.sh` re-renders the Xray config from `users.json` on
every boot, so the new user is live within ~10 seconds.

## Security notes

- `TG_BOT_TOKEN` and `FLY_API_TOKEN` are stored as Fly secrets — encrypted
  at rest and only injected into the running machine's environment. Not
  visible in the image, the repo, or `flyctl status`.
- Only the Telegram user IDs in `TG_ALLOWED_USERS` can run any command;
  everyone else gets a polite refusal that exposes only their own ID.
- The bot has full control over your Fly org (org-scoped token). If you'd
  rather narrow it to just the two apps, replace step 2 of `deploy.sh`
  with: `flyctl tokens create deploy --app <vpn-app>` and
  `flyctl tokens create deploy --app <bot-app>` and combine them — but
  you'll need to refresh them every time you want to allocate new IPs
  on the VPN app.
