# 03 — Client setup (Windows · macOS · Android · iOS)

You have two share links from the installer:

```
vless://...               ← Reality (use this most of the time)
hysteria2://...           ← Hysteria2 (switch when you want max speed / streaming)
```

Pick your OS below.

---

## Recommended client apps (all free, except Shadowrocket on iOS)

| OS | App | Reality | Hysteria2 | Cost | Where |
|---|---|---|---|---|---|
| **Windows** | **v2rayN** | ✓ | ✓ (via core) | Free | https://github.com/2dust/v2rayN/releases |
| Windows (alt) | NekoRay / NekoBox | ✓ | ✓ | Free | https://github.com/MatsuriDayo/nekoray/releases |
| **macOS** | **FoxRay** | ✓ | ✓ | Free | Mac App Store |
| macOS (alt) | V2Box / Clash Verge Rev | ✓ | ✓ | Free | Mac App Store / GitHub |
| **Android** | **v2rayNG** | ✓ | ✗ (use NekoBox for Hy2) | Free | https://github.com/2dust/v2rayNG/releases |
| Android (Hy2) | **NekoBox for Android** | ✓ | ✓ | Free | https://github.com/MatsuriDayo/NekoBoxForAndroid/releases |
| **iOS** | **Streisand** | ✓ | ✓ | Free | App Store (search "Streisand") |
| iOS (premium) | **Shadowrocket** | ✓ | ✓ | $2.99 one-time | App Store (US/JP/etc., NOT China store) |

> **iOS note:** apps like Streisand, Shadowrocket, Quantumult X, and Stash are not available in the China App Store. You need a non-China Apple ID (free to make any non-China region account) to download them.

---

## Windows — v2rayN

1. Download the latest `v2rayN-windows-64-desktop.zip` from https://github.com/2dust/v2rayN/releases
2. Extract anywhere (e.g., `C:\Tools\v2rayN`). Run `v2rayN.exe`.
3. **First launch:** it may prompt to download Xray-core. Click yes.
4. **Add Reality server:**
   - Top-left **Servers → Import bulk URL from clipboard**
   - Copy your `vless://...` link first; v2rayN reads from clipboard.
   - You should see one row added in the server list. ✓
5. **Add Hysteria2 server:**
   - Same again with the `hysteria2://...` link.
   - You'll now see two rows: Reality and Hysteria2.
6. **Pick the active server:** double-click the row you want to use.
7. **Routing mode** (bottom of the window):
   - **"Bypass mainland"** = sites/IPs in China go direct, everything else through VPN. Use this if you're in China.
   - **"Global"** = everything through VPN.
   - **"Bypass LAN and mainland"** = China + your local network go direct.
8. **System proxy:** click `System Proxy → Set system proxy` (icon in tray).
9. **Test:** open a browser → https://ipinfo.io/ → should show your VM's IP, not yours.

**v2rayN tips:**
- Right-click a server → **Test real delay (single)** to ping it.
- For fastest experience: **Servers → Test all real delays** then pick the lowest.
- Disable system proxy when not needed: tray icon → `System Proxy → Clear system proxy`.

---

## macOS — FoxRay (free, App Store)

1. Open the **Mac App Store** and install **FoxRay**.
2. Open FoxRay. First launch: grant VPN permission when prompted.
3. **Add Reality server:**
   - Click the **+** button → **Import from clipboard**
   - Copy your `vless://...` link first.
4. **Add Hysteria2 server:** same process with the `hysteria2://...` link.
5. Click a server's row to select; click **Connect** (toggle in upper right).
6. **Test:** Safari → https://ipinfo.io/ → should show server IP.

**Routing modes:** FoxRay defaults to "Rule-based" which sends China IPs direct and the rest through VPN. Good for inside China. For travel use cases (geo-unblocking), switch to "Global" in settings.

**Alternative (very polished UI): Clash Verge Rev**
- Free, open source — https://github.com/clash-verge-rev/clash-verge-rev/releases
- Better dashboard, traffic graphs, per-app routing
- Slightly steeper learning curve. Reality + Hy2 both supported.

