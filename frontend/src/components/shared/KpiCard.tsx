import { ArrowDownRight, ArrowUpRight, Minus } from 'lucide-react';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { delta } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { Kpi } from '@/types/api';

export function KpiCard({ kpi, loading }: { kpi?: Kpi; loading?: boolean }) {
  if (loading || !kpi) {
    return (
      <Card className="p-4">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-4 h-7 w-32" />
        <Skeleton className="mt-3 h-3 w-20" />
      </Card>
    );
  }
  const Trend = kpi.trend === 'up' ? ArrowUpRight : kpi.trend === 'down' ? ArrowDownRight : Minus;
  return (
    <Card className="p-4 transition-colors duration-150 hover:border-accent/40">
      <p className="text-xs font-medium text-muted">{kpi.label}</p>
      <p className="num mt-2 text-2xl font-semibold tracking-tight text-ink">{kpi.display}</p>
      <div className="mt-2 flex items-center gap-1 text-[11px] text-muted">
        {kpi.delta_pct === null ? (
          <span>No prior period comparison</span>
        ) : (
          <>
            <Trend
              className={cn(
                'h-3.5 w-3.5',
                kpi.trend === 'up' && 'text-emerald-500',
                kpi.trend === 'down' && 'text-red-400',
              )}
              aria-hidden
            />
            <span className="num">{delta(kpi.delta_pct)}</span>
            <span>vs prior period</span>
          </>
        )}
      </div>
    </Card>
  );
}
