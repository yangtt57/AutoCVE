"""Pi 容器的驱动逻辑（用假 Docker 对象，不需要真 Docker）。"""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.services.verification_agent.docker_runtime import (
    VerificationFiles,
    VerificationRuntimeError,
    VerifierDockerRuntime,
    raw_output_tail,
)


class _FakeContainer:
    """像真 docker-py 一样：暂停状态只存在 daemon 侧，``attrs`` 是快照。

    所以这里 ``pause()``/``unpause()`` **不**直接改 ``attrs``，只有 ``reload()`` 才同步——
    这样才测得出「忘了 reload 就会让继续失效」这个真 bug。
    """

    def __init__(self, *, status: str = "running", evidence: dict | None = None):
        self.status = status
        self.name = "autocve-pi-verifier"
        self.evidence = evidence
        self.archives: list[tuple[str, bytes]] = []
        self.execs: list[tuple[list[str], dict]] = []
        self.exec_result = (0, (b"final message\n", b""))
        self.removed = False
        self.pause_calls = 0
        self.unpause_calls = 0
        self.reloads = 0
        self._paused = status == "paused"
        self.attrs = {"State": {"Paused": self._paused, "Status": status}}

    def pause(self):
        self.pause_calls += 1
        self._paused = True

    def unpause(self):
        self.unpause_calls += 1
        self._paused = False

    def reload(self):
        self.reloads += 1
        self.status = "paused" if self._paused else "running"
        self.attrs = {"State": {"Paused": self._paused, "Status": self.status}}

    def exec_run(self, cmd, **kwargs):
        self.execs.append((cmd, kwargs))
        return self.exec_result

    def put_archive(self, path, data):
        self.archives.append((path, data))
        return True

    def get_archive(self, path):
        assert self.evidence is not None, "test did not provide evidence"
        payload = json.dumps(self.evidence).encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="EVIDENCE.json")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        return iter([buffer.getvalue()]), {}

    def remove(self, **kwargs):
        self.removed = True


class _FakeContainersApi:
    def __init__(self, container):
        self._container = container
        self.filters = None

    def get(self, name):
        if self._container is None:
            raise RuntimeError("No such container")
        return self._container

    def list(self, all=False, filters=None):
        self.filters = filters
        return [self._container] if self._container is not None else []


class _FakeNetworksApi:
    def __init__(self, names):
        self._names = names

    def list(self, filters=None):
        return [type("N", (), {"name": name, "remove": lambda self: None})() for name in self._names]


class _FakeVolumesApi:
    def __init__(self, names):
        self._names = names

    def list(self, filters=None):
        return [type("V", (), {"name": name, "remove": lambda self, force=False: None})() for name in self._names]


class _FakeClient:
    def __init__(self, container=None, networks=(), volumes=()):
        self.containers = _FakeContainersApi(container)
        self.networks = _FakeNetworksApi(list(networks))
        self.volumes = _FakeVolumesApi(list(volumes))


def _runtime(client, **kwargs):
    return VerifierDockerRuntime(client=client, **kwargs)


def test_workspace_path_uses_configured_root():
    runtime = _runtime(_FakeClient(), workspace_root="/verifier/work/")
    assert runtime.workspace_for("abc") == "/verifier/work/abc"


def test_missing_container_raises_actionable_error():
    runtime = _runtime(_FakeClient(container=None))
    with pytest.raises(VerificationRuntimeError, match="docker-compose.verify.yml"):
        runtime.ensure_container()


def test_non_running_container_is_rejected():
    runtime = _runtime(_FakeClient(container=_FakeContainer(status="exited")))
    with pytest.raises(VerificationRuntimeError, match="不是 running"):
        runtime.ensure_container()


def test_prepare_workspace_packs_files_into_archive():
    container = _FakeContainer()
    runtime = _runtime(_FakeClient(container))
    files = VerificationFiles()
    files.add_text("TASK.md", "# 任务")
    files.add_json("TASK.json", {"run_id": "abc"})

    runtime.prepare_workspace(container, "/verifier/work/abc", files)

    assert container.execs[0][0] == ["mkdir", "-p", "/verifier/work/abc"]
    path, data = container.archives[0]
    assert path == "/verifier/work/abc"
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        names = sorted(tar.getnames())
        assert names == ["TASK.json", "TASK.md"]
        assert json.loads(tar.extractfile("TASK.json").read().decode()) == {"run_id": "abc"}


def test_build_command_pins_tools_and_isolates_the_agent():
    runtime = _runtime(_FakeClient())
    command = runtime.build_command(
        prompt_file="TASK.md",
        model_provider="deepseek",
        model_id="deepseek-v4.1f",
        thinking_level="max",
    )
    joined = " ".join(command)

    assert "--print" in command
    assert "--no-session" in command
    assert "--no-context-files" in command
    assert "--no-skills" in command
    assert "--no-approve" in command
    assert "--tools" in command
    assert "read,write,edit,bash,grep,find,ls" in command
    # --tools / --model / --thinking 的值必须是**独立 argv**：
    # 写成 --tools=... 会被 Pi 当成未知选项直接退出（exit 1），验证一步都没跑就失败。
    assert not any(argument.startswith("--tools=") for argument in command)
    assert not any(argument.startswith("--model=") for argument in command)
    assert not any(argument.startswith("--thinking=") for argument in command)
    assert "--model deepseek/deepseek-v4.1f" in joined
    assert "--thinking max" in joined
    assert '--append-system-prompt /opt/verifier/verifier-rules.md' in joined
    assert '"$(cat TASK.md)"' in joined


