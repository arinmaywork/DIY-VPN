# DIY-VPN — Code & Architecture Audit

**Scope:** full repo (flyio/, telegram-bot/, scripts/, configs/, docs/) as of Apr 23, 2026.
**Goal:** best-class, China-resilient, ~$0 self-hosted VPN.

The design is already very good. What follows is what I'd fix before you
actually trust it in front of the GFW, plus what I'd add to make it genuinely
best-in-class.

Severity legend: **🔴 critical** (breaks at runtime or leaks secrets) · **🟠 high** (silently produces wrong results) · **🟡 medium** (bad UX / fragile) · **🟢 polish**.

---

## Part 1 — Bugs, severity-ranked

### 🔴 B1. `vpn_ops.query_online` uses a command name that doesn't exist

`lib/vpn_ops.py:119`:

```python
"/usr/local/bin/xray api stats_online --server=127.0.0.1:10085 2>&1 || true"
```

Xray-core's CLI registers the command as **`statsonline`** (no underscore).
`stats_online` will print a help/usage blurb and the regex on the next line
will match nothing — so `/devices` will **always show "online: 0"** for every
user even when they're actively streaming. Since the output is suppressed
with `|| true`, this fails silently.

**Fix:** change `stats_online` → `statsonline`. Same for any similar typo.

---

### 🔴 B2. `vpn_ops.query_stats` assumes JSON output, but `xray api statsquery` emits protobuf text by default

`lib/vpn_ops.py:110`:

```python
"/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 -reset=false 2>&1 || true"
```

Default output is protobuf-text like:

```
stat: <
  name: "user>>>default@diyvpn>>>traffic>>>uplink"
  value: 1234
>
```

That's neither JSON nor the `name: value` form your fallback regex expects,
so `_parse_stats` returns empty dicts. `/devices` reports `↑ 0 B / ↓ 0 B` for
every user forever.

**Fix:** pass the JSON flag — modern xray supports `--json`:

```python
"/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 --reset=false --pattern='' 2>&1"
```

…but the JSON flag is implied on recent builds only for `stats` not `statsquery`.
The robust fix is to parse protobuf-text: split on `stat: <` blocks and grab
`name` + `value`. Patch in Part 3.

---

### 🔴 B3. `REALITY_DEST` / `REALITY_SNI` can't be rotated after first boot — contradicting the README

`flyio/entrypoint.sh` writes the defaults into `/data/credentials.env` on the
first boot, then on every subsequent boot sources that file (which overrides
the env vars from `fly.toml` / `flyctl secrets`):

```bash
cat > "$CRED" <<EOF
...
REALITY_DEST=${REALITY_DEST}
REALITY_SNI=${REALITY_SNI}
EOF
...
. "$CRED"     # ← clobbers any env-supplied rotation
```

The README explicitly tells the user:

> `flyctl secrets set REALITY_DEST=www.apple.com REALITY_SNI=www.apple.com … then /restart`

That will do **nothing** after the first boot. For China-survival this is
important — the whole point of rotating the steal-from target is to keep
Reality's fingerprint fresh. Right now, once set, it's set forever unless you
wipe the volume.

**Fix:** don't persist `REALITY_DEST`/`REALITY_SNI` in credentials.env; only
persist the cryptographic material. Re-read from env on every boot, with the
credentials.env value as a fallback.

---

### 🔴 B4. GraphQL IP operations will fail with the deploy-scoped token

`lib/fly_api.py` uses a single `FLY_API_TOKEN` for both the Machines REST API
(`api.machines.dev`) and the GraphQL control-plane (`api.fly.io/graphql`).
**Fly's `deploy`-scoped tokens do not work against GraphQL.** They only
authorise the Machines REST surface.

`deploy.sh` already acknowledges this and falls back to `flyctl tokens create
org personal` — but that token has **full access to every app in your org**.
If the bot container is ever compromised, the attacker can destroy/rename any
app you own, exfiltrate secrets from them, etc. This is a meaningful
blast-radius upgrade from "just the VPN".

**Fix (operational):** mint two tokens:

