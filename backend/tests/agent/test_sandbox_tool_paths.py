from __future__ import annotations

from types import SimpleNamespace

from app.core.config import settings
from app.services.agent.tools.sandbox_tool import SandboxManager


def test_sandbox_manager_maps_managed_workspace_to_host_root(monkeypatch):
    original_managed_root = settings.MANAGED_PROJECTS_ROOT
    settings.MANAGED_PROJECTS_ROOT = "/workspace/projects"
    monkeypatch.setenv("HOST_PROJECT_ROOT", r"D:\Projects\AutoCVE\projects")

    try:
        resolved = SandboxManager._resolve_docker_host_workdir(
            "/workspace/projects/.auditai_workspaces/task-1/chartbrew-4.9.0"
        )
    finally:
        settings.MANAGED_PROJECTS_ROOT = original_managed_root

    assert resolved == r"D:\Projects\AutoCVE\projects\.auditai_workspaces\task-1\chartbrew-4.9.0"


def test_linux_container_maps_named_volume_and_project_bind(monkeypatch):
    monkeypatch.delenv("HOST_PROJECT_ROOT", raising=False)
    container = SimpleNamespace(attrs={"Mounts": [
        {"Destination": "/app/uploads", "Source": "/var/lib/docker/volumes/autocve_uploads/_data"},
        {"Destination": "/workspace/projects", "Source": "/srv/autocve/projects"},
    ]})
    client = SimpleNamespace(containers=SimpleNamespace(get=lambda _: container))
    assert SandboxManager._resolve_docker_host_workdir(
        "/app/uploads/discovery_v2/source-123/Main.java", client
    ) == "/var/lib/docker/volumes/autocve_uploads/_data/discovery_v2/source-123/Main.java"
    assert SandboxManager._resolve_docker_host_workdir(
        "/workspace/projects/my project/src", client
    ) == "/srv/autocve/projects/my project/src"
    assert SandboxManager._resolve_docker_host_workdir(
        "/app/uploads-other/file", client
    ) == "/app/uploads-other/file"


def test_native_linux_path_does_not_require_container_inspection(monkeypatch):
    monkeypatch.delenv("HOST_PROJECT_ROOT", raising=False)
    assert SandboxManager._resolve_docker_host_workdir(
        "/srv/autocve/backend/uploads/source-1"
    ) == "/srv/autocve/backend/uploads/source-1"
