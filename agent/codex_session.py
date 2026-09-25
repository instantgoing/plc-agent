"""One persistent Codex thread bound to one PLC engineering workspace."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .codex_client import CodexClient, CodexInfrastructureError, CodexTurn


@dataclass
class PLCTaskResult:
    success: bool
    state: str
    final_message: str
    thread_id: str | None
    workspace: str
    project_path: str
    files_modified: list[str] = field(default_factory=list)
    last_failure: str | None = None
    diagnostics: str | None = None
    commands: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _plc_snapshot(workspace: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in (*workspace.rglob("*.st"), *workspace.rglob("*.tests.json")):
        relative = path.relative_to(workspace)
        if any(part in {".git", ".plc-agent", ".venv", "smolagents"} for part in relative.parts):
            continue
        if path.is_file():
            snapshot[str(relative)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return snapshot


_CLI_RE = re.compile(
    r"main\.py['\"\s]+(check|compile|run|start|stop|verify|force|read|status)\b", re.I
)
_ARG_RE = re.compile(r"\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s;&|]+))")


def _cli_action(command: str) -> tuple[str | None, re.Match[str] | None]:
    matches = list(_CLI_RE.finditer(command))
    # A combined shell command has only one exit code and output. It cannot
    # provide trustworthy per-command evidence.
    return (matches[0].group(1).lower(), matches[0]) if len(matches) == 1 else (None, None)


def _command_target(command: str, match: re.Match[str], workspace: Path) -> str | None:
    token = _ARG_RE.match(command, match.end())
    if not token:
        return None
    raw = next(part for part in token.groups() if part is not None)
    path = Path(raw)
    try:
        return str((path if path.is_absolute() else workspace / path).resolve().relative_to(workspace))
    except ValueError:
        return None


def _has_real_assertion(payload: dict[str, Any]) -> bool:
    steps = payload.get("steps")
    return isinstance(steps, list) and any(
        isinstance(step, dict) and step.get("passed") is True
        and isinstance(step.get("expected"), dict) and bool(step["expected"])
        and isinstance(step.get("actual"), dict)
        and all(step["actual"].get(name.lower()) == wanted
                for name, wanted in step["expected"].items())
        for step in steps
    )


def _command_evidence(
    turn: CodexTurn, snapshots: list[dict[str, str]], workspace: Path,
    final: dict[str, str], modified: list[str],
) -> tuple[bool, bool, str | None, str | None]:
    checked_revisions: dict[str, str] = {}
    loaded: tuple[str, str] | None = None
    started = stopped = False
    verification: tuple[tuple[str, str], tuple[str, str]] | None = None
    last_failure = diagnostics = None
    for index, item in enumerate(turn.commands):
        command = str(item.get("command") or "")
        output = str(item.get("aggregated_output") or "")
        exit_code = item.get("exit_code")
        action, match = _cli_action(command)
        snapshot = snapshots[index] if index < len(snapshots) else {}
        target = _command_target(command, match, workspace) if match and action in {"check", "compile", "run", "verify"} else None
        try:
            payload = json.loads(output)
            if not isinstance(payload, dict):
                payload = {}
        except (ValueError, TypeError):
            payload = {}
        if action == "check" and exit_code == 0 and payload.get("success") is True and target in snapshot:
            checked_revisions[target] = snapshot[target]
        elif action in {"compile", "run"}:
            compile_result = payload.get("compile", {}) if action == "run" else payload
            if exit_code == 0 and isinstance(compile_result, dict) and compile_result.get("success") is True and target in snapshot:
                loaded = (target, snapshot[target])
                started = action == "run" and isinstance(payload.get("start"), dict) and payload["start"].get("success") is True
            else:
                loaded = None
                started = False
            verification = None
            stopped = False
        elif action == "start":
            started = exit_code == 0 and payload.get("success") is True
            stopped = False
        elif action == "verify":
            verification = None
            if (exit_code == 0 and payload.get("passed") is True and _has_real_assertion(payload)
                    and loaded and started and checked_revisions.get(loaded[0]) == loaded[1]
                    and snapshot.get(loaded[0]) == loaded[1] and target in snapshot):
                verification = (loaded, (target, snapshot[target]))
        elif action == "stop":
            stopped = exit_code == 0 and payload.get("success") is True
        if action and exit_code not in (0, None):
            last_failure = f"command exited {exit_code}: {command[:200]}"
            diagnostics = output[-4000:]
    modified_st = [name for name in modified if name.lower().endswith(".st")]
    checked = all(checked_revisions.get(name) == final.get(name) for name in modified_st)
    verified = bool(
        verification and stopped
        and final.get(verification[0][0]) == verification[0][1]
        and final.get(verification[1][0]) == verification[1][1]
        and all(name == verification[0][0] for name in modified_st)
        and all(name == verification[1][0] for name in modified if name.lower().endswith(".tests.json"))
    )
    if verified:
        last_failure = diagnostics = None
    return checked, verified, last_failure, diagnostics


def _cleanup_interrupted_runtime(turn: CodexTurn) -> str | None:
    running = False
    input_names: set[str] = set()
    forced_names: set[str] = set()
    for item in turn.commands:
        command = str(item.get("command") or "")
        action_match = re.search(r"main\.py['\"\s]+(compile|run|start|stop|force)\b", command, re.I)
        action = action_match.group(1).lower() if action_match else None
        if action == "force":
            forced_names.update(name.lower() for name in re.findall(r"--set\s+['\"]?([\w.]+)=", command, re.I))
            if item.get("exit_code") == 0:
                forced_names.difference_update(name.lower() for name in re.findall(r"--release\s+['\"]?([\w.]+)", command, re.I))
        if item.get("exit_code") != 0:
            continue
        if action in {"compile", "run"}:
            try:
                payload = json.loads(str(item.get("aggregated_output") or ""))
                compiled = payload.get("compile", payload)
                input_names.update(
                    variable["name"] for variable in compiled.get("variables", [])
                    if variable.get("location", "").upper().startswith("%I")
                )
            except (ValueError, TypeError, KeyError, AttributeError):
                pass
        if action in {"run", "start"}:
            running = True
        elif action == "stop":
            running = False
    pending = [str(item.get("command") or "") for item in turn.pending_commands]
    for command in pending:
        if any(match.group(1).lower() == "force" for match in _CLI_RE.finditer(command)):
            forced_names.update(name.lower() for name in re.findall(r"--set\s+['\"]?([\w.]+)=", command, re.I))
    errors: list[str] = []
    if turn.error and any(
        match.group(1).lower() in {"run", "start"}
        for command in pending for match in _CLI_RE.finditer(command)
    ):
        from plc_tools import get_plc_status
        try:
            status = get_plc_status()
            if not status.success:
                errors.append(status.tool_error or "Runtime status unavailable after interrupted start")
            else:
                running = status.actual_status == "RUNNING"
        except Exception as exc:
            errors.append(f"Runtime status unavailable after interrupted start: {exc}")
    if not running and not forced_names and not errors:
        return None

    from plc_tools import force_variables, stop_plc

    try:
        release_names = forced_names | (input_names if running else set())
        if release_names:
            released = force_variables(release=sorted(release_names))
            if not released.success:
                errors.append(released.tool_error or "forced-variable release failed")
    except Exception as exc:
        errors.append(f"forced-variable release failed: {exc}")
    if running:
        try:
            stopped = stop_plc()
            if not stopped.success:
                errors.append(stopped.tool_error or "Runtime stop failed")
        except Exception as exc:
            errors.append(f"Runtime stop failed: {exc}")
    return "Runtime cleanup failed: " + "; ".join(errors) if errors else "Test Runtime cleanup completed by the harness."


class CodexPLCSession:
    def __init__(
        self,
        *,
        workspace: str | Path,
        project_path: str | Path | None = None,
        client: CodexClient | None = None,
        max_repair_attempts: int = 5,
        max_commands: int = 40,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.workspace = Path(workspace).resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("workspace must be an existing directory")
        self.project_path = Path(project_path or Path(__file__).resolve().parents[1]).resolve(strict=True)
        if not (self.project_path / "main.py").is_file():
            raise ValueError("project_path must contain main.py")
        self.client = client or CodexClient()
        self.max_repair_attempts = max_repair_attempts
        self.max_commands = max_commands
        self.on_event = on_event
        self.state_file = self.workspace / ".plc-agent" / "codex-session.json"
        self.thread_id: str | None = None
        self.last_result: PLCTaskResult | None = None
        self._load()

    def _load(self) -> None:
        if not self.state_file.exists():
            return
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CodexInfrastructureError(f"cannot read Codex session state: {exc}") from exc
        if data.get("workspace") != str(self.workspace) or data.get("project_path") != str(self.project_path):
            raise CodexInfrastructureError("saved Codex thread belongs to a different workspace or project")
        self.thread_id = data.get("thread_id")

    def _save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.state_file.with_suffix(".tmp")
        temporary.write_text(json.dumps({
            "thread_id": self.thread_id,
            "workspace": str(self.workspace),
            "project_path": str(self.project_path),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.state_file)

    def interrupt(self) -> bool:
        return self.client.interrupt()

    def _instructions(self, user_message: str) -> str:
        entry = self.project_path / "main.py"
        python = Path(sys.executable)
        return (
            f"PLC engineering workspace: {self.workspace}\n"
            f"PLC tool entrypoint: {entry}\n"
            f"Python interpreter: {python}\n"
            "Use the existing CLI commands: check SOURCE.st, compile SOURCE.st, run SOURCE.st, "
            "start, stop, force --set NAME=VALUE, read NAME, verify PLAN.json. "
            "Run them as separate shell commands using the Python interpreter and tool entrypoint above. "
            "These commands return structured JSON and nonzero exit codes for PLC failures. "
            f"At most {self.max_repair_attempts} check/compile attempts are allowed this turn. "
            "If a command fails, read its diagnostics and repair within the limit. "
            "If you start the test Runtime, release forced variables and stop it before finishing. "
            "Do not treat compiler success as behavior verification. Do not claim behavior success "
            "unless a real verify command returned passed=true. "
            "Keep edits within the workspace and preserve a clear diff. "
            f"\nUser request:\n{user_message}"
        )

    def run(self, user_message: str, *, on_event: Callable[[dict[str, Any]], None] | None = None) -> PLCTaskResult:
        if not isinstance(user_message, str) or not user_message.strip():
            raise ValueError("user_message must be nonempty")
        before = _plc_snapshot(self.workspace)
        command_snapshots: list[dict[str, str]] = []

        def emit(event: dict[str, Any]) -> None:
            if event.get("type") == "item.completed" and (event.get("item") or {}).get("type") == "command_execution":
                command_snapshots.append(_plc_snapshot(self.workspace))
            if event.get("type") == "thread.started" and event.get("thread_id"):
                self.thread_id = str(event["thread_id"])
                self._save()
            for callback in (self.on_event, on_event):
                if callback:
                    try:
                        callback(event)
                    except Exception:
                        # Presentation errors must not interrupt a PLC turn.
                        pass

        turn = self.client.run(
            self._instructions(user_message), workspace=self.workspace,
            thread_id=self.thread_id, max_repair_attempts=self.max_repair_attempts,
            max_commands=self.max_commands,
            on_event=emit,
        )
        cleanup_message = _cleanup_interrupted_runtime(turn)
        if turn.thread_id and turn.thread_id != self.thread_id:
            self.thread_id = turn.thread_id
            self._save()
        after = _plc_snapshot(self.workspace)
        modified = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        modified_st = any(name.lower().endswith(".st") for name in modified)
        checked, verified, last_failure, diagnostics = _command_evidence(
            turn, command_snapshots, self.workspace, after, modified
        )
        if turn.error:
            state = ("attempt_limit_reached" if turn.limit_reached else
                     "cancelled" if turn.error == "Codex turn interrupted" else
                     "agent_infrastructure_error")
            success = False
        elif modified_st and not checked:
            state, success = "check_missing_or_failed", False
        elif modified and not verified:
            state, success = "behavior_unverified", False
        elif cleanup_message:
            state, success = "runtime_cleanup_required", False
        elif last_failure:
            state, success = "plc_tool_failed", False
        else:
            state, success = "verified" if verified else "completed", True
        message = turn.final_answer or turn.error or "Codex turn ended without a final answer"
        if cleanup_message:
            message += f"\n{cleanup_message}"
        if modified and not verified:
            message += "\nPLC behavior has not been verified by the real Runtime."
        if success:
            last_failure = diagnostics = None
        result = PLCTaskResult(
            success=success, state=state, final_message=message,
            thread_id=self.thread_id, workspace=str(self.workspace),
            project_path=str(self.project_path), files_modified=modified,
            last_failure=last_failure or turn.error, diagnostics=diagnostics,
            commands=turn.commands,
        )
        self.last_result = result
        return result
