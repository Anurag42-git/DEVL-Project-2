import type { ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { humanize } from '@/lib/format';
import type { Outcome, Priority } from '@/types/api';

const priorityStyles: Record<Priority, string> = {
  high: 'border-red-500/30 bg-red-500/10 text-red-500 dark:text-red-400',
  medium: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  low: 'border-sky-500/30 bg-sky-500/10 text-sky-600 dark:text-sky-400',
};

const outcomeStyles: Record<Outcome, string> = {
  pending: 'border-line bg-elevated text-muted',
  reviewed_normal: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400',
  needs_follow_up: 'border-amber-500/30 bg-amber-500/10 text-amber-600 dark:text-amber-400',
  escalated: 'border-red-500/30 bg-red-500/10 text-red-500 dark:text-red-400',
};

const base = 'inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4';

export function Badge({ children }: { children: ReactNode }) {
  return <span className={cn(base, 'border-line bg-elevated text-muted')}>{children}</span>;
}

export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  return (
    <span className={cn(base, priorityStyles[priority] ?? priorityStyles.low, className)}>
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden />
      {humanize(priority)}
    </span>
  );
}

export function OutcomeBadge({ outcome, className }: { outcome: Outcome; className?: string }) {
  return (
    <span className={cn(base, outcomeStyles[outcome] ?? outcomeStyles.pending, className)}>
      {humanize(outcome)}
    </span>
  );
}

export function ReasonChip({ code, onClick }: { code: string; onClick?: () => void }) {
  const content = <span className="rounded-md border border-line bg-elevated px-1.5 py-0.5 font-mono text-[10px] text-muted">{code}</span>;
  return onClick ? (
    <button type="button" onClick={onClick} className="transition-opacity hover:opacity-75">
      {content}
    </button>
  ) : (
    content
  );
}
