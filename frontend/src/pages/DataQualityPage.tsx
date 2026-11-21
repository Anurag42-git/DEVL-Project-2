import { Fragment, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { ChevronDown, ChevronRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ChartCard } from '@/components/shared/ChartCard';
import { ErrorState, PageHeader } from '@/components/shared/States';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { humanize, number } from '@/lib/format';
import { cn } from '@/lib/utils';

const severityStyles: Record<string, string> = {
  high: 'text-red-400 border-red-500/30 bg-red-500/10',
  medium: 'text-amber-500 border-amber-500/30 bg-amber-500/10',
  low: 'text-sky-400 border-sky-500/30 bg-sky-500/10',
};

export function DataQualityPage() {
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['data-quality'],
    queryFn: api.dataQuality,
  });
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  function toggle(rule: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(rule)) next.delete(rule);
      else next.add(rule);
      return next;
    });
  }

  const rulesWithFindings = data?.summary.filter((row) => row.count > 0) ?? [];
  const maxCount = Math.max(1, ...rulesWithFindings.map((row) => row.count));

  return (
    <>
      <PageHeader
        title="Data Quality"
        description="Independent validation rules run on the raw files before reconciliation. Some violations are deliberate injections in this synthetic dataset."
      />

      {isError ? (
        <Card><ErrorState message={error.message} onRetry={() => void refetch()} /></Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Rules evaluated', value: data?.totals.rules },
              { label: 'Total violations', value: data?.totals.violations },
              { label: 'High severity', value: data?.totals.high_severity },
              { label: 'Rules with findings', value: rulesWithFindings.length },
            ].map((item) => (
              <Card key={item.label} className="p-4">
                <p className="text-xs text-muted">{item.label}</p>
                {isLoading || !data ? (
                  <Skeleton className="mt-3 h-7 w-20" />
                ) : (
                  <p className="num mt-2 text-2xl font-semibold">{number(item.value)}</p>
                )}
              </Card>
            ))}
          </div>

          <div className="mt-4 grid gap-4 lg:grid-cols-[1.4fr_1fr]">
            <Card>
              <CardHeader>
                <CardTitle>Validation rules</CardTitle>
                <p className="text-xs text-muted">Select a rule to inspect example rows.</p>
              </CardHeader>
              <CardContent className="px-0 pb-2">
                {isLoading || !data ? (
                  <div className="space-y-2 px-5"><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /><Skeleton className="h-8 w-full" /></div>
                ) : (
                  <div className="overflow-x-auto">
                    <table className="w-full text-left text-xs">
                      <thead className="border-y border-line text-muted">
                        <tr>
                          <th className="px-5 py-2 font-medium">Rule</th>
                          <th className="px-3 py-2 font-medium">Severity</th>
                          <th className="px-3 py-2 text-right font-medium">Count</th>
                          <th className="w-8 px-2 py-2"><span className="sr-only">Expand</span></th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-line/70">
                        {data.summary.map((row) => {
                          const isOpen = expanded.has(row.rule);
                          const examples = data.violations.filter((item) => item.rule === row.rule);
                          return (
                            <Fragment key={row.rule}>
                              <tr className={cn('transition-colors', isOpen && 'bg-elevated/60')}>
                                <td className="px-5 py-2.5 font-mono text-[11px] text-ink">{row.rule}</td>
                                <td className="px-3 py-2.5">
                                  <span className={cn('rounded-full border px-2 py-0.5 text-[10px]', severityStyles[row.severity] ?? severityStyles.low)}>
                                    {row.severity}
                                  </span>
                                </td>
                                <td className="num px-3 py-2.5 text-right">
                                  <div className="flex items-center justify-end gap-2">
                                    <div className="h-1.5 w-16 overflow-hidden rounded-full bg-elevated">
                                      <div className="h-full rounded-full bg-accent" style={{ width: `${(row.count / maxCount) * 100}%` }} />
                                    </div>
                                    {row.count}
                                  </div>
                                </td>
                                <td className="px-2 py-2.5">
                                  <button
                                    type="button"
                                    onClick={() => toggle(row.rule)}
                                    aria-expanded={isOpen}
                                    aria-label={`${isOpen ? 'Hide' : 'Show'} examples for ${row.rule}`}
                                    className="rounded p-1 text-muted hover:bg-elevated hover:text-ink"
                                  >
                                    {isOpen ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                                  </button>
                                </td>
                              </tr>
                              {isOpen && (
                                <tr>
                                  <td colSpan={4} className="bg-elevated/40 px-5 py-3">
                                    {examples.length === 0 ? (
                                      <p className="text-xs text-muted">No violations for this rule.</p>
                                    ) : (
                                      <ul className="space-y-2">
                                        {examples.slice(0, 5).map((item, index) => (
                                          <li key={`${item.record_id}-${index}`} className="rounded-lg border border-line bg-surface p-2.5 text-[11px]">
                                            <span className="font-mono text-ink">{item.record_id}</span>
                                            <span className="mx-2 text-line">·</span>
                                            <span className="text-muted">{item.detail}</span>
                                          </li>
                                        ))}
                                      </ul>
                                    )}
                                  </td>
                                </tr>
                              )}
                            </Fragment>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                )}
              </CardContent>
            </Card>

            <div className="space-y-4">
              <ChartCard title="Violations by rule" description="Only rules with findings">
                {data && (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={rulesWithFindings.slice(0, 10)} layout="vertical" margin={{ top: 4, right: 16, left: 4, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--line))" horizontal={false} />
                      <XAxis type="number" tick={{ fontSize: 11, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <YAxis type="category" dataKey="rule" width={120} tick={{ fontSize: 9, fill: 'rgb(var(--muted))' }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ backgroundColor: 'rgb(var(--elevated))', border: '1px solid rgb(var(--line))', borderRadius: 10, fontSize: 12 }} />
                      <Bar dataKey="count" fill="#fbbf24" fillOpacity={0.8} radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </ChartCard>

              <Card>
                <CardHeader><CardTitle>Status state machine</CardTitle></CardHeader>
                <CardContent>
                  <ul className="space-y-1.5 text-xs">
                    {data && Object.entries(data.state_machine).map(([state, allowed]) => (
                      <li key={state} className="flex gap-2">
                        <span className="min-w-28 font-mono text-ink">{state}</span>
                        <span className="text-muted">{allowed.length ? allowed.map(humanize).join(', ') : 'terminal'}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
}
