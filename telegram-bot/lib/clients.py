"""Client app recommendations + setup guides, per platform.

Kept in a separate module so you can edit/extend it without touching bot.py.

If you find a better client for a given OS, just update the entry here.
The only hard requirement: it must support BOTH VLESS+Reality (with
xtls-rprx-vision flow) AND Hysteria2 with Salamander obfuscation.
"""

from __future__ import annotations

# ─── Per-platform client recommendations ─────────────────────────────────────

PLATFORMS: dict[str, dict] = {
    "ios": {
        "label": "iPhone / iPad",
        "emoji": "📱",
        "primary": {
            "name": "V2Box — V2ray Client",
            "vendor": "Bear Hill / techlaim",
            "store": "App Store (free)",
            "url": "https://apps.apple.com/app/v2box-v2ray-client/id6446814690",
            "why": "Free, supports VLESS+Reality with Vision flow AND Hysteria2 with Salamander. No ads.",
        },
        "alternatives": [
            {"name": "Shadowrocket", "note": "$2.99, very polished, same protocol support.",
             "url": "https://apps.apple.com/app/shadowrocket/id932747118"},
            {"name": "Streisand", "note": "Free, open-source, slightly less refined UI.",
             "url": "https://apps.apple.com/app/streisand/id6450534064"},
        ],
        "steps": [
            "Install V2Box from the App Store.",
            "Send me `/qr` in this chat — I'll reply with QR codes.",
            "In V2Box, tap the `+` in the top-right, choose *Import from QR Code*.",
            "Scan the *VLESS Reality* QR first. (Optionally scan the Hysteria2 one too as a backup profile.)",
            "Tap the profile, toggle the big power button. On first connect iOS will ask to install a VPN profile — accept.",
            "Open Safari, go to https://ifconfig.co — it should show the VPN's IP, not your carrier's.",
        ],
    },
    "android": {
        "label": "Android",
        "emoji": "🤖",
        "primary": {
            "name": "v2rayNG",
            "vendor": "2dust",
            "store": "Google Play / GitHub release",
            "url": "https://github.com/2dust/v2rayNG/releases/latest",
            "why": "The reference VLESS+Reality client on Android. Open source. Pairs well with Hysteria2 via built-in support.",
        },
        "alternatives": [
            {"name": "NekoBox for Android",
             "note": "Friendlier UI, supports both protocols, active development.",
             "url": "https://github.com/MatsuriDayo/NekoBoxForAndroid/releases/latest"},
            {"name": "Hiddify",
             "note": "Official Hysteria2 client if you only want UDP. VLESS also supported.",
             "url": "https://github.com/hiddify/hiddify-next/releases/latest"},
        ],
        "steps": [
            "On your phone, open the v2rayNG Play Store page (link above) and install. (Or sideload the APK from the GitHub release.)",
            "Send me `/qr` here — I'll send QR codes.",
            "In v2rayNG tap the `+` icon (bottom right) → *Import config from QRcode*.",
            "Point your phone's camera at your laptop showing the VLESS Reality QR. (You can repeat for the Hysteria2 QR.)",
            "Tap the round icon at the bottom to connect. Android will prompt once for VPN permission — approve.",
            "Confirm at https://ifconfig.co that your IP changed.",
        ],
    },
    "windows": {
        "label": "Windows",
        "emoji": "🪟",
        "primary": {
            "name": "Nekoray",
            "vendor": "MatsuriDayo",
            "store": "GitHub release (free, open source)",
            "url": "https://github.com/MatsuriDayo/nekoray/releases/latest",
            "why": "Full support for VLESS+Reality AND Hysteria2, per-app routing, clean UI. Works portable (no install needed).",
        },
        "alternatives": [
            {"name": "v2rayN",
             "note": "More spartan UI; if Nekoray doesn't work on your machine try this.",
             "url": "https://github.com/2dust/v2rayN/releases/latest"},
            {"name": "Hiddify (Windows)",
             "note": "Cross-platform clone of v2rayN. Good fallback.",
             "url": "https://github.com/hiddify/hiddify-next/releases/latest"},
        ],
        "steps": [
            "Download `nekoray-*-windows64.zip` from the release page and extract it anywhere.",
            "Run `nekoray.exe`. (Windows Defender may warn — it's a portable binary, click *More info → Run anyway*.)",
            "Send me `/links` here and copy the VLESS Reality URI (or the Hysteria2 one).",
            "In Nekoray: *Program → Add profile from clipboard* (Ctrl+V works too). The profile appears in the list.",
            "Right-click the profile → *Start*. You should see a green dot.",
            "Open https://ifconfig.co in your browser — the IP should match `/ipv4` here.",
        ],
    },
    "macos": {
        "label": "Mac (macOS)",
        "emoji": "🍎",
        "primary": {
            "name": "V2Box — V2ray Client",
            "vendor": "Bear Hill / techlaim",
            "store": "Mac App Store (free)",
            "url": "https://apps.apple.com/app/v2box-v2ray-client/id6446814690",
            "why": "Same app as iOS. Free, signed, supports both protocols. Menu-bar icon for quick toggle.",
        },
        "alternatives": [
            {"name": "FoXray",
             "note": "Also free, also on the App Store. Worth trying if V2Box misbehaves.",
             "url": "https://apps.apple.com/app/foxray/id6448898396"},
            {"name": "Hiddify-Next",
             "note": "Cross-platform, more features. Can be flaky on Apple Silicon.",
             "url": "https://github.com/hiddify/hiddify-next/releases/latest"},
        ],
        "steps": [
            "Install V2Box from the Mac App Store (link above).",
            "Send me `/links` in this chat — I'll send the VLESS and Hysteria2 URIs.",
            "Copy the VLESS link to your clipboard.",
            "In V2Box, click the `+` button → *Import V2ray URI from clipboard*.",
            "Click the small power icon next to the profile. macOS will ask to install a VPN profile once — allow it.",
            "Verify in Terminal: `curl https://ifconfig.co` — should print the VPN's IP.",
        ],
    },
    "linux": {
        "label": "Linux",
        "emoji": "🐧",
        "primary": {
            "name": "Nekoray (Linux AppImage)",
            "vendor": "MatsuriDayo",
            "store": "GitHub release",
            "url": "https://github.com/MatsuriDayo/nekoray/releases/latest",
            "why": "Same UI as the Windows build, distributed as a single AppImage. Supports VLESS+Reality + Hysteria2.",
        },
        "alternatives": [
            {"name": "xray-core (CLI)",
             "note": "If you want a headless tunnel: run xray with the client-side JSON. Best for servers/routers.",
             "url": "https://github.com/XTLS/Xray-core/releases/latest"},
            {"name": "Hiddify-Next",
             "note": "GUI client, multi-protocol, cross-distro AppImage.",
             "url": "https://github.com/hiddify/hiddify-next/releases/latest"},
        ],
        "steps": [
            "Download the Linux AppImage from the Nekoray release page.",
            "`chmod +x nekoray-*.AppImage && ./nekoray-*.AppImage` to launch it.",
            "Send me `/links` here and copy the VLESS Reality URI.",
            "In Nekoray: *Program → Add profile from clipboard*.",
            "Right-click the profile → *Start*.",
            "Confirm with `curl https://ifconfig.co` in a terminal.",
        ],
    },
}


