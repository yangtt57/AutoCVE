import { apiClient } from './serverClient';

/** 与后端 verification_agent/contract.py 的证据契约保持一致。 */

export type VerificationStatus =
  | 'pending'
  | 'running'
  | 'paused'
  | 'completed'
  | 'failed'
  | 'cancelled';
export type VerificationVerdict = 'confirmed' | 'refuted' | 'inconclusive' | 'unverifiable';
export type VerificationConfidence = 'high' | 'medium' | 'low';

export interface VerificationEnvironment {
  /** compose / dockerfile / minimal / harness / none */
  method?: string | null;
  app_url?: string | null;
  commit_sha?: string | null;
  image_digest?: string | null;
  build_seconds?: number | null;
  notes?: string | null;
}

export interface VerificationStep {
  seq?: number;
  intent?: string | null;
  command?: string | null;
  exit_code?: number | null;
  stdout?: string | null;
  stderr?: string | null;
}

export interface VerificationHttpMessage {
  method?: string | null;
  url?: string | null;
  headers?: Record<string, string> | null;
  body?: string | null;
  /** 仅响应侧有 */
  status?: number | null;
}

export interface VerificationHttpExchange {
  seq?: number;
  intent?: string | null;
  request?: VerificationHttpMessage | null;
  response?: VerificationHttpMessage | null;
}

export interface VerificationArtifact {
  path?: string | null;
  sha256?: string | null;
  bytes?: number | null;
}

export interface VerificationEvidence {
  steps?: VerificationStep[] | null;
  http_exchanges?: VerificationHttpExchange[] | null;
  reproduction?: string[] | null;
  [key: string]: unknown;
}

export interface VulnerabilityVerification {
  id: string;
  vulnerability_id: string;
  project_id: string;
  task_id?: string | null;

  status: VerificationStatus;
  verdict?: VerificationVerdict | null;
  confidence?: VerificationConfidence | null;

  model_provider?: string | null;
  model_id?: string | null;
  thinking_level?: string | null;

  evidence_digest?: string | null;
  summary?: string | null;
  impact?: string | null;
  refutation_reason?: string | null;
  unverifiable_reason?: string | null;

  environment?: VerificationEnvironment | null;
  /** 详情接口才下发；历史列表为 null（完整证据可能有几百 KB） */
  evidence?: VerificationEvidence | null;
  limitations?: string[] | null;
  artifacts?: VerificationArtifact[] | null;

  started_at?: string | null;
  completed_at?: string | null;
  duration_seconds?: number | null;
  /** 本次暂停的开始时间（未暂停时为 null） */
  paused_at?: string | null;
  /** 累计暂停时长（秒），已从 duration_seconds 里扣掉 */
  paused_seconds?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  error_message?: string | null;
}

export interface VerificationStartPayload {
  rerun?: boolean;
}

/** 功能被关闭时后端返回 409，detail 里带开启方式。 */
export interface VerificationDisabledError {
  disabled: true;
  detail: string;
}

export function isVerificationDisabled(error: unknown): error is VerificationDisabledError {
  const detail = (error as { response?: { status?: number; data?: { detail?: unknown } } })?.response;
  return detail?.status === 409 && typeof detail.data?.detail === 'string';
}

export async function startVulnerabilityVerification(
  vulnerabilityId: string,
  payload: VerificationStartPayload = {}
): Promise<VulnerabilityVerification> {
  const response = await apiClient.post(`/vulnerabilities/${vulnerabilityId}/verification`, payload);
  return response.data;
}

/** 没有验证记录时返回 null（后端 404）。 */
export async function getLatestVulnerabilityVerification(
  vulnerabilityId: string
): Promise<VulnerabilityVerification | null> {
  try {
    const response = await apiClient.get(`/vulnerabilities/${vulnerabilityId}/verification`);
    return response.data;
  } catch (error) {
    if ((error as { response?: { status?: number } })?.response?.status === 404) {
      return null;
    }
    throw error;
  }
}

export async function listVulnerabilityVerifications(
  vulnerabilityId: string,
  limit = 20
): Promise<VulnerabilityVerification[]> {
  const response = await apiClient.get(`/vulnerabilities/${vulnerabilityId}/verification/history`, {
    params: { limit },
  });
  return response.data;
}

export function isVerificationActive(verification?: VulnerabilityVerification | null): boolean {
  return (
    verification?.status === 'pending' ||
    verification?.status === 'running' ||
    verification?.status === 'paused'
  );
}

export function isVerificationPaused(verification?: VulnerabilityVerification | null): boolean {
  return verification?.status === 'paused';
}

/** 暂停正在跑的验证（冻结容器，之后再点「继续」接着跑）。 */
export async function pauseVulnerabilityVerification(
  vulnerabilityId: string
): Promise<VulnerabilityVerification> {
  const response = await apiClient.post(`/vulnerabilities/${vulnerabilityId}/verification/pause`);
  return response.data;
}

/** 继续被暂停的验证。 */
export async function resumeVulnerabilityVerification(
  vulnerabilityId: string
): Promise<VulnerabilityVerification> {
  const response = await apiClient.post(
    `/vulnerabilities/${vulnerabilityId}/verification/resume`
  );
  return response.data;
}
