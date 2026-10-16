from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.models.discovery import DiscoveryEvidence
from app.services.discovery.store import RunStore, digest, row_dict


def validate_evidence(db, run, ids, *, source_only=False):
    for evidence_id in ids:
        evidence = db.get(DiscoveryEvidence, evidence_id)
        if (
            not evidence
            or evidence.run_id != run.id
            or evidence.repo_snapshot_id != run.repo_snapshot_id
        ):
            raise ValueError(f"Unknown evidence or snapshot mismatch: {evidence_id}")
        if source_only and evidence.kind != "source":
            raise ValueError("Independent tasks may only reference source evidence")
        if evidence.kind == "skill_reference":
            raise ValueError(
                "Skill reading belongs in skills_used, not source evidence or coverage"
            )


def require_source_evidence(db, ids):
    if not any((row := db.get(DiscoveryEvidence, eid)) and row.kind == "source" for eid in ids):
        raise ValueError("Source review requires at least one real source evidence reference")


class EvidenceStore(RunStore):
    def record(self, run_id, kind, payload) -> str:
        run = self.get(run_id)
        content_hash = digest(payload)
        evidence_id = digest([run_id, run["repo_snapshot_id"], kind, content_hash])
        try:
            with self.sf.begin() as db:
                if not db.get(DiscoveryEvidence, evidence_id):
                    db.add(
                        DiscoveryEvidence(
                            id=evidence_id,
                            run_id=run_id,
                            repo_snapshot_id=run["repo_snapshot_id"],
                            kind=kind,
                            content_hash=content_hash,
                            payload=payload,
                        )
                    )
        except IntegrityError:
            with self.sf() as db:
                if not db.get(DiscoveryEvidence, evidence_id):
                    raise
        return evidence_id

    def evidence(self, run_id, evidence_id, *, source_only=False):
        with self.sf() as db:
            row = db.get(DiscoveryEvidence, evidence_id)
            if not row or row.run_id != run_id or (source_only and row.kind != "source"):
                raise ValueError("Evidence unavailable in this work package")
            return row_dict(row)
