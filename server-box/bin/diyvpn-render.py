#!/usr/bin/env python3
"""Regenerate Hysteria2 + Xray configs from /data/users.json.

Source of truth: /data/users.json, /data/credentials.env.
Renders /etc/hysteria/config.yaml and /usr/local/etc/xray/config.json.
Restarts services only if the rendered config actually changed.

Run as root after every users.json mutation. Idempotent.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile

USERS_PATH = "/data/users.json"
CREDS_PATH = "/data/credentials.env"
HY2_CONFIG = "/etc/hysteria/config.yaml"
XRAY_CONFIG = "/usr/local/etc/xray/config.json"


def load_creds() -> dict[str, str]:
    out: dict[str, str] = {}
    if not os.path.exists(CREDS_PATH):
        sys.exit(f"missing {CREDS_PATH} — run server-box/setup.sh first")
    with open(CREDS_PATH) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def load_users() -> list[dict]:
    if not os.path.exists(USERS_PATH):
        return []
    with open(USERS_PATH) as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"users.json is malformed: {e}")
    if not isinstance(data, list):
        sys.exit("users.json must be a JSON array")
    return data


def render_hy2(creds: dict, _users: list[dict]) -> str:
    """Hysteria2 config delegates auth to the HTTP backend, so users don't appear here.

    The backend reads /data/users.json on each connect — adding/removing users
    is hot, no Hysteria2 restart needed (config doesn't change with users).
    """
    secret = creds.get("HY2_STATS_SECRET", "")
    return f"""listen: :443

tls:
  cert: /etc/hysteria/server.crt
  key: /etc/hysteria/server.key

auth:
  type: http
  http:
    url: http://127.0.0.1:8080/auth
    insecure: true

masquerade:
  type: proxy
  proxy:
    url: https://www.bing.com
    rewriteHost: true

quic:
  initStreamReceiveWindow: 8388608
  maxStreamReceiveWindow: 8388608
  initConnReceiveWindow: 20971520
  maxConnReceiveWindow: 20971520

trafficStats:
  listen: 127.0.0.1:25413
  secret: {secret}

ignoreClientBandwidth: true

acl:
  inline:
    - reject(geoip:private)
"""


def render_xray(creds: dict, users: list[dict]) -> str:
    """Xray VLESS-Reality config; per-user UUIDs baked in. Restart on user change."""
    clients = [
        {
            "id": u["uuid"],
            "flow": u.get("flow", "xtls-rprx-vision"),
            "email": u.get("email") or f"{u['name']}@diyvpn",
            "level": _level_for_priority(u.get("priority", "normal")),
        }
        for u in users
    ]
    config = {
        "log": {"loglevel": "warning"},
        "stats": {},
        "policy": {
            "levels": {
                "0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True},
                "1": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True},
                "2": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True},
            },
            "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
        },
        "api": {"tag": "api", "services": ["StatsService", "HandlerService"]},
        "inbounds": [
            {
                "listen": "127.0.0.1",
                "port": 10085,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1"},
                "tag": "api-in",
            },
            {
                "listen": "0.0.0.0",
                "port": 443,
                "protocol": "vless",
                "tag": "vless-reality",
                "settings": {"clients": clients, "decryption": "none"},
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": f"{creds['REALITY_SNI']}:443",
                        "xver": 0,
                        "serverNames": [creds["REALITY_SNI"]],
                        "privateKey": creds["REALITY_PRIVATE_KEY"],
                        "shortIds": [creds["REALITY_SHORT_ID"]],
                    },
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls", "quic"]},
            },
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"},
            {"protocol": "blackhole", "tag": "block"},
        ],
        "routing": {
            "rules": [
                {"type": "field", "inboundTag": ["api-in"], "outboundTag": "api"},
                {"type": "field", "ip": ["geoip:private"], "outboundTag": "block"},
            ]
        },
    }
    return json.dumps(config, indent=2)


def _level_for_priority(p: str) -> int:
    """Map priority tier -> xray user level. Levels are referenced in policy.levels."""
    return {"high": 2, "normal": 0, "low": 1}.get(p, 0)


def atomic_write(path: str, content: str, owner: str | None) -> bool:
    """Write content atomically. Returns True if file content actually changed."""
    if os.path.exists(path):
        with open(path) as f:
            if f.read() == content:
                return False
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile("w", delete=False, dir=parent)
    tmp.write(content)
    tmp.close()
    os.chmod(tmp.name, 0o644)
    if owner:
        try:
            shutil.chown(tmp.name, owner, owner)
        except (LookupError, PermissionError):
            pass
    os.replace(tmp.name, path)
    return True


def main() -> None:
    creds = load_creds()
    users = load_users()

    hy2_changed = atomic_write(HY2_CONFIG, render_hy2(creds, users), owner="hysteria")
    xray_changed = atomic_write(XRAY_CONFIG, render_xray(creds, users), owner="xray")

    if hy2_changed:
        subprocess.run(["systemctl", "restart", "hysteria-server"], check=True)
    if xray_changed:
        subprocess.run(["systemctl", "restart", "xray"], check=True)

    print(
        f"rendered: users={len(users)} "
        f"hy2_changed={hy2_changed} xray_changed={xray_changed}"
    )


if __name__ == "__main__":
    main()
