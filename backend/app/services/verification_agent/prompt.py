"""把一条已产出的漏洞记录转换成给验证 Agent 的任务。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# 静态审计产出的 raw_finding 里字段名不完全统一，按候选顺序取值。
_RAW_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "description": ("description", "detail", "details", "summary"),
    "source": ("source", "source_point", "source_location", "source_desc"),
    "sink": ("sink", "sink_point", "sink_location", "sink_desc"),
    "poc": ("poc", "poc_description", "poc_steps", "proof_of_concept"),
    "exploit_chain": ("exploit_chain", "attack_chain", "chain", "exploit"),
    "impact": ("impact", "impact_description", "consequence"),
    "cve_justification": ("cve_justification", "cve_reason", "justification"),
    "verification_notes": ("verification_notes", "verification", "verify_notes"),
    "suggestion": ("suggestion", "fix", "remediation"),
    "confidence": ("confidence", "confidence_level"),
}


@dataclass
class VerificationTarget:
    """一次验证的输入：一条漏洞记录 + 它所属项目/任务的定位信息。"""

    vulnerability_id: str
    vulnerability_name: str
    vulnerability_type: str | None = None
    severity: str | None = None

    project_name: str | None = None
    repository_url: str | None = None
    version_label: str | None = None
    version_tag: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None

    file_path: str | None = None
    line_start: int | None = None
    line_end: int | None = None

    finding: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_managed_vulnerability(cls, vulnerability: Any) -> "VerificationTarget":
        metadata = getattr(vulnerability, "source_metadata", None)
        raw_finding: dict[str, Any] = {}
        if isinstance(metadata, dict):
            candidate = metadata.get("raw_finding")
            if isinstance(candidate, dict):
                raw_finding = candidate
        return cls(
            vulnerability_id=str(vulnerability.id),
            vulnerability_name=str(vulnerability.vulnerability_name or ""),
            vulnerability_type=vulnerability.vulnerability_type,
            severity=vulnerability.severity,
            project_name=vulnerability.project_name,
            repository_url=vulnerability.repository_url_snapshot,
            version_label=vulnerability.version_label,
            version_tag=vulnerability.version_tag,
            branch_name=vulnerability.branch_name,
            commit_sha=vulnerability.commit_sha,
            file_path=vulnerability.file_path,
            line_start=vulnerability.line_start,
            line_end=vulnerability.line_end,
            finding=_extract_finding_fields(raw_finding),
        )

    def to_payload_dict(self) -> dict[str, Any]:
        location = None
        if self.file_path:
            location = self.file_path
            if self.line_start:
                location = f"{location}:{self.line_start}"
                if self.line_end and self.line_end != self.line_start:
                    location = f"{location}-{self.line_end}"
        return {
            "vulnerability_name": self.vulnerability_name,
            "vulnerability_type": self.vulnerability_type,
            "severity": self.severity,
            "project_name": self.project_name,
            "location": location,
            "file_path": self.file_path,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "finding": self.finding,
        }


def _extract_finding_fields(raw_finding: dict[str, Any]) -> dict[str, Any]:
    extracted: dict[str, Any] = {}
    for target_key, aliases in _RAW_FIELD_ALIASES.items():
        for alias in aliases:
            value = raw_finding.get(alias)
            if value not in (None, "", [], {}):
                extracted[target_key] = value
                break
    return extracted


def build_task_payload(
    target: VerificationTarget,
    *,
    run_id: str,
    budget_seconds: int,
    workspace: str,
) -> dict[str, Any]:
    """写入 ``TASK.json`` 的结构化任务描述。"""
    revision: dict[str, Any] = {
        "commit_sha": target.commit_sha,
        "version_tag": target.version_tag,
        "version_label": target.version_label,
        "branch": target.branch_name,
    }
    return {
        "run_id": run_id,
        "kind": "autocve.dynamic-verification",
        "workspace": workspace,
        "budget": {
            "seconds": budget_seconds,
            "note": "超过该预算仍未得出结论时，按 inconclusive 如实汇报卡在哪一步。",
        },
        "container_label": {"autocve.verification": run_id},
        "vulnerability": target.to_payload_dict(),
        "repository": {
            "url": target.repository_url,
            "revision": revision,
            "clone_note": "必须 checkout 到 revision 中给定的 commit 或 tag，并核对实际 HEAD。",
        },
        "output": {
            "evidence_file": "EVIDENCE.json",
            "rules_file": "/opt/verifier/verifier-rules.md",
            "final_message": "最后一条消息只输出 EVIDENCE.json 的完整 JSON 内容。",
        },
    }


def build_task_prompt(
    target: VerificationTarget,
    *,
    run_id: str,
    budget_seconds: int,
    workspace: str,
) -> str:
    """写入 ``TASK.md``，并作为 ``pi --print`` 的 prompt 传给 Agent。"""
    payload = build_task_payload(
        target,
        run_id=run_id,
        budget_seconds=budget_seconds,
        workspace=workspace,
    )
    finding = target.finding
    revision = payload["repository"]["revision"]
    revision_text = revision.get("commit_sha") or revision.get("version_tag") or revision.get("version_label") or "未指定"

    lines = [
        "# 本次验证任务",
        "",
        f"- run_id: `{run_id}`",
        f"- 工作目录: `{workspace}`（项目副本请 clone 到 `./target-repo`）",
        f"- 时间预算: {budget_seconds} 秒",
        f"- 容器标签: `autocve.verification={run_id}`",
        "",
        "## 待验证漏洞",
        "",
        f"- 名称: {target.vulnerability_name}",
        f"- 类型: {target.vulnerability_type or '未标注'}",
        f"- 严重级别: {target.severity or '未标注'}",
        f"- 项目: {target.project_name or '未标注'}",
        f"- 仓库: {target.repository_url or '未提供'}",
        f"- 版本定位: {revision_text}",
        f"- 位置: {payload['vulnerability']['location'] or '未标注'}",
        "",
    ]

    if finding.get("description"):
        lines += ["### 静态审计的描述", "", str(finding["description"]), ""]
    if finding.get("source") or finding.get("sink"):
        lines += [
            "### Source → Sink",
            "",
            f"- source: {finding.get('source', '未标注')}",
            f"- sink: {finding.get('sink', '未标注')}",
            "",
        ]
    if finding.get("exploit_chain"):
        lines += ["### 审计给出的利用链", "", _render_value(finding["exploit_chain"]), ""]
    if finding.get("poc"):
        lines += ["### 审计给出的 PoC", "", _render_value(finding["poc"]), ""]
    if finding.get("impact"):
        lines += ["### 审计声称的影响", "", _render_value(finding["impact"]), ""]
    if finding.get("cve_justification"):
        lines += ["### 审计给出的 CVE 理由", "", _render_value(finding["cve_justification"]), ""]
    if finding.get("verification_notes"):
        lines += ["### 审计的验证备注", "", _render_value(finding["verification_notes"]), ""]

    lines += [
        "## 你要做的事",
        "",
        "1. 先读 `TASK.json` 和上面的信息，在源码里核对 source→sink 是否真的连通。",
        "2. 设法把项目（或最小可运行子集）在 Docker 里真实跑起来，checkout 到指定版本。",
        "3. 先尝试**推翻**这个漏洞；推不翻再尝试坐实它并证明实际影响。",
        "4. 把原始证据（命令、输出、HTTP 请求与响应）写进 `EVIDENCE.json`。",
        "5. 拆掉你起的所有容器/网络/卷（按标签 `autocve.verification=" + run_id + "` 回收）。",
        "",
        "严格按 `/opt/verifier/verifier-rules.md` 里的证据格式和硬性约束执行。",
        "最后一条消息只输出 `EVIDENCE.json` 的完整 JSON 内容，不要加任何解释或 Markdown 代码块。",
    ]
    return "\n".join(lines)


def _render_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2)
    return str(value)
