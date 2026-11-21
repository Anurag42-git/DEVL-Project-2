import { useState, type FormEvent, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  Activity, BarChart3, ClipboardCheck, FileText, LayoutDashboard, Menu,
  Moon, RefreshCw, Search, ShieldCheck, Sun,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useTheme } from '@/components/layout/ThemeProvider';
import { cn } from '@/lib/utils';

const NAV = [
  { to: '/overview', label: 'Overview', icon: LayoutDashboard },
  { to: '/review', label: 'Review Queue', icon: ClipboardCheck },
  { to: '/ledger', label: 'Ledger', icon: BarChart3 },
  { to: '/data-quality', label: 'Data Quality', icon: Activity },
  { to: '/report', label: 'Audit Report', icon: FileText },
];

interface AppShellProps {
  children: ReactNode;
  onReload: () => void;
  reloading: boolean;
}

export function AppShell({ children, onReload, reloading }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [search, setSearch] = useState('');
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    const term = search.trim();
    if (!term) return;
    navigate(`/review?search=${encodeURIComponent(term)}`);
    setMobileOpen(false);
  }

  const sidebar = (
    <aside
      className={cn(
        'no-print flex h-full flex-col border-r border-line bg-surface transition-[width] duration-200',
        collapsed ? 'w-[72px]' : 'w-60',
      )}
    >
      <div className="flex h-16 items-center gap-2 border-b border-line px-4">
        <ShieldCheck className="h-6 w-6 shrink-0 text-accent" aria-hidden />
        {!collapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">Investigation</p>
            <p className="truncate text-[10px] text-muted">Payment monitoring</p>
          </div>
        )}
      </div>

      <nav className="flex-1 space-y-1 p-2" aria-label="Main navigation">
        {NAV.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.to}
              to={item.to}
              onClick={() => setMobileOpen(false)}
              title={collapsed ? item.label : undefined}
              className={({ isActive }) =>
                cn(
                  'flex h-10 items-center gap-3 rounded-lg px-3 text-sm transition-colors duration-150',
                  collapsed && 'justify-center px-0',
                  isActive
                    ? 'bg-accent/15 font-medium text-accent'
                    : 'text-muted hover:bg-elevated hover:text-ink',
                )
              }
            >
              <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
              {!collapsed && <span>{item.label}</span>}
            </NavLink>
          );
        })}
      </nav>

      <div className="border-t border-line p-2">
        <button
          type="button"
          onClick={() => setCollapsed((value) => !value)}
          className={cn(
            'flex h-9 w-full items-center gap-3 rounded-lg px-3 text-xs text-muted transition-colors hover:bg-elevated hover:text-ink',
            collapsed && 'justify-center px-0',
          )}
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <Menu className="h-4 w-4" aria-hidden />
          {!collapsed && <span>Collapse sidebar</span>}
        </button>
      </div>
    </aside>
  );

  return (
    <div className="flex min-h-screen bg-canvas">
      <div className="no-print hidden md:block">{sidebar}</div>

      {mobileOpen && (
        <div className="no-print fixed inset-0 z-50 md:hidden">
          <button
            type="button"
            aria-label="Close navigation"
            className="absolute inset-0 bg-black/60"
            onClick={() => setMobileOpen(false)}
          />
          <div className="relative h-full w-64 animate-slide-in">{sidebar}</div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="no-print sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-line bg-canvas/95 px-4 backdrop-blur md:px-6">
          <button
            type="button"
            className="rounded-lg p-2 text-muted hover:bg-elevated md:hidden"
            onClick={() => setMobileOpen(true)}
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" />
          </button>
          <form onSubmit={submitSearch} className="relative max-w-xl flex-1" role="search">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search transaction, customer, merchant or device ID"
              aria-label="Global search"
              className="pl-9"
            />
          </form>
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={onReload} disabled={reloading}
              aria-label="Reload data" title="Reload data">
              <RefreshCw className={cn('h-4 w-4', reloading && 'animate-spin')} />
            </Button>
            <Button variant="ghost" size="icon" onClick={toggleTheme}
              aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}>
              {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </header>

        <main className="flex-1 px-4 py-6 md:px-6 lg:px-8">{children}</main>

        <footer className="no-print border-t border-line px-4 py-3 text-center text-[11px] text-muted md:px-6">
          Flags are review triggers for unusual patterns, not fraud determinations.
          <span className="mx-2 text-line">·</span>
          {location.pathname.replace('/', '') || 'overview'}
        </footer>
      </div>
    </div>
  );
}