async def test_run_agent_wraps_command_with_timeout():
    container = _FakeContainer()
    container.exec_result = (124, (b"", b"timeout"))
    runtime = _runtime(_FakeClient(container))

    result = await runtime.run_agent(
        container,
        workspace="/verifier/work/abc",
        prompt_file="TASK.md",
        timeout_seconds=900,
        model_provider="deepseek",
        model_id="m",
        thinking_level="max",
    )

    shell_command = container.execs[0][0][2]
    assert "cd /verifier/work/abc" in shell_command
    assert "timeout --signal=TERM --kill-after=60 900 pi" in shell_command
    assert result.exit_code == 124
    assert result.timed_out is True
    assert result.stderr == "timeout"


async def test_run_agent_extends_hard_timeout_by_pause_allowance():
    """暂停不能让预算白白流失：容器内的硬超时要加上允许的暂停额度。"""
    container = _FakeContainer()
    runtime = _runtime(_FakeClient(container))

    await runtime.run_agent(
        container,
        workspace="/verifier/work/abc",
        prompt_file="TASK.md",
        timeout_seconds=900,
        model_provider="deepseek",
        model_id="m",
        thinking_level="max",
        pause_allowance_seconds=14400,
    )

    shell_command = container.execs[0][0][2]
    assert "timeout --signal=TERM --kill-after=60 15300 pi" in shell_command


def test_pause_and_resume_agent_toggle_container_state():
    container = _FakeContainer()
    runtime = _runtime(_FakeClient(container))

    assert runtime.agent_is_paused(container) is False
    runtime.pause_agent(container)
    assert runtime.agent_is_paused(container) is True
    assert container.pause_calls == 1
    # 重复暂停是幂等的，不会重复调 Docker
    runtime.pause_agent(container)
    assert container.pause_calls == 1

    runtime.resume_agent(container)
    assert runtime.agent_is_paused(container) is False
    assert container.unpause_calls == 1
    # 没暂停时继续也是幂等的
    runtime.resume_agent(container)
    assert container.unpause_calls == 1


def test_agent_is_paused_reloads_stale_snapshot():
    """回归：Docker SDK 的 ``attrs`` 是快照，不 reload 会让「继续」失效。

    真容器上撞到过：``docker inspect`` 已经是 ``Paused=true``，但容器对象的 attrs
    还停在暂停前，于是 ``resume_agent`` 以为没暂停、直接跳过 unpause，
    容器就永远冻着。
    """
    container = _FakeContainer()
    runtime = _runtime(_FakeClient(container))

    runtime.pause_agent(container)
    # attrs 是快照：pause() 之后它还是老的 False。只读 attrs 的实现会在这里误判。
    assert container.attrs["State"]["Paused"] is False
    assert container._paused is True

    # 读状态必须先 reload，才能看到 daemon 侧的真实状态
    assert runtime.agent_is_paused(container) is True
    assert container.reloads >= 1

    runtime.resume_agent(container)
    assert container.unpause_calls == 1
    # 同样地：unpause() 之后 attrs 还是过期值，只能靠重新查询拿真相
    assert container.attrs["State"]["Paused"] is True
    assert runtime.agent_is_paused(container) is False
    assert container.status == "running"


def test_pause_still_recognises_paused_container_without_state_attrs():
    """没有 ``reload``（旧 SDK / 极简假对象）时退回看 ``status``。"""
    container = _FakeContainer()
    container.reload = None  # 模拟没有 reload 的旧 SDK / 极简假对象
    container.attrs = {}
    container.status = "paused"
    runtime = _runtime(_FakeClient(container))
    assert runtime.agent_is_paused(container) is True


def test_read_evidence_accepts_json_wrapped_in_prose_or_fences():
    runtime = _runtime(_FakeClient())
    fenced = _FakeContainer(evidence={"verdict": "refuted", "confidence": "low"})
    fenced.get_archive = lambda path: (
        iter([_tar_with_text("EVIDENCE.json", '```json\n{"verdict": "refuted", "confidence": "low"}\n```')]),
        {},
    )
    assert runtime.read_evidence(fenced, "/verifier/work/abc", "EVIDENCE.json")["verdict"] == "refuted"

    noisy = _FakeContainer()
    noisy.get_archive = lambda path: (
        iter([_tar_with_text("EVIDENCE.json", '这是结果：{"verdict": "unverifiable"} 以上。')]),
        {},
    )
    assert runtime.read_evidence(noisy, "/verifier/work/abc", "EVIDENCE.json")["verdict"] == "unverifiable"


def test_read_evidence_rejects_garbage():
    runtime = _runtime(_FakeClient())
    broken = _FakeContainer()
    broken.get_archive = lambda path: (iter([_tar_with_text("EVIDENCE.json", "not json at all")]), {})
    with pytest.raises(VerificationRuntimeError, match="不是合法的 JSON 对象"):
        runtime.read_evidence(broken, "/verifier/work/abc", "EVIDENCE.json")


def test_cleanup_removes_labeled_resources():
    container = _FakeContainer()
    client = _FakeClient(container, networks=["proj_default"], volumes=["proj_data"])
    runtime = _runtime(client)

    removed = runtime.cleanup_labeled_resources("run-1")

    assert container.removed is True
    assert client.containers.filters == {"label": "autocve.verification=run-1"}
    assert removed["networks"] == ["proj_default"]
    assert removed["volumes"] == ["proj_data"]


def test_raw_output_tail_keeps_the_end():
    text = raw_output_tail("A" * 100, "B" * 100, limit=50)
    assert text.startswith("...[truncated]")
    assert text.endswith("B" * 50)


def _tar_with_text(name: str, text: str) -> bytes:
    payload = text.encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name=name)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()
