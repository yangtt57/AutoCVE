"""验证报告的渲染。"""

from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.verification_agent.contract import normalize_evidence
from app.services.verification_agent.report import render_verification_report

RUN_ID = "run-abc"


def _evidence(**overrides):
    payload = {
        "run_id": RUN_ID,
        "verdict": "confirmed",
        "confidence": "high",
        "summary": "命令注入可通过 ping 参数触发。",
        "environment": {
            "method": "dockerfile",
            "app_url": "http://127.0.0.1:18080",
            "commit_sha": "deadbeef",
            "build_seconds": 75,
            "notes": "跳过了邮件模块",
        },
        "steps": [
            {
                "seq": 1,
                "intent": "验证命令注入",
                "command": "curl 'http://127.0.0.1:18080/ping?host=127.0.0.1;id'",
                "exit_code": 0,
                "stdout": "uid=1000(app) gid=1000(app)\n",
                "stderr": "",
            }
        ],
        "http_exchanges": [],
        "impact": "以应用身份执行任意命令。",
        "reproduction": ["docker build -t t .", "docker run -p 18080:80 t"],
        "limitations": ["未测试需要认证的管理接口"],
        "artifacts": [{"path": "notes/poc.sh", "sha256": "f" * 64, "bytes": 120}],
    }
    payload.update(overrides)
    return normalize_evidence(payload, run_id=RUN_ID)


def test_report_contains_verdict_evidence_and_metadata():
    markdown = render_verification_report(
        _evidence(),
        run_id=RUN_ID,
        model_provider="deepseek",
        model_id="deepseek-v4.1f",
        thinking_level="max",
        duration_seconds=845.5,
        evidence_digest="a" * 64,
    )

    assert "已确认（动态验证复现）" in markdown
    assert "deepseek/deepseek-v4.1f（thinking=max）" in markdown
    assert "uid=1000(app) gid=1000(app)" in markdown
    assert "curl 'http://127.0.0.1:18080/ping?host=127.0.0.1;id'" in markdown
    assert "未测试需要认证的管理接口" in markdown
    assert "notes/poc.sh" in markdown
    assert "14m05s" in markdown


def test_report_warns_when_not_confirmed():
    markdown = render_verification_report(
        _evidence(
            verdict="unverifiable",
            unverifiable_reason="需要企业版私有依赖，无法构建。",
            impact=None,
            reproduction=[],
        ),
        run_id=RUN_ID,
    )

    assert "不可验证" in markdown
    assert "需要企业版私有依赖，无法构建。" in markdown
    assert "不构成**漏洞成立的证据" in markdown


def test_report_code_fence_survives_backticks_in_output():
    markdown = render_verification_report(
        _evidence(
            steps=[
                {
                    "seq": 1,
                    "intent": "打印带围栏的输出",
                    "command": "echo '```'",
                    "exit_code": 0,
                    "stdout": "before\n```\ninside fenced\n```\nafter",
                    "stderr": "",
                }
            ]
        ),
        run_id=RUN_ID,
    )

    fence_start = markdown.index("````")
    assert fence_start > 0
    assert "inside fenced" in markdown


def test_report_renders_http_exchange():
    markdown = render_verification_report(
        _evidence(
            steps=[],
            http_exchanges=[
                {
                    "seq": 7,
                    "intent": "越权访问他人订单",
                    "request": {
                        "method": "GET",
                        "url": "http://127.0.0.1:18080/api/orders/42",
                        "headers": {"Cookie": "session=low-priv"},
                        "body": "",
                    },
                    "response": {"status": 200, "headers": {"Content-Type": "application/json"}, "body": '{"total":1337}'},
                }
            ],
        ),
        run_id=RUN_ID,
    )

    assert "`GET http://127.0.0.1:18080/api/orders/42` → `200`" in markdown
    assert '{"total":1337}' in markdown
    assert "session=low-priv" in markdown
