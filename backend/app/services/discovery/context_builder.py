from app.services.discovery.candidate_store import CandidateStore


def build_context(run, task, session_factory=None):
    candidates = CandidateStore(session_factory)
    payload = task["payload"]
    checkpoint = {**payload.get("prior_checkpoint", {}), **task["checkpoint"]}
    candidate_ids = sorted(
        set(payload.get("candidate_ids", []) + checkpoint.get("candidate_ids", []))
    )
    restored = [candidates.candidate(run["id"], cid) for cid in candidate_ids]

    def in_scope(item):
        path = item.get("locator", {}).get("file_path", "")
        return any(
            path.startswith(s.rstrip("/") + "/") or path == s or s == "."
            for s in payload.get("scope", [])
        )

    entry_ids = set(payload.get("entrypoint_ids", []))
    entries = [
        e
        for e in run["profile"].get("entrypoints", [])
        if e["id"] in entry_ids or (not entry_ids and in_scope(e))
    ]
    return {
        "repo_snapshot_id": run["repo_snapshot_id"],
        "task_id": task["id"],
        "phase": task["phase"],
        "scope": payload.get("scope", []),
        "analysis_question": payload.get("analysis_question", ""),
        "candidate_records": restored,
        "observation_ids": payload.get("observation_ids", []),
        "checkpoint": checkpoint,
        "skills_plan": checkpoint.get("skills_plan", {}),
        "skill_context": {
            key: payload[key]
            for key in ("spec_paths", "spec_basis", "changed_paths", "comparison_basis")
            if payload.get(key)
        },
        "coverage": task["coverage"] or payload.get("prior_coverage", []),
        "project_kinds": run["profile"].get("project_kinds", []),
        "entrypoints": entries[:50],
        "entrypoints_total": len(entries),
        "entrypoints_truncated": len(entries) > 50,
        "trust_boundaries": [
            b
            for b in run["profile"].get("trust_boundaries", [])
            if set(b["entrypoint_ids"]) & {e["id"] for e in entries[:50]}
        ],
        "shared_guard_hints": [g for g in run["profile"].get("shared_guards", []) if in_scope(g)][
            :50
        ],
        "resource_hints": [r for r in run["profile"].get("protected_resources", []) if in_scope(r)][
            :50
        ],
        "navigation_note": "Shared/global guards may live outside this package; use FindSymbol/Grep/Read to inspect mounting and configuration. All hints are unresolved until source review.",
        "capabilities": run["profile"].get("analysis_capabilities", []),
        "unknowns": run["profile"].get("unsupported_features", [])
        + run["profile"].get("unknowns", [])[:20],
    }
