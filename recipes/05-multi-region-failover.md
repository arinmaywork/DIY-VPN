# Recipe — Multi-region active/standby on Fly.io

## Why

One region can get its IP ranges contaminated in a day (this has happened
with Fly's Singapore and Tokyo pools historically). If your only VPN box is
there, you're offline until you redeploy in a different region — 10 minutes
minimum if you're stressed.

With a standby container in a second region, `/failover` swaps in 30 seconds.

## Architecture

```
  Fly app: diyvpn-sgad
  ├── machine A (region: sin)  — state: started   (active)
  │     ├── volume: diyvpn_data_sin (credentials)
  │     └── dedicated IPv6: 2606:...:A
  └── machine B (region: nrt)  — state: stopped   (standby)
        ├── volume: diyvpn_data_nrt (credentials, same UUIDs)
        └── dedicated IPv6: 2606:...:B
```

Two regions, one app, same credentials on both volumes (synced once), two
IPv6s. The bot picks which machine to `start` / `stop`; clients have both
IPs in their app and switch profiles manually, or use a DNS record that you
flip via Cloudflare when failing over (cleaner).

## Implementation

### 1. Second volume

```bash
flyctl volumes create diyvpn_data --app diyvpn-sgad --region nrt --size 1 --yes
```

### 2. Scale to 2 machines, one per region

```bash
flyctl scale count 2 --region sin,nrt --app diyvpn-sgad
flyctl machine stop <nrt-machine-id>  # standby starts stopped
```

### 3. Seed the nrt volume with the same credentials

Without this the nrt machine regenerates fresh credentials and clients
won't connect to it with the existing URIs.

```bash
# On the sin machine:
flyctl ssh console --app diyvpn-sgad -s  # pick sin
# Inside:
tar czf /tmp/creds.tar.gz -C /data credentials.env users.json tls
cat /tmp/creds.tar.gz | base64 -w0 > /tmp/b64
# Copy the base64 string, then:
flyctl ssh console --app diyvpn-sgad -s  # pick nrt
# Inside:
echo "<paste>" | base64 -d > /tmp/creds.tar.gz
tar xzf /tmp/creds.tar.gz -C /data
```

(Or write a one-liner in the bot that does this on first standby creation.)

### 4. Bot command `/failover`

In `telegram-bot/lib/fly_api.py`, add:

```python
async def list_machines_by_region() -> dict[str, dict]:
    out = {}
    for m in await list_machines():
        if m.get("state") != "destroyed":
            out[m.get("region")] = m
    return out
```

In `lib/vpn_ops.py`:

```python
async def failover(new_region: str) -> tuple[str, str]:
    """Stop whichever is started, start the one in `new_region`.
    Returns (old_region, new_region)."""
    by_region = await fly_api.list_machines_by_region()
    if new_region not in by_region:
        raise ValueError(f"No machine in region {new_region}. "
                         f"Available: {list(by_region)}")
    started = [r for r, m in by_region.items() if m["state"] == "started"]
    old = started[0] if started else "(none)"
    if old == new_region:
        return old, new_region
    # Start the new one first (IPv6 advertisement takes a few seconds)
    await fly_api.start_machine(by_region[new_region]["id"])
    # Only stop the old one once the new one reports started
    for _ in range(30):
        m = (await fly_api.list_machines_by_region()).get(new_region, {})
        if m.get("state") == "started":
            break
        await asyncio.sleep(1)
    for r in started:
        if r != new_region:
            await fly_api.stop_machine(by_region[r]["id"])
    return old, new_region
```

In `bot.py`:

```python
@authed
async def cmd_failover(update, ctx):
    if not ctx.args:
        by_region = await fly_api.list_machines_by_region()
        lines = ["*Regions:*"] + [
            f"• `{r}` — {m['state']}" for r, m in by_region.items()
        ]
        lines.append("\nUsage: `/failover <region>`")
        await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
        return
    target = ctx.args[0].strip()
    try:
        old, new = await vpn_ops.failover(target)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Failover: `{old}` → `{new}`. New region is active in ~30 s. "
        f"Clients: switch to the `{new}` profile (they already have it from /qr).",
        parse_mode=ParseMode.MARKDOWN,
    )
```

### 5. QR codes — one per region

Update `_build_links_for_user` so it returns pairs per (ip, region). Each
QR has the region in its remark: `DIY-VPN Reality sin`, `DIY-VPN Reality
nrt`. User imports all of them; client app shows a region picker.

## Cost

- Second volume: $0.15/mo.
- Second machine (stopped): $0 (Fly bills machines only while running).
- Second dedicated IPv6: $0 (IPv6 is free on Fly).
- Second dedicated IPv4 (if allocated): $2/mo.

Net: **$0.15/month** for a warm standby if IPv6-only. Under the $5 credit.

## Picking regions

For China-origin traffic, best pairs (low latency + high IP diversity):

| Primary | Standby | Rationale |
|---|---|---|
| `sin` Singapore | `nrt` Tokyo | If Singapore pool contaminates, Tokyo usually isn't. |
| `hkg` Hong Kong | `sin` | HKG has the lowest RTT but contaminates faster. |
| `nrt` Tokyo | `sjc` San Jose | Tokyo for primary; SJC if Pacific transit from Tokyo breaks. |

Don't both-in-same-ASN (e.g. two regions sharing the same Fly POP) — Fly
publishes which POPs are which; pick physically distinct ones.