def platform_message(key: str) -> str:
    """Render a single platform's setup info as Markdown for Telegram."""
    p = PLATFORMS[key]
    lines: list[str] = [
        f"{p['emoji']} *{p['label']} — setup*",
        "",
        f"*Recommended client:* [{p['primary']['name']}]({p['primary']['url']})",
        f"_{p['primary']['store']}_ — {p['primary']['why']}",
        "",
        "*Steps:*",
    ]
    for i, step in enumerate(p["steps"], 1):
        lines.append(f"{i}. {step}")
    if p.get("alternatives"):
        lines.append("")
        lines.append("*Alternatives if that one doesn't work for you:*")
        for alt in p["alternatives"]:
            lines.append(f"• [{alt['name']}]({alt['url']}) — {alt['note']}")
    return "\n".join(lines)


def overview_message() -> str:
    """Short summary listing every platform and its recommended client."""
    lines = ["*Client apps per platform:*", ""]
    for key, p in PLATFORMS.items():
        lines.append(
            f"{p['emoji']} *{p['label']}* — [{p['primary']['name']}]({p['primary']['url']})"
        )
    lines += [
        "",
        "Send `/setup <platform>` for step-by-step instructions.",
        "Platforms: `ios`, `android`, `windows`, `macos`, `linux`",
        "",
        "Then `/qr` (or `/qr <device-name>`) to scan the code into your client.",
    ]
    return "\n".join(lines)
