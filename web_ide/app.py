"""Local HTTP/WebSocket gateway. No browser request reaches runtime internals."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel

from agent.env import load_project_env
from plc_tools import get_plc_status
from web_ide.service import Gateway
from web_ide.workspace import WorkspaceConflict, WorkspaceError


class SaveFile(BaseModel):
    path: str
    content: str
    expected_version: str


class Message(BaseModel):
    message: str


class ForceRequest(BaseModel):
    variables: dict[str, bool | int | float | str]
    release: list[str] = []


class Names(BaseModel):
    variables: list[str]


class FileRequest(BaseModel):
    file: str


class ResumeRequest(BaseModel):
    thread_id: str


class DebugSubscription(BaseModel):
    consumer: str
    variables: list[str]


class DebugConfig(BaseModel):
    interval_ms: int = 250


class TraceRequest(BaseModel):
    action: str = "start"
    variables: list[str] = []
    sample_interval_ms: int = 100


def create_app(workspace: str | Path) -> FastAPI:
    load_project_env(Path(__file__).resolve().parents[1])
    gateway = Gateway(workspace)
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        gateway.attach_loop(asyncio.get_running_loop())
        async def watch_workspace() -> None:
            while True:
                await asyncio.sleep(1)
                if not gateway.sessions()["active"]:
                    await asyncio.to_thread(gateway.scan_changes)
        watcher = asyncio.create_task(watch_workspace())
        async def monitor_runtime():
            while True:
                began = asyncio.get_running_loop().time()
                if gateway.debug.subscriptions or gateway.debug.trace.state == "recording":
                    try:
                        await asyncio.to_thread(gateway.debug.poll)
                    except Exception as exc:
                        gateway._publish({"type": "debug.error", "message": str(exc)})
                interval = gateway.debug.interval_ms
                if gateway.debug.trace.state == "recording":
                    interval = min(interval, gateway.debug.trace.interval_ms)
                elapsed = asyncio.get_running_loop().time() - began
                await asyncio.sleep(max(.01, interval / 1000 - elapsed))
        monitor = asyncio.create_task(monitor_runtime())
        try:
            yield
        finally:
            watcher.cancel()
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
            with suppress(asyncio.CancelledError):
                await monitor
            await asyncio.to_thread(gateway.shutdown)
    app = FastAPI(title="PLC-Agent Web IDE", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
    app.state.gateway = gateway

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse(status_code=403, content={"detail": {"type": "origin_rejected", "message": "local origin required"}})
        return await call_next(request)

    def file_error(exc: Exception) -> HTTPException:
        if isinstance(exc, WorkspaceConflict):
            return HTTPException(409, {"type": "workspace_conflict", "message": str(exc)})
        if isinstance(exc, FileNotFoundError):
            return HTTPException(404, {"type": "file_not_found", "message": str(exc)})
        return HTTPException(400, {"type": "workspace_error", "message": str(exc)})

    @app.get("/api/health")
    async def health() -> dict:
        codex, runtime = await asyncio.gather(
            asyncio.to_thread(gateway.codex_status), asyncio.to_thread(get_plc_status))
        project = gateway.plc_call("project_context", "summary")
        return {"workspace": str(gateway.workspace.root), "codex": codex,
                "mcp": "ready" if project.get("success") else "error",
                "runtime": (runtime.actual_status or "error").lower(),
                "project": "ready" if project.get("success") else "error",
                "environment": gateway.environment, "agent_active": gateway.sessions()["active"]}

    @app.get("/api/workspace/status")
    def workspace_status() -> dict:
        return {"workspace": str(gateway.workspace.root), "read_only": False}

    @app.get("/api/workspace/tree")
    def tree() -> dict:
        return gateway.workspace.tree()

    @app.get("/api/workspace/file")
    def read_file(path: str) -> dict:
        try:
            return gateway.workspace.read(path)
        except (WorkspaceError, FileNotFoundError) as exc:
            raise file_error(exc) from exc

    @app.put("/api/workspace/file")
    def save_file(body: SaveFile) -> dict:
        try:
            saved = gateway.workspace.save(body.path, body.content, body.expected_version)
            gateway.scan_changes("user")
            return saved
        except (WorkspaceError, FileNotFoundError) as exc:
            raise file_error(exc) from exc

    @app.get("/api/project/context")
    def context(detail: str = "summary", limit: int = 500, offset: int = 0) -> dict:
        return gateway.plc_call("project_context", detail, limit, offset)

    @app.get("/api/project/symbol")
    def symbol(query: str, match: str = "exact") -> dict:
        return gateway.plc_call("find_symbol", query, match)

    @app.get("/api/project/references")
    def references(symbol: str) -> dict:
        return gateway.plc_call("find_references", symbol)

    @app.post("/api/plc/check")
    async def check(body: FileRequest) -> dict:
        return await asyncio.to_thread(gateway.plc_call, "check", body.file)

    @app.post("/api/plc/compile")
    async def compile_file(body: FileRequest) -> dict:
        return await asyncio.to_thread(gateway.plc_call, "compile", body.file)

    @app.get("/api/plc/status")
    async def plc_status() -> dict:
        result = await asyncio.to_thread(get_plc_status)
        return {"success": result.success, "state": (result.actual_status or "error").lower(),
                "error": result.tool_error, "environment": gateway.environment}

    @app.post("/api/plc/start")
    async def start_plc() -> dict:
        return await asyncio.to_thread(gateway.plc_call, "start")

    @app.post("/api/plc/stop")
    async def stop_plc() -> dict:
        return await asyncio.to_thread(gateway.plc_call, "stop")

    @app.post("/api/plc/read")
    async def read_variables(body: Names) -> dict:
        return await asyncio.to_thread(gateway.plc_call, "read", body.variables)

    @app.post("/api/plc/force")
    async def force_variable(body: ForceRequest) -> dict:
        if gateway.environment != "simulation":
            raise HTTPException(403, {"type": "safety_boundary", "message": "force is available only for the test Runtime"})
        return await asyncio.to_thread(gateway.plc_call, "force", body.variables, body.release)

    @app.post("/api/plc/verify")
    async def verify(body: FileRequest) -> dict:
        return await asyncio.to_thread(gateway.plc_call, "verify", body.file)

    @app.post("/api/plc/unforce")
    async def unforce(body: Names) -> dict:
        if gateway.environment != "simulation":
            raise HTTPException(403, "unforce is available only for the test Runtime")
        return await asyncio.to_thread(gateway.plc_call, "unforce", body.variables)

    @app.get("/api/debug/state")
    def debug_state():
        return gateway.debug.snapshot()

    @app.get("/api/debug/variables")
    def debug_variables(query: str = ""):
        # P3 search is authoritative for declarations; generated instance fields
        # additionally come from the successful build's runtime debug map.
        matches = gateway.plc_call("find_symbol", query, "substring") if query else {}
        return {"variables": [v for v in gateway.debug.catalog() if not query or
                              query.casefold() in (v["id"] + " " + v["owner"] + "." + v["name"] + " " + (v["address"] or "")).casefold()],
                "symbols": matches.get("matches", [])}

    @app.post("/api/debug/subscribe")
    def debug_subscribe(body: DebugSubscription):
        try:
            return gateway.debug.subscribe(body.consumer, body.variables)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/debug/config")
    def debug_config(body: DebugConfig):
        try:
            gateway.debug.configure(body.interval_ms)
            return gateway.debug.snapshot()
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/debug/trace")
    def trace_control(body: TraceRequest):
        try:
            return gateway.debug.start_trace(body.variables, body.sample_interval_ms) if body.action == "start" else gateway.debug.trace_action(body.action)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/debug/trace")
    def trace_data(start_ms: int = 0, end_ms: int | None = None, summary: bool = False):
        with gateway.debug._lock:
            result = gateway.debug.trace.summary() if summary else gateway.debug.trace.data(start_ms, end_ms)
            return {"workspace": str(gateway.workspace.root), **result}

    @app.get("/api/debug/ladder")
    def ladder(file: str):
        from plc_context.ladder import ladder_ir
        try:
            data = gateway.workspace.read(file)
            if not file.lower().endswith(".st"):
                raise WorkspaceError("ladder requires an ST file")
            return ladder_ir(data["content"].encode(), file)
        except (WorkspaceError, FileNotFoundError) as exc:
            raise file_error(exc) from exc

    @app.get("/api/agent/sessions")
    def sessions() -> dict:
        return gateway.sessions()

    @app.post("/api/agent/sessions/new")
    def new_session() -> dict:
        try:
            return gateway.new_session()
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/agent/sessions/resume")
    def resume_session(body: ResumeRequest) -> dict:
        try:
            return gateway.resume_session(body.thread_id)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/agent/message")
    def agent_message(body: Message) -> dict:
        if not body.message.strip():
            raise HTTPException(400, "message is empty")
        try:
            gateway.run_agent(body.message.strip())
            return {"accepted": True}
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/api/agent/interrupt")
    def interrupt() -> dict:
        return {"interrupted": gateway.interrupt()}

    @app.get("/api/agent/events")
    def events(after: int = 0) -> dict:
        history, gap = gateway.event_history(after)
        return {"events": history, "history_truncated": gap, "active": gateway.sessions()["active"]}

    @app.get("/api/changes")
    def changes() -> dict:
        return {"files": gateway.changes()}

    @app.get("/api/changes/diff")
    def diff(path: str) -> dict:
        try:
            return gateway.diff(path)
        except (KeyError, WorkspaceError) as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.websocket("/ws/events")
    async def websocket(websocket: WebSocket, after: int = 0) -> None:
        origin = websocket.headers.get("origin")
        if origin and urlparse(origin).hostname not in {"127.0.0.1", "localhost", "testserver"}:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        queue, history, gap = gateway.subscribe(after)
        try:
            if gap:
                await websocket.send_json({"type": "history.truncated", "message": "Earlier Agent activity is no longer available; the current thread remains resumable."})
            for event in history:
                await websocket.send_json(event)
            await websocket.send_json({"type": "connection.ready", "active": gateway.sessions()["active"],
                                       "thread_id": gateway.sessions()["current_thread_id"]})
            await websocket.send_json(gateway.debug.snapshot())
            while True:
                incoming = asyncio.create_task(websocket.receive_text())
                outgoing = asyncio.create_task(queue.get())
                done, pending = await asyncio.wait({incoming, outgoing}, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                for task in pending:
                    with suppress(asyncio.CancelledError):
                        await task
                if incoming in done:
                    incoming.result()  # raises WebSocketDisconnect on browser close
                if outgoing in done:
                    await websocket.send_json(outgoing.result())
        except WebSocketDisconnect:
            pass
        finally:
            gateway.unsubscribe(queue)

    dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
    if dist.is_dir():
        @app.get("/{path:path}")
        def frontend(path: str):
            target = (dist / path).resolve()
            if target.is_relative_to(dist) and target.is_file():
                return FileResponse(target)
            return FileResponse(dist / "index.html")
    return app
