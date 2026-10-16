"""Small entry-oriented work packages; unmatched source never disappears behind a specialty."""

from pathlib import Path

from app.services.discovery.repo_index import LANGUAGES

SPECIALTY_CHECKS = {
    "github_actions": "CI event provenance, token permissions and artifact consumers",
    "native": "C/C++ ownership, bounds arithmetic and shared-state invariants",
    "rust": "Rust safe/unsafe, FFI, panic and concurrency boundaries",
    "cloud": "deployment identity, configuration precedence and resource authority",
    "local_ipc": "local peer identity, native bridge and per-operation authorization",
    "dependencies": "dependency resolution, integrity and build-consumer trust",
}


def independent_packages(run):
    profile, groups, assigned = run["profile"], {}, set()
    entries = profile.get("entrypoints", [])
    external_files = {e["locator"]["file_path"] for e in entries if e["kind"] != "library_sdk"}
    for entry in entries:
        path = entry["locator"]["file_path"]
        if entry["kind"] == "library_sdk" and path in external_files:
            continue
        groups.setdefault((entry["kind"], str(Path(path).parent)), []).append(entry)
        assigned.add(path)
    for hint in profile.get("skill_signals", []):
        kind = next((k for k in SPECIALTY_CHECKS if k in hint["signals"]), None)
        if kind:
            path = hint["file_path"]
            groups.setdefault((kind, str(Path(path).parent)), []).append(
                {"locator": {"file_path": path}}
            )
            assigned.add(path)
    # Always schedule unassigned source/configuration, even if Docker or CI was found.
    extra_ext = {
        ".xml",
        ".yaml",
        ".yml",
        ".toml",
        ".json",
        ".ini",
        ".conf",
        ".sql",
        ".sh",
        ".scala",
        ".vue",
        ".svelte",
        ".dart",
        ".ex",
        ".exs",
    }
    remaining = [
        p
        for p in run["snapshot"]["files"]
        if p not in assigned and (Path(p).suffix in LANGUAGES or Path(p).suffix in extra_ext)
    ]
    if not groups and not remaining:
        remaining = list(run["snapshot"]["files"])
    for path in sorted(remaining):
        groups.setdefault(("source", str(Path(path).parent)), []).append(
            {"locator": {"file_path": path}}
        )
    order = {"web_api": 0, "background_service": 1, "cli": 2, "source": 3, "library_sdk": 4}
    # Round-robin packages across components: a single large controller cannot occupy
    # the entire front of the queue. Each package carries all of its entry IDs.
    buckets = []
    for (kind, module), seeds in sorted(
        groups.items(), key=lambda pair: (order.get(pair[0][0], 3), pair[0])
    ):
        packages, chunk = [], []
        for seed in seeds:
            paths = {s["locator"]["file_path"] for s in chunk + [seed]}
            if chunk and (len(chunk) >= 24 or len(paths) > 8):
                packages.append(chunk)
                chunk = []
            chunk.append(seed)
        if chunk:
            packages.append(chunk)
        checks = profile.get("applicable_checks", {}).get(kind) or [
            SPECIALTY_CHECKS.get(
                kind, "input contracts, trust boundaries, configuration and resource constraints"
            )
        ]
        buckets.append(
            [
                {
                    "scope": sorted({s["locator"]["file_path"] for s in batch}),
                    "entry_files": sorted({s["locator"]["file_path"] for s in batch}),
                    "entrypoint_ids": [s["id"] for s in batch if s.get("id")],
                    "component": module,
                    "profile": kind,
                    "analysis_question": "; ".join(checks),
                }
                for batch in packages
            ]
        )
    for position in range(max((len(b) for b in buckets), default=0)):
        for bucket in buckets:
            if position < len(bucket):
                yield bucket[position]
