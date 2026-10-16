"""Pinned, data-only skill routing for discovery. No legacy bindings or plugin execution."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path, PurePosixPath

from pydantic import BaseModel, Field

from app.models.discovery import DiscoveryEvidence
from app.services.discovery.candidate_store import CandidateStore
from app.services.discovery.store import RunStore, digest, require_attempt
from app.services.skill_file_service import SkillFileService

MAX_SKILL_BYTES = 128 * 1024
MAX_READ_CHARS = 14000
CATALOG_PATH = ".discovery/manifest.json"


def catalog_snapshot():
    path = SkillFileService.library_root() / CATALOG_PATH
    if not path.is_file():
        return {"status": "unavailable", "packages": {}, "reason": "Pinned skill catalog missing"}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported discovery skill catalog")
    return {**data, "status": "available", "catalog_hash": digest(data)}


def source_signals(index):
    """Routing hints only; no findings, coverage, or new parser capability claims."""
    records = []
    code_ext = {
        ".py",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".go",
        ".rs",
        ".java",
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".hpp",
        ".cxx",
        ".swift",
        ".kt",
        ".m",
        ".mm",
        ".cs",
        ".php",
        ".rb",
        ".kts",
    }
    for path in sorted(index.snapshot["files"]):
        name, suffix = Path(path).name.lower(), Path(path).suffix.lower()
        text = index.texts.get(path, "")
        signals = set()
        if suffix in {".c", ".h", ".cpp", ".cc", ".hpp", ".cxx"}:
            signals.add("native")
        if suffix == ".rs":
            signals.add("rust")
        if suffix == ".py" and re.search(r"\b(?:from|import)\s+(?:django|rest_framework)\b", text):
            signals.update({"django", "web_api"})
        if (
            path.startswith(".github/workflows/")
            and suffix in {".yaml", ".yml"}
            or name in {"action.yml", "action.yaml"}
        ):
            signals.update({"github_actions", "supply_chain"})
        if name in {
            "package.json",
            "package-lock.json",
            "pyproject.toml",
            "requirements.txt",
            "cargo.toml",
            "cargo.lock",
            "go.mod",
            "go.sum",
            "uv.lock",
            "poetry.lock",
            "pom.xml",
            "build.gradle",
            "build.gradle.kts",
            "composer.json",
            "composer.lock",
            "gemfile",
            "gemfile.lock",
            "packages.lock.json",
        }:
            signals.update({"dependencies", "supply_chain"})
        if (
            suffix in {".tf", ".tfvars"}
            or name.startswith(("dockerfile", "docker-compose", "compose."))
            or re.search(
                r"\b(?:apiVersion:|AWSTemplateFormatVersion|aws_iam|kubernetes_|wrangler)",
                text if suffix in {".yaml", ".yml", ".toml", ".json"} else "",
            )
        ):
            signals.add("cloud")
        if suffix in code_ext or signals & {"github_actions", "cloud"}:
            if re.search(
                r"\b(?:langchain|litellm|openai|anthropic|mcp|tool_calls|tool_call_id)\b",
                text,
                re.I,
            ):
                signals.add("ai_agent")
            if re.search(
                r"\b(?:grpc|protobuf|basic_consume|process_message|on_message|KafkaConsumer|shared_task)\b|@\w+\.task\b",
                text,
                re.I,
            ):
                signals.update({"background_service", "resource"})
            if re.search(
                r"\b(?:tenant_id|owner_id|organization_id|org_id|row_level_security)\b", text
            ):
                signals.add("data_isolation")
            if re.search(
                r"\b(?:postMessage|innerHTML|dangerouslySetInnerHTML|document\.write|createRoot)\b",
                text,
            ) or suffix in {".tsx", ".jsx"}:
                signals.add("client_side")
            if re.search(
                r"\b(?:WebView|WKWebView|ipcMain|ipcRenderer|XPC|Binder|AF_UNIX|UnixStream|DBus)\b",
                text,
            ) or name in {"androidmanifest.xml", "info.plist"}:
                signals.add("local_ipc")
            if re.search(
                r"@\w+(?:\.\w+)*\.(?:route|get|post|put|delete|patch)\(|\b(?:app|router)\.(?:get|post|use)\(",
                text,
            ):
                signals.add("web_api")
            if suffix in code_ext and re.search(
                r"\b(?:api_key|password|client_secret|access_token|credential|secretstr)\b",
                text,
                re.I,
            ):
                signals.add("credentials")
            if re.search(
                r"\b(?:getenv|environ|process\.env|verify_ssl|DEBUG)\b", text
            ) or re.search(r"config|settings", name):
                signals.add("configuration")
        if name in {"androidmanifest.xml", "info.plist"} or suffix == ".entitlements":
            signals.add("local_ipc")
        if signals:
            records.append(
                {"file_path": path, "signals": sorted(signals), "basis": "source_text_heuristic"}
            )
    return records


def in_scope(path, scopes):
    return any(s == "." or path == s or path.startswith(s.rstrip("/") + "/") for s in scopes)


DOMAIN_RESOURCES = {
    "ai_agent": "AI-AND-LLM",
    "web_api": "WEB-PROTOCOL-AND-AUTH",
    "client_side": "CLIENT-SIDE",
    "native": "MEMORY-SAFETY-AND-BINARY",
    "rust": "MEMORY-SAFETY-AND-BINARY",
    "cloud": "CLOUD-AND-DEPLOYMENT",
    "background_service": "PROTOCOLS-RPC-AND-MESSAGING",
    "resource": "RESOURCE-EXHAUSTION-AND-AVAILABILITY",
    "data_isolation": "DATA-ISOLATION-AND-LIFECYCLE",
    "supply_chain": "SUPPLY-CHAIN-AND-RELEASE",
    "local_ipc": "DESKTOP-MOBILE-AND-LOCAL-IPC",
}


def plan_skills(run, task, candidates=()):
    catalog = run["profile"].get("skills_catalog", {})
    packages = catalog.get("packages", {})
    payload, phase = task["payload"], task["phase"]
    hints = [
        r
        for r in run["profile"].get("skill_signals", [])
        if in_scope(r["file_path"], payload.get("entry_files") or payload.get("scope", ["."]))
    ]
    signals = {s for r in hints for s in r["signals"]}
    kind = payload.get("profile", "")
    if kind and kind != "source":
        signals.add(kind)
    main = (
        "autocve-code-audit"
        if kind == "web_api"
        or "web_api" in signals
        and kind not in {"cli", "library_sdk", "background_service"}
        else "autocve-context-building"
    )
    selected, unavailable = [], []

    def add(slug, role, reason, resources=None):
        entry = packages.get(slug)
        if not entry or phase not in entry["stages"] or entry["runtime"] != "discovery_v2":
            unavailable.append(slug)
            return
        selected.append(
            {
                "slug": slug,
                "name": entry["name"],
                "role": role,
                "reason": reason,
                "resources": resources or ["SKILL.md"],
                "adaptation_version": entry["adaptation_version"],
            }
        )

    main_resources = ["SKILL.md"]
    if main == "autocve-context-building":
        main_resources.append("references/analysis-format.md")
    add(main, "method", "One primary method for this work package", main_resources)
    specialty = None
    # Narrow task focus wins over broad repository signals. All eligibility is source/ledger based.
    if (
        payload.get("spec_paths")
        and payload.get("spec_basis")
        and all(p in run["snapshot"]["files"] for p in payload["spec_paths"])
    ):
        specialty = "autocve-spec-compliance"
    elif payload.get("changed_paths") and payload.get("comparison_basis"):
        specialty = "autocve-differential-review"
    elif phase == "expansion" and any(c.get("source_evidence_available") for c in candidates):
        specialty = "autocve-variant-analysis"
    elif phase != "independent" and payload.get("observation_ids"):
        specialty = (
            "autocve-sarif-interpretation"
            if run.get("scan_manifest", {}).get("format") == "sarif"
            else "autocve-semgrep-feedback"
        )
    elif "github_actions" in signals:
        specialty = "autocve-agentic-actions" if "ai_agent" in signals else "autocve-gha-review"
    elif "native" in signals:
        specialty = "autocve-native-c-review"
    elif "rust" in signals:
        specialty = "autocve-rust-review"
    elif "django" in signals:
        specialty = "autocve-django-access"
    elif "credentials" in signals:
        specialty = "autocve-secret-serialization"
    elif "configuration" in signals:
        specialty = "autocve-insecure-defaults"
    elif "dependencies" in signals:
        specialty = "autocve-supply-chain"
    elif kind in {"library_sdk", "cli"}:
        specialty = "autocve-sharp-edges"
    if specialty:
        add(
            specialty,
            "specialty",
            "Selected by task phase, scope and source signals",
            ["SKILL.md"] + packages.get(specialty, {}).get("default_resources", []),
        )
    priorities = [
        "local_ipc",
        "ai_agent",
        "cloud",
        "native",
        "rust",
        "background_service",
        "data_isolation",
        "web_api",
        "client_side",
        "supply_chain",
        "resource",
    ]
    # Ensure a known role's domain is considered first (e.g. worker in a mixed web repo).
    if kind in DOMAIN_RESOURCES:
        priorities = [kind] + [s for s in priorities if s != kind]
    domains = []
    for signal in priorities:
        name = DOMAIN_RESOURCES[signal]
        if signal in signals and name not in domains:
            domains.append(name)
    if domains:
        add(
            "autocve-cloudflare-domains",
            "domain",
            "At most two relevant domain references",
            ["SKILL.md"] + [f"references/{name}.md" for name in domains[:2]],
        )
    return {
        "catalog_version": catalog.get("catalog_version"),
        "catalog_hash": catalog.get("catalog_hash"),
        "selected": selected,
        "signals": sorted(signals),
        "unavailable": unavailable,
        "limits": {"primary_methods": 1, "specialties": 1, "domain_references": 2},
        "policy": "Read selected SKILL.md bodies first, then only the relevant listed references. Skill reading is not source coverage.",
    }


class SkillReadInput(BaseModel):
    skill_ref: str
    action: str = Field("body", pattern="^(body|list_resources|read_resource)$")
    resource_name: str | None = None
    start_line: int = Field(1, ge=1)
    end_line: int | None = Field(None, ge=1)


class DiscoverySkillRuntime(RunStore):
    def __init__(self, run, task, session_factory=None, library_root=None):
        super().__init__(session_factory)
        self.run, self.task = run, task
        self.root = Path(library_root or SkillFileService.library_root()).resolve()
        self.packages = run["profile"].get("skills_catalog", {}).get("packages", {})
        with self.sf.begin() as db:
            current = require_attempt(db, task["id"], task["attempt_id"])
            plan = current.checkpoint.get("skills_plan")
            if plan is None:
                ids = list(
                    dict.fromkeys(
                        task["payload"].get("candidate_ids", [])
                        + current.checkpoint.get("candidate_ids", [])
                    )
                )
                candidates = [CandidateStore(self.sf).candidate(run["id"], cid) for cid in ids]
                for candidate in candidates:
                    candidate["source_evidence_available"] = any(
                        (evidence := db.get(DiscoveryEvidence, eid))
                        and evidence.run_id == run["id"]
                        and evidence.kind == "source"
                        for eid in candidate.get("supporting_evidence_ids", [])
                    )
                plan = plan_skills(run, task, candidates)
                current.checkpoint = {**current.checkpoint, "skills_plan": plan}
            self.plan = copy.deepcopy(plan)
        task["checkpoint"] = {**task["checkpoint"], "skills_plan": self.plan}

    def invoke(self, value: SkillReadInput):
        selected = next((s for s in self.plan["selected"] if s["slug"] == value.skill_ref), None)
        if not selected:
            raise ValueError("Skill is not routed to this work package")
        entry = self.packages[value.skill_ref]
        if value.action == "list_resources":
            return {
                "skill": value.skill_ref,
                "resources": selected["resources"],
                "reading_is_coverage": False,
            }
        resource = "SKILL.md" if value.action == "body" else value.resource_name
        if not resource or resource not in selected["resources"]:
            raise ValueError("Skill reference is not allowed for this work package")
        relative = PurePosixPath(resource)
        if relative.is_absolute() or ".." in relative.parts or "\\" in resource:
            raise ValueError("Skill resource must remain within its approved package")
        package = self.root / value.skill_ref
        path = package / resource
        if not path.resolve().is_relative_to(self.root) or any(
            p.is_symlink() for p in [path, package, *path.parents][: len(relative.parts) + 2]
        ):
            raise ValueError("Skill resource symlinks are not permitted")
        if path.stat().st_size > MAX_SKILL_BYTES:
            raise ValueError("Skill resource exceeds byte limit")
        data = path.read_bytes()
        resource_meta = entry["resources"][resource]
        content_hash = hashlib.sha256(data).hexdigest()
        if content_hash != resource_meta["sha256"]:
            raise ValueError(
                "Pinned skill integrity mismatch; review and version the adaptation before use"
            )
        lines = data.decode("utf-8").splitlines()
        start = value.start_line
        end = min(value.end_line or start + 119, start + 199, len(lines))
        if end < start:
            raise ValueError("Empty skill line range")
        chosen, size = [], 0
        for line in lines[start - 1 : end]:
            if size + len(line) + 1 > MAX_READ_CHARS:
                break
            chosen.append(line)
            size += len(line) + 1
        if not chosen:
            raise ValueError("Skill line exceeds read limit; split this resource during adaptation")
        payload = {
            "skill_slug": value.skill_ref,
            "upstream_repo": entry["upstream_repo"],
            "upstream_commit": entry["upstream_commit"],
            "entry_path": entry["entry_path"],
            "adapted_entry_path": f"skill_library/{value.skill_ref}/SKILL.md",
            "reference_path": resource,
            "source_paths": resource_meta["source_paths"],
            "adaptation_version": entry["adaptation_version"],
            "license": entry["license"],
            "file_hash": content_hash,
            "catalog_hash": self.plan["catalog_hash"],
            "line_start": start,
            "line_end": start + len(chosen) - 1,
            "total_lines": len(lines),
            "content": "\n".join(chosen),
            "task_id": self.task["id"],
            "attempt_id": self.task["attempt_id"],
            "tool": "Skill",
            "trust": "reviewed_method_reference_not_source_evidence",
        }
        payload["has_more"] = payload["line_end"] < len(lines)
        eid = digest([self.run["id"], "skill_reference", payload])
        # Persist actual bytes and their receipt together, after validating the live attempt.
        with self.sf.begin() as db:
            task = require_attempt(db, self.task["id"], self.task["attempt_id"])
            if not db.get(DiscoveryEvidence, eid):
                db.add(
                    DiscoveryEvidence(
                        id=eid,
                        run_id=task.run_id,
                        repo_snapshot_id=self.run["repo_snapshot_id"],
                        kind="skill_reference",
                        content_hash=digest(payload),
                        payload=payload,
                    )
                )
            reads = list(task.checkpoint.get("skill_reads", []))
            if eid not in reads:
                reads.append(eid)
            task.checkpoint = {
                **task.checkpoint,
                "skill_reads": reads,
                "skills_last_read_at": time.time(),
            }
        return {**payload, "evidence_id": eid, "reading_is_coverage": False}


def candidate_skill_usage(db, task, previous):
    """Provenance is server-derived from real Skill reads, never model-provided fields."""
    usage = copy.deepcopy(previous.get("skills_used", []))
    read_ids = dict.fromkeys(
        task.payload.get("prior_checkpoint", {}).get("skill_reads", [])
        + task.checkpoint.get("skill_reads", [])
    )
    for eid in read_ids:
        evidence = db.get(DiscoveryEvidence, eid)
        if not evidence or evidence.run_id != task.run_id or evidence.kind != "skill_reference":
            continue
        value = evidence.payload
        key = (value["skill_slug"], value["upstream_commit"], value["adaptation_version"])
        item = next(
            (
                u
                for u in usage
                if (u["skill_slug"], u["upstream_commit"], u["adaptation_version"]) == key
            ),
            None,
        )
        if item is None:
            item = {
                k: value[k]
                for k in (
                    "skill_slug",
                    "upstream_repo",
                    "upstream_commit",
                    "entry_path",
                    "adaptation_version",
                    "license",
                )
            }
            item.update(
                {"reference_paths": [], "source_paths": [], "tool_evidence_ids": [], "reads": []}
            )
            usage.append(item)
        item["reference_paths"] = sorted(set(item["reference_paths"] + [value["reference_path"]]))
        item["source_paths"] = sorted(set(item["source_paths"] + value["source_paths"]))
        if eid not in item["tool_evidence_ids"]:
            item["tool_evidence_ids"].append(eid)
            item["reads"].append(
                {
                    k: value[k]
                    for k in (
                        "reference_path",
                        "line_start",
                        "line_end",
                        "file_hash",
                        "task_id",
                        "attempt_id",
                    )
                }
            )
    return usage
