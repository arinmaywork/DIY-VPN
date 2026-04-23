# 07 — Telegram Bot

The bot is the control plane for the VPN. Anything you'd normally do with
`flyctl` or by SSHing into the container — start, stop, rotate credentials,
add a device, pull QR codes, check who's connected — is wrapped behind a
Telegram command with authentication + auditing for free (every command goes
through Telegram's own infrastructure, and you can scroll back through chat
history).

It's a separate Fly app from the VPN, so when you `/down` the VPN to save
bandwidth, the bot stays alive to `/up` it later.

---

## Cost

The bot is one `shared-cpu-1x@256MB` Fly machine, always on, with no volume
and no allocated IPs (Telegram talks to it outbound-only). At the time of
writing that's **~$1.94/month**, which stacks with the VPN's ~$2/month and
is still fully inside Fly's $5 included credit. **Net $0 out of pocket.**

If you want to squeeze further, you could fold the bot into the VPN container
as a sidecar process — but then stopping the VPN stops the bot, defeating the
whole "start-from-anywhere" benefit.

---

## Prerequisites

Before deploying the bot, you need:

1. **The VPN already deployed** via [`flyio/deploy.sh`](../flyio/deploy.sh).
   You should have an app like `diyvpn-sgad` and your clients should already
   work (`curl https://ifconfig.co` through the tunnel returns a Fly IP).