1. `FLY_API_TOKEN` — deploy-scoped to the VPN app (used for REST: start/stop/restart).
2. `FLY_GRAPHQL_TOKEN` — `flyctl tokens create deploy --app <VPN>` also works against GraphQL for the same app if the scope includes `control-plane` — current flyctl has `--scope` flags. Or mint an **app-specific** GraphQL token (`flyctl tokens create readonly --app <VPN>` is too narrow; use `flyctl tokens create machines --app <VPN>` for both).

Patch in Part 3 splits the token and adds a helpful error message if the
wrong one is configured.

---

### 🔴 B5. The Fly.io `docs` + `deploy.sh` tell users to hit the raw dedicated IP — but Fly's dedicated IPs still route through the Anycast proxy

This is more of a documentation error than a code bug, but it matters for
China.

Fly's dedicated IPv4/IPv6 are routed via Fly's Anycast proxy (they are not
BGP-advertised to the machine directly). For TCP/UDP passthrough services
this works, but:

- Reality's handshake is a real TLS 1.3 handshake end-to-end through the
  proxy — **OK**, this works.
- Hysteria2's QUIC masquerade to `bing.com` works — **OK**.
- But the "source IP the client sees" is a Fly edge IP in the client's
  nearest POP, which on some mobile carriers in China gets flagged as
  "VPN traffic to Singapore" very quickly, shortening your IP's lifetime.

For long-term China survival the dedicated-IPv6 path is fine, but the raw IP
path is not magical — you're still passing through Fly's proxy.

**Fix:** update docs, and add the "Cloudflare WARP outbound" recipe (Part 4)
so outbound traffic leaves via Cloudflare IPs instead of Fly IPs. This also
fixes Netflix/Hulu blocking Fly IP ranges.

---

### 🟠 B6. `sniffing.routeOnly = true` + DNS routing is inconsistent with the blocklist

`xray.json.template` enables sniffing to extract the destination hostname
from TLS SNI / HTTP Host, but then `routeOnly=true` means the original IP
destination is still used for the connection. The routing rules block
`geoip:private` and `bittorrent` — both of these work with `routeOnly=true`.
So far so good.

The issue: if a client's DNS leaks or their DoH request goes to a private
range, sniffing won't help. More importantly, the `dns.servers` block lists
both `https+local://1.1.1.1/dns-query` and raw `1.1.1.1` as fallback. With
`queryStrategy: UseIP` that means any DNS failure falls through to plaintext
UDP 53 — **DNS leak**. The DoH servers should be the only servers, period.

**Fix:** drop the plaintext DNS fallbacks. Add `disableFallback: true`.

---

### 🟠 B7. Fly.io UDP proxy + Hysteria2 port-hopping is silently absent

The project uses `:443/udp` only on the Fly side. Hysteria2's *killer feature*
for China survival is **UDP port hopping** — the client hops through a range
of UDP ports (e.g. 20000-50000) so the GFW can't just rate-limit a single
5-tuple. Your VPS `install.sh` opens the firewall range but never configures
hysteria2 to actually *use* it (no DNAT rule, no `listen` range), and the
Fly.io deployment can't use it anyway because Fly's UDP proxy only exposes
specifically-declared ports.

This is the single biggest China-survival feature you're leaving on the table.

**Fix (VPS path):** add iptables DNAT from the port range to 443:

```bash
iptables -t nat -I PREROUTING -i <nic> -p udp --dport 20000:50000 -j REDIRECT --to-ports 443
```

Plus the hysteria2 client URI needs `&mport=20000-50000` so the client hops.
Patch in Part 4.

**Fix (Fly.io path):** declare the UDP range in `fly.toml` (Fly supports
this since 2024 — `[[services.ports]] port = { start = 20000, end = 50000 }`,
syntax check their docs for your flyctl version). Or accept that Fly won't
hop and use the VPS path for China.

---

### 🟠 B8. `entrypoint.sh`: `wait -n` semantics + `set -e`

```bash
wait -n
EXIT=$?
```

Under `set -e`, `wait -n` returning non-zero will cause the script to exit
immediately, **before** the cleanup / kill-sibling block runs. In practice
Fly does the cleanup for you (it SIGKILLs the container after `kill_timeout`),
but it's still a bug: the sibling daemon can live on for up to 30s eating
CPU while Fly marks the machine unhealthy.

