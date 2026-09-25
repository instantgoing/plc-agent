"""Human and JSON terminal entrypoints for the Codex PLC session."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .codex_client import CodexInfrastructureError
from .codex_session import CodexPLCSession, PLCTaskResult


def print_event(event: dict[str, Any], *, stream: Any = None) -> None:
    stream = stream or sys.stdout
    kind = event.get("type")
    item = event.get("item") or {}
    item_type = item.get("type")
    if kind == "thread.started":
        print(f"Agent thread: {event.get('thread_id')}", file=stream, flush=True)
    elif kind == "item.started" and item_type == "command_execution":
        print(f"Command start: {item.get('command', '')}", file=stream, flush=True)
    elif kind == "item.completed" and item_type == "command_execution":
        print(f"Command exit: {item.get('exit_code')}", file=stream, flush=True)
        output = str(item.get("aggregated_output") or "").strip()
        if output:
            print(output[-4000:], file=stream, flush=True)
    elif kind == "item.completed" and item_type == "file_change":
        print(f"File modification: {json.dumps(item.get('changes', []), ensure_ascii=False)}", file=stream, flush=True)
    elif kind == "item.completed" and item_type == "agent_message":
        print(f"Agent: {item.get('text', '')}", file=stream, flush=True)
    elif kind in {"error", "turn.failed", "infrastructure.stderr"}:
        print(f"Error: {event.get('message') or event.get('error')}", file=stream, flush=True)


def _show_result(result: PLCTaskResult) -> None:
    print(f"\nState: {result.state}")
    print(result.final_message)
    if result.files_modified:
        print("Modified ST: " + ", ".join(result.files_modified))
    if result.last_failure:
        print("Last failure: " + result.last_failure)
    if result.diagnostics:
        print(result.diagnostics)


def _print_error(message: str, *, as_json: bool, workspace: Path, project_path: Path) -> None:
    if as_json:
        print(json.dumps(PLCTaskResult(
            success=False, state="agent_infrastructure_error", final_message=message,
            thread_id=None, workspace=str(workspace), project_path=str(project_path),
            last_failure=message,
        ).to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"Agent infrastructure error: {message}", file=sys.stderr)


def run_command(args: Any) -> int:
    from .env import load_project_env

    project_path = Path(__file__).resolve().parents[1]
    load_project_env(project_path)
    if not 1 <= args.max_attempts <= 5 or not 1 <= args.max_actions <= 100:
        print("--max-attempts must be 1..5 and --max-actions must be 1..100.", file=sys.stderr)
        return 2
    try:
        session = CodexPLCSession(
            workspace=args.workspace,
            project_path=project_path,
            max_repair_attempts=args.max_attempts,
            max_commands=args.max_actions,
        )
    except (OSError, ValueError, CodexInfrastructureError) as exc:
        _print_error(str(exc), as_json=bool(getattr(args, "json", False)),
                     workspace=Path(args.workspace), project_path=project_path)
        return 3
    if args.command == "chat":
        print("PLC Codex session. Enter /quit to exit, /json for the last result.")
        pending = args.task
        while True:
            try:
                task = pending if pending is not None else input("User > ")
            except (EOFError, KeyboardInterrupt):
                return 0
            pending = None
            task = task.strip()
            if task == "/quit":
                return 0
            if task == "/json":
                print(json.dumps(session.last_result.to_dict(), ensure_ascii=False, indent=2) if session.last_result else "No result yet")
                continue
            if not task:
                continue
            try:
                result = session.run(task, on_event=print_event)
            except KeyboardInterrupt:
                session.interrupt()
                print("Codex turn interrupted.")
                continue
            except (OSError, CodexInfrastructureError) as exc:
                print(f"Agent infrastructure error: {exc}", file=sys.stderr)
                continue
            _show_result(result)
    if bool(args.task) == bool(args.requirement_file):
        print("Provide exactly one task or --requirement-file.", file=sys.stderr)
        return 2
    try:
        task = args.requirement_file.read_text(encoding="utf-8") if args.requirement_file else args.task
        result = session.run(task, on_event=lambda event: print_event(event, stream=sys.stderr))
    except (OSError, CodexInfrastructureError) as exc:
        _print_error(str(exc), as_json=args.json,
                     workspace=session.workspace, project_path=project_path)
        return 3
    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        _show_result(result)
    return 0 if result.success else 3 if result.state == "agent_infrastructure_error" else 1
