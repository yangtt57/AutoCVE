import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  Ban,
  ChevronDown,
  ChevronRight,
  CircleCheck,
  Clock,
  Copy,
  ExternalLink,
  FlaskConical,
  Globe,
  HelpCircle,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  ShieldQuestion,
  ShieldX,
  Terminal,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { exportVulnerabilityReport } from '@/shared/api/vulnerabilities';
import {
  getLatestVulnerabilityVerification,
  isVerificationActive,
  isVerificationDisabled,
  isVerificationPaused,
  listVulnerabilityVerifications,
  pauseVulnerabilityVerification,
  resumeVulnerabilityVerification,
  startVulnerabilityVerification,
  type VerificationHttpExchange,
  type VerificationStep,
  type VulnerabilityVerification,
} from '@/shared/api/verifications';

const POLL_INTERVAL_MS = 5000;

const VERDICT_META: Record<
  string,
  { label: string; description: string; className: string; icon: typeof ShieldCheck }
> = {
  confirmed: {
    label: '已确认',
    description: '验证 Agent 在真实运行环境里复现出了该漏洞，并留下了原始证据。',
    className: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    icon: ShieldCheck,
  },
  refuted: {
    label: '已推翻',
    description: '真实环境里无法复现，报告里的利用链在这一版本/配置下不成立。',
    className: 'border-slate-300 bg-slate-100 text-slate-700',
    icon: ShieldX,
  },
  inconclusive: {
    label: '未得出结论',
    description: '环境跑起来了，但证据不足以判定成立或不成立，需要人工复核。',
    className: 'border-amber-200 bg-amber-50 text-amber-900',
    icon: ShieldQuestion,
  },
  unverifiable: {
    label: '不可验证',
    description: '项目在这个环境里跑不起来（缺依赖、需要商业组件等），未做动态判定。',
    className: 'border-zinc-300 bg-zinc-100 text-zinc-700',
    icon: Ban,
  },
};

const STATUS_META: Record<string, { label: string; className: string }> = {
  pending: { label: '排队中', className: 'border-slate-300 bg-slate-100 text-slate-700' },
  running: { label: '验证中', className: 'border-sky-200 bg-sky-50 text-sky-800' },
  paused: { label: '已暂停', className: 'border-amber-200 bg-amber-50 text-amber-900' },
  completed: { label: '已完成', className: 'border-slate-300 bg-white text-slate-700' },
  failed: { label: '失败', className: 'border-rose-200 bg-rose-50 text-rose-800' },
  cancelled: { label: '已取消', className: 'border-zinc-300 bg-zinc-100 text-zinc-700' },
};

const METHOD_LABELS: Record<string, string> = {
  compose: 'docker compose 完整跑起',
  dockerfile: '按 Dockerfile 构建运行',
  minimal: '最小依赖手工跑起',
  harness: '抽取函数做 harness（不作为独立证据）',
  none: '未搭建环境',
};