**Fix:** `set +e` around the wait, or explicitly `wait -n || true`.

---

### 🟠 B9. `flyctl ssh console -C` may block on TTY

`fly_api.ssh_exec` shells out to `flyctl ssh console -C "cmd"`. On some
flyctl versions this still attempts TTY allocation, which hangs when no TTY
is attached (bot runs under asyncio, no PTY). Symptom: `/adduser`, `/devices`,
`/rotate` all time out silently.

**Fix:** pass `--pty=false` or use `flyctl ssh sftp shell`-less variant. Or
switch to the Fly Machines `exec` API (which is what you actually want
long-term — no `flyctl` binary in the bot container, no ssh client, smaller
blast radius). Patch in Part 3.

---

### 🟠 B10. Org-scoped `FLY_API_TOKEN` lives in the bot container

`telegram-bot/deploy.sh` mints `flyctl tokens create org personal -x 8760h`
and stores it as a Fly secret in the bot app. If anyone pops the bot app
(python-telegram-bot has had CVEs historically; one bad pip pin and you're
cooked), they own your whole Fly org.

**Fix:**

1. Mint a token scoped to exactly the VPN app: `flyctl tokens create deploy --app <VPN> -x 8760h`.
2. For IP allocation (GraphQL), the same deploy token now works against
   `api.fly.io/graphql` for that specific app, *provided you use the
   `app:<name>` scoping — check current flyctl.
3. If step 2 still fails on your flyctl version, accept that the bot can't
   allocate IPs and require the user to do `flyctl ips allocate-v4 --app <VPN>`
   themselves. Which is a 30-second operation.

---

### 🟡 B11. `allocate_ipv4` / `release_ip` pass the app **name** as `appId: ID!`

Fly's GraphQL accepts the app name as `appId` for most of the app's fields
(they alias name → id internally), but this is undocumented and has flipped
in the past. Safer: resolve the actual numeric appId first via
`{ app(name: "X") { id } }` and then pass that ID to the mutation. That also
matches Fly's own tooling.

---

### 🟡 B12. `cmd_links` and `cmd_logs` chunk at 4000 chars but can split mid-backtick

