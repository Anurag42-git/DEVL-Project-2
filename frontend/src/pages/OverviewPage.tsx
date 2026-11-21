import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ComposedChart, Legend,
  Line, Pie, PieChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { ArrowUpRight, ShieldCheck } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartCard } from '@/components/shared/ChartCard';
import { KpiCard } from '@/components/shared/KpiCard';
import { EmptyState, ErrorState, PageHeader } from '@/components/shared/States';
import { PriorityBadge } from '@/components/shared/Badges';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { compactMoney, humanize, number, percent, shortDate } from '@/lib/format';

const tooltipStyle = {
  backgroundColor: 'rgb(var(--elevated))',
  border: '1px solid rgb(var(--line))',
  borderRadius: '10px',
  color: 'rgb(var(--ink))',
  fontSize: '12px',
};

const priorityColors: Record<string, string> = {
  high: '#f87171',
  medium: '#fbbf24',
  low: '#60a5fa',
};

export function OverviewPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['overview'],
    queryFn: api.overview,
  });

  const kpis = data?.kpis.map((kpi) =>
    kpi.id === 'flagged'
      ? { ...kpi, display: `${number(kpi.value)} · ${percent(data.metrics.flag_rate)}` }
      : kpi,
  );

  return (
    <>
      <PageHeader
        title="Overview"
        description="Reconciled payment activity and explainable review flags across the monitored portfolio."
        actions={
          data && (
            <div className="flex items-center gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-xs text-muted">
              <ShieldCheck className="h-4 w-4 text-emerald-500" aria-hidden />
              Ledger conservation check:{' '}
              <span className={data.conservation.matched ? 'text-emerald-500' : 'text-red-400'}>
                {data.conservation.matched ? 'PASS' : 'FAIL'}
              </span>
            </div>
          )
        }
      />

      {isError ? (
        <Card><ErrorState message={error.message} onRetry={() => void refetch()} /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
            {(kpis ?? Array.from({ length: 5 }).map(() => undefined)).map((kpi, index) => (
              <KpiCard key={kpi?.id ?? index} kpi={kpi} loading={isLoading} />
            ))}
          </div>

          {isLoading || !data ? (
            <div className="mt-4 grid gap-4 lg:grid-cols-2">
              {Array.from({ length: 4 }).map((_, index) => (
                <Card key={index} className="p-5">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="mt-4 h-56 w-full" />
                </Card>
              ))}
            </div>
          ) : (
            <>
              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <ChartCard title="Transactions per day" description="Reconciled transaction count">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.daily} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
                      <defs>
                        <linearGradient id="txnFill" x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor="rgb(var(--accent))" stopOpacity={0.35} />
                          <stop offset="100%" stopColor="rgb(var(--accent))" stopOpacity={0} />
                        </linearGradient>
                      </defs>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <YAxis tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={tooltipStyle} labelFormatter={(value) => String(value)} />
                      <Area type="monotone" dataKey="transactions" stroke="rgb(var(--accent))" fill="url(#txnFill)" strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartCard>

                <ChartCard title="Captured vs refunded" description="Daily settlement amounts">
                  <ResponsiveContainer width="100%" height="100%">
                    <ComposedChart data={data.daily} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <YAxis tickFormatter={(value: number) => compactMoney(value)} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={tooltipStyle} formatter={(value) => compactMoney(Number(value))} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="captured" name="Captured" fill="rgb(var(--accent))" fillOpacity={0.55} radius={[3, 3, 0, 0]} />
                      <Line dataKey="refunded" name="Refunded" stroke="#fbbf24" strokeWidth={2} dot={false} type="monotone" />
                    </ComposedChart>
                  </ResponsiveContainer>
                </ChartCard>

                <ChartCard title="Flags by reason code" description="Most common unusual patterns">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data.reason_counts.slice(0, 10)} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <YAxis type="category" dataKey="name" width={118} tick={{ fontSize: 10, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={tooltipStyle} formatter={(value) => [`${number(Number(value))} records`, 'Flagged']} />
                      <Bar dataKey="value" name="Flagged" fill="rgb(var(--accent))" fillOpacity={0.8} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </ChartCard>

                <ChartCard title="Priority distribution" description="Current review queue mix">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie data={data.priority_counts} dataKey="value" nameKey="name" innerRadius={58} outerRadius={86} paddingAngle={3} stroke="none">
                        {data.priority_counts.map((entry) => (
                          <Cell key={entry.name} fill={priorityColors[entry.name] ?? 'rgb(var(--muted))'} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={tooltipStyle} formatter={(value) => [`${number(Number(value))} records`, 'Flagged']} />
                      <Legend wrapperStyle={{ fontSize: 11 }} formatter={(value) => humanize(String(value))} />
                    </PieChart>
                  </ResponsiveContainer>
                </ChartCard>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <ChartCard title="Refund ratio trend" description={`Alert threshold ${percent(data.refund_threshold, 0)}`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={data.daily} margin={{ top: 8, right: 8, left: -22, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" vertical={false} />
                      <XAxis dataKey="date" tickFormatter={shortDate} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <YAxis tickFormatter={(value: number) => percent(value, 0)} tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={tooltipStyle} formatter={(value) => percent(Number(value), 2)} />
                      <ReferenceLine y={data.refund_threshold} stroke="#fbbf24" strokeDasharray="4 4" />
                      <Area type="monotone" dataKey="refund_ratio" stroke="#fbbf24" fill="#fbbf24" fillOpacity={0.12} strokeWidth={2} />
                    </AreaChart>
                  </ResponsiveContainer>
                </ChartCard>

                <Card>
                  <CardHeader>
                    <CardTitle>Needs attention</CardTitle>
                    <p className="text-xs text-muted">Highest-scoring items still pending review.</p>
                  </CardHeader>
                  <CardContent>
                    {data.needs_attention.length === 0 ? (
                      <EmptyState title="Nothing pending" message="All flagged records have a review outcome." />
                    ) : (
                      <ul className="divide-y divide-line">
                        {data.needs_attention.map((item) => (
                          <li key={item.record_id}>
                            <Link
                              to={`/review?search=${encodeURIComponent(item.record_id)}`}
                              className="group flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors duration-150 hover:bg-elevated"
                            >
                              <span className="num w-10 text-center text-sm font-semibold text-ink">{item.score}</span>
                              <div className="min-w-0 flex-1">
                                <p className="truncate font-mono text-xs text-ink">{item.record_id}</p>
                                <p className="truncate text-[11px] text-muted">{item.reason_codes.join(' · ')}</p>
                              </div>
                              <PriorityBadge priority={item.priority} />
                              <ArrowUpRight className="h-4 w-4 text-muted transition-colors group-hover:text-accent" aria-hidden />
                            </Link>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}
