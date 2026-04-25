# Recipe — Hysteria2 port hopping (the single biggest China-durability win)

## Why

The GFW has increasingly targeted long-lived UDP flows to a single 5-tuple
(src_ip, src_port, dst_ip, dst_port=443). Once flagged, throughput is
throttled to near zero after a few minutes. Port hopping randomises the
server-side destination port per packet-burst, so the GFW's flow-stats
engine never settles into "this is a QUIC tunnel on 443".

Hysteria2 supports this natively via a port **range** on the server + the
`&mport=` URI parameter on the client.

## The moving parts

```
Client ──▶ UDP/20001 ┐
Client ──▶ UDP/25843 ├── all → 127.0.0.1:443 (via DNAT) ──▶ hysteria2
Client ──▶ UDP/42011 ┘
```

The server keeps one listener on 443. Iptables DNAT redirects everything in
the 20000-50000 range to it. The client picks a fresh port per burst.

## Implementation — VPS path (Oracle, Hetzner, any bare Linux)

### 1. Add DNAT rule to `scripts/install.sh`

In section 8 ("Fix Oracle / strict iptables"), add **after** the existing
accept rules:

```bash
# Detect primary NIC (the one with the default route)
PRIMARY_NIC="$(ip route | awk '/^default/ {print $5; exit}')"

# DNAT: anything in UDP 20000-50000 is redirected to our hysteria2 on :443
iptables -t nat -C PREROUTING -i "$PRIMARY_NIC" -p udp --dport 20000:50000 \
  -j REDIRECT --to-ports 443 2>/dev/null || \
  iptables -t nat -I PREROUTING -i "$PRIMARY_NIC" -p udp --dport 20000:50000 \
  -j REDIRECT --to-ports 443

ip6tables -t nat -I PREROUTING -i "$PRIMARY_NIC" -p udp --dport 20000:50000 \
  -j REDIRECT --to-ports 443 2>/dev/null || true
```

Note: REDIRECT is cheaper than DNAT-to-loopback because conntrack tracks
fewer flows. On lossy mobile links this matters.

### 2. Update the Hysteria2 share URI

In `scripts/generate-client-links.sh`, append to `HY2_URI`:

```bash
HY2_URI+="&mport=20000-50000"
```

And in the bot's `lib/links.py`:

```python
def hysteria2_link(*, host, password, obfs_password, sni="bing.com",
                   remark="DIY-VPN Hysteria2", mport="20000-50000") -> str:
    return (
        f"hysteria2://{_enc(password)}@{host}:443/"
        f"?obfs=salamander&obfs-password={_enc(obfs_password)}"
        f"&sni={sni}&insecure=1&mport={mport}"
        f"#{_enc(remark)}"
    )
```

### 3. Verify

Client-side, after re-importing the URI:

- Connect. Look at conntrack on server: `conntrack -L -p udp | grep :443`
- You should see **multiple entries** with different `sport=`, all mapped
  to the same origin `dst=<client-ip>`. That's the hop range in action.

## Implementation — Fly.io path

Fly's UDP proxy requires you to declare each port. Declaring 30000 ports is
impractical (and expensive — Fly charges per allocated port above some
threshold on their newer pricing). **On Fly, you can't do real port
hopping.** You get one UDP/443 and that's it.

Workarounds on Fly:

1. **Open a small hop range** (say 10 ports: 20001-20010). Add to
   `flyio/fly.toml`:

   ```toml
   [[services]]
     internal_port = 443
     protocol      = "udp"
     [[services.ports]]
       start_port = 20001
       end_port   = 20010
   ```

   Set `mport=20001-20010` on the client. You lose 99% of the hop space but
   keep some churn.

2. **Move to Oracle Always Free** for the VPN and keep Fly for the bot.
   Oracle gives you a full bare-metal firewall; port hopping works properly.
   This is genuinely a better architecture for China.

3. **Skip hopping, rely on Reality** as the primary and use Hysteria2 only
   as a fallback on networks where TCP is throttled (some hotel Wi-Fis).
   This is what the current setup does.

## Gotchas

- **Stateful NAT middleboxes** (some ISPs, most corporate networks) drop
  packets when the 5-tuple changes rapidly. If the user connects from such a
  network, port hopping can make things *worse* — they should set
  `mport=443` on that client profile as a fallback.
- **Conntrack table size** — with lots of clients, 1 client * many hops can
  fill conntrack. Bump `net.netfilter.nf_conntrack_max = 131072` in the
  sysctl block of `install.sh`.
