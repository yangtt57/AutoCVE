"""Coverage and recovery are evidence-based, independent from workflow progress."""


def coverage_summary(run, tasks, stats):
    continued = {t["payload"].get("continuation_of") for t in tasks if t["status"] == "completed"}
    unfinished = [t for t in tasks if t["status"] != "completed" and t["id"] not in continued]
    coverage = [c for t in tasks if t["id"] not in continued for c in t["coverage"]]
    reads = {
        r["file_path"]
        for t in tasks
        for checkpoint in [t.get("checkpoint", {}), t["payload"].get("prior_checkpoint", {})]
        for r in checkpoint.get("read_ranges", [])
        if r["file_path"] in run["snapshot"]["files"]
    }
    scan = run["scan_manifest"]
    limit = run["config"].get("max_feedback_rounds", 2)
    exhausted = [
        t
        for t in unfinished
        if t.get("round", 0) >= limit
        or (t["phase"] == "independent" and run.get("initial_snapshot") and limit <= 1)
    ]
    exhausted_ids = {t["id"] for t in exhausted}
    runnable = [t for t in unfinished if t["id"] not in exhausted_ids]
    retry_scan = bool(
        scan.get("ingestion_error")
        or scan.get("not_imported_count")
        or (scan.get("status") in {"failed", "prepared"} and not scan.get("indexed_count"))
    )
    can_resume = bool(
        runnable or stats.get("pending") or retry_scan or not run.get("initial_snapshot")
    )
    limitations = list(run["profile"].get("unsupported_features", []))
    unresolved = [c for c in coverage if c["status"] != "checked"]
    reasons = []
    if runnable or stats.get("pending"):
        reasons.append(
            {
                "code": "pending_work",
                "message": "仍有未处理的工作包或扫描告警，可沿用源码快照继续。",
                "resumable": True,
            }
        )
    if retry_scan:
        reasons.append(
            {
                "code": "scan_retry",
                "message": "扫描或导入失败；修复扫描环境后可继续。",
                "resumable": True,
            }
        )
    if exhausted:
        reasons.append(
            {
                "code": "round_limit",
                "message": "部分补查已达到轮次上限，需要缩小范围后创建新任务。",
                "resumable": False,
            }
        )
    if limitations:
        reasons.append(
            {
                "code": "capability_gap",
                "message": "存在入口识别或解析能力限制；继续同一任务不会自动消除这些限制。",
                "resumable": False,
            }
        )
    if scan.get("status") == "skipped":
        reasons.append(
            {"code": "scan_disabled", "message": "当前模式未执行规则扫描。", "resumable": False}
        )
    if scan.get("status") == "partial" and not retry_scan:
        reasons.append(
            {
                "code": "scan_partial",
                "message": scan.get("reason") or "规则扫描存在覆盖缺口，请检查扫描诊断后新建任务。",
                "resumable": False,
            }
        )
    if unresolved and not runnable:
        reasons.append(
            {
                "code": "unresolved_checks",
                "message": "仍有未决检查项，需要补充配置、调用方或策略依据。",
                "resumable": False,
            }
        )
    partial = bool(
        unfinished
        or stats.get("pending")
        or stats.get("needs_followup")
        or limitations
        or unresolved
        or scan.get("status") not in {"completed", "skipped"}
    )
    return {
        "status": "partial" if partial else "completed",
        "observations": stats,
        "unfinished_tasks": len(unfinished),
        "completed_tasks": sum(t["status"] == "completed" for t in tasks),
        "total_files": len(run["snapshot"]["files"]),
        "read_file_count": len(reads),
        "unread_file_count": len(run["snapshot"]["files"]) - len(reads),
        "scanned_file_count": scan.get("targets_scanned"),
        "checked_scopes": sorted({c["scope"] for c in coverage if c["status"] == "checked"}),
        "checked_check_count": sum(c["status"] == "checked" for c in coverage),
        "unresolved_check_count": len(unresolved),
        "entrypoint_count": len(run["profile"].get("entrypoints", [])),
        "deferred_reasons": sorted({t["reason"] for t in unfinished if t.get("reason")}),
        "can_resume": can_resume,
        "recovery_reasons": reasons,
        "coverage_note": "已读文件表示实际返回过源码片段；检查回执按具体范围记录，均不代表整个项目安全。",
        "initial_branches": (
            {k: run["initial_snapshot"].get(k) for k in ["independent_status", "scan_status"]}
            if run.get("initial_snapshot")
            else {}
        ),
    }
