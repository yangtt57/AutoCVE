"""证据契约的校验规则 —— 这是"真实验证"与"模型嘴炮"的分界线。"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.verification_agent.contract import (
    VerificationEvidenceError,
    canonical_evidence_digest,
    normalize_evidence,
)

RUN_ID = "run-123"


def _base_payload(**overrides):
    payload = {
        "run_id": RUN_ID,
        "verdict": "confirmed",
        "confidence": "high",
        "summary": "路径穿越可以读到 /etc/passwd。",
        "environment": {
            "method": "compose",
            "app_url": "http://127.0.0.1:18080",
            "commit_sha": "a" * 40,
            "build_seconds": 91,
        },
        "steps": [
            {
                "seq": 1,
                "intent": "发送穿越 payload",
                "command": "curl 'http://127.0.0.1:18080/download?f=../../../../etc/passwd'",
                "exit_code": 0,
                "stdout": "root:x:0:0:root:/root:/bin/bash\n",
                "stderr": "",
            }
        ],
        "http_exchanges": [],
        "impact": "任意文件读取，可导出凭据。",
        "reproduction": ["docker compose up -d", "curl 上述 URL"],
        "limitations": [],
        "artifacts": [],
    }
    payload.update(overrides)
    return payload


def test_normalizes_valid_confirmed_evidence():
    evidence = normalize_evidence(_base_payload(), run_id=RUN_ID)

    assert evidence["verdict"] == "confirmed"
    assert evidence["confidence"] == "high"
    assert evidence["environment"]["method"] == "compose"
    assert evidence["environment"]["build_seconds"] == 91
    assert evidence["steps"][0]["stdout"].startswith("root:x")
    assert evidence["limitations"] == []


def test_rejects_confirmed_without_raw_evidence():
    payload = _base_payload(
        steps=[{"seq": 1, "intent": "看了看代码", "command": "cat app.py", "exit_code": 0, "stdout": "", "stderr": ""}],
        http_exchanges=[],
    )
    with pytest.raises(VerificationEvidenceError, match="raw stdout"):
        normalize_evidence(payload, run_id=RUN_ID)


def test_rejects_confirmed_without_reproduction_or_impact():
    with pytest.raises(VerificationEvidenceError, match="reproduction"):
        normalize_evidence(_base_payload(reproduction=[]), run_id=RUN_ID)

    with pytest.raises(VerificationEvidenceError, match="impact"):
        normalize_evidence(_base_payload(impact=None), run_id=RUN_ID)


def test_rejects_refuted_without_reason():
    payload = _base_payload(verdict="refuted", confidence="medium", refutation_reason=None)
    with pytest.raises(VerificationEvidenceError, match="refutation_reason"):
        normalize_evidence(payload, run_id=RUN_ID)


def test_rejects_unverifiable_without_reason():
    payload = _base_payload(verdict="unverifiable", unverifiable_reason="  ")
    with pytest.raises(VerificationEvidenceError, match="unverifiable_reason"):
        normalize_evidence(payload, run_id=RUN_ID)


def test_rejects_unknown_verdict_and_confidence():
    with pytest.raises(VerificationEvidenceError, match="verdict must be one of"):
        normalize_evidence(_base_payload(verdict="maybe"), run_id=RUN_ID)

    with pytest.raises(VerificationEvidenceError, match="confidence must be one of"):
        normalize_evidence(_base_payload(confidence="sure"), run_id=RUN_ID)


def test_rejects_run_id_mismatch_and_non_object():
    with pytest.raises(VerificationEvidenceError, match="run_id mismatch"):
        normalize_evidence(_base_payload(run_id="other"), run_id=RUN_ID)

    with pytest.raises(VerificationEvidenceError, match="JSON object"):
        normalize_evidence(["not", "an", "object"], run_id=RUN_ID)


def test_rejects_malformed_http_exchange():
    payload = _base_payload(http_exchanges=[{"seq": 1, "request": {"method": "GET"}}])
    with pytest.raises(VerificationEvidenceError, match="'request' and 'response'"):
        normalize_evidence(payload, run_id=RUN_ID)


def test_http_exchange_body_counts_as_raw_evidence():
    payload = _base_payload(
        steps=[],
        http_exchanges=[
            {
                "seq": 1,
                "intent": "越权读取",
                "request": {"method": "GET", "url": "http://127.0.0.1:18080/api/users/2", "headers": {}},
                "response": {"status": 200, "headers": {}, "body": '{"email":"victim@example.com"}'},
            }
        ],
    )
    evidence = normalize_evidence(payload, run_id=RUN_ID)
    assert evidence["http_exchanges"][0]["request"]["method"] == "GET"
    assert "victim@example.com" in evidence["http_exchanges"][0]["response"]["body"]


def test_long_fields_are_truncated_and_marked():
    payload = _base_payload(steps=[{"seq": 1, "intent": "x", "command": "y", "exit_code": 0, "stdout": "A" * 50_000}])
    evidence = normalize_evidence(payload, run_id=RUN_ID)
    stdout = evidence["steps"][0]["stdout"]
    assert len(stdout) < 21_000
    assert stdout.endswith("[truncated]")


def test_total_evidence_budget_is_enforced():
    steps = [
        {
            "seq": index,
            "intent": "step",
            "command": "cmd",
            "exit_code": 0,
            "stdout": "B" * 19_000,
            "stderr": "C" * 19_000,
        }
        for index in range(1, 40)
    ]
    evidence = normalize_evidence(_base_payload(steps=steps), run_id=RUN_ID, max_total_chars=50_000)

    encoded = json.dumps(evidence, ensure_ascii=False, separators=(",", ":"))
    assert len(encoded) <= 50_000
    # confirmed 所依赖的"至少一条原始输出"必须活下来
    assert evidence["steps"]
    assert evidence["steps"][0]["stdout"]


def test_whitespace_only_fields_do_not_count_as_provided():
    # “看来填了” 不算证据：纯空白必须当作没填。
    payload = _base_payload(
        steps=[{"seq": 1, "intent": "x", "command": "y", "exit_code": 0, "stdout": "   \n  ", "stderr": "  "}],
        http_exchanges=[],
    )
    with pytest.raises(VerificationEvidenceError, match="raw stdout"):
        normalize_evidence(payload, run_id=RUN_ID)

    with pytest.raises(VerificationEvidenceError, match="impact"):
        normalize_evidence(_base_payload(impact="   "), run_id=RUN_ID)

    with pytest.raises(VerificationEvidenceError, match="reproduction"):
        normalize_evidence(_base_payload(reproduction=["  ", ""]), run_id=RUN_ID)


def test_raw_output_whitespace_is_preserved_for_evidence():
    payload = _base_payload(
        steps=[
            {
                "seq": 1,
                "intent": "保持原样",
                "command": "cat out.txt",
                "exit_code": 0,
                "stdout": "  indented\n\n\n",
                "stderr": "",
            }
        ]
    )
    evidence = normalize_evidence(payload, run_id=RUN_ID)
    assert evidence["steps"][0]["stdout"] == "  indented\n\n\n"


def test_evidence_digest_is_stable_and_sensitive():
    first = normalize_evidence(_base_payload(), run_id=RUN_ID)
    second = normalize_evidence(_base_payload(), run_id=RUN_ID)
    assert canonical_evidence_digest(first) == canonical_evidence_digest(second)

    changed = normalize_evidence(_base_payload(impact="只影响自己"), run_id=RUN_ID)
    assert canonical_evidence_digest(first) != canonical_evidence_digest(changed)
