"""集成冒烟测试：用真实 pi-verifier 容器跑一条最小的验证任务。

目的不是验证漏洞，而是验证"后端驱动容器"这一层的每个真实环节：
  prepare_workspace（put_archive 写 tar 进容器）
  → run_agent（docker exec pi --print，带 rules/工具白名单/thinking）
  → read_evidence（get_archive 取回 EVIDENCE.json）
  → contract.normalize_evidence（硬校验）
  → report.render_verification_report（渲染 markdown）
"""

# 注意：
#   - 这个脚本会**真的调一次模型**（便宜的 low thinking 短任务），用于验证管道而不是漏洞。
#   - Colima / 远程 docker 的机器上，宿主机跑的进程需要指定 socket，例如：
#       export DOCKER_HOST=unix://$HOME/.colima/default/docker.sock
#   - 后端跑在 docker compose 里时不需要，容器里有挂好的 socket。
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.core.config import settings
from app.services.verification_agent.contract import canonical_evidence_digest, normalize_evidence
from app.services.verification_agent.docker_runtime import (
    VerificationFiles,
    VerifierDockerRuntime,
    raw_output_tail,
)
from app.services.verification_agent.prompt import (
    VerificationTarget,
    build_task_payload,
    build_task_prompt,
)
from app.services.verification_agent.report import render_verification_report

RUN_ID = f"probe-{uuid4().hex}"
MODEL_PROVIDER = settings.VERIFICATION_AGENT_MODEL_PROVIDER
MODEL_ID = settings.VERIFICATION_AGENT_MODEL_ID

# 故意给一个"起不来"的目标：探针只验证管道，不验证漏洞。
TASK_MD = """你在做一次动态验证。目标项目 `acme/demo-portal` 在 GitHub 上并不存在，
所以这次注定走不到搭建环境那一步。

请严格按规则执行：
1. 真的尝试 `git clone https://github.com/acme/demo-portal /tmp/probe-clone` 一次，记录原始输出。
2. 确认 clone 失败、无法取得源码后，不要继续瞎猜。
3. 把 EVIDENCE.json 写到当前工作目录，内容必须符合规则里的结构，并且：
   - verdict = "unverifiable"
   - unverifiable_reason 里写清楚是取不到源码
   - 至少有一步 steps 带真实的 stdout/stderr 与 exit_code
   - limitations 不得为空
4. 最后一条消息只输出 EVIDENCE.json 的内容。
"""


async def main() -> int:
    if not MODEL_ID:
        raise RuntimeError("Set VERIFICATION_AGENT_MODEL_ID in backend/.env before running the smoke test")
    runtime = VerifierDockerRuntime()
    container = runtime.ensure_container()
    print(f"[1/6] 找到常驻容器: {container.name} ({container.status})")

    workspace = runtime.workspace_for(RUN_ID)
    class _Stub:
        id = "vuln-probe"
        vulnerability_name = "演示：路径穿越导致任意文件读取"
        vulnerability_type = "path_traversal"
        severity = "high"
        project_name = "acme/demo-portal"
        version_label = "v1.0.0"
        version_tag = "v1.0.0"
        branch_name = "main"
        commit_sha = None
        repository_url_snapshot = "https://github.com/acme/demo-portal"
        file_path = "app/routes/download.py"
        line_start = 42
        line_end = 48
        source_metadata = {
            "raw_finding": {
                "source": "request.args.get('file')",
                "sink": "open(path).read()",
                "poc": "curl 'http://target/download?file=../../etc/passwd'",
                "impact": "读取服务器任意文件",
            }
        }

    target = VerificationTarget.from_managed_vulnerability(_Stub())
    payload = build_task_payload(target, run_id=RUN_ID, budget_seconds=900, workspace=workspace)
    prompt = build_task_prompt(target, run_id=RUN_ID, budget_seconds=900, workspace=workspace) + "\n\n" + TASK_MD

    files = VerificationFiles()
    files.add_json("TASK.json", payload)
    files.add_text("TASK.md", prompt)
    runtime.prepare_workspace(container, workspace, files)
    print(f"[2/6] 已写入工作区: {workspace}")
    print("      容器内:", runtime.read_workspace_file(container, f"{workspace}/TASK.json")[:60].decode())

    print("[3/6] 让容器里的 Pi 真的跑一次（--print）...")
    result = await runtime.run_agent(
        container,
        workspace=workspace,
        prompt_file="TASK.md",
        model_provider=MODEL_PROVIDER,
        model_id=MODEL_ID,
        thinking_level="low",
        timeout_seconds=600,
    )
    print(f"      exit={result.exit_code} timed_out={result.timed_out}")
    print("      stdout 尾部:", (result.stdout or "")[-160:].replace("\n", " "))

    if result.timed_out:
        print("!! 超时了")
        return 1

    print("[4/6] 取回 EVIDENCE.json")
    evidence_raw = runtime.read_evidence(container, workspace, "EVIDENCE.json")
    print("      verdict =", evidence_raw.get("verdict"))
    print("      steps   =", len(evidence_raw.get("steps") or []))

    print("[5/6] 走证据契约校验")
    evidence = normalize_evidence(evidence_raw, run_id=RUN_ID)
    digest = canonical_evidence_digest(evidence)
    print("      digest  =", digest[:16], "…")
    print("      limitations =", evidence.get("limitations"))

    print("[6/6] 渲染 markdown 报告")
    markdown = render_verification_report(
        evidence,
        run_id=RUN_ID,
        model_provider=MODEL_PROVIDER,
        model_id=MODEL_ID,
        thinking_level="low",
        evidence_digest=digest,
    )
    out = Path("/tmp/probe-verification-report.md")
    out.write_text(markdown, encoding="utf-8")
    print(f"      写入 {out} ({len(markdown)} 字符)")

    print("[clean] 按标签回收容器/网络/卷:", runtime.cleanup_labeled_resources(RUN_ID))
    print("raw_output_tail:", raw_output_tail(result.stdout, result.stderr, limit=120))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
