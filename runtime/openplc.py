"""Docker and REST adapter for the MatIEC-compatible OpenPLC Runtime."""

from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from typing import Literal


CompileStage = Literal[
    "iec2c", "xml2st_debug", "xml2st_gluevars", "package"
]

_CONTAINER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_GENERATED_FILES = [
    "Config0.c",
    "Config0.h",
    "Res0.c",
    "POUS.c",
    "POUS.h",
    "LOCATED_VARIABLES.h",
    "VARIABLES.csv",
    "debug.c",
    "glueVars.c",
]


class OpenPLCConfigurationError(RuntimeError):
    """Raised when the real OpenPLC backend is unavailable or unusable."""


@dataclass(frozen=True)
class ContainerCompileResult:
    success: bool
    failed_stage: CompileStage | None
    package_path: str | None
    generated_files: list[str]
    stdout: str
    stderr: str
    variables_csv: str = ""


@dataclass(frozen=True)
class UploadResult:
    success: bool
    failed_stage: Literal["upload", "gcc"] | None
    status: str
    logs: list[str]
    error: str | None


@dataclass(frozen=True)
class RuntimeCommandResult:
    actual_status: str
    message: str


def _docker_bin() -> str:
    executable = os.environ.get("PLC_DOCKER_BIN", "docker")
    if shutil.which(executable) is None and not Path(executable).is_file():
        raise OpenPLCConfigurationError(f"Docker executable not found: {executable}")
    return executable


def _container_name() -> str:
    name = os.environ.get("PLC_OPENPLC_CONTAINER", "plc-agent-openplc-m2")
    if not _CONTAINER_RE.fullmatch(name):
        raise OpenPLCConfigurationError(f"invalid OpenPLC container name: {name}")
    return name