function formatDuration(seconds?: number | null): string {
  if (seconds === null || seconds === undefined) return '-';
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (minutes < 60) return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分`;
  const hours = Math.floor(minutes / 60);
  return `${hours} 小时 ${minutes % 60} 分`;
}

function formatTime(value?: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleString('zh-CN', { hour12: false });
}

function formatBytes(bytes?: number | null): string {
  if (bytes === null || bytes === undefined) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

async function copyText(text: string, label = '已复制') {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(label);
  } catch {
    toast.error('复制失败，请手动选中');
  }
}

function RawBlock({
  title,
  content,
  tone = 'slate',
}: {
  title: string;
  content: string;
  tone?: 'slate' | 'rose';
}) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</span>
        <button
          type="button"
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 transition hover:bg-slate-100 hover:text-slate-700"
          onClick={() => copyText(content, `${title} 已复制`)}
        >
          <Copy className="h-3 w-3" />
          复制
        </button>
      </div>
      <pre
        className={`max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-xl border p-3 font-mono text-[11.5px] leading-5 ${
          tone === 'rose'
            ? 'border-rose-200 bg-rose-50/60 text-rose-900'
            : 'border-slate-200 bg-slate-50 text-slate-800'
        }`}
      >
        {content}
      </pre>
    </div>
  );
}

function StepRow({ step, index }: { step: VerificationStep; index: number }) {
  const [open, setOpen] = useState(index === 0);
  const ok = step.exit_code === 0 || step.exit_code === null || step.exit_code === undefined;
  const hasOutput = Boolean(step.stdout?.trim() || step.stderr?.trim());

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <button
        type="button"
        className="flex w-full items-start gap-3 px-3 py-2.5 text-left"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="mt-0.5 shrink-0 text-slate-400">
          {open ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
        </span>
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 font-mono text-[11px] text-slate-600">
          {step.seq ?? index + 1}
        </span>
        <span className="min-w-0 flex-1 space-y-1">
          {step.intent ? <span className="block text-sm text-slate-800">{step.intent}</span> : null}
          <span className="block break-all font-mono text-[11.5px] leading-5 text-slate-500">
            {step.command || '(未记录命令)'}
          </span>
        </span>
        <span className="shrink-0">
          {step.exit_code === null || step.exit_code === undefined ? (
            <Badge variant="outline" className="font-mono text-[11px]">
              无退出码
            </Badge>
          ) : (
            <Badge
              variant="outline"
              className={`font-mono text-[11px] ${
                ok
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  : 'border-rose-200 bg-rose-50 text-rose-700'
              }`}
            >
              exit {step.exit_code}
            </Badge>
          )}
        </span>
      </button>
      {open ? (
        <div className="space-y-3 border-t border-slate-100 px-3 py-3">
          {hasOutput ? (
            <>
              {step.stdout?.trim() ? <RawBlock title="stdout" content={step.stdout} /> : null}
              {step.stderr?.trim() ? <RawBlock title="stderr" content={step.stderr} tone="rose" /> : null}
            </>
          ) : (
            <div className="text-xs text-slate-500">这一步没有记录到输出。</div>
          )}
        </div>
      ) : null}
    </div>
  );
}

function HttpExchangeCard({ exchange, index }: { exchange: VerificationHttpExchange; index: number }) {
  const { request, response } = exchange;
  const status = response?.status ?? null;
  const ok = status !== null && status >= 200 && status < 400;

  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline" className="font-mono text-[11px]">
          #{exchange.seq ?? index + 1}
        </Badge>
        <span className="font-mono text-xs text-slate-700">
          {request?.method || 'GET'} {request?.url || '-'}
        </span>
        {status !== null ? (
          <Badge
            variant="outline"
            className={`font-mono text-[11px] ${
              ok
                ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
                : 'border-rose-200 bg-rose-50 text-rose-700'
            }`}
          >
            HTTP {status}
          </Badge>
        ) : null}
      </div>
      {exchange.intent ? <div className="text-xs text-slate-500">{exchange.intent}</div> : null}
      {request?.body?.trim() ? <RawBlock title="请求体" content={request.body} /> : null}
      {response?.body?.trim() ? (
        <RawBlock title="响应体（原始）" content={response.body} tone={ok ? 'slate' : 'rose'} />
      ) : null}
    </div>
  );
}

export interface VerificationPanelProps {
  vulnerabilityId: string;
}

export function VerificationPanel({ vulnerabilityId }: VerificationPanelProps) {
  const [verification, setVerification] = useState<VulnerabilityVerification | null>(null);
  const [history, setHistory] = useState<VulnerabilityVerification[]>([]);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [pausing, setPausing] = useState(false);
  const [disabledHint, setDisabledHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const cancelledRef = useRef(false);

  const load = useCallback(async () => {
    try {
      const [latest, runs] = await Promise.all([
        getLatestVulnerabilityVerification(vulnerabilityId),
        listVulnerabilityVerifications(vulnerabilityId).catch(() => []),
      ]);
      if (cancelledRef.current) return;
      setVerification(latest);
      setHistory(runs);
      setDisabledHint(null);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      if (isVerificationDisabled(err)) {
        setDisabledHint(
          (err as { detail?: string }).detail ||
            '动态验证未启用。请设置 VERIFICATION_AGENT_ENABLED=true 并先启动 docker compose -f docker-compose.verify.yml up -d --build。'
        );
      } else {
        setError('加载验证记录失败');
      }
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [vulnerabilityId]);

  useEffect(() => {
    cancelledRef.current = false;
    setLoading(true);
    void load();
    return () => {
      cancelledRef.current = true;
    };
  }, [load]);

  // 验证在跑的时候轮询状态；结束后自动停下。
  useEffect(() => {
    if (!isVerificationActive(verification)) return;
    const timer = window.setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [verification, load]);

  // 进行中时每秒把 now 推进一步，让"已用时"真的走起来（真实状态靠上面的轮询）。
  // 暂停时跳过：时间已经冻在暂停那一刻了。
  useEffect(() => {
    if (!isVerificationActive(verification) || isVerificationPaused(verification)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [verification]);

  const handlePause = async () => {
    setPausing(true);
    try {
      const updated = await pauseVulnerabilityVerification(vulnerabilityId);
      setVerification(updated);
      toast.success('已暂停：Agent 的进程被冻住，随时可以继续');
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || '暂停失败');
    } finally {
      setPausing(false);
    }
  };

  const handleResume = async () => {
    setPausing(true);
    try {
      const updated = await resumeVulnerabilityVerification(vulnerabilityId);
      setVerification(updated);
      toast.success('已继续，Agent 从停下的地方接着跑');
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || '继续失败');
    } finally {
      setPausing(false);
    }
  };

  const handleStart = async () => {
    setStarting(true);
    try {
      const created = await startVulnerabilityVerification(vulnerabilityId, {
        rerun: Boolean(verification),
      });
      setVerification(created);
      setError(null);
      toast.success('已提交动态验证，Agent 开始在 Docker 里搭建环境');
      void load();
    } catch (err) {
      if (isVerificationDisabled(err)) {
        setDisabledHint(
          (err as { detail?: string }).detail || '动态验证未启用。'
        );
      } else {
        const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        toast.error(detail || '提交验证失败');
      }
    } finally {
      setStarting(false);
    }
  };

  const handleExportReport = async () => {
    try {
      const content = await exportVulnerabilityReport(vulnerabilityId, 'verification');
      const blob = new Blob([content], { type: 'text/markdown;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = 'verification_report.md';
      anchor.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error('还没有生成验证报告（验证完成或失败后才会写入）');
    }
  };

  const active = isVerificationActive(verification);
  const isPaused = isVerificationPaused(verification);
  const isRunning = !isPaused && active;
  const verdictMeta = verification?.verdict ? VERDICT_META[verification.verdict] : null;
  const statusMeta = verification ? STATUS_META[verification.status] ?? STATUS_META.completed : null;

  const elapsed = useMemo(() => {
    if (!active || !verification?.started_at) return verification?.duration_seconds ?? null;
    const started = new Date(verification.started_at).getTime();
    if (Number.isNaN(started)) return verification.duration_seconds ?? null;
    // 暂停中：时间停在暂停那一刻；已跑的时长里还要扣掉之前累计的暂停时长。
    const reference =
      isPaused && verification.paused_at
        ? new Date(verification.paused_at).getTime()
        : now;
    if (Number.isNaN(reference)) return verification.duration_seconds ?? null;
    return (reference - started) / 1000 - (verification.paused_seconds ?? 0);
  }, [active, isPaused, verification, now]);

  const steps = verification?.evidence?.steps ?? [];
  const exchanges = verification?.evidence?.http_exchanges ?? [];
  const reproduction = verification?.evidence?.reproduction ?? [];

  if (loading) {
    return (
      <div className="flex min-h-[420px] items-center justify-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        正在读取验证记录...
      </div>
    );
  }

  return (
    <div className="min-h-[520px] space-y-4 lg:max-h-[calc(94vh-280px)] lg:overflow-y-auto">
      {/* 顶部状态与控制 */}
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3">
        <div className="min-w-0 space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-slate-900">
              <FlaskConical className="h-4 w-4 text-teal-700" />
              独立动态验证
            </span>
            {statusMeta ? (
              <Badge variant="outline" className={statusMeta.className}>
                {isRunning ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                {isPaused ? <Pause className="mr-1 h-3 w-3" /> : null}
                {statusMeta.label}
              </Badge>
            ) : null}
            {verdictMeta ? (
              <Badge variant="outline" className={verdictMeta.className}>
                <verdictMeta.icon className="mr-1 h-3.5 w-3.5" />
                {verdictMeta.label}
              </Badge>
            ) : null}
            {verification?.confidence ? (
              <Badge variant="outline" className="border-slate-200 bg-white text-slate-600">
                置信度 {verification.confidence}
              </Badge>
            ) : null}
          </div>
          <p className="max-w-3xl text-xs leading-6 text-slate-500">
            由独立的 Pi Agent 在隔离 Docker 环境里把项目真正跑起来，尝试复现该漏洞；判为「已确认」必须附原始命令输出或原始 HTTP 请求响应。
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => void load()} disabled={loading}>
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            刷新
          </Button>
          {verification && !active ? (
            <Button size="sm" variant="outline" onClick={() => void handleExportReport()}>
              <ExternalLink className="h-4 w-4" />
              导出验证报告
            </Button>
          ) : null}
          {isRunning ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handlePause()}
              disabled={pausing}
            >
              {pausing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Pause className="h-4 w-4" />}
              暂停
            </Button>
          ) : null}
          {isPaused ? (
            <Button size="sm" onClick={() => void handleResume()} disabled={pausing}>
              {pausing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              继续
            </Button>
          ) : null}
          <Button size="sm" onClick={handleStart} disabled={starting || active || Boolean(disabledHint)}>
            {starting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            {active ? '验证进行中' : verification ? '重新验证' : '开始动态验证'}
          </Button>
        </div>
      </div>

      {disabledHint ? (
        <div className="space-y-2 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <AlertTriangle className="h-4 w-4" />
            动态验证还没有在这个部署里打开
          </div>
          <p className="text-xs leading-6 text-amber-900/90">{disabledHint}</p>
          <pre className="overflow-x-auto rounded-xl border border-amber-200 bg-white p-3 font-mono text-[11.5px] leading-5 text-slate-700">
{`# 1) 启动验证环境（首次会构建 Pi 镜像）
scripts/verify-stack.sh up -d --build

# 2) 打开开关后重启后端（backend/.env）
VERIFICATION_AGENT_ENABLED=true`}
          </pre>
        </div>
      ) : null}

      {error ? (
        <div className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-800">{error}</div>
      ) : null}

      {/* 没有任何记录 */}
      {!verification && !disabledHint && !error ? (
        <div className="flex min-h-[280px] flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-slate-50/60 px-6 text-center">
          <FlaskConical className="h-8 w-8 text-slate-400" />
          <div className="text-sm font-semibold text-slate-800">这条漏洞还没有做过动态验证</div>
          <p className="max-w-xl text-xs leading-6 text-slate-500">
            点「开始动态验证」后，Agent 会拉取对应版本的源码、在 Docker 里搭建运行环境，然后尝试证明或推翻报告里的利用链。整个过程通常几分钟到几十分钟。
          </p>
        </div>
      ) : null}

      {/* 已暂停 */}
      {isPaused ? (
        <div className="space-y-3 rounded-2xl border border-amber-200 bg-amber-50/80 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900">
            <Pause className="h-4 w-4" />
            验证已暂停，Agent 的进程被冻住，不再消耗 CPU 与模型额度
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-amber-900/80">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              已跑 {formatDuration(elapsed)}（暂停时间不计入）
            </span>
            {verification?.paused_at ? (
              <span>暂停于 {formatTime(verification.paused_at)}</span>
            ) : null}
          </div>
          <p className="text-xs leading-6 text-amber-900/80">
            继续后 Agent 会从停下的地方接着跑。注意：暂停时间过长时，正在等待的模型请求可能已被服务端断开，
            继续后这一轮可能失败、需要重新验证——短暂停（几分钟内）最稳。
          </p>
          <Button size="sm" onClick={() => void handleResume()} disabled={pausing}>
            {pausing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
            继续验证
          </Button>
        </div>
      ) : null}

      {/* 进行中 */}
      {isRunning ? (
        <div className="space-y-3 rounded-2xl border border-sky-200 bg-sky-50/70 px-4 py-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-sky-900">
            <Loader2 className="h-4 w-4 animate-spin" />
            {verification?.status === 'pending' ? '已排队，等待可用并发额度' : 'Agent 正在 Docker 里搭建环境并验证'}
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-sky-900/80">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              已用时 {formatDuration(elapsed)}
            </span>
            {verification?.model_id ? (
              <span className="inline-flex items-center gap-1">
                <Activity className="h-3.5 w-3.5" />
                模型 {verification.model_provider}/{verification.model_id}
                {verification.thinking_level ? ` · thinking=${verification.thinking_level}` : ''}
              </span>
            ) : null}
          </div>
          <p className="text-xs leading-6 text-sky-900/70">
            原始证据会在验证结束后一次性写入。中途可以在容器里看到进度：
            <code className="mx-1 rounded bg-white px-1.5 py-0.5 font-mono text-[11px]">
              docker exec autocve-pi-verifier ls /verifier/work
            </code>
          </p>
        </div>
      ) : null}

      {/* 结果 */}
      {verification && !active ? (
        <>
          {verdictMeta ? (
            <div className={`space-y-2 rounded-2xl border px-4 py-4 ${verdictMeta.className}`}>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <verdictMeta.icon className="h-4 w-4" />
                判定：{verdictMeta.label}
              </div>
              <p className="text-xs leading-6 opacity-90">{verdictMeta.description}</p>
              {verification.summary ? (
                <p className="pt-1 text-sm leading-7 opacity-95">{verification.summary}</p>
              ) : null}
            </div>
          ) : null}

          {verification.status === 'failed' && verification.error_message ? (
            <div className="space-y-2 rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold text-rose-900">
                <ShieldAlert className="h-4 w-4" />
                验证执行失败
              </div>
              <RawBlock title="错误信息" content={verification.error_message} tone="rose" />
            </div>
          ) : null}

          {verification.impact ? (
            <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">实际影响</h4>
              <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">{verification.impact}</p>
            </section>
          ) : null}

          {verification.refutation_reason ? (
            <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">推翻理由</h4>
              <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                {verification.refutation_reason}
              </p>
            </section>
          ) : null}

          {verification.unverifiable_reason ? (
            <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">不可验证的原因</h4>
              <p className="whitespace-pre-wrap text-sm leading-7 text-slate-700">
                {verification.unverifiable_reason}
              </p>
            </section>
          ) : null}

          {verification.environment ? (
            <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Globe className="h-4 w-4 text-slate-500" />
                验证环境
              </h4>
              <dl className="grid gap-3 text-xs sm:grid-cols-2">
                <div>
                  <dt className="uppercase tracking-[0.16em] text-slate-500">搭建方式</dt>
                  <dd className="mt-1 text-slate-800">
                    {METHOD_LABELS[verification.environment.method || 'none'] ||
                      verification.environment.method ||
                      '-'}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-[0.16em] text-slate-500">被测地址</dt>
                  <dd className="mt-1 break-all font-mono text-slate-800">
                    {verification.environment.app_url || '-'}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-[0.16em] text-slate-500">代码版本</dt>
                  <dd className="mt-1 break-all font-mono text-slate-800">
                    {verification.environment.commit_sha || '-'}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-[0.16em] text-slate-500">镜像指纹</dt>
                  <dd className="mt-1 break-all font-mono text-slate-800">
                    {verification.environment.image_digest || '-'}
                  </dd>
                </div>
                <div>
                  <dt className="uppercase tracking-[0.16em] text-slate-500">构建耗时</dt>
                  <dd className="mt-1 text-slate-800">
                    {formatDuration(verification.environment.build_seconds)}
                  </dd>
                </div>
                {verification.environment.notes ? (
                  <div className="sm:col-span-2">
                    <dt className="uppercase tracking-[0.16em] text-slate-500">补充说明</dt>
                    <dd className="mt-1 whitespace-pre-wrap text-slate-800">
                      {verification.environment.notes}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </section>
          ) : null}

          {steps.length ? (
            <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Terminal className="h-4 w-4 text-slate-500" />
                执行记录（原始输出）
                <span className="text-xs font-normal text-slate-500">{steps.length} 步</span>
              </h4>
              <div className="space-y-2">
                {steps.map((step, index) => (
                  <StepRow key={`${step.seq ?? index}`} step={step} index={index} />
                ))}
              </div>
            </section>
          ) : null}

          {exchanges.length ? (
            <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                <Globe className="h-4 w-4 text-slate-500" />
                HTTP 交互（原始请求响应）
                <span className="text-xs font-normal text-slate-500">{exchanges.length} 次</span>
              </h4>
              <div className="space-y-2">
                {exchanges.map((exchange, index) => (
                  <HttpExchangeCard key={`${exchange.seq ?? index}`} exchange={exchange} index={index} />
                ))}
              </div>
            </section>
          ) : null}

          {reproduction.length ? (
            <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">复现步骤</h4>
              <ol className="space-y-2 text-sm leading-6 text-slate-700">
                {reproduction.map((item, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 font-mono text-[11px] text-slate-600">
                      {index + 1}
                    </span>
                    <span className="whitespace-pre-wrap break-words">{item}</span>
                  </li>
                ))}
              </ol>
            </section>
          ) : null}

          {verification.artifacts?.length ? (
            <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">证据产物</h4>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-500">
                    <tr>
                      <th className="pb-2 pr-4 font-medium uppercase tracking-[0.16em]">文件</th>
                      <th className="pb-2 pr-4 font-medium uppercase tracking-[0.16em]">大小</th>
                      <th className="pb-2 font-medium uppercase tracking-[0.16em]">sha256</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono text-slate-700">
                    {verification.artifacts.map((artifact, index) => (
                      <tr key={index} className="border-t border-slate-100">
                        <td className="max-w-[280px] truncate py-2 pr-4">{artifact.path || '-'}</td>
                        <td className="py-2 pr-4">{formatBytes(artifact.bytes)}</td>
                        <td className="max-w-[360px] truncate py-2">{artifact.sha256 || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}

          {verification.limitations?.length ? (
            <section className="space-y-2 rounded-2xl border border-amber-200 bg-amber-50/70 p-4">
              <h4 className="flex items-center gap-2 text-sm font-semibold text-amber-900">
                <AlertTriangle className="h-4 w-4" />
                这次验证没有覆盖的部分
              </h4>
              <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-amber-900/90">
                {verification.limitations.map((item, index) => (
                  <li key={index} className="whitespace-pre-wrap break-words">
                    {item}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <section className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              耗时 {formatDuration(verification.duration_seconds ?? elapsed)}
            </span>
            <span>
              模型 {verification.model_provider || '-'}/{verification.model_id || '-'}
              {verification.thinking_level ? ` · thinking=${verification.thinking_level}` : ''}
            </span>
            <span>开始 {formatTime(verification.started_at)}</span>
            <span>结束 {formatTime(verification.completed_at)}</span>
            {verification.evidence_digest ? (
              <span className="inline-flex items-center gap-1">
                证据摘要
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-slate-700">
                  {verification.evidence_digest.slice(0, 16)}…
                </code>
                <button
                  type="button"
                  className="rounded-md p-1 transition hover:bg-slate-100"
                  onClick={() => copyText(verification.evidence_digest || '', '证据摘要已复制')}
                >
                  <Copy className="h-3 w-3" />
                </button>
              </span>
            ) : null}
          </section>

          {history.length > 1 ? (
            <section className="space-y-2 rounded-2xl border border-slate-200 bg-white p-4">
              <h4 className="text-sm font-semibold text-slate-900">历次验证</h4>
              <ul className="divide-y divide-slate-100">
                {history.map((item) => {
                  const meta = item.verdict ? VERDICT_META[item.verdict] : null;
                  return (
                    <li key={item.id} className="flex flex-wrap items-center gap-3 py-2 text-xs">
                      <span className="text-slate-500">{formatTime(item.created_at)}</span>
                      <Badge variant="outline" className={STATUS_META[item.status]?.className}>
                        {STATUS_META[item.status]?.label || item.status}
                      </Badge>
                      {meta ? (
                        <Badge variant="outline" className={meta.className}>
                          {meta.label}
                        </Badge>
                      ) : null}
                      <span className="text-slate-500">耗时 {formatDuration(item.duration_seconds)}</span>
                      {item.id === verification.id ? (
                        <span className="inline-flex items-center gap-1 text-teal-700">
                          <CircleCheck className="h-3.5 w-3.5" />
                          当前显示
                        </span>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          <section className="flex items-start gap-2 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-xs leading-6 text-slate-500">
            <HelpCircle className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
            <span>
              动态验证只回答"在这个环境、这个版本上能不能真的跑出效果"。即使判为「已确认」，也建议人工复核原始输出；判为「已推翻」时，请先确认没有落在上面列出的未覆盖范围内。
            </span>
          </section>
        </>
      ) : null}
    </div>
  );
}
