from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .models import Device
from .case_library import CaseLibrary
from .scheduler import Scheduler, TaskConflict, TaskNotFound
from .sqlite_repository import SqliteTaskRepository


class SubmitRequest(BaseModel):
    flow_ref: str
    platform: str = "any"
    required_capabilities: set[str] = Field(default_factory=set)
    labels: dict[str, str] = Field(default_factory=dict)


class ClaimRequest(BaseModel):
    device_id: str
    agent_id: str
    platform: str
    capabilities: set[str] = Field(default_factory=set)
    labels: dict[str, str] = Field(default_factory=dict)
    lease_ms: int = Field(default=60_000, ge=1_000, le=600_000)


class CompleteRequest(BaseModel):
    device_id: str
    passed: bool
    result: dict = Field(default_factory=dict)


class RenewRequest(BaseModel):
    device_id: str
    lease_ms: int = Field(default=60_000, ge=1_000, le=600_000)


class PublicationPreviewRequest(BaseModel):
    payload: dict
    target: dict


class PublicationCommitRequest(BaseModel):
    operation_id: str
    confirmation: str


def task_dict(task) -> dict:
    value = asdict(task)
    value["status"] = task.status.value
    value["required_capabilities"] = sorted(task.required_capabilities)
    return value


def create_app(database_path: Path | str | None = None, api_token: str | None = None) -> FastAPI:
    database = database_path or os.environ.get("DEVICE_LAB_DATABASE", "device-lab.db")
    expected_token = api_token if api_token is not None else os.environ.get("DEVICE_LAB_TOKEN", "")
    scheduler = Scheduler(SqliteTaskRepository(database))
    case_library = CaseLibrary(database)
    app = FastAPI(title="Device Test Lab", version="0.1.0")
    app.state.scheduler = scheduler
    app.state.case_library = case_library

    def authorize(authorization: str | None) -> None:
        if expected_token and authorization != f"Bearer {expected_token}":
            raise HTTPException(401, "invalid bearer token")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/v1/tasks")
    def list_tasks(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return [task_dict(task) for task in scheduler.repository.all()]

    @app.post("/api/v1/tasks", status_code=202)
    def submit(request: SubmitRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        return task_dict(scheduler.submit(request.flow_ref, request.platform, request.required_capabilities, request.labels))

    @app.get("/api/v1/tasks/{task_id}")
    def get_task(task_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return task_dict(scheduler.repository.get(task_id))
        except TaskNotFound as error:
            raise HTTPException(404, "task not found") from error

    @app.post("/api/v1/tasks/claim/next")
    def claim(request: ClaimRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        device = Device(request.device_id, request.agent_id, request.platform, frozenset(request.capabilities), request.labels)
        task = scheduler.claim(device, request.lease_ms)
        return task_dict(task) if task else None

    @app.post("/api/v1/tasks/{task_id}/renew")
    def renew(task_id: str, request: RenewRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return task_dict(scheduler.renew(task_id, request.device_id, request.lease_ms))
        except (TaskNotFound, TaskConflict) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/v1/tasks/{task_id}/complete")
    def complete(task_id: str, request: CompleteRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return task_dict(scheduler.complete(task_id, request.device_id, request.passed, request.result))
        except TaskNotFound as error:
            raise HTTPException(404, "task not found") from error
        except TaskConflict as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/v1/tasks/{task_id}/cancel")
    def cancel(task_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return task_dict(scheduler.cancel(task_id))
        except TaskNotFound as error:
            raise HTTPException(404, "task not found") from error

    @app.get("/api/v1/case-sets")
    def list_case_sets(authorization: str | None = Header(default=None)):
        authorize(authorization)
        return case_library.list_sets()

    @app.get("/api/v1/case-sets/{case_set_id}")
    def get_case_set(case_set_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return case_library.get_set(case_set_id)
        except LookupError as error:
            raise HTTPException(404, "case set not found") from error

    @app.post("/api/v1/case-publications/preview")
    def preview_publication(request: PublicationPreviewRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return case_library.preview(request.payload, request.target)
        except (ValueError, LookupError) as error:
            raise HTTPException(400, str(error)) from error

    @app.post("/api/v1/case-publications/commit")
    def commit_publication(request: PublicationCommitRequest, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return case_library.commit(request.operation_id, request.confirmation)
        except LookupError as error:
            raise HTTPException(404, "publication not found") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/v1/case-publications/{operation_id}/undo")
    def undo_publication(operation_id: str, authorization: str | None = Header(default=None)):
        authorize(authorization)
        try:
            return case_library.undo(operation_id)
        except LookupError as error:
            raise HTTPException(404, "publication not found") from error
        except ValueError as error:
            raise HTTPException(409, str(error)) from error

    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(static_dir / "index.html")

    return app


def run() -> None:
    import uvicorn

    uvicorn.run(create_app(), host=os.environ.get("DEVICE_LAB_HOST", "127.0.0.1"), port=int(os.environ.get("DEVICE_LAB_PORT", "8877")))

