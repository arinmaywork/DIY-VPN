# Recipe — `/speedtest`, `/health`, and alerting

## Why

"The VPN feels slow" is the most common and most ambiguous complaint. Is it
your ISP? The VPN's CPU? Fly's transit? The destination service (Netflix)?
Without measurement you can only guess.

Two-part plan:
1. **Active: `/speedtest`** — run iperf3 on demand from the VPN machine to a
   known-good endpoint and report Mbps.
2. **Passive: `/health`** — synthetic liveness checks at 1-minute intervals;
   alert the bot's owner if any fail 3× in a row.

## Part 1 — `/speedtest`

### 1. Add iperf3 to the Dockerfile

```dockerfile
RUN apk add --no-cache iperf3
```

### 2. Bot command

In `telegram-bot/lib/vpn_ops.py`:

```python
async def run_speedtest(target: str = "speedtest.serverius.net") -> dict:
    """Run iperf3 against a public iperf3 server. Returns {up, down, rtt}.
    Public servers from https://iperf3serverlist.net/ — rotate if blocked."""
    raw = await fly_api.ssh_exec(
        f"iperf3 -c {shlex.quote(target)} -J --connect-timeout 5000 -t 5 2>&1 || true"
    )
    try:
        j = json.loads(raw)
    except json.JSONDecodeError:
        raise RuntimeError(f"iperf3 produced non-JSON: {raw[:400]}")
    end = j.get("end", {})
    sent = end.get("sum_sent", {}).get("bits_per_second", 0)
    recv = end.get("sum_received", {}).get("bits_per_second", 0)
    rtt_ms = end.get("streams", [{}])[0].get("sender", {}).get("rtt", 0) / 1000
    return {
        "up_mbps":   sent / 1e6,
        "down_mbps": recv / 1e6,
        "rtt_ms":    rtt_ms,
        "target":    target,
    }
```

In `bot.py`:

```python
@authed
async def cmd_speedtest(update, ctx):
    target = ctx.args[0] if ctx.args else "speedtest.serverius.net"
    await update.message.reply_text(f"Running iperf3 against `{target}`...",
                                     parse_mode=ParseMode.MARKDOWN)
    try:
        r = await vpn_ops.run_speedtest(target)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"*Speedtest — {r['target']}*\n"
        f"↓ {r['down_mbps']:.1f} Mbps\n"
        f"↑ {r['up_mbps']:.1f} Mbps\n"
        f"RTT ~ {r['rtt_ms']:.0f} ms",
        parse_mode=ParseMode.MARKDOWN,
    )
```

### What "good" looks like

For a shared-cpu-1x @ 256MB on Fly in SIN, testing against Serverius (NL):

| Metric | Good | Investigate | Bad |
|---|---|---|---|
| Down | > 150 Mbps | 50–150 | < 50 |
| Up | > 80 Mbps | 20–80 | < 20 |
| RTT | < 300 ms | 300–500 | > 500 |

Typical Fly shared-cpu VMs top out ~200-300 Mbps single-stream. If you're
getting < 50 with a nearby iperf3 server, something is wrong (CPU pinned,
BBR not active, Fly throttling you).

## Part 2 — `/health` + alerting

### Goal

Every 60 seconds, probe:

1. `tcp://<dedicated_ip>:443` — Reality endpoint reachable.
2. `udp://<dedicated_ip>:443` — Hysteria2 reachable (harder to probe
   cleanly; send a QUIC Initial and expect any reply).
3. `http://127.0.0.1:10085` (inside the VPN machine, via ssh) — xray stats
   API responding.
4. `systemctl is-active hysteria-server` / equivalent process check on VPN.

Log to a small ring buffer in memory. On N consecutive failures of any
probe, send a Telegram message to the bot's owner.

### Implementation sketch

In `bot.py` `main()`:

```python
from datetime import timedelta

async def health_probe(context):
    from lib.auth import ALLOWED
    failures = context.bot_data.setdefault("fail_counts", {})
    checks = {
        "machine_started": _check_machine_started,
        "reality_443_tcp": _check_tcp_443,
        "xray_api":        _check_xray_api,
    }
    for name, fn in checks.items():
        try:
            await fn()
            failures[name] = 0
        except Exception as e:
            failures[name] = failures.get(name, 0) + 1
            if failures[name] == 3:
                owner = next(iter(ALLOWED), None)
                if owner:
                    await context.bot.send_message(
                        owner,
                        f"⚠️ `{name}` failing 3x: {e}",
                        parse_mode="Markdown",
                    )

app.job_queue.run_repeating(
    health_probe, interval=timedelta(seconds=60), first=30
)
```

Probe implementations live in a new `lib/health.py`:

```python
async def _check_machine_started():
    m = await fly_api.get_primary_machine()
    if not m or m.get("state") != "started":
        raise RuntimeError(f"machine state: {m and m.get('state')}")

async def _check_tcp_443():
    ips = await fly_api.list_ips()
    v4 = next((i["address"] for i in ips if i["type"] in ("v4","shared_v4")), None)
    if not v4:
        return  # only test TCP if we have an IPv4; IPv6 needs a v6 socket.
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(v4, 443), timeout=5
    )
    writer.close()
    await writer.wait_closed()

async def _check_xray_api():
    raw = await fly_api.ssh_exec(
        "/usr/local/bin/xray api stats --server=127.0.0.1:10085 --runtime=false 2>&1 || true",
        timeout=10,
    )
    if "invalid" in raw.lower() or "refused" in raw.lower():
        raise RuntimeError(raw[:200])
```

### Cost of probes

1 SSH per minute × 30 days = 43,200 Fly API calls/month. Fly doesn't charge
for API calls. Bandwidth from probes ≈ 5 MB/month. Free.

### Noise discipline

3-consecutive-failures before alerting is the right default. With 1min
probes that's ~3min of unreachability before you hear about it. Tune down
if you want faster alerts; tune up if you're getting noise from Fly's
intermittent API hiccups.
