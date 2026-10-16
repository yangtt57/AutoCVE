"""Source discovery v2 ledgers; old findings are untouched."""

import sqlalchemy as sa

from alembic import op

revision = "20261016_01"
down_revision = "20260711_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "task_id",
            sa.String(length=36),
            sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("repo_snapshot_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=24), primary_key=False, nullable=False),
        sa.Column("phase", sa.String(length=24), primary_key=False, nullable=False),
        sa.Column("config", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("snapshot", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("profile", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("initial_snapshot", sa.JSON(), primary_key=False, nullable=True),
        sa.Column("scan_manifest", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("summary", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("owner", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("lease_until", sa.Float(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.Float(), primary_key=False, nullable=False),
        sa.UniqueConstraint("task_id"),
    )
    op.create_table(
        "discovery_work_items",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("dedup_key", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("phase", sa.String(length=24), primary_key=False, nullable=False),
        sa.Column("round", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=24), primary_key=False, nullable=False),
        sa.Column("worker_id", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("attempt_id", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("attempts", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("lease_until", sa.Float(), primary_key=False, nullable=False),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("checkpoint", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("coverage", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("reason", sa.Text(), primary_key=False, nullable=True),
        sa.Column("session_id", sa.String(length=36), primary_key=False, nullable=True),
        sa.Column("created_at", sa.Float(), primary_key=False, nullable=False),
        sa.UniqueConstraint("run_id", "dedup_key"),
    )
    op.create_index(
        "ix_discovery_claim",
        "discovery_work_items",
        ["run_id", "phase", "status", "lease_until"],
        unique=False,
    )
    op.create_index(
        "ix_discovery_work_items_run_id", "discovery_work_items", ["run_id"], unique=False
    )
    op.create_table(
        "discovery_candidates",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("status", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("severity", sa.String(length=16), primary_key=False, nullable=False),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
    )
    op.create_index(
        "ix_discovery_candidates_run_id", "discovery_candidates", ["run_id"], unique=False
    )
    op.create_table(
        "discovery_candidate_versions",
        sa.Column(
            "candidate_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_candidates.id", ondelete="CASCADE"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("created_at", sa.Float(), primary_key=False, nullable=False),
        sa.UniqueConstraint("candidate_id", "idempotency_key"),
    )
    op.create_table(
        "discovery_evidence",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("repo_snapshot_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("kind", sa.String(length=32), primary_key=False, nullable=False),
        sa.Column("content_hash", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
    )
    op.create_index("ix_discovery_evidence_run_id", "discovery_evidence", ["run_id"], unique=False)
    op.create_table(
        "scan_observations",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("scan_run_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("repo_snapshot_id", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("signal_fingerprint", sa.String(length=64), primary_key=False, nullable=False),
        sa.Column("priority", sa.Integer(), primary_key=False, nullable=False),
        sa.Column("file_path", sa.Text(), primary_key=False, nullable=False),
        sa.Column("rule_id", sa.Text(), primary_key=False, nullable=False),
        sa.Column("severity", sa.String(length=16), primary_key=False, nullable=False),
        sa.Column("review_status", sa.String(length=24), primary_key=False, nullable=False),
        sa.Column("feedback_task_id", sa.String(length=64), primary_key=False, nullable=True),
        sa.Column("payload", sa.JSON(), primary_key=False, nullable=False),
        sa.Column("decision", sa.JSON(), primary_key=False, nullable=True),
    )
    op.create_index(
        "ix_discovery_observation_page",
        "scan_observations",
        ["run_id", "priority", "id"],
        unique=False,
    )
    op.create_index("ix_scan_observations_run_id", "scan_observations", ["run_id"], unique=False)
    op.create_index(
        "ix_scan_observations_signal_fingerprint",
        "scan_observations",
        ["signal_fingerprint"],
        unique=False,
    )
    op.create_table(
        "scan_ingest_errors",
        sa.Column("id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("discovery_runs.id", ondelete="CASCADE"),
            primary_key=False,
            nullable=False,
        ),
        sa.Column("locator", sa.Text(), primary_key=False, nullable=False),
        sa.Column("reason", sa.Text(), primary_key=False, nullable=False),
    )
    op.create_index("ix_scan_ingest_errors_run_id", "scan_ingest_errors", ["run_id"], unique=False)


def downgrade():
    op.drop_table("scan_ingest_errors")
    op.drop_table("scan_observations")
    op.drop_table("discovery_evidence")
    op.drop_table("discovery_candidate_versions")
    op.drop_table("discovery_candidates")
    op.drop_table("discovery_work_items")
    op.drop_table("discovery_runs")
