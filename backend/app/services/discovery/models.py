import warnings
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SkillContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec_paths: list[str] = Field(default_factory=list, max_length=50)
    spec_basis: str = Field("", max_length=4000)
    changed_paths: list[str] = Field(default_factory=list, max_length=200)
    comparison_basis: str = Field("", max_length=8000)

    @model_validator(mode="after")
    def require_basis(self):
        if self.spec_paths and not self.spec_basis.strip():
            raise ValueError("spec_paths requires an independent spec_basis")
        if self.changed_paths and not self.comparison_basis.strip():
            raise ValueError("changed_paths requires a comparison_basis; history is not inferred")
        return self


class DiscoveryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    max_index_findings: int | None = Field(
        None, exclude=True, description="Deprecated; ignored by discovery v2"
    )
    configuration_warnings: list[str] = Field(default_factory=list)
    worker_concurrency: int = Field(3, ge=1, le=3)
    default_batch_size: int = Field(5, ge=1, le=20)
    max_feedback_rounds: int = Field(2, ge=1, le=2)
    independent_share: float = Field(0.40, gt=0, lt=1)
    feedback_share: float = Field(0.45, gt=0, lt=1)
    expansion_share: float = Field(0.15, ge=0, lt=1)
    write_batch_size: int = Field(1000, ge=1, le=5000)
    artifact_quota_bytes: int = Field(512 * 1024 * 1024, ge=1024)
    snapshot_quota_bytes: int = Field(1024 * 1024 * 1024, ge=1024)
    scanner_timeout_seconds: int = Field(600, ge=1, le=3600)
    skill_context: SkillContext = Field(default_factory=SkillContext)
    project_profiles: list[
        Literal["auto", "web_api", "library_sdk", "cli", "background_service"]
    ] = Field(default_factory=lambda: ["auto"])

    @model_validator(mode="after")
    def shares(self):
        if self.max_index_findings is not None:
            message = "max_index_findings is deprecated in discovery_v2 and ignored; all parseable observations are indexed"
            warnings.warn(message, UserWarning, stacklevel=2)
            if message not in self.configuration_warnings:
                self.configuration_warnings.append(message)
            self.max_index_findings = None
        if abs(self.independent_share + self.feedback_share + self.expansion_share - 1) > 0.00001:
            raise ValueError("Discovery budget shares must sum to 1")
        return self


class Policy(BaseModel):
    text: str = Field(min_length=1)
    basis_kind: Literal["code", "documentation", "test", "user_rule", "assumption"]
    evidence_ids: list[str] = Field(default_factory=list)


class CandidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim: str = Field(min_length=1)
    project_component: str
    analysis_kind: str
    status: Literal["needs_context", "statically_supported", "ruled_out"] = "needs_context"
    severity_estimate: Literal["critical", "high", "medium", "low", "info", "unknown"] = "unknown"
    severity_reason: str = ""
    expected_policy: Policy
    attacker_capabilities: list[str] = Field(default_factory=list)
    entrypoint_refs: list[str] = Field(default_factory=list)
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    counter_evidence_ids: list[str] = Field(default_factory=list)
    scanner_observation_ids: list[str] = Field(default_factory=list)
    controls_considered: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    change_reason: str = Field(min_length=1)


class FollowupInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: list[str] = Field(min_length=1)
    analysis_question: str = Field(min_length=5)
    why_new: str = Field(min_length=5)
    evidence_ids: list[str] = Field(min_length=1)
    candidate_ids: list[str] = Field(default_factory=list)
    observation_ids: list[str] = Field(default_factory=list)


class FeedbackDecision(BaseModel):
    observation_id: str
    status: Literal["linked_candidate", "new_candidate", "ruled_out", "needs_followup"]
    candidate_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=1)
    followup_task_ids: list[str] = Field(default_factory=list)
