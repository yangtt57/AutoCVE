import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "sonner";
import { Input } from "@/components/ui/input";
import DiscoveryRecordView from "./DiscoveryRecordView";
import {
  getDiscovery, getDiscoveryCandidates, getObservations, getDiscoveryRecord, resumeDiscovery, downloadDiscovery,
  type CandidateStatus, type DiscoveryCandidate, type DiscoveryRun, type Observation,
} from "@/shared/api/discovery";

const statusLabel: Record<string, string> = {
  completed: "已完成", partial: "部分完成", failed: "失败", skipped: "已跳过", running: "进行中",
  pending: "待处理", deferred: "已延期", cancelled: "已取消", reviewed: "已研判", needs_followup: "待补查",
  prepared: "规则已就绪", indexing: "正在导入",
};
const phaseLabel: Record<string, string> = { independent: "独立发现", feedback: "反馈研判", expansion: "定向补查", complete: "本轮结束" };
const sourceLabel: Record<string, string> = {
  independent_agent: "独立发现", scanner_feedback: "工具反馈", targeted_expansion: "定向扩展",
};
const severityLabel: Record<string, string> = { critical: "严重", high: "高危", medium: "中危", low: "低危", info: "提示", unknown: "待定" };
const kindLabel: Record<string, string> = { web_api: "Web / API", library_sdk: "库与 SDK", cli: "命令行", background_service: "后台服务" };
const tabs: Array<[CandidateStatus | "observations", string]> = [
  ["statically_supported", "静态支持的候选"], ["needs_context", "未决线索"], ["ruled_out", "已排除项"], ["observations", "原始工具告警"],
];

