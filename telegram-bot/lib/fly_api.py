"""Thin async client for Fly.io's Machines REST API + flyctl shell-outs.

Auth: FLY_API_TOKEN env var (set via `flyctl tokens create deploy`).
Target app: DIYVPN_APP_NAME env var (e.g. "diyvpn-sgad").

We use the REST API for fast/idempotent ops (state, start, stop, IPs)
and shell out to `flyctl` only for things the REST API doesn't expose
nicely (logs, ssh exec).
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from typing import Any

import httpx

API_ROOT = "https://api.machines.dev/v1"
GRAPHQL = "https://api.fly.io/graphql"
APP = os.environ["DIYVPN_APP_NAME"]
TOKEN = os.environ["FLY_API_TOKEN"]

_HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json",
}


async def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=_HEADERS, timeout=30.0)


# ─── Machines ─────────────────────────────────────────────────────────────────


async def list_machines() -> list[dict[str, Any]]:
    async with await _client() as c:
        r = await c.get(f"{API_ROOT}/apps/{APP}/machines")
        r.raise_for_status()
        return r.json()


async def get_primary_machine() -> dict[str, Any] | None:
    machines = await list_machines()
    if not machines:
        return None
    # Prefer "started" machines, then any non-destroyed machine.
    for m in machines:
        if m.get("state") == "started":
            return m
    for m in machines:
        if m.get("state") != "destroyed":
            return m
    return None


async def start_machine(machine_id: str) -> dict[str, Any]:
    async with await _client() as c:
        r = await c.post(f"{API_ROOT}/apps/{APP}/machines/{machine_id}/start")
        r.raise_for_status()
        return r.json()


async def stop_machine(machine_id: str) -> dict[str, Any]:
    async with await _client() as c:
        r = await c.post(f"{API_ROOT}/apps/{APP}/machines/{machine_id}/stop")
        r.raise_for_status()
        return r.json()


async def restart_machine(machine_id: str) -> dict[str, Any]:
    async with await _client() as c:
        r = await c.post(f"{API_ROOT}/apps/{APP}/machines/{machine_id}/restart")
        r.raise_for_status()
        return r.json()


# ─── IPs (GraphQL — no REST equivalent) ──────────────────────────────────────


async def list_ips() -> list[dict[str, Any]]:
    """Returns list of {address, type, region} for the app's allocated IPs."""
    query = """
    query($name: String!) {
      app(name: $name) {
        ipAddresses {
          nodes { address type region }
        }
      }
    }
    """
    async with await _client() as c:
        r = await c.post(GRAPHQL, json={"query": query, "variables": {"name": APP}})
        r.raise_for_status()
        data = r.json()
        nodes = data.get("data", {}).get("app", {}).get("ipAddresses", {}).get("nodes", [])
        return nodes or []


async def allocate_ipv4(dedicated: bool = True) -> str:
    """Allocates a dedicated IPv4. Returns the address. Raises on failure."""
    mutation = """
    mutation($appId: ID!, $type: IPAddressType!, $region: String) {
      allocateIpAddress(input: {appId: $appId, type: $type, region: $region}) {
        ipAddress { address type region }
      }
    }
    """
    variables = {"appId": APP, "type": "v4" if dedicated else "shared_v4"}
    async with await _client() as c:
        r = await c.post(GRAPHQL, json={"query": mutation, "variables": variables})
        r.raise_for_status()
        data = r.json()
        if data.get("errors"):
            raise RuntimeError(data["errors"][0].get("message", "unknown"))
        ip = data["data"]["allocateIpAddress"]["ipAddress"]["address"]
        return ip


async def release_ip(address: str) -> None:
    mutation = """
    mutation($appId: ID!, $ip: String!) {
      releaseIpAddress(input: {appId: $appId, ip: $ip}) { app { name } }
    }
    """
    async with await _client() as c:
        r = await c.post(
            GRAPHQL,
            json={"query": mutation, "variables": {"appId": APP, "ip": address}},
        )
        r.raise_for_status()
        if r.json().get("errors"):
            raise RuntimeError(r.json()["errors"][0].get("message", "unknown"))


# ─── flyctl shell-outs (logs, ssh exec) ──────────────────────────────────────


async def flyctl(*args: str, timeout: float = 60.0) -> tuple[int, str, str]:
    """Run flyctl with the bot's token, capture stdout/stderr."""
    env = {**os.environ, "FLY_API_TOKEN": TOKEN}
    proc = await asyncio.create_subprocess_exec(
        "flyctl",
        *args,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout.decode(errors="replace"), stderr.decode(errors="replace")


async def ssh_exec(cmd: str, timeout: float = 60.0) -> str:
    """Run a shell command on the VPN machine via `flyctl ssh console -C`.

    Passes `--pty=false` to prevent flyctl from allocating a TTY (which hangs
    indefinitely under asyncio.subprocess). Retries without the flag if the
    local flyctl is old enough to not recognise it.
    """
    wrapped = f"sh -c {shlex.quote(cmd)}"
    attempts = [
        ("ssh", "console", "--app", APP, "--pty=false", "-C", wrapped),
        ("ssh", "console", "--app", APP,                "-C", wrapped),
    ]
    code, out, err = 0, "", ""
    for args in attempts:
        try:
            code, out, err = await flyctl(*args, timeout=timeout)
        except asyncio.TimeoutError:
            # Most likely a pty hang on older flyctl — try the next form.
            code, out, err = 124, "", "ssh_exec: flyctl hung (possible pty issue)"
            continue
        # If flyctl rejected --pty=false as unknown, fall through to the
        # no-flag form. Otherwise we're done.
        if code == 0 or "unknown flag" not in err:
            break
    if code != 0:
        raise RuntimeError(f"ssh failed (exit {code}): {err.strip() or out.strip()}")
    return out


async def fetch_logs(lines: int = 50) -> str:
    code, out, err = await flyctl("logs", "--app", APP, "--no-tail")
    if code != 0:
        raise RuntimeError(err.strip() or "flyctl logs failed")
    tail = out.splitlines()[-lines:]
    return "\n".join(tail)
