from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from pathlib import Path

from app.core.config import settings
from app.services.discovery.budget import BudgetedModelClient, BudgetExhausted, PhaseBudget
from app.services.discovery.candidate_store import CandidateStore
from app.services.discovery.feedback_planner import FeedbackPlanner
from app.services.discovery.models import DiscoveryConfig
from app.services.discovery.profiles import build_profile
from app.services.discovery.repo_index import RepoIndex, create_snapshot
from app.services.discovery.scan_ingest import ObservationStore
from app.services.discovery.store import RunStore
from app.services.discovery.task_store import TaskStore
from app.services.finding_runtime.bridge import FindingRuntimeBridge
from app.services.scan_runtime.pipeline import ScanPipeline


class DiscoveryScheduler:
    def __init__(
        self,
        *,
        llm_service,
        sandbox_manager,
        session_factory=None,
        event_sink=None,
        worker=None,
        scanner=None,
        storage_root=None,
    ):
        self.llm = llm_service
        self.sandbox = sandbox_manager
        self.sf = session_factory
        self.runs, self.tasks = RunStore(session_factory), TaskStore(session_factory)
        self.candidates, self.observations = (
            CandidateStore(session_factory),
            ObservationStore(session_factory),
        )
        self.planner = FeedbackPlanner(session_factory)
        self.event_sink = event_sink
        self.worker_override, self.scanner_override = worker, scanner
        self.storage = Path(storage_root or settings.DISCOVERY_STORAGE_PATH).resolve()

    async def emit(self, phase, **data):
        if self.event_sink:
            await self.event_sink({"phase": phase, **data})

    async def run(self, input_data):
        started = time.monotonic()
        incoming = input_data.get("config", {})
        config = DiscoveryConfig.model_validate(incoming.get("discovery_v2", {}))
        task_id = input_data["task_id"]
        run = self.runs.for_task(task_id)
        if run is None:
            snapshot = await asyncio.to_thread(
                create_snapshot,
                input_data["project_root"],
                self.storage / "sources",
                target_files=incoming.get("target_files"),
                exclude_patterns=incoming.get("exclude_patterns"),
                quota_bytes=config.snapshot_quota_bytes,
                forbidden_roots=[self.storage],
            )
            index = await asyncio.to_thread(RepoIndex, snapshot)
            profile = build_profile(index, config.project_profiles)
            run = self.runs.create(
                task_id=task_id, snapshot=snapshot, config=config.model_dump(), profile=profile
            )
        else:
            config = DiscoveryConfig.model_validate(run["config"])
            index = await asyncio.to_thread(RepoIndex, run["snapshot"])
        run_id, owner = run["id"], uuid.uuid4().hex
        if not self.runs.acquire(run_id, owner):
            raise ValueError("This discovery run already has an active coordinator")
        pulse = asyncio.create_task(self._pulse(lambda: self.runs.heartbeat(run_id, owner)))
        tokens, turns = (
            int(incoming.get("token_budget") or 100000),
            int(incoming.get("max_iterations") or 50),
        )
        timeout = int(incoming.get("timeout_seconds") or 1800)
        deadline = started + timeout
        budgets = {
            phase: PhaseBudget(tokens * share, turns * share)
            for phase, share in [
                ("independent", config.independent_share),
                ("feedback", config.feedback_share),
                ("expansion", config.expansion_share),
            ]
        }
        self.runs.patch(run_id, status="running")
        try:
            self.tasks.reopen(run_id)
            if not self.scanner_override:
                from app.services.agent.tools.sandbox_tool import SandboxManager
                from app.services.discovery.scanners import ScannerAdapter

                scan_enabled = incoming.get("workflow", {}).get("agentStates", {}).get("scan", {}).get("enabled", True)
                if scan_enabled and isinstance(self.sandbox, SandboxManager) and not run["scan_manifest"].get(
                    "rule_bundle"
                ):
                    try:
                        await asyncio.wait_for(
                            ScannerAdapter().prepare(
                                run_id=run_id,
                                artifact_root=self.storage / "artifacts",
                                session_factory=self.sf,
                            ),
                            timeout=min(60, max(1, deadline - time.monotonic())),
                        )
                        run = self.runs.get(run_id)
                    except Exception as exc:
                        self.runs.patch(
                            run_id,
                            scan_manifest={
                                "status": "failed",
                                "preparation_error": str(exc),
                                "reason": "Rule bundle could not be frozen: " + str(exc),
                                "raw_count": None,
                                "ingestion_incomplete": True,
                            },
                        )
            if not run["initial_snapshot"]:
                self._plan_independent(run, incoming)
                self.runs.patch(run_id, phase="independent")
                await self.emit(
                    "independent",
                    run_id=run_id,
                    message="Independent source audit and static scan started",
                )
                independent_seconds = max(
                    1, min(timeout * config.independent_share, deadline - time.monotonic())
                )
                outcomes = await asyncio.gather(
                    self._phase(
                        run,
                        index,
                        "independent",
                        budgets["independent"],
                        input_data,
                        time.monotonic() + independent_seconds,
                    ),
                    asyncio.wait_for(
                        self._scan(run, input_data, independent_seconds),
                        timeout=independent_seconds,
                    ),
                    return_exceptions=True,
                )
                # Each branch keeps committed data even if its peer failed.
                branch_tasks = self.tasks.list(run_id, "independent")
                finding_state = (
                    "completed"
                    if branch_tasks and all(t["status"] == "completed" for t in branch_tasks)
                    else "partial"
                )
                if not branch_tasks:
                    finding_state = "skipped"
                elif all(t["status"] == "failed" for t in branch_tasks):
                    finding_state = "failed"
                if isinstance(outcomes[0], BaseException):
                    finding_state = "failed"
                scan = self.runs.get(run_id)["scan_manifest"]
                if isinstance(outcomes[1], BaseException):
                    scan = {
                        **scan,
                        "status": "failed",
                        "reason": str(outcomes[1]),
                        "ingestion_incomplete": True,
                    }
                    self.runs.patch(run_id, scan_manifest=scan)
                self.runs.freeze_initial(
                    run_id,
                    {
                        "independent_status": finding_state,
                        "scan_status": scan.get("status", "failed"),
                        "candidate_versions": {
                            c["candidate_id"]: c["record_version"]
                            for c in self.candidates.list(run_id)
                        },
                        "work_items": [
                            {
                                "task_id": t["id"],
                                "status": t["status"],
                                "coverage": t["coverage"],
                                "reason": t["reason"],
                            }
                            for t in branch_tasks
                        ],
                        "scan_snapshot_id": scan.get("scan_snapshot_id"),
                    },
                )
            elif (
                run["scan_manifest"].get("ingestion_error")
                or run["scan_manifest"].get("not_imported_count")
                or (
                    run["scan_manifest"].get("status") in {"failed", "prepared"}
                    and not run["scan_manifest"].get("indexed_count")
                )
            ):
                # Recover the same raw artifact/index after a crash without rewriting the first-round checkpoint.
                await asyncio.wait_for(
                    self._scan(run, input_data, max(1, deadline - time.monotonic())),
                    timeout=max(1, deadline - time.monotonic()),
                )
            run = self.runs.get(run_id)
            self.planner.plan_agent_feedback(run_id)
            # Unfinished independent attack surfaces are explicit bounded continuation packages.
            for task in self.tasks.list(run_id, "independent"):
                if task["status"] != "completed":
                    payload = {
                        **task["payload"],
                        "evidence_version": [task["id"], "initial"],
                        "prior_coverage": task["coverage"],
                        "continuation_of": task["id"],
                        "prior_checkpoint": task["checkpoint"],
                        "analysis_question": "Continue unfinished independent scope: "
                        + task["payload"]["analysis_question"],
                        "candidate_ids": [
                            c["candidate_id"]
                            for c in self.candidates.list(run_id)
                            if c["task_id"] == task["id"]
                        ],
                    }
                    self.tasks.enqueue(run_id, "expansion", payload, round=1)
            budgets["feedback"].tokens += max(
                0, budgets["independent"].tokens - budgets["independent"].used_tokens
            )
            budgets["feedback"].turns += max(
                0, budgets["independent"].turns - budgets["independent"].used_turns
            )
            await self._phase(
                run,
                index,
                "feedback",
                budgets["feedback"],
                input_data,
                min(deadline, time.monotonic() + timeout * config.feedback_share),
            )
            budgets["expansion"].tokens += max(
                0, budgets["feedback"].tokens - budgets["feedback"].used_tokens
            )
            budgets["expansion"].turns += max(
                0, budgets["feedback"].turns - budgets["feedback"].used_turns
            )
            for round_no in range(1, config.max_feedback_rounds):
                await self._phase(
                    run,
                    index,
                    "expansion",
                    budgets["expansion"],
                    input_data,
                    deadline,
                    round_no=round_no,
                )
            summary = self.summarize(run_id)
            summary["budget"] = {
                name: {
                    "tokens_used": b.used_tokens,
                    "turns_used": b.used_turns,
                    "tokens_allocated": b.tokens,
                    "turns_allocated": b.turns,
                }
                for name, b in budgets.items()
            }
            self.runs.patch(run_id, status=summary["status"], phase="complete", summary=summary)
            await self.emit("complete", run_id=run_id, **summary)
            return {
                "discovery_v2": True,
                "run_id": run_id,
                "findings": [],
                "summary": summary,
                "tokens_used": sum(b.used_tokens for b in budgets.values()),
            }
        except asyncio.CancelledError:
            self.runs.patch(
                run_id,
                status="cancelled",
                summary={"reason": "User cancelled; committed records remain resumable"},
            )
            raise
        except Exception as exc:
            self.runs.patch(run_id, status="partial", summary={"reason": str(exc)})
            raise
        finally:
            pulse.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pulse
            self.runs.release(run_id, owner)

    def _plan_independent(self, run, incoming):
        states = incoming.get("workflow", {}).get("agentStates", {})
        if states.get("finding", {}).get("enabled", True) is False:
            return
        skill_context = run.get("config", {}).get("skill_context", {})
        declared_paths = skill_context.get("spec_paths", []) + skill_context.get(
            "changed_paths", []
        )
        if any(path not in run["snapshot"]["files"] for path in declared_paths):
            raise ValueError("Skill context paths must be files in the immutable source snapshot")
        from app.services.discovery.planning import independent_packages

        for package in independent_packages(run):
            self.tasks.enqueue(run["id"], "independent", {**skill_context, **package})

    async def _scan(self, run, input_data, seconds):
        if self.scanner_override:
            return await self.scanner_override(run)
        states = input_data.get("config", {}).get("workflow", {}).get("agentStates", {})
        if states.get("scan", {}).get("enabled", True) is False:
            self.runs.patch(
                run["id"],
                scan_manifest={
                    "status": "skipped",
                    "reason": "Disabled in task workflow",
                    "raw_count": None,
                },
            )
            return
        config = dict(run["config"])
        config["scanner_timeout_seconds"] = min(
            config["scanner_timeout_seconds"], max(1, int(seconds) - 2)
        )
        self.runs.patch(run["id"], config=config)
        pipeline = ScanPipeline(project_root=run["snapshot"]["root"], sandbox_manager=self.sandbox)
        return await pipeline.run_discovery(
            run_id=run["id"], artifact_root=self.storage / "artifacts", session_factory=self.sf
        )

    async def _phase(self, run, index, phase, budget, input_data, deadline, round_no=None):
        run_id = run["id"]
        self.runs.patch(run_id, phase=phase)
        await self.emit(phase, run_id=run_id, message=f"Source discovery: {phase}")

        async def consume(worker_number):
            while budget.available and time.monotonic() < deadline:
                task = self.tasks.claim(run_id, phase, f"{phase}-{worker_number}", round=round_no)
                if task is None and phase == "feedback":
                    if self.planner.plan_batch(run_id, run["config"]["default_batch_size"]):
                        task = self.tasks.claim(run_id, phase, f"{phase}-{worker_number}")
                if task is None:
                    return
                pulse = asyncio.create_task(
                    self._pulse(
                        lambda work=task: self.tasks.heartbeat(work["id"], work["attempt_id"])
                    )
                )
                try:
                    if self.worker_override:
                        await asyncio.wait_for(
                            self.worker_override(run, task, index, budget),
                            timeout=max(0.1, deadline - time.monotonic()),
                        )
                    else:
                        bridge = FindingRuntimeBridge(
                            llm_service=self.llm, tools={}, session_factory=self.sf
                        )
                        await asyncio.wait_for(
                            bridge.run_audit_task(
                                project_id=input_data["project_id"],
                                parent_task_id=input_data["task_id"],
                                run=run,
                                task=task,
                                index=index,
                                model_client=BudgetedModelClient(
                                    llm_service=self.llm, budget=budget
                                ),
                                max_turns=max(1, min(16, budget.turns - budget.used_turns)),
                                on_session_created=lambda sid, work=task: self.tasks.heartbeat(
                                    work["id"], work["attempt_id"], session_id=sid
                                ),
                            ),
                            timeout=max(0.1, deadline - time.monotonic()),
                        )
                    current = next(t for t in self.tasks.list(run_id) if t["id"] == task["id"])
                    if current["status"] == "running":
                        self.tasks.finish(
                            task["id"],
                            task["attempt_id"],
                            status="deferred",
                            reason="Worker stopped without a complete receipt",
                        )
                except asyncio.CancelledError:
                    with contextlib.suppress(ValueError):
                        self.tasks.finish(
                            task["id"],
                            task["attempt_id"],
                            status="deferred",
                            reason="Cancelled; committed records retained",
                        )
                    raise
                except Exception as exc:
                    status = (
                        "deferred" if isinstance(exc, (TimeoutError, BudgetExhausted)) else "failed"
                    )
                    with contextlib.suppress(ValueError):
                        self.tasks.finish(
                            task["id"],
                            task["attempt_id"],
                            status=status,
                            reason=str(exc) or "Phase deadline reached",
                        )
                finally:
                    pulse.cancel()
                    with contextlib.suppress(asyncio.CancelledError, ValueError):
                        await pulse

        workers = [
            asyncio.create_task(consume(n)) for n in range(run["config"]["worker_concurrency"])
        ]
        try:
            await asyncio.gather(*workers)
        except BaseException:
            for worker in workers:
                worker.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
            raise
        self.tasks.defer_pending(run_id, phase, "Phase budget/deadline exhausted")

    @staticmethod
    async def _pulse(callback):
        while True:
            await asyncio.sleep(20)
            callback()

    def summarize(self, run_id):
        run = self.runs.get(run_id)
        tasks, candidates = self.tasks.list(run_id), self.candidates.list(run_id)
        stats = self.observations.stats(run_id)
        from app.services.discovery.coverage import coverage_summary

        return {
            **coverage_summary(run, tasks, stats),
            "candidate_count": len(candidates),
            "statically_supported": sum(c["status"] == "statically_supported" for c in candidates),
            "needs_context": sum(c["status"] == "needs_context" for c in candidates),
            "ruled_out": sum(c["status"] == "ruled_out" for c in candidates),
        }