export default function DiscoveryPanel({ taskId, taskStatus, onResumed }: { taskId: string; taskStatus: string; onResumed?: () => void | Promise<void> }) {
  const [run, setRun] = useState<DiscoveryRun | null>(null);
  const [candidates, setCandidates] = useState<DiscoveryCandidate[]>([]);
  const [view, setView] = useState<CandidateStatus | "observations">("statically_supported");
  const [items, setItems] = useState<Observation[]>([]);
  const [cursor, setCursor] = useState<string>();
  const [next, setNext] = useState<string | null>(null);
  const [severity, setSeverity] = useState("");
  const [query, setQuery] = useState("");
  const [detail, setDetail] = useState<{ title: string; value: unknown } | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try {
      const [result, records] = await Promise.all([getDiscovery(taskId), getDiscoveryCandidates(taskId)]);
      setRun(result); setCandidates(records); setError("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "结果暂不可用，正在准备源码快照");
    }
  }, [taskId]);
  useEffect(() => {
    void load();
    if (["completed", "partial", "failed", "cancelled"].includes(taskStatus)) return;
    const interval = setInterval(() => void load(), 5000);
    return () => clearInterval(interval);
  }, [load, taskStatus]);
  useEffect(() => {
    if (view !== "observations") return;
    let current = true;
    getObservations(taskId, cursor, severity).then((page) => {
      if (current) { setItems(page.items); setNext(page.next_cursor); }
    }).catch((err) => { if (current) setError(String(err)); });
    return () => { current = false; };
  }, [taskId, cursor, severity, view, run?.scan_manifest.indexed_count]);
  const inspect = async (title: string, path: string) => {
    try { setDetail({ title, value: await getDiscoveryRecord(taskId, path) }); }
    catch { toast.error("读取记录失败"); }
  };
  const download = async (kind: "export" | "artifact") => {
    try { await downloadDiscovery(taskId, kind); } catch { toast.error("导出失败或原始产物尚未生成"); }
  };
  const resume = async () => {
    setBusy(true);
    try { await resumeDiscovery(taskId); toast.success("已从账本恢复待处理工作"); await load(); await onResumed?.(); }
    catch (err) { toast.error(err instanceof Error ? err.message : "恢复失败"); }
    finally { setBusy(false); }
  };
  const counts = run?.observation_stats;
  const filteredCandidates = candidates.filter(c => c.status === view && (!severity || c.severity_estimate === severity)
    && `${c.claim} ${c.project_component} ${c.unknowns.join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  return <section className="space-y-5" aria-label="综合源码审计结果">
    <div className="rounded-xl border border-border bg-muted/40 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">综合源码审计</h2>
        <Badge variant="outline" className={run?.status === "completed" ? "text-emerald-700" : "text-amber-700"}>
          {statusLabel[run?.status || taskStatus] || "准备中"}
        </Badge>
      </div>
      <p className="text-xs text-muted-foreground">结论依据源码与配置；未知条件保留在候选中。阶段：{phaseLabel[run?.phase || ""] || "准备快照"}</p>
      {error && <p role="alert" className="text-sm text-amber-700">{error}</p>}
      <div className="flex flex-wrap gap-2 text-xs">
        <span>初轮独立审计：{statusLabel[run?.initial_snapshot?.independent_status || "running"]}</span>
        <span>当前工具扫描：{statusLabel[run?.scan_manifest.status || "running"]}</span>
        {run?.profile.project_kinds.map((kind) => <Badge key={kind} variant="secondary">{kindLabel[kind] || kind}</Badge>)}
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs sm:grid-cols-6">
        {[["原始告警", run?.scan_manifest.raw_count ?? "未知"], ["已索引", run?.scan_manifest.indexed_count ?? 0],
          ["关联分组", counts?.signal_groups ?? 0], ["已研判", counts?.reviewed ?? 0],
          ["待补查", counts?.needs_followup ?? 0], ["未处理", counts?.pending ?? 0]].map(([label, value]) =>
          <div key={label} className="rounded-lg bg-background p-2"><div className="font-mono text-lg">{value}</div><div className="text-muted-foreground">{label}</div></div>)}
      </div>
      {run?.scan_manifest.ingestion_incomplete && <p className="text-xs text-amber-700">扫描或导入不完整：{run.scan_manifest.reason || run.scan_manifest.ingestion_error || "请查看导入诊断与覆盖缺口"}</p>}
      <div className="grid grid-cols-2 gap-3 border-t pt-3 text-xs sm:grid-cols-4">
        {[["实际阅读文件", `${run?.summary.read_file_count ?? "—"} / ${run?.summary.total_files ?? "—"}`],
          ["规则扫描文件", run?.summary.scanned_file_count ?? "未记录"], ["已核查检查项", run?.summary.checked_check_count ?? 0],
          ["待处理工作包", run?.summary.unfinished_tasks ?? 0]].map(([label, value]) => <div key={label}><p className="text-muted-foreground">{label}</p><p className="mt-1 text-base font-medium tabular-nums">{value}</p></div>)}
      </div>
      <p className="text-xs text-muted-foreground">已读文件表示实际读取过源码片段；流程结束不代表整个项目已审查或安全。</p>
      {run?.summary.recovery_reasons?.map(reason => <p key={reason.code} className="text-xs text-muted-foreground">{reason.message}</p>)}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={() => void download("export")}>导出完整账本</Button>
        <Button size="sm" variant="outline" onClick={() => void download("artifact")}>下载扫描原始文件</Button>
        <Button size="sm" variant="ghost" onClick={() => void load()}>刷新结果</Button>
        {run?.summary.can_resume && ["partial", "failed", "cancelled"].includes(taskStatus) &&
          <Button size="sm" disabled={busy} onClick={() => void resume()}>继续待处理工作</Button>}
      </div>
    </div>
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="结果视图">
      {tabs.map(([key, label]) => <button key={key} type="button" role="tab" aria-selected={view === key}
        className={`rounded-md border px-3 py-2 text-xs ${view === key ? "bg-primary/10 border-primary/40 text-primary" : "bg-card"}`}
        onClick={() => setView(key)}>{label}{key !== "observations" && ` (${candidates.filter((c) => c.status === key).length})`}</button>)}
    </div>
    <div className="flex flex-wrap items-center gap-3">
      <label className="text-xs">严重程度 <select aria-label="筛选严重程度" className="ml-2 rounded-md border px-2 py-2 bg-card" value={severity}
        onChange={e => { setSeverity(e.target.value); setCursor(undefined); }}>
        {["", "critical", "high", "medium", "low", "info", "unknown"].map(s => <option key={s} value={s}>{severityLabel[s] || "全部"}</option>)}
      </select></label>
      {view !== "observations" && <Input className="h-8 max-w-sm text-xs" aria-label="搜索结论或组件" placeholder="搜索结论、组件或未决条件…" value={query} onChange={e => setQuery(e.target.value)} />}
    </div>
    {view === "observations" ? <div className="space-y-3">
      <p className="text-xs text-muted-foreground">翻页仅用于查看，模型处理进度以研判回执为准。</p>
      {items.map((item) => <button key={item.observation_id} type="button" className="w-full rounded-lg border p-3 text-left hover:bg-muted"
        onClick={() => void inspect("原始告警、规则与数据流", `observations/${item.observation_id}`)}>
        <div className="flex gap-2 text-xs"><Badge variant="outline" title={`工具原始等级：${item.severity_raw || "unknown"}`}>{severityLabel[item.severity_normalized] || "待定"}</Badge><span>{statusLabel[item.review_status]}</span></div>
        <p className="mt-2 text-sm break-all">{item.rule_id}</p><p className="text-xs text-muted-foreground">{item.file_path}:{item.line_start}</p>
        <p className="mt-1 text-xs">{item.description_preview}</p>{item.decision && <p className="mt-1 text-xs">研判：{item.decision.reason}</p>}
      </button>)}
      {!items.length && <p className="text-sm text-muted-foreground">当前页无告警。扫描失败、尚未导入或不支持的情况请查看上方状态。</p>}
      <div className="flex gap-2"><Button size="sm" variant="outline" disabled={!cursor} onClick={() => setCursor(undefined)}>第一页</Button>
        <Button size="sm" variant="outline" disabled={!next} onClick={() => setCursor(next || undefined)}>下一页</Button></div>
    </div> : <div className="space-y-3">
      {filteredCandidates.map((candidate) => <article key={candidate.candidate_id} className="rounded-lg border bg-card p-4 space-y-2">
        <div className="flex flex-wrap gap-2"><Badge variant="outline">{severityLabel[candidate.severity_estimate] || candidate.severity_estimate}</Badge>
          {candidate.contributing_sources.map((s) => <Badge key={s} variant="secondary">{sourceLabel[s] || s}</Badge>)}
          <span className="text-xs text-muted-foreground">v{candidate.record_version}</span></div>
        <h3 className="text-sm font-medium">{candidate.claim}</h3>
        <p className="text-xs">预期规则：{candidate.expected_policy.text}（{candidate.expected_policy.basis_kind}）</p>
        <p className="text-xs text-muted-foreground">{candidate.change_reason}</p>
        {candidate.unknowns.length > 0 && <p className="text-xs text-amber-700">未决条件：{candidate.unknowns.join("；")}</p>}
        {candidate.controls_considered.length > 0 && <p className="text-xs">已检查防护：{candidate.controls_considered.join("；")}</p>}
        {(candidate.skills_used?.length ?? 0) > 0 && <details className="rounded-lg border p-3 text-xs">
          <summary className="cursor-pointer font-medium">使用的 Skills（{candidate.skills_used!.length}）</summary>
          <p className="mt-2 text-muted-foreground">以下记录实际读取的审计参考，不代表代码覆盖或漏洞证明。</p>
          {candidate.skills_used!.map((skill) => <div key={`${skill.skill_slug}-${skill.adaptation_version}`} className="mt-3 space-y-1 break-all">
            <p className="font-medium">{skill.skill_slug} · {skill.adaptation_version}</p>
            <p>{skill.upstream_repo} · {skill.upstream_commit.slice(0, 12)}</p>
            <p>已读参考：{skill.reference_paths.join("、")}</p>
            <div className="flex flex-wrap gap-1">{skill.tool_evidence_ids.map((id, n) =>
              <Button key={id} size="sm" variant="ghost" onClick={() => void inspect("Skill 阅读记录与固定版本", `evidence/${id}`)}>阅读记录 {n + 1}</Button>)}</div>
          </div>)}
        </details>}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => void inspect("候选版本与变化原因", `candidates/${candidate.candidate_id}/history`)}>版本历史</Button>
          {[...candidate.supporting_evidence_ids, ...candidate.counter_evidence_ids].map((id, n) =>
            <Button key={`${id}-${n}`} size="sm" variant="ghost" onClick={() => void inspect("原始证据", `evidence/${id}`)}>{candidate.counter_evidence_ids.includes(id) ? "反证" : "支持证据"} {n + 1}</Button>)}
        </div>
      </article>)}
      {!filteredCandidates.length && <p className="rounded-lg border border-dashed p-5 text-sm text-muted-foreground">当前筛选下暂无记录。可以调整筛选；待处理范围请查看覆盖信息。</p>}
    </div>}
    <details className="rounded-xl border p-4 text-xs space-y-3"><summary className="cursor-pointer font-medium">任务覆盖、能力限制与导入诊断</summary>
      {run?.profile.analysis_capabilities.map((c) => <p key={c.profile}>{c.profile} · {c.level}：{c.limitations}</p>)}
      {[...(run?.profile.unsupported_features || []), ...(run?.profile.unknowns || [])].map((text, n) => <p key={n} className="text-amber-700">{text}</p>)}
      {run?.ingest_errors.map((e, n) => <p key={n}>{e.locator}：{e.reason}</p>)}
      {run?.work_items.map((t) => <details key={t.id} className="border-t py-2"><summary className="cursor-pointer">{statusLabel[t.status] || t.status} · {t.phase} · {t.payload.scope.join(", ")}</summary>
        <p className="mt-2">{t.payload.analysis_question}</p><p className="text-amber-700">{t.reason}</p>
        {t.coverage.map((c, i) => <div key={i} className="mt-2 rounded border p-2"><p>{c.status === "checked" ? "已核查" : "未决"} · {c.scope}</p><p>{c.check}</p><p className="text-muted-foreground">{c.reason}</p>
          {c.evidence_ids.map((id, n) => <Button key={id} size="sm" variant="ghost" onClick={() => void inspect("检查依据", `evidence/${id}`)}>证据 {n + 1}</Button>)}</div>)}
        </details>)}
    </details>
    <DiscoveryRecordView detail={detail} onClose={() => setDetail(null)} />
  </section>;
}
