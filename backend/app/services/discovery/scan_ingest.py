from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path

import ijson
from sqlalchemy import func, select

from app.models.discovery import ScanIngestError, ScanObservation
from app.services.discovery.store import RunStore, digest, row_dict
from app.services.scan_runtime.normalizers.semgrep import normalize_semgrep_results

SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "info"}
PRIORITY = {"critical": 100, "high": 85, "medium": 55, "low": 25, "info": 10, "unknown": 0}


class ObservationStore(RunStore):
    def import_semgrep(
        self,
        run_id,
        artifact_path,
        *,
        scan_run_id,
        diagnostics=None,
        batch_size=1000,
        cancel_event=None,
    ):
        """Re-runnable import of a durable artifact. JSONL locators retain every occurrence."""
        run = self.get(run_id)
        path = Path(artifact_path)
        with path.open("rb") as source:
            artifact_hash = hashlib.file_digest(source, "sha256").hexdigest()
        previous = run["scan_manifest"]
        if previous.get("indexed_count", 0) and previous.get("artifact_id") != artifact_hash:
            raise ValueError(
                "Published observations are immutable; changed scanner output requires a new discovery task"
            )
        records_path = path.with_suffix(".records.jsonl")
        manifest = {
            "scan_run_id": scan_run_id,
            "artifact_id": artifact_hash,
            "artifact_path": str(path),
            "records_path": str(records_path),
            "repo_snapshot_id": run["repo_snapshot_id"],
            "scan_snapshot_id": digest([scan_run_id, artifact_hash, "priority-v1"]),
            "sort_version": "priority-v1",
            "raw_count": None,
            "indexed_count": 0,
            "parse_error_count": 0,
            "import_cursor": 0,
            "ingestion_incomplete": True,
            "scanner_version": None,
            "ruleset_version": (diagnostics or {}).get("ruleset_version"),
            "rule_bundle": previous.get("rule_bundle"),
            "diagnostics": dict(diagnostics or {}),
            "targets_scanned": None,
            "skipped_count": 0,
            "scanner_error_count": 0,
        }
        self.patch(run_id, scan_manifest=manifest)
        count, errors, batch, saw_results = 0, 0, [], False
        builder, depth, offset = None, 0, 0
        try:
            with path.open("rb") as source, records_path.open("wb") as output:
                for prefix, event, value in ijson.parse(source, use_float=True):
                    if cancel_event is not None and cancel_event.is_set():
                        raise InterruptedError(
                            "Ingestion cancelled; existing rows and raw artifact retained"
                        )
                    if prefix == "version" and event == "string":
                        manifest["scanner_version"] = value
                    if prefix == "results" and event == "start_array":
                        saw_results = True
                    if prefix == "paths.scanned" and event == "start_array":
                        manifest["targets_scanned"] = 0
                    if prefix == "paths.scanned.item" and event == "string":
                        manifest["targets_scanned"] += 1
                    if prefix == "paths.skipped.item" and event in {"start_map", "string"}:
                        manifest["skipped_count"] += 1
                    if prefix == "errors.item" and event == "start_map":
                        manifest["scanner_error_count"] += 1
                    if prefix == "results.item" and builder is None:
                        builder = ijson.ObjectBuilder()
                        depth = 0
                    if builder is None:
                        continue
                    builder.event(event, value)
                    if event in {"start_map", "start_array"}:
                        depth += 1
                    elif event in {"end_map", "end_array"}:
                        depth -= 1
                    if depth:
                        continue
                    raw = builder.value
                    builder = None
                    encoded = (json.dumps(raw, ensure_ascii=False, default=str) + "\n").encode()
                    offset = output.tell()
                    output.write(encoded)
                    output.flush()
                    try:
                        obs = self._normalize(
                            run,
                            scan_run_id,
                            artifact_hash,
                            count,
                            offset,
                            len(encoded),
                            raw,
                            manifest["scanner_version"],
                            manifest["ruleset_version"],
                        )
                        batch.append(obs)
                    except (ValueError, TypeError, KeyError) as exc:
                        errors += 1
                        self._error(run_id, f"results[{count}]", str(exc))
                    count += 1
                    if len(batch) >= batch_size:
                        self._flush(batch)
                        batch = []
                        manifest.update(import_cursor=count, parse_error_count=errors)
                        self.patch(run_id, scan_manifest=manifest)
            if not saw_results:
                raise ValueError("Semgrep artifact lacks a results array")
            manifest["raw_count"] = count
            manifest["ingestion_incomplete"] = bool(errors)
        except Exception as exc:
            manifest["ingestion_error"] = str(exc)
            self._error(run_id, f"after results[{count - 1}]", str(exc))
        finally:
            try:
                self._flush(batch)
            except Exception as exc:
                manifest["ingestion_incomplete"] = True
                manifest["ingestion_error"] = f"Index write failed: {exc}"
            with self.sf() as db:
                indexed = db.scalar(
                    select(func.count())
                    .select_from(ScanObservation)
                    .where(ScanObservation.run_id == run_id)
                )
            manifest.update(indexed_count=indexed, import_cursor=count, parse_error_count=errors)
            manifest["not_imported_count"] = (
                max(0, manifest["raw_count"] - indexed - errors)
                if manifest["raw_count"] is not None
                else None
            )
            diagnostic = manifest["diagnostics"]
            if diagnostic.get("error") or diagnostic.get("exit_code") not in (None, 0, 1):
                manifest["ingestion_incomplete"] = True
            incomplete = (
                manifest["ingestion_incomplete"]
                or manifest["skipped_count"]
                or manifest["scanner_error_count"]
                or manifest["targets_scanned"] == 0
            )
            if manifest["targets_scanned"] == 0:
                manifest["reason"] = "Scanner scanned zero target files; this is not a clean scan"
            manifest["status"] = "partial" if incomplete else "completed"
            manifest["published_at"] = time.time()
            self.patch(run_id, scan_manifest=manifest)
        return manifest

    def _normalize(
        self,
        run,
        scan_id,
        artifact_hash,
        position,
        offset,
        length,
        raw,
        scanner_version,
        ruleset_version,
    ):
        if not isinstance(raw, dict) or not isinstance(raw.get("extra"), dict):
            raise ValueError("Malformed Semgrep record")
        item = normalize_semgrep_results(
            {"results": [raw]}, artifact_ref=artifact_hash, max_index_findings=None
        )[0]
        if (
            not item["rule_id"]
            or item["file_path"] not in run["snapshot"]["files"]
            or item["line_start"] <= 0
        ):
            raise ValueError("Missing rule/location, or path outside audited source manifest")
        severity_raw = str(raw["extra"].get("severity") or "")
        severity = SEVERITY.get(severity_raw.upper(), "unknown")
        oid = digest([scan_id, "SemgrepScan", artifact_hash, position])
        signal = digest(
            [
                item["rule_id"],
                item["file_path"],
                raw.get("start"),
                raw.get("end"),
                raw["extra"].get("lines"),
                raw["extra"].get("dataflow_trace"),
            ]
        )
        payload = {
            **item,
            "observation_id": oid,
            "scan_run_id": scan_id,
            "repo_snapshot_id": run["repo_snapshot_id"],
            "scanner_name": "SemgrepScan",
            "scanner_version": scanner_version,
            "ruleset_version": ruleset_version,
            "rule_metadata_hash": digest(raw["extra"].get("metadata", {})),
            "severity_raw": severity_raw,
            "severity_normalized": severity,
            "severity_mapping_version": "semgrep-v1",
            "related_locations": [],
            "artifact_id": artifact_hash,
            "raw_record_locator": {"index": position, "byte_offset": offset, "byte_length": length},
            "source_trace_refs": [oid] if raw["extra"].get("dataflow_trace") else [],
            "signal_fingerprint": signal,
            "created_at": time.time(),
            "record_version": 1,
        }
        return {
            "id": oid,
            "run_id": run["id"],
            "scan_run_id": scan_id,
            "repo_snapshot_id": run["repo_snapshot_id"],
            "signal_fingerprint": signal,
            "priority": PRIORITY[severity],
            "file_path": item["file_path"],
            "rule_id": item["rule_id"],
            "severity": severity,
            "review_status": "pending",
            "payload": payload,
        }

    def _flush(self, batch):
        if not batch:
            return
        with self.sf.begin() as db:
            existing = set(
                db.scalars(
                    select(ScanObservation.id).where(
                        ScanObservation.id.in_([b["id"] for b in batch])
                    )
                )
            )
            db.add_all(ScanObservation(**item) for item in batch if item["id"] not in existing)

    def _error(self, run_id, locator, reason):
        with self.sf.begin() as db:
            eid = digest([run_id, locator, reason])
            if not db.get(ScanIngestError, eid):
                db.add(ScanIngestError(id=eid, run_id=run_id, locator=locator, reason=reason))

    def list_page(self, run_id, *, cursor=None, page_size=100, severity=None, file_path=None):
        run = self.get(run_id)
        manifest = run["scan_manifest"]
        snapshot = manifest.get("scan_snapshot_id")
        if not manifest.get("published_at"):
            return {"items": [], "next_cursor": None, "snapshot_id": snapshot, "ready": False}
        filters = digest([severity, file_path])
        stmt = select(ScanObservation).where(ScanObservation.run_id == run_id)
        if severity:
            stmt = stmt.where(ScanObservation.severity == severity)
        if file_path:
            stmt = stmt.where(ScanObservation.file_path == file_path)
        if cursor:
            try:
                page = json.loads(base64.urlsafe_b64decode(cursor))
                if page["snapshot"] != snapshot or page["filters"] != filters:
                    raise ValueError("Cursor belongs to a different result snapshot or filter")
                stmt = stmt.where(
                    (ScanObservation.priority < page["priority"])
                    | (
                        (ScanObservation.priority == page["priority"])
                        & (ScanObservation.id > page["id"])
                    )
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("Invalid observation cursor") from exc
        size = min(max(1, page_size), 1000)
        with self.sf() as db:
            rows = list(
                db.scalars(
                    stmt.order_by(ScanObservation.priority.desc(), ScanObservation.id).limit(
                        size + 1
                    )
                )
            )
        next_cursor = None
        if len(rows) > size:
            last = rows[size - 1]
            next_cursor = base64.urlsafe_b64encode(
                json.dumps(
                    {
                        "snapshot": snapshot,
                        "filters": filters,
                        "priority": last.priority,
                        "id": last.id,
                    }
                ).encode()
            ).decode()
        return {
            "items": [self._public(r) for r in rows[:size]],
            "next_cursor": next_cursor,
            "snapshot_id": snapshot,
            "ready": True,
        }

    @staticmethod
    def _public(row):
        return {
            **row.payload,
            "review_status": row.review_status,
            "decision": row.decision,
            "priority": row.priority,
        }

    def observation(self, run_id, observation_id, *, include_raw=False, include_trace=False):
        with self.sf() as db:
            row = db.get(ScanObservation, observation_id)
            if not row or row.run_id != run_id:
                raise ValueError("Unknown observation")
            result = self._public(row)
        if include_raw or include_trace:
            manifest = self.get(run_id)["scan_manifest"]
            locator = result["raw_record_locator"]
            with Path(manifest["records_path"]).open("rb") as source:
                source.seek(locator["byte_offset"])
                raw = json.loads(source.read(locator["byte_length"]))
            if include_raw:
                result["raw"] = raw
            if include_trace:
                result["trace"] = raw.get("extra", {}).get("dataflow_trace")
        return result

    def stats(self, run_id):
        with self.sf() as db:
            counts = dict(
                db.execute(
                    select(ScanObservation.review_status, func.count())
                    .where(ScanObservation.run_id == run_id)
                    .group_by(ScanObservation.review_status)
                ).all()
            )
            groups = db.scalar(
                select(func.count(func.distinct(ScanObservation.signal_fingerprint))).where(
                    ScanObservation.run_id == run_id
                )
            )
        return {
            "reviewed": counts.get("reviewed", 0),
            "needs_followup": counts.get("needs_followup", 0),
            "pending": counts.get("pending", 0),
            "signal_groups": groups,
        }

    def errors(self, run_id):
        with self.sf() as db:
            return [
                row_dict(r)
                for r in db.scalars(select(ScanIngestError).where(ScanIngestError.run_id == run_id))
            ]
