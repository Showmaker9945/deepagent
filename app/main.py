from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.agents import DecisionAgentRuntime
from app.config import settings
from app.manager import RunManager
from app.schemas import ClarificationRequest, FeedbackRequest, RunCreateRequest
from app.storage import Storage


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    storage = Storage(settings.sqlite_db_path)
    storage.init_db()
    manager = RunManager(settings, storage, DecisionAgentRuntime(settings))
    app.state.storage = storage
    app.state.manager = manager
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "app_name": settings.app_name,
            "default_user_id": settings.default_user_id,
        },
    )


@app.post("/api/runs")
async def create_run(payload: RunCreateRequest, background_tasks: BackgroundTasks, request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    run_id = manager.start_run(payload)
    background_tasks.add_task(manager.process_run, run_id)
    return JSONResponse({"run_id": run_id})


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request) -> JSONResponse:
    storage: Storage = request.app.state.storage
    envelope = storage.get_run_envelope(run_id)
    if not envelope:
        raise HTTPException(status_code=404, detail="Run not found.")
    return JSONResponse(envelope.model_dump(mode="json"))


@app.post("/api/runs/{run_id}/clarifications")
async def submit_clarification(
    run_id: str,
    payload: ClarificationRequest,
    background_tasks: BackgroundTasks,
    request: Request,
) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    storage: Storage = request.app.state.storage
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status != "needs_clarification":
        raise HTTPException(status_code=409, detail="Run is not waiting for clarification.")
    if not manager.submit_clarification(run_id, payload.answer):
        raise HTTPException(status_code=404, detail="Run not found.")
    background_tasks.add_task(manager.process_run, run_id)
    return JSONResponse({"run_id": run_id, "status": "queued"})


@app.post("/api/runs/{run_id}/feedback")
async def submit_feedback(run_id: str, payload: FeedbackRequest, request: Request) -> JSONResponse:
    manager: RunManager = request.app.state.manager
    storage: Storage = request.app.state.storage
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found.")
    if run.status != "completed":
        raise HTTPException(status_code=409, detail="Feedback is only available after a completed run.")
    manager.submit_feedback(run_id, payload)
    return JSONResponse({"ok": True})


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str, request: Request) -> StreamingResponse:
    storage: Storage = request.app.state.storage
    if not storage.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found.")

    async def event_generator():
        last_event_id = int(request.headers.get("last-event-id", "0") or 0)
        terminal = {"completed", "failed"}
        while True:
            if await request.is_disconnected():
                break

            events = storage.list_events(run_id, after_id=last_event_id)
            for event in events:
                last_event_id = event.id
                yield f"id: {event.id}\n"
                yield f"event: {event.event_type}\n"
                yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"

            run = storage.get_run(run_id)
            if run and run.status in terminal and not events:
                break

            await asyncio.sleep(0.7)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True})
