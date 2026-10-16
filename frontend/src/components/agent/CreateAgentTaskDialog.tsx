/**
 * Agent 审计任务创建对话框
 * Cyberpunk Terminal Aesthetic
 */

import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { BranchSelector } from "@/components/ui/branch-selector";
import {
  Search,
  ChevronRight,
  GitBranch,
  Package,
  Globe,
  Loader2,
  Bot,
  Settings2,
  Play,
  Upload,
  FolderOpen,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/shared/config/database";
import { createAgentTask } from "@/shared/api/agentTasks";
import { isRepositoryProject, isZipProject, isLocalDirectoryProject } from "@/shared/utils/projectUtils";
import { AUDIT_MODE_OPTIONS, buildAgentTaskAuditScope, type AuditMode } from "./auditModeConfig";
import { getZipFileInfo, uploadZipFile, waitForZipImport, type ZipFileMeta } from "@/shared/utils/zipStorage";
import { validateZipFile } from "@/features/projects/services/repoZipScan";
import type { Project } from "@/shared/types";
import FileSelectionDialog from "@/components/audit/FileSelectionDialog";

interface CreateAgentTaskDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const DEFAULT_EXCLUDES = [
  "node_modules/**",
  ".git/**",
  "dist/**",
  "build/**",
  "*.log",
];

export default function CreateAgentTaskDialog({
  open,
  onOpenChange,
}: CreateAgentTaskDialogProps) {
  const navigate = useNavigate();

  // 状态
  const [projects, setProjects] = useState<Project[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [selectedProjectId, setSelectedProjectId] = useState<string>("");
  const [searchTerm, setSearchTerm] = useState("");
  const [branch, setBranch] = useState("main");
  const [branches, setBranches] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);
  const [excludePatterns, setExcludePatterns] = useState(DEFAULT_EXCLUDES);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [creating, setCreating] = useState(false);
  const [discoveryV2, setDiscoveryV2] = useState(true);
  const [auditMode, setAuditMode] = useState<AuditMode>("comprehensive_audit");
  const [tokenBudget, setTokenBudget] = useState(150000);
  const [maxIterations, setMaxIterations] = useState(75);
  const [timeoutMinutes, setTimeoutMinutes] = useState(40);
  const [versionLabel, setVersionLabel] = useState("local-audit");

  // ZIP 文件状态
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [storedZipInfo, setStoredZipInfo] = useState<ZipFileMeta | null>(null);
  const [useStoredZip, setUseStoredZip] = useState(true);

  // 文件选择状态
  const [selectedFiles, setSelectedFiles] = useState<string[] | undefined>();
  const [showFileSelection, setShowFileSelection] = useState(false);

  const selectedProject = projects.find((p) => p.id === selectedProjectId);

  // 加载项目列表
  useEffect(() => {
    if (open) {
      setLoadingProjects(true);
      api.getProjects()
        .then((data) => {
          setProjects(data.filter((p: Project) => p.is_active));
        })
        .catch(() => {
          toast.error("加载项目列表失败");
        })
        .finally(() => setLoadingProjects(false));

      // 重置状态
      setSelectedProjectId("");
      setSearchTerm("");
      setBranch("main");
      setExcludePatterns(DEFAULT_EXCLUDES);
      setShowAdvanced(false);
      setZipFile(null);
      setStoredZipInfo(null);
      setSelectedFiles(undefined);
      setDiscoveryV2(true);
      setAuditMode("comprehensive_audit");
      setTokenBudget(150000);
      setMaxIterations(75);
      setTimeoutMinutes(40);
      setVersionLabel("local-audit");
    }
  }, [open]);

  // 加载分支列表
  useEffect(() => {
    let active = true;
    setSelectedFiles(undefined);
    setZipFile(null);
    setStoredZipInfo(null);
    setUseStoredZip(true);
    const loadBranches = async () => {
      const project = projects.find((p) => p.id === selectedProjectId);
      if (!project || !isRepositoryProject(project)) {
        setBranches([]);
        setLoadingBranches(false);
        return;
      }

      setLoadingBranches(true);
      try {
        const result = await api.getProjectBranches(project.id);
        if (!active) return;

        if (result.error) {
          toast.error(`加载分支失败: ${result.error}`);
        }

        setBranches(result.branches);
        if (result.default_branch) {
          setBranch(result.default_branch);
        }
      } catch (err) {
        if (!active) return;
        const msg = err instanceof Error ? err.message : "未知错误";
        toast.error(`加载分支失败: ${msg}`);
        setBranches([project.default_branch || "main"]);
      } finally {
        if (active) setLoadingBranches(false);
      }
    };

    loadBranches();
    return () => { active = false; };
  }, [selectedProjectId, projects]);

  // 加载 ZIP 文件信息
  useEffect(() => {
    let active = true;
    const loadZipInfo = async () => {
      if (!selectedProject || !isZipProject(selectedProject)) {
        setStoredZipInfo(null);
        return;
      }

      try {
        const info = await getZipFileInfo(selectedProject.id);
        if (!active) return;
        setStoredZipInfo(info);
        setUseStoredZip(info.has_file || !!info.has_persistent_source);
      } catch {
        if (active) setStoredZipInfo(null);
      }
    };

    loadZipInfo();
    return () => { active = false; };
  }, [selectedProject?.id]);

  // 过滤项目
  const filteredProjects = useMemo(() => {
    if (!searchTerm) return projects;
    const term = searchTerm.toLowerCase();
    return projects.filter(
      (p) =>
        p.name.toLowerCase().includes(term) ||
        p.description?.toLowerCase().includes(term)
    );
  }, [projects, searchTerm]);

  // 是否可以开始
  const canStart = useMemo(() => {
    if (!selectedProject) return false;
    if (isLocalDirectoryProject(selectedProject)) return !!selectedProject.local_path?.trim();
    if (isZipProject(selectedProject)) {
      return (useStoredZip && (storedZipInfo?.has_file || storedZipInfo?.has_persistent_source)) || !!zipFile;
    }
    return !!selectedProject.repository_url && !!branch.trim() && !loadingBranches;
  }, [selectedProject, useStoredZip, storedZipInfo, zipFile, branch, loadingBranches]);

  // 创建任务
  const handleCreate = async () => {
    if (!selectedProject) return;

    setCreating(true);
    try {
      if (isZipProject(selectedProject)) {
        if (!useStoredZip && zipFile) {
          const uploaded = await uploadZipFile(selectedProject.id, zipFile);
          if (!uploaded.success) throw new Error(uploaded.message || "ZIP 上传失败");
          await waitForZipImport(selectedProject.id);
        } else if (storedZipInfo?.import_status === "processing") {
          await waitForZipImport(selectedProject.id);
        }
      }
      const agentTask = await createAgentTask({
        project_id: selectedProject.id,
        name: `Agent审计-${selectedProject.name}`,
        version_label: versionLabel.trim() || "local-audit",
        branch_name: isRepositoryProject(selectedProject) ? branch : undefined,
        exclude_patterns: excludePatterns,
        target_files: selectedFiles,
        verification_level: discoveryV2 ? "analysis_only" : "sandbox",
        discovery_v2: { enabled: discoveryV2 },
        audit_scope: buildAgentTaskAuditScope(auditMode, !discoveryV2),
        max_iterations: maxIterations,
        token_budget: tokenBudget,
        timeout_seconds: timeoutMinutes * 60,
      });

      onOpenChange(false);
      toast.success("Agent 审计任务已创建");
      navigate(`/agent-audit/${agentTask.id}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "创建失败";
      toast.error(msg);
    } finally {
      setCreating(false);
    }
  };

  // 处理文件上传
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validation = validateZipFile(file);
      if (!validation.valid) {
        toast.error(validation.error || "文件无效");
        e.target.value = "";
        return;
      }
      setZipFile(file);
      setUseStoredZip(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent aria-describedby={undefined} className="!w-[min(90vw,520px)] !max-w-none max-h-[85vh] flex flex-col p-0 gap-0 cyber-dialog border border-border rounded-lg">
        {/* Header */}
        <DialogHeader className="px-5 py-4 border-b border-border flex-shrink-0 bg-muted">
          <DialogTitle className="flex items-center gap-3 font-mono text-foreground">
            <div className="p-2 bg-primary/20 rounded border border-primary/30">
              <Bot className="w-5 h-5 text-primary" />
            </div>
            <div>
              <span className="text-base font-semibold">新建审计</span>
              <p className="text-xs text-muted-foreground font-normal mt-0.5">
                选择项目、分析方式和资源预算
              </p>
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          <fieldset className="space-y-2">
            <legend className="mb-2 text-sm font-medium">分析方式</legend>
            {AUDIT_MODE_OPTIONS.map(option => <label key={option.mode} className={`flex items-start gap-3 rounded-lg border p-3 cursor-pointer ${auditMode === option.mode ? "border-primary bg-primary/5" : "hover:bg-muted/50"}`}>
              <input type="radio" name="audit-mode" checked={auditMode === option.mode} className="mt-1 accent-primary"
                onChange={() => { setAuditMode(option.mode); const quick = option.mode === "enhanced_scan"; const full = option.mode === "comprehensive_audit"; setTokenBudget(quick ? 40000 : full ? 150000 : 100000); setMaxIterations(quick ? 25 : full ? 75 : 50); setTimeoutMinutes(quick ? 15 : full ? 40 : 30); }} />
              <span><span className="text-sm font-medium">{option.label}{option.recommended && <span className="ml-2 text-xs text-primary">推荐</span>}</span><span className="mt-1 block text-xs text-muted-foreground">{option.description}</span></span>
            </label>)}
          </fieldset>
          <label className="flex items-start gap-3 rounded-lg border p-3 cursor-pointer">
            <input type="checkbox" checked={discoveryV2} onChange={(e) => setDiscoveryV2(e.target.checked)} className="mt-1" />
            <span><span className="text-sm font-medium">使用源码发现与覆盖账本</span><span className="mt-1 block text-xs text-muted-foreground">按入口与信任边界组织静态分析，保留未决线索及原始告警。启用后仅执行静态审计；未启用时沿用现有 CVE 挖掘与验证流程。</span></span>
          </label>
          <p className="text-xs text-muted-foreground">{discoveryV2 ? `本次预算：${(tokenBudget / 1000).toFixed(0)}k Token · ${maxIterations} 轮 · ${timeoutMinutes} 分钟。实际用量取决于项目规模，可在高级设置调整。` : "当前沿用原有 CVE 流程的模型与验证配置；开启源码账本后可设置单次任务预算。"}</p>
          <label className="block text-xs text-muted-foreground">版本标记
            <Input value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} placeholder="例如 v1.2.0 或 local-audit" className="mt-1" />
          </label>
          {/* 项目选择 */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono font-bold uppercase text-muted-foreground">选择项目</span>
              <Badge className="cyber-badge-muted font-mono text-xs">
                {filteredProjects.length} 个项目
              </Badge>
            </div>

            {/* 搜索框 */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="搜索项目…"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="!pl-9 h-10 cyber-input"
              />
            </div>

            {/* 项目列表 */}
            <ScrollArea className="h-[200px] border border-border rounded bg-muted/50">
              {loadingProjects ? (
                <div className="flex items-center justify-center h-full">
                  <Loader2 className="w-5 h-5 animate-spin text-primary" />
                </div>
              ) : filteredProjects.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-muted-foreground font-mono">
                  <Package className="w-8 h-8 mb-2 opacity-50" />
                  <span className="text-sm">{searchTerm ? "没有匹配的项目" : "暂无项目，请先在项目管理中添加"}</span>
                </div>
              ) : (
                <div className="p-1">
                  {filteredProjects.map((project) => (
                    <ProjectItem
                      key={project.id}
                      project={project}
                      selected={selectedProjectId === project.id}
                      onSelect={() => setSelectedProjectId(project.id)}
                    />
                  ))}
                </div>
              )}
            </ScrollArea>
          </div>

          {/* 配置区域 */}
          {selectedProject && (
            <div className="space-y-4">
              {/* 仓库项目：分支选择 */}
              {isRepositoryProject(selectedProject) && (
                <div className="flex items-center gap-3 p-3 border border-border rounded bg-blue-950/20">
                  <GitBranch className="w-5 h-5 text-blue-400" />
                  <span className="font-mono text-sm text-muted-foreground w-16">分支</span>
                  {loadingBranches ? (
                    <div className="flex items-center gap-2 flex-1">
                      <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
                      <span className="text-sm text-blue-400 font-mono">加载中…</span>
                    </div>
                  ) : (
                    <BranchSelector
                      value={branch}
                      onChange={setBranch}
                      branches={branches}
                      placeholder="Select branch"
                      className="flex-1"
                    />
                  )}
                </div>
              )}

              {/* ZIP 项目：文件选择 */}
              {isZipProject(selectedProject) && (
                <div className="p-3 border border-border rounded bg-amber-950/20 space-y-3">
                  <div className="flex items-center gap-3">
                    <Package className="w-5 h-5 text-amber-400" />
                    <span className="font-mono text-sm text-muted-foreground uppercase font-bold">ZIP 文件</span>
                  </div>

                  {(storedZipInfo?.has_file || storedZipInfo?.has_persistent_source) && (
                    <div
                      className={`p-2 rounded border cursor-pointer transition-colors ${useStoredZip
                          ? 'border-emerald-500/50 bg-emerald-50'
                          : 'border-border hover:border-border bg-muted/50'
                        }`}
                      onClick={() => setUseStoredZip(true)}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`w-3 h-3 rounded-full border-2 ${useStoredZip ? 'border-emerald-500 bg-emerald-500' : 'border-border'
                          }`} />
                        <span className="text-sm text-foreground font-mono">
                          {storedZipInfo.original_filename || "已导入源码"}
                        </span>
                        <Badge className="cyber-badge-success text-xs">
                          Stored
                        </Badge>
                      </div>
                    </div>
                  )}

                  <div
                    className={`p-2 rounded border cursor-pointer transition-colors ${!useStoredZip && zipFile
                        ? 'border-amber-500/50 bg-amber-50'
                        : 'border-border hover:border-border bg-muted/50'
                      }`}
                  >
                    <label className="flex items-center gap-2 cursor-pointer">
                      <div className={`w-3 h-3 rounded-full border-2 ${!useStoredZip && zipFile ? 'border-amber-500 bg-amber-500' : 'border-border'
                        }`} />
                      <Upload className="w-4 h-4 text-muted-foreground" />
                      <span className="text-sm text-muted-foreground font-mono">
                        {zipFile ? zipFile.name : "上传新的 ZIP 文件…"}
                      </span>
                      <input
                        type="file"
                        accept=".zip"
                        onChange={handleFileChange}
                        className="hidden"
                      />
                    </label>
                  </div>
                </div>
              )}

              {/* 高级选项 */}
              <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
                <CollapsibleTrigger className="flex items-center gap-2 text-xs font-mono text-muted-foreground hover:text-foreground transition-colors">
                  <ChevronRight className={`w-4 h-4 transition-transform ${showAdvanced ? "rotate-90" : ""}`} />
                  <Settings2 className="w-4 h-4" />
                  <span className="uppercase font-bold">高级设置</span>
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-3 space-y-3">
                  {discoveryV2 && <div className="grid grid-cols-3 gap-2">
                    <label className="text-xs text-muted-foreground">Token 上限<Input type="number" min={1000} max={2000000} step={1000} value={tokenBudget} onChange={e => setTokenBudget(Number(e.target.value))} /></label>
                    <label className="text-xs text-muted-foreground">最大轮次<Input type="number" min={1} max={200} value={maxIterations} onChange={e => setMaxIterations(Number(e.target.value))} /></label>
                    <label className="text-xs text-muted-foreground">超时（分钟）<Input type="number" min={1} max={120} value={timeoutMinutes} onChange={e => setTimeoutMinutes(Number(e.target.value))} /></label>
                  </div>}
                  {/* 文件选择 */}
                  {(() => {
                    const isRepo = isRepositoryProject(selectedProject);
                    const isZip = isZipProject(selectedProject);
                    const hasStoredZip = storedZipInfo?.has_file || storedZipInfo?.has_persistent_source;
                    const canSelectFiles = isRepo || isLocalDirectoryProject(selectedProject) || (isZip && useStoredZip && hasStoredZip);

                    return (
                      <div className="flex items-center justify-between p-3 border border-dashed border-border rounded bg-muted/50">
                        <div>
                          <p className="font-mono text-xs uppercase font-bold text-muted-foreground">审计范围</p>
                          <p className="text-sm text-foreground font-mono font-bold mt-1">
                            {selectedFiles
                              ? `${selectedFiles.length} 个已选文件`
                              : "全部文件"}
                          </p>
                        </div>
                        <div className="flex gap-2">
                          {selectedFiles && canSelectFiles && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setSelectedFiles(undefined)}
                              className="h-8 text-xs text-rose-400 hover:bg-rose-900/30 hover:text-rose-300"
                            >重置</Button>
                          )}
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => setShowFileSelection(true)}
                            disabled={!canSelectFiles}
                            className="h-8 text-xs cyber-btn-outline font-mono font-bold disabled:opacity-50"
                          >
                            <FolderOpen className="w-3 h-3 mr-1" />选择文件</Button>
                        </div>
                      </div>
                    );
                  })()}

                  {/* 排除模式 */}
                  <div className="p-3 border border-dashed border-border rounded bg-muted/50 space-y-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs uppercase font-bold text-muted-foreground">
                        排除规则
                      </span>
                      <button
                        type="button"
                        onClick={() => setExcludePatterns(DEFAULT_EXCLUDES)}
                        className="text-xs font-mono text-primary hover:text-primary/80"
                      >
                        重置
                      </button>
                    </div>

                    <div className="flex flex-wrap gap-1.5">
                      {excludePatterns.map((p) => (
                        <Badge
                          key={p}
                          className="bg-muted text-foreground border-0 font-mono text-xs cursor-pointer hover:bg-rose-900/50 hover:text-rose-400"
                          onClick={() => setExcludePatterns((prev) => prev.filter((x) => x !== p))}
                        >
                          {p} ×
                        </Badge>
                      ))}
                    </div>

                    <Input
                      placeholder="输入排除规则，按回车添加…"
                      className="h-8 cyber-input text-sm"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && e.currentTarget.value) {
                          const val = e.currentTarget.value.trim();
                          if (val && !excludePatterns.includes(val)) {
                            setExcludePatterns((prev) => [...prev, val]);
                          }
                          e.currentTarget.value = "";
                        }
                      }}
                    />
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 flex justify-end gap-3 px-5 py-4 bg-muted border-t border-border">
          <Button
            variant="ghost"
            onClick={() => onOpenChange(false)}
            disabled={creating}
            className="px-4 h-10 font-mono text-muted-foreground hover:text-foreground hover:bg-muted"
          >
            取消
          </Button>
          <Button
            onClick={handleCreate}
            disabled={!canStart || creating || tokenBudget < 1000 || tokenBudget > 2000000 || maxIterations < 1 || maxIterations > 200 || timeoutMinutes < 1 || timeoutMinutes > 120}
            className="px-5 h-10 cyber-btn-primary font-mono font-bold uppercase"
          >
            {creating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin mr-2" />
                正在创建…
              </>
            ) : (
              <>
                <Play className="w-4 h-4 mr-2" />
                开始审计
              </>
            )}
          </Button>
        </div>
      </DialogContent>

      {/* 文件选择对话框 */}
      <FileSelectionDialog
        open={showFileSelection}
        onOpenChange={setShowFileSelection}
        projectId={selectedProjectId}
        branch={branch}
        excludePatterns={excludePatterns}
        onConfirm={setSelectedFiles}
      />
    </Dialog>
  );
}

// 项目列表项
function ProjectItem({
  project,
  selected,
  onSelect,
}: {
  project: Project;
  selected: boolean;
  onSelect: () => void;
}) {
  const isRepo = isRepositoryProject(project);

  return (
    <button type="button" aria-pressed={selected}
      className={`w-full text-left flex items-center gap-3 p-3 cursor-pointer rounded transition-all ${selected
          ? "bg-primary/10 border border-primary/50"
          : "hover:bg-muted border border-transparent"
        }`}
      onClick={onSelect}
    >
      <div className={`p-1.5 rounded ${isRepo ? "bg-blue-500/20" : "bg-amber-500/20"}`}>
        {isRepo ? (
          <Globe className="w-4 h-4 text-blue-400" />
        ) : (
          <Package className="w-4 h-4 text-amber-400" />
        )}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className={`font-mono text-sm truncate ${selected ? 'text-foreground font-bold' : 'text-foreground'}`}>
            {project.name}
          </span>
          <Badge
            className={`text-xs px-1 py-0 font-mono ${isRepo
                ? "bg-blue-500/20 text-blue-400 border-blue-500/30"
                : "bg-amber-500/20 text-amber-400 border-amber-500/30"
              }`}
          >
            {isRepo ? "仓库" : isLocalDirectoryProject(project) ? "本地目录" : "ZIP"}
          </Badge>
        </div>
        {project.description && (
          <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
            {project.description}
          </p>
        )}
      </div>

      {selected && (
        <div className="w-2 h-2 rounded-full bg-primary" />
      )}
    </button>
  );
}
