"""Workspace-scoped, disposable ST index with per-file refresh."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import (
    IOBinding, PLCProjectSnapshot, PLCSourceFile, ParsedSource, Reference,
)
from .st_adapter import parse_st


_EXCLUDED = {".git", ".plc-agent", ".venv", "smolagents", "__pycache__"}


def _record(value: Any) -> dict[str, Any]:
    data = asdict(value)
    location = data.pop("location", None)
    if location:
        data.update(location)
    return data


def _pou_record(pou: Any) -> dict[str, Any]:
    data = _record(pou)
    data.pop("variables")
    variables = [_record(item) for item in pou.variables]
    for scope, key in (("input", "inputs"), ("output", "outputs"),
                       ("inout", "inouts"), ("local", "locals"),
                       ("external", "externals"), ("temporary", "temporaries"),
                       ("constant", "constants")):
        data[key] = [item for item in variables if item["scope"] == scope]
    return data


def _data_type_record(data_type: Any) -> dict[str, Any]:
    data = _record(data_type)
    data.pop("declaration")
    return data


class ProjectIndexer:
    """Re-stat on query; only changed ST files are read and parsed again."""

    def __init__(self, project_root: str | Path):
        self.root = Path(project_root).resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("project_root must be a directory")
        self._cache: dict[str, tuple[tuple[int, int], ParsedSource]] = {}
        self._snapshot: PLCProjectSnapshot | None = None
        self.parse_count = 0

    def _paths(self, pattern: str) -> list[Path]:
        return sorted(
            path for path in self.root.rglob(pattern)
            if path.is_file() and path.resolve().is_relative_to(self.root)
            and not any(part in _EXCLUDED or part.startswith(".venv")
                        for part in path.relative_to(self.root).parts)
        )

    def snapshot(self) -> PLCProjectSnapshot:
        paths = self._paths("*.st")
        seen: set[str] = set()
        changed = self._snapshot is None
        for path in paths:
            relative = path.relative_to(self.root).as_posix()
            seen.add(relative)
            signature = (-1, -1)
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if relative in self._cache and self._cache[relative][0] == signature:
                    continue
                source = path.read_bytes()
                parsed = parse_st(source, relative)
            except Exception as exc:
                from .model import Diagnostic
                parsed = ParsedSource(PLCSourceFile(relative, False, False, (
                    Diagnostic(relative, 1, 1, f"cannot index file: {type(exc).__name__}: {exc}"),
                )))
            self._cache[relative] = (signature, parsed)
            self.parse_count += 1
            changed = True
        if seen != set(self._cache):
            changed = True
            for missing in set(self._cache) - seen:
                del self._cache[missing]
        tests = tuple(path.relative_to(self.root).as_posix() for path in self._paths("*.tests.json"))
        if self._snapshot is not None and not changed and tests == self._snapshot.tests:
            return self._snapshot
        parsed_files = [entry[1] for _, entry in sorted(self._cache.items())]
        files = tuple(item.source_file for item in parsed_files)
        pous = tuple(pou for item in parsed_files for pou in item.pous)
        globals_ = tuple(var for item in parsed_files for var in item.globals)
        data_types = tuple(dtype for item in parsed_files for dtype in item.data_types)
        tasks = tuple(task for item in parsed_files for task in item.tasks)
        all_variables = (*globals_, *(var for pou in pous for var in pou.variables))
        io = tuple(
            IOBinding(var.name, var.address, var.type,
                      "input" if var.address.upper().startswith("%I") else
                      "output" if var.address.upper().startswith("%Q") else "memory",
                      var.owner, var.location)
            for var in all_variables if var.address
        )
        references = self._resolve_references(parsed_files, pous, globals_)
        self._snapshot = PLCProjectSnapshot(
            str(self.root), files, pous, globals_, data_types, tasks, io,
            references, tests, all(item.complete for item in files),
        )
        return self._snapshot

    @staticmethod
    def _resolve_references(parsed_files: list[ParsedSource], pous: tuple,
                            globals_: tuple) -> tuple[Reference, ...]:
        pou_names = {pou.name.casefold(): pou.name for pou in pous}
        global_names = {var.name.casefold(): var.name for var in globals_}
        local_names = {
            pou.name.casefold(): {var.name.casefold(): var.name for var in pou.variables}
            for pou in pous
        }
        local_types = {
            pou.name.casefold(): {var.name.casefold(): var.type for var in pou.variables}
            for pou in pous
        }
        pou_variables = {
            pou.name.casefold(): {var.name.casefold(): var.name for var in pou.variables}
            for pou in pous
        }
        refs: list[Reference] = []
        for item in parsed_files:
            for use in item.usages:
                key = use.name.casefold()
                owner_key = (use.owner or "").casefold()
                declaration_owner = None
                if use.object:
                    instance_type = local_types.get(owner_key, {}).get(use.object.casefold(), "")
                    declaration_owner = pou_names.get(instance_type.casefold())
                    target = pou_variables.get(instance_type.casefold(), {}).get(key)
                    kind = "member"
                elif use.call:
                    target = pou_names.get(key)
                    if not target:
                        target = pou_names.get(local_types.get(owner_key, {}).get(key, "").casefold())
                    kind = "call"
                elif key in local_names.get(owner_key, {}):
                    target = local_names[owner_key][key]
                    kind = "variable"
                    declaration_owner = use.owner
                else:
                    target = global_names.get(key)
                    kind = "global"
                if target:
                    refs.append(Reference(target, use.owner, kind, use.location,
                                          declaration_owner))
        return tuple(refs)

    def project_context(self, detail: str = "summary", *, limit: int = 100,
                        offset: int = 0) -> dict[str, Any]:
        snapshot = self.snapshot()
        if detail == "summary":
            return {"success": True, "project_root": snapshot.project_root,
                    "complete": snapshot.complete, "files": len(snapshot.files),
                    "pous": len(snapshot.pous), "globals": len(snapshot.globals),
                    "data_types": len(snapshot.data_types), "tasks": len(snapshot.tasks),
                    "io_inputs": sum(item.direction == "input" for item in snapshot.io),
                    "io_outputs": sum(item.direction == "output" for item in snapshot.io),
                    "references": len(snapshot.references), "tests": len(snapshot.tests),
                    "incomplete_files": [item.path for item in snapshot.files if not item.complete]}
        if detail == "io":
            page = snapshot.io[offset:offset + limit]
            return {"success": True, "complete": snapshot.complete,
                    "total": len(snapshot.io), "offset": offset, "io": {
                "inputs": [_record(item) for item in page if item.direction == "input"],
                "outputs": [_record(item) for item in page if item.direction == "output"],
                "memory": [_record(item) for item in page if item.direction == "memory"],
            }}
        sections = {
            "files": (snapshot.files, _record),
            "pous": (snapshot.pous, _pou_record),
            "globals": (snapshot.globals, _record),
            "data_types": (snapshot.data_types, _data_type_record),
            "tasks": (snapshot.tasks, _record),
            "references": (snapshot.references, _record),
            "tests": (snapshot.tests, str),
        }
        if detail not in sections:
            return {"success": False, "error": {"type": "invalid_argument", "message": "unsupported detail"}}
        values, serialize = sections[detail]
        return {"success": True, "complete": snapshot.complete, "detail": detail,
                "total": len(values), "offset": offset,
                "items": [serialize(item) for item in values[offset:offset + limit]]}

    def find_symbol(self, query: str, *, match: str = "exact", limit: int = 100) -> dict[str, Any]:
        if not query or match not in {"exact", "prefix", "substring"}:
            return {"success": False, "matches": [], "error": {"type": "invalid_argument", "message": "query and match are required"}}
        snapshot = self.snapshot()
        symbols = self._matching_symbols(snapshot, query, match)
        return {"success": True, "complete": snapshot.complete, "query": query,
                "match": match, "total": len(symbols), "matches": symbols[:limit]}

    @staticmethod
    def _matching_symbols(snapshot: PLCProjectSnapshot, query: str,
                          match: str) -> list[dict[str, Any]]:
        needle = query.casefold()

        def matches(value: str) -> bool:
            key = value.casefold()
            return key == needle if match == "exact" else key.startswith(needle) if match == "prefix" else needle in key

        symbols = [
            {**_pou_record(pou), "kind": pou.kind} for pou in snapshot.pous
            if matches(pou.name)
        ]
        symbols += [
            {**_record(var), "kind": "variable"} for var in
            (*snapshot.globals, *(var for pou in snapshot.pous for var in pou.variables))
            if (matches(var.name)
                or ("." in query and var.owner and matches(f"{var.owner}.{var.name}"))
                or (var.address and matches(var.address)))
        ]
        symbols += [{**_data_type_record(item), "kind": "data_type"} for item in snapshot.data_types if matches(item.name)]
        symbols += [{**_record(item), "kind": "task"} for item in snapshot.tasks if matches(item.name)]
        return symbols

    def find_references(self, symbol: str, *, limit: int = 100) -> dict[str, Any]:
        snapshot = self.snapshot()
        declarations = self._matching_symbols(snapshot, symbol, "exact")
        qualified_owner = symbol.rsplit(".", 1)[0].casefold() if "." in symbol and not symbol.startswith("%") else None
        names = {item["name"].casefold() for item in declarations}
        address_owners = {
            (item["name"].casefold(), (item.get("owner") or "").casefold())
            for item in declarations
        } if symbol.startswith("%") else None
        refs = [_record(item) for item in snapshot.references
                if item.symbol.casefold() in names and
                (address_owners is None or
                 (item.symbol.casefold(), (item.declaration_owner or "").casefold()) in address_owners) and
                (qualified_owner is None or (item.declaration_owner or "").casefold() == qualified_owner)]
        return {"success": True, "complete": snapshot.complete, "symbol": symbol,
                "declarations": declarations, "total": len(refs), "references": refs[:limit]}
