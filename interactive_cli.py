"""Human-facing, in-process PLC chat; the JSON CLI remains in main.py."""

from __future__ import annotations

import json
from threading import Thread
from typing import Callable

from agent import M5Result, PLCEvent, PLCSession


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def print_progress(event: PLCEvent, *, output: Callable[[str], None] = print) -> None:
    """Render stable phase events, never raw model internals or Runtime commands."""

    name, data = event.name, event.data
    messages = {
        "model_preflight_started": "正在检查模型凭据与工具能力…",
        "model_preflight_passed": "模型工具能力检查通过。",
        "candidate_generated": "已生成候选程序。",
        "check_started": "正在进行 ST 预检…",
        "compile_started": "预检通过，正在编译并加载真实 Runtime…",
        "runtime_started": "Runtime 已启动，正在验证行为…",
        "repair_started": "检查未通过，正在尝试修复…",
        "accepted": "真实行为验证通过。",
    }
    if name in messages:
        output(f"Agent > {messages[name]}")
    elif name == "requirement_analyzed":
        output("Agent > 需求规格已生成。" if data.get("ready") else "Agent > 需求中仍有待确认信息。")
    elif name == "waiting_for_user":
        output("Agent > 等待你补充需求。")
    elif name == "tool_call_rejected":
        output("Agent > 工具参数格式有误，正在纠正…" if data.get("reason") == "schema_error"
               else "Agent > 工具调用未被接受，正在处理…")
    elif name == "check_failed":
        output("Agent > ST 预检未通过，正在查看诊断。")
    elif name == "cleanup_completed":
        stop = data.get("stop_result")
        release = data.get("release_result")
        cleaned = (
            isinstance(stop, dict) and stop.get("success") is True
            and (release is None or isinstance(release, dict) and release.get("success") is True)
        )
        output("Agent > Runtime 清理已完成。" if cleaned else "Agent > Runtime 清理未完全成功，请检查结果。")
    elif name == "verification_step":
        output(
            f"Agent > 验证步骤 {data.get('step', '?')}: "
            f"{'通过' if data.get('passed') else '未通过'}；"
            f"expected={_json(data.get('expected', {}))}；"
            f"actual={_json(data.get('actual', {}))}"
        )
    elif name == "failed":
        output(f"Agent > 本轮未通过：{data.get('failure_kind') or 'unknown'}。")


def print_result(result: M5Result, *, output: Callable[[str], None] = print) -> None:
    """Separate the human summary, ST, plan, and observed expected/actual."""

    if result.state == "needs_user_input":
        output(f"\nAgent > {result.final_message}")
        if result.clarification_options:
            output("可选回答（也可以直接输入自己的答案）：")
            for index, choice in enumerate(result.clarification_options, 1):
                output(f"  {index}. {choice}")
        return

    if result.success:
        output(f"\nAgent > 已通过真实 PLC 行为验证；Runtime 尝试 {len(result.attempts)} 次。")
    else:
        output(f"\nAgent > 未完成验证（{result.failure_kind or result.state}）：{result.final_message}")
    if result.st_code:
        output("\n--- 最终 ST ---" if result.success else "\n--- 未验证的候选 ST ---")
        output(result.st_code.rstrip())
    if result.verification_plan:
        output("\n--- 验证计划 ---")
        output(json.dumps(result.verification_plan, ensure_ascii=False, indent=2))
    for attempt in result.attempts:
        verification = attempt.verify_result
        if not verification:
            continue
        output(f"\n--- 第 {attempt.attempt} 次真实运行证据 ---")
        for step in verification.get("steps", []):
            output(
                f"步骤 {step.get('step', '?')} "
                f"{'通过' if step.get('passed') else '失败'}: "
                f"expected={_json(step.get('expected', {}))}, "
                f"actual={_json(step.get('actual', {}))}"
            )
        for failure in verification.get("failures", []):
            output(
                f"差异: {failure.get('variable') or 'tool'} "
                f"expected={_json(failure.get('expected'))}, "
                f"actual={_json(failure.get('actual'))}"
            )
        output(f"释放强制变量: {_json(verification.get('cleanup_result'))}")
        output(f"停止 Runtime: {_json(attempt.stop_result)}")


def _run_turn(session: PLCSession, message: str, *, first: bool,
              output: Callable[[str], None]) -> M5Result:
    outcome: dict[str, object] = {}

    def work() -> None:
        try:
            outcome["result"] = session.submit(message) if first else session.resume(message)
        except Exception as exc:
            outcome["error"] = exc

    worker = Thread(target=work, name="plc-agent-turn")
    worker.start()
    cancel_requested = False
    while worker.is_alive():
        try:
            worker.join(0.1)
        except KeyboardInterrupt:
            cancel_requested = True
            output("Agent > 已请求取消；等待 Runtime 停止和强制变量释放…")
        if cancel_requested:
            session.cancel()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["result"]


def run_interactive(
    session: PLCSession,
    *,
    first_message: str | None = None,
    input_fn: Callable[[str], str] = input,
    output: Callable[[str], None] = print,
) -> int:
    """One process-local conversation; /json preserves complete machine evidence."""

    output("PLC-Agent 交互模式。输入 /help 查看命令，/quit 退出。")
    pending = first_message
    choices: list[str] = []
    while True:
        try:
            message = pending if pending is not None else input_fn("用户 > ")
        except (EOFError, KeyboardInterrupt):
            output("Agent > 会话已结束。")
            return 0
        pending = None
        message = message.strip()
        if not message:
            continue
        if message == "/quit":
            output("Agent > 会话已结束。")
            return 0
        if message == "/help":
            output("/json 查看上一轮完整 JSON；/metrics 查看体验指标；/quit 退出。")
            continue
        if message == "/json":
            output(json.dumps(session.last_result.to_dict(), ensure_ascii=False, indent=2)
                   if session.last_result else "还没有运行结果。")
            continue
        if message == "/metrics":
            output(json.dumps(session.metrics_dict(), ensure_ascii=False, indent=2))
            continue
        if choices and message.isdigit() and 1 <= int(message) <= len(choices):
            message = choices[int(message) - 1]
        try:
            result = _run_turn(session, message, first=session.turn == 0, output=output)
        except Exception as exc:
            output(f"Agent > 会话调用失败：{type(exc).__name__}: {exc}")
            choices = []
            continue
        print_result(result, output=output)
        choices = result.clarification_options if result.state == "needs_user_input" else []
