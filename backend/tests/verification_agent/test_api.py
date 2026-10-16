"""动态验证 API 的行为。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
import sys

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.api import deps
from app.api.v1.endpoints import vulnerability_verifications as endpoint
from app.api.v1.endpoints.vulnerability_verifications import router
from app.core.config import settings
from app.db.base import Base
from app.db.session import get_db
from app.models.managed_vulnerability import ManagedVulnerability
from app.models.project import Project
from app.models.user import User
from app.models.vulnerability_verification import (
    VerificationStatus,
    VerificationVerdict,
    VulnerabilityVerification,
)


def build_test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/vulnerabilities")
    return app


async def _seed(session_factory):
    async with session_factory() as db:
        db.add(User(id="user-1", email="owner@example.com", hashed_password="x"))
        db.add(
            Project(
                id="project-1",
                name="acme/portal",
                source_type="repository",
                repository_url="https://github.com/acme/portal",
                owner_id="user-1",
            )
        )
        db.add(
            ManagedVulnerability(
                id="vuln-1",
                project_id="project-1",
                task_id="task-1",
                finding_id="finding-1",
                project_name="acme/portal",
                version_label="v1.2.0",
                vulnerability_name="路径穿越导致任意文件读取",
                vulnerability_type="path_traversal",
                severity="high",
                human_review_result="confirmed",
                cve_request_status="pending",
                report_generation_status="pending",
                source_metadata={"raw_finding": {"source": "request.args", "sink": "open()"}},
            )
        )
        await db.commit()


@asynccontextmanager
async def _harness():
    """建库、播种、搭 app，并在退出时**一定** dispose 引擎。

    必须 dispose：aiosqlite 的 worker 线程不是 daemon 线程，断言失败提前退出时
    pytest 会卡在解释器退出阶段，把一次普通失败伪装成"测试超时"。
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        await _seed(session_factory)

        async def _session():
            async with session_factory() as session:
                yield session

        app = build_test_app()
        app.dependency_overrides[get_db] = _session
        app.dependency_overrides[deps.get_current_user] = lambda: User(
            id="user-1", email="owner@example.com", hashed_password="x"
        )
        yield session_factory, app
    finally:
        await engine.dispose()


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.asyncio
async def test_disabled_feature_returns_actionable_conflict(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", False)

    async with _harness() as (_session_factory, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/vulnerabilities/vuln-1/verification")

    assert response.status_code == 409
    assert "VERIFICATION_AGENT_ENABLED" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_verification_persists_record_and_schedules_run(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)
    scheduled: list[str] = []

    def _fake_run(verification_id: str) -> None:
        scheduled.append(verification_id)

    monkeypatch.setattr(endpoint, "run_vulnerability_verification", _fake_run)

    async with _harness() as (session_factory, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/vulnerabilities/vuln-1/verification")

        assert response.status_code == 201
        body = response.json()
        assert body["vulnerability_id"] == "vuln-1"
        assert body["project_id"] == "project-1"
        assert body["status"] == VerificationStatus.PENDING
        assert scheduled == [body["id"]]

        async with session_factory() as db:
            stored = (await db.execute(select(VulnerabilityVerification))).scalars().all()
            assert len(stored) == 1
            assert stored[0].created_by == "user-1"


@pytest.mark.asyncio
async def test_second_run_is_rejected_while_one_is_active(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)
    monkeypatch.setattr(endpoint, "run_vulnerability_verification", lambda verification_id: None)

    async with _harness() as (session_factory, app):
        async with session_factory() as db:
            db.add(
                VulnerabilityVerification(
                    id="existing",
                    vulnerability_id="vuln-1",
                    project_id="project-1",
                    status=VerificationStatus.RUNNING,
                )
            )
            await db.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/vulnerabilities/vuln-1/verification")

        assert response.status_code == 409
        assert "existing" in response.json()["detail"]


@pytest.mark.asyncio
async def test_latest_and_history_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)

    async with _harness() as (session_factory, app):
        async with session_factory() as db:
            db.add(
                VulnerabilityVerification(
                    id="v-old",
                    vulnerability_id="vuln-1",
                    project_id="project-1",
                    status=VerificationStatus.COMPLETED,
                    verdict=VerificationVerdict.REFUTED,
                    confidence="medium",
                    environment_json={"method": "compose", "app_url": "http://verifier-dind:18080"},
                    evidence_json={"steps": [{"seq": 1, "command": "curl -s ...", "exit_code": 0}]},
                    limitations_json=["未覆盖 Windows"],
                    artifacts_json=[{"path": "poc.sh", "sha256": "a" * 64, "bytes": 12}],
                )
            )
            await db.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            latest = await client.get("/api/v1/vulnerabilities/vuln-1/verification")
            history = await client.get("/api/v1/vulnerabilities/vuln-1/verification/history")
            missing = await client.get("/api/v1/vulnerabilities/does-not-exist/verification")

        assert latest.status_code == 200
        body = latest.json()
        assert body["verdict"] == VerificationVerdict.REFUTED
        # 这几个字段在 ORM 里叫 *_json；别名没接好的话会静默变成 None/[]，前端就看不到证据
        assert body["environment"] == {"method": "compose", "app_url": "http://verifier-dind:18080"}
        assert body["limitations"] == ["未覆盖 Windows"]
        assert body["artifacts"][0]["path"] == "poc.sh"
        assert body["evidence"]["steps"][0]["command"] == "curl -s ..."

        assert history.status_code == 200
        assert len(history.json()) == 1
        # 历史列表不下发完整证据，只有详情接口才有（否则列表接口要背几百 KB）
        assert history.json()[0]["evidence"] is None
        assert history.json()[0]["limitations"] == ["未覆盖 Windows"]

        # 不存在的漏洞先被所有权校验拦下
        assert missing.status_code == 404


@pytest.mark.asyncio
async def test_pause_and_resume_endpoints(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)
    calls: list[str] = []

    async def _fake_pause(verification, db, **kwargs):
        calls.append("pause")
        verification.status = VerificationStatus.PAUSED
        await db.commit()
        # 真实现里也这样：commit 后必须 refresh，否则 updated_at 这类
        # onupdate 列是 expired 的，_to_response 一读就会在异步上下文里炸。
        await db.refresh(verification)
        return verification

    async def _fake_resume(verification, db, **kwargs):
        calls.append("resume")
        verification.status = VerificationStatus.RUNNING
        await db.commit()
        await db.refresh(verification)
        return verification

    monkeypatch.setattr(endpoint, "pause_verification", _fake_pause)
    monkeypatch.setattr(endpoint, "resume_verification", _fake_resume)

    async with _harness() as (session_factory, app):
        async with session_factory() as db:
            db.add(
                VulnerabilityVerification(
                    id="v-run",
                    vulnerability_id="vuln-1",
                    project_id="project-1",
                    status=VerificationStatus.RUNNING,
                )
            )
            await db.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 跑步中的不能“继续”
            not_paused = await client.post("/api/v1/vulnerabilities/vuln-1/verification/resume")
            # 运行中：可以暂停
            paused = await client.post("/api/v1/vulnerabilities/vuln-1/verification/pause")
            # 已暂停的不能重复暂停
            paused_again = await client.post("/api/v1/vulnerabilities/vuln-1/verification/pause")
            # 暂停后可以继续
            resumed = await client.post("/api/v1/vulnerabilities/vuln-1/verification/resume")

        assert not_paused.status_code == 409
        assert "只有已暂停的验证可以继续" in not_paused.json()["detail"]
        assert paused.status_code == 200
        assert paused.json()["status"] == VerificationStatus.PAUSED
        assert paused_again.status_code == 409
        assert "只有进行中的验证可以暂停" in paused_again.json()["detail"]
        assert resumed.status_code == 200
        assert resumed.json()["status"] == VerificationStatus.RUNNING
        assert calls == ["pause", "resume"]


@pytest.mark.asyncio
async def test_pause_requires_existing_record(monkeypatch):
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)

    async with _harness() as (_session_factory, app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/vulnerabilities/vuln-1/verification/pause")

    assert response.status_code == 404
    assert "还没有动态验证记录" in response.json()["detail"]


@pytest.mark.asyncio
async def test_paused_verification_still_counts_as_active(monkeypatch):
    """暂停中的验证不能被“重新发起”按钮绕过。"""
    monkeypatch.setattr(settings, "VERIFICATION_AGENT_ENABLED", True)
    monkeypatch.setattr(endpoint, "run_vulnerability_verification", lambda verification_id: None)

    async with _harness() as (session_factory, app):
        async with session_factory() as db:
            db.add(
                VulnerabilityVerification(
                    id="v-paused",
                    vulnerability_id="vuln-1",
                    project_id="project-1",
                    status=VerificationStatus.PAUSED,
                )
            )
            await db.commit()

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/v1/vulnerabilities/vuln-1/verification")

    assert response.status_code == 409
    assert "v-paused" in response.json()["detail"]
