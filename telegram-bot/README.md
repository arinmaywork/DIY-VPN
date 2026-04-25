# DIY-VPN Telegram Bot

Control your Oracle-hosted DIY-VPN from Telegram — list devices, add/kick
clients, hand out QR codes, hand out time-limited access, view live traffic
stats, see service health.

## Architecture

```
┌──────────────────┐  Telegram Bot API   ┌────────────────────┐    ssh    ┌────────────────────┐
│  You (Telegram)  │ ───────────────────►│  Bot host          │ ────────► │  VPN box           │
│                  │ ◄─────────────────── │  (sentistack VM)   │ ◄──────── │  (Oracle Cloud)    │
└──────────────────┘                     │  - python-tg-bot    │  exit 0   │  - Hysteria2 :443  │
                                         │  - openssh-client   │           │  - Xray-Reality    │
                                         └────────────────────┘            │  - diyvpn-auth     │
                                                                           └────────────────────┘
```

The bot doesn't touch protocol internals. It SSHes into the VPN box,
edits `/data/users.json`, and runs `sudo /usr/local/bin/diyvpn-render` —
that script re-renders Hy2 + Xray configs and restarts only what changed.

## Cost

Free. Bot host is your own VM (sentistack); VPN box is Oracle Always Free.

## Required env vars

| Var | What |
|---|---|
| `TG_BOT_TOKEN` | from @BotFather |
| `TG_ALLOWED_USERS` | comma-separated Telegram user IDs |
| `VPN_HOST` | public IPv4 of the VPN box |

## Optional env vars

| Var | Default |
|---|---|
| `VPN_SSH_USER` | `ubuntu` |
| `VPN_SSH_KEY_PATH` | `~/.ssh/diyvpn-oracle` |
| `VPN_SSH_PORT` | `22` |
| `VPN_SSH_KNOWN_HOSTS` | `~/.ssh/known_hosts` |
| `TG_LOGLEVEL` | `INFO` |

## Prereqs on the bot host

- Python 3.10+ and `pip`
- `openssh-client` (Ubuntu: `apt install openssh-client`)
- A working SSH key + connectivity to `ubuntu@VPN_HOST` (test with `ssh -i $VPN_SSH_KEY_PATH ubuntu@VPN_HOST true`)

## Deploy

```bash
cd telegram-bot/
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# Stash creds
cat > .env <<EOF
TG_BOT_TOKEN=...
TG_ALLOWED_USERS=...
VPN_HOST=40.233.120.150
VPN_SSH_KEY_PATH=$HOME/.ssh/diyvpn-oracle
EOF

# Start
set -a; source .env; set +a
.venv/bin/python bot.py
```

For long-running, use the systemd unit in `systemd/diyvpn-bot.service`.

## Commands

### Share links & QR
- `/links [name]` — vless:// + hysteria2:// for the named user (default: `default`)
- `/qr [name]` — send the QR codes

### Devices
- `/devices` — list users + traffic + online + priority + expiry
- `/adduser <name> [priority]` — add permanent device (priority: `high|normal|low`, default `normal`)
- `/temp <name> <hours> [priority]` — time-limited device
- `/priority <name> <high|normal|low>` — change priority tier
- `/kick <name>` — remove a device
- `/rotate <name>` — regenerate one user's UUID + Hy2 password
- `/rotate all yes` — nuke everything (kicks all clients, regenerates Reality keys)

### Server health
- `/status` — services + listening sockets
- `/logs <auth|hysteria|xray>` — last 30 journalctl lines

### Setup helpers
- `/apps` — recommended client per platform
- `/setup <ios|android|windows|macos|linux>` — step-by-step

### Misc
- `/whoami` — your Telegram ID
- `/help` — full command list

## How priorities work

Each user gets an xray policy `level` (high=2, normal=0, low=1). Right now
all three levels enable per-user stats; priority is just a tag for your own
bookkeeping until you wire QoS rules into the routing.

## How `/temp` works

`/temp` sets `expires_at` (Unix timestamp) on the user. The Hy2 auth backend
checks `expires_at` on every connect and returns `{ok:false}` once expired.
Xray-Reality doesn't enforce expiry on its own — you need to also `/kick`
the user to remove the UUID from xray's accept list. (TODO: wire a cron
that auto-kicks expired users.)

## Security notes

- The bot uses passwordless `sudo` over SSH — make sure your SSH key is
  protected and only on the bot host.
- `TG_ALLOWED_USERS` is the only auth in front of every command; if your
  bot token leaks, anyone outside this allowlist still gets rejected.
- All SSH calls use `BatchMode=yes` (no password prompts) and
  `StrictHostKeyChecking=accept-new` (pin on first connect, fail on change).
