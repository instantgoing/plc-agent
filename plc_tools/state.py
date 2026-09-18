"""Small persisted hand-off between compile and M3 variable tools."""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class VariableEntry:
    name: str
    type: str
    location: str
    index: int


def _state_path() -> Path:
    configured = os.environ.get("PLC_STATE_FILE")
    return Path(configured).resolve() if configured else Path(".plc-agent/state.json").resolve()


def parse_variable_map(raw_csv: str, st_code: str) -> list[VariableEntry]:
    locations = {
        match.group(1).lower(): match.group(2).upper()
        for match in re.finditer(
            r"\b([A-Za-z_][A-Za-z0-9_]*)\s+AT\s+(%[IQM][A-Z]*[0-9][0-9.]*)",
            st_code,
            re.IGNORECASE,
        )
    }
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
        variables.append(
            VariableEntry(name, variable_type.upper(), locations.get(name, ""), debug_index)
        )
        debug_index += 1
    return variables


def save_variable_map(variables: list[VariableEntry]) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"variables": [asdict(item) for item in variables]}, indent=2),
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
