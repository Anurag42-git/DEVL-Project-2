import { useState, type ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Braces, Clock3, MapPin, Table2 } from 'lucide-react';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { Badge } from '@/components/shared/Badges';
import { OutcomeBadge, PriorityBadge } from '@/components/shared/Badges';
import { OutcomeForm } from '@/components/review/OutcomeForm';
import { Skeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { dateTime, humanize, money, number } from '@/lib/format';
import type { Outcome, Reason, ReviewItem, TimelineEvent } from '@/types/api';
import { cn } from '@/lib/utils';

function gaugeColor(score: number): string {
  return score >= 45 ? '#f87171' : score >= 22 ? '#fbbf24' : '#60a5fa';
}

function ScoreGauge({ score }: { score: number }) {
  return (
    <div className="relative h-16 w-16 shrink-0 rounded-full"
      style={{ background: `conic-gradient(${gaugeColor(score)} ${Math.min(score, 100) * 3.6}deg, rgb(var(--elevated)) 0deg)` }}>
      <div className="absolute inset-1.5 flex flex-col items-center justify-center rounded-full bg-surface">
        <span className="num text-lg font-semibold leading-none text-ink">{score}</span>
        <span className="text-[9px] uppercase text-muted">score</span>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-t border-line py-4">
      <h3 className="mb-3 text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3>
      {children}
    </section>
  );
}

function ReasonRow({ reason }: { reason: Reason }) {
  const actual = reason.actual ?? 0;
  const threshold = reason.threshold ?? 0;
  const ratio = reason.operator === '<='
    ? (threshold > 0 ? Math.min(100, (threshold / Math.max(actual, threshold)) * 100) : 100)
    : threshold > 0 ? Math.min(100, (actual / threshold) * 100) : 100;
  return (
    <li className="rounded-lg border border-line bg-elevated/40 p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs font-medium text-accent">{reason.code}</span>
        <span className="num text-[10px] text-muted">+{reason.weight} pts</span>
      </div>
      <p className="mt-1 text-xs leading-relaxed text-ink/90">{reason.explanation}</p>
      <p className="num mt-1 text-[11px] text-muted">{reason.detail}</p>
      <div className="mt-2 h-1 overflow-hidden rounded-full bg-line">
        <div className="h-full rounded-full bg-accent/80" style={{ width: `${Math.max(3, ratio)}%` }} />
      </div>
    </li>
  );
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) return <p className="text-xs text-muted">No lifecycle events available.</p>;
  return (
    <ol className="relative ml-2 space-y-3 border-l border-line pl-4">
      {events.map((event, index) => (
        <li key={`${event.kind}-${index}`} className="relative">
          <span className={cn('absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface',
            event.invalid ? 'bg-red-400' : 'bg-accent')} />
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="font-medium text-ink">{event.label}</span>
            <Badge>{humanize(event.status || 'recorded')}</Badge>
            {event.amount !== null && <span className="num text-muted">{money(event.amount)}</span>}
            {event.invalid && <span className="text-[10px] text-red-400">invalid transition</span>}
          </div>
          <p className="num text-[10px] text-muted">{dateTime(event.time)}</p>
        </li>
      ))}
    </ol>
  );
}

interface Props {
  item: ReviewItem | null;
  open: boolean;
  onClose: () => void;
  presetOutcome?: Outcome;
}

