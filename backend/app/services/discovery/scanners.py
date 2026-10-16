from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
import threading
import time
from pathlib import Path

import httpx
import yaml

from app.core.config import settings
from app.services.agent.tools.sandbox_tool import SandboxConfig, SandboxManager
from app.services.discovery.scan_ingest import ObservationStore
from app.services.discovery.store import digest
from app.services.scan_runtime.executors.semgrep import CONTAINER_OUTPUT_PATH, SemgrepScanExecutor
from app.services.scan_runtime.models import DEFAULT_SEMGREP_CONFIGS, ScannerRequest


class ScannerAdapter:
    name = "SemgrepScan"

    async def prepare(self, *, run_id, artifact_root, session_factory=None):
        """Freeze the exact public rule bytes before either independent branch starts."""
        store = ObservationStore(session_factory)
        run = store.get(run_id)
        previous = run["scan_manifest"]
        if previous.get("rule_bundle"):
            return previous["rule_bundle"]
        directory = Path(artifact_root) / digest([run_id, "semgrep-v2"]) / "rules"
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o755)
        quota = min(run["config"]["artifact_quota_bytes"], 64 * 1024 * 1024)
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:

            async def fetch(number, config):
                target = directory / f"rules-{number}.yaml"
                data = bytearray()
                async with client.stream("GET", f"https://semgrep.dev/c/{config}") as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        data.extend(chunk)
                        if len(data) > quota // len(DEFAULT_SEMGREP_CONFIGS):
                            raise ValueError("Rule bundle exceeds storage quota")
                payload = yaml.safe_load(bytes(data))
                if not isinstance(payload.get("rules"), list) or not payload["rules"]:
                    raise ValueError(f"Registry returned no usable rules for {config}")
                temporary = target.with_suffix(".tmp")
                temporary.write_bytes(data)
                temporary.replace(target)
                target.chmod(0o444)
                return {
                    "config": config,
                    "filename": target.name,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "rule_count": len(payload["rules"]),
                }

            records = await asyncio.gather(
                *(fetch(n, config) for n, config in enumerate(DEFAULT_SEMGREP_CONFIGS)),
                return_exceptions=True,
            )
            failures = [str(record) for record in records if isinstance(record, BaseException)]
            if failures:
                raise ValueError("Rule preparation failed: " + "; ".join(failures))
        directory.chmod(0o555)
        bundle = {
            "directory": str(directory),
            "files": records,
            "version": digest(records),
            "prepared_at": time.time(),
        }
        prepared = {**previous, "rule_bundle": bundle, "status": "prepared"}
        prepared.pop("preparation_error", None)
        prepared.pop("reason", None)
        store.patch(run_id, scan_manifest=prepared)
        return bundle

    @staticmethod
    async def _import(store, run_id, artifact, **kwargs):
        cancel = threading.Event()
        job = asyncio.create_task(
            asyncio.to_thread(store.import_semgrep, run_id, artifact, cancel_event=cancel, **kwargs)
        )
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            cancel.set()
            await asyncio.shield(job)
            raise

    @staticmethod
    def applicable(profile):
        supported = {
            "python",
            "javascript",
            "typescript",
            "go",
            "java",
            "ruby",
            "php",
            "c",
            "cpp",
            "rust",
        }
        return bool(supported.intersection(profile.get("languages", [])))

    async def run(self, *, pipeline, run_id, artifact_root, session_factory=None):
        store = ObservationStore(session_factory)
        run = store.get(run_id)
        config = run["config"]
        manager = pipeline.sandbox_manager
        if isinstance(manager, SandboxManager):
            manager = SandboxManager(SandboxConfig(image=settings.DISCOVERY_SCANNER_IMAGE))
        scan_id = digest([run_id, "semgrep-v2"])
        artifact_dir = Path(artifact_root) / scan_id
        artifact_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        artifact_dir.chmod(0o700)
        previous = run["scan_manifest"]
        if previous.get("preparation_error"):
            return {**previous, "status": "failed"}
        if (
            previous.get("published_at")
            and not previous.get("ingestion_error")
            and not previous.get("not_imported_count")
        ):
            return previous
        # Crash recovery consumes already captured bytes without a second scan.
        existing = artifact_dir / "semgrep.json"
        if existing.exists() and existing.stat().st_size:
            return await self._import(
                store,
                run_id,
                existing,
                scan_run_id=scan_id,
                diagnostics=previous.get("diagnostics", {}),
                batch_size=config["write_batch_size"],
            )
        if not self.applicable(run["profile"]):
            manifest = {
                "status": "skipped",
                "raw_count": None,
                "indexed_count": 0,
                "ingestion_incomplete": True,
                "reason": "No supported Semgrep language detected",
            }
            store.patch(run_id, scan_manifest=manifest)
            return manifest
        request = ScannerRequest(
            scanner="SemgrepScan",
            configs=list(DEFAULT_SEMGREP_CONFIGS),
            target_paths=["."],
            timeout_seconds=config["scanner_timeout_seconds"],
        )
        executor = SemgrepScanExecutor(
            project_root=pipeline.project_root, sandbox_manager=pipeline.sandbox_manager
        )
        command = executor._build_command_summary(request)
        bundle = previous.get("rule_bundle")
        if isinstance(manager, SandboxManager) and not bundle:
            bundle = await self.prepare(
                run_id=run_id, artifact_root=artifact_root, session_factory=session_factory
            )
        if bundle:
            arguments = ["semgrep", "scan"]
            for record in bundle["files"]:
                arguments.extend(["--config", "/audit-rules/" + record["filename"]])
            arguments.extend(["--json-output", CONTAINER_OUTPUT_PATH, "--metrics=off", "."])
            command = shlex.join(arguments)
        diagnostic = {
            "command": command,
            "configs": request.configs,
            "target_paths": ["."],
            "excludes": run["snapshot"].get("exclude_patterns", []),
            "ruleset_version": bundle["version"] if bundle else None,
            "rule_bundle": bundle,
            "started_at": time.time(),
        }
        try:
            await manager.initialize()
            if not manager.is_available:
                raise RuntimeError(manager.get_diagnosis())
            await pipeline._emit("scanner_started", "Static Semgrep scan started", **diagnostic)
            result = await manager.execute_tool_command(
                command=command,
                host_workdir=str(pipeline.project_root),
                timeout=request.timeout_seconds,
                network_mode="none" if bundle else "bridge",
                env={"SEMGREP_ENABLE_VERSION_CHECK": "0"},
                readonly_rules_dir=bundle["directory"] if bundle else None,
                artifact_paths=[CONTAINER_OUTPUT_PATH],
                artifact_output_dir=str(artifact_dir),
                artifact_quota_bytes=config["artifact_quota_bytes"],
            )
            diagnostic.update(
                exit_code=result.get("exit_code"),
                stderr=result.get("stderr", ""),
                error=result.get("error"),
            )
            artifact = result.get("artifacts", {}).get(CONTAINER_OUTPUT_PATH, {})
            if artifact.get("error"):
                diagnostic["error"] = artifact["error"]
            artifact_path = Path(artifact.get("path") or existing)
            if artifact.get("content") and not artifact_path.exists():
                artifact_path.write_text(artifact["content"], encoding="utf-8")
            (artifact_dir / "diagnostics.json").write_text(
                json.dumps(diagnostic, ensure_ascii=False), encoding="utf-8"
            )
            store.patch(
                run_id,
                scan_manifest={
                    "diagnostics": diagnostic,
                    "status": "indexing",
                    "rule_bundle": bundle,
                },
            )
            if not artifact_path.exists() or not artifact_path.stat().st_size:
                raise ValueError("Semgrep produced no readable JSON artifact; raw count is unknown")
            return await self._import(
                store,
                run_id,
                artifact_path,
                scan_run_id=scan_id,
                diagnostics=diagnostic,
                batch_size=config["write_batch_size"],
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            retained = store.get(run_id)["scan_manifest"]
            manifest = {
                **retained,
                "status": "partial" if retained.get("indexed_count") else "failed",
                "raw_count": retained.get("raw_count"),
                "indexed_count": retained.get("indexed_count", 0),
                "ingestion_incomplete": True,
                "diagnostics": diagnostic,
                "reason": str(exc),
                "artifact_path": str(existing) if existing.exists() else None,
            }
            store.patch(run_id, scan_manifest=manifest)
            return manifest
