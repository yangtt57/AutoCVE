import type { WorkflowConfig } from "@/shared/api/modelConfig";

export type AuditMode =
	| "enhanced_scan"
	| "intelligent_audit"
	| "comprehensive_audit";

export interface AuditModeOption {
	mode: AuditMode;
	label: string;
	recommended?: boolean;
	description: string;
	workflow: string;
}

export const AUDIT_MODE_OPTIONS: AuditModeOption[] = [
	{
		mode: "enhanced_scan",
		label: "快速扫描",
		description: "规则扫描与告警研判，适合快速检查",
		workflow: "规则扫描 → 逐项研判",
	},
	{
		mode: "intelligent_audit",
		label: "深入分析",
		description: "Agent 自主阅读源码，适合业务逻辑检查",
		workflow: "源码导航 → 业务与权限分析",
	},
	{
		mode: "comprehensive_audit",
		label: "全面审计",
		recommended: true,
		description: "结合独立分析与规则扫描，保留更多线索",
		workflow: "独立发现 + 规则扫描 → 反馈研判",
	},
];

export function getAuditModeLabel(mode: AuditMode): string {
	return (
		AUDIT_MODE_OPTIONS.find((option) => option.mode === mode)?.label ??
		"智能审计"
	);
}

function buildWorkflowConfig(
	mode: AuditMode,
	enableVerification: boolean,
): WorkflowConfig {
	const scanEnabled = mode !== "intelligent_audit";
	const triageEnabled = mode !== "intelligent_audit";
	const findingEnabled = mode !== "enhanced_scan";

	return {
		agentStates: {
			orchestrator: { enabled: true, locked: true },
			recon: { enabled: true, locked: true },
			scan: { enabled: scanEnabled },
			triage: { enabled: triageEnabled },
			finding: { enabled: findingEnabled },
			verification: { enabled: enableVerification },
		},
	};
}

export function buildAgentTaskAuditScope(
	mode: AuditMode,
	enableVerification: boolean,
): Record<string, unknown> {
	return {
		mode,
		dynamic_verification_enabled: enableVerification,
		workflow: buildWorkflowConfig(mode, enableVerification),
	};
}
