"""SSH transport to the Oracle VPN box. Replaces fly_api.py.

Shells out to the system `ssh` binary (no extra Python deps beyond what we
already ship). Each ssh_exec runs a one-shot command and returns stdout.

Required env vars:
  VPN_HOST            — public IPv4 of the VPN box (e.g. "40.233.120.150")

Optional:
  VPN_SSH_USER        — default "ubuntu"
  VPN_SSH_KEY_PATH    — default "~/.ssh/diyvpn-oracle"
  VPN_SSH_PORT        — default "22"
  VPN_SSH_KNOWN_HOSTS — default "~/.ssh/known_hosts"
"""

from __future__ import annotations

import asyncio
import os
import shlex
from typing import Final

HOST: Final[str] = os.environ["VPN_HOST"]
USER: Final[str] = os.environ.get("VPN_SSH_USER", "ubuntu")
KEY: Final[str] = os.path.expanduser(
    os.environ.get("VPN_SSH_KEY_PATH", "~/.ssh/diyvpn-oracle")
)
PORT: Final[str] = os.environ.get("VPN_SSH_PORT", "22")
KNOWN_HOSTS: Final[str] = os.path.expanduser(
    os.environ.get("VPN_SSH_KNOWN_HOSTS", "~/.ssh/known_hosts")
)


def _ssh_argv(cmd: str) -> list[str]:
    """Build an argv that runs `cmd` on the VPN box via ssh.

    StrictHostKeyChecking=accept-new means the first connect auto-trusts
    the host key (and pins it). After that, any key change blocks the
    connection — which is what we want for a long-lived bot.
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
        f"{USER}@{HOST}",
        # Outer `bash -lc` wraps the inner command so multi-line / piped
        # commands work without escape hell.
        "bash", "-lc", shlex.quote(cmd),
    ]


async def ssh_exec(cmd: str, timeout: float = 30.0) -> str:
    """Run `cmd` on the VPN box, return stdout. Raises on non-zero exit."""
    argv = _ssh_argv(cmd)
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
        raise RuntimeError(f"ssh timed out after {timeout}s: {cmd[:80]}")

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip() or stdout.decode(errors="replace").strip()
        raise RuntimeError(f"ssh failed (exit {proc.returncode}): {err}")
    return stdout.decode(errors="replace")


async def sudo_exec(cmd: str, timeout: float = 30.0) -> str:
    """Run `cmd` with passwordless sudo on the VPN box.

    The `ubuntu` user has NOPASSWD sudo on Oracle Cloud's default cloud-init,
    so this just prefixes `sudo`. Use this for anything that touches /data
    or restarts services.
    """
    return await ssh_exec(f"sudo {cmd}", timeout=timeout)


def host() -> str:
    """Return the VPN box's public IP — used to build share links."""
    return HOST


async def fetch_logs(unit: str, lines: int = 50) -> str:
    """Last N journalctl lines for a systemd unit (hysteria-server, xray, diyvpn-auth)."""
    safe_unit = shlex.quote(unit)
    return await sudo_exec(f"journalctl -u {safe_unit} -n {lines} --no-pager", timeout=20.0)
