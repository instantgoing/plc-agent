"""Run the localhost gateway: python -m web_ide --workspace ."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

import uvicorn

from web_ide.app import create_app
from agent.env import load_project_env
from agent.codex_client import CodexInfrastructureError
from web_ide.connectivity import ensure_local_proxy


def serve(workspace: Path, port: int = 8765, *, dev: bool = False) -> int:
    workspace = workspace.resolve(strict=True)
    os.chdir(workspace)
    frontend = Path(__file__).resolve().parents[1] / "frontend"
    load_project_env(frontend.parent)
    # The per-turn MCP process may read the gateway's temporary selected trace.
    os.environ["PLC_DEBUG_GATEWAY_URL"] = f"http://127.0.0.1:{port}"
    try:
        print(ensure_local_proxy(), flush=True)
    except CodexInfrastructureError as exc:
        # The workspace and editor remain usable while the Agent is offline.
        print(f"Codex connection: {exc}", flush=True)
    child = None
    if dev:
        executable = shutil.which("npm.cmd" if os.name == "nt" else "npm")
        if not executable or not (frontend / "node_modules").is_dir():
            raise RuntimeError("install frontend dependencies with npm install before --dev")
        child = subprocess.Popen([executable, "run", "dev"], cwd=frontend)
        print("Vite frontend: http://127.0.0.1:5173", flush=True)
    print(f"PLC Web IDE gateway: http://127.0.0.1:{port}", flush=True)
    try:
        uvicorn.run(create_app(workspace), host="127.0.0.1", port=port)
    finally:
        if child is not None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dev", action="store_true")
    args = parser.parse_args()
    serve(args.workspace, args.port, dev=args.dev)


if __name__ == "__main__":
    main()