2. **A Telegram bot token** from [@BotFather](https://t.me/BotFather):
   - Open Telegram, find @BotFather
   - Send `/newbot`
   - Pick a display name (e.g. "Arinmay's VPN")
   - Pick a username ending in `bot` (e.g. `arinmay_diyvpn_bot`)
   - BotFather replies with a token like `1234567890:ABC-DEF-ghi...`. Save it.
3. **Your Telegram user ID**:
   - Open Telegram, find [@userinfobot](https://t.me/userinfobot)
   - Send `/start` — it replies with your numeric user ID (e.g. `7986012544`)
4. On your local machine: `flyctl` installed, logged in, and `jq` installed.

---

## Deploy

```bash
cd telegram-bot
chmod +x deploy.sh
VPN_APP_NAME=diyvpn-sgad ./deploy.sh
```

The script walks you through the rest:

1. Prompts for the bot token and your Telegram user ID(s) if you didn't set them as env vars
2. Creates a new Fly app (`<vpn-app>-bot` by default)
3. Mints a long-lived Fly API token (org-scoped, 1 year) so the bot can
   control the VPN app
4. Sets `TG_BOT_TOKEN`, `TG_ALLOWED_USERS`, `FLY_API_TOKEN` as Fly secrets
5. Builds the container and deploys

**Takes ~3 minutes.** Then in Telegram, find your bot, send `/start`. If it
replies, send `/help` for the full command list.

### Env vars the deploy script accepts

| Var | Required | Default | Notes |
|---|---|---|---|
| `VPN_APP_NAME` | yes | — | Name of the VPN Fly app the bot will control |
| `BOT_APP_NAME` | no | `<VPN_APP_NAME>-bot` | Name of the bot's Fly app |
| `REGION` | no | same as VPN | Fly region; inherited from the VPN machine if present |
| `TG_BOT_TOKEN` | no | prompted | Your BotFather token |
| `TG_ALLOWED_USERS` | no | prompted | Comma-separated Telegram user IDs |

---

## Command reference

### Power

```
/status     — machine state, IPs, region, running image
/up         — start the VPN machine (Fly Machines API call)
/down       — stop the VPN machine — use when traveling or not using the VPN
/restart    — rolling restart (for after you change secrets or redeploy)
```

### Share links & QR codes

```
/links [name]    — paste-able URIs for both protocols, for the named device
                   (defaults to "default" — the original user)
/qr [name]       — sends a PNG QR code for each protocol × each allocated IP
```

Both commands build one entry per allocated IP — so if you have both IPv6 and
IPv4 on the VPN, you get two VLESS URIs and two Hysteria2 URIs (and the QR
variant sends four images).

### IPv4 management

```
/ipv4             — list current IPs with type and region
/ipv4_add         — allocate a dedicated IPv4 via Fly GraphQL (costs $2/mo)
/ipv4_release     — release every dedicated IPv4 the VPN has
```

After `/ipv4_add`, run `/restart` so Xray re-reads its bind address cleanly,
then `/qr` to get fresh share-links that include the new v4.

### Devices / users

```
/devices                — list configured users with live online count
                           and bytes ↑/↓ per user (when VPN is running)
/adduser <name>         — provision a new UUID, bump users.json, reload Xray
                           — then /qr <name> for that device's share-link
/kick <name>            — remove a device; can't remove the last one
/rotate yes             — WIPE everything and regenerate (everyone re-scans)
```

### Client apps

```
/apps                    — table of recommended clients per OS
/setup <platform>        — step-by-step walkthrough for one OS
                           platforms: ios, android, windows, macos, linux
                           aliases:   iphone=ios, mac=macos, win=windows
```

### Misc

```
/logs         — tail last ~50 lines of VPN logs (via flyctl logs)
/whoami       — show your Telegram user ID (useful when adding new admins)
/help         — full command list
```

---

## How it works under the hood

### `/status`, `/up`, `/down`, `/restart`, `/ipv4*`

The bot talks to Fly's **Machines REST API** (`api.machines.dev`) and Fly's
**GraphQL API** (`api.fly.io/graphql`) over HTTPS. Credentials are the
`FLY_API_TOKEN` secret baked into the bot's environment. No SSH needed.

### `/links`, `/qr`, `/devices`, `/adduser`, `/kick`, `/rotate`

These need to read or modify files inside the running VPN container. The bot
shells out to `flyctl ssh console -C "..."` for each operation. The bot's
container has `flyctl` and `openssh-client` installed for exactly this.

`/devices` additionally calls `/usr/local/bin/xray api statsquery --server=127.0.0.1:10085`
inside the VPN container to fetch live traffic counters and online session counts.

### User management (`/adduser`, `/kick`)

User entries live in `/data/users.json` on the VPN's persistent volume:

```json
[
  {"name": "default", "uuid": "...", "flow": "xtls-rprx-vision", "email": "default@diyvpn"},
  {"name": "iphone",  "uuid": "...", "flow": "xtls-rprx-vision", "email": "iphone@diyvpn"}
]
```

On boot, the VPN's `entrypoint.sh` renders `/etc/xray/config.json` by
substituting `users.json` into the `__CLIENTS_JSON__` placeholder in
`xray.json.template`. Each user gets its own VLESS client entry with its own
email tag — Xray's stats API keys all counters by that tag, which is how
`/devices` can show per-device byte counts and online session counts.

After any `/adduser` or `/kick`, the bot restarts the VPN machine so Xray
re-reads its config. Takes ~10 seconds. Existing devices stay connected
(their UUIDs didn't change).

### Credential rotation (`/rotate yes`)

The nuclear option. On the VPN volume:

```
rm /data/credentials.env /data/users.json /data/share-links.txt \
   /data/tls/server.crt /data/tls/server.key
```

…then `/restart`. On next boot, the VPN regenerates fresh UUIDs, a new Reality
keypair, new Hysteria2 passwords, and re-seeds `users.json` with just the
`default` user. All existing client share-links break — re-import from `/qr`.

---

## Operating the bot

### Update the allowlist

```bash
flyctl secrets set --app <bot-app> TG_ALLOWED_USERS="111,222,333"
```

The bot machine restarts automatically and picks up the change.

### Update the bot code

```bash
cd telegram-bot
flyctl deploy --app <bot-app> --config fly.toml
```

The bot machine does a rolling restart. No impact on the VPN.

### Rotate the Fly API token

Fly tokens created via `flyctl tokens create org` default to 1 year. To refresh:

```bash
flyctl tokens create org personal -x 8760h
flyctl secrets set --app <bot-app> FLY_API_TOKEN='<new-token>'
```

### Tear it down

```bash
flyctl apps destroy <bot-app> --yes
```

The VPN is untouched.

### Move the bot to another region

The bot does negligible traffic. You can move it freely:

```bash
flyctl machine list --app <bot-app> --json | jq -r '.[0].id'    # note the id
flyctl machine destroy --force <machine-id>
flyctl scale count 1 --region fra --app <bot-app>               # or wherever
```

---

## Security model

- **The bot has full control over your Fly org** (via the org-scoped token).
  It can create/destroy apps, allocate IPs, spend money. Treat the bot app
  as high-privilege.
- **Allowlist is strict.** The decorator in `lib/auth.py` drops every update
  where `update.effective_user.id` isn't in `TG_ALLOWED_USERS`. A rejected
  user sees only their own Telegram ID (for self-identification when asking
  an admin to allow them).
- **Secrets never appear in the image or repo.** They're injected as env vars
  at runtime by Fly and are only visible inside the running machine.
- **Telegram's transport is TLS, not E2E**, so a sufficiently-resourced state
  actor with Telegram server access could read your commands. For personal
  use this is fine; if you're in a threat model where that matters, run the
  bot on Signal or in-person SSH instead.

---

## Limitations & things to know

- **`/devices` online counts need the VPN to be running.** If you call it
  while the VPN is stopped, it falls back to just listing the configured
  users (no byte counts, no online sessions).
- **`/kick` requires a restart of the VPN.** Xray doesn't have a
  zero-downtime way to drop a single client without reloading config.
  Restart takes ~10 s. Other devices reconnect automatically.
- **`flyctl ssh console` is not fast.** Commands like `/devices`, `/adduser`,
  `/links` take 3–6 seconds because each opens a fresh SSH session. Future
  work: a tiny HTTP companion inside the VPN container on the private Fly
  network would cut that to <1s.
- **The bot polls Telegram.** No webhook, no public port. This is fine
  (Telegram's polling is efficient) and eliminates a whole class of
  deployment headaches (no TLS cert for the webhook, no DNS, no reverse
  proxy).

---

## Extending the bot

### Adding a command

1. Edit `telegram-bot/bot.py`, add an `async def cmd_whatever(update, ctx)`
   decorated with `@authed`.
2. Register it in `main()`: `app.add_handler(CommandHandler("whatever", cmd_whatever))`.
3. Update the `/help` text in `cmd_help` and add a row to the README's
   command reference.
4. `flyctl deploy --app <bot-app> --config fly.toml`.

### Updating client-app recommendations

When an App Store pick gets delisted, or you find a better client, edit
`telegram-bot/lib/clients.py` → the `PLATFORMS` dict. Each platform has:

```python
"primary":       {name, vendor, store, url, why}
"alternatives":  [{name, note, url}, ...]
"steps":         ["numbered setup step", ...]
```

Deploy and `/setup <platform>` picks up the change.
