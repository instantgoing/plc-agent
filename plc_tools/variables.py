"""M3 contracts for reading and forcing real OpenPLC debug variables."""

from __future__ import annotations

import struct
import math
import os
from dataclasses import asdict, dataclass

from plc_tools.state import VariableEntry, load_variable_map, load_debug_state, record_forces, serialized_debug
from runtime.openplc import OpenPLCConfigurationError, run_debug_command, runtime_program_hash


@dataclass(frozen=True)
class VariableValue:
    value: bool | int | float | str
    type: str
    index: int
    location: str
    id: str = ""


@dataclass(frozen=True)
class ReadVariablesResult:
    success: bool
    variables: dict[str, VariableValue]
    unresolved_names: list[str]
    tick: int | None = None
    tool_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "variables": {name: asdict(value) for name, value in self.variables.items()},
            "unresolved_names": self.unresolved_names,
            "tick": self.tick,
            "tool_error": self.tool_error,
        }


@dataclass(frozen=True)
class ForceFailure:
    name: str
    reason: str


@dataclass(frozen=True)
class ForceVariablesResult:
    success: bool
    forced: dict[str, bool | int | float | str]
    released: list[str]
    failures: list[ForceFailure]
    tool_error: str | None = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "forced": self.forced,
            "released": self.released,
            "failures": [asdict(item) for item in self.failures],
            "tool_error": self.tool_error,
        }


_SIZES = {
    "BOOL": 1,
    "SINT": 1,
    "USINT": 1,
    "BYTE": 1,
    "INT": 2,
    "UINT": 2,
    "WORD": 2,
    "DINT": 4,
    "UDINT": 4,
    "DWORD": 4,
    "REAL": 4,
    "LINT": 8,
    "ULINT": 8,
    "LWORD": 8,
    "LREAL": 8,
    # OpenPLC v4 bundled MatIEC ABI: int32 seconds + int32 nanoseconds.
    "TIME": 8,
}


def _hex_command(values: list[int]) -> str:
    return " ".join(f"{value:02X}" for value in values)


def _build_read_command(indices: list[int]) -> str:
    command = [0x44, (len(indices) >> 8) & 0xFF, len(indices) & 0xFF]
    for index in indices:
        command.extend([(index >> 8) & 0xFF, index & 0xFF])
    return _hex_command(command)


def _build_force_command(index: int, flag: int, value: bytes) -> str:
    return _hex_command(
        [
            0x42,
            (index >> 8) & 0xFF,
            index & 0xFF,
            flag,
            (len(value) >> 8) & 0xFF,
            len(value) & 0xFF,
            *value,
        ]
    )


def _decode(variable_type: str, value: bytes) -> bool | int | float | str:
    kind = variable_type.upper()
    if kind == "BOOL":
        return value[0] != 0
    if kind == "REAL":
        return struct.unpack("<f", value)[0]
    if kind == "LREAL":
        return struct.unpack("<d", value)[0]
    if kind == "TIME":
        seconds, nanos = struct.unpack("<ii", value)
        return seconds * 1000 + nanos / 1_000_000
    signed = kind in {"SINT", "INT", "DINT", "LINT"}
    return int.from_bytes(value, "little", signed=signed)


def _parse_read_response(
    raw: str, variables: list[VariableEntry]
) -> tuple[int | None, dict[str, VariableValue]]:
    try:
        payload = bytes(int(item, 16) for item in raw.strip().split())
    except ValueError:
        return None, {}
    if len(payload) < 10 or payload[0:2] != b"D~":
        return None, {}
    tick = int.from_bytes(payload[4:8], "big")
    response_size = int.from_bytes(payload[8:10], "big")
    data = payload[10 : 10 + response_size]
    offset = 0
    result: dict[str, VariableValue] = {}
    for variable in variables:
        size = _SIZES.get(variable.type.upper())
        if size is None or offset + size > len(data):
            break
        value = _decode(variable.type, data[offset : offset + size])
        offset += size
        key = variable.name if sum(v.name.casefold() == variable.name.casefold() for v in variables) == 1 else variable.id
        result[key] = VariableValue(
            value, variable.type, variable.index, variable.location, variable.id
        )
    return tick, result


