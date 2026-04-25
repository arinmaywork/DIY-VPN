"""DIY-VPN Telegram bot — control your Oracle Cloud VPN over SSH.

Required env vars:
  TG_BOT_TOKEN        — from @BotFather
  TG_ALLOWED_USERS    — comma-separated Telegram user IDs allowed to use the bot
  VPN_HOST            — public IPv4 of the VPN box (e.g. "40.233.120.150")

Optional:
  VPN_SSH_USER        — default "ubuntu"
  VPN_SSH_KEY_PATH    — default "~/.ssh/diyvpn-oracle"
  VPN_SSH_PORT        — default "22"
  TG_LOGLEVEL         — DEBUG/INFO/WARNING (default INFO)
"""

from __future__ import annotations

import logging
import os
from io import BytesIO

from telegram import InputFile, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from lib import server_api, vpn_ops
from lib.auth import authed
from lib.clients import PLATFORMS, overview_message, platform_message
from lib.links import host_for, hysteria2_link, vless_link
from lib.qr import qr_png

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=os.environ.get("TG_LOGLEVEL", "INFO"),
)
log = logging.getLogger("diyvpn-bot")


# ─── Helpers ─────────────────────────────────────────────────────────────────

TELEGRAM_MSG_LIMIT = 4000


def chunk_for_telegram(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    """Split on newlines so each chunk is <= limit chars (preserves Markdown)."""
    chunks: list[str] = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > limit and buf:
            chunks.append(buf)
            buf = ""
        if len(line) > limit:
            for i in range(0, len(line), limit):
                chunks.append(line[i:i + limit])
            buf = ""
            continue
        buf += line
    if buf:
        chunks.append(buf)
    return chunks or [text]


async def _build_links_for_user(name: str = "default") -> tuple[str, str, dict]:
    """Returns (vless_url, hy2_url, user_dict) for the named user."""
    creds = await vpn_ops.read_credentials()
    users = await vpn_ops.read_users()
    user = next((u for u in users if u.get("name") == name), None)
    if not user:
        raise ValueError(f"No user named '{name}'. Try /devices.")

    host = host_for(server_api.host())
    v = vless_link(
        host=host,
        uuid=user["uuid"],
        public_key=creds["REALITY_PUBLIC_KEY"],
        sni=creds["REALITY_SNI"],
        short_id=creds["REALITY_SHORT_ID"],
        flow=user.get("flow", "xtls-rprx-vision"),
        remark=f"DIY-VPN Reality {name}",
    )
    h = hysteria2_link(
        host=host,
        password=user["hy2_password"],
        remark=f"DIY-VPN Hy2 {name}",
    )
    return v, h, user


# ─── /start, /help, /whoami ───────────────────────────────────────────────────


@authed
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"DIY-VPN bot online. Controlling box `{server_api.host()}`.\n"
        f"Send /help for the full command list.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "*Share links & QR*\n"
        "/links `[name]` — share-link URIs (default user if no name)\n"
        "/qr `[name]` — QR codes for VLESS + Hy2\n"
        "\n"
        "*Devices / users*\n"
        "/devices — list users + traffic + online sessions + expiry\n"
        "/adduser `<name> [priority]` — add a permanent device\n"
        "/temp `<name> <hours> [priority]` — add a time-limited device\n"
        "/priority `<name> <high|normal|low>` — change priority tier\n"
        "/kick `<name>` — remove a device\n"
        "/rotate `<name>` — regenerate UUID + Hy2 password for one device\n"
        "/rotate `all yes` — nuke everything (kicks all)\n"
        "\n"
        "*Server health*\n"
        "/status — services + listening sockets\n"
        "/logs `<auth|hysteria|xray>` — last 30 journalctl lines\n"
        "\n"
        "*Client apps & setup*\n"
        "/apps — recommended client per platform\n"
        "/setup `<ios|android|windows|macos|linux>` — step-by-step\n"
        "\n"
        "*Misc*\n"
        "/whoami — show your Telegram ID\n"
        "/help — this message"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_whoami(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    u = update.effective_user
    await update.message.reply_text(
        f"User ID: `{u.id}`\nName: {u.full_name}\nUsername: @{u.username or '-'}",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Apps + setup ─────────────────────────────────────────────────────────────


@authed
async def cmd_apps(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        overview_message(),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


@authed
async def cmd_setup(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text(
            overview_message(),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
        return
    key = ctx.args[0].strip().lower()
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
    await update.message.reply_text(
        "When you're at the *import* step, send `/qr` (or `/qr <device-name>` "
        "if you've added per-device users with `/adduser`).",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Share links + QR ─────────────────────────────────────────────────────────


@authed
async def cmd_links(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = (ctx.args[0] if ctx.args else "default").strip()
    try:
        v, h, _u = await _build_links_for_user(name)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    text = (
        f"*Share links for `{name}`:*\n"
        f"\n*VLESS Reality (TCP, fallback):*\n`{v}`"
        f"\n\n*Hysteria2 (UDP, primary):*\n`{h}`"
    )
    for piece in chunk_for_telegram(text):
        await update.message.reply_text(piece, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_qr(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    name = (ctx.args[0] if ctx.args else "default").strip()
    try:
        v, h, _u = await _build_links_for_user(name)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")
        return
    await update.message.reply_photo(
        photo=InputFile(BytesIO(qr_png(v)), filename=f"vless-{name}.png"),
        caption=f"VLESS Reality — `{name}`",
        parse_mode=ParseMode.MARKDOWN,
    )
    await update.message.reply_photo(
        photo=InputFile(BytesIO(qr_png(h)), filename=f"hy2-{name}.png"),
        caption=f"Hysteria2 — `{name}`",
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
        prio = u.get("priority", "normal")
        exp = vpn_ops.fmt_expiry(u.get("expires_at"))
        prio_marker = {"high": "⚡", "normal": "", "low": "🐢"}.get(prio, "")
        lines.append(
            f"{dot} `{u['name']}` {prio_marker}— online: {on}, ↑ {up} / ↓ {dn} | exp: {exp}"
        )

    inbound_lines: list[str] = []
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
        await update.message.reply_text(
            "Usage: `/adduser <name> [priority]`\n"
            "  priority: `high`, `normal` (default), or `low`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = ctx.args[0].strip()
    priority = (ctx.args[1].strip().lower() if len(ctx.args) > 1 else "normal")
    try:
        info = await vpn_ops.add_user(name, priority=priority)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Added `{info['name']}` (priority `{info['priority']}`).\n"
        f"Send `/qr {name}` to scan its share links.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_temp(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Usage: `/temp <name> <hours> [priority]`\n"
            "Example: `/temp guest 24` adds 'guest' for 24 hours",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = ctx.args[0].strip()
    try:
        hours = float(ctx.args[1])
    except ValueError:
        await update.message.reply_text("hours must be a number")
        return
    priority = (ctx.args[2].strip().lower() if len(ctx.args) > 2 else "normal")
    try:
        info = await vpn_ops.temp_user(name, hours, priority=priority)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"Added `{info['name']}` — expires {vpn_ops.fmt_expiry(info['expires_at'])}.\n"
        f"Send `/qr {name}` for share links.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_priority(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if len(ctx.args) < 2:
        await update.message.reply_text(
            "Usage: `/priority <name> <high|normal|low>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    name = ctx.args[0].strip()
    prio = ctx.args[1].strip().lower()
    try:
        info = await vpn_ops.set_priority(name, prio)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"`{info['name']}` priority is now `{info['priority']}`.",
        parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_kick(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: `/kick <name>`", parse_mode=ParseMode.MARKDOWN)
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
        f"Removed `{name}`.", parse_mode=ParseMode.MARKDOWN,
    )


@authed
async def cmd_rotate(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text(
            "Usage:\n"
            "`/rotate <name>` — rotate one user's UUID + Hy2 password\n"
            "`/rotate all yes` — nuke everything (kicks all clients)",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    target = ctx.args[0].strip()
    if target == "all":
        if (ctx.args[1].lower() if len(ctx.args) > 1 else "") != "yes":
            await update.message.reply_text(
                "This wipes ALL credentials (Reality keys, every UUID, every Hy2 password).\n"
                "Confirm with: `/rotate all yes`",
                parse_mode=ParseMode.MARKDOWN,
            )
            return
        await update.message.reply_text("Rotating server-wide...")
        try:
            await vpn_ops.rotate_all_credentials()
        except Exception as e:
            await update.message.reply_text(f"Failed: {e}")
            return
        await update.message.reply_text(
            "Done. Every share-link is dead. Use /qr per-user to get fresh ones."
        )
        return

    # Single user
    try:
        info = await vpn_ops.rotate_user(target)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    await update.message.reply_text(
        f"`{info['name']}` rotated. Send `/qr {info['name']}` for the new link.",
        parse_mode=ParseMode.MARKDOWN,
    )


# ─── Server health ────────────────────────────────────────────────────────────


@authed
async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        states = await server_api.sudo_exec(
            "for s in diyvpn-auth hysteria-server xray; do "
            "  echo \"$s: $(systemctl is-active $s)\"; "
            "done"
        )
        sockets = await server_api.sudo_exec(
            "ss -lntup 2>/dev/null | awk 'NR==1 || /:(443|8080|10085|25413) /' | head -20"
        )
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    text = (
        f"*Box:* `{server_api.host()}`\n"
        f"\n*Services:*\n```\n{states.strip()}\n```"
        f"\n*Listening on key ports:*\n```\n{sockets.strip()}\n```"
    )
    for piece in chunk_for_telegram(text, limit=3900):
        await update.message.reply_text(piece, parse_mode=ParseMode.MARKDOWN)


@authed
async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text(
            "Usage: `/logs <auth|hysteria|xray>`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    key = ctx.args[0].strip().lower()
    unit_map = {
        "auth": "diyvpn-auth",
        "hysteria": "hysteria-server",
        "hy2": "hysteria-server",
        "xray": "xray",
    }
    unit = unit_map.get(key)
    if not unit:
        await update.message.reply_text(
            f"Unknown unit `{key}`. Options: `auth`, `hysteria`, `xray`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    try:
        out = await server_api.fetch_logs(unit, lines=30)
    except Exception as e:
        await update.message.reply_text(f"Failed: {e}")
        return
    if not out.strip():
        out = "(no log lines)"
    for ch in chunk_for_telegram(out, limit=3900):
        await update.message.reply_text(f"```\n{ch}\n```", parse_mode=ParseMode.MARKDOWN)


# ─── Bootstrap ────────────────────────────────────────────────────────────────


def main() -> None:
    token = os.environ["TG_BOT_TOKEN"]
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("whoami", cmd_whoami))
    app.add_handler(CommandHandler("links", cmd_links))
    app.add_handler(CommandHandler("qr", cmd_qr))
    app.add_handler(CommandHandler("devices", cmd_devices))
    app.add_handler(CommandHandler("adduser", cmd_adduser))
    app.add_handler(CommandHandler("temp", cmd_temp))
    app.add_handler(CommandHandler("priority", cmd_priority))
    app.add_handler(CommandHandler("kick", cmd_kick))
    app.add_handler(CommandHandler("rotate", cmd_rotate))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("apps", cmd_apps))
    app.add_handler(CommandHandler("setup", cmd_setup))

    log.info("DIY-VPN bot starting (controlling host=%s)", server_api.host())
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
