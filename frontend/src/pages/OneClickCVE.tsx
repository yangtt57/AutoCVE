import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  AlertCircle,
  BadgeCheck,
  Bug,
  Clock3,
  Eye,
  ExternalLink,
  FileSearch,
  GitBranch,
  Github,
  History,
  Loader2,
  Play,
  RefreshCw,
  Sparkles,
  Square,
  Star,
  Target,
} from "lucide-react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import {
  cancelOneClickCveBatch,
  createOneClickCveBatch,
  getOneClickCveBatch,
  listOneClickCveBatches,
  resumeOneClickCveProject,
  type OneClickCveBatch,
  type OneClickCveProject,
} from "@/shared/api/oneClickCve";

const ACTIVE_STATUSES = new Set(["pending", "running"]);
const TARGET_COUNT_MIN = 1;
const TARGET_COUNT_MAX = 10;

function errorMessage(error: unknown, fallback: string) {
  if (typeof error === "object" && error && "response" in error) {
    const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((item) => (typeof item === "string" ? item : JSON.stringify(item))).join("；") || fallback;
    }
  }
  return error instanceof Error ? error.message : fallback;
}

function formatTime(value?: string | null) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatStars(value: number) {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}k`;
  return String(value);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    pending: "等待中",
    running: "运行中",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
    exhausted: "候选耗尽",
    candidate: "候选",
    importing: "导入中",
    auditing: "审计中",
    skipped: "已跳过",
  };
  return labels[status] || status;
}

function statusClass(status: string) {
  if (status === "completed") return "border-emerald-200 bg-emerald-50 text-emerald-700";
  if (status === "running" || status === "auditing" || status === "importing" || status === "pending") {
    return "border-sky-200 bg-sky-50 text-sky-700";
  }
  if (status === "failed") return "border-red-200 bg-red-50 text-red-700";
  if (status === "exhausted" || status === "cancelled" || status === "skipped") return "border-amber-200 bg-amber-50 text-amber-700";
  return "border-slate-200 bg-slate-50 text-slate-600";
}

function projectSignal(project: OneClickCveProject) {
  if (project.has_security_advisory && project.has_private_vulnerability_reporting) return "Report a vulnerability";
  if (project.has_security_advisory) return "Security Advisory";
  if (project.has_private_vulnerability_reporting) return "Report enabled";
  if (project.has_security_policy) return "SECURITY.md";
  return "实时候选";
}

function projectSignalClass(project: OneClickCveProject) {
  if (project.has_security_advisory && project.has_private_vulnerability_reporting) {
    return "border-emerald-200 bg-emerald-50 text-emerald-800";
  }
  if (project.has_security_advisory) return "border-blue-200 bg-blue-50 text-blue-800";
  if (project.has_private_vulnerability_reporting) return "border-teal-200 bg-teal-50 text-teal-800";
  if (project.has_security_policy) return "border-slate-200 bg-slate-50 text-slate-700";
  return "border-stone-200 bg-stone-50 text-stone-600";
}

function vulnerabilityLink(project: OneClickCveProject) {
  const params = new URLSearchParams();
  params.set("project_name", project.github_full_name);
  if (project.version_label) params.set("version_label", project.version_label);
  params.set("project_link", project.repository_url);
  return `/vulnerabilities?${params.toString()}`;
}

export default function OneClickCVE() {
  const location = useLocation();
  const navigate = useNavigate();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [targetCount, setTargetCount] = useState("5");
  const [targetCountError, setTargetCountError] = useState("");
  const [preferSecurityAdvisory, setPreferSecurityAdvisory] = useState(true);
  const [batches, setBatches] = useState<OneClickCveBatch[]>([]);
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const [selectedBatch, setSelectedBatch] = useState<OneClickCveBatch | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [resumingProjectId, setResumingProjectId] = useState("");

  const hasActiveResume = Boolean(
    selectedBatch?.projects.some((project) => project.resume_status === "queued" || project.resume_status === "running"),
  );
  const active = selectedBatch ? ACTIVE_STATUSES.has(selectedBatch.status) || hasActiveResume : false;
  const progress = selectedBatch?.requested_count ? Math.min(100, Math.round((selectedBatch.found_count / selectedBatch.requested_count) * 100)) : 0;
  const batchStats = useMemo(() => {
    const projects = selectedBatch?.projects || [];
    return {
      scanned: projects.filter((item) => item.status === "completed").length,
      failed: projects.filter((item) => item.status === "failed").length,
      reportable: projects.filter((item) => item.has_security_advisory && item.has_private_vulnerability_reporting).length,
      findings: projects.reduce((sum, item) => sum + (item.findings_count || 0), 0),
    };
  }, [selectedBatch]);

  async function loadBatches(preferredBatchId?: string) {
    try {
      setLoading(true);
      const rows = await listOneClickCveBatches();
      setBatches(rows);
      const nextId = preferredBatchId || selectedBatchId || rows[0]?.id || "";
      setSelectedBatchId(nextId);
      if (nextId) {
        const detail = await getOneClickCveBatch(nextId);
        setSelectedBatch(detail);
      } else {
        setSelectedBatch(null);
      }
    } catch (error) {
      toast.error(errorMessage(error, "加载一键 CVE 批次失败"));
    } finally {
      setLoading(false);
    }
  }

  async function refreshBatch(batchId = selectedBatchId) {
    if (!batchId) return;
    try {
      setRefreshing(true);
      const detail = await getOneClickCveBatch(batchId);
      setSelectedBatch(detail);
      setBatches((current) => current.map((item) => (item.id === batchId ? detail : item)));
    } catch (error) {
      toast.error(errorMessage(error, "刷新一键 CVE 状态失败"));
    } finally {
      setRefreshing(false);
    }
  }

  async function startBatch() {
    const requestedCount = Number(targetCount);
    if (!Number.isInteger(requestedCount) || requestedCount < TARGET_COUNT_MIN || requestedCount > TARGET_COUNT_MAX) {
      const message = "请输入 1-10 之间的整数";
      setTargetCountError(message);
      toast.error(message);
      return;
    }

    try {
      setStarting(true);
      const created = await createOneClickCveBatch(requestedCount, preferSecurityAdvisory);
      setDialogOpen(false);
      setSelectedBatchId(created.id);
      setSelectedBatch(created);
      setBatches((current) => [created, ...current.filter((item) => item.id !== created.id)]);
      toast.success("一键 CVE 任务已启动");
    } catch (error) {
      toast.error(errorMessage(error, "启动一键 CVE 失败"));
    } finally {
      setStarting(false);
    }
  }

  async function cancelBatch() {
    if (!selectedBatch?.id) return;
    try {
      setCancelling(true);
      const next = await cancelOneClickCveBatch(selectedBatch.id);
      setSelectedBatch(next);
      setBatches((current) => current.map((item) => (item.id === next.id ? next : item)));
      toast.success("已发送取消请求");
    } catch (error) {
      toast.error(errorMessage(error, "取消一键 CVE 失败"));
    } finally {
      setCancelling(false);
    }
  }

  async function resumeProject(project: OneClickCveProject) {
    if (!selectedBatch?.id) return;
    try {
      setResumingProjectId(project.id);
      await resumeOneClickCveProject(selectedBatch.id, project.id);
      toast.success("已从上一个完整回合继续审计");
      await refreshBatch(selectedBatch.id);
    } catch (error) {
      toast.error(errorMessage(error, "继续审计失败"));
    } finally {
      setResumingProjectId("");
    }
  }

  useEffect(() => {
    loadBatches();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    if (searchParams.get("start") !== "1") return;
    setDialogOpen(true);
    navigate(location.pathname, { replace: true });
  }, [location.pathname, location.search, navigate]);

  useEffect(() => {
    if (!active || !selectedBatchId) return;
    const timer = window.setInterval(() => {
      refreshBatch(selectedBatchId);
    }, 5000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, selectedBatchId]);

  return (
    <div className="cyber-bg-elevated relative min-h-screen w-full min-w-0 overflow-x-hidden">
      <div className="pointer-events-none absolute inset-0 cyber-grid-subtle" />
      <div className="relative z-10 mx-auto flex w-full max-w-[1500px] flex-col gap-5 p-5">
        <section className="overflow-hidden rounded-lg border border-[#d3e2d9] bg-card shadow-sm">
          <div className="flex flex-col gap-5 p-6 lg:flex-row lg:items-center lg:justify-between lg:p-7">
            <div className="flex min-w-0 gap-4">
              <div className="flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl border border-emerald-200 bg-card text-emerald-700 shadow-sm">
                <Sparkles className="h-7 w-7" />
              </div>
              <div className="min-w-0">
                <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-[#bed1c8] bg-white/90 px-3 py-1 text-xs font-semibold text-[#50715d] shadow-sm">
                  <Github className="h-3.5 w-3.5" />
                  GitHub CVE Discovery
                </div>
                <h1 className="text-4xl font-bold tracking-normal text-slate-950">一键CVE</h1>
                <p className="mt-3 max-w-3xl text-sm leading-7 text-slate-600">
                  自动从 GitHub 上筛选符合要求的开源项目，并挖掘其中具有 CVE 申报价值的安全漏洞。
                </p>
              </div>
            </div>
            <div className="flex shrink-0 flex-wrap gap-2">
              <Button variant="outline" className="h-11 rounded-xl border-[#d6e3dc] bg-white/92 shadow-sm" onClick={() => loadBatches()} disabled={loading}>
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                刷新
              </Button>
              {active && (
                <Button variant="outline" className="h-11 rounded-xl border-amber-200 bg-amber-50 text-amber-700" onClick={cancelBatch} disabled={cancelling}>
                  {cancelling ? <Loader2 className="h-4 w-4 animate-spin" /> : <Square className="h-4 w-4" />}
                  停止
                </Button>
              )}
              <Button className="h-11 rounded-xl bg-[#5e7a63] px-5 text-white shadow-sm hover:bg-[#4e6a55]" onClick={() => setDialogOpen(true)}>
                <Play className="h-4 w-4" />
                启动
              </Button>
            </div>
          </div>
        </section>

        <section className="grid min-h-0 gap-5 xl:grid-cols-[320px_minmax(0,1fr)]">
          <aside className="min-h-0">
            <div className="flex h-full min-h-[620px] flex-col rounded-lg border border-[#d7e4dc] bg-white/94 p-4 shadow-sm ">
              <div className="mb-4 flex shrink-0 items-center justify-between">
                <div className="flex items-center gap-2 text-sm font-bold text-slate-900">
                  <History className="h-4 w-4 text-[#5e7a63]" />
                  扫描记录
                </div>
                <Badge className="rounded-full border-[#d6e3dc] bg-[#f4f8f5] text-[#5e7a63]">{batches.length}</Badge>
              </div>
              <div className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-1">
                {batches.length === 0 && (
                  <div className="rounded-2xl border border-dashed border-[#d7e4dc] bg-[#f7faf8] px-4 py-10 text-center text-sm text-slate-500">
                    暂无一键 CVE 批次
                  </div>
                )}
                {batches.map((batch) => {
                  const activeItem = batch.id === selectedBatchId;
                  return (
                    <button
                      key={batch.id}
                      type="button"
                      onClick={() => {
                        setSelectedBatchId(batch.id);
                        refreshBatch(batch.id);
                      }}
                      className={`w-full rounded-2xl border px-4 py-3 text-left transition duration-200 ${
                        activeItem
                          ? "border-emerald-300 bg-card shadow-sm"
                          : "border-[#e2ebe6] bg-white hover:border-[#b9cec2] hover:bg-[#fbfdfb]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="truncate text-sm font-bold text-slate-950">{formatTime(batch.created_at)}</span>
                        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs ${statusClass(batch.status)}`}>
                          {statusLabel(batch.status)}
                        </span>
                      </div>
                      <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-slate-500">
                        <span>目标 {batch.requested_count}</span>
                        <span className="text-right">发现 {batch.found_count}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </aside>

          <main className="min-w-0 space-y-5">
            <div className="grid gap-3 md:grid-cols-4">
              <MetricTile label="目标漏洞" value={selectedBatch?.requested_count ?? 0} icon={<Target className="h-4 w-4" />} />
              <MetricTile label="累计发现" value={selectedBatch?.found_count ?? 0} icon={<Bug className="h-4 w-4" />} tone="red" />
              <MetricTile label="已扫项目" value={batchStats.scanned} icon={<Github className="h-4 w-4" />} />
              <MetricTile label="Reportable" value={batchStats.reportable} icon={<BadgeCheck className="h-4 w-4" />} tone="emerald" />
            </div>

            <section className="rounded-lg border border-[#d7e4dc] bg-white/95 p-5 shadow-sm ">
              {selectedBatch ? (
                <div className="space-y-4">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-xl font-bold text-slate-950">当前状态</h2>
                        <span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass(selectedBatch.status)}`}>
                          {statusLabel(selectedBatch.status)}
                        </span>
                      </div>
                      <div className="mt-1 text-sm text-slate-500">{selectedBatch.current_step || "等待状态更新"}</div>
                    </div>
                    <div className="inline-flex items-center gap-2 rounded-full border border-[#d7e4dc] bg-[#f7faf8] px-3 py-1.5 text-sm text-slate-500">
                      <Clock3 className="h-4 w-4 text-[#5e7a63]" />
                      {formatTime(selectedBatch.started_at)} - {formatTime(selectedBatch.completed_at)}
                    </div>
                  </div>
                  <InteractiveProgress value={progress} active={active} />
                  {active && (
                    <div className="flex flex-wrap items-center gap-2 rounded-2xl border border-emerald-100 bg-emerald-50/70 px-3 py-2 text-xs font-medium text-emerald-800">
                      <span className="relative flex h-2.5 w-2.5">
                        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-emerald-600" />
                      </span>
                      正在持续发现项目与同步审计结果，每 5 秒自动刷新一次
                    </div>
                  )}
                  {selectedBatch.error_message && (
                    <div className="flex items-start gap-2 rounded-2xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                      <AlertCircle className="mt-0.5 h-4 w-4" />
                      <span>{selectedBatch.error_message}</span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="rounded-2xl border border-dashed border-[#d7e4dc] bg-[#f7faf8] px-4 py-12 text-center text-sm text-slate-500">
                  选择或启动一个批次后显示实时进度
                </div>
              )}
            </section>

            <section className="overflow-hidden rounded-lg border border-[#d7e4dc] bg-white/95 shadow-sm ">
              <div className="flex flex-col gap-3 border-b border-[#e1ebe5] bg-card px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h2 className="text-xl font-bold text-slate-950">扫描项目</h2>
                </div>
                <Button variant="outline" size="sm" className="h-10 rounded-xl border-[#d6e3dc] bg-white" onClick={() => refreshBatch()} disabled={!selectedBatchId || refreshing}>
                  {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  更新
                </Button>
              </div>

              <div className="max-h-[620px] divide-y divide-[#edf2ef] overflow-y-auto pr-1">
                {(selectedBatch?.projects || []).length === 0 && (
                  <div className="px-5 py-14 text-center text-sm text-slate-500">暂无项目记录</div>
                )}
                {(selectedBatch?.projects || []).map((project) => (
                  <ProjectRow
                    key={project.id}
                    project={project}
                    onResume={resumeProject}
                    resuming={resumingProjectId === project.id}
                  />
                ))}
              </div>
            </section>
          </main>
        </section>
      </div>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="overflow-hidden rounded-lg border border-[#d3e3da] bg-[#fbfdfb] p-0 shadow-sm sm:max-w-[520px]">
          <div className="border-b border-[#e4eee8] bg-card px-6 pb-5 pt-6">
            <DialogHeader className="space-y-3 text-left">
              <div className="flex items-start gap-3">
                <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl border border-[#bfe4cd] bg-white text-[#32754c] shadow-sm">
                  <Sparkles className="h-5 w-5" />
                </div>
                <div className="min-w-0">
                  <DialogTitle className="text-[22px] font-bold tracking-normal text-slate-950">启动一键 CVE</DialogTitle>
                  <DialogDescription className="mt-1 text-sm leading-6 text-slate-600">
                    选择目标漏洞数量，系统会持续搜索、导入并审计 GitHub 项目，直到累计发现数达到目标或候选耗尽。
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>
          </div>

          <div className="space-y-4 px-6 py-5">
            <div className="rounded-lg border border-[#dbe8e1] bg-white p-4 shadow-sm">
              <div className="mb-2 flex items-center justify-between gap-3">
                <label className="text-sm font-semibold text-slate-900">目标漏洞数量</label>
                <span className="rounded-full border border-[#d8e6de] bg-[#f7fbf8] px-2.5 py-1 text-xs font-medium text-[#5f7567]">
                  1-10
                </span>
              </div>
              <Input
                type="number"
                min={TARGET_COUNT_MIN}
                max={TARGET_COUNT_MAX}
                step={1}
                inputMode="numeric"
                value={targetCount}
                onChange={(event) => {
                  setTargetCount(event.target.value);
                  setTargetCountError("");
                }}
                className="h-12 rounded-2xl border-[#cfded5] bg-[#fbfdfb] text-base font-semibold text-slate-950 shadow-inner focus-visible:ring-[#6d9a76]"
                placeholder="输入 1-10 之间的整数"
              />
              <div className={`mt-2 text-xs ${targetCountError ? "text-red-600" : "text-slate-500"}`}>
                {targetCountError || "仅支持 1-10 之间的整数"}
              </div>
            </div>

            <div className="rounded-lg border border-[#cfe3d6] bg-card p-4 shadow-sm">
              <div className="flex min-h-12 items-center justify-between gap-4">
                <div className="flex min-w-0 items-center gap-3">
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-2xl border border-[#c6e6d0] bg-white text-[#397a52]">
                    <BadgeCheck className="h-5 w-5" />
                  </div>
                  <div className="whitespace-nowrap text-sm font-semibold text-slate-950">
                    优先审计 GitHub 有 Security Advisory 的项目
                  </div>
                </div>
                <Switch
                  checked={preferSecurityAdvisory}
                  onCheckedChange={setPreferSecurityAdvisory}
                  className="shrink-0"
                />
              </div>
            </div>
          </div>

          <DialogFooter className="border-t border-[#e4eee8] bg-white/90 px-6 py-4">
            <Button
              variant="outline"
              className="h-11 rounded-2xl border-[#d7e4dc] bg-white px-5 shadow-sm"
              onClick={() => setDialogOpen(false)}
              disabled={starting}
            >
              取消
            </Button>
            <Button
              className="h-11 rounded-2xl bg-[#5e7a63] px-6 text-white shadow-sm hover:bg-[#4e6a55]"
              onClick={startBatch}
              disabled={starting}
            >
              {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              启动
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function MetricTile({
  label,
  value,
  icon,
  tone = "slate",
}: {
  label: string;
  value: number;
  icon: ReactNode;
  tone?: "slate" | "red" | "emerald";
}) {
  const toneClass = {
    slate: "border-[#d7e4dc] bg-white/94 text-[#5e7a63]",
    red: "border-red-100 bg-red-50/90 text-red-700",
    emerald: "border-emerald-100 bg-emerald-50/90 text-emerald-700",
  }[tone];

  return (
    <div className={`rounded-lg border px-4 py-4 shadow-sm  ${toneClass}`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-500">{label}</span>
        {icon}
      </div>
      <div className="mt-2 text-3xl font-bold text-slate-950">{value}</div>
    </div>
  );
}

function InteractiveProgress({ value, active }: { value: number; active: boolean }) {
  return (
    <div className="space-y-2">
      <div className="relative h-3 overflow-hidden rounded-full border border-[#cfddd5] bg-[#edf4ef]">
        <div
          className={`h-full rounded-full bg-primary transition-all duration-700 ${
            active ? "bg-[length:200%_100%] animate-pulse" : ""
          }`}
          style={{ width: `${Math.max(value, active ? 8 : 0)}%` }}
        />
        {active && (
          <div className="absolute inset-0 bg-card opacity-60 [animation:one-click-cve-sweep_1.8s_linear_infinite]" />
        )}
      </div>
      <div className="flex items-center justify-between text-xs text-slate-500">
        <span>{active ? "任务进行中" : "进度"}</span>
        <span className="font-semibold text-[#5e7a63]">{value}%</span>
      </div>
      <style>{`
        @keyframes one-click-cve-sweep {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }
      `}</style>
    </div>
  );
}

function ProjectRow({
  project,
  onResume,
  resuming,
}: {
  project: OneClickCveProject;
  onResume: (project: OneClickCveProject) => void | Promise<void>;
  resuming: boolean;
}) {
  const canViewFindings = project.findings_count > 0;
  const resumeState = (() => {
    if (project.resume_status === "queued") {
      return { label: "排队中", className: "border-amber-200 bg-amber-50 text-amber-800" };
    }
    if (project.resume_status === "running") {
      const attempt = Number(project.resume_attempt || 0);
      const maxAttempts = Number(project.resume_max_attempts || 6);
      return {
        label: attempt > 1 ? `重试第 ${attempt}/${maxAttempts} 次` : "审计中",
        className: "border-sky-200 bg-sky-50 text-sky-800",
      };
    }
    if (project.resume_status === "resumable_failed" || project.resume_status === "enqueue_failed") {
      return { label: "恢复失败", className: "border-red-200 bg-red-50 text-red-700" };
    }
    return null;
  })();

  return (
    <div className="px-5 py-4 transition hover:bg-[#f8fbf9]">
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_auto] 2xl:items-center">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <a
              href={project.repository_url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex min-w-0 items-center gap-2 text-base font-bold text-slate-950 hover:text-[#5e7a63]"
            >
              <Github className="h-4 w-4 shrink-0" />
              <span className="truncate">{project.github_full_name}</span>
              <ExternalLink className="h-3.5 w-3.5 shrink-0" />
            </a>
            <span className={`rounded-full border px-2.5 py-1 text-xs ${statusClass(project.status)}`}>{statusLabel(project.status)}</span>
            <Badge className={`rounded-full ${projectSignalClass(project)}`}>{projectSignal(project)}</Badge>
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Star className="h-3.5 w-3.5" />
              {formatStars(project.stars)}
            </span>
            <span className="inline-flex items-center gap-1">
              <GitBranch className="h-3.5 w-3.5" />
              {project.default_branch || "main"}
            </span>
            <span>Version {project.version_label || project.default_branch || "unknown"}</span>
            {project.language && <span>{project.language}</span>}
            <span>更新 {formatTime(project.pushed_at)}</span>
          </div>
          {project.description && <div className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{project.description}</div>}
          {resumeState && (
            <div className={`mt-2 inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold ${resumeState.className}`}>
              {(project.resume_status === "queued" || project.resume_status === "running") && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {resumeState.label}
            </div>
          )}
          {project.error_message && <div className="mt-2 rounded-xl border border-red-100 bg-red-50 px-3 py-2 text-sm leading-6 text-red-600">{project.error_message}</div>}
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-2 rounded-2xl border border-[#dce8e1] bg-[#fbfdfb] p-2 shadow-sm">
          <div className="flex h-12 min-w-[72px] flex-col items-center justify-center rounded-xl border border-red-100 bg-red-50 px-3 text-center">
            <div className="text-[11px] font-semibold text-red-500">漏洞</div>
            <div className="text-xl font-bold leading-5 text-red-700">{project.findings_count}</div>
          </div>
          {canViewFindings && (
            <Button asChild variant="outline" size="sm" className="h-12 rounded-xl border-[#cdded4] bg-white px-3 text-[#365944] hover:bg-[#f1f7f3] hover:text-[#365944]">
              <Link to={vulnerabilityLink(project)}>
                <Eye className="h-4 w-4" />
                查看漏洞
              </Link>
            </Button>
          )}
          {project.project_id && (
            <Button asChild variant="outline" size="sm" className="h-12 rounded-xl border-[#d6e3dc] bg-white px-3 hover:bg-[#f6faf7]">
              <Link to={`/projects/${project.project_id}`}>
                <Github className="h-4 w-4" />
                项目
              </Link>
            </Button>
          )}
          {project.agent_task_id && (
            <Button asChild variant="outline" size="sm" className="h-12 rounded-xl border-[#d6e3dc] bg-white px-3 hover:bg-[#f6faf7]">
              <Link to={`/agent-audit/${project.agent_task_id}`}>
                <FileSearch className="h-4 w-4" />
                审计
              </Link>
            </Button>
          )}
          {project.agent_task_id && project.can_resume && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="h-12 rounded-xl border-amber-200 bg-amber-50 px-3 text-amber-800 hover:bg-amber-100"
              disabled={resuming}
              onClick={() => void onResume(project)}
            >
              {resuming ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              继续审计
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