def _run_docker(args: list[str], *, timeout: float) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            [_docker_bin(), *args],
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except OSError as exc:
        raise OpenPLCConfigurationError(f"failed to start Docker: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise OpenPLCConfigurationError(f"Docker command timed out after {timeout:g}s") from exc
    return completed


def _require_running_container(timeout: float) -> str:
    container = _container_name()
    inspected = _run_docker(
        ["inspect", "--format", "{{.State.Running}}", container], timeout=timeout
    )
    if inspected.returncode != 0 or inspected.stdout.strip().lower() != "true":
        detail = (inspected.stderr.strip() or inspected.stdout.strip())[:2000]
        raise OpenPLCConfigurationError(
            f"OpenPLC container is not running: {container}. {detail}".strip()
        )
    return container


def compile_program(source: Path, *, timeout: float) -> ContainerCompileResult:
    """Run MatIEC and xml2st inside the selected real Runtime container."""

    container = _require_running_container(min(timeout, 15.0))
    token = uuid.uuid4().hex
    remote_source = f"/tmp/plc_agent_{token}.st"
    copied = _run_docker(["cp", str(source), f"{container}:{remote_source}"], timeout=timeout)
    if copied.returncode != 0:
        raise OpenPLCConfigurationError(
            f"cannot copy ST source into OpenPLC container: {copied.stderr.strip()[:2000]}"
        )

    try:
        completed = _run_docker(
            [
                "exec",
                container,
                "/workspace/scripts/compile_st.sh",
                remote_source,
            ],
            timeout=timeout,
        )
    finally:
        _run_docker(["exec", container, "rm", "-f", remote_source], timeout=10.0)

    stage_by_code: dict[int, CompileStage] = {
        1: "iec2c",
        2: "xml2st_debug",
        3: "xml2st_gluevars",
        4: "package",
    }
    if completed.returncode != 0:
        return ContainerCompileResult(
            False,
            stage_by_code.get(completed.returncode, "package"),
            None,
            [],
            completed.stdout,
            completed.stderr,
        )
    package_path = next(
        (line.strip() for line in completed.stdout.splitlines() if line.strip().endswith(".zip")),
        None,
    )
    if package_path is None:
        return ContainerCompileResult(
            False,
            "package",
            None,
            [],
            completed.stdout,
            "compile script did not return a package path",
        )
    csv_path = str(PurePosixPath(package_path).parent / "VARIABLES.csv")
    csv_result = _run_docker(["exec", container, "cat", csv_path], timeout=10.0)
    if csv_result.returncode != 0:
        return ContainerCompileResult(
            False,
            "package",
            None,
            [],
            completed.stdout,
            f"cannot read generated VARIABLES.csv: {csv_result.stderr.strip()}",
        )
    return ContainerCompileResult(
        True,
        None,
        package_path,
        list(_GENERATED_FILES),
        completed.stdout,
        completed.stderr,
        csv_result.stdout,
    )


class _RuntimeClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get("PLC_OPENPLC_URL", "https://localhost:8443").rstrip("/")
        self.username = os.environ.get("PLC_OPENPLC_USER", "admin")
        self.password = os.environ.get("PLC_OPENPLC_PASSWORD", "admin123")
        parsed = urllib.parse.urlparse(self.base_url)
        configured_verify = os.environ.get("PLC_OPENPLC_TLS_VERIFY")
        verify = (
            configured_verify.strip().lower() not in {"0", "false", "no"}
            if configured_verify is not None
            else parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        )
        self.context = ssl.create_default_context() if verify else ssl._create_unverified_context()
        self.token: str | None = None

    def _request(
        self,
        method: str,
        endpoint: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        allow_http_error: bool = False,
    ) -> tuple[int, dict]:
        request = urllib.request.Request(
            f"{self.base_url}{endpoint}", data=data, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=timeout) as response:
                body = response.read().decode("utf-8", errors="replace")
                return response.status, json.loads(body or "{}")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if allow_http_error:
                try:
                    return exc.code, json.loads(body or "{}")
                except json.JSONDecodeError:
                    return exc.code, {"error": body}
            raise OpenPLCConfigurationError(
                f"OpenPLC API {endpoint} returned HTTP {exc.code}: {body[:1000]}"
            ) from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise OpenPLCConfigurationError(
                f"cannot reach OpenPLC Runtime at {self.base_url}: {exc}"
            ) from exc
        except json.JSONDecodeError as exc:
            raise OpenPLCConfigurationError(
                f"OpenPLC API {endpoint} returned invalid JSON"
            ) from exc

    def _json_request(
        self, method: str, endpoint: str, payload: dict, *, allow_http_error: bool = False
    ) -> tuple[int, dict]:
        return self._request(
            method,
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            allow_http_error=allow_http_error,
        )

    def authenticate(self) -> str:
        if self.token:
            return self.token
        credentials = {
            "username": self.username,
            "password": self.password,
            "role": "admin",
        }
        self._json_request("POST", "/api/create-user", credentials, allow_http_error=True)
        _, login = self._json_request(
            "POST",
            "/api/login",
            {"username": self.username, "password": self.password},
        )
        token = login.get("access_token") or login.get("token")
        if not isinstance(token, str) or not token:
            raise OpenPLCConfigurationError("OpenPLC authentication returned no token")
        self.token = token
        return token

    def debug_command(self, command: str, *, timeout: float = 5.0) -> str:
        """Send one OpenPLC debug command over Socket.IO polling transport."""

        deadline = time.monotonic() + timeout
        base_query = "EIO=4&transport=polling"

        def polling_request(
            method: str, *, sid: str | None = None, body: str | None = None
        ) -> str:
            query = base_query
            if sid:
                query += f"&sid={urllib.parse.quote(sid)}"
            query += f"&t={int(time.time() * 1000)}"
            request = urllib.request.Request(
                f"{self.base_url}/socket.io/?{query}",
                data=body.encode("utf-8") if body is not None else None,
                method=method,
                headers={"Content-Type": "text/plain;charset=UTF-8"},
            )
            remaining = max(0.1, deadline - time.monotonic())
            try:
                with urllib.request.urlopen(
                    request, context=self.context, timeout=remaining
                ) as response:
                    return response.read().decode("utf-8", errors="replace")
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                raise OpenPLCConfigurationError(f"OpenPLC debug socket failed: {exc}") from exc

        handshake = polling_request("GET")
        first_packet = handshake.split("\x1e", 1)[0]
        if not first_packet.startswith("0"):
            raise OpenPLCConfigurationError("OpenPLC debug socket returned no handshake")
        try:
            sid = str(json.loads(first_packet[1:])["sid"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise OpenPLCConfigurationError("OpenPLC debug handshake was malformed") from exc

        namespace = "/api/debug"
        polling_request(
            "POST",
            sid=sid,
            body=f"40{namespace},{json.dumps({'token': self.authenticate()}, separators=(',', ':'))}",
        )

        connected = False
        while time.monotonic() < deadline and not connected:
            payload = polling_request("GET", sid=sid)
            for packet in payload.split("\x1e"):
                if packet == "2":
                    polling_request("POST", sid=sid, body="3")
                elif packet.startswith(f"40{namespace},"):
                    connected = True
                elif packet.startswith(f"42{namespace},"):
                    connected = True
            if not payload:
                time.sleep(0.02)
        if not connected:
            raise OpenPLCConfigurationError("OpenPLC debug namespace did not connect")

        event = json.dumps(
            ["debug_command", {"command": command}], separators=(",", ":")
        )
        polling_request("POST", sid=sid, body=f"42{namespace},{event}")
        while time.monotonic() < deadline:
            payload = polling_request("GET", sid=sid)
            for packet in payload.split("\x1e"):
                if packet == "2":
                    polling_request("POST", sid=sid, body="3")
                    continue
                prefix = f"42{namespace},"
                if not packet.startswith(prefix):
                    continue
                try:
                    name, data = json.loads(packet[len(prefix) :])
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
                if name != "debug_response":
                    continue
                if not isinstance(data, dict) or data.get("success") is False:
                    raise OpenPLCConfigurationError(
                        f"OpenPLC debug command failed: {data.get('error') if isinstance(data, dict) else data}"
                    )
                return str(data.get("data", ""))
        raise OpenPLCConfigurationError(f"OpenPLC debug command timed out after {timeout:g}s")

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.authenticate()}"}

    def upload(self, package: bytes, *, timeout: float) -> dict:
        boundary = f"----plc-agent-{uuid.uuid4().hex}"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="file"; filename="program.zip"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode("ascii") + package + f"\r\n--{boundary}--\r\n".encode("ascii")
        headers = self._auth_headers()
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        _, response = self._request(
            "POST", "/api/upload-file", data=body, headers=headers, timeout=timeout
        )
        return response

    def compilation_status(self, *, timeout: float) -> dict:
        _, response = self._request(
            "GET", "/api/compilation-status", headers=self._auth_headers(), timeout=timeout
        )
        return response

    def status(self) -> str:
        _, response = self._request("GET", "/api/status", headers=self._auth_headers())
        raw = str(response.get("status", ""))
        return raw.removeprefix("STATUS:")

    def command(self, target: str) -> str:
        endpoint = "/api/start-plc" if target == "RUNNING" else "/api/stop-plc"
        _, response = self._request("GET", endpoint, headers=self._auth_headers())
        return str(response.get("status", ""))


def upload_program(package_path: str | None, *, timeout: float) -> UploadResult:
    if not package_path:
        return UploadResult(False, "upload", "FAILED", [], "no compiled package was produced")
    container = _require_running_container(min(timeout, 15.0))
    # Copy to a host temp file; the normal text subprocess boundary must never
    # decode or otherwise alter ZIP bytes.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="plc-agent-upload-") as directory:
        local_package = Path(directory) / "program.zip"
        copied = _run_docker(
            ["cp", f"{container}:{package_path}", str(local_package)], timeout=timeout
        )
        if copied.returncode != 0:
            return UploadResult(False, "upload", "FAILED", [], copied.stderr.strip())
        try:
            package = local_package.read_bytes()
        except OSError as exc:
            return UploadResult(False, "upload", "FAILED", [], str(exc))

    client = _RuntimeClient()
    response = client.upload(package, timeout=min(timeout, 30.0))
    upload_error = response.get("UploadFileFail")
    if upload_error:
        return UploadResult(False, "upload", "FAILED", [], str(upload_error))

    deadline = time.monotonic() + timeout
    last_logs: list[str] = []
    while time.monotonic() < deadline:
        response = client.compilation_status(timeout=min(10.0, timeout))
        status = str(response.get("status", "UNKNOWN"))
        last_logs = [str(item) for item in response.get("logs", [])]
        if status == "SUCCESS":
            return UploadResult(True, None, status, last_logs, None)
        if status == "FAILED":
            return UploadResult(False, "gcc", status, last_logs, "Runtime GCC compilation failed")
        time.sleep(1.0)
    return UploadResult(False, "gcc", "TIMEOUT", last_logs, "Runtime GCC compilation timed out")


def runtime_status() -> str:
    _require_running_container(15.0)
    return _RuntimeClient().status()


def runtime_command(target: str, *, timeout: float) -> RuntimeCommandResult:
    if target not in {"RUNNING", "STOPPED"}:
        raise ValueError(f"unsupported runtime target: {target}")
    _require_running_container(min(timeout, 15.0))
    client = _RuntimeClient()
    message = client.command(target)
    deadline = time.monotonic() + timeout
    matches = 0
    actual = ""
    while time.monotonic() < deadline:
        actual = client.status()
        if actual == target:
            matches += 1
            if matches >= 2:
                return RuntimeCommandResult(actual, message)
        else:
            matches = 0
        time.sleep(0.25)
    return RuntimeCommandResult(actual, message)


def run_debug_command(command: str, *, timeout: float = 5.0) -> str:
    _require_running_container(min(timeout, 15.0))
    return _RuntimeClient().debug_command(command, timeout=timeout)
