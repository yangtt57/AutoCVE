"""漏洞记录 -> 验证任务 的转换。"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.verification_agent.prompt import (
    VerificationTarget,
    build_task_payload,
    build_task_prompt,
)

RUN_ID = "run-xyz"


def _vulnerability(**overrides):
    values = {
        "id": "vuln-1",
        "vulnerability_name": "任意文件读取",
        "vulnerability_type": "path_traversal",
        "severity": "high",
        "project_name": "acme/portal",
        "repository_url_snapshot": "https://github.com/acme/portal",
        "version_label": "v1.4.2",
        "version_tag": "v1.4.2",
        "branch_name": "main",
        "commit_sha": "b" * 40,
        "file_path": "app/download.py",
        "line_start": 20,
        "line_end": 34,
        "source_metadata": {
            "raw_finding": {
                "detail": "用户可控的 f 参数直接拼进 open()",
                "source_point": "request.args['f']",
                "sink_location": "open(os.path.join(base, f))",
                "proof_of_concept": "GET /download?f=../../etc/passwd",
                "attack_chain": "未认证路由 -> 无过滤拼接 -> 读任意文件",
                "consequence": "读取服务器任意文件",
                "cve_reason": "远程可利用且无需认证",
                "verify_notes": "静态分析确认",
            }
        },
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_target_extracts_defensively_named_finding_fields():
    target = VerificationTarget.from_managed_vulnerability(_vulnerability())

    assert target.finding["description"] == "用户可控的 f 参数直接拼进 open()"
    assert target.finding["source"] == "request.args['f']"
    assert target.finding["sink"] == "open(os.path.join(base, f))"
    assert target.finding["poc"] == "GET /download?f=../../etc/passwd"
    assert target.finding["exploit_chain"] == "未认证路由 -> 无过滤拼接 -> 读任意文件"
    assert target.finding["impact"] == "读取服务器任意文件"
    assert target.finding["cve_justification"] == "远程可利用且无需认证"
    assert target.finding["verification_notes"] == "静态分析确认"


def test_target_tolerates_missing_metadata():
    target = VerificationTarget.from_managed_vulnerability(_vulnerability(source_metadata=None))
    assert target.finding == {}


def test_payload_carries_run_id_label_and_revision():
    target = VerificationTarget.from_managed_vulnerability(_vulnerability())
    payload = build_task_payload(target, run_id=RUN_ID, budget_seconds=1800, workspace="/verifier/work/x")

    assert payload["run_id"] == RUN_ID
    assert payload["container_label"] == {"autocve.verification": RUN_ID}
    assert payload["budget"]["seconds"] == 1800
    assert payload["repository"]["revision"]["commit_sha"] == "b" * 40
    assert payload["vulnerability"]["location"] == "app/download.py:20-34"
    assert payload["output"]["evidence_file"] == "EVIDENCE.json"


def test_prompt_includes_finding_details_and_rules_pointer():
    target = VerificationTarget.from_managed_vulnerability(_vulnerability())
    prompt = build_task_prompt(target, run_id=RUN_ID, budget_seconds=600, workspace="/verifier/work/x")

    assert "# 本次验证任务" in prompt
    assert RUN_ID in prompt
    assert "任意文件读取" in prompt
    assert "GET /download?f=../../etc/passwd" in prompt
    assert "/opt/verifier/verifier-rules.md" in prompt
    assert "EVIDENCE.json" in prompt
    assert "600 秒" in prompt


def test_prompt_reports_missing_revision_instead_of_guessing():
    target = VerificationTarget.from_managed_vulnerability(
        _vulnerability(commit_sha=None, version_tag=None, version_label=None)
    )
    prompt = build_task_prompt(target, run_id=RUN_ID, budget_seconds=600, workspace="/verifier/work/x")
    assert "未指定" in prompt
