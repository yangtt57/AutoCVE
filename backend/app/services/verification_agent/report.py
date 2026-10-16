"""把归一化后的证据渲染成可读的验证报告（存进 managed_vulnerability_reports）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

VERDICT_LABELS = {
    "confirmed": "已确认（动态验证复现）",
    "refuted": "已推翻（动态验证未能复现）",
    "inconclusive": "未能得出结论",
    "unverifiable": "不可验证",
}

CONFIDENCE_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
}

PREAMBLE = (
    "> 本报告由独立的动态验证 Agent（Pi，运行在隔离的 Docker 环境中）生成。\n"
    "> 报告只包含在真实运行实例上观察到的原始证据；未注明为动态验证的结论均不代表已复现。\n"
)


def render_verification_report(
    evidence: dict[str, Any],
    *,
    run_id: str,
    model_provider: str | None = None,
    model_id: str | None = None,
    thinking_level: str | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    duration_seconds: float | None = None,
    evidence_digest: str | None = None,
) -> str:
    verdict = str(evidence.get("verdict") or "inconclusive")
    confidence = str(evidence.get("confidence") or "")
    environment = evidence.get("environment") or {}

    lines: list[str] = [
        f"# 动态验证报告：{VERDICT_LABELS.get(verdict, verdict)}",
        "",
        PREAMBLE.strip(),
        "",
        "## 结论",
        "",
        f"- **判定**: {VERDICT_LABELS.get(verdict, verdict)}",
        f"- **置信度**: {CONFIDENCE_LABELS.get(confidence, confidence or '未标注')}",
    ]

    if verdict == "confirmed" and evidence.get("impact"):
        lines.append(f"- **实际影响**: {evidence['impact']}")
    if verdict == "refuted" and evidence.get("refutation_reason"):
        lines.append(f"- **推翻理由**: {evidence['refutation_reason']}")
    if verdict == "unverifiable" and evidence.get("unverifiable_reason"):
        lines.append(f"- **无法验证的原因**: {evidence['unverifiable_reason']}")

    lines += ["", evidence.get("summary") or "（Agent 未提供摘要）", ""]

    lines += [
        "## 验证环境",
        "",
        "| 项 | 值 |",
        "| --- | --- |",
        f"| 搭建方式 | {environment.get('method') or '未标注'} |",
        f"| 应用地址 | {environment.get('app_url') or '-'} |",
        f"| 实际 commit | {environment.get('commit_sha') or '-'} |",
        f"| 镜像 digest | {environment.get('image_digest') or '-'} |",
        f"| 构建耗时 | {_format_seconds(environment.get('build_seconds'))} |",
        f"| run_id | `{run_id}` |",
        f"| 模型 | {_format_model(model_provider, model_id, thinking_level)} |",
        f"| 开始 / 结束 | {_format_time(started_at)} / {_format_time(completed_at)} |",
        f"| 总耗时 | {_format_seconds(duration_seconds)} |",
        f"| 证据摘要 | `{evidence_digest or '-'}` |",
        "",
    ]
    if environment.get("notes"):
        lines += ["环境备注：", "", str(environment["notes"]), ""]

    reproduction = evidence.get("reproduction") or []
    if reproduction:
        lines += ["## 复现步骤", ""]
        for index, step in enumerate(reproduction, start=1):
            lines.append(f"{index}. {step}")
        lines.append("")

    steps = evidence.get("steps") or []
    if steps:
        lines += ["## 执行记录（原始输出）", ""]
        for step in steps:
            lines.append(f"### 步骤 {step.get('seq')}: {step.get('intent') or '（未说明意图）'}")
            lines.append("")
            if step.get("command"):
                lines += [_code_block(step["command"] or "", "bash"), ""]
            lines.append(f"exit_code: `{step.get('exit_code')}`")
            lines.append("")
            if step.get("stdout"):
                lines += ["stdout:", "", _code_block(step["stdout"], "text"), ""]
            if step.get("stderr"):
                lines += ["stderr:", "", _code_block(step["stderr"], "text"), ""]

    exchanges = evidence.get("http_exchanges") or []
    if exchanges:
        lines += ["## HTTP 交互（原始请求与响应）", ""]
        for exchange in exchanges:
            request = exchange.get("request") or {}
            response = exchange.get("response") or {}
            lines.append(
                f"### 请求 {exchange.get('seq')}: {exchange.get('intent') or '（未说明意图）'}"
            )
            lines.append("")
            lines.append(f"`{request.get('method')} {request.get('url')}` → `{response.get('status')}`")
            lines.append("")
            if request.get("headers"):
                lines += ["请求头:", "", _code_block(_format_headers(request["headers"]), "http"), ""]
            if request.get("body"):
                lines += ["请求体:", "", _code_block(request["body"], "http"), ""]
            if response.get("headers"):
                lines += ["响应头:", "", _code_block(_format_headers(response["headers"]), "http"), ""]
            if response.get("body"):
                lines += ["响应体:", "", _code_block(response["body"], "http"), ""]

    artifacts = evidence.get("artifacts") or []
    if artifacts:
        lines += ["## 证据产物", "", "| 路径 | 大小 | sha256 |", "| --- | ---: | --- |"]
        for artifact in artifacts:
            lines.append(
                f"| {artifact.get('path') or '-'} | {artifact.get('bytes') or 0} | `{artifact.get('sha256') or '-'}` |"
            )
        lines.append("")

    limitations = evidence.get("limitations") or []
    lines += ["## 本次验证未覆盖的部分", ""]
    if limitations:
        lines += [f"- {item}" for item in limitations]
    else:
        lines.append("- （Agent 未说明）")
    lines.append("")

    if verdict != "confirmed":
        lines += [
            "## 使用提示",
            "",
            "该结论**不构成**漏洞成立的证据，也不构成漏洞不成立的证据。",
            "如果要据此修改漏洞管理状态，请人工复核上面的原始输出。",
            "",
        ]

    return "\n".join(lines).rstrip() + "\n"


def _code_block(text: str, language: str) -> str:
    """输出围栏代码块；围栏长度自动超过正文里最长的反引号串，避免被正文截断。"""
    longest = 0
    current = 0
    for char in text:
        if char == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text}\n{fence}"


def _format_headers(headers: dict[str, Any]) -> str:
    return "\n".join(f"{key}: {value}" for key, value in headers.items())


def _format_model(provider: str | None, model_id: str | None, thinking_level: str | None) -> str:
    if not provider and not model_id:
        return "未记录"
    name = f"{provider or '?'}/{model_id or '?'}"
    if thinking_level:
        name = f"{name}（thinking={thinking_level}）"
    return name


def _format_time(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.strftime("%Y-%m-%d %H:%M:%S %Z").strip()


def _format_seconds(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}m{remainder:02d}s"
