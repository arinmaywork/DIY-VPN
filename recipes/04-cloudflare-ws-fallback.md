# Recipe — Cloudflare-fronted VLESS+WS fallback (nuclear option)

## When to use

Your Fly IP is burned, a new IP gets burned within hours, Reality itself is
being probed against you. You need to route through Cloudflare's 10,000+ edge
IPs so the GFW can't block individual destinations.

Trade-off: Cloudflare's HTTP proxy adds latency and caps WebSocket idle at
~100s. Not as fast as Reality. Use as **fallback**, not primary.

## Architecture

```
Client in China ──HTTPS──▶ yourdomain.xyz (Cloudflare proxied, orange cloud)
                               │
                     Cloudflare's edge terminates TLS
                               │
                     HTTP/1.1 WebSocket upgrade to origin
                               │
                               ▼
                       Your Fly container (VLESS over WS on :8080)
                               │
                               ▼
                           Open internet
```

## Prerequisites

1. A domain you own. Options:
   - $1/year: `.xyz` on Namecheap during promo.
   - $10/year: `.com` anywhere.
   - Free: `nom.za` (.za subdomain) — fewer TLDs are free in 2026.
2. Cloudflare account (free plan is fine).
3. Domain's nameservers pointed at Cloudflare.

## Implementation

### 1. Add a third Fly service on port 8080

In `flyio/fly.toml.template`, add a third `[[services]]` block:

```toml
# Service 3: HTTP on :8080 for Cloudflare-fronted VLESS-WS
[[services]]
  internal_port = 8080
  protocol      = "tcp"
  [[services.ports]]
    port = 8080
    handlers = ["http"]   # Fly's HTTP handler terminates nothing; just routes.
```

### 2. Add a second inbound to `xray.json.template`

```json
{
  "tag": "vless-ws-in",
  "listen": "0.0.0.0",
  "port": 8080,
  "protocol": "vless",
  "settings": {
    "clients": __CLIENTS_JSON__,
    "decryption": "none"
  },
  "streamSettings": {
    "network": "ws",
    "security": "none",
    "wsSettings": {
      "path": "/__WS_PATH__",
      "headers": { "Host": "__WS_HOST__" }
    }
  },
  "sniffing": { "enabled": true, "destOverride": ["http", "tls"] }
}
```

Add env substitution:

```python
.replace("__WS_PATH__", os.environ.get("WS_PATH", "ws"))
.replace("__WS_HOST__", os.environ.get("WS_HOST", "example.com"))
```

Set via `flyctl secrets set --app diyvpn-sgad WS_PATH=6a7f9b2c WS_HOST=mysite.xyz`.
Random path makes this inbound unfindable by scanners.

### 3. Point Cloudflare at it

1. In Cloudflare DNS: add `A` record `vpn.mysite.xyz` → `<dedicated-IPv4>`
   (orange cloud = proxied).
2. SSL/TLS → Overview → "Full" (not "Full (strict)" because your origin is
   HTTP, not HTTPS — Cloudflare terminates TLS and re-originates HTTP to
   Fly's 8080).
3. Network → WebSockets: ON (usually on by default).

### 4. Client-side share URI

```
vless://<UUID>@vpn.mysite.xyz:443?
   encryption=none
   &security=tls
   &sni=vpn.mysite.xyz
   &type=ws
   &host=vpn.mysite.xyz
   &path=%2F<WS_PATH>
   &fp=chrome
   #DIY-VPN-CF-WS
```

Add a helper to `telegram-bot/lib/links.py`:

```python
def vless_ws_link(*, host, uuid, path, remark="DIY-VPN CF-WS") -> str:
    return (
        f"vless://{uuid}@{host}:443"
        f"?encryption=none&security=tls&sni={host}"
        f"&type=ws&host={host}&path={_enc('/' + path)}"
        f"&fp=chrome#{_enc(remark)}"
    )
```

### 5. Bot command `/qr_cf`

Wire a `/qr_cf` command that emits the CF-WS QR code so it shows up
alongside the Reality + Hy2 QRs.

## Verification

From China, when Reality is down:

1. Switch client profile to the CF-WS one.
2. `curl https://ifconfig.co` through the tunnel — should show your Fly IP
   (not Cloudflare's — Cloudflare is just the tunnel endpoint; egress still
   happens from the Fly container).

## Why this is slower

Cloudflare's nearest PoP to Shanghai is Singapore/Hong Kong at best. RTT
adds ~30-50ms vs direct. HTTP/1.1 WS means head-of-line blocking on any
hiccup. You'll see half the Mbps of Reality direct.

But it's reachable when Reality isn't — that's the whole point.

## Gotchas

- Cloudflare TOS technically forbids non-HTTP proxying; VPN-over-WS is a
  grey area. Small personal use is never an issue but don't advertise it.
- Don't reuse the same UUID you use for Reality+Hy2. If this inbound gets
  popped, rotating just this path is easier if it has its own UUID.
- Cloudflare will rate-limit you if the WS is used heavily (>1TB/mo free).
  Fine for personal use.
