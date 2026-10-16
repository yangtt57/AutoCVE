"""暂停 / 继续，以及后端重启后的收尾。

这里用真实的 ``VerifierDockerRuntime``，只把 Docker 客户端换成假的——
暂停的逻辑（冻结哪个容器、状态怎么变、时间怎么算）都是真的在跑。
"""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.db.base import Base
from app.models.managed_vulnerability import (
    ManagedVulnerability,
    ManagedVulnerabilityReport,
)
from app.models.vulnerability_verification import (
    VerificationStatus,
    VulnerabilityVerification,
)
from app.services.verification_agent import runner
from app.services.verification_agent.docker_runtime import VerifierDockerRuntime

RUN_ID = "verification-pause-01"


class _FakeContainer:
    def __init__(self, *, evidence: dict | None = None, paused: bool = False):
        self.attrs = {"State": {"Paused": paused}}
        self.status = "paused" if paused else "running"
        self.evidence = evidence
        self.pause_calls = 0
        self.unpause_calls = 0

    def pause(self):
        self.pause_calls += 1
        self.attrs["State"]["Paused"] = True
        self.status = "paused"

    def unpause(self):
        self.unpause_calls += 1
        self.attrs["State"]["Paused"] = False
        self.status = "running"

    def get_archive(self, path):
        if self.evidence is None:
            raise FileNotFoundError(path)
        payload = json.dumps(self.evidence).encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="EVIDENCE.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        return iter([buffer.getvalue()]), {}

    def remove(self, **kwargs):
        return None


class _FakeContainers:
    def __init__(self, container):
        self.container = container

    def get(self, name):
        return self.container


class _FakeClient:
    def __init__(self, container):
        self.containers = _FakeContainers(container)


def _runtime(container):
    return VerifierDockerRuntime(client=_FakeClient(container))


def _evidence(**overrides):
    payload = {
        "run_id": RUN_ID,
        "verdict": "unverifiable",
        "confidence": "medium",
        "summary": "环境起不来，无法判定。",
        "unverifiable_reason": "依赖装不上。",
        "environment": {"method": "none"},
        "steps": [],
        "http_exchanges": [],
        "limitations": ["没有运行时证据"],
        "artifacts": [],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
async def harness():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        vulnerability = ManagedVulnerability(
            id="vuln-1",
            project_id="project-1",
            task_id="task-1",
            finding_id="finding-1",
            project_name="demo-portal",
            version_label="v1.0.0",
            vulnerability_name="路径穿越",
            vulnerability_type="path_traversal",
            severity="high",
        )
        db.add(vulnerability)
        verification = VulnerabilityVerification(
            id=RUN_ID,
            vulnerability_id="vuln-1",
            project_id="project-1",
            status=VerificationStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            workspace_path=f"/verifier/work/{RUN_ID}",
            model_provider="deepseek",
            model_id="deepseek-flash",
            thinking_level="max",
        )
        db.add(verification)
        await db.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


async def test_pause_freezes_container_and_marks_record(harness):
    container = _FakeContainer()
    async with harness() as db:
        verification = await db.get(VulnerabilityVerification, RUN_ID)
        await runner.pause_verification(verification, db, runtime=_runtime(container))

        assert verification.status == VerificationStatus.PAUSED
        assert verification.paused_at is not None
        assert container.pause_calls == 1
        assert container.status == "paused"

        stored = await db.get(VulnerabilityVerification, RUN_ID)
        assert stored.status == VerificationStatus.PAUSED


async def test_resume_unfreezes_and_accumulates_paused_seconds(harness):
    container = _FakeContainer()
    async with harness() as db:
        verification = await db.get(VulnerabilityVerification, RUN_ID)
        await runner.pause_verification(verification, db, runtime=_runtime(container))
        # 假装暂停了两分钟
        verification.paused_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        await db.commit()

        await runner.resume_verification(verification, db, runtime=_runtime(container))

        assert verification.status == VerificationStatus.RUNNING
        assert verification.paused_at is None
        assert verification.paused_seconds >= 119
        assert container.unpause_calls == 1
        assert container.status == "running"


def test_effective_duration_excludes_paused_time():
    started = datetime.now(timezone.utc) - timedelta(seconds=1000)
    record = SimpleNamespace(
        started_at=started, paused_seconds=600.0, paused_at=None
    )
    end = datetime.now(timezone.utc)
    assert 395 <= runner.effective_duration_seconds(record, end) <= 405


def test_effective_duration_deducts_ongoing_pause():
    """暂停中就被收尾时，当前这段暂停也要扣掉。"""
    started = datetime.now(timezone.utc) - timedelta(seconds=1000)
    record = SimpleNamespace(
        started_at=started,
        paused_seconds=0.0,
        paused_at=datetime.now(timezone.utc) - timedelta(seconds=900),
    )
    end = datetime.now(timezone.utc)
    assert 95 <= runner.effective_duration_seconds(record, end) <= 105


async def test_reconcile_recovers_evidence_left_by_previous_process(harness, monkeypatch):
    """后端重启前 Agent 其实已经跑完 —— 应该把证据救回来，而不是白扔。"""
    container = _FakeContainer(evidence=_evidence())
    monkeypatch.setattr(runner, "AsyncSessionLocal", harness)

    counts = await runner.reconcile_interrupted_verifications(runtime=_runtime(container))

    assert counts == {"recovered": 1, "failed": 0}
    async with harness() as db:
        stored = await db.get(VulnerabilityVerification, RUN_ID)
        assert stored.status == VerificationStatus.COMPLETED
        assert stored.verdict == "unverifiable"
        assert stored.evidence_digest
        report = (
            await db.execute(
                ManagedVulnerabilityReport.__table__.select().where(
                    ManagedVulnerabilityReport.report_kind == "verification"
                )
            )
        ).first()
        assert report is not None


async def test_reconcile_marks_stuck_run_as_failed(harness, monkeypatch):
    """没有证据可救 → 如实标记失败，而不是永远显示「验证中」。"""
    container = _FakeContainer(evidence=None)
    monkeypatch.setattr(runner, "AsyncSessionLocal", harness)

    counts = await runner.reconcile_interrupted_verifications(runtime=_runtime(container))

    assert counts == {"recovered": 0, "failed": 1}
    async with harness() as db:
        stored = await db.get(VulnerabilityVerification, RUN_ID)
        assert stored.status == VerificationStatus.FAILED
        assert "后端重启" in stored.error_message
        assert stored.completed_at is not None


async def test_reconcile_unfreezes_paused_container(harness, monkeypatch):
    """被中断的验证如果还冻着，收尾时要解冻，否则容器再也跑不了。"""
    container = _FakeContainer(evidence=_evidence(), paused=True)
    monkeypatch.setattr(runner, "AsyncSessionLocal", harness)
    async with harness() as db:
        verification = await db.get(VulnerabilityVerification, RUN_ID)
        verification.status = VerificationStatus.PAUSED
        verification.paused_at = datetime.now(timezone.utc)
        await db.commit()

    await runner.reconcile_interrupted_verifications(runtime=_runtime(container))

    assert container.unpause_calls == 1
    assert container.status == "running"
