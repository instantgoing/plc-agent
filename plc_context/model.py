"""Static project facts. Source files, never this index, are authoritative."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class SourceLocation:
    file: str
    line: int
    column: int
    end_line: int
    end_column: int


@dataclass(frozen=True)
class Diagnostic:
    file: str
    line: int
    column: int
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class PLCSourceFile:
    path: str
    indexed: bool
    complete: bool
    diagnostics: tuple[Diagnostic, ...] = ()
    unsupported_constructs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Variable:
    name: str
    type: str
    scope: str
    owner: str | None
    address: str | None
    initial_value: str | None
    location: SourceLocation
    constant: bool = False
    located: bool = False


@dataclass(frozen=True)
class POU:
    name: str
    kind: str
    location: SourceLocation
    variables: tuple[Variable, ...] = ()
    return_type: str | None = None


@dataclass(frozen=True)
class DataType:
    name: str
    declaration: str
    location: SourceLocation


@dataclass(frozen=True)
class Task:
    name: str
    interval: str | None
    priority: str | None
    location: SourceLocation


@dataclass(frozen=True)
class IOBinding:
    symbol: str
    address: str
    type: str
    direction: str
    owner: str | None
    location: SourceLocation


@dataclass(frozen=True)
class Reference:
    symbol: str
    owner: str | None
    type: str
    location: SourceLocation
    declaration_owner: str | None = None


@dataclass(frozen=True)
class UsageCandidate:
    name: str
    owner: str | None
    call: bool
    location: SourceLocation
    object: str | None = None


@dataclass(frozen=True)
class ParsedSource:
    source_file: PLCSourceFile
    pous: tuple[POU, ...] = ()
    globals: tuple[Variable, ...] = ()
    data_types: tuple[DataType, ...] = ()
    tasks: tuple[Task, ...] = ()
    usages: tuple[UsageCandidate, ...] = ()


@dataclass(frozen=True)
class PLCProjectSnapshot:
    project_root: str
    files: tuple[PLCSourceFile, ...] = ()
    pous: tuple[POU, ...] = ()
    globals: tuple[Variable, ...] = ()
    data_types: tuple[DataType, ...] = ()
    tasks: tuple[Task, ...] = ()
    io: tuple[IOBinding, ...] = ()
    references: tuple[Reference, ...] = ()
    tests: tuple[str, ...] = ()
    complete: bool = True
