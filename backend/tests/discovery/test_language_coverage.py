import pytest

from app.services.agent.read_coverage import read_paths
from app.services.discovery.coverage import coverage_summary
from app.services.discovery.planning import independent_packages
from app.services.discovery.profiles import build_profile
from app.services.discovery.repo_index import RepoIndex, create_snapshot
from app.services.scan_runtime.models import ScannerExecutionResult
from app.services.scan_runtime.normalizers.semgrep import normalize_semgrep_results
from app.services.scan_runtime.pipeline import ScanPipeline


@pytest.fixture
def index_for(tmp_path):
    roots = []

    def build(files):
        source = tmp_path / f"repo{len(roots)}"
        source.mkdir()
        for path, text in files.items():
            target = source / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        snapshot = create_snapshot(source, tmp_path / "snapshots")
        roots.append(snapshot["root"])
        return RepoIndex(snapshot)

    yield build
    from pathlib import Path

    for root in roots:
        Path(root).chmod(0o755)
        for path in Path(root).rglob("*"):
            if path.is_dir():
                path.chmod(0o755)


@pytest.mark.parametrize(
    "path,source,symbol",
    [
        (
            "Users.java",
            '@RestController\nclass Users {\n @GetMapping(\n "/users")\n @PreAuthorize("hasRole(\'ADMIN\')")\n public String list() { return service.load(); }\n}',
            "list",
        ),
        (
            "server.go",
            'package main\nfunc list() {}\nfunc main() { http.HandleFunc("/", list) }',
            "list",
        ),
        (
            "Users.cs",
            'class Users { [HttpGet("/")] public string List() { return "ok"; } }',
            "List",
        ),
        (
            "api.php",
            '<?php\nRoute::get("/", [Users::class, "index"]);\nfunction index() { return 1; }',
            "index",
        ),
        (
            "config/routes.rb",
            'get "/users", to: "users#index"\ndef index\n  service.load\nend',
            "index",
        ),
        ("server.rs", '#[get("/users")]\nasync fn list() { service.load(); }', "list"),
        (
            "Users.kt",
            'class Users {\n @GetMapping("/users")\n fun list(): String { return service.load() }\n}',
            "list",
        ),
        (
            "app.ts",
            'const list = () => { return store.load(); };\nrouter.get("/users", list);',
            "list",
        ),
        ("server.swift", 'func list() { store.load() }\napp.get("users", use: list)', "list"),
    ],
)
def test_common_language_symbols_routes_and_uncertain_boundaries(index_for, path, source, symbol):
    index = index_for({path: source})
    profile = build_profile(index)
    assert index.find_symbol(symbol), (path, index.unknowns)
    entries = [e for e in profile["entrypoints"] if e["kind"] == "web_api"]
    assert entries, (path, index.code_texts)
    assert all(e["locator"]["file_path"] == path for e in entries)
    assert profile["trust_boundaries"]
    assert all(b["status"] == "hypothesis" for b in profile["trust_boundaries"])
    assert not profile["unsupported_features"]
    if path.endswith(".java"):
        assert profile["shared_guards"][0]["status"] == "requires_source_review"


def test_comments_and_strings_are_not_routes(index_for):
    index = index_for(
        {
            "Fake.java": '// @GetMapping("/fake")\nclass Fake { String example = "@PostMapping(/fake)"; }',
            "fake.js": '// app.get("/fake", fn);\nconst doc = "router.post(/fake)";',
        }
    )
    assert not [e for e in build_profile(index)["entrypoints"] if e["kind"] == "web_api"]


def test_unmatched_source_is_scheduled_alongside_deployment_and_large_controller(index_for):
    index = index_for(
        {
            "Dockerfile": "FROM scratch",
            "src/Unmatched.scala": "object Unknown {}",
            "src/Users.java": "class Users {\n"
            + "\n".join(
                f'@GetMapping("/{i}") public String get{i}() {{ return "ok"; }}' for i in range(60)
            )
            + "\n}",
        }
    )
    profile = build_profile(index)
    packages = list(independent_packages({"snapshot": index.snapshot, "profile": profile}))
    assert {"Dockerfile", "src/Unmatched.scala", "src/Users.java"} <= {
        p for task in packages for p in task["entry_files"]
    }
    ids = [eid for p in packages for eid in p["entrypoint_ids"]]
    assert len(ids) == len(set(ids)) == 60
    assert max(len(p["entrypoint_ids"]) for p in packages) <= 24


def test_late_high_priority_and_duplicate_occurrences_survive_ingestion():
    low = {"check_id": "x", "path": "app.py", "start": {"line": 1}, "extra": {"severity": "INFO"}}
    high = {**low, "extra": {"severity": "ERROR"}}
    findings = normalize_semgrep_results(
        {"results": [low] * 220 + [high]}, artifact_ref="raw.json", max_index_findings=200
    )
    combined = ScanPipeline._combine_index(
        [
            ScannerExecutionResult(
                scanner="SemgrepScan", status="completed", indexed_findings=findings
            )
        ]
    )
    assert len(combined) == 221
    assert combined[0]["raw_finding_index"] == 220
    assert len({f["finding_id"] for f in combined}) == 221


def test_coverage_and_resume_distinguish_disabled_scan_and_exhausted_work():
    run = {
        "snapshot": {"files": {"one.py": "a", "two.py": "b"}},
        "config": {"max_feedback_rounds": 2},
        "profile": {"entrypoints": [], "unsupported_features": []},
        "scan_manifest": {"status": "skipped"},
        "initial_snapshot": {"independent_status": "completed"},
    }
    stats = {"pending": 0, "needs_followup": 0}
    done = {
        "id": "a",
        "phase": "independent",
        "status": "completed",
        "payload": {},
        "coverage": [],
        "checkpoint": {"read_ranges": [{"file_path": "one.py"}]},
    }
    summary = coverage_summary(run, [done], stats)
    assert summary["status"] == "completed"
    assert summary["read_file_count"] == 1 and summary["unread_file_count"] == 1
    assert not summary["can_resume"]
    exhausted = {
        **done,
        "id": "b",
        "phase": "expansion",
        "status": "deferred",
        "round": 2,
        "reason": "limit",
    }
    summary = coverage_summary(run, [done, exhausted], stats)
    assert summary["status"] == "partial" and not summary["can_resume"]
    assert any(r["code"] == "round_limit" for r in summary["recovery_reasons"])


def test_only_successful_project_read_receipts_count():
    assert not read_paths({"success": False, "metadata": {"file_path": "foo.py", "end_line": 20}})
    assert read_paths(
        {
            "success": True,
            "metadata": {"files_read": ["a.py", "a.py", "../secret", "/tmp/skill.md"]},
        }
    ) == {"a.py"}
