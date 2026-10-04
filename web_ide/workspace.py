"""Workspace-local file access for the web editor."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path, PurePosixPath

VISIBLE_SUFFIXES = {".st", ".json", ".yaml", ".yml", ".toml", ".md"}
HIDDEN_DIRS = {".git", ".plc-agent", ".venv", ".venv-p3", "node_modules", "__pycache__", "smolagents"}


class WorkspaceError(ValueError):
    pass


class WorkspaceConflict(WorkspaceError):
    pass


class WorkspaceHiddenContents(WorkspaceConflict):
    def __init__(self, count: int):
        self.count = count
        super().__init__(f"folder contains {count} item(s) hidden from the file explorer")


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

    def item_path(self, relative: str, *, directory: bool | None = None) -> Path:
        if not isinstance(relative, str) or not relative or "\x00" in relative or "\\" in relative:
            raise WorkspaceError("invalid workspace path")
        parts = PurePosixPath(relative).parts
        if relative.startswith("/") or any(part in {"..", "."} or part in HIDDEN_DIRS or part.startswith(".") for part in parts):
            raise WorkspaceError("path is outside the visible workspace")
        current = self.root
        for part in parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceError("symlinks are not supported in the file explorer")
        path = current.resolve()
        if not path.is_relative_to(self.root):
            raise WorkspaceError("path is outside the visible workspace")
        if directory is False and path.suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("file type is not visible in the file explorer")
        return path

    def _parent(self, relative: str) -> Path:
        path = self.root if relative == "" else self.item_path(relative, directory=True)
        if not path.is_dir():
            raise FileNotFoundError(relative)
        return path

    @staticmethod
    def _name(name: str, *, file: bool) -> None:
        if (not isinstance(name, str) or not name or name != name.strip(" .")
                or name.startswith(".") or name in HIDDEN_DIRS
                or any(char in name for char in '\\/:*?"<>|\x00')
                or len(name) > 255):
            raise WorkspaceError("invalid file or folder name")
        if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL",
                                             *(f"COM{i}" for i in range(1, 10)),
                                             *(f"LPT{i}" for i in range(1, 10))}:
            raise WorkspaceError("reserved file or folder name")
        if file and Path(name).suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("file type is not visible in the file explorer")

    @staticmethod
    def _available(parent: Path, name: str, *, original: Path | None = None) -> bool:
        return not any(child.name.casefold() == name.casefold() and child != original
                       for child in parent.iterdir())

    def create(self, parent: str, name: str, kind: str) -> dict:
        if kind not in {"file", "folder"}:
            raise WorkspaceError("kind must be file or folder")
        directory = self._parent(parent)
        self._name(name, file=kind == "file")
        if not self._available(directory, name):
            raise WorkspaceConflict("an item with this name already exists")
        target = directory / name
        if kind == "file":
            with target.open("x", encoding="utf-8"):
                pass
        else:
            target.mkdir()
        return {"success": True, "kind": kind, "path": target.relative_to(self.root).as_posix()}

    def move(self, source: str, parent: str, name: str | None = None) -> dict:
        path = self.item_path(source)
        if not path.exists():
            raise FileNotFoundError(source)
        if not path.is_dir() and not path.is_file():
            raise WorkspaceError("unsupported workspace item")
        kind = "folder" if path.is_dir() else "file"
        if kind == "file" and path.suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("file type is not visible in the file explorer")
        directory = self._parent(parent)
        new_name = name if name is not None else path.name
        self._name(new_name, file=kind == "file")
        if path.is_dir() and (directory == path or directory.is_relative_to(path)):
            raise WorkspaceError("cannot move a folder into itself")
        target = directory / new_name
        if target == path:
            return {"success": True, "kind": kind, "source": source, "path": source}
        if not self._available(directory, new_name, original=path):
            raise WorkspaceConflict("an item with this name already exists")
        path.rename(target)
        return {"success": True, "kind": kind, "source": source,
                "path": target.relative_to(self.root).as_posix()}

    def copy(self, source: str, parent: str, name: str | None = None) -> dict:
        path = self.item_path(source)
        if not path.exists():
            raise FileNotFoundError(source)
        if not path.is_dir() and not path.is_file():
            raise WorkspaceError("unsupported workspace item")
        kind = "folder" if path.is_dir() else "file"
        if kind == "file" and path.suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("file type is not visible in the file explorer")
        directory = self._parent(parent)
        if path.is_dir() and (directory == path or directory.is_relative_to(path)):
            raise WorkspaceError("cannot copy a folder into itself")
        if name is None:
            stem, suffix = (path.stem, path.suffix) if kind == "file" else (path.name, "")
            name = path.name
            if not self._available(directory, name):
                for number in range(1, 1001):
                    candidate = f"{stem} copy{f' {number}' if number > 1 else ''}{suffix}"
                    if self._available(directory, candidate):
                        name = candidate
                        break
                else:
                    raise WorkspaceConflict("too many copies with the same name")
        self._name(name, file=kind == "file")
        if not self._available(directory, name):
            raise WorkspaceConflict("an item with this name already exists")
        target = directory / name
        created = False
        try:
            if kind == "file":
                with path.open("rb") as original, target.open("xb") as duplicate:
                    created = True
                    shutil.copyfileobj(original, duplicate)
            else:
                target.mkdir()
                created = True
                shutil.copytree(path, target, symlinks=True, dirs_exist_ok=True)
        except Exception:
            if created and target.is_dir():
                shutil.rmtree(target)
            elif created and target.exists():
                target.unlink()
            raise
        return {"success": True, "kind": kind, "source": source,
                "path": target.relative_to(self.root).as_posix()}

    def _hidden_count(self, path: Path) -> int:
        if not path.is_dir():
            return 0
        count = 0
        pending = [path]
        while pending:
            current = pending.pop()
            for child in current.iterdir():
                if child.name.startswith(".") or child.name in HIDDEN_DIRS or child.is_symlink():
                    count += 1
                elif child.is_dir():
                    pending.append(child)
                elif child.suffix.lower() not in VISIBLE_SUFFIXES:
                    count += 1
        return count

    def _trash_root(self) -> Path:
        root = self.root / ".plc-agent"
        trash = root / "trash"
        if root.is_symlink() or trash.is_symlink():
            raise WorkspaceError("trash path cannot be a symlink")
        trash.mkdir(parents=True, exist_ok=True)
        return trash

    def delete(self, relative: str, *, confirm_hidden: bool = False) -> dict:
        path = self.item_path(relative)
        if not path.exists():
            raise FileNotFoundError(relative)
        if not path.is_dir() and not path.is_file():
            raise WorkspaceError("unsupported workspace item")
        kind = "folder" if path.is_dir() else "file"
        if kind == "file" and path.suffix.lower() not in VISIBLE_SUFFIXES:
            raise WorkspaceError("file type is not visible in the file explorer")
        hidden_count = self._hidden_count(path)
        if hidden_count and not confirm_hidden:
            raise WorkspaceHiddenContents(hidden_count)
        token = uuid.uuid4().hex
        entry = self._trash_root() / token
        entry.mkdir()
        try:
            (entry / "manifest.json").write_text(json.dumps({"path": relative, "kind": kind}), encoding="utf-8")
            path.rename(entry / "item")
        except Exception:
            shutil.rmtree(entry)
            raise
        return {"success": True, "kind": kind, "path": relative, "undo_token": token}

    def restore(self, token: str) -> dict:
        if not isinstance(token, str) or len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
            raise WorkspaceError("invalid undo token")
        entry = self._trash_root() / token
        if entry.is_symlink() or (entry / "manifest.json").is_symlink() or (entry / "item").is_symlink():
            raise WorkspaceError("invalid undo entry")
        try:
            manifest = json.loads((entry / "manifest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise FileNotFoundError("undo token not found") from exc
        if not isinstance(manifest, dict) or manifest.get("kind") not in {"file", "folder"}:
            raise WorkspaceError("invalid undo entry")
        relative = manifest.get("path")
        target = self.item_path(relative)
        if not target.parent.is_dir():
            raise WorkspaceConflict("original parent folder no longer exists")
        if not self._available(target.parent, target.name):
            raise WorkspaceConflict("an item now exists at the original path")
        (entry / "item").rename(target)
        (entry / "manifest.json").unlink()
        entry.rmdir()
        return {"success": True, "kind": manifest["kind"], "path": relative}

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
                    if children or not any(child.iterdir()):
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
