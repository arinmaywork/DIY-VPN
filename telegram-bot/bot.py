"""DIY-VPN Telegram bot — control your Fly.io VPN from any device.

Required env vars:
  TG_BOT_TOKEN        — from @BotFather
  TG_ALLOWED_USERS    — comma-separated Telegram user IDs allowed to use the bot
  FLY_API_TOKEN       — `flyctl tokens create deploy --app diyvpn-sgad`
  DIYVPN_APP_NAME     — your VPN app name (e.g. "diyvpn-sgad")

Optional:
  TG_LOGLEVEL         — DEBUG/INFO/WARNING (default INFO)
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from lib import fly_api, vpn_ops
from lib.auth import authed
from lib.clients import PLATFORMS, overview_message, platform_message
from lib.links import host_for, hysteria2_link, vless_link
from lib.qr import qr_png

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=os.environ.get("TG_LOGLEVEL", "INFO"),
)
log = logging.getLogger("diyvpn-bot")

APP_NAME = os.environ["DIYVPN_APP_NAME"]


# ─── Telegram text helpers ───────────────────────────────────────────────────

TELEGRAM_MSG_LIMIT = 4000  # 96-char headroom under Telegram's 4096 hard cap


def chunk_for_telegram(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """Split `text` on newlines so each chunk is <= `limit` chars.

    Line-aware so we don't split a Markdown code span mid-backtick (which
    would unbalance the next chunk and render as literal text).
    """
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > limit and buf:
            chunks.append(buf)
            buf = ""
        if len(line) > limit:
            # Single line longer than limit — hard-split as a last resort.
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit])
            buf = ""
            continue
        buf += line
    if buf:
        chunks.append(buf)
    return chunks or [text]


# ─── Helpers ─────────────────────────────────────────────────────────────────


async def _pick_host() -> tuple[str, str] | None:
    """Returns (ip_address, label) — IPv4 if available, else IPv6."""
    ips = await fly_api.list_ips()
    v4 = next((i for i in ips if i.get("type") in ("v4", "shared_v4")), None)
    v6 = next((i for i in ips if i.get("type") == "v6"), None)
    if v4:
        return v4["address"], "IPv4"
    if v6:
        return v6["address"], "IPv6"
    return None


async def _credential_block() -> dict[str, str]:
    return await vpn_ops.read_credentials()


def _md_escape(s: str) -> str:
    """Telegram MarkdownV1 escape (for share links etc)."""
    return s.replace("`", "\\`").replace("_", "\\_").replace("*", "\\*")


# ─── /start, /help ────────────────────────────────────────────────────────────


@authed
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"DIY-VPN bot online. Controlling Fly app *{APP_NAME}*.\n"
        f"Send /help for the full command list.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*VPN power*\n"
        "/status — machine state, IPs, region\n"
        "/up — start the VPN machine\n"
        "/down — stop the VPN machine (saves $)\n"
        "/restart — restart the machine\n"
        "\n"
        "*Share links & QR codes*\n"
        "/links — share-link URIs (text)\n"
        "/qr — QR codes for VLESS + Hysteria2\n"
        "\n"
        "*IPv4 management*\n"
        "/ipv4 — show current IPs\n"
        "/ipv4\\_add — allocate dedicated IPv4 ($2/mo)\n"
        "/ipv4\\_release — release dedicated IPv4\n"
        "\n"
        "*Devices / users*\n"
        "/devices — list VLESS users + traffic + online sessions\n"
        "/adduser `<name>` — add a new device (returns its share links)\n"
        "/kick `<name>` — remove a device\n"
        "/rotate — wipe all credentials, regenerate (kicks everyone)\n"
        "\n"
        "*Client apps & setup*\n"
        "/apps — recommended client app per platform\n"
        "/setup `<platform>` — step-by-step setup guide\n"
        "    platforms: `ios`, `android`, `windows`, `macos`, `linux`\n"
        "\n"
        "*Misc*\n"
        "/logs — last 50 lines of VPN logs\n"
        "/whoami — show your Telegram ID\n"
        "/help — this message"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_apps(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Quick overview of recommended clients per platform."""
    await update.message.reply_text(
        overview_message(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


@authed
async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Platform-specific setup walkthrough. Usage: /setup ios|android|windows|macos|linux"""
    if not ctx.args:
        # No arg: show overview + prompt.
        await update.message.reply_text(
            overview_message(),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        return

    key = ctx.args[0].strip().lower()
    # Accept a few common aliases.
    alias = {
        "iphone": "ios", "ipad": "ios", "apple": "ios",
        "mac": "macos", "osx": "macos",
        "win": "windows", "pc": "windows",
        "droid": "android",
    }
    key = alias.get(key, key)

    if key not in PLATFORMS:
        await update.message.reply_text(
            f"Unknown platform `{key}`. Options: "
            + ", ".join(f"`{k}`" for k in PLATFORMS.keys()),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await update.message.reply_text(
        platform_message(key),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    # Nudge the user toward the next step.
    await update.message.reply_text(
        "When you're at the *import* step, send `/qr` (or `/qr <device-name>` "
        "if you've added per-device users with `/adduser`).",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    await update.message.reply_text(
        f"User ID: `{u.id}`\nName: {u.full_name}\nUsername: @{u.username or '-'}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Power ────────────────────────────────────────────────────────────────────


@authed
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    machine = await fly_api.get_primary_machine()
    if not machine:
        await update.message.reply_text("No machines exist for this app.")
        return
    ips = await fly_api.list_ips()
    ip_lines = "\n".join(f"  • `{i['address']}` ({i['type']})" for i in ips) or "  (none)"
    text = (
        f"*App:* `{APP_NAME}`\n"
        f"*Machine:* `{machine['id']}`\n"
        f"*State:* `{machine.get('state')}`\n"
        f"*Region:* `{machine.get('region')}`\n"
        f"*Image:* `{(machine.get('config') or {}).get('image','?')}`\n"
        f"*IPs:*\n{ip_lines}"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_up(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    machine = await fly_api.get_primary_machine()
    if not machine:
        await update.message.reply_text("No machine to start. Did you run flyio/deploy.sh?")
        return
    await fly_api.start_machine(machine["id"])
    await update.message.reply_text(
        f"Starting machine `{machine['id']}`. Use /status in ~10 s to confirm.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_down(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    machine = await fly_api.get_primary_machine()
    if not machine:
        await update.message.reply_text("No machine to stop.")
        return
    await fly_api.stop_machine(machine["id"])
    await update.message.reply_text(
        f"Stopping machine `{machine['id']}`. The VPN will be unreachable until /up.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    machine = await fly_api.get_primary_machine()
    if not machine:
        await update.message.reply_text("No machine to restart.")
        return
    await fly_api.restart_machine(machine["id"])
    await update.message.reply_text("Restart sent. Should be back in ~10 s.")


# ─── Share links + QR ────────────────────────────────────────────────────────


async def _build_links_for_user(name: str = "default") -> list[tuple[str, str, str]]:
    """Returns list of (label, vless_url, hy2_url) tuples for the named user.

    One entry per allocated IP (so v4 + v6 give two pairs).
    """
    creds = await _credential_block()
    users = await vpn_ops.read_users()
    user = next((u for u in users if u.get("name") == name), None)
    if not user:
        raise ValueError(f"No user named '{name}'. Try /devices.")

    ips = await fly_api.list_ips()
    out: list[tuple[str, str, str]] = []
    for ip in ips:
        host = host_for(ip["address"])
        v = vless_link(
            host=host,
            uuid=user["uuid"],
            public_key=creds["REALITY_PUBLIC_KEY"],
            sni=creds["REALITY_SNI"],
            short_id=creds["REALITY_SHORT_ID"],
            flow=user.get("flow", "xtls-rprx-vision"),
            remark=f"DIY-VPN Reality {name} ({ip['type']})",
        )
        h = hysteria2_link(
            host=host,
            password=creds["HY2_PASSWORD"],
            obfs_password=creds["HY2_OBFS_PASSWORD"],
            remark=f"DIY-VPN Hy2 {name} ({ip['type']})",
        )
        out.append((ip["type"], v, h))
    return out


@authed
async def cmd_links(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = (ctx.args[0] if ctx.args else "default").strip()
    try:
        links = await _build_links_for_user(name)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    if not links:
        await update.message.reply_text(
            "No IPs allocated yet. Use /ipv4\\_add or check `flyctl ips list`.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    chunks = [f"*Share links for `{name}`:*"]
    for label, v, h in links:
        chunks.append(f"\n*{label} — VLESS Reality:*\n`{v}`")
        chunks.append(f"\n*{label} — Hysteria2:*\n`{h}`")
    text = "\n".join(chunks)
    for piece in chunk_for_telegram(text):
        await update.message.reply_text(piece, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_qr(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = (ctx.args[0] if ctx.args else "default").strip()
    try:
        links = await _build_links_for_user(name)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    if not links:
        await update.message.reply_text("No IPs allocated yet. /ipv4\\_add first.",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    for label, v, h in links:
        await update.message.reply_photo(
            photo=InputFile(BytesIO(qr_png(v)), filename=f"vless-{label}.png"),
            caption=f"VLESS Reality ({label}) — `{name}`",
            parse_mode=ParseMode.MARKDOWN,
        )
        await update.message.reply_photo(
            photo=InputFile(BytesIO(qr_png(h)), filename=f"hy2-{label}.png"),
            caption=f"Hysteria2 ({label}) — `{name}`",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─── IPv4 ─────────────────────────────────────────────────────────────────────


@authed
async def cmd_ipv4(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ips = await fly_api.list_ips()
    if not ips:
        await update.message.reply_text("No IPs allocated.")
        return
    lines = [f"`{i['address']}` — {i['type']} ({i.get('region') or 'global'})" for i in ips]
    await update.message.reply_text("*IPs:*\n" + "\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_ipv4_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Allocating dedicated IPv4 ($2/mo)...")
    try:
        addr = await fly_api.allocate_ipv4(dedicated=True)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Allocated `{addr}`. Run /restart so the VPN picks it up cleanly,"
        f" then /qr or /links to get fresh share-links.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_ipv4_release(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    ips = await fly_api.list_ips()
    v4s = [i for i in ips if i.get("type") in ("v4", "shared_v4")]
    if not v4s:
        await update.message.reply_text("No IPv4 to release.")
        return
    released = []
    for ip in v4s:
        try:
            await fly_api.release_ip(ip["address"])
            released.append(ip["address"])
        except Exception as e:
            await update.message.reply_text(f"Failed to release {ip['address']}: {e}")
    if released:
        await update.message.reply_text(
            "Released:\n" + "\n".join(f"`{a}`" for a in released)
            + "\nClients with v4 share-links will need fresh ones (use /qr or /links).",
            parse_mode=ParseMode.MARKDOWN,
        )


# ─── Devices / users ──────────────────────────────────────────────────────────


@authed
async def cmd_devices(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        users = await vpn_ops.read_users()
    except Exception as e:
        await update.message.reply_text(f"Couldn't read users.json: {e}")
        return

    machine = await fly_api.get_primary_machine()
    if (machine or {}).get("state") != "started":
        # Stats need xray running. Fall back to just listing configured users.
        lines = [f"• `{u['name']}` (uuid: `{u['uuid'][:8]}…`)" for u in users]
        await update.message.reply_text(
            "*Configured devices (VPN is OFFLINE — start it for live stats):*\n"
            + "\n".join(lines),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        stats = await vpn_ops.query_stats()
        online = await vpn_ops.query_online()
    except Exception as e:
        await update.message.reply_text(f"Couldn't query xray stats: {e}")
        stats = {"users": {}, "inbound": {}}
        online = {}

    lines = ["*Devices:*"]
    for u in users:
        email = u.get("email", f"{u['name']}@diyvpn")
        s = stats["users"].get(email, {})
        up = vpn_ops.fmt_bytes(int(s.get("uplink", 0)))
        dn = vpn_ops.fmt_bytes(int(s.get("downlink", 0)))
        on = online.get(email, 0)
        dot = "🟢" if on else "⚪"
        lines.append(
            f"{dot} `{u['name']}` — online: {on}, ↑ {up} / ↓ {dn}"
        )

    inbound_lines = []
    for tag, s in stats["inbound"].items():
        if tag == "api-in":
            continue
        up = vpn_ops.fmt_bytes(int(s.get("uplink", 0)))
        dn = vpn_ops.fmt_bytes(int(s.get("downlink", 0)))
        inbound_lines.append(f"`{tag}`: ↑ {up} / ↓ {dn}")
    if inbound_lines:
        lines.append("\n*Inbound totals:*")
        lines.extend(inbound_lines)

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_adduser(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /adduser `<name>` (e.g. /adduser iphone)",
                                        parse_mode=ParseMode.MARKDOWN)
        return
    name = ctx.args[0].strip()
    try:
        info = await vpn_ops.add_user(name)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Added `{info['name']}` (uuid `{info['uuid']}`). Restarting VPN to apply...\n"
        f"In ~15 s, send `/qr {name}` to get its share links.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /kick `<name>`", parse_mode=ParseMode.MARKDOWN)
        return
    name = ctx.args[0].strip()
    try:
        ok = await vpn_ops.remove_user(name)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    if not ok:
        await update.message.reply_text(f"No device named `{name}`.", parse_mode=ParseMode.MARKDOWN)
        return
    await update.message.reply_text(
        f"Removed `{name}`. Restarting VPN to apply...", parse_mode=ParseMode.MARKDOWN
    )


@authed
async def cmd_rotate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    confirm = (ctx.args[0] if ctx.args else "").lower()
    if confirm != "yes":
        await update.message.reply_text(
            "This wipes ALL credentials (UUIDs, Reality keys, Hysteria2 passwords) "
            "and regenerates fresh ones. Every existing client share-link will stop "
            "working and you'll need to re-import on every device.\n\n"
            "If you really want to do this, send: `/rotate yes`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    await update.message.reply_text("Wiping credentials and restarting...")
    try:
        await vpn_ops.rotate_credentials()
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        "Done. Wait ~30 s, then send /qr to get the new share-links.")


# ─── Logs ─────────────────────────────────────────────────────────────────────


@authed
async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        out = await fly_api.fetch_logs(50)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    if not out.strip():
        out = "(no log lines)"
    # Line-aware chunking so Markdown code fences don't get broken.
    for ch in chunk_for_telegram(out, limit=3900):
        await update.message.reply_text(f"```\n{ch}\n```", parse_mode=ParseMode.MARKDOWN)


# ─── Bootstrap ───────────────────────────────────────────────────────────────


def main() -> None:
    token = os.environ["TG_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("up", cmd_up))
    app.add_handler(CommandHandler("down", cmd_down))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("links", cmd_links))
    app.add_handler(CommandHandler("qr", cmd_qr))
    app.add_handler(CommandHandler("ipv4", cmd_ipv4))
    app.add_handler(CommandHandler("ipv4_add", cmd_ipv4_add))
    app.add_handler(CommandHandler("ipv4_release", cmd_ipv4_release))
    app.add_handler(CommandHandler("devices", cmd_devices))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("rotate", cmd_rotate))
    app.add_handler(CommandHandler("apps", cmd_apps))
    app.add_handler(CommandHandler("setup", cmd_setup))
    app.add_handler(CommandHandler("logs", cmd_logs))

    log.info("DIY-VPN bot starting (controlling app=%s)", APP_NAME)
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
