from __future__ import annotations

import time

from sqlalchemy import select, update

from app.models.discovery import (
    DiscoveryCandidate,
    DiscoveryCandidateVersion,
    DiscoveryRun,
    ScanObservation,
)
from app.services.discovery.evidence_store import require_source_evidence, validate_evidence
from app.services.discovery.models import CandidateInput
from app.services.discovery.store import RunStore, digest, require_attempt

ORIGINS = {
    "independent": "independent_agent",
    "feedback": "scanner_feedback",
    "expansion": "targeted_expansion",
}


class CandidateStore(RunStore):
    def record(
        self,
        *,
        task_id,
        attempt_id,
        key,
        candidate: CandidateInput,
        candidate_id=None,
        expected_version=0,
    ) -> dict:
        with self.sf.begin() as db:
            task = require_attempt(db, task_id, attempt_id)
            run = db.get(DiscoveryRun, task.run_id)
            if task.phase == "independent" and run.initial_snapshot is not None:
                raise ValueError("Independent snapshot is already frozen")
            cid = candidate_id or digest([task.run_id, task.id, key])
            idem = digest([task.id, key])
            prior = db.scalar(
                select(DiscoveryCandidateVersion).where(
                    DiscoveryCandidateVersion.candidate_id == cid,
                    DiscoveryCandidateVersion.idempotency_key == idem,
                )
            )
            if prior:
                return prior.payload
            current = db.get(DiscoveryCandidate, cid)
            if current and (current.run_id != task.run_id or current.version != expected_version):
                raise ValueError("Candidate version conflict; reload before updating")
            if not current and (candidate_id or expected_version):
                raise ValueError("Candidate does not exist")
            refs = (
                candidate.supporting_evidence_ids
                + candidate.counter_evidence_ids
                + candidate.expected_policy.evidence_ids
            )
            validate_evidence(db, run, refs, source_only=task.phase == "independent")
            if candidate.status == "statically_supported" and not candidate.supporting_evidence_ids:
                raise ValueError("Statically supported candidates require source evidence")
            if candidate.status == "statically_supported":
                require_source_evidence(db, candidate.supporting_evidence_ids)
            if candidate.status == "ruled_out" and not candidate.counter_evidence_ids:
                raise ValueError("Ruled out candidates require counter evidence")
            if candidate.status == "ruled_out":
                require_source_evidence(db, candidate.counter_evidence_ids)
            if task.phase == "independent" and candidate.scanner_observation_ids:
                raise ValueError("Scanner results are isolated during independent discovery")
            for oid in candidate.scanner_observation_ids:
                obs = db.get(ScanObservation, oid)
                if not obs or obs.run_id != run.id:
                    raise ValueError("Unknown scanner observation")
            known_entries = {e["id"] for e in run.profile.get("entrypoints", [])}
            if set(candidate.entrypoint_refs) - known_entries:
                raise ValueError("Unknown entrypoint reference")
            previous = current.payload if current else {}
            from app.services.discovery.skill_catalog import candidate_skill_usage

            origin = ORIGINS[task.phase]
            version = expected_version + 1
            payload = {
                **candidate.model_dump(),
                "candidate_id": cid,
                "repo_snapshot_id": run.repo_snapshot_id,
                "record_version": version,
                "initial_version": 1,
                "origin": previous.get("origin", origin),
                "contributing_sources": sorted(
                    set(previous.get("contributing_sources", []) + [origin])
                ),
                "task_id": task.id,
                "skills_used": candidate_skill_usage(db, task, previous),
            }
            if current:
                changed = db.execute(
                    update(DiscoveryCandidate)
                    .where(
                        DiscoveryCandidate.id == cid, DiscoveryCandidate.version == expected_version
                    )
                    .values(
                        version=version,
                        status=candidate.status,
                        severity=candidate.severity_estimate,
                        payload=payload,
                    )
                )
                if not changed.rowcount:
                    raise ValueError("Candidate version conflict")
            else:
                db.add(
                    DiscoveryCandidate(
                        id=cid,
                        run_id=run.id,
                        version=version,
                        status=candidate.status,
                        severity=candidate.severity_estimate,
                        payload=payload,
                    )
                )
                db.flush()
            db.add(
                DiscoveryCandidateVersion(
                    candidate_id=cid,
                    version=version,
                    idempotency_key=idem,
                    payload=payload,
                    created_at=time.time(),
                )
            )
            task.checkpoint = {
                **task.checkpoint,
                "candidate_ids": sorted(set(task.checkpoint.get("candidate_ids", []) + [cid])),
            }
            return payload

    def candidate(self, run_id, candidate_id, version=None):
        with self.sf() as db:
            row = db.get(DiscoveryCandidate, candidate_id)
            if not row or row.run_id != run_id:
                raise ValueError("Unknown candidate")
            if version is not None:
                row = db.get(DiscoveryCandidateVersion, (candidate_id, version))
                if not row:
                    raise ValueError("Unknown candidate version")
            return row.payload

    def list(self, run_id, *, status=None):
        with self.sf() as db:
            stmt = (
                select(DiscoveryCandidate)
                .where(DiscoveryCandidate.run_id == run_id)
                .order_by(DiscoveryCandidate.id)
            )
            if status:
                stmt = stmt.where(DiscoveryCandidate.status == status)
            return [r.payload for r in db.scalars(stmt)]

    def history(self, run_id, candidate_id):
        self.candidate(run_id, candidate_id)
        with self.sf() as db:
            return [
                r.payload
                for r in db.scalars(
                    select(DiscoveryCandidateVersion)
                    .where(DiscoveryCandidateVersion.candidate_id == candidate_id)
                    .order_by(DiscoveryCandidateVersion.version)
                )
            ]
