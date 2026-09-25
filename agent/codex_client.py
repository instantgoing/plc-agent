"""Small process adapter for the local Codex CLI JSON event stream."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


EventSink = Callable[[dict[str, Any]], None]


class CodexInfrastructureError(RuntimeError):
    """Codex could not start or its event protocol failed."""


@dataclass
class CodexTurn:
    thread_id: str | None = None
    final_answer: str = ""
    exit_code: int | None = None
    completed: bool = False
    error: str | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)
    mcp_calls: list[dict[str, Any]] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    pending_commands: list[dict[str, Any]] = field(default_factory=list)
    pending_mcp_calls: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    limit_reached: bool = False


def _codex_binary() -> str:
    # On Windows the npm shim is a .cmd file; the .ps1 shim cannot be launched
    # by subprocess without an extra PowerShell process.
    name = "codex.cmd" if os.name == "nt" else "codex"
    found = shutil.which(name)
    if not found:
        raise CodexInfrastructureError(f"{name} is unavailable; install and authenticate Codex CLI")
    return found


def _launch_prefix(executable: str) -> list[str]:
    if os.name == "nt" and executable.lower().endswith(".cmd"):
        # An npm .cmd shim passes %* through cmd.exe, where user text may be
        # interpreted as shell syntax. Launch the installed JS entrypoint
        # through Node so the prompt stays one literal argv element.
        script = Path(executable).parent / "node_modules" / "@openai" / "codex" / "bin" / "codex.js"
        node = shutil.which("node.exe") or shutil.which("node")
        if not script.is_file() or not node:
            raise CodexInfrastructureError("Codex npm entrypoint or Node.js is unavailable")
        return [node, str(script)]
    return [executable]


class CodexClient:
    def __init__(self, *, executable: str | None = None, timeout_seconds: int = 900):
        self.executable = executable or _codex_binary()
        self.timeout_seconds = timeout_seconds
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._interrupted = False

    def interrupt(self) -> bool:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            self._interrupted = True
            process.terminate()
            return True

    def _check_auth(self) -> None:
        if os.environ.get("CODEX_API_KEY") or os.environ.get("OPENAI_API_KEY"):
            return
        if Path(self.executable).name.lower() not in {"codex", "codex.exe", "codex.cmd"}:
            return
        try:
            status = subprocess.run(
                [*_launch_prefix(self.executable), "login", "status"], capture_output=True,
                text=True, timeout=8, check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CodexInfrastructureError(f"cannot check Codex authentication: {exc}") from exc
        if status.returncode:
            raise CodexInfrastructureError("Codex is not authenticated; run `codex login` or set CODEX_API_KEY")

    def run(
        self,
        prompt: str,
        *,
        workspace: Path,
        thread_id: str | None = None,
        max_repair_attempts: int = 5,
        max_commands: int = 40,
        on_event: EventSink | None = None,
    ) -> CodexTurn:
        self._check_auth()
        workspace = workspace.resolve(strict=True)
        if not workspace.is_dir():
            raise CodexInfrastructureError(f"workspace is not a directory: {workspace}")
        project_root = Path(__file__).resolve().parents[1]
        mcp_args = [str(project_root / "plc_mcp.py"), "--project-root", str(workspace)]
        # Explicit per-turn configuration works even with --ignore-user-config
        # and binds every MCP file operation to this Codex workspace.
        command = [
            *_launch_prefix(self.executable), "exec",
            "-c", f"mcp_servers.plc.command={json.dumps(sys.executable)}",
            "-c", f"mcp_servers.plc.args={json.dumps(mcp_args, ensure_ascii=False)}",
        ]
        if thread_id:
            command += ["--approve-for-me", "resume", "--json", "--ignore-user-config", thread_id, prompt]
        else:
            command += [
                "--json", "--ignore-user-config",
                "--approve-for-me", "--skip-git-repo-check", "--cd", str(workspace), prompt,
            ]
        outcome = CodexTurn(thread_id=thread_id)
        self._interrupted = False
        received: queue.Queue[tuple[str, str | None]] = queue.Queue()

        try:
            child_env = os.environ.copy()
            # This is the old Chat Completions credential, not Codex auth.
            child_env.pop("PLC_AGENT_API_KEY", None)
            process = subprocess.Popen(
                command, cwd=workspace, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env=child_env,
            )
        except OSError as exc:
            raise CodexInfrastructureError(f"failed to start Codex: {exc}") from exc
        with self._lock:
            self._process = process

        def read_stream(stream: Any, kind: str) -> None:
            for line in stream:
                received.put((kind, line.rstrip("\r\n")))
            received.put((kind, None))

        stdout_reader = threading.Thread(target=read_stream, args=(process.stdout, "stdout"), daemon=True)
        stderr_reader = threading.Thread(target=read_stream, args=(process.stderr, "stderr"), daemon=True)
        stdout_reader.start()
        stderr_reader.start()
        open_streams = 2
        actions_started = 0
        repair_attempts = 0
        deadline = time.monotonic() + self.timeout_seconds
        try:
            while open_streams:
                if time.monotonic() >= deadline:
                    outcome.error = f"Codex turn timed out after {self.timeout_seconds} seconds"
                    process.terminate()
                    break
                try:
                    kind, line = received.get(timeout=0.2)
                except queue.Empty:
                    continue
                if line is None:
                    open_streams -= 1
                    continue
                if kind == "stderr":
                    if line and on_event:
                        on_event({"type": "infrastructure.stderr", "message": line})
                    if line and "blocked by policy" in line.lower():
                        outcome.error = "Codex command was blocked by policy"
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    outcome.error = f"invalid Codex JSON event: {line[:200]}"
                    process.terminate()
                    break
                if not isinstance(event, dict) or not isinstance(event.get("type"), str):
                    outcome.error = "Codex emitted an invalid event object"
                    process.terminate()
                    break
                outcome.events.append(event)
                if len(outcome.events) > 500:
                    outcome.events.pop(0)
                event_type = event["type"]
                item = event.get("item") or {}
                if event_type == "thread.started":
                    outcome.thread_id = event.get("thread_id")
                elif event_type == "turn.completed":
                    outcome.completed = True
                elif event_type == "turn.failed":
                    outcome.error = str(event.get("message") or event.get("error") or event_type)
                elif event_type == "item.completed" and item.get("type") == "agent_message":
                    outcome.final_answer = str(item.get("text") or outcome.final_answer)
                if item.get("type") == "command_execution":
                    if event_type == "item.started":
                        actions_started += 1
                        command_text = str(item.get("command") or "")
                        repair_attempts += len(re.findall(
                            r"main\.py['\"\s]+(?:check|compile|run)\b", command_text, re.I
                        ))
                        outcome.pending_commands.append(item)
                        if actions_started > max_commands or repair_attempts > max_repair_attempts:
                            outcome.limit_reached = True
                            outcome.error = "command or PLC repair attempt limit reached"
                            process.terminate()
                    elif event_type == "item.completed":
                        outcome.commands.append(item)
                        outcome.actions.append(item)
                        for index, pending in enumerate(outcome.pending_commands):
                            if pending.get("id") == item.get("id") and pending.get("command") == item.get("command"):
                                del outcome.pending_commands[index]
                                break
                elif item.get("type") == "mcp_tool_call" and item.get("server") == "plc":
                    if event_type == "item.started":
                        actions_started += 1
                        tool = str(item.get("tool") or "")
                        if tool in {"plc_check", "plc_compile"}:
                            repair_attempts += 1
                        outcome.pending_mcp_calls.append(item)
                        if actions_started > max_commands or repair_attempts > max_repair_attempts:
                            outcome.limit_reached = True
                            outcome.error = "action or PLC repair attempt limit reached"
                            process.terminate()
                    elif event_type == "item.completed":
                        outcome.mcp_calls.append(item)
                        outcome.actions.append(item)
                        outcome.pending_mcp_calls = [pending for pending in outcome.pending_mcp_calls
                                                     if pending.get("id") != item.get("id")]
                if on_event:
                    on_event(event)
            try:
                outcome.exit_code = process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                outcome.exit_code = process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            with self._lock:
                if self._process is process:
                    self._process = None
        if self._interrupted:
            outcome.error = "Codex turn interrupted"
        if outcome.exit_code != 0 and outcome.error is None:
            outcome.error = f"Codex exited with status {outcome.exit_code}"
        if not outcome.completed and outcome.error is None:
            outcome.error = "Codex ended without turn.completed"
        return outcome
