import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, FolderGit2, ListChecks, ShieldCheck, Plus, ScanLine } from 'lucide-react';
import { Button } from '@/components/ui/button';
import CreateAgentTaskDialog from '@/components/agent/CreateAgentTaskDialog';

export default function HomeCover() {
  const [creating, setCreating] = useState(false);
  return <div className="mx-auto max-w-5xl space-y-10 py-6 md:py-12">
    <header className="max-w-2xl space-y-5">
      <div className="flex items-center gap-2 text-sm font-medium text-primary"><ScanLine className="h-4 w-4" />源码安全工作台</div>
      <h1 className="text-3xl leading-tight md:text-4xl">从源码到证据，<br className="hidden sm:block" />让每一次审计有据可查。</h1>
      <p className="max-w-xl text-sm leading-7 text-muted-foreground">选择项目，启动规则扫描与 Agent 分析。集中查看漏洞线索、审计证据和待处理范围，再按需运行 PoC 验证。</p>
      <div className="flex flex-wrap gap-3 pt-2">
        <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />新建审计</Button>
        <Button variant="outline" asChild><Link to="/audit-tasks">查看审计任务<ArrowRight className="h-4 w-4" /></Link></Button>
      </div>
    </header>
    <div className="grid gap-4 sm:grid-cols-3">
      {[{ to: '/projects', icon: FolderGit2, title: '管理项目', text: '接入 Git 仓库、ZIP 或本地源码，明确版本与审计范围。' },
        { to: '/audit-tasks', icon: ListChecks, title: '跟进审计', text: '查看任务进度、实际阅读记录和未决线索。' },
        { to: '/vulnerabilities', icon: ShieldCheck, title: '核查漏洞', text: '对照源码证据，管理漏洞并发起动态验证。' }].map(item => <Link key={item.to} to={item.to} className="group rounded-lg border bg-card p-5 transition-colors hover:border-primary/50">
          <item.icon className="mb-5 h-5 w-5 text-muted-foreground" />
          <div className="mb-2 flex items-center justify-between"><h2 className="text-sm font-semibold">{item.title}</h2><ArrowRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" /></div>
          <p className="text-xs leading-6 text-muted-foreground">{item.text}</p>
        </Link>)}
    </div>
    <div className="flex flex-wrap items-center justify-between gap-4 border-t pt-6">
      <div><p className="text-sm font-medium">需要完整的 CVE 挖掘流程？</p><p className="mt-1 text-xs text-muted-foreground">从项目审计、动态验证到报告，继续使用一键挖掘。</p></div>
      <Button asChild variant="ghost"><Link to="/one-click-cve?start=1">打开一键挖掘<ArrowRight className="h-4 w-4" /></Link></Button>
    </div>
    <CreateAgentTaskDialog open={creating} onOpenChange={setCreating} />
  </div>;
}
