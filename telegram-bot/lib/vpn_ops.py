"""Higher-level operations on the VPN container, executed via flyctl ssh.

These wrappers build small shell snippets, run them in the VPN container,
and parse the result. They avoid pulling in any extra in-container API
surface — everything is done via /usr/local/bin/xray + jq + the files on
/data.
"""

from __future__ import annotations

import json
import re
import shlex
import uuid as uuid_mod
from typing import Any

from . import fly_api


# ─── Credentials & users ──────────────────────────────────────────────────────


async def read_credentials() -> dict[str, str]:
    raw = await fly_api.ssh_exec("cat /data/credentials.env")
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


async def read_users() -> list[dict[str, Any]]:
    raw = await fly_api.ssh_exec("cat /data/users.json")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return []


async def write_users(users: list[dict[str, Any]]) -> None:
    payload = json.dumps(users, indent=2)
    # Use base64 to ferry arbitrary JSON safely through `sh -c`.
    import base64
    b64 = base64.b64encode(payload.encode()).decode()
    cmd = f"echo {shlex.quote(b64)} | base64 -d > /data/users.json && chmod 600 /data/users.json"
    await fly_api.ssh_exec(cmd)


async def add_user(name: str) -> dict[str, str]:
    """Adds a new VLESS client (= a new device). Triggers a config rebuild + xray reload."""
    if not re.match(r"^[a-zA-Z0-9_-]{1,32}$", name):
        raise ValueError("Name must be 1–32 chars, [a-zA-Z0-9_-] only.")

    users = await read_users()
    if any(u.get("name") == name for u in users):
        raise ValueError(f"A user named '{name}' already exists.")

    new_uuid = str(uuid_mod.uuid4())
    users.append(
        {
            "name": name,
            "uuid": new_uuid,
            "flow": "xtls-rprx-vision",
            "email": f"{name}@diyvpn",
        }
    )
    await write_users(users)
    await reload_xray()
    return {"name": name, "uuid": new_uuid}


async def remove_user(name: str) -> bool:
    users = await read_users()
    new_users = [u for u in users if u.get("name") != name]
    if len(new_users) == len(users):
        return False
    if not new_users:
        raise ValueError("Refusing to remove the last user (you'd lock yourself out).")
    await write_users(new_users)
    await reload_xray()
    return True


async def reload_xray() -> None:
    """Re-render xray config from users.json + restart xray.

    We just re-run the relevant chunk of entrypoint.sh's render step and
    then nudge xray to reload by sending it SIGTERM (the entrypoint will
    notice and the machine will restart). Simpler than wiring xray's
    HandlerService dynamic add — and we already trust the entrypoint render.
    """
    # Easiest reliable path: restart the machine. Takes ~5–10 s.
    machine = await fly_api.get_primary_machine()
    if not machine:
        raise RuntimeError("No machine to restart")
    await fly_api.restart_machine(machine["id"])


# ─── Stats via xray API (queryStats) ─────────────────────────────────────────


async def query_stats() -> dict[str, Any]:
    """Returns dict: { 'users': {email: {uplink, downlink, online}}, 'inbound': {...} }.

    Calls `xray api statsquery --server 127.0.0.1:10085` inside the container.
    """
    raw = await fly_api.ssh_exec(
        "/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 --reset=false 2>&1 || true"
    )
    return _parse_stats(raw)


async def query_online() -> dict[str, int]:
    """Returns {email: online_session_count}."""
    # NOTE: xray-core's CLI registers this as `statsonline` (no underscore).
    # The previous `stats_online` silently printed help and the regex below
    # matched nothing — /devices always reported "online: 0".
    raw = await fly_api.ssh_exec(
        "/usr/local/bin/xray api statsonline --server=127.0.0.1:10085 2>&1 || true"
    )
    out: dict[str, int] = {}
    # Output is one user per line: "user>>>email>>>online: N"
    for line in raw.splitlines():
        m = re.match(r"user>>>([^>]+)>>>online:\s*(\d+)", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def _parse_stats(raw: str) -> dict[str, Any]:
    """Parse `xray api statsquery` output.

    Xray's statsquery emits **protobuf text format** by default, like:

        stat: <
          name: "user>>>foo@diyvpn>>>traffic>>>uplink"
          value: 1234
        >

    Some builds / flags produce JSON. We handle both, then fall back to a
    line-based `name: value` form.
    """
    raw = raw.strip()
    users: dict[str, dict[str, int]] = {}
    inbound: dict[str, dict[str, int]] = {}
    if not raw:
        return {"users": users, "inbound": inbound}

    # 1) Try JSON first (some xray builds emit JSON when asked).
    try:
        data = json.loads(raw)
        for entry in data.get("stat", []):
            name = entry.get("name", "")
            value = int(entry.get("value", 0) or 0)
            _bucket(name, value, users, inbound)
        return {"users": users, "inbound": inbound}
    except json.JSONDecodeError:
        pass

    # 2) Protobuf text format:  stat: < name: "..."  value: 1234 >
    #    re.DOTALL so the regex can cross newlines within a single stat block.
    pb_pairs = re.findall(
        r'name:\s*"([^"]+)"[^}>]*?value:\s*(-?\d+)',
        raw,
        flags=re.DOTALL,
    )
    if pb_pairs:
        for name, value in pb_pairs:
            _bucket(name, int(value), users, inbound)
        return {"users": users, "inbound": inbound}

    # 3) Last resort: "user>>>foo@diyvpn>>>traffic>>>uplink: 1234"
    for line in raw.splitlines():
        m = re.match(r"(\S+):\s*(\d+)", line.strip())
        if m:
            _bucket(m.group(1), int(m.group(2)), users, inbound)
    return {"users": users, "inbound": inbound}


def _bucket(name: str, value: int, users: dict, inbound: dict) -> None:
    parts = name.split(">>>")
    if len(parts) >= 4 and parts[0] == "user" and parts[2] == "traffic":
        u = users.setdefault(parts[1], {"uplink": 0, "downlink": 0})
        u[parts[3]] = value
    elif len(parts) >= 4 and parts[0] == "inbound" and parts[2] == "traffic":
        i = inbound.setdefault(parts[1], {"uplink": 0, "downlink": 0})
        i[parts[3]] = value


# ─── Rotate credentials (= "kick everyone, rotate keys") ──────────────────────


async def rotate_credentials() -> None:
    """Wipes credentials.env + users.json + TLS cert, restarts machine.

    Next boot of the VPN container regenerates all of them. After this,
    your existing client share-links no longer work — call /links to get
    the new ones.
    """
    await fly_api.ssh_exec(
        "rm -f /data/credentials.env /data/users.json /data/share-links.txt /data/tls/server.crt /data/tls/server.key"
    )
    machine = await fly_api.get_primary_machine()
    if machine:
        await fly_api.restart_machine(machine["id"])


# ─── Format helpers ───────────────────────────────────────────────────────────


def fmt_bytes(n: int) -> str:
    """Pretty-print byte counts (1234 -> '1.2 KB', 1234567 -> '1.2 MB')."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} PB"
