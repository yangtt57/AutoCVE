import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";

const asRecord = (value: unknown): Record<string, unknown> => value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown) => typeof value === "string" || typeof value === "number" ? String(value) : "";
const status: Record<string, string> = { statically_supported: "静态支持", needs_context: "未决线索", ruled_out: "已排除" };

export default function DiscoveryRecordView({ detail, onClose }: {
  detail: { title: string; value: unknown } | null; onClose: () => void;
}) {
  const record = asRecord(detail?.value);
  const payload = Object.keys(asRecord(record.payload)).length ? asRecord(record.payload) : record;
  const content = text(payload.content);
  const file = text(payload.file_path);
  const start = Number(payload.line_start) || 1;
  const source = record.kind === "source" && Boolean(content);
  const history = Array.isArray(detail?.value) ? detail.value : null;
  return <Dialog open={Boolean(detail)} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="flex max-h-[85vh] max-w-4xl flex-col overflow-hidden">
      <DialogHeader>
        <DialogTitle>{detail?.title}</DialogTitle>
        <DialogDescription>{source ? `${file} · 第 ${start}–${payload.line_end || start} 行` : "查看结论依据与变化记录"}</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-4 overflow-y-auto">
        {source ? <>
          <div className="overflow-x-auto rounded-md border bg-slate-50 text-xs text-slate-800">
            <pre className="py-3 font-mono leading-6">{content.split("\n").map((line, i) => <div key={i} className="flex min-w-max hover:bg-slate-100">
              <span className="sticky left-0 mr-4 inline-block w-14 shrink-0 select-none border-r bg-slate-50 pr-3 text-right text-slate-400">{start + i}</span><code className="pr-4">{line || " "}</code>
            </div>)}</pre>
          </div>
          <p className="text-xs text-muted-foreground">此片段来自本次审计的固定源码快照，行号对应原始文件。</p>
        </> : history ? <div className="space-y-3">{history.map((item, i) => {
          const version = asRecord(item);
          const data = Object.keys(asRecord(version.payload)).length ? asRecord(version.payload) : version;
          return <article key={i} className="rounded-md border p-4">
            <p className="text-xs text-muted-foreground">版本 {text(data.record_version || version.record_version || i + 1)} · {status[text(data.status)] || text(data.status)}</p>
            <p className="mt-2 text-sm font-medium">{text(data.claim)}</p><p className="mt-2 text-sm">{text(data.change_reason)}</p>
            {Array.isArray(data.unknowns) && data.unknowns.length > 0 && <p className="mt-2 text-xs text-amber-700">未决条件：{data.unknowns.map(text).join("；")}</p>}
          </article>;
        })}</div> : <div className="space-y-2 rounded-md border p-4 text-sm">
          {text(payload.rule_id) && <p className="font-medium break-all">{text(payload.rule_id)}</p>}
          {file && <p className="text-xs text-muted-foreground break-all">{file}{payload.line_start ? `:${start}` : ""}</p>}
          <p>{text(payload.description_preview || payload.description || payload.reason || payload.entry_path) || "该记录的结构化内容可在下方展开查看。"}</p>
          {content && <pre className="max-h-96 overflow-auto whitespace-pre-wrap text-xs">{content}</pre>}
          {text(asRecord(payload.decision).reason) && <p>研判依据：{text(asRecord(payload.decision).reason)}</p>}
        </div>}
        <details className="rounded-md border p-3 text-xs"><summary className="cursor-pointer text-muted-foreground">原始记录与元数据</summary>
          <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(detail?.value, null, 2)}</pre>
        </details>
      </div>
    </DialogContent>
  </Dialog>;
}
