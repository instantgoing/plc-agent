"""Build the pinned MatIEC-era OpenPLC base image on any Docker host."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


OPENPLC_REPOSITORY = "https://github.com/Autonomy-Logic/openplc-runtime.git"
OPENPLC_COMMIT = "f1a70e91e4d633db3653d1097f9d42e487970a6d"
BASE_IMAGE = "plc-agent-openplc:m2-base"
LOCAL_DEBIAN_BASE = (
    "python:3.12-slim@sha256:"
    "78387bc3881b8273120a12ebe6c1ab22b018ccc2c9adf565ae1ac9b536e184ea"
)


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def main() -> int:
    for executable in ("git", "docker"):
        if shutil.which(executable) is None:
            raise SystemExit(f"required executable not found: {executable}")

    with tempfile.TemporaryDirectory(prefix="plc-agent-openplc-") as directory:
        source = Path(directory) / "openplc-runtime"
        source.mkdir()
        run("git", "init", cwd=source)
        run("git", "config", "core.autocrlf", "false", cwd=source)
        run("git", "remote", "add", "origin", OPENPLC_REPOSITORY, cwd=source)
        run("git", "fetch", "--depth", "1", "origin", OPENPLC_COMMIT, cwd=source)
        run("git", "checkout", "--detach", "FETCH_HEAD", cwd=source)
        run("git", "submodule", "update", "--init", "--recursive", cwd=source)
        # Dockerfile's syntax frontend and debian:bookworm-slim both require a
        # Docker Hub authorization round trip. The development machine already
        # carries this pinned Debian-slim Python image. M1 deliberately uses the
        # same image family for offline-friendly builds. OpenPLC source remains
        # pinned and otherwise unchanged.
        dockerfile = source / "Dockerfile"
        contents = dockerfile.read_text(encoding="utf-8")
        contents = contents.replace("# syntax=docker/dockerfile:1\n\n", "", 1)
        contents = contents.replace(
            "FROM debian:bookworm-slim", f"FROM {LOCAL_DEBIAN_BASE}", 1
        )
        dockerfile.write_text(contents, encoding="utf-8", newline="\n")
        run(
            "docker",
            "build",
            "--platform=linux/amd64",
            "--tag",
            BASE_IMAGE,
            ".",
            cwd=source,
        )
    print(f"built {BASE_IMAGE} from OpenPLC {OPENPLC_COMMIT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
