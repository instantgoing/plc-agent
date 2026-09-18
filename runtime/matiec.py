"""Process adapter for the real MatIEC ``iec2c`` compiler.

The public ``plc_tools`` layer calls this module so compiler command-line and
container/WSL path details do not leak into the future Agent layer.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatiecRunResult:
    returncode: int
    stdout: str
    stderr: str


class MatiecConfigurationError(RuntimeError):
    """Raised when no configured MatIEC execution backend is usable."""


def _raise_for_backend_failure(
    backend: str, returncode: int, stdout: str, stderr: str
) -> None:
    if returncode == 0:
        return
    combined = "\n".join(part for part in (stderr, stdout) if part).strip()
    lowered = combined.lower()
    docker_failure = backend == "docker" and (
        returncode in {125, 126, 127}
        or "docker api" in lowered
        or "docker daemon" in lowered
        or "error during connect" in lowered
        or "unable to find image" in lowered
    )
    wsl_failure = backend == "wsl" and (
        returncode in {126, 127}
        or "wsl/service" in lowered
        or "createprocess" in lowered
        or "no such file or directory" in lowered
        or "command not found" in lowered
    )
    if docker_failure or wsl_failure:
        detail = combined[:2000] or f"backend exited with status {returncode}"
        raise MatiecConfigurationError(f"{backend} MatIEC backend failed: {detail}")


def _selected_backend() -> str:
    configured = os.environ.get("PLC_MATIEC_BACKEND", "").strip().lower()
    if configured:
        if configured not in {"local", "docker", "wsl"}:
            raise MatiecConfigurationError(
                "PLC_MATIEC_BACKEND must be one of: local, docker, wsl"
            )
        return configured
    if os.environ.get("PLC_MATIEC_DOCKER_IMAGE"):
        return "docker"
    if os.environ.get("PLC_MATIEC_WSL_DISTRO"):
        return "wsl"
    return "local"


def _require_executable(executable: str, purpose: str) -> None:
    if shutil.which(executable) is None and not Path(executable).is_file():
        raise MatiecConfigurationError(f"{purpose} executable not found: {executable}")


def _windows_to_wsl_path(path: Path) -> str:
    text = str(path.resolve())
    match = re.match(r"^(?P<drive>[A-Za-z]):[\\/](?P<tail>.*)$", text)
    if match is None:
        raise MatiecConfigurationError(
            f"WSL backend requires a drive-letter path, got: {text}"
        )
    tail = match.group("tail").replace("\\", "/")
    return f"/mnt/{match.group('drive').lower()}/{tail}"


def _local_command(source: Path) -> list[str]:
    compiler = os.environ.get("PLC_MATIEC_BIN", "iec2c")
    _require_executable(compiler, "MatIEC")
    command = [compiler, "-f", "-l", "-p"]
    library = os.environ.get("PLC_MATIEC_LIB")
    if library:
        command.extend(["-I", library])
    command.append(str(source))
    return command


def _docker_command(source: Path, output_dir: Path) -> list[str]:
    docker = os.environ.get("PLC_DOCKER_BIN", "docker")
    _require_executable(docker, "Docker")
    image = os.environ.get("PLC_MATIEC_DOCKER_IMAGE")
    if not image:
        raise MatiecConfigurationError(
            "PLC_MATIEC_DOCKER_IMAGE is required for the Docker backend"
        )
    library = os.environ.get("PLC_MATIEC_DOCKER_LIB", "/usr/local/share/matiec/lib")
    return [
        docker,
        "run",
        "--rm",
        "--platform=linux/amd64",
        "-v",
        f"{source.parent}:/source:ro",
        "-v",
        f"{output_dir}:/output",
        "-w",
        "/output",
        image,
        "iec2c",
        "-f",
        "-l",
        "-p",
        "-I",
        library,
        f"/source/{source.name}",
    ]


def _wsl_command(source: Path, output_dir: Path) -> list[str]:
    wsl = os.environ.get("PLC_WSL_BIN", "wsl.exe")
    _require_executable(wsl, "WSL")
    distro = os.environ.get("PLC_MATIEC_WSL_DISTRO")
    if not distro:
        raise MatiecConfigurationError(
            "PLC_MATIEC_WSL_DISTRO is required for the WSL backend"
        )
    compiler = os.environ.get("PLC_MATIEC_WSL_BIN", "iec2c")
    library = os.environ.get("PLC_MATIEC_WSL_LIB", "/usr/local/share/matiec/lib")
    return [
        wsl,
        "-d",
        distro,
        "--",
        compiler,
        "-f",
        "-l",
        "-p",
        "-T",
        _windows_to_wsl_path(output_dir),
        "-I",
        library,
        _windows_to_wsl_path(source),
    ]


def run_iec2c(source: Path, output_dir: Path, *, timeout: float) -> MatiecRunResult:
    """Run ``iec2c`` once, using the explicitly configured runtime backend."""

    backend = _selected_backend()
    if backend == "docker":
        command = _docker_command(source, output_dir)
    elif backend == "wsl":
        command = _wsl_command(source, output_dir)
    else:
        command = _local_command(source)

    process_environment = os.environ.copy()
    process_cwd = output_dir
    if backend == "wsl":
        # wsl.exe otherwise may prepend localized UTF-16 host warnings to the
        # UTF-8 compiler stream, producing mixed-encoding diagnostics.
        process_environment["WSL_UTF8"] = "1"
        # Never launch wsl.exe *from* a disposable Windows directory. WSL may
        # retain the launcher's cwd briefly after the compiler exits, which
        # makes TemporaryDirectory cleanup fail with WinError 32.
        process_cwd = source.parent

    try:
        completed = subprocess.run(
            command,
            cwd=process_cwd,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=process_environment,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise MatiecConfigurationError(f"failed to start MatIEC backend: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise MatiecConfigurationError(f"MatIEC timed out after {timeout:g}s") from exc

    _raise_for_backend_failure(
        backend, completed.returncode, completed.stdout, completed.stderr
    )
    return MatiecRunResult(completed.returncode, completed.stdout, completed.stderr)
