"""Operations on /data/users.json + /data/credentials.env, executed via SSH.

Source-of-truth files on the VPN box:
  /data/users.json       — list of user dicts (name, uuid, hy2_password, …)
  /data/credentials.env  — server-wide secrets (Reality keys, SNI, etc)

After every users.json mutation we run `sudo /usr/local/bin/diyvpn-render`,
which atomically rewrites /etc/hysteria/config.yaml + /usr/local/etc/xray/config.json
and restarts the relevant service ONLY if the rendered content actually changed.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import shlex
import time
import uuid as uuid_mod
from typing import Any

from . import server_api


# ─── Constants ────────────────────────────────────────────────────────────────

VALID_PRIORITIES = ("high", "normal", "low")
NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


# ─── Reads ────────────────────────────────────────────────────────────────────


async def read_credentials() -> dict[str, str]:
    raw = await server_api.sudo_exec("cat /data/credentials.env")
    out: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out


async def read_users() -> list[dict[str, Any]]:
    raw = await server_api.sudo_exec("cat /data/users.json")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


# ─── Writes ───────────────────────────────────────────────────────────────────


async def write_users(users: list[dict[str, Any]]) -> None:
    """Atomically replace /data/users.json with the given list, then re-render configs."""
    payload = json.dumps(users, indent=2)
    b64 = base64.b64encode(payload.encode()).decode()
    cmd = (
        f"echo {shlex.quote(b64)} | base64 -d | "
        f"install -m 640 -g hysteria /dev/stdin /data/users.json"
    )
    await server_api.sudo_exec(cmd)
    await apply_changes()


async def apply_changes() -> None:
    """Run diyvpn-render — regenerates hy2 + xray configs + restarts services if needed."""
    await server_api.sudo_exec("/usr/local/bin/diyvpn-render", timeout=30.0)


# ─── User mutations ───────────────────────────────────────────────────────────


def _validate_name(name: str) -> None:
    if not NAME_RE.match(name):
        raise ValueError("Name must be 1–32 chars: letters, digits, _ or -.")


def _gen_hy2_password() -> str:
    """28-char URL-safe random — matches what setup.sh seeds with."""
    return secrets.token_urlsafe(21)[:28]


async def add_user(
    name: str,
    *,
    priority: str = "normal",
    expires_at: int | None = None,
) -> dict[str, Any]:
    """Add a new device. Generates a fresh UUID + hy2_password.

    Args:
        name: 1-32 chars, [a-zA-Z0-9_-]
        priority: "high" | "normal" | "low" — maps to xray policy level
        expires_at: optional Unix timestamp; user is rejected after this

    Returns the new user dict.
    """
    _validate_name(name)
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"priority must be one of {VALID_PRIORITIES}")

    users = await read_users()
    if any(u.get("name") == name for u in users):
        raise ValueError(f"A user named '{name}' already exists.")

    new_user = {
        "name": name,
        "uuid": str(uuid_mod.uuid4()),
        "hy2_password": _gen_hy2_password(),
        "email": f"{name}@diyvpn",
        "flow": "xtls-rprx-vision",
        "created_at": int(time.time()),
        "expires_at": expires_at,
        "priority": priority,
    }
    users.append(new_user)
    await write_users(users)
    return new_user


async def remove_user(name: str) -> bool:
    users = await read_users()
    new_users = [u for u in users if u.get("name") != name]
    if len(new_users) == len(users):
        return False
    if not new_users:
        raise ValueError("Refusing to remove the last user (you'd lock yourself out).")
    await write_users(new_users)
    return True


async def set_priority(name: str, priority: str) -> dict[str, Any]:
    """Change a user's priority tier. Maps to xray policy level (stats granularity)."""
    if priority not in VALID_PRIORITIES:
        raise ValueError(f"priority must be one of {VALID_PRIORITIES}")
    users = await read_users()
    for u in users:
        if u.get("name") == name:
            u["priority"] = priority
            await write_users(users)
            return u
    raise ValueError(f"No user named '{name}'.")


async def set_expiry(name: str, expires_at: int | None) -> dict[str, Any]:
    """Set or clear a user's expiry. Pass None to make permanent."""
    users = await read_users()
    for u in users:
        if u.get("name") == name:
            u["expires_at"] = expires_at
            await write_users(users)
            return u
    raise ValueError(f"No user named '{name}'.")


async def temp_user(
    name: str,
    hours: float,
    *,
    priority: str = "normal",
) -> dict[str, Any]:
    """Convenience: add_user with expires_at = now + hours."""
    if hours <= 0:
        raise ValueError("hours must be > 0")
    expires_at = int(time.time() + hours * 3600)
    return await add_user(name, priority=priority, expires_at=expires_at)


