"""Optional on-demand startup of the user's existing local proxy application."""

from __future__ import annotations

import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.parse import urlparse

from agent.codex_client import CodexInfrastructureError


_started_processes: list[subprocess.Popen] = []


def ensure_local_proxy() -> str:
    """Reuse a running proxy; launch only an explicitly configured executable."""
    proxy = os.environ.get("PLC_CODEX_PROXY", "").strip()
    if not proxy:
        return "Codex uses the configured direct/network proxy connection."
    parsed = urlparse(proxy)
    try:
        port = parsed.port
    except ValueError as exc:
        raise CodexInfrastructureError("PLC_CODEX_PROXY has an invalid port") from exc
    if not parsed.hostname or not port:
        raise CodexInfrastructureError("PLC_CODEX_PROXY must include a host and port")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        return "Codex uses the configured remote proxy."

    def reachable() -> bool:
        try:
            with socket.create_connection((parsed.hostname, port), timeout=1):
                return True
        except OSError:
            return False

    if reachable():
        return "Codex local proxy is ready."
    configured = os.environ.get("PLC_CODEX_PROXY_EXECUTABLE", "").strip()
    if not configured:
        raise CodexInfrastructureError(
            "Codex local proxy is unavailable. Start your proxy application, or set "
            "PLC_CODEX_PROXY_EXECUTABLE in .env.local for automatic startup."
        )
    executable = Path(configured)
    if not executable.is_absolute() or not executable.is_file():
        raise CodexInfrastructureError("PLC_CODEX_PROXY_EXECUTABLE must name an existing absolute executable path")
    options: dict = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if os.name == "nt":
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options["startupinfo"] = startup
    else:
        options["start_new_session"] = True
    try:
        _started_processes[:] = [process for process in _started_processes if process.poll() is None]
        _started_processes.append(subprocess.Popen([str(executable)], **options))
    except OSError as exc:
        raise CodexInfrastructureError("Could not start the configured Codex proxy application") from exc
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if reachable():
            return "Codex local proxy started automatically."
        time.sleep(0.25)
    raise CodexInfrastructureError("The proxy application started but its configured port is still unavailable")
