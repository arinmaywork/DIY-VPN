"""SSH transport to the Oracle VPN box(es). Multi-box-aware.

The bot can talk to one or more VPN boxes (e.g. toronto + london). Every
SSH call routes to the *active* box, which the operator switches via
`/switch <name>` in Telegram. The choice is persisted in `.bot-state.json`
so it survives bot restarts.

Required env (one of these must be set):
  VPN_BOXES           — csv of name:ip pairs, e.g.
                        "toronto:40.233.120.150,london:1.2.3.4"
  VPN_HOST            — single-box fallback (treated as one box named "default")

Optional:
  VPN_SSH_USER        — default "ubuntu"            (same for every box)
  VPN_SSH_KEY_PATH    — default "~/.ssh/diyvpn-oracle"
  VPN_SSH_PORT        — default "22"
  VPN_SSH_KNOWN_HOSTS — default "~/.ssh/known_hosts"

We assume every box uses the same SSH user/key. Different keys per box
would require per-box overrides (e.g. VPN_KEY_TORONTO=...) — easy to add
later if needed.
"""

from __future__ import annotations

import asyncio
import os
import shlex
from dataclasses import dataclass

from . import state


@dataclass(frozen=True)
class Box:
    name: str
    host: str  # public IPv4

    def label(self) -> str:
        return f"{self.name} ({self.host})"


# ─── Parse box list once at import ────────────────────────────────────────────


def _parse_boxes() -> list[Box]:
    raw = os.environ.get("VPN_BOXES", "").strip()
    if raw:
        boxes: list[Box] = []
        seen: set[str] = set()
        for tok in raw.split(","):
            tok = tok.strip()
            if not tok:
                continue
            if ":" not in tok:
                raise RuntimeError(
                    f"VPN_BOXES entry must be 'name:ip', got {tok!r}"
                )
            name, host = tok.split(":", 1)
            name, host = name.strip(), host.strip()
            if not name or not host:
                raise RuntimeError(f"VPN_BOXES entry has empty name or host: {tok!r}")
            if name in seen:
                raise RuntimeError(f"VPN_BOXES has duplicate box name: {name!r}")
            seen.add(name)
            boxes.append(Box(name=name, host=host))
        if not boxes:
            raise RuntimeError("VPN_BOXES is set but parsed empty")
        return boxes

    legacy = os.environ.get("VPN_HOST", "").strip()
    if legacy:
        return [Box(name="default", host=legacy)]

    raise RuntimeError(
        "Set either VPN_BOXES (preferred, multi-box) or VPN_HOST (single box) in the environment"
    )


BOXES: list[Box] = _parse_boxes()
USER: str = os.environ.get("VPN_SSH_USER", "ubuntu")
KEY: str = os.path.expanduser(
    os.environ.get("VPN_SSH_KEY_PATH", "~/.ssh/diyvpn-oracle")
)
PORT: str = os.environ.get("VPN_SSH_PORT", "22")
KNOWN_HOSTS: str = os.path.expanduser(
    os.environ.get("VPN_SSH_KNOWN_HOSTS", "~/.ssh/known_hosts")
)


# ─── Active-box tracking ──────────────────────────────────────────────────────


def _initial_active_name() -> str:
    saved = state.load().get("active_box")
    names = {b.name for b in BOXES}
    if isinstance(saved, str) and saved in names:
        return saved
    return BOXES[0].name


_active_name: str = _initial_active_name()


def boxes() -> list[Box]:
    """All configured boxes, in declaration order."""
    return list(BOXES)


def active_box() -> Box:
    return next(b for b in BOXES if b.name == _active_name)


def set_active(name: str) -> Box:
    """Change which box subsequent SSH calls target. Persists to disk."""
    global _active_name
    if not any(b.name == name for b in BOXES):
        raise ValueError(
            f"unknown box {name!r}; have {[b.name for b in BOXES]}"
        )
    _active_name = name
    state.update(active_box=name)
    return active_box()


def host() -> str:
    """Public IP of the active box. Used to build share links."""
    return active_box().host


# ─── SSH plumbing ─────────────────────────────────────────────────────────────


def _ssh_argv(cmd: str, target: Box) -> list[str]:
    """Build an argv that runs `cmd` on `target` via ssh.

    StrictHostKeyChecking=accept-new auto-trusts a new host on first connect
    and refuses if the key changes later — what we want for a long-lived bot.
    """
    return [
        "ssh",
        "-i", KEY,
        "-p", PORT,
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "ServerAliveInterval=15",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={KNOWN_HOSTS}",
        f"{USER}@{target.host}",
        # Outer `bash -lc` lets pipelines/heredocs survive SSH escaping.
        "bash", "-lc", shlex.quote(cmd),
    ]


async def ssh_exec(
    cmd: str,
    timeout: float = 30.0,
    *,
    box: Box | None = None,
) -> str:
    """Run `cmd` on `box` (default = active box). Returns stdout, raises on non-zero exit."""
    target = box or active_box()
    argv = _ssh_argv(cmd, target)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise RuntimeError(f"ssh to {target.label()} timed out after {timeout}s: {cmd[:80]}")

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise RuntimeError(f"ssh to {target.label()} failed (exit {proc.returncode}): {err}")
    return stdout.decode(errors="replace")


async def sudo_exec(
    cmd: str,
    timeout: float = 30.0,
    *,
    box: Box | None = None,
) -> str:
    """ssh_exec but prefixed with passwordless sudo. Use for /data writes + restarts."""
    return await ssh_exec(f"sudo {cmd}", timeout=timeout, box=box)


async def fetch_logs(
    unit: str,
    lines: int = 50,
    *,
    box: Box | None = None,
) -> str:
    """Last N journalctl lines for a systemd unit."""
    safe_unit = shlex.quote(unit)
    return await sudo_exec(
        f"journalctl -u {safe_unit} -n {lines} --no-pager",
        timeout=20.0,
        box=box,
    )
