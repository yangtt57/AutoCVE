import { useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { BookOpen, Bot, ChevronLeft, ChevronRight, FileText, FolderGit2, WandSparkles,
  LayoutDashboard, ListTodo, Menu, ScanSearch, Settings, ShieldAlert, UserCircle, X } from 'lucide-react';
import routes from '@/app/routes';
import { Button } from '@/components/ui/button';
import { appVersionLabel } from '@/shared/config/version';

const icons = { '/': Bot, '/dashboard': LayoutDashboard, '/projects': FolderGit2,
  '/one-click-cve': WandSparkles, '/audit-tasks': ListTodo, '/skills': BookOpen,
  '/report-templates': FileText, '/vulnerabilities': ShieldAlert, '/checkmarx-scan': ScanSearch, '/admin': Settings };

export default function Sidebar({ collapsed, setCollapsed }: { collapsed: boolean; setCollapsed: (value: boolean) => void }) {
  const { pathname } = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  return <>
    <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b bg-card px-4 md:hidden">
      <Button variant="ghost" size="icon" aria-label={mobileOpen ? '关闭导航' : '打开导航'} aria-expanded={mobileOpen} onClick={() => { if (!mobileOpen) setCollapsed(false); setMobileOpen(!mobileOpen); }}>
        {mobileOpen ? <X /> : <Menu />}
      </Button><span className="text-sm font-semibold">AutoCVE</span>
    </header>
    {mobileOpen && <button type="button" aria-label="关闭导航遮罩" className="fixed inset-0 z-40 bg-black/25 md:hidden" onClick={() => setMobileOpen(false)} />}
    <aside aria-label="主导航" className={`fixed inset-y-0 left-0 z-50 flex flex-col border-r bg-card transition-[width,transform] duration-200 ${collapsed ? 'w-[72px]' : 'w-[224px]'} ${mobileOpen ? 'visible translate-x-0' : 'invisible -translate-x-full md:visible md:translate-x-0'}`}>
      <div className={`flex h-16 shrink-0 items-center border-b ${collapsed ? 'justify-center' : 'px-5 gap-3'}`}>
        <Link to="/" className="flex min-w-0 items-center gap-2.5" onClick={() => setMobileOpen(false)} aria-label="AutoCVE 首页">
          <img src="/autocve_icon.svg" alt="AutoCVE" className="h-8 w-8" />
          {!collapsed && <span className="text-lg font-semibold tracking-tight">AutoCVE</span>}
        </Link>
        <button type="button" aria-label="关闭导航" className="ml-auto p-1 md:hidden" onClick={() => setMobileOpen(false)}><X className="h-4 w-4" /></button>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto p-3">
        {routes.filter(route => route.visible !== false).map(route => {
          const active = pathname === route.path || (route.path !== '/' && pathname.startsWith(`${route.path}/`)) || (route.path === '/audit-tasks' && pathname.startsWith('/agent-audit/'));
          const Icon = icons[route.path as keyof typeof icons] || LayoutDashboard;
          return <Link key={route.path} to={route.path} title={collapsed ? route.name : undefined} aria-label={route.name}
            aria-current={active ? 'page' : undefined} onClick={() => setMobileOpen(false)}
            className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm transition-colors ${active ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground hover:bg-muted hover:text-foreground'} ${collapsed ? 'justify-center px-0' : ''}`}>
            <Icon className="h-[18px] w-[18px] shrink-0" />{!collapsed && <span className="truncate">{route.name}</span>}
          </Link>;
        })}
      </nav>
      <div className="space-y-2 border-t p-3">
        <Link to="/account" title="账号设置" aria-label="账号设置" onClick={() => setMobileOpen(false)} className={`flex h-10 items-center gap-3 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted ${collapsed ? 'justify-center px-0' : ''}`}>
          <UserCircle className="h-[18px] w-[18px]" />{!collapsed && '账号设置'}
        </Link>
        <div className={`hidden items-center md:flex ${collapsed ? 'justify-center' : 'justify-between px-3'}`}>
          {!collapsed && <span className="text-xs text-muted-foreground">{appVersionLabel}</span>}
          <button type="button" aria-label={collapsed ? '展开导航' : '收起导航'} className="rounded p-1.5 text-muted-foreground hover:bg-muted" onClick={() => setCollapsed(!collapsed)}>
            {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
          </button>
        </div>
      </div>
    </aside>
  </>;
}
