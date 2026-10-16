"""Count successful source reads from tool receipts, never from model claims or task status."""

from pathlib import PurePosixPath


def read_paths(payload):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        return set()
    metadata = payload.get("metadata") or {}
    paths = metadata.get("files_read", [])
    if metadata.get("file_path") and metadata.get("end_line", 0) >= metadata.get("start_line", 1):
        paths = [*paths, metadata["file_path"]]
    return {
        str(PurePosixPath(p.replace("\\", "/")))
        for p in paths
        if isinstance(p, str)
        and p
        and not PurePosixPath(p.replace("\\", "/")).is_absolute()
        and ".." not in PurePosixPath(p.replace("\\", "/")).parts
        and not p.startswith((".auditai/", ".discovery/", "skill_library/"))
    }


async def task_read_coverage(db, task_id, total_files):
    from sqlalchemy import select

    from app.models.agent_task import AgentEvent
    from app.models.audit_session import AuditSession, AuditToolCall

    paths = set()
    rows = await db.execute(
        select(AuditToolCall.output_payload)
        .join(AuditSession, AuditToolCall.session_id == AuditSession.id)
        .where(
            AuditSession.task_id == task_id,
            AuditToolCall.status == "completed",
            AuditToolCall.tool_name.in_(
                ["Read", "FileRead", "ReadManyFiles", "read_file", "read_many_files"]
            ),
        )
    )
    for (payload,) in rows:
        paths.update(read_paths(payload))
    rows = await db.execute(
        select(AgentEvent.tool_output).where(
            AgentEvent.task_id == task_id,
            AgentEvent.event_type == "tool_result",
            AgentEvent.tool_name.in_(
                ["Read", "FileRead", "ReadManyFiles", "read_file", "read_many_files"]
            ),
        )
    )
    for (payload,) in rows:
        paths.update(read_paths(payload))
    return {
        "basis": "tool_receipts",
        "read_file_count": len(paths),
        "total_files": total_files,
        "note": "按成功读取的源码片段去重统计，不代表整个文件或项目已完成安全检查。",
    }
