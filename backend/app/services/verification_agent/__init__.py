"""独立动态验证 Agent（Pi）接入层。

模块边界：
  - ``contract``       证据契约：结构校验、归一化、摘要计算
  - ``prompt``         把漏洞记录转成给 Agent 的任务（TASK.json / TASK.md）
  - ``docker_runtime`` 通过 docker exec 驱动常驻的 pi-verifier 容器
  - ``report``         把证据渲染成 markdown 报告
  - ``runner``         编排整个流程并把结果落库
"""

from app.services.verification_agent.contract import (
    CONFIDENCE_LEVELS,
    VERDICTS,
    VerificationEvidenceError,
    canonical_evidence_digest,
    normalize_evidence,
)
from app.services.verification_agent.prompt import VerificationTarget, build_task_payload, build_task_prompt

__all__ = [
    "CONFIDENCE_LEVELS",
    "VERDICTS",
    "VerificationEvidenceError",
    "VerificationTarget",
    "build_task_payload",
    "build_task_prompt",
    "canonical_evidence_digest",
    "normalize_evidence",
]