Telegram renders MarkdownV1 code spans with `` ` ``. If the split falls
inside a code span, the next message has unbalanced backticks and the whole
chunk renders as plaintext, including literal backticks. Not catastrophic,
but ugly.

**Fix:** split on newlines, not arbitrary char boundaries. Patch in Part 3.

---

### 🟡 B13. `_md_escape` is dead code

Defined in `bot.py`, never used. Either wire it into places that interpolate
user-controlled strings into Markdown (`/adduser <name>`) or delete it.

---

### 🟡 B14. `cmd_adduser` error path doesn't restore on restart failure

If `vpn_ops.add_user` writes `users.json` and then the `restart_machine` call
fails (Fly API hiccup), `users.json` has the new user but xray is running
with the old config. Next boot picks it up, but the user gets "Failed: …"
with no indication that they'll be connected after the VPN comes back up.

**Fix:** distinguish "users.json write failed" (rollback) from "restart API
call failed" (retry hint).

---

### 🟡 B15. `cmd_rotate` doesn't kill existing sessions before wiping

`rotate_credentials` removes the files and restarts. But until the machine
actually restarts, existing connections (with old UUID) are still live. If
the reason for rotating is "a key leaked", you want those sessions terminated
**now**, not eventually. The fastest way: `stop_machine` then `start_machine`
instead of `restart_machine`.

---

### 🟡 B16. `bot.py`: no per-user rate limiting

Anyone on the allowlist can spam `/adduser` or `/rotate yes` faster than the
VPN can restart, putting it in a boot loop. TG_ALLOWED_USERS is small by
design, but if one of your devices gets owned the attacker can DoS you.

**Fix:** simple in-memory token bucket per user_id (e.g. 10 mutating commands
per minute).

---

### 🟡 B17. `install.sh` doesn't handle UFW

Ubuntu 22+ LTS images often ship with UFW. Your iptables edits are applied
below UFW's chains, which means on the next `ufw reload` your 443/udp rule
can be overridden. The installer should either `ufw allow 443` (preferred)
or `ufw disable` explicitly.

---

### 🟡 B18. Credentials on `/data` are unencrypted

Fly volumes are not encrypted at rest. If Fly's infra is ever compromised,
UUIDs and Reality private keys leak. Mitigation: rotate on a schedule (you
have `/rotate`, use it), or store the Reality private key encrypted with a
passphrase and enter it via `flyctl secrets` on boot. Probably overkill for
a personal VPN, noted for completeness.

---

### 🟢 B19. `Dockerfile` fetches "latest" from GitHub on every build

If GitHub's API is rate-limited or blocked from Fly's builder, your deploy
fails. Pin to specific known-good tags, or vendor the `jq`-based discovery
behind a retry loop. Also consider caching via GHCR.

---

### 🟢 B20. `fly.toml` (VPN) doesn't set `kill_signal` / `kill_timeout`

Default Fly is `SIGINT` / 5s. Your entrypoint traps both. 5s is tight if
Hysteria2 has lots of QUIC conns to close. Bump to `kill_timeout = "15s"`.

---

### 🟢 B21. `fly.toml` (bot) has no `[[services]]` — that's correct — but there's also no `release_command` or healthcheck on the polling loop

If the polling loop wedges (rare but happens with python-telegram-bot on
network flakes), Fly won't restart the machine. Add a periodic health-write
to a file + a filesystem-based check, or add an HTTP sidecar. Or just
`app.run_polling(poll_interval=…, connect_timeout=…)` and trust Fly.

---

### 🟢 B22. `fly.toml.template` is rendered into a committed `fly.toml`

Your `.gitignore` lists `flyio/fly.toml` and `telegram-bot/fly.toml`, but the
current tree actually has both `fly.toml` files committed (shown in `git ls-files`).
Once committed, `.gitignore` won't un-track them. Either `git rm --cached fly.toml`
or accept that they're committed and drop the gitignore entries.

---

### 🟢 B23. `REALITY_SHORT_ID` is only 8 hex chars

Xray supports up to 16 bytes. 8 hex = 4 bytes. Still fine, but 8 bytes (16 hex)
gives more entropy and matches what the anti-censorship research community now
recommends.

---

### 🟢 B24. Docker image is Alpine for VPN — fine, but `musl` DNS resolver has quirks

Alpine uses musl, which has had historical issues with parallel DNS lookups
in some Go versions. Not a blocker today but something to be aware of when
debugging weird resolution flakes. Switching to `debian:bookworm-slim` costs
~30 MB and zero money on Fly.

---

### 🟢 B25. No `compromised_clients_list` / revocation mechanism beyond `/rotate`

`/kick` only removes from users.json; the active session can linger until
TCP timeout. Reality's per-user UUID means removing from the clients array
does block *new* handshakes, but `/kick` doesn't force-close the live one.
A `/kickforce <name>` that does `flyctl ssh console -C "xray api … close"`
would be more useful. Xray's API does support forcing session close per user.

---

## Part 2 — Architectural improvements for "best class, worldwide incl. China"

These are not bugs — they're the difference between "works" and "survives a
month in Shanghai on China Telecom".

### A1. Cloudflare WARP as outbound (no extra cost, huge wins)

Pipe xray's `direct` outbound through WireGuard-to-Cloudflare-WARP. You get:

- Cloudflare-owned source IP → no Fly reputation issues.
- Netflix / Hulu / BBC iPlayer unblocks (Fly IP ranges are mostly blocked by streaming).
- Free; zero config on Cloudflare's end if you use the `warp-cli register`
  equivalent via `wgcf`.

Recipe in Part 4.

### A2. Second stealth path via Cloudflare-proxied VLESS+WebSocket+TLS

Reality is state of the art, but the GFW tests it from time to time. Having a
second-tier fallback that is fundamentally different (CF proxy → WS over TLS)
means a nasty rollout by the GFW can't take down your access in one move.
Only ~$0 extra if you use a free domain (`.xyz` on Namecheap is $1/year,
`nom.za` free).

The client side is already supported by all the recommended apps (V2Box,
v2rayNG, Nekoray).

### A3. Auto-rotating Reality steal-from target

A scheduled task that cycles `REALITY_DEST` through a short list of popular
HTTPS sites every N days. Combined with B3's fix, this makes the
fingerprint moving-target without user intervention. One well-tested list:

- `www.microsoft.com`
- `www.apple.com`
- `www.icloud.com`
- `www.yahoo.co.jp`
- `www.lovelive-anime.jp`

All TLS 1.3 + X25519, all heavily used in-country so blocking them is painful.

### A4. Multi-region failover

Fly.io allows you to deploy the same container to multiple regions under one
app. Have the bot know about two regions (e.g. `sin` + `nrt`), and a
`/failover` command swaps which one is `started`. For the cost of a second
$0.15/month volume you halve your "oh no my IP is burned" downtime.

### A5. Hysteria2 port hopping done right (VPS path)

Fix B7 + point the client at `&mport=20000-50000`. This single change can
double your Hysteria2 longevity in China.

### A6. Warp-split routing for China-inside traffic

If you actually use this from inside China, you want *China domestic* traffic
(Alipay, Baidu Maps, WeChat APIs) to NOT go through the VPN — those APIs
require a China-resident IP or they rate-limit hard. Add a client-side
geosite-China bypass rule, not server-side.

### A7. Observability

Write a `/speedtest` command in the bot that runs `iperf3 --client` against
a known server from the VPN machine, and prints up/down Mbps. Useful for
"is this slow because of my ISP, the VPN box, or Fly's transit?" triage.

### A8. Multi-architecture container

Your `Dockerfile` builds for amd64 when run on amd64 and arm64 when run on
arm64. Fly runs x86_64 by default, but Fly also has `arm64` machines which
are ~30% cheaper per-cpu. Build once, tag twice: add `--platform` and push to GHCR.

---

## Part 3 — Patches for the critical bugs

Below are drop-in patches for B1, B2, B3, B8, B9, B12. Files created
alongside this audit:

- `patches/01-vpn_ops-stats-fix.patch` — fixes B1, B2
- `patches/02-entrypoint-reality-env.patch` — fixes B3
- `patches/03-entrypoint-wait-trap.patch` — fixes B8
- `patches/04-fly_api-pty-timeout.patch` — fixes B9
- `patches/05-bot-smart-split.patch` — fixes B12

Apply with `git apply patches/*.patch` from the repo root.

---

## Part 4 — "Best class" add-on recipes

Cookbook-style recipes for the architectural improvements:

- `recipes/warp-outbound.md` — pipe all VPN egress through Cloudflare WARP
- `recipes/cloudflare-ws-fallback.md` — VLESS+WS+TLS via Cloudflare
- `recipes/reality-auto-rotate.md` — scheduled SNI rotation
- `recipes/hysteria-port-hopping.md` — proper port-hop config
- `recipes/multi-region-failover.md` — 2-region active/standby on Fly
- `recipes/observability.md` — `/speedtest`, `/health`, alerting

(Recipes are in a subfolder so they don't crowd the repo root.)

---

## Summary — what to do in what order

If you have 30 minutes today:

1. Apply patches 01, 02, 03 (fixes the silent-failure bugs). **High value, low risk.**
2. Re-run `/rotate yes` once — that re-generates credentials.env **without**
   the REALITY_DEST persistence, so future `flyctl secrets set REALITY_DEST=…`
   actually works.
3. Mint a new, app-scoped Fly token for the bot and re-`flyctl secrets set`;
   `flyctl tokens revoke` the old org-scoped one. **Big blast-radius reduction.**

If you have an afternoon this weekend:

4. Apply patches 04, 05 (quality-of-life).
5. Follow `recipes/hysteria-port-hopping.md` on a VPS (if you have one) —
   single biggest China-durability upgrade.
6. Follow `recipes/warp-outbound.md` on Fly — eliminates Fly IP reputation
   problems for good.

If you have a weekend project budget:

7. `recipes/cloudflare-ws-fallback.md` — true defence in depth.
8. `recipes/multi-region-failover.md` — `/failover sin→nrt` on demand.
9. `recipes/observability.md` — so you know when something's off before your
   client app tells you.

— end —
