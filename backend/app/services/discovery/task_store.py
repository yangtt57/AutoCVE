from __future__ import annotations

import time
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError

from app.models.discovery import DiscoveryCandidate, DiscoveryRun, DiscoveryTask, ScanObservation
from app.services.discovery.evidence_store import require_source_evidence, validate_evidence
from app.services.discovery.models import FeedbackDecision, FollowupInput
from app.services.discovery.store import RunStore, digest, require_attempt, row_dict


class TaskStore(RunStore):
    def enqueue(self, run_id, phase, payload, *, round=0):
        key = digest(
            [
                run_id,
                phase,
                sorted(payload.get("scope", [])),
                payload.get("analysis_question"),
                payload.get("evidence_version", []),
                sorted(payload.get("observation_ids", [])),
                sorted(payload.get("entrypoint_ids", [])),
            ]
        )
        task_id = digest([run_id, key])
        try:
            with self.sf.begin() as db:
                if not db.get(DiscoveryTask, task_id):
                    db.add(
                        DiscoveryTask(
                            id=task_id,
                            run_id=run_id,
                            dedup_key=key,
                            phase=phase,
                            round=round,
                            payload=payload,
                            created_at=time.time(),
                        )
                    )
        except IntegrityError:
            with self.sf() as db:
                if not db.get(DiscoveryTask, task_id):
                    raise
        return task_id

    def list(self, run_id, phase=None):
        with self.sf() as db:
            stmt = select(DiscoveryTask).where(DiscoveryTask.run_id == run_id)
            if phase:
                stmt = stmt.where(DiscoveryTask.phase == phase)
            return [
                row_dict(r)
                for r in db.scalars(stmt.order_by(DiscoveryTask.created_at, DiscoveryTask.id))
            ]

    def claim(self, run_id, phase, worker_id, *, lease_seconds=90, round=None):
        with self.sf.begin() as db:
            available = or_(
                DiscoveryTask.status == "pending",
                (DiscoveryTask.status == "running") & (DiscoveryTask.lease_until < time.time()),
            )
            stmt = select(DiscoveryTask).where(
                DiscoveryTask.run_id == run_id, DiscoveryTask.phase == phase, available
            )
            if round is not None:
                stmt = stmt.where(DiscoveryTask.round == round)
            # CAS below also protects SQLite, where FOR UPDATE is ignored.
            for task in db.scalars(
                stmt.order_by(DiscoveryTask.created_at, DiscoveryTask.id).with_for_update(
                    skip_locked=True
                )
            ):
                attempt = uuid.uuid4().hex
                changed = db.execute(
                    update(DiscoveryTask)
                    .where(DiscoveryTask.id == task.id, available)
                    .values(
                        status="running",
                        worker_id=worker_id,
                        attempt_id=attempt,
                        attempts=DiscoveryTask.attempts + 1,
                        lease_until=time.time() + lease_seconds,
                    )
                )
                if changed.rowcount:
                    db.refresh(task)
                    return row_dict(task)
        return None

    def heartbeat(self, task_id, attempt_id, *, lease_seconds=90, session_id=None):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            task.lease_until = time.time() + lease_seconds
            if session_id:
                task.session_id = session_id

    def checkpoint(self, task_id, attempt_id, payload):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            task.checkpoint = {**task.checkpoint, **payload}

    def record_read(self, task_id, attempt_id, record):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            reads = list(task.checkpoint.get("read_ranges", []))
            if record not in reads:
                reads.append(record)
            task.checkpoint = {**task.checkpoint, "read_ranges": reads}

    def coverage(self, task_id, attempt_id, *, scope, check, status, evidence_ids, reason):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            run = db.get(DiscoveryRun, task.run_id)
            validate_evidence(db, run, evidence_ids, source_only=task.phase == "independent")
            if status == "checked" and not evidence_ids:
                raise ValueError("Checked coverage needs evidence")
            if status == "checked":
                require_source_evidence(db, evidence_ids)
            if scope != "." and not any(
                p == scope or p.startswith(scope.rstrip("/") + "/") for p in run.snapshot["files"]
            ):
                raise ValueError("Coverage scope is outside the source snapshot")
            record = {
                "scope": scope,
                "check": check,
                "status": status,
                "evidence_ids": evidence_ids,
                "reason": reason,
            }
            items = [c for c in task.coverage if (c["scope"], c["check"]) != (scope, check)]
            task.coverage = [*items, record]

    def finish(self, task_id, attempt_id, *, status="completed", reason=""):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            ids = task.payload.get("observation_ids", [])
            missing = (
                list(
                    db.scalars(
                        select(ScanObservation.id).where(
                            ScanObservation.id.in_(ids),
                            (ScanObservation.review_status == "pending")
                            | (
                                (ScanObservation.review_status == "needs_followup")
                                & (ScanObservation.feedback_task_id != task.id)
                            ),
                        )
                    )
                )
                if ids
                else []
            )
            if status == "completed" and (missing or not task.coverage):
                status, reason = "deferred", "Missing per-item decisions or coverage receipt"
            if status == "completed":
                reads = task.checkpoint.get("read_ranges", []) + task.payload.get("prior_checkpoint", {}).get("read_ranges", [])
                read_files = {r["file_path"] for r in reads}
                unread = set(task.payload.get("entry_files", [])) - read_files
                if unread:
                    status, reason = "deferred", f"Entry files not read: {', '.join(sorted(unread))}"
            task.status = status
            task.reason = reason
            task.lease_until = 0
            return {
                "task_id": task.id,
                "status": status,
                "missing_observation_ids": missing,
                "reason": reason,
            }

    def defer_pending(self, run_id, phase, reason):
        with self.sf.begin() as db:
            db.execute(
                update(DiscoveryTask)
                .where(
                    DiscoveryTask.run_id == run_id,
                    DiscoveryTask.phase == phase,
                    DiscoveryTask.status == "pending",
                )
                .values(status="deferred", reason=reason)
            )

    def reopen(self, run_id):
        with self.sf.begin() as db:
            run = db.get(DiscoveryRun, run_id)
            stmt = update(DiscoveryTask).where(
                DiscoveryTask.run_id == run_id,
                or_(
                    DiscoveryTask.status.in_(["failed", "deferred"]),
                    (DiscoveryTask.status == "running") & (DiscoveryTask.lease_until < time.time()),
                ),
            )
            # The original independent checkpoint remains immutable on resume.
            if run.initial_snapshot:
                stmt = stmt.where(DiscoveryTask.phase != "independent")
            stmt = stmt.where(DiscoveryTask.round < run.config.get("max_feedback_rounds", 2))
            db.execute(stmt.values(status="pending", lease_until=0))

    def request_followup(self, task_id, attempt_id, request: FollowupInput):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            run = db.get(DiscoveryRun, task.run_id)
            validate_evidence(
                db, run, request.evidence_ids, source_only=task.phase == "independent"
            )
            if set(request.observation_ids) - set(task.payload.get("observation_ids", [])):
                raise ValueError("Follow-up observations must belong to the parent work package")
            for cid in request.candidate_ids:
                candidate = db.get(DiscoveryCandidate, cid)
                if not candidate or candidate.run_id != run.id:
                    raise ValueError("Unknown follow-up candidate")
            scope_files = set(run.snapshot["files"])
            if any(
                not any(f == scope or f.startswith(scope.rstrip("/") + "/") for f in scope_files)
                for scope in request.scope
            ):
                raise ValueError("Follow-up scope must locate files in the source snapshot")
            next_round = task.round + 1
            limit = run.config.get("max_feedback_rounds", 2)
            payload = {
                **request.model_dump(),
                "evidence_version": sorted(request.evidence_ids),
                "parent_task_id": task.id,
            }
        followup_id = self.enqueue(task.run_id, "expansion", payload, round=next_round)
        if next_round >= limit:
            with self.sf.begin() as db:
                item = db.get(DiscoveryTask, followup_id)
                if item.status == "pending":
                    item.status, item.reason = "deferred", "Feedback round limit reached"
        return followup_id

    def submit_decisions(self, task_id, attempt_id, decisions: list[FeedbackDecision]):
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            run = db.get(DiscoveryRun, task.run_id)
            if task.phase == "independent" or run.initial_snapshot is None:
                raise ValueError("Scanner feedback is unavailable before the initial checkpoint")
            claimed = set(task.payload.get("observation_ids", []))
            for decision in decisions:
                if decision.observation_id not in claimed:
                    raise ValueError("Observation not claimed by this work package")
                validate_evidence(db, run, decision.evidence_ids)
                require_source_evidence(db, decision.evidence_ids)
                for cid in decision.candidate_ids:
                    candidate = db.get(DiscoveryCandidate, cid)
                    if not candidate or candidate.run_id != run.id:
                        raise ValueError("Unknown linked candidate")
                if (
                    decision.status in {"new_candidate", "linked_candidate"}
                    and not decision.candidate_ids
                ):
                    raise ValueError("Candidate decision requires a persisted candidate")
                if decision.status == "needs_followup" and not decision.followup_task_ids:
                    raise ValueError("Needs-followup decisions require a persisted work item")
                for fid in decision.followup_task_ids:
                    followup = db.get(DiscoveryTask, fid)
                    if not followup or followup.run_id != run.id or followup.phase != "expansion":
                        raise ValueError("Unknown follow-up task")
                obs = db.get(ScanObservation, decision.observation_id)
                parent = task.payload.get("parent_task_id")
                continuation = (
                    task.phase == "expansion"
                    and obs.feedback_task_id == parent
                    and obs.review_status == "needs_followup"
                    and task.id in (obs.decision or {}).get("followup_task_ids", [])
                )
                if obs.feedback_task_id != task.id and not continuation:
                    raise ValueError("Observation belongs to another work package")
                if obs.decision and obs.decision != decision.model_dump() and not continuation:
                    raise ValueError("Decision already recorded; use a follow-up candidate version")
                if continuation:
                    obs.payload = {
                        **obs.payload,
                        "review_history": [*obs.payload.get("review_history", []), obs.decision],
                    }
                    obs.feedback_task_id = task.id
                obs.decision = decision.model_dump()
                obs.review_status = (
                    "needs_followup" if decision.status == "needs_followup" else "reviewed"
                )
            db.flush()
            pending = list(
                db.scalars(
                    select(ScanObservation.id).where(
                        ScanObservation.id.in_(claimed), ScanObservation.review_status == "pending"
                    )
                )
            )
            return {"accepted": len(decisions), "pending_ids": pending}
