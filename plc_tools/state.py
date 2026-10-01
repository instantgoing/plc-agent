"""Small persisted hand-off between compile and M3 variable tools."""

from __future__ import annotations

import json
import os
import re
import hashlib
import time
import uuid
from functools import wraps
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import asdict, dataclass
from pathlib import Path

from plc_context.st_adapter import parse_st


@dataclass(frozen=True)
class VariableEntry:
    name: str
    type: str
    location: str
    index: int
    id: str = ""
    owner: str = ""
    scope: str = "local"
    runtime_path: str = ""


def _state_path() -> Path:
    configured = os.environ.get("PLC_STATE_FILE")
    return Path(configured).resolve() if configured else Path(".plc-agent/state.json").resolve()


def parse_variable_map(raw_csv: str, st_code: str, *,
                       fragment_fallback: bool = True) -> list[VariableEntry]:
    # The same ST adapter supplies static I/O bindings to context queries and
    # to the compiled Runtime debug map. The regex branch only preserves the
    # historical contract for declaration fragments passed by older callers.
    parsed = parse_st(st_code.encode("utf-8"), "<compiled source>")
    declarations = [*parsed.globals,
                    *(variable for pou in parsed.pous for variable in pou.variables)]
    locations: dict[str, str] = {}
    ambiguous: set[str] = set()
    for variable in declarations:
        if variable.address:
            key = variable.name.casefold()
            if key in locations and locations[key] != variable.address:
                ambiguous.add(key)
            locations[key] = variable.address
    for key in ambiguous:
        del locations[key]
    if fragment_fallback and not parsed.pous and not parsed.globals:
        locations = {
            match.group(1).lower(): match.group(2).upper()
            for match in re.finditer(
                r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AT\s+(%[IQM][A-Z]*[0-9][0-9.]*)",
                st_code, re.IGNORECASE,
            )
        }
    # MatIEC FB rows describe concrete instances, including the program instance.
    instances = {}
    for line in raw_csv.splitlines():
        parts = line.strip().split(";")
        if len(parts) >= 5 and parts[1] == "FB":
            instances[parts[2].casefold()] = parts[4]
    programs = {pou.name.casefold(): pou for pou in parsed.pous if pou.kind == "program"}
    program_instances = {path: kind for path, kind in instances.items() if kind.casefold() in programs}
    variables: list[VariableEntry] = []
    debug_index = 0
    for raw_line in raw_csv.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        parts = line.split(";")
        if len(parts) < 5:
            continue
        kind, full_path, variable_type = parts[1], parts[2], parts[4]
        if kind == "FB" or not full_path or not variable_type:
            continue
        segments = full_path.split(".")
        if len(segments) < 4:
            continue
        name = ".".join(segments[3:]).lower()
        program_path = ".".join(segments[:3]).casefold()
        program = instances.get(program_path, parsed.pous[-1].name if parsed.pous else segments[2])
        # Multiple instances of a program must never collapse onto its type name.
        count = sum(kind.casefold() == program.casefold() for kind in program_instances.values())
        owner = program if count <= 1 else ".".join(segments[:3])
        if len(segments) > 4:
            owner += "." + ".".join(segments[3:-1])
        declaration_owner = instances.get(".".join(segments[:-1]).casefold(), program)
        matches = [v for v in declarations if (v.owner or "").casefold() == declaration_owner.casefold()
                   and v.name.casefold() == segments[-1].casefold()]
        address = matches[0].address or "" if len(matches) == 1 else locations.get(name, "")
        scope = matches[0].scope if len(matches) == 1 else "local"
        variable_id = f"{owner}:{segments[-1]}".casefold()
        variables.append(
            VariableEntry(name, variable_type.upper(), address, debug_index,
                          variable_id, owner, scope, full_path)
        )
        debug_index += 1
    return variables


def save_variable_map(variables: list[VariableEntry], *, identity: dict | None = None) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"variables": [asdict(item) for item in variables],
                    "program": identity, "forced": {}}, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def load_variable_map() -> list[VariableEntry]:
    path = _state_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return [VariableEntry(**item) for item in payload.get("variables", [])]
    except (OSError, ValueError, TypeError):
        return []


def load_debug_state() -> dict:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@contextmanager
def debug_operation():
    """Serialize runtime debug/build operations across CLI, MCP and the gateway."""
    path = _state_path().with_suffix(".lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + 120
    handle = path.open("a+b")
    if handle.tell() == 0:
        handle.write(b"0")
        handle.flush()
    while True:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError("PLC debug operation lock timed out")
            time.sleep(.025)
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def record_forces(forced: dict, released: list[str]) -> None:
    state = load_debug_state()
    known = state.setdefault("forced", {})
    known.update(forced)
    for name in released:
        known.pop(name, None)
    path = _state_path()
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(path)


def program_identity(source: Path, st_code: str) -> dict:
    return {"build_id": uuid.uuid4().hex, "source_hash": hashlib.sha256(st_code.encode()).hexdigest(),
            "runtime_hash": hashlib.md5(source.read_bytes()).hexdigest(),
            "source_file": str(source), "loaded_at": datetime.now(timezone.utc).isoformat()}


def serialized_debug(function):
    @wraps(function)
    def call(*args, **kwargs):
        with debug_operation():
            return function(*args, **kwargs)
    return call
