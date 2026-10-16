from __future__ import annotations

from sqlalchemy import func, select, update

from app.models.discovery import (
    DiscoveryCandidate,
    DiscoveryEvidence,
    DiscoveryTask,
    ScanObservation,
)
from app.services.discovery.store import digest
from app.services.discovery.task_store import TaskStore


class FeedbackPlanner(TaskStore):
    def plan_batch(self, run_id, batch_size=5):
        """UI pagination is unrelated to claiming. Stable priority with file/rule rotation."""
        run = self.get(run_id)
        if not run["initial_snapshot"]:
            raise ValueError("Initial checkpoint must be frozen before feedback")
        with self.sf.begin() as db:
            ranked = (
                select(
                    ScanObservation.id,
                    ScanObservation.priority,
                    func.row_number()
                    .over(
                        partition_by=(ScanObservation.file_path, ScanObservation.rule_id),
                        order_by=(ScanObservation.priority.desc(), ScanObservation.id),
                    )
                    .label("rotation"),
                )
                .where(ScanObservation.run_id == run_id, ScanObservation.feedback_task_id.is_(None))
                .subquery()
            )
            ids = list(
                db.scalars(
                    select(ranked.c.id)
                    .order_by(ranked.c.rotation, ranked.c.priority.desc(), ranked.c.id)
                    .limit(batch_size)
                )
            )
            if not ids:
                return None
            rows = list(db.scalars(select(ScanObservation).where(ScanObservation.id.in_(ids))))
            scope = sorted({r.file_path for r in rows})
            # Association is many-to-many and advisory. Never merge candidate identities here.
            related = []
            for candidate in db.scalars(
                select(DiscoveryCandidate).where(DiscoveryCandidate.run_id == run_id)
            ):
                payload = candidate.payload
                evidence_paths = {
                    e.payload.get("file_path")
                    for e in db.scalars(
                        select(DiscoveryEvidence).where(
                            DiscoveryEvidence.run_id == run_id,
                            DiscoveryEvidence.id.in_(
                                payload.get("supporting_evidence_ids", [])
                                + payload.get("counter_evidence_ids", [])
                            ),
                        )
                    )
                }
                if (
                    payload.get("project_component") in {p.split("/")[0] for p in scope}
                    or set(payload.get("scanner_observation_ids", [])).intersection(ids)
                    or evidence_paths.intersection(scope)
                ):
                    related.append(candidate.id)
            payload = {
                "scope": scope,
                "analysis_question": "Check source conditions and counter-evidence for each observation; inspect related callers and propose bounded follow-up when justified.",
                "observation_ids": ids,
                "candidate_ids": related,
                "evidence_version": run["scan_manifest"].get("scan_snapshot_id"),
            }
            # Coordinator owns one run lease. The transaction publishes task and bindings together.
            key = digest([run_id, "feedback", ids])
            task_id = digest([run_id, key])
            if not db.get(DiscoveryTask, task_id):
                import time

                db.add(
                    DiscoveryTask(
                        id=task_id,
                        run_id=run_id,
                        dedup_key=key,
                        phase="feedback",
                        round=0,
                        payload=payload,
                        created_at=time.time(),
                    )
                )
                db.flush()
            db.execute(
                update(ScanObservation)
                .where(ScanObservation.id.in_(ids), ScanObservation.feedback_task_id.is_(None))
                .values(feedback_task_id=task_id)
            )
            return task_id

    def plan_agent_feedback(self, run_id):
        with self.sf() as db:
            candidates = [
                c.payload
                for c in db.scalars(
                    select(DiscoveryCandidate).where(DiscoveryCandidate.run_id == run_id)
                )
            ]
        for candidate in candidates:
            self.enqueue(
                run_id,
                "feedback",
                {
                    "scope": [candidate["project_component"]],
                    "analysis_question": "Revisit the independent candidate, including contrary evidence and remaining caller conditions; scanner silence does not remove a candidate.",
                    "candidate_ids": [candidate["candidate_id"]],
                    "evidence_version": candidate["record_version"],
                },
            )
