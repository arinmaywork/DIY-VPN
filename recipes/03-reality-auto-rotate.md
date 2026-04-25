# Recipe — Auto-rotate Reality steal-from target

## Why

Reality's anti-fingerprint guarantee hinges on the `REALITY_DEST` /
`REALITY_SNI` being a "normal site people visit from this IP". If your box
has been claiming to be `www.microsoft.com` for six months straight, a
future GFW heuristic could look for "servers that always forward to
Microsoft for every new handshake" — rare among real web servers.

Rotating every N weeks pre-empts this.

**Requires patch 02** from `/patches/02-entrypoint-reality-env.patch` —
without it, env changes are ignored after first boot.

## Implementation — bot-side `/rotate_sni` command

In `telegram-bot/lib/vpn_ops.py`, add:

```python
REALITY_TARGETS = [
    "www.microsoft.com",
    "www.apple.com",
    "www.icloud.com",
    "www.yahoo.co.jp",
    "www.lovelive-anime.jp",
    "www.spotify.com",
    "www.samsung.com",
]

async def rotate_sni(target: str | None = None) -> str:
    """Set a new REALITY_DEST/SNI via Fly secrets and restart.
    If `target` is None, pick the next one from the preset list."""
    import random
    if target is None:
        target = random.choice(REALITY_TARGETS)
    # Set the secret on the VPN app (not the bot app!)
    await fly_api.flyctl(
        "secrets", "set", "--app", fly_api.APP,
        f"REALITY_DEST={target}", f"REALITY_SNI={target}",
        "--stage",
    )
    # Secrets need a deploy to take effect; a restart won't pick them up.
    # Use `machine update` to re-inject env without rebuilding.
    # Simpler: just restart the machine — the secret propagates on the next boot.
    machine = await fly_api.get_primary_machine()
    if machine:
        await fly_api.restart_machine(machine["id"])
    return target
```

In `telegram-bot/bot.py`:

```python
@authed
async def cmd_rotate_sni(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    target = ctx.args[0] if ctx.args else None
    try:
        chosen = await vpn_ops.rotate_sni(target)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Reality target rotated to `{chosen}`. Machine restarting... "
        f"Clients reconnect automatically; no re-import needed "
        f"(the SNI is in the *server's* domain of Reality, not the client URI's).",
        parse_mode=ParseMode.MARKDOWN,
    )

# register:
app.add_handler(CommandHandler("rotate_sni", cmd_rotate_sni))
```

**Important subtlety:** the client's share URI also includes `sni=...` —
this is used for the TLS handshake the client initiates. If you rotate
the server's REALITY_DEST but clients still send `sni=www.microsoft.com`,
Reality will reject them (the SNI must match what the server is currently
impersonating). So rotation is a breaking change for existing clients.

### Two ways to handle that:

**Option A (recommended, simpler):** rotate + push new QR codes to each
device. The `/qr` command already reads the current credentials, so after
`/rotate_sni`, `/qr` returns URIs with the new SNI. The user scans once.

**Option B (complex, seamless):** configure Reality with multiple
`serverNames` and multiple `shortIds`. Rotate between them on a schedule.
Clients with any of the accepted SNIs keep working; you `/kickforce` the
stale ones after each rotation window. Documented in Xray's advanced
Reality docs — overkill for a personal VPN.

## Automating with a schedule

The bot machine can run a weekly cron — python-telegram-bot has a built-in
JobQueue:

```python
# In main():
job_queue = app.job_queue
async def weekly_sni_rotate(context):
    chosen = await vpn_ops.rotate_sni()
    # Send notification to the first allowed user
    from lib.auth import ALLOWED
    if ALLOWED:
        await context.bot.send_message(
            chat_id=next(iter(ALLOWED)),
            text=f"🔄 Weekly SNI rotation → `{chosen}`. Send /qr to re-import.",
            parse_mode="Markdown",
        )

# Run every 14 days at 02:00 UTC
from datetime import time, timedelta
job_queue.run_repeating(
    weekly_sni_rotate,
    interval=timedelta(days=14),
    first=time(hour=2, minute=0),
)
```

## Picking good targets

Criteria for a safe `REALITY_DEST`:

1. ✅ Uses TLS 1.3 + X25519 (verify: `openssl s_client -connect host:443 -tls1_3`)
2. ✅ Serves from a single origin (not a geographically-sharded CDN that
   might answer differently from your Fly region).
3. ✅ Popular enough that blocking it would cause real user complaints.
4. ❌ Not a Cloudflare/Akamai/Fastly front that terminates TLS itself — the
   TLS fingerprint has to come from a "real" origin.

Tested-good list (as of Apr 2026): Microsoft, Apple, iCloud, Spotify,
Yahoo JP, Lovelive, Samsung. Avoid: GitHub Pages, Cloudflare-fronted sites,
Google (too unique a TLS fingerprint).