def _serialize(variable_type: str, value: bool | int | float | str) -> bytes | None:
    kind = variable_type.upper()
    if kind == "BOOL":
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1"}:
                value = True
            elif normalized in {"false", "0"}:
                value = False
        if value is True or value == 1:
            return b"\x01"
        if value is False or value == 0:
            return b"\x00"
        return None
    if kind in {"REAL", "LREAL"}:
        try:
            if not math.isfinite(float(value)):
                return None
            return struct.pack("<f" if kind == "REAL" else "<d", float(value))
        except (TypeError, ValueError, OverflowError):
            return None
    if kind == "TIME":
        # TIME is expressed in milliseconds at the debug contract boundary.
        try:
            millis = float(value)
            seconds = int(millis // 1000)
            return struct.pack("<ii", seconds, round((millis - seconds * 1000) * 1_000_000))
        except (TypeError, ValueError, OverflowError, struct.error):
            return None
    size = _SIZES.get(kind)
    if size is None:
        return None
    try:
        if isinstance(value, float) and not value.is_integer():
            return None
        numeric = int(value)
        signed = kind in {"SINT", "INT", "DINT", "LINT"}
        return numeric.to_bytes(size, "little", signed=signed)
    except (TypeError, ValueError, OverflowError):
        return None


def _resolve(
    requested: list[str], variables: list[VariableEntry]
) -> tuple[list[VariableEntry], list[str]]:
    resolved: list[VariableEntry] = []
    unresolved: list[str] = []
    for name in requested:
        exact = [v for v in variables if v.id and v.id.casefold() == name.casefold()]
        matches = exact or [v for v in variables if v.name.casefold() == name.casefold()
                            or v.runtime_path.casefold() == name.casefold()]
        if len(matches) != 1:
            unresolved.append(name)
        else:
            if matches[0] not in resolved:
                resolved.append(matches[0])
    return resolved, unresolved


@serialized_debug
def read_variables(names: list[str], *, timeout: float = 5.0) -> ReadVariablesResult:
    variable_map = load_variable_map()
    if not variable_map:
        return ReadVariablesResult(False, {}, names, tool_error="no variable map; run compile first")
    targets, unresolved = _resolve(names or [item.id or item.name for item in variable_map], variable_map)
    unsupported = [v.id or v.name for v in targets if v.type.upper() not in _SIZES]
    targets = [v for v in targets if v.type.upper() in _SIZES]
    unresolved.extend(unsupported)
    if not targets:
        return ReadVariablesResult(True, {}, unresolved)
    try:
        identity = load_debug_state().get("program")
        if identity and identity.get("runtime_hash") and runtime_program_hash(timeout=timeout) != identity["runtime_hash"]:
            return ReadVariablesResult(False, {}, unresolved, tool_error="Runtime program hash differs from compiled debug map")
        raw = run_debug_command(
            _build_read_command([item.index for item in targets]), timeout=timeout
        )
    except OpenPLCConfigurationError as exc:
        return ReadVariablesResult(False, {}, unresolved, tool_error=str(exc))
    tick, values = _parse_read_response(raw, targets)
    if len(values) != len(targets):
        return ReadVariablesResult(
            False, values, unresolved, tick, "OpenPLC returned an incomplete variable payload"
        )
    return ReadVariablesResult(True, values, unresolved, tick)


@serialized_debug
def force_variables(
    values: dict[str, bool | int | float | str] | None = None,
    *, release: list[str] | None = None, timeout: float = 5.0,
) -> ForceVariablesResult:
    return _force_variables(values, release=release, timeout=timeout)


def _force_variables(
    values: dict[str, bool | int | float | str] | None = None,
    *,
    release: list[str] | None = None,
    timeout: float = 5.0,
) -> ForceVariablesResult:
    values = values or {}
    release = release or []
    variable_map = load_variable_map()
    if not variable_map:
        return ForceVariablesResult(False, {}, [], [], "no variable map; run compile first")
    if os.environ.get("PLC_RUNTIME_ENVIRONMENT", "simulation") != "simulation":
        return ForceVariablesResult(False, {}, [], [], "Level 3 force is disabled; simulation only")
    identity = load_debug_state().get("program")
    if identity and identity.get("runtime_hash"):
        try:
            if runtime_program_hash(timeout=timeout) != identity["runtime_hash"]:
                return ForceVariablesResult(False, {}, [], [], "Runtime program hash differs from compiled debug map")
        except OpenPLCConfigurationError as exc:
            return ForceVariablesResult(False, {}, [], [], str(exc))
    forced: dict[str, bool | int | float | str] = {}
    released: list[str] = []
    failures: list[ForceFailure] = []

    operations: list[tuple[str, VariableEntry, int, bytes, bool | int | float | str | None]] = []
    for name, value in values.items():
        matched, _ = _resolve([name], variable_map)
        variable = matched[0] if matched else None
        if variable is None:
            failures.append(ForceFailure(name, "variable not found"))
            continue
        if not variable.location.startswith(("%I", "%Q")):
            failures.append(ForceFailure(name, "only located %I/%Q variables can be forced"))
            continue
        encoded = _serialize(variable.type, value)
        if encoded is None:
            failures.append(ForceFailure(name, f"cannot serialize value as {variable.type}"))
            continue
        operations.append((name, variable, 1, encoded, _decode(variable.type, encoded)))
    for name in release:
        matched, _ = _resolve([name], variable_map)
        variable = matched[0] if matched else None
        if variable is None:
            failures.append(ForceFailure(name, "variable not found"))
            continue
        size = _SIZES.get(variable.type.upper())
        if size is None:
            failures.append(ForceFailure(name, f"unsupported type {variable.type}"))
            continue
        operations.append((name, variable, 0, bytes(size), None))

    for name, variable, flag, encoded, original in operations:
        try:
            raw = run_debug_command(
                _build_force_command(variable.index, flag, encoded), timeout=timeout
            )
        except OpenPLCConfigurationError as exc:
            failures.append(ForceFailure(name, str(exc)))
            continue
        try:
            response = bytes(int(item, 16) for item in raw.strip().split())
        except ValueError:
            response = b""
        if len(response) < 2 or response[0] != 0x42 or response[1] != 0x7E:
            failures.append(ForceFailure(name, f"runtime rejected force: {raw[:80]}"))
        elif flag == 1 and original is not None:
            forced[name] = original
            record_forces({variable.id or variable.name: original}, [])
        else:
            released.append(name)
            record_forces({}, [variable.id or variable.name])
    return ForceVariablesResult(not failures, forced, released, failures)


def unforce_variables(variables: list[str], *, timeout: float = 5.0) -> ForceVariablesResult:
    """Explicit release contract; never overload a force value with null."""
    return force_variables({}, release=variables, timeout=timeout)
