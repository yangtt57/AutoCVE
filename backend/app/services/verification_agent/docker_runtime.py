"""通过 docker exec 驱动常驻的 Pi 验证容器。

为什么不把工作目录挂进后端容器：
  后端已经有宿主 docker.sock（现有沙箱就是这么用的），所以它可以直接用
  Docker API 往容器里塞文件、读文件、执行命令，不需要再多挂一个卷。
  这样验证功能的接入完全不依赖修改主 docker-compose.yml。

关于"写进去的代码进不了被测容器"这个经典坑：
  Pi 在它自己的容器里 clone 源码，然后用 ``docker build``/``docker run`` 交给
  兄弟 daemon 执行。路径是 daemon 解析的，所以 docker-compose.verify.yml 里把
  ``verifier-work`` 同时挂给了 pi-verifier 和 verifier-dind 的**同一个路径**。
  改这个 compose 文件时要保持这个不变量，否则跑起来的容器里是空的。
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tarfile
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger(__name__)

DEFAULT_RAW_OUTPUT_TAIL_CHARS = 20_000
LABEL_KEY = "autocve.verification"


class VerificationRuntimeError(RuntimeError):
    """验证运行时不可用或执行失败。"""


@dataclass
class PiRunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


@dataclass
class VerificationFiles:
    """要写进 Agent 工作目录的文件：相对路径 -> 内容。"""

    entries: dict[str, bytes] = field(default_factory=dict)

    def add_text(self, relative_path: str, content: str) -> None:
        self.entries[relative_path] = content.encode("utf-8")

    def add_json(self, relative_path: str, payload: Any) -> None:
        self.add_text(relative_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


class VerifierDockerRuntime:
    """封装所有对 pi-verifier 容器的操作，便于在测试里注入假实现。"""

    def __init__(
        self,
        *,
        client: Any | None = None,
        container_name: str | None = None,
        workspace_root: str | None = None,
        rules_path: str | None = None,
    ):
        self._client = client
        self.container_name = container_name or getattr(
            settings, "VERIFICATION_AGENT_CONTAINER", "autocve-pi-verifier"
        )
        self.workspace_root = (workspace_root or getattr(settings, "VERIFICATION_AGENT_WORKDIR", "/verifier/work")).rstrip("/")
        self.rules_path = rules_path or getattr(
            settings, "VERIFICATION_AGENT_RULES_PATH", "/opt/verifier/verifier-rules.md"
        )

    # ---- docker 客户端 -------------------------------------------------

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                import docker
            except ImportError as exc:  # pragma: no cover - 环境缺依赖时
                raise VerificationRuntimeError(
                    "Docker SDK 不可用，无法驱动验证 Agent。请确认后端容器已安装 docker 依赖。"
                ) from exc
            try:
                self._client = docker.from_env()
                self._client.ping()
            except Exception as exc:  # pragma: no cover - 依赖宿主环境
                self._client = None
                raise VerificationRuntimeError(
                    "无法连接 Docker，验证 Agent 不可用。请确认后端能访问 Docker daemon。"
                ) from exc
        return self._client

    def workspace_for(self, run_id: str) -> str:
        return f"{self.workspace_root}/{run_id}"

    def ensure_container(self, *, allow_paused: bool = False) -> Any:
        """找到常驻的验证容器。

        ``allow_paused=True`` 用于「暂停/继续/收尾」这些场景：容器被冻结时
        状态是 ``paused`` 而不是 ``running``，但对我们来说它仍然是可用的
        （可以解冻、可以直接读文件）。启动新的 Agent 运行必须用默认的
        ``allow_paused=False``，否则 exec 会一直挂在冻住的容器里。
        """
        try:
            container = self.client.containers.get(self.container_name)
        except Exception as exc:
            raise VerificationRuntimeError(
                f"验证容器 {self.container_name!r} 不存在。请先运行 "
                "`docker compose -f docker-compose.verify.yml up -d --build`。"
            ) from exc
        state = getattr(container, "status", None)
        accepted = {"running", "paused"} if allow_paused else {"running"}
        if state not in accepted:
            raise VerificationRuntimeError(
                f"验证容器 {self.container_name!r} 当前状态为 {state!r}，不是 running。"
            )
        return container

    # ---- 暂停 / 继续 ----------------------------------------------------

    def agent_is_paused(self, container: Any) -> bool:
        """容器是否处于冻结状态。

        Docker SDK 的 ``attrs`` 是**快照**，pause/unpause 之后不会自动更新。
        不 reload 直接读的话，``resume_agent`` 会以为容器没在暂停而跳过 unpause，
        容器就永远冻着——这是实测在真容器上撞到的坑，不是理论风险。
        """
        reload = getattr(container, "reload", None)
        if callable(reload):
            try:
                reload()
            except Exception:  # pragma: no cover - 容器刚好被删掉
                pass
        attrs = getattr(container, "attrs", None) or {}
        state = attrs.get("State") or {}
        if "Paused" in state:
            return bool(state["Paused"])
        return getattr(container, "status", None) == "paused"

    def pause_agent(self, container: Any) -> None:
        """冻结验证容器：进程停在原处，CPU 与 token 消耗都归零。"""
        if self.agent_is_paused(container):
            return
        try:
            container.pause()
        except Exception as exc:
            raise VerificationRuntimeError(f"暂停验证容器失败：{exc}") from exc

    def resume_agent(self, container: Any) -> None:
        """解冻验证容器，Agent 从暂停处继续跑。"""
        if not self.agent_is_paused(container):
            return
        try:
            container.unpause()
        except Exception as exc:
            raise VerificationRuntimeError(f"继续验证容器失败：{exc}") from exc

    # ---- 文件交换 ------------------------------------------------------

    def prepare_workspace(self, container: Any, workspace: str, files: VerificationFiles) -> None:
        container.exec_run(["mkdir", "-p", workspace])
        if not files.entries:
            return
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            for relative_path, content in files.entries.items():
                info = tarfile.TarInfo(name=relative_path)
                info.size = len(content)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(content))
        buffer.seek(0)
        if not container.put_archive(workspace, buffer.getvalue()):
            raise VerificationRuntimeError(f"无法把任务文件写入验证容器目录 {workspace}")

    def read_workspace_file(self, container: Any, path: str) -> bytes:
        try:
            stream, _stat = container.get_archive(path)
        except Exception as exc:
            raise VerificationRuntimeError(f"读取 {path} 失败：{exc}") from exc
        raw = b"".join(stream) if not isinstance(stream, (bytes, bytearray)) else bytes(stream)
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r") as tar:
            member = next((item for item in tar.getmembers() if item.isfile()), None)
            if member is None:
                raise VerificationRuntimeError(f"{path} 不是一个文件")
            fileobj = tar.extractfile(member)
            if fileobj is None:
                raise VerificationRuntimeError(f"无法读取 {path} 的内容")
            return fileobj.read()

    def read_evidence(self, container: Any, workspace: str, filename: str) -> dict[str, Any]:
        raw = self.read_workspace_file(container, f"{workspace}/{filename}")
        text = raw.decode("utf-8", errors="replace").strip()
        if not text:
            raise VerificationRuntimeError(f"{filename} 是空文件")
        payload = _loads_json_object(text)
        if payload is None:
            raise VerificationRuntimeError(f"{filename} 不是合法的 JSON 对象")
        return payload

    # ---- 执行 ----------------------------------------------------------

    def build_command(self, *, prompt_file: str, model_provider: str, model_id: str, thinking_level: str) -> list[str]:
        tools = getattr(
            settings,
            "VERIFICATION_AGENT_TOOLS",
            "read,write,edit,bash,grep,find,ls",
        )
        pi_args = [
            "pi",
            "--print",
            "--no-session",
            "--no-context-files",
            "--no-skills",
            "--no-mcp",
            "--no-extensions",
            "--no-approve",
            # 注意：--tools 必须拆成两个 argv，写成 --tools=read,... 会被 Pi 直接拒绝
            # （报 Unknown option: --tools，进程以 exit 1 结束，验证会一步都没跑就失败）。
            "--tools",
            tools,
            "--thinking",
            thinking_level,
            "--provider",
            model_provider,
            "--model",
            f"{model_provider}/{model_id}",
            "--append-system-prompt",
            self.rules_path,
            f'"$(cat {prompt_file})"',
        ]
        return pi_args

    async def run_agent(
        self,
        container: Any,
        *,
        workspace: str,
        prompt_file: str,
        timeout_seconds: int,
        model_provider: str,
        model_id: str,
        thinking_level: str,
        pause_allowance_seconds: int = 0,
    ) -> PiRunResult:
        pi_command = " ".join(self.build_command(
            prompt_file=prompt_file,
            model_provider=model_provider,
            model_id=model_id,
            thinking_level=thinking_level,
        ))
        # 容器里的 ``timeout`` 走的是墙钟：暂停期间进程被冻结，但墙钟照样在走。
        # 所以硬上限要加上「允许的累计暂停时长」，否则暂停一会儿就把预算耗光，
        # 一解冻就被 timeout 当场杀掉。
        hard_timeout = int(timeout_seconds) + max(0, int(pause_allowance_seconds))
        shell_command = (
            f"cd {workspace} && "
            f"timeout --signal=TERM --kill-after=60 {hard_timeout} {pi_command}"
        )
        try:
            exit_code, output = await asyncio.wait_for(
                asyncio.to_thread(
                    container.exec_run,
                    ["sh", "-lc", shell_command],
                    demux=True,
                ),
                timeout=hard_timeout + 120,
            )
        except asyncio.TimeoutError as exc:
            raise VerificationRuntimeError(
                f"验证 Agent 执行超过 {hard_timeout} 秒仍未返回（容器内 timeout 未生效）"
            ) from exc
        stdout_bytes, stderr_bytes = (output or (b"", b""))
        stdout = (stdout_bytes or b"").decode("utf-8", errors="replace")
        stderr = (stderr_bytes or b"").decode("utf-8", errors="replace")
        return PiRunResult(
            exit_code=int(exit_code),
            stdout=stdout,
            stderr=stderr,
            timed_out=int(exit_code) == 124,
        )

    # ---- 回收 ----------------------------------------------------------

    def cleanup_labeled_resources(self, run_id: str) -> dict[str, list[str]]:
        """按标签回收 Agent 留下的容器/网络/卷，作为它自己清理失败的兜底。"""
        label_filter = {"label": f"{LABEL_KEY}={run_id}"}
        removed: dict[str, list[str]] = {"containers": [], "networks": [], "volumes": []}
        try:
            client = self.client
        except VerificationRuntimeError:
            return removed

        for container in _safe_list(lambda: client.containers.list(all=True, filters=label_filter)):
            name = getattr(container, "name", None) or getattr(container, "id", "?")
            try:
                container.remove(force=True, v=True)
                removed["containers"].append(str(name))
            except Exception as exc:  # pragma: no cover - 清理失败不应影响主流程
                logger.warning("清理验证容器 %s 失败: %s", name, exc)

        for network in _safe_list(lambda: client.networks.list(filters=label_filter)):
            name = getattr(network, "name", None) or getattr(network, "id", "?")
            try:
                network.remove()
                removed["networks"].append(str(name))
            except Exception as exc:  # pragma: no cover
                logger.warning("清理验证网络 %s 失败: %s", name, exc)

        for volume in _safe_list(lambda: client.volumes.list(filters=label_filter)):
            name = getattr(volume, "name", None) or "?"
            try:
                volume.remove(force=True)
                removed["volumes"].append(str(name))
            except Exception as exc:  # pragma: no cover
                logger.warning("清理验证卷 %s 失败: %s", name, exc)

        return removed


def _safe_list(factory) -> list[Any]:
    try:
        return list(factory())
    except Exception as exc:  # pragma: no cover - daemon 异常不应中断流程
        logger.warning("列举待清理资源失败: %s", exc)
        return []


def _loads_json_object(text: str) -> dict[str, Any] | None:
    """容忍 Agent 把 JSON 包在 ``` 里或前后带解释文字的情况。"""
    candidates = [text]
    stripped = text.strip()
    if stripped.startswith("```"):
        candidate = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        candidate = candidate.rsplit("```", 1)[0]
        candidates.append(candidate.strip())
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        candidates.append(stripped[start : end + 1])
    for candidate in candidates:
        if not candidate:
            continue
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def raw_output_tail(*parts: str, limit: int = DEFAULT_RAW_OUTPUT_TAIL_CHARS) -> str:
    merged = "\n".join(part for part in parts if part)
    if len(merged) <= limit:
        return merged
    return "...[truncated]\n" + merged[-limit:]
