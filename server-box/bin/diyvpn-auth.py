#!/usr/bin/env python3
"""Hysteria2 HTTP auth backend.

Hysteria2 POSTs {"addr":"1.2.3.4:5678","auth":"<password>","tx":0} on each
client connect. We read /data/users.json (cheap — small JSON), find a user
whose hy2_password matches and isn't expired, and reply {"ok":true,"id":<name>}.

Listens on 127.0.0.1:8080 (firewalled to localhost — only Hysteria2 talks to it).

Reads users.json on every request so /adduser, /kick, /rotate don't require
a service restart — just `sudo /usr/local/bin/diyvpn-render` to update the
xray config; the auth backend picks up the new users.json on the next connect.
"""
from __future__ import annotations

import json
import logging
import os
import time

from aiohttp import web

USERS_PATH = "/data/users.json"

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] diyvpn-auth: %(message)s",
    level=os.environ.get("DIYVPN_AUTH_LOGLEVEL", "INFO"),
)
log = logging.getLogger("diyvpn-auth")


def load_users() -> list[dict]:
    if not os.path.exists(USERS_PATH):
        return []
    try:
        with open(USERS_PATH) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        log.warning("users.json read failed: %s", e)
        return []
    return data if isinstance(data, list) else []


async def handle_auth(request: web.Request) -> web.Response:
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False}, status=400)

    addr = body.get("addr", "")
    auth_token = body.get("auth", "")

    users = load_users()
    now = int(time.time())
    for u in users:
        if u.get("hy2_password") != auth_token:
            continue
        exp = u.get("expires_at")
        if exp and now >= int(exp):
            log.info("rejected expired user=%s addr=%s", u.get("name"), addr)
            return web.json_response({"ok": False})
        log.info("accepted user=%s addr=%s", u.get("name"), addr)
        return web.json_response({"ok": True, "id": u.get("name", "anon")})

    log.info("rejected unknown auth from %s", addr)
    return web.json_response({"ok": False})


async def handle_health(_request: web.Request) -> web.Response:
    return web.Response(text="ok\n")


def main() -> None:
    app = web.Application()
    app.router.add_post("/auth", handle_auth)
    app.router.add_get("/health", handle_health)
    log.info("diyvpn-auth listening on 127.0.0.1:8080")
    web.run_app(app, host="127.0.0.1", port=8080, print=None, access_log=None)


if __name__ == "__main__":
    main()