async def rotate_user(name: str) -> dict[str, Any]:
    """Regenerate UUID + hy2_password for one user. Kicks that device only.

    Useful when a device share-link has leaked — rotate just that user
    instead of nuking the whole server.
    """
    users = await read_users()
    for u in users:
        if u.get("name") == name:
            u["uuid"] = str(uuid_mod.uuid4())
            u["hy2_password"] = _gen_hy2_password()
            await write_users(users)
            return u
    raise ValueError(f"No user named '{name}'.")


async def rotate_all_credentials() -> None:
    """Server-wide nuke: regenerate Reality keys AND every user's UUID + hy2_password.

    Every existing share-link will stop working. Use only when the box
    itself is suspected compromised.
    """
    # Generate fresh Reality keypair on the box (xray's own x25519 helper).
    raw = await server_api.sudo_exec("/usr/local/bin/xray x25519")
    priv = pub = ""
    for line in raw.splitlines():
        if line.lower().startswith("private"):
            priv = line.split(":", 1)[1].strip()
        if line.lower().startswith("public"):
            pub = line.split(":", 1)[1].strip()
    if not priv or not pub:
        raise RuntimeError(f"xray x25519 output unexpected: {raw!r}")

    new_short_id = secrets.token_hex(8)
    new_stats_secret = secrets.token_hex(16)

    # Rewrite credentials.env atomically.
    creds_env = (
        f"HY2_STATS_SECRET={new_stats_secret}\n"
        f"REALITY_PRIVATE_KEY={priv}\n"
        f"REALITY_PUBLIC_KEY={pub}\n"
        f"REALITY_SNI=www.microsoft.com\n"
        f"REALITY_SHORT_ID={new_short_id}\n"
    )
    b64 = base64.b64encode(creds_env.encode()).decode()
    await server_api.sudo_exec(
        f"echo {shlex.quote(b64)} | base64 -d | "
        f"install -m 640 -g hysteria /dev/stdin /data/credentials.env"
    )

    # Re-roll every user.
    users = await read_users()
    for u in users:
        u["uuid"] = str(uuid_mod.uuid4())
        u["hy2_password"] = _gen_hy2_password()
    await write_users(users)


# ─── Stats via xray API ──────────────────────────────────────────────────────


async def query_stats() -> dict[str, Any]:
    """Returns {'users': {email: {uplink, downlink}}, 'inbound': {...}}."""
    raw = await server_api.ssh_exec(
        "/usr/local/bin/xray api statsquery --server=127.0.0.1:10085 --reset=false 2>&1 || true"
    )
    return _parse_stats(raw)


async def query_online() -> dict[str, int]:
    """Returns {email: online_session_count}."""
    raw = await server_api.ssh_exec(
        "/usr/local/bin/xray api statsonline --server=127.0.0.1:10085 2>&1 || true"
    )
    out: dict[str, int] = {}
    for line in raw.splitlines():
        m = re.match(r"user>>>([^>]+)>>>online:\s*(\d+)", line.strip())
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def _parse_stats(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    users: dict[str, dict[str, int]] = {}
    inbound: dict[str, dict[str, int]] = {}
    if not raw:
        return {"users": users, "inbound": inbound}

    # JSON form (some xray builds).
    try:
        data = json.loads(raw)
        for entry in data.get("stat", []):
            _bucket(entry.get("name", ""), int(entry.get("value", 0) or 0), users, inbound)
        return {"users": users, "inbound": inbound}
    except json.JSONDecodeError:
        pass

    # Protobuf text form.
    pb_pairs = re.findall(
        r'name:\s*"([^"]+)"[^}>]*?value:\s*(-?\d+)',
        raw,
        flags=re.DOTALL,
    )
    if pb_pairs:
        for name, value in pb_pairs:
            _bucket(name, int(value), users, inbound)
        return {"users": users, "inbound": inbound}

    # Last resort: "name: value" lines.
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


# ─── Format helpers ───────────────────────────────────────────────────────────


def fmt_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(f) < 1024:
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024.0
    return f"{f:.1f} PB"


def fmt_expiry(ts: int | None) -> str:
    """Return a human-readable expiry. None -> 'never'."""
    if ts is None:
        return "never"
    now = int(time.time())
    if ts <= now:
        return "EXPIRED"
    seconds = ts - now
    if seconds < 3600:
        return f"in {seconds // 60}m"
    if seconds < 86400:
        return f"in {seconds // 3600}h"
    return f"in {seconds // 86400}d"
