from __future__ import annotations

import hashlib
import json
import time

from sqlalchemy import select, update

from app.db.session import get_sync_session_factory
from app.models.discovery import DiscoveryRun, DiscoveryTask


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def row_dict(row) -> dict:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def require_attempt(db, task_id: str, attempt_id: str) -> DiscoveryTask:
    # A row lock fences concurrent completion and lease reclamation on PostgreSQL.
    task = db.scalar(select(DiscoveryTask).where(DiscoveryTask.id == task_id).with_for_update())
    if (
        not task
        or task.status != "running"
        or task.attempt_id != attempt_id
        or task.lease_until < time.time()
    ):
        raise ValueError("Stale or expired work-item lease")
    return task


class RunStore:
    def __init__(self, session_factory=None):
        self.sf = session_factory or get_sync_session_factory()

    def get(self, run_id: str) -> dict:
        with self.sf() as db:
            row = db.get(DiscoveryRun, run_id)
            if not row:
                raise ValueError("Unknown discovery run")
            return row_dict(row)

    def for_task(self, task_id: str) -> dict | None:
        with self.sf() as db:
            row = db.scalar(select(DiscoveryRun).where(DiscoveryRun.task_id == task_id))
            return row_dict(row) if row else None

    def create(self, *, task_id, snapshot, config, profile) -> dict:
        with self.sf.begin() as db:
            row = DiscoveryRun(
                id=digest(["discovery-v2", task_id]),
                task_id=task_id,
                repo_snapshot_id=snapshot["repo_snapshot_id"],
                snapshot=snapshot,
                config=config,
                profile=profile,
                created_at=time.time(),
            )
            db.add(row)
            db.flush()
            return row_dict(row)

    def patch(self, run_id, **values):
        if "initial_snapshot" in values:
            raise ValueError("Use freeze_initial for immutable checkpoints")
        with self.sf.begin() as db:
            db.execute(update(DiscoveryRun).where(DiscoveryRun.id == run_id).values(**values))

    def acquire(self, run_id, owner, seconds=120) -> bool:
        with self.sf.begin() as db:
            return bool(
                db.execute(
                    update(DiscoveryRun)
                    .where(DiscoveryRun.id == run_id, DiscoveryRun.lease_until < time.time())
                    .values(owner=owner, lease_until=time.time() + seconds)
                ).rowcount
            )

    def heartbeat(self, run_id, owner, seconds=120):
        with self.sf.begin() as db:
            if not db.execute(
                update(DiscoveryRun)
                .where(DiscoveryRun.id == run_id, DiscoveryRun.owner == owner)
                .values(lease_until=time.time() + seconds)
            ).rowcount:
                raise ValueError("Lost discovery coordinator lease")

    def release(self, run_id, owner):
        with self.sf.begin() as db:
            db.execute(
                update(DiscoveryRun)
                .where(DiscoveryRun.id == run_id, DiscoveryRun.owner == owner)
                .values(owner=None, lease_until=0)
            )

    def freeze_initial(self, run_id, payload):
        with self.sf.begin() as db:
            row = db.scalar(select(DiscoveryRun).where(DiscoveryRun.id == run_id).with_for_update())
            if row.initial_snapshot is None:
                row.initial_snapshot = {**payload, "frozen_at": time.time(), "snapshot_version": 1}
            return row.initial_snapshot
