import { memo } from "react";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import type { StatsPanelProps } from "../types";

export const StatsPanel = memo(function StatsPanel({ task, findings }: StatsPanelProps) {
  if (!task) return null;
  const readCount = task.coverage?.read_file_count;
  const total = task.coverage?.total_files ?? task.total_files ?? 0;
  const severity = [["严重", task.critical_count], ["高危", task.high_count], ["中危", task.medium_count], ["低危", task.low_count]] as const;
  const verdict: Record<string, string> = { confirmed: "已确认", candidate: "候选", false_positive: "已排除", pending: "待核查" };
  return <div className="space-y-4">
    <section className="rounded-lg border bg-card p-4">
      <div className="mb-3 flex items-center justify-between"><h3 className="text-sm">流程进度</h3><span className="text-sm tabular-nums">{Math.round(task.progress_percentage || 0)}%</span></div>
      <Progress value={task.progress_percentage || 0} className="h-1.5" />
      <p className="mt-3 text-xs text-muted-foreground">表示任务阶段进度，不代表源码覆盖率。</p>
      <div className="mt-4 flex items-center justify-between border-t pt-4 text-sm"><span className="text-muted-foreground">实际阅读文件</span><span className="tabular-nums">{readCount == null ? "未记录" : `${readCount} / ${total}`}</span></div>
      <p className="mt-2 text-xs text-muted-foreground">{readCount == null ? "此任务没有可核验的阅读统计。" : "读取过片段的文件数；文件内其他代码仍可能未检查。"}</p>
    </section>
    <div className="grid grid-cols-2 gap-3">
      {[["迭代次数", task.total_iterations || 0], ["工具调用", task.tool_calls_count || 0],
        ["Token 用量", `${((task.tokens_used || 0) / 1000).toFixed(1)}k`],
        [task.discovery_v2?.enabled ? "静态支持候选" : "已入库发现", task.findings_count || 0]].map(([label, value]) => <div key={label} className="rounded-lg border bg-card p-3"><p className="text-xs text-muted-foreground">{label}</p><p className="mt-2 text-xl font-semibold tabular-nums">{value}</p></div>)}
    </div>
    {(task.recovered_candidates_count || 0) > 0 && <p className="rounded-lg border bg-card p-3 text-xs text-muted-foreground">另有 {task.recovered_candidates_count} 条恢复的候选线索，需要进一步核查。</p>}
    {!task.discovery_v2?.enabled && task.findings_count > 0 && <section className="rounded-lg border bg-card p-4"><h3 className="mb-3 text-sm">严重程度</h3><div className="flex flex-wrap gap-2">{severity.filter(([, count]) => count > 0).map(([label, count]) => <Badge key={label} variant="outline">{label} {count}</Badge>)}</div></section>}
    {findings.length > 0 && <section className="rounded-lg border bg-card p-4"><h3 className="mb-3 text-sm">发现预览</h3><div className="space-y-4">{findings.slice(0, 3).map(finding => <div key={finding.id} className="border-t pt-3 first:border-0 first:pt-0">
      <p className="text-sm font-medium">{finding.title}</p><p className="mt-1 break-all text-xs text-muted-foreground">{finding.file_path}{finding.line_start ? `:${finding.line_start}` : ""}</p>
      <Badge variant="outline" className="mt-2">{verdict[finding.report_status || finding.verdict || "candidate"] || "待核查"}</Badge>
    </div>)}</div></section>}
  </div>;
});
export default StatsPanel;
