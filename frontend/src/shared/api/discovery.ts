import { apiClient } from "./serverClient";

export type CandidateStatus = "statically_supported" | "needs_context" | "ruled_out";
export interface DiscoverySkillUsage {
  skill_slug: string; upstream_repo: string; upstream_commit: string; entry_path: string;
  adaptation_version: string; reference_paths: string[]; source_paths: string[]; tool_evidence_ids: string[];
}
export interface DiscoveryCandidate {
  candidate_id: string; record_version: number; status: CandidateStatus;
  claim: string; severity_estimate: string; severity_reason: string;
  project_component: string; contributing_sources: string[]; change_reason: string;
  expected_policy: { text: string; basis_kind: string; evidence_ids: string[] };
  supporting_evidence_ids: string[]; counter_evidence_ids: string[];
  unknowns: string[]; controls_considered: string[]; scanner_observation_ids: string[];
  skills_used?: DiscoverySkillUsage[];
}
export interface Observation {
  observation_id: string; rule_id: string; file_path: string; line_start: number;
  severity_raw: string; severity_normalized: string; description_preview: string;
  review_status: string; decision?: { reason: string };
}
export interface DiscoveryRun {
  id: string; status: string; phase: string; repo_snapshot_id: string;
  initial_snapshot: { independent_status: string; scan_status: string } | null;
  scan_manifest: { status?: string; raw_count?: number | null; indexed_count?: number; parse_error_count?: number;
    ingestion_incomplete?: boolean; reason?: string; ingestion_error?: string };
  observation_stats: { reviewed: number; pending: number; needs_followup: number; signal_groups: number };
  summary: { unfinished_tasks?: number; deferred_reasons?: string[]; can_resume?: boolean;
    total_files?: number; read_file_count?: number; scanned_file_count?: number | null;
    checked_check_count?: number; unresolved_check_count?: number; entrypoint_count?: number;
    recovery_reasons?: Array<{ code: string; message: string; resumable: boolean }> };
  profile: { project_kinds: string[]; languages: string[]; unsupported_features: string[]; unknowns: string[];
    analysis_capabilities: Array<{ profile: string; level: string; limitations: string }> };
  work_items: Array<{ id: string; phase: string; status: string; reason?: string;
    payload: { scope: string[]; analysis_question: string }; coverage: Array<{ scope: string; check: string; status: string; reason: string; evidence_ids: string[] }> }>;
  ingest_errors: Array<{ locator: string; reason: string }>;
}
const base = (taskId: string) => `/discovery/tasks/${taskId}`;
export async function getDiscovery(taskId: string): Promise<DiscoveryRun> {
  return (await apiClient.get(base(taskId))).data;
}
export async function getDiscoveryCandidates(taskId: string): Promise<DiscoveryCandidate[]> {
  return (await apiClient.get(`${base(taskId)}/candidates`)).data;
}
export async function getObservations(taskId: string, cursor?: string, severity?: string): Promise<{
  items: Observation[]; next_cursor: string | null; ready: boolean;
}> {
  return (await apiClient.get(`${base(taskId)}/observations`, { params: { cursor, severity: severity || undefined, page_size: 100 } })).data;
}
export async function getDiscoveryRecord(taskId: string, path: string): Promise<unknown> {
  return (await apiClient.get(`${base(taskId)}/${path}`)).data;
}
export async function resumeDiscovery(taskId: string) {
  return (await apiClient.post(`${base(taskId)}/resume`)).data;
}
export async function downloadDiscovery(taskId: string, kind: "export" | "artifact") {
  const { data } = await apiClient.get(`${base(taskId)}/${kind}`, { responseType: "blob" });
  const url = URL.createObjectURL(data);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `${taskId}-${kind === "export" ? "discovery.jsonl" : "semgrep.json"}`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
