"""Authenticated, versioned static-discovery results. Never uses the CVE report schema."""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.db.session import get_db
from app.models.agent_task import AgentTask
from app.models.discovery import DiscoveryEvidence, ScanObservation
from app.models.project import Project
from app.models.user import User
from app.services.discovery.candidate_store import CandidateStore
from app.services.discovery.evidence_store import EvidenceStore
from app.services.discovery.scan_ingest import ObservationStore
from app.services.discovery.store import RunStore, row_dict
from app.services.discovery.task_store import TaskStore
from app.services.discovery.coverage import coverage_summary

router = APIRouter()


async def authorized_task(
    task_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    task = await db.get(AgentTask, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    project = await db.get(Project, task.project_id)
    if task.created_by != current_user.id and (not project or project.owner_id != current_user.id):
        raise HTTPException(403, "Access denied")
    if not (task.agent_config or {}).get("discovery_v2", {}).get("enabled"):
        raise HTTPException(404, "Discovery v2 is not enabled for this task")
    return task


def get_run(task):
    run = RunStore().for_task(task.id)
    if not run:
        raise HTTPException(404, "Discovery is preparing its source snapshot")
    return run


def public_run(run):
    tasks = TaskStore().list(run["id"])
    stats = ObservationStore().stats(run["id"])
    manifest = {
        k: v for k, v in run["scan_manifest"].items() if k not in {"artifact_path", "records_path"}
    }
    return {
        "id": run["id"],
        "task_id": run["task_id"],
        "status": run["status"],
        "phase": run["phase"],
        "repo_snapshot_id": run["repo_snapshot_id"],
        "configuration_warnings": run["config"].get("configuration_warnings", []),
        "commit": run["snapshot"].get("commit"),
        "profile": run["profile"],
        "initial_snapshot": run["initial_snapshot"],
        "scan_manifest": manifest,
        "summary": {**run["summary"], **coverage_summary(run, tasks, stats)},
        "observation_stats": stats,
        "work_items": tasks,
        "ingest_errors": ObservationStore().errors(run["id"]),
    }


@router.get("/tasks/{task_id}")
async def detail(task=Depends(authorized_task)):
    return public_run(get_run(task))


@router.get("/tasks/{task_id}/candidates")
async def candidates(status: str | None = None, task=Depends(authorized_task)):
    return CandidateStore().list(get_run(task)["id"], status=status)


@router.get("/tasks/{task_id}/candidates/{candidate_id}/history")
async def candidate_history(candidate_id: str, task=Depends(authorized_task)):
    try:
        return CandidateStore().history(get_run(task)["id"], candidate_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/tasks/{task_id}/evidence/{evidence_id}")
async def evidence(evidence_id: str, task=Depends(authorized_task)):
    try:
        return EvidenceStore().evidence(get_run(task)["id"], evidence_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/tasks/{task_id}/observations")
async def observations(
    cursor: str | None = None,
    page_size: int = Query(100, ge=1, le=1000),
    severity: str | None = None,
    file_path: str | None = None,
    task=Depends(authorized_task),
):
    try:
        return ObservationStore().list_page(
            get_run(task)["id"],
            cursor=cursor,
            page_size=page_size,
            severity=severity,
            file_path=file_path,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/tasks/{task_id}/observations/{observation_id}")
async def observation(
    observation_id: str,
    include_raw: bool = True,
    include_trace: bool = True,
    task=Depends(authorized_task),
):
    try:
        return ObservationStore().observation(
            get_run(task)["id"],
            observation_id,
            include_raw=include_raw,
            include_trace=include_trace,
        )
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/tasks/{task_id}/artifact")
async def artifact(task=Depends(authorized_task)):
    from pathlib import Path

    run = get_run(task)
    path = run["scan_manifest"].get("artifact_path")
    if not path or not Path(path).is_file():
        raise HTTPException(404, "Raw scan artifact unavailable; completeness cannot be inferred")
    return FileResponse(path, media_type="application/json", filename=f"{task.id}-semgrep.json")


@router.get("/tasks/{task_id}/export")
async def export(task=Depends(authorized_task)):
    run = get_run(task)
    header = public_run(run)

    def records():
        yield json.dumps({"type": "discovery_run", "data": header}, ensure_ascii=False) + "\n"
        with RunStore().sf() as db:
            for model, kind in [
                (DiscoveryEvidence, "evidence"),
                (ScanObservation, "scan_observation"),
            ]:
                for row in db.scalars(
                    select(model).where(model.run_id == run["id"]).execution_options(yield_per=500)
                ):
                    yield (
                        json.dumps({"type": kind, "data": row_dict(row)}, ensure_ascii=False) + "\n"
                    )
            candidate_store = CandidateStore()
            for candidate in candidate_store.list(run["id"]):
                for version in candidate_store.history(run["id"], candidate["candidate_id"]):
                    yield (
                        json.dumps(
                            {"type": "candidate_version", "data": version}, ensure_ascii=False
                        )
                        + "\n"
                    )

    return StreamingResponse(
        records(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="discovery-{task.id}.jsonl"'},
    )


@router.post("/tasks/{task_id}/resume")
async def resume(
    background_tasks: BackgroundTasks,
    task=Depends(authorized_task),
    db: AsyncSession = Depends(get_db),
):
    from app.api.v1.endpoints.agent_tasks import _schedule_agent_task
    from app.services.agent.task_executor import clear_task_cancellation

    run = get_run(task)
    if run["lease_until"] > time.time():
        raise HTTPException(409, "Discovery is already running")
    if task.status in {"pending", "initializing", "planning", "indexing", "analyzing"}:
        raise HTTPException(409, "This task is already queued or preparing")
    if task.status == "completed":
        raise HTTPException(409, "Completed discovery has no deferred work to resume")
    summary = coverage_summary(run, TaskStore().list(run["id"]), ObservationStore().stats(run["id"]))
    if not summary["can_resume"]:
        raise HTTPException(409, "没有可继续的工作；请补充缺失上下文或调整范围后创建新任务。")
    task.status, task.error_message, task.completed_at = "pending", None, None
    clear_task_cancellation(task.id)
    await db.commit()
    await _schedule_agent_task(background_tasks, task.id)
    return {"task_id": task.id, "status": "pending", "run_id": run["id"]}
