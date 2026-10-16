"""编排一次动态验证：准备任务 -> 驱动 Pi 容器 -> 校验证据 -> 落库 + 出报告。"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.managed_vulnerability import ManagedVulnerability, ManagedVulnerabilityReport
from app.models.vulnerability_verification import (
    VerificationStatus,
    VulnerabilityVerification,
)
from app.services.managed_vulnerability_service import ManagedVulnerabilityService
from app.services.verification_agent.contract import (
    VerificationEvidenceError,
    canonical_evidence_digest,
    normalize_evidence,
)
from app.services.verification_agent.docker_runtime import (
    VerificationFiles,
    VerificationRuntimeError,
    VerifierDockerRuntime,
    raw_output_tail,
)
from app.services.verification_agent.prompt import (
    VerificationTarget,
    build_task_payload,
    build_task_prompt,
)
from app.services.verification_agent.report import render_verification_report

logger = logging.getLogger(__name__)

VERIFICATION_REPORT_KIND = "verification"
PROMPT_FILENAME = "TASK.md"
TASK_FILENAME = "TASK.json"
EVIDENCE_FILENAME = "EVIDENCE.json"

_GATES: dict[int, asyncio.Semaphore] = {}


def verification_concurrency_limit() -> int:
    try:
        return max(1, int(getattr(settings, "VERIFICATION_AGENT_MAX_CONCURRENCY", 1)))
    except (TypeError, ValueError):
        return 1


def _gate(limit: int) -> asyncio.Semaphore:
    """按配置的并发上限复用一个信号量；默认 1，也就是一次只跑一个项目环境。"""
    gate = _GATES.get(limit)
    if gate is None:
        gate = asyncio.Semaphore(limit)
        _GATES[limit] = gate
    return gate


def _agent_timeout_seconds() -> int:
    try:
        return max(60, int(getattr(settings, "VERIFICATION_AGENT_TIMEOUT_SECONDS", 3600)))
    except (TypeError, ValueError):
        return 3600


def verification_pause_allowance_seconds() -> int:
    """一次验证允许累计暂停多久（默认 4 小时）。

    容器里的 ``timeout`` 是墙钟，暂停期间照样在走；这个额度会被加到硬上限上，
    让「暂停不算时间」这句话成立。超过它就会被 timeout 兜底杀掉。
    """
    try:
        return max(0, int(getattr(settings, "VERIFICATION_AGENT_MAX_PAUSE_SECONDS", 14400)))
    except (TypeError, ValueError):
        return 14400


def _seconds_between(start: datetime, end: datetime) -> float:
    """两个时间点相差秒数，兼容 SQLite 取回的 naive datetime。"""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return (end - start).total_seconds()


def effective_duration_seconds(
    verification: VulnerabilityVerification, end: datetime
) -> float:
    """实际耗时 = 墙钟时长 - 累计暂停时长。

    ``paused_at`` 还在（暂停中就被收尾）时，把当前这段暂停也扣掉。
    """
    started_at = verification.started_at or end
    paused = float(verification.paused_seconds or 0.0)
    paused_at = verification.paused_at
    if paused_at is not None:
        paused += max(0.0, _seconds_between(paused_at, end))
    return max(0.0, _seconds_between(started_at, end) - paused)


def _model_settings() -> tuple[str, str, str]:
    provider = str(getattr(settings, "VERIFICATION_AGENT_MODEL_PROVIDER", "deepseek") or "deepseek")
    model_id = str(getattr(settings, "VERIFICATION_AGENT_MODEL_ID", "") or "")
    thinking = str(getattr(settings, "VERIFICATION_AGENT_THINKING_LEVEL", "max") or "max")
    return provider, model_id, thinking


async def run_vulnerability_verification(
    verification_id: str,
    *,
    runtime: VerifierDockerRuntime | None = None,
) -> None:
    """验证入口。任何异常都会落到记录的 ``status/error_message``，不会向上抛。"""
    runtime = runtime or VerifierDockerRuntime()
    provider, model_id, thinking = _model_settings()

    async with _gate(verification_concurrency_limit()):
        async with AsyncSessionLocal() as db:
            verification = await db.get(VulnerabilityVerification, verification_id)
            if verification is None:
                logger.warning("验证记录 %s 不存在，跳过", verification_id)
                return

            if not model_id:
                await _fail(
                    db,
                    verification,
                    "未配置验证模型（VERIFICATION_AGENT_MODEL_ID），无法启动动态验证。",
                )
                return

            vulnerability = await _load_vulnerability(db, verification.vulnerability_id)
            if vulnerability is None:
                await _fail(db, verification, "漏洞记录已不存在，无法验证。")
                return

            target = VerificationTarget.from_managed_vulnerability(vulnerability)
            run_id = str(verification.id)
            timeout_seconds = _agent_timeout_seconds()
            started_at = datetime.now(timezone.utc)

            verification.status = VerificationStatus.RUNNING
            verification.started_at = started_at
            verification.model_provider = provider
            verification.model_id = model_id
            verification.thinking_level = thinking
            verification.container_name = runtime.container_name
            verification.workspace_path = runtime.workspace_for(run_id)
            verification.error_message = None
            verification.paused_at = None
            verification.paused_seconds = 0.0
            await db.commit()

            stdout = ""
            stderr = ""
            try:
                container = runtime.ensure_container()
                workspace = runtime.workspace_for(run_id)
                files = VerificationFiles()
                files.add_json(
                    TASK_FILENAME,
                    build_task_payload(
                        target,
                        run_id=run_id,
                        budget_seconds=timeout_seconds,
                        workspace=workspace,
                    ),
                )
                files.add_text(
                    PROMPT_FILENAME,
                    build_task_prompt(
                        target,
                        run_id=run_id,
                        budget_seconds=timeout_seconds,
                        workspace=workspace,
                    ),
                )
                await asyncio.to_thread(runtime.prepare_workspace, container, workspace, files)

                result = await runtime.run_agent(
                    container,
                    workspace=workspace,
                    prompt_file=PROMPT_FILENAME,
                    timeout_seconds=timeout_seconds,
                    model_provider=provider,
                    model_id=model_id,
                    thinking_level=thinking,
                    pause_allowance_seconds=verification_pause_allowance_seconds(),
                )
                stdout, stderr = result.stdout, result.stderr

                payload = await asyncio.to_thread(
                    runtime.read_evidence, container, workspace, EVIDENCE_FILENAME
                )
                evidence = normalize_evidence(payload, run_id=run_id)
            except VerificationEvidenceError as exc:
                await _fail(
                    db,
                    verification,
                    f"验证 Agent 产出的证据不符合契约：{exc}",
                    stdout=stdout,
                    stderr=stderr,
                )
                return
            except VerificationRuntimeError as exc:
                await _fail(db, verification, str(exc), stdout=stdout, stderr=stderr)
                return
            except Exception as exc:  # pragma: no cover - 防御性兜底
                logger.exception("动态验证执行失败: %s", exc)
                await _fail(db, verification, f"动态验证执行失败：{exc}", stdout=stdout, stderr=stderr)
                return
            finally:
                # 无论成功失败都按标签回收，避免 Agent 漏拆的容器留在机器上。
                try:
                    await asyncio.to_thread(runtime.cleanup_labeled_resources, run_id)
                except Exception as exc:  # pragma: no cover
                    logger.warning("回收验证环境失败: %s", exc)

            await _store_success(
                db,
                verification,
                evidence=evidence,
                started_at=started_at,
                stdout=stdout,
                stderr=stderr,
            )


async def _load_vulnerability(db: AsyncSession, vulnerability_id: str) -> ManagedVulnerability | None:
    result = await db.execute(
        select(ManagedVulnerability)
        .options(selectinload(ManagedVulnerability.reports))
        .where(ManagedVulnerability.id == vulnerability_id)
    )
    return result.scalars().first()


async def _fail(
    db: AsyncSession,
    verification: VulnerabilityVerification,
    message: str,
    *,
    stdout: str = "",
    stderr: str = "",
) -> None:
    # 回滚可能带有未提交的中间状态，失败路径上要重新取一次记录。
    await db.rollback()
    fresh = await db.get(VulnerabilityVerification, verification.id)
    if fresh is None:
        return
    fresh.status = VerificationStatus.FAILED
    fresh.error_message = message
    fresh.completed_at = datetime.now(timezone.utc)
    fresh.duration_seconds = effective_duration_seconds(fresh, fresh.completed_at)
    fresh.paused_at = None
    fresh.raw_output_tail = raw_output_tail(stdout, stderr) or None
    await db.commit()


async def _store_success(
    db: AsyncSession,
    verification: VulnerabilityVerification,
    *,
    evidence: dict,
    started_at: datetime,
    stdout: str,
    stderr: str,
) -> None:
    completed_at = datetime.now(timezone.utc)
    digest = canonical_evidence_digest(evidence)
    duration = effective_duration_seconds(verification, completed_at)

    report = await _get_or_create_verification_report(db, verification.vulnerability_id)
    markdown = render_verification_report(
        evidence,
        run_id=str(verification.id),
        model_provider=verification.model_provider,
        model_id=verification.model_id,
        thinking_level=verification.thinking_level,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration,
        evidence_digest=digest,
    )

    verification.status = VerificationStatus.COMPLETED
    verification.verdict = evidence["verdict"]
    verification.confidence = evidence["confidence"]
    verification.summary = evidence["summary"]
    verification.impact = evidence["impact"]
    verification.refutation_reason = evidence["refutation_reason"]
    verification.unverifiable_reason = evidence["unverifiable_reason"]
    verification.environment_json = evidence["environment"]
    verification.evidence_json = evidence
    verification.limitations_json = evidence["limitations"]
    verification.artifacts_json = evidence["artifacts"]
    verification.evidence_digest = digest
    verification.completed_at = completed_at
    verification.duration_seconds = duration
    verification.paused_at = None
    verification.raw_output_tail = raw_output_tail(stdout, stderr) or None
    verification.error_message = None

    report.markdown_content = markdown
    report.generation_status = "completed"
    report.source_type = "dynamic_verification"
    report.last_generated_at = completed_at
    report.template_version = digest[:40]

    await db.commit()


async def _get_or_create_verification_report(
    db: AsyncSession, vulnerability_id: str
) -> ManagedVulnerabilityReport:
    """验证报告按需创建，不需要给历史漏洞做数据回填。"""
    result = await db.execute(
        select(ManagedVulnerabilityReport).where(
            ManagedVulnerabilityReport.vulnerability_id == vulnerability_id,
            ManagedVulnerabilityReport.report_kind == VERIFICATION_REPORT_KIND,
        )
    )
    report = result.scalars().first()
    if report is not None:
        return report
    report = ManagedVulnerabilityService(db).create_report_stub(
        vulnerability_id=vulnerability_id,
        report_kind=VERIFICATION_REPORT_KIND,
    )
    db.add(report)
    await db.flush()
    return report


# ---- 暂停 / 继续 -------------------------------------------------------


async def pause_verification(
    verification: VulnerabilityVerification,
    db: AsyncSession,
    *,
    runtime: VerifierDockerRuntime | None = None,
) -> VulnerabilityVerification:
    """冻结正在跑的验证。

    实现方式是把验证容器整体冻住（Docker pause）：Agent 的进程组停在原处，
    CPU 归零，也不会再调模型。解冻后从同一行代码继续，不需要重建环境。

    一个诚实的限制：如果冻住的时候正好在等模型回复，那条 HTTP 连接可能被
    服务端掐断，继续后这一轮会失败或被重试。所以短暂停（几分钟内）最稳。
    """
    runtime = runtime or VerifierDockerRuntime()
    container = runtime.ensure_container(allow_paused=True)
    await asyncio.to_thread(runtime.pause_agent, container)

    now = datetime.now(timezone.utc)
    verification.status = VerificationStatus.PAUSED
    verification.paused_at = now
    verification.error_message = None
    await db.commit()
    await db.refresh(verification)
    return verification


async def resume_verification(
    verification: VulnerabilityVerification,
    db: AsyncSession,
    *,
    runtime: VerifierDockerRuntime | None = None,
) -> VulnerabilityVerification:
    """解冻验证容器，并把这段暂停时长记到 ``paused_seconds`` 里。"""
    runtime = runtime or VerifierDockerRuntime()
    container = runtime.ensure_container(allow_paused=True)
    await asyncio.to_thread(runtime.resume_agent, container)

    now = datetime.now(timezone.utc)
    if verification.paused_at is not None:
        verification.paused_seconds = float(verification.paused_seconds or 0.0) + max(
            0.0, _seconds_between(verification.paused_at, now)
        )
    verification.paused_at = None
    verification.status = VerificationStatus.RUNNING
    await db.commit()
    await db.refresh(verification)
    return verification


# ---- 后端重启后的收尾 ---------------------------------------------------

#: 这些状态意味着「有后台任务在跑」。后端一重启，后台任务就没了，
#: 但记录还停在这些状态上，需要启动时收拾。
RECOVERABLE_STATUSES = (
    VerificationStatus.PENDING,
    VerificationStatus.RUNNING,
    VerificationStatus.PAUSED,
)


async def reconcile_interrupted_verifications(
    *, runtime: VerifierDockerRuntime | None = None
) -> dict[str, int]:
    """启动时收尾上一个进程留下的进行中验证。

    验证是跑在 web 进程的后台任务里的，后端一重启那个任务就没了。不处理的话
    前端会永远显示「验证中」。这里做两件事：

      1. 工作区里已经有完整合法的 ``EVIDENCE.json``（说明 Agent 其实跑完了，
         只是没人来读）→ 直接按成功落库，不白跑这一轮；
      2. 其余情况如实标记失败，并解冻容器、按标签回收环境。
    """
    counts = {"recovered": 0, "failed": 0}
    runtime = runtime or VerifierDockerRuntime()

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(VulnerabilityVerification).where(
                VulnerabilityVerification.status.in_(RECOVERABLE_STATUSES)
            )
        )
        stale_ids = [str(item.id) for item in result.scalars().all()]

    for verification_id in stale_ids:
        try:
            recovered = await _recover_or_fail(verification_id, runtime=runtime)
        except Exception as exc:  # pragma: no cover - 收尾不能拖垮启动
            logger.warning("收尾中断的验证 %s 失败: %s", verification_id, exc)
            continue
        counts["recovered" if recovered else "failed"] += 1
    return counts


async def _recover_or_fail(verification_id: str, *, runtime: VerifierDockerRuntime) -> bool:
    """返回 True 表示抢救成功（把已有证据落了库）。"""
    async with AsyncSessionLocal() as db:
        verification = await db.get(VulnerabilityVerification, verification_id)
        if verification is None:
            return False
        run_id = str(verification.id)
        workspace = verification.workspace_path or runtime.workspace_for(run_id)

        container = None
        try:
            container = runtime.ensure_container(allow_paused=True)
        except VerificationRuntimeError as exc:
            await _mark_interrupted(db, verification, f"后端重启，验证被中断：{exc}")
            return False

        # 先解冻：不然容器一直卡在暂停状态，下次也跑不了
        try:
            if runtime.agent_is_paused(container):
                await asyncio.to_thread(runtime.resume_agent, container)
        except Exception as exc:  # pragma: no cover
            logger.warning("解冻验证容器失败: %s", exc)

        evidence: dict | None = None
        reason = "Agent 没有产出完整证据"
        try:
            payload = await asyncio.to_thread(
                runtime.read_evidence, container, workspace, EVIDENCE_FILENAME
            )
            evidence = normalize_evidence(payload, run_id=run_id)
        except VerificationEvidenceError as exc:
            reason = f"Agent 留下的证据不符合契约：{exc}"
        except VerificationRuntimeError as exc:
            reason = f"Agent 没留下可用证据（{exc}）"

        if evidence is None:
            await _mark_interrupted(
                db,
                verification,
                f"后端重启，动态验证被中断，无法继续：{reason}",
                cleanup_workspace=True,
            )
            return False

        await _store_success(
            db,
            verification,
            evidence=evidence,
            started_at=verification.started_at or datetime.now(timezone.utc),
            stdout="",
            stderr="",
        )
        await asyncio.to_thread(runtime.cleanup_labeled_resources, run_id)
        logger.info("后端重启前已经跑完的验证 %s 已被抢救落库", run_id)
        return True


async def _mark_interrupted(
    db: AsyncSession,
    verification: VulnerabilityVerification,
    message: str,
    *,
    cleanup_workspace: bool = False,
) -> None:
    verification.status = VerificationStatus.FAILED
    verification.error_message = message
    verification.completed_at = datetime.now(timezone.utc)
    verification.duration_seconds = effective_duration_seconds(
        verification, verification.completed_at
    )
    verification.paused_at = None
    await db.commit()
    if cleanup_workspace:
        try:
            runtime = VerifierDockerRuntime()
            await asyncio.to_thread(runtime.cleanup_labeled_resources, str(verification.id))
        except Exception as exc:  # pragma: no cover
            logger.warning("回收中断验证的环境失败: %s", exc)


__all__ = [
    "VERIFICATION_REPORT_KIND",
    "RECOVERABLE_STATUSES",
    "effective_duration_seconds",
    "pause_verification",
    "reconcile_interrupted_verifications",
    "resume_verification",
    "run_vulnerability_verification",
    "verification_concurrency_limit",
    "verification_pause_allowance_seconds",
]
