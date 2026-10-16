"""Multi-label project adapters. Capability levels describe implemented parsing."""

import re
from pathlib import Path

from app.services.discovery.profiles.rules import (
    BACKGROUND_PATTERN,
    CLI_PATTERN,
    GUARDS,
    RESOURCES,
    WEB_RULES,
)
from app.services.discovery.repo_index import LANGUAGES
from app.services.discovery.skill_catalog import catalog_snapshot, source_signals
from app.services.discovery.store import digest

CHECKS = {
    "web_api": [
        "authentication and object authorization",
        "input constraints and sensitive operations",
    ],
    "library_sdk": [
        "public API contract and caller trust boundary",
        "safe defaults and resource limits",
    ],
    "cli": [
        "local caller intent versus crossed privilege boundaries",
        "argument, environment and filesystem constraints",
    ],
    "background_service": [
        "message provenance and task authorization",
        "idempotency, state and resource lifecycle",
    ],
}


class ProjectProfileAdapter:
    kind = ""
    pattern = ""

    def discover(self, index):
        entries = []
        for path, text in index.texts.items():
            language = LANGUAGES.get(Path(path).suffix)
            code = getattr(index, "code_texts", {}).get(path)
            if not language or code is None:
                continue
            rules = (
                WEB_RULES.get(language, [])
                if self.kind == "web_api"
                else [(self.kind, self.pattern)]
            )
            seen = set()
            for framework, pattern in rules:
                if framework == "Ktor" and not re.search(r"\b(?:io\.ktor|routing)\b", code):
                    continue
                if (
                    language == "ruby"
                    and self.kind == "web_api"
                    and not (path.endswith("routes.rb") or "sinatra" in text)
                ):
                    continue
                for match in re.finditer(pattern, code):
                    number = code.count("\n", 0, match.start()) + 1
                    if number in seen:
                        continue
                    seen.add(number)
                    entries.append(
                        {
                            "id": digest([self.kind, path, number]),
                            "kind": self.kind,
                            "locator": {"file_path": path, "line": number},
                            "input_contract": "Inspect source and caller contract",
                            "caller_context": "unresolved",
                            "basis": "syntax_registration_heuristic",
                            "framework": framework,
                        }
                    )
        return entries


class WebAdapter(ProjectProfileAdapter):
    kind = "web_api"
    pattern = r"@\w+(?:\.\w+)*\.(?:route|get|post|put|delete|patch|websocket)\(|\b(?:app|router)\.(?:get|post|use|put|delete)\("


class CLIAdapter(ProjectProfileAdapter):
    kind = "cli"
    pattern = CLI_PATTERN


class BackgroundAdapter(ProjectProfileAdapter):
    kind = "background_service"
    pattern = BACKGROUND_PATTERN


class LibraryAdapter(ProjectProfileAdapter):
    kind = "library_sdk"

    def discover(self, index):
        return [
            {
                "id": digest([self.kind, s["id"]]),
                "kind": self.kind,
                "locator": {
                    "file_path": s["file_path"],
                    "line": s["line_start"],
                    "symbol_id": s["id"],
                },
                "input_contract": "Public API candidate; verify exports and documented preconditions",
                "caller_context": "library caller",
                "basis": s["basis"],
            }
            for s in index.symbols
            if s["kind"] == "function"
            and not s["name"].startswith("_")
            and not any(p in {"test", "tests", "__tests__"} for p in Path(s["file_path"]).parts)
        ]


ADAPTERS = [WebAdapter(), CLIAdapter(), BackgroundAdapter(), LibraryAdapter()]


def build_profile(index, requested=None):
    entries, capabilities = [], []
    for adapter in ADAPTERS:
        found = adapter.discover(index)
        if found or adapter.kind in (requested or []):
            entries.extend(found)
            capabilities.append(
                {
                    "profile": adapter.kind,
                    "level": "syntax_navigation",
                    "entry_discovery": "Tree-sitter / Python AST and framework registration hints",
                    "limitations": "Requires review of reachability, exports, guards and dynamic registration",
                }
            )
    kinds = sorted({e["kind"] for e in entries} | (set(requested or []) - {"auto"}))
    languages = sorted(
        {LANGUAGES[Path(p).suffix] for p in index.snapshot["files"] if Path(p).suffix in LANGUAGES}
    )
    unsupported = [
        f"{language}: text navigation only; no entry/call resolver"
        for language in languages
        if language not in getattr(index, "parsed_languages", set())
    ]
    if not kinds:
        unsupported.append(
            "No supported entry adapter matched; use file-scope review and explicit entry references"
        )
    guards, resources = [], []
    for path, code in getattr(index, "code_texts", {}).items():
        for pattern, collection, kind in [
            (GUARDS, guards, "guard"),
            (RESOURCES, resources, "resource"),
        ]:
            for match in re.finditer(pattern, code):
                line = code.count("\n", 0, match.start()) + 1
                collection.append(
                    {
                        "id": digest([kind, path, line, match.group()]),
                        "locator": {"file_path": path, "line": line},
                        "name": match.group().strip(),
                        "basis": "syntax_name_hint",
                        "status": "requires_source_review",
                    }
                )
    actors = {
        "web_api": "external request caller",
        "cli": "local operator / invoking process",
        "background_service": "message producer / scheduler",
        "library_sdk": "library consumer",
    }
    boundaries = [
        {
            "id": digest(["boundary", e["id"]]),
            "entrypoint_ids": [e["id"]],
            "locator": e["locator"],
            "from": actors[e["kind"]],
            "to": "application authority and protected resources",
            "status": "hypothesis",
            "basis": e["basis"],
            "review_question": "Trace controlled input → identity/tenant checks → sensitive operation; verify intended caller privileges",
        }
        for e in entries
    ]
    signals = {s["file_path"]: s for s in source_signals(index)}
    for entry in entries:
        path = entry["locator"]["file_path"]
        signal = signals.setdefault(
            path, {"file_path": path, "signals": [], "basis": entry["basis"]}
        )
        signal["signals"] = sorted(set(signal["signals"]) | {entry["kind"]})
    return {
        "project_kinds": kinds,
        "languages": languages,
        "components": sorted({p.split("/")[0] for p in index.snapshot["files"]}),
        "entrypoints": entries,
        "analysis_capabilities": capabilities,
        "unsupported_features": unsupported,
        "unknowns": index.unknowns,
        "applicable_checks": {kind: CHECKS.get(kind, []) for kind in kinds},
        "actors": [
            {"kind": k, "name": actors.get(k, "caller"), "status": "hypothesis"} for k in kinds
        ],
        "protected_resources": resources,
        "trust_boundaries": boundaries,
        "shared_guards": guards,
        "configuration_defaults": [],
        "security_contracts": [],
        "frameworks": sorted({e["framework"] for e in entries if e["kind"] == "web_api"}),
        "skill_signals": list(signals.values()),
        "skills_catalog": catalog_snapshot(),
    }
