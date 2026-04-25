# Recipe — Route outbound through Cloudflare WARP

## Why

- Fly.io IP ranges are on Netflix/Hulu/BBC/ChatGPT blocklists. Warp-originating traffic is not.
- Cloudflare IPs are very rarely on GFW reputation lists — the reverse direction (into your Fly box) still goes through Fly, so the GFW still only sees "TLS to a Fly IP" but your *egress* to the open internet looks like Cloudflare, improving what services you can reach.
- Free. Cloudflare WARP is free for unlimited traffic.

## The moving parts

```
Client in China  ──TLS (Reality)──▶  Fly edge ──▶  VPN container
                                                     │
                                                     │ WireGuard tunnel (wgcf)
                                                     ▼
                                              Cloudflare WARP endpoint
                                                     │
                                                     ▼
                                              Open internet (Netflix-OK)
```

## Implementation

### 1. Add `wireguard-tools` + `wgcf` to the Dockerfile

In `flyio/Dockerfile`, add to the apk install block:

```dockerfile
RUN apk add --no-cache wireguard-tools
RUN set -eux; \
    case "$(uname -m)" in \
      x86_64)  WCARCH=amd64 ;; \
      aarch64) WCARCH=arm64 ;; \
    esac; \
    curl -fsSL "https://github.com/ViRb3/wgcf/releases/latest/download/wgcf_2.2.22_linux_${WCARCH}" \
      -o /usr/local/bin/wgcf; \
    chmod 0755 /usr/local/bin/wgcf; \
    /usr/local/bin/wgcf --version
```

### 2. Register WARP on first boot (in `entrypoint.sh`)

Add before the daemons start:

```bash
WARP_DIR=/data/warp
mkdir -p "$WARP_DIR"
if [[ ! -f "$WARP_DIR/wgcf.conf" ]]; then
  echo "[*] Registering with Cloudflare WARP..."
  (cd "$WARP_DIR" && yes | /usr/local/bin/wgcf register && /usr/local/bin/wgcf generate)
fi
```

### 3. Add a second outbound to `xray.json.template`

Replace the `outbounds` block:

```json
"outbounds": [
  {
    "tag": "warp",
    "protocol": "wireguard",
    "settings": {
      "secretKey": "__WARP_PRIVATE__",
      "address": ["172.16.0.2/32", "__WARP_V6__/128"],
      "peers": [{
        "publicKey": "bmXOC+F1FxEMF9dyiK2H5/1SUtzH0JuVo51h2wPfgyo=",
        "endpoint": "engage.cloudflareclient.com:2408",
        "allowedIPs": ["0.0.0.0/0", "::/0"]
      }],
      "mtu": 1280
    }
  },
  { "tag": "direct", "protocol": "freedom", "settings": { "domainStrategy": "UseIP" } },
  { "tag": "block",  "protocol": "blackhole" }
],
"routing": {
  "domainStrategy": "IPIfNonMatch",
  "rules": [
    { "type": "field", "inboundTag": ["api-in"], "outboundTag": "api" },
    { "type": "field", "ip": ["geoip:private"],  "outboundTag": "block" },
    { "type": "field", "protocol": ["bittorrent"], "outboundTag": "block" },
    { "type": "field", "domain": ["geosite:netflix", "geosite:openai", "geosite:google"],
      "outboundTag": "warp" },
    { "type": "field", "network": "tcp,udp", "outboundTag": "warp" }
  ]
}
```

Add to the python render block in `entrypoint.sh`:

```python
.replace("__WARP_PRIVATE__", os.environ["WARP_PRIVATE"])
.replace("__WARP_V6__", os.environ["WARP_V6"])
```

And parse `wgcf.conf` into env vars before rendering:

```bash
if [[ -f "$WARP_DIR/wgcf-profile.conf" ]]; then
  export WARP_PRIVATE="$(awk -F ' = ' '/PrivateKey/ {print $2; exit}' "$WARP_DIR/wgcf-profile.conf")"
  export WARP_V6="$(awk -F ' = ' '/Address/ {print $2; exit}' "$WARP_DIR/wgcf-profile.conf" | tr ',' '\n' | grep ':' | tr -d ' /128')"
fi
```

### 4. Verify

After redeploy:

```
/logs                 # should show "Registering with Cloudflare WARP" once
(from client) curl https://ifconfig.co    # expect a Cloudflare IP, not Fly's
```

If Netflix previously blocked your Fly IP, it will now work (or at least
fall back to proxy detection, which is a different, rare problem).

## Gotchas

- **MTU matters.** 1280 is the safe floor. If you see large-response stalls,
  tune up to 1380 but test carefully.
- **WARP's free tier** has no SLA. In practice it's ~99.9%, but for
  production-critical traffic you'd want the paid WARP+ ($5/mo — defeats
  the purpose).
- **You lose the ability to host inbound services** on this container through
  WARP (you're behind NAT). VPN use only.
