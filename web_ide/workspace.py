"""Workspace-local file access for the web editor."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath

VISIBLE_SUFFIXES = {".st", ".json", ".yaml", ".yml", ".toml", ".md"}
HIDDEN_DIRS = {".git", ".plc-agent", ".venv", ".venv-p3", "node_modules", "__pycache__", "smolagents"}


class WorkspaceError(ValueError):
    pass


class WorkspaceConflict(WorkspaceError):
    pass


class Workspace:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir():
            raise WorkspaceError("workspace must be a directory")

    def path(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative or "\\" in relative:
            raise WorkspaceError("invalid workspace path")
        parts = PurePosixPath(relative).parts
        if relative.startswith("/") or any(part in {"..", "."} or part in HIDDEN_DIRS or part.startswith(".") for part in parts):
            raise WorkspaceError("path is outside the visible workspace")
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root) or path.suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("path is outside the visible workspace")
        if any(part in HIDDEN_DIRS or part.startswith(".") for part in path.relative_to(self.root).parts):
            raise WorkspaceError("path is outside the visible workspace")
        return path

    @staticmethod
    def version(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    def read(self, relative: str) -> dict:
        path = self.path(relative)
        if not path.is_file():
            raise FileNotFoundError(relative)
        content = path.read_text(encoding="utf-8")
        return {"path": path.relative_to(self.root).as_posix(), "content": content,
                "version": self.version(content)}

    def save(self, relative: str, content: str, expected_version: str) -> dict:
        path = self.path(relative)
        if not path.is_file():
            raise FileNotFoundError(relative)
        if not isinstance(content, str) or not isinstance(expected_version, str):
            raise WorkspaceError("content and expected_version must be strings")
        current = path.read_text(encoding="utf-8")
        if self.version(current) != expected_version:
            raise WorkspaceConflict("file changed externally; compare and reload before saving")
        path.write_text(content, encoding="utf-8")
        return {"success": True, "path": path.relative_to(self.root).as_posix(),
                "version": self.version(content)}

    def tree(self) -> dict:
        def visit(directory: Path) -> list[dict]:
            nodes = []
            for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
                if child.name in HIDDEN_DIRS or child.name.startswith(".") or child.is_symlink():
                    continue
                if child.is_dir():
                    children = visit(child)
                    if children:
                        nodes.append({"name": child.name, "path": child.relative_to(self.root).as_posix(),
                                      "kind": "folder", "children": children})
                elif child.suffix.lower() in VISIBLE_SUFFIXES:
                    nodes.append({"name": child.name, "path": child.relative_to(self.root).as_posix(),
                                  "kind": "file"})
            return nodes
        return {"workspace": str(self.root), "nodes": visit(self.root)}

    def snapshot(self) -> dict[str, str]:
        result = {}
        def walk(directory: Path) -> None:
            for child in directory.iterdir():
                if child.name in HIDDEN_DIRS or child.name.startswith(".") or child.is_symlink():
                    continue
                if child.is_dir():
                    walk(child)
                elif child.suffix.lower() in VISIBLE_SUFFIXES:
                    result[child.relative_to(self.root).as_posix()] = child.read_text(encoding="utf-8")
        walk(self.root)
        return result
