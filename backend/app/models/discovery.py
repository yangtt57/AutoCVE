"""Three logical ledgers backed by the application's relational database."""

from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from app.db.base import Base


class DiscoveryRun(Base):
    __tablename__ = "discovery_runs"
    id = Column(String(64), primary_key=True)
    task_id = Column(
        String(36), ForeignKey("agent_tasks.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    repo_snapshot_id = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default="running")
    phase = Column(String(24), nullable=False, default="independent")
    config = Column(JSON, nullable=False, default=dict)
    snapshot = Column(JSON, nullable=False, default=dict)
    profile = Column(JSON, nullable=False, default=dict)
    initial_snapshot = Column(JSON, nullable=True)
    scan_manifest = Column(JSON, nullable=False, default=dict)
    summary = Column(JSON, nullable=False, default=dict)
    owner = Column(String(64), nullable=True)
    lease_until = Column(Float, nullable=False, default=0)
    created_at = Column(Float, nullable=False)


class DiscoveryTask(Base):
    __tablename__ = "discovery_work_items"
    id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    dedup_key = Column(String(64), nullable=False)
    phase = Column(String(24), nullable=False)
    round = Column(Integer, nullable=False, default=0)
    status = Column(String(24), nullable=False, default="pending")
    worker_id = Column(String(64), nullable=True)
    attempt_id = Column(String(64), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    lease_until = Column(Float, nullable=False, default=0)
    payload = Column(JSON, nullable=False, default=dict)
    checkpoint = Column(JSON, nullable=False, default=dict)
    coverage = Column(JSON, nullable=False, default=list)
    reason = Column(Text, nullable=True)
    session_id = Column(String(36), nullable=True)
    created_at = Column(Float, nullable=False)
    __table_args__ = (
        UniqueConstraint("run_id", "dedup_key"),
        Index("ix_discovery_claim", "run_id", "phase", "status", "lease_until"),
    )


class DiscoveryCandidate(Base):
    __tablename__ = "discovery_candidates"
    id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    severity = Column(String(16), nullable=False)
    payload = Column(JSON, nullable=False)


class DiscoveryCandidateVersion(Base):
    __tablename__ = "discovery_candidate_versions"
    candidate_id = Column(
        String(64), ForeignKey("discovery_candidates.id", ondelete="CASCADE"), primary_key=True
    )
    version = Column(Integer, primary_key=True)
    idempotency_key = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(Float, nullable=False)
    __table_args__ = (UniqueConstraint("candidate_id", "idempotency_key"),)


class DiscoveryEvidence(Base):
    __tablename__ = "discovery_evidence"
    id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    repo_snapshot_id = Column(String(64), nullable=False)
    kind = Column(String(32), nullable=False)
    content_hash = Column(String(64), nullable=False)
    payload = Column(JSON, nullable=False)


class ScanObservation(Base):
    __tablename__ = "scan_observations"
    id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scan_run_id = Column(String(64), nullable=False)
    repo_snapshot_id = Column(String(64), nullable=False)
    signal_fingerprint = Column(String(64), nullable=False, index=True)
    priority = Column(Integer, nullable=False)
    file_path = Column(Text, nullable=False)
    rule_id = Column(Text, nullable=False)
    severity = Column(String(16), nullable=False)
    review_status = Column(String(24), nullable=False, default="pending")
    feedback_task_id = Column(String(64), nullable=True)
    payload = Column(JSON, nullable=False)
    decision = Column(JSON, nullable=True)
    __table_args__ = (Index("ix_discovery_observation_page", "run_id", "priority", "id"),)


class ScanIngestError(Base):
    __tablename__ = "scan_ingest_errors"
    id = Column(String(64), primary_key=True)
    run_id = Column(
        String(64), ForeignKey("discovery_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    locator = Column(Text, nullable=False)
    reason = Column(Text, nullable=False)