---

## Android — v2rayNG (Reality) + NekoBox (Hysteria2)

### Option A — Use both apps

1. Install **v2rayNG** from the Play Store *or* its GitHub releases (more up to date): https://github.com/2dust/v2rayNG/releases
2. Open v2rayNG → top-right **+** → **Import config from clipboard**.
3. Copy your `vless://...` link from a desktop and paste in (or have someone send it to you).
4. Tap the server, then tap the big V (start) button at the bottom.
5. Allow the VPN permission prompt.

For Hysteria2, install **NekoBox for Android** (https://github.com/MatsuriDayo/NekoBoxForAndroid/releases):
1. Open NekoBox → **+** → **Import from clipboard**.
2. Tap your Hy2 server → toggle the connect switch at the top.

### Option B — One app for both (recommended)

Just use **NekoBox for Android** for both. It supports Reality and Hysteria2 in one place.

### Easy QR import

On the server, run:
```bash
sudo ./scripts/generate-client-links.sh
```
Both QR codes are printed. Open v2rayNG/NekoBox → **+** → **Scan QR code** → point your phone at the terminal. Done in 5 seconds.

---

## iOS — Streisand (free) or Shadowrocket ($2.99)

> You need a non-China Apple ID. Streisand is free; Shadowrocket has nicer UX.

### Streisand (free)

1. Install **Streisand** from the App Store.
2. Open it → top-right **+** → **Type a URL or scan QR**.
3. Paste your `vless://...` (or scan QR). Tap **Save**.
4. Repeat for `hysteria2://...`.
5. Tap the server → toggle Connect → allow VPN permission.

### Shadowrocket ($2.99)

1. Install **Shadowrocket** from the App Store.
2. Tap **+** (top right) → Shadowrocket auto-detects clipboard share links and offers to add them. (Or scan a QR.)
3. After both are added, tap a server, then flick the Connect toggle.

**iOS routing tips:** in either app, set "Routing → Config" to a Chinese-routing rule set if you'll use it inside China:
- Streisand: Settings → Route → "Bypass China"
- Shadowrocket: Configuration → "Bypass LAN & China" (this is shipped)

---

## When to use which protocol?

| Situation | Use |
|---|---|
| First-time test, anywhere | **Reality (TCP/443)** |
| Inside China, normal browsing/work | **Reality** |
| Inside China, streaming / large download / video calls | **Hysteria2** if UDP isn't blocked, else Reality |
| Hotel wifi / corporate network blocking UDP | **Reality** |
| Mobile data, want best speed | **Hysteria2** |
| Reality suddenly slow | switch to **Hysteria2** (port-hopping route may be faster) |
| Hysteria2 slow / dropping | switch to **Reality** (TCP routes are more deterministic) |

The flexibility of running both is the whole point — switch in one tap when one is having a bad day.

---

## Sanity-check the connection

After connecting, visit:

- **https://ipinfo.io/** — confirm IP is your VM's IP and country is your server's region.
- **https://browserleaks.com/ip** — confirms WebRTC and DNS leak status. Should show only the VM's IP.
- **https://fast.com/** — Netflix-run speed test. Realistic numbers from where your VM lives.

If your real IP leaks via WebRTC, you can disable WebRTC in your browser (Chrome: install "WebRTC Network Limiter"; Firefox: `about:config` → `media.peerconnection.enabled = false`). Most modern VPN clients route WebRTC traffic through the tunnel, but worth checking.

---

## Adding more devices later

Run `sudo ./scripts/generate-client-links.sh` on the server any time. Same UUIDs/passwords; same share links. Add to as many devices as you want — just be aware that simultaneous heavy use will share the same bandwidth pool.

Multiple users? You can add additional UUIDs to the Xray config and additional Hy2 password entries; not covered here but easy to extend.

---

Next → [04-TROUBLESHOOTING.md](04-TROUBLESHOOTING.md)
