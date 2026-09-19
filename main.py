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
        "agent", help="generate, repair, and behavior-verify ST with the M5 Agent"
    )
    agent_parser.add_argument("task", nargs="?", help="natural-language PLC requirement")
    agent_parser.add_argument("--requirement-file", type=Path)
    agent_parser.add_argument("--max-attempts", type=int, choices=range(1, 4), default=3)
    agent_parser.add_argument("--provider")
    agent_parser.add_argument("--model-id")
    agent_parser.add_argument("--api-base")
    agent_parser.add_argument("--json", action="store_true", help="kept for CLI symmetry; output is always JSON")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "agent":
        from agent import M5Request, PLCRepairAgent

        if bool(args.task) == bool(args.requirement_file):
            payload = {
                "success": False,
                "failure_kind": "invalid_request",
                "final_message": "provide exactly one of task or --requirement-file",
                "attempts": [],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 2
        if args.requirement_file:
            try:
                task = args.requirement_file.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                payload = {
                    "success": False,
                    "failure_kind": "invalid_request",
                    "final_message": f"cannot read requirement file: {exc}",
                    "attempts": [],
                }
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 2
        else:
            task = args.task
        result = PLCRepairAgent(
            provider=args.provider,
            model_id=args.model_id,
            api_base=args.api_base,
        ).run(M5Request(task=task, max_attempts=args.max_attempts))
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
        if result.success:
            return 0
        if result.failure_kind in {"invalid_request", "model_unavailable", "tool_unavailable", "runtime_busy"}:
            return 2 if result.failure_kind == "invalid_request" else 3
        return 1
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
