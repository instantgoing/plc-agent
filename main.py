"""Small CLI for the currently implemented PLC-Agent milestone."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from plc_tools import (
    compile_st,
    force_variables,
    get_plc_status,
    read_variables,
    start_plc,
    stop_plc,
    verify_file,
)
from plc_tools.check import check_st


def _collect_clarification(question: str, choices: list[str]) -> str | None:
    """Return one terminal answer, or None when this invocation must remain non-interactive."""

    if not sys.stdin.isatty():
        return None
    print("\n需要补充 PLC 需求后才能安全继续：")
    print(question)
    if choices:
        print("\n可选答案：")
        for index, choice in enumerate(choices, start=1):
            print(f"  {index}. {choice}")
    print("  C. 自定义填写")
    while True:
        answer = input("请选择编号，或输入 C 后填写（直接回车取消）：").strip()
        if not answer:
            return None
        if answer.lower() == "c":
            custom = input("请输入你的完整补充：").strip()
            if custom:
                return custom
            print("自定义答案不能为空。")
            continue
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1]
        print("请输入列出的编号，或输入 C。")


def _append_clarification(task: str, question: str, answer: str) -> str:
    """Make the selected answer explicit input for the next bounded Agent run."""

    return (
        f"{task}\n\n"
        "User clarification for the previously unresolved PLC requirement:\n"
        f"Question: {question}\n"
        f"Answer: {answer}"
    )


def _print_agent_result(result: object) -> None:
    """Render a compact terminal report; complete machine data stays behind --json."""

    success = bool(getattr(result, "success", False))
    state = getattr(result, "state", None) or "unknown"
    failure_kind = getattr(result, "failure_kind", None)
    final_message = str(getattr(result, "final_message", ""))
    model_final_message = getattr(result, "model_final_message", None)
    attempts = list(getattr(result, "attempts", []) or [])
    st_code = getattr(result, "st_code", None)
    plan = getattr(result, "verification_plan", None)

    print("\n=== PLC-Agent ===")
    print(f"Result: {'verified by real PLC behavior' if success else 'not completed'}")
    print(f"State: {state}")
    if failure_kind:
        print(f"Failure kind: {failure_kind}")
    if final_message:
        print(f"\nMessage:\n{final_message}")
    if (
        state != "needs_user_input"
        and isinstance(model_final_message, str)
        and model_final_message.strip()
        and model_final_message != final_message
    ):
        print(f"\nModel response:\n{model_final_message.strip()}")
    if attempts:
        print(f"\nEvaluation attempts: {len(attempts)}")
        for attempt in attempts:
            number = getattr(attempt, "attempt", "?")
            phase = getattr(attempt, "phase", "unknown")
            accepted = getattr(attempt, "accepted", False)
            print(f"  - Attempt {number}: {phase}{' (passed)' if accepted else ''}")
    if st_code:
        print("\n--- Structured Text ---")
        print(st_code.rstrip())
    if plan:
        steps = plan.get("steps", []) if isinstance(plan, dict) else []
        print(f"\nVerification plan: {len(steps)} assertions (use --json for details)")


def _print_agent_invalid_request(payload: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    print("\n=== PLC-Agent ===")
    print("Result: invalid request")
    print(f"Message: {payload['final_message']}")


def _write_verified_artifacts(result: object, output: Path, *, overwrite: bool) -> tuple[Path, Path]:
    """Persist only an accepted candidate and its matching behavior plan."""

    if not bool(getattr(result, "success", False)):
        raise ValueError("refusing to write artifacts because real PLC behavior verification did not pass")
    st_code = getattr(result, "st_code", None)
    verification_plan = getattr(result, "verification_plan", None)
    if not isinstance(st_code, str) or not st_code.strip() or not isinstance(verification_plan, dict):
        raise ValueError("accepted result has no complete ST program and verification plan")
    if output.suffix.lower() != ".st":
        raise ValueError("--output must name a .st file")
    if not output.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output.parent}")

    plan_path = output.with_suffix(".tests.json")
    existing = [path for path in (output, plan_path) if path.exists()]
    if existing and not overwrite:
        names = ", ".join(str(path) for path in existing)
        raise FileExistsError(f"refusing to overwrite existing artifact(s): {names}; pass --overwrite")

    output.write_text(st_code.rstrip() + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(verification_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output, plan_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="plc-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="run real MatIEC compiler verification")
    check_parser.add_argument("source", type=Path)

    compile_parser = subparsers.add_parser(
        "compile", help="compile ST and load it into the real OpenPLC Runtime"
    )
    compile_parser.add_argument("source", type=Path)

    run_parser = subparsers.add_parser(
        "run", help="compile, load, and start a real OpenPLC scan cycle"
    )
    run_parser.add_argument("source", type=Path)

    subparsers.add_parser("start", help="start the loaded PLC program")
    subparsers.add_parser("stop", help="stop the loaded PLC program")
    subparsers.add_parser("status", help="read the OpenPLC runtime status")

    read_parser = subparsers.add_parser("read", help="read real PLC variable values")
    read_parser.add_argument("names", nargs="*")

    force_parser = subparsers.add_parser("force", help="force or release located variables")
    force_parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    force_parser.add_argument("--release", action="append", default=[], metavar="NAME")

    verify_parser = subparsers.add_parser("verify", help="run a real behavior test plan")
    verify_parser.add_argument("plan", type=Path)

    agent_parser = subparsers.add_parser(
        "agent", help="run one Codex turn in a PLC workspace"
    )
    agent_parser.add_argument("task", nargs="?", help="natural-language PLC requirement")
    agent_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    agent_parser.add_argument("--requirement-file", type=Path)
    agent_parser.add_argument("--max-attempts", type=int, default=5)
    agent_parser.add_argument("--max-actions", type=int, default=40)
    agent_parser.add_argument(
        "--json", action="store_true",
        help="emit one JSON result without prompting, for scripts and CI",
    )

    chat_parser = subparsers.add_parser(
        "chat", help="continue a persistent Codex PLC conversation with live progress"
    )
    chat_parser.add_argument("task", nargs="?", help="optional first PLC requirement")
    chat_parser.add_argument("--workspace", type=Path, default=Path.cwd())
    chat_parser.add_argument("--max-attempts", type=int, default=5)
    chat_parser.add_argument("--max-actions", type=int, default=40)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from agent.env import load_project_env
    load_project_env(Path(__file__).resolve().parent)
    if args.command in {"agent", "chat"}:
        from agent.codex_cli import run_command
        return run_command(args)
    if args.command == "check":
        result = check_st(args.source)
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        return 0 if result.success else 1
    if args.command in {"compile", "run"}:
        result = compile_st(args.source)
        payload: dict = {"compile": result.to_dict()} if args.command == "run" else result.to_dict()
        if args.command == "run" and result.success:
            started = start_plc()
            payload["start"] = started.to_dict()
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0 if started.success else 1
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if result.success else 1
    if args.command == "start":
        result = start_plc()
    elif args.command == "stop":
        result = stop_plc()
    elif args.command == "status":
        result = get_plc_status()
    elif args.command == "read":
        result = read_variables(args.names)
    elif args.command == "force":
        values: dict[str, bool | int | float | str] = {}
        for assignment in args.set:
            if "=" not in assignment:
                print(json.dumps({"success": False, "tool_error": f"invalid --set: {assignment}"}))
                return 2
            name, raw_value = assignment.split("=", 1)
            normalized = raw_value.strip().lower()
            if normalized in {"true", "false"}:
                value: bool | int | float | str = normalized == "true"
            else:
                try:
                    value = int(raw_value, 0)
                except ValueError:
                    try:
                        value = float(raw_value)
                    except ValueError:
                        value = raw_value
            values[name] = value
        result = force_variables(values, release=args.release)
    elif args.command == "verify":
        result = verify_file(args.plan)
    else:
        return 2
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    succeeded = result.passed if args.command == "verify" else result.success
    return 0 if succeeded else 1


if __name__ == "__main__":
    sys.exit(main())
