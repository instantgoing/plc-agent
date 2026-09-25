"""M4 declarative behavior verification over real PLC variable tools."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from plc_tools.runtime import get_plc_status
from plc_tools.variables import force_variables, read_variables


@dataclass(frozen=True)
class VerificationFailure:
    step: int
    variable: str
    expected: Any
    actual: Any
    reason: str


@dataclass(frozen=True)
class StepResult:
    step: int
    passed: bool
    time_ms: int
    inputs: dict[str, Any]
    expected: dict[str, Any]
    actual: dict[str, Any]


@dataclass(frozen=True)
class VerifyResult:
    passed: bool
    failures: list[VerificationFailure]
    steps: list[StepResult]
    tool_error: str | None = None
    cancelled: bool = False
    cleanup_result: dict[str, Any] | None = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "failures": [asdict(item) for item in self.failures],
            "steps": [asdict(item) for item in self.steps],
            "tool_error": self.tool_error,
            "cancelled": self.cancelled,
            "cleanup_result": self.cleanup_result,
        }


def _normalize_steps(plan: dict | list) -> list[dict] | None:
    candidate = plan.get("steps") if isinstance(plan, dict) else plan
    if not isinstance(candidate, list) or not all(isinstance(item, dict) for item in candidate):
        return None
    return candidate


def verify_plan(
    plan: dict | list,
    *,
    default_settle_ms: int = 50,
    cancel_requested: Callable[[], bool] | None = None,
    on_step: Callable[[StepResult], None] | None = None,
) -> VerifyResult:
    steps = _normalize_steps(plan)
    if steps is None:
        return VerifyResult(False, [], [], "test plan must be a list or contain a steps list")
    if not any(isinstance(step.get("expect", step.get("expected")), dict)
               and step.get("expect", step.get("expected")) for step in steps):
        return VerifyResult(False, [], [], "test plan must contain at least one output assertion")
    status = get_plc_status()
    if not status.success or status.actual_status != "RUNNING":
        detail = status.tool_error or f"PLC status is {status.actual_status}"
        return VerifyResult(False, [], [], f"PLC must be RUNNING: {detail}")

    failures: list[VerificationFailure] = []
    results: list[StepResult] = []
    forced_names: set[str] = set()
    started = time.monotonic()
    previous_time_ms = 0
    cancelled = False
    cleanup_result: dict[str, Any] | None = None
    cleanup_error: str | None = None

    def wait(seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while True:
            if cancel_requested and cancel_requested():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(remaining, 0.05))

    try:
        for index, step in enumerate(steps):
            if cancel_requested and cancel_requested():
                cancelled = True
                break
            step_number = index + 1
            inputs = step.get("inputs", {})
            expected = step.get("expect", step.get("expected", {}))
            if not isinstance(inputs, dict) or not isinstance(expected, dict):
                failures.append(
                    VerificationFailure(
                        step_number, "", expected, None, "inputs and expected must be objects"
                    )
                )
                continue
            target_time_ms = int(step.get("time_ms", previous_time_ms))
            previous_time_ms = max(previous_time_ms, target_time_ms)
            remaining = target_time_ms / 1000 - (time.monotonic() - started)
            if remaining > 0 and not wait(remaining):
                cancelled = True
                break

            forced_names.update(inputs)
            force_result = force_variables(inputs)
            if cancel_requested and cancel_requested():
                cancelled = True
                break
            if not force_result.success:
                for failure in force_result.failures:
                    failures.append(
                        VerificationFailure(
                            step_number,
                            failure.name,
                            inputs.get(failure.name),
                            None,
                            f"force failed: {failure.reason}",
                        )
                    )
                if force_result.tool_error:
                    failures.append(
                        VerificationFailure(
                            step_number, "", inputs, None, force_result.tool_error
                        )
                    )

            settle_ms = max(0, int(step.get("settle_ms", default_settle_ms)))
            if settle_ms and not wait(settle_ms / 1000):
                cancelled = True
                break
            read_result = read_variables(list(expected))
            actual = {
                name: value.value for name, value in read_result.variables.items()
            }
            if not read_result.success:
                failures.append(
                    VerificationFailure(
                        step_number,
                        "",
                        expected,
                        actual,
                        read_result.tool_error or "variable read failed",
                    )
                )
            for name, wanted in expected.items():
                observed = actual.get(name.lower())
                if observed != wanted:
                    failures.append(
                        VerificationFailure(
                            step_number, name, wanted, observed, "value mismatch"
                        )
                    )
            step_failed = any(item.step == step_number for item in failures)
            step_result = StepResult(
                    step_number,
                    not step_failed,
                    target_time_ms,
                    dict(inputs),
                    dict(expected),
                    actual,
                )
            results.append(step_result)
            if on_step is not None:
                on_step(step_result)
    finally:
        if forced_names:
            try:
                release_result = force_variables(release=sorted(forced_names))
                cleanup_result = release_result.to_dict()
                if not release_result.success:
                    cleanup_error = release_result.tool_error or "forced-variable release failed"
                    failures.append(
                        VerificationFailure(0, "", None, None, "forced-variable release failed")
                    )
            except Exception as exc:
                cleanup_error = f"{type(exc).__name__}: {exc}"
                cleanup_result = {"success": False, "tool_error": f"{type(exc).__name__}: {exc}"}
                failures.append(
                    VerificationFailure(0, "", None, None, "forced-variable release failed")
                )
    return VerifyResult(
        not failures and not cancelled,
        failures,
        results,
        cleanup_error or ("verification cancelled" if cancelled else None),
        cancelled,
        cleanup_result,
    )


def verify_file(path: str | Path) -> VerifyResult:
    source = Path(path).resolve()
    try:
        plan = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return VerifyResult(False, [], [], f"cannot read test plan: {exc}")
    return verify_plan(plan)