export function ReviewDetail({ item, open, onClose, presetOutcome }: Props) {
  const [showJson, setShowJson] = useState(false);
  const isTransaction = item?.record_type === 'transaction';
  const detailQuery = useQuery({
    queryKey: ['transaction', item?.record_id],
    queryFn: () => api.transaction(item?.record_id ?? ''),
    enabled: open && isTransaction && Boolean(item?.record_id),
  });
  const audit = useQuery({
    queryKey: ['audit-trail', item?.record_id],
    queryFn: () => api.auditTrail(item?.record_id ?? ''),
    enabled: open && Boolean(item?.record_id),
  });

  if (!item) return null;
  const detail = detailQuery.data;
  const indicator = detail?.indicators ?? {};
  const windows = [
    { label: '1h', value: Number(indicator.max_txns_1h ?? 0) },
    { label: '24h', value: Number(indicator.max_txns_24h ?? 0) },
    { label: '7d', value: Number(indicator.max_txns_7d ?? 0) },
  ];
  const maxWindow = Math.max(1, ...windows.map((item) => item.value));

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent side aria-describedby="review-detail-description">
        <div className="shrink-0 border-b border-line px-6 py-5 pr-14">
          <DialogTitle className="font-mono text-base font-semibold text-ink">{item.record_id}</DialogTitle>
          <DialogDescription id="review-detail-description" className="mt-1 text-xs text-muted">
            {humanize(item.record_type)} record · flags are review triggers, not determinations of intent
          </DialogDescription>
          <div className="mt-4 flex items-center gap-4">
            <ScoreGauge score={item.score} />
            <div className="flex flex-col items-start gap-2">
              <PriorityBadge priority={item.priority} />
              <OutcomeBadge outcome={item.outcome} />
            </div>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-6 pb-8">
          <Section title="Why this was flagged">
            <ul className="space-y-2">
              {item.reasons.length ? item.reasons.map((reason) => (
                <ReasonRow key={reason.code} reason={reason} />
              )) : <li className="text-xs text-muted">No reason details available.</li>}
            </ul>
          </Section>

          {isTransaction && (
            <>
              <Section title="Payment lifecycle">
                {detailQuery.isLoading ? <Skeleton className="h-24 w-full" /> :
                  detailQuery.isError ? <p role="alert" className="text-xs text-red-400">{detailQuery.error.message}</p> :
                    <Timeline events={detail?.timeline ?? []} />}
              </Section>

              <Section title="Context">
                <div className="grid grid-cols-3 gap-2">
                  {[
                    { icon: MapPin, label: 'Customer', value: detail?.context.customer || item.customer_id },
                    { icon: MapPin, label: 'Merchant', value: detail?.context.merchant || item.merchant_id },
                    { icon: MapPin, label: 'Device', value: detail?.context.device || '—' },
                  ].map((card) => (
                    <div key={card.label} className="rounded-lg border border-line bg-elevated/40 p-2.5">
                      <div className="flex items-center gap-1 text-[10px] uppercase text-muted">
                        <card.icon className="h-3 w-3" /> {card.label}
                      </div>
                      <p className="mt-1 truncate font-mono text-[11px] text-ink">{card.value || '—'}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-3 rounded-lg border border-line bg-elevated/40 p-3">
                  <div className="flex items-center gap-1 text-[10px] uppercase text-muted">
                    <Clock3 className="h-3 w-3" /> Activity windows · max transactions
                  </div>
                  <div className="mt-2 flex items-end gap-3">
                    {windows.map((window) => (
                      <div key={window.label} className="flex flex-1 flex-col items-center gap-1">
                        <div className="flex h-12 w-full items-end rounded bg-line/40">
                          <div className="w-full rounded bg-accent/70 transition-all duration-200"
                            style={{ height: `${(window.value / maxWindow) * 100}%` }} />
                        </div>
                        <span className="num text-[11px] text-ink">{number(window.value)}</span>
                        <span className="text-[10px] text-muted">{window.label}</span>
                      </div>
                    ))}
                    <div className="flex-1 text-[10px] text-muted">
                      Distinct customers on device:{' '}
                      <span className="num text-ink">{number(Number(indicator.distinct_customers ?? 0))}</span>
                    </div>
                  </div>
                </div>
              </Section>

              <Section title="Raw events">
                <div className="mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-1 text-[11px] text-muted"><Table2 className="h-3 w-3" /> Source records</span>
                  <button type="button" onClick={() => setShowJson((value) => !value)}
                    className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] text-muted transition-colors hover:bg-elevated hover:text-ink">
                    <Braces className="h-3 w-3" /> {showJson ? 'Hide JSON' : 'View JSON'}
                  </button>
                </div>
                {showJson ? (
                  <pre className="max-h-64 overflow-auto rounded-lg border border-line bg-canvas p-3 text-[10px] leading-relaxed text-muted">
                    {JSON.stringify(detail ?? {}, null, 2)}
                  </pre>
                ) : (
                  <div className="max-h-56 overflow-auto rounded-lg border border-line">
                    <table className="w-full text-left text-[11px]">
                      <thead className="sticky top-0 bg-elevated text-muted">
                        <tr><th className="px-2 py-1.5">Time</th><th className="px-2 py-1.5">Event</th><th className="px-2 py-1.5">Status</th><th className="px-2 py-1.5 text-right">Amount</th></tr>
                      </thead>
                      <tbody className="divide-y divide-line/60">
                        {(detail?.events ?? []).map((event, index) => (
                          <tr key={index}>
                            <td className="num px-2 py-1.5 text-muted">{dateTime(String(event.event_timestamp ?? ''))}</td>
                            <td className="px-2 py-1.5 text-ink">{humanize(String(event.event_type ?? ''))}</td>
                            <td className="px-2 py-1.5 text-muted">{humanize(String(event.status ?? ''))}</td>
                            <td className="num px-2 py-1.5 text-right text-ink">{money(Number(event.amount ?? 0))}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </Section>
            </>
          )}

          <Section title="Review outcome">
            <OutcomeForm key={`${item.record_id}-${presetOutcome ?? ''}`} item={item} presetOutcome={presetOutcome} />
          </Section>

          <Section title="Audit trail">
            {audit.isLoading ? <Skeleton className="h-12 w-full" /> :
              audit.data?.items.length ? (
                <ul className="space-y-2">
                  {audit.data.items.map((event) => (
                    <li key={event.id} className="flex items-start gap-2 rounded-lg border border-line bg-elevated/40 p-2.5 text-[11px]">
                      <span className="num text-muted">{dateTime(event.changed_at)}</span>
                      <span className="text-ink">{humanize(event.old_outcome)} → {humanize(event.new_outcome)}</span>
                      <span className="text-muted">by {event.reviewer || 'unknown'}</span>
                    </li>
                  ))}
                </ul>
              ) : <p className="text-xs text-muted">No outcome changes recorded yet.</p>}
          </Section>
        </div>
      </DialogContent>
    </Dialog>
  );
}
