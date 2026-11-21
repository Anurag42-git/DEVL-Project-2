import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight, Columns3, Download } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog';
import { ErrorState, PageHeader } from '@/components/shared/States';
import { TableSkeleton } from '@/components/ui/skeleton';
import { api } from '@/lib/api';
import { dateTime, money, number, percent } from '@/lib/format';
import { cn } from '@/lib/utils';
import type { LedgerRow } from '@/types/api';

const COLUMNS: Array<{ key: keyof LedgerRow; label: string; width: number }> = [
  { key: 'transaction_id', label: 'Transaction', width: 140 },
  { key: 'customer_id', label: 'Customer', width: 116 },
  { key: 'merchant_id', label: 'Merchant', width: 100 },
  { key: 'final_status', label: 'Status', width: 112 },
  { key: 'captured_amount', label: 'Captured', width: 116 },
  { key: 'total_refunded', label: 'Refunded', width: 108 },
  { key: 'refund_ratio', label: 'Refund ratio', width: 104 },
  { key: 'attempt_count', label: 'Attempts', width: 88 },
  { key: 'retry_count', label: 'Retries', width: 80 },
  { key: 'first_event_time', label: 'First event', width: 160 },
];

const PAGE_SIZE = 50;

function cell(row: LedgerRow, key: keyof LedgerRow): string {
  const value = row[key];
  if (value === null || value === undefined) return '—';
  if (key === 'captured_amount' || key === 'total_refunded') return money(Number(value));
  if (key === 'refund_ratio') return percent(Number(value), 1);
  if (key === 'first_event_time') return dateTime(String(value));
  return String(value);
}

function exportCsv(rows: LedgerRow[], visible: Set<string>) {
  const keys = COLUMNS.filter((column) => visible.has(column.key));
  const header = keys.map((column) => column.label).join(',');
  const body = rows.map((row) =>
    keys.map((column) => `"${cell(row, column.key).replace(/"/g, '""')}"`).join(',')
  ).join('\n');
  const url = URL.createObjectURL(new Blob([`${header}\n${body}`], { type: 'text/csv' }));
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = 'reconciled-ledger.csv';
  anchor.click();
  URL.revokeObjectURL(url);
}

export function LedgerPage() {
  const [search, setSearch] = useState('');
  const [debounced, setDebounced] = useState('');
  const [status, setStatus] = useState('');
  const [sortBy, setSortBy] = useState('first_event_time');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState(1);
  const [visible, setVisible] = useState<Set<string>>(new Set(COLUMNS.map((column) => column.key)));
  const [opened, setOpened] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => { setDebounced(search); setPage(1); }, 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  const params = useMemo(() => ({ search: debounced, status: status || undefined,
    sort_by: sortBy, sort_dir: sortDir, page, page_size: PAGE_SIZE }),
  [debounced, status, sortBy, sortDir, page]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['ledger', params], queryFn: () => api.ledger(params),
  });
  const detail = useQuery({
    queryKey: ['transaction', opened],
    queryFn: () => api.transaction(opened ?? ''),
    enabled: Boolean(opened),
  });

  const rows = data?.items ?? [];
  const columns = COLUMNS.filter((column) => visible.has(column.key));
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 44,
    overscan: 12,
  });

  function sort(column: string) {
    if (column === sortBy) setSortDir((current) => (current === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(column); setSortDir('desc'); }
  }

  const pageCount = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Reconciled Ledger"
        description="One row per transaction. Duplicate events are collapsed, retries counted as attempts, and partial refunds aggregated."
        actions={
          <Button variant="outline" size="sm" disabled={!rows.length} onClick={() => exportCsv(rows, visible)}>
            <Download className="h-4 w-4" /> Export CSV
          </Button>
        }
      />

      <Card className="mb-4 flex flex-wrap items-center gap-2 p-3">
        <Input aria-label="Search ledger" placeholder="Search transaction, customer, merchant, device…"
          value={search} onChange={(event) => setSearch(event.target.value)} className="max-w-sm flex-1" />
        <Select value={status || 'all'} onValueChange={(value) => { setStatus(value === 'all' ? '' : value); setPage(1); }}>
          <SelectTrigger className="w-40" aria-label="Filter by status"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All statuses</SelectItem>
            {data?.facets.statuses.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
          </SelectContent>
        </Select>
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <Button variant="outline" size="sm"><Columns3 className="h-4 w-4" /> Columns</Button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={6} className="z-50 min-w-48 rounded-xl border border-line bg-elevated p-1 shadow-card">
              {COLUMNS.map((column) => (
                <DropdownMenu.CheckboxItem key={column.key} checked={visible.has(column.key)}
                  onSelect={(event) => event.preventDefault()}
                  onCheckedChange={(checked) => setVisible((current) => {
                    const next = new Set(current);
                    if (checked) next.add(column.key); else next.delete(column.key);
                    return next;
                  })}
                  className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-xs text-ink outline-none data-[highlighted]:bg-surface">
                  <Checkbox checked={visible.has(column.key)} tabIndex={-1} aria-hidden />
                  {column.label}
                </DropdownMenu.CheckboxItem>
              ))}
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </Card>

      {isError ? <Card><ErrorState message={error.message} onRetry={() => void refetch()} /></Card> : (
        <>
          <Card className="overflow-hidden">
            {isLoading ? <TableSkeleton rows={12} /> : rows.length === 0 ? (
              <p className="px-6 py-14 text-center text-sm text-muted">No transactions match these filters.</p>
            ) : (
              <div ref={scrollRef} className="h-[min(66vh,700px)] overflow-auto" role="grid" aria-label="Reconciled ledger">
                <div style={{ minWidth: columns.reduce((sum, column) => sum + column.width, 0) }}>
                  <div className="sticky top-0 z-10 flex h-10 border-b border-line bg-elevated text-[11px] font-medium text-muted">
                    {columns.map((column) => (
                      <div key={column.key} style={{ width: column.width }} className="flex shrink-0 items-center px-3">
                        <button type="button" className="flex items-center gap-1 hover:text-ink"
                          onClick={() => sort(column.key)} aria-label={`Sort by ${column.label}`}>
                          {column.label}
                          {sortBy === column.key ? (
                            sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
                          ) : null}
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
                    {virtualizer.getVirtualItems().map((virtualRow) => {
                      const row = rows[virtualRow.index];
                      if (!row) return null;
                      return (
                        <div key={row.transaction_id} role="row" tabIndex={0}
                          onClick={() => setOpened(row.transaction_id)}
                          onKeyDown={(event) => { if (event.key === 'Enter') setOpened(row.transaction_id); }}
                          className={cn('absolute left-0 top-0 flex w-full cursor-pointer items-center border-b border-line/60 text-xs transition-colors hover:bg-elevated/70',
                            opened === row.transaction_id && 'bg-accent/10')}
                          style={{ height: virtualRow.size, transform: `translateY(${virtualRow.start}px)` }}>
                          {columns.map((column) => (
                            <div key={column.key} style={{ width: column.width }}
                              className={cn('shrink-0 truncate px-3',
                                typeof row[column.key] === 'number' && 'num',
                                column.key === 'transaction_id' && 'font-mono text-ink')}>
                              {cell(row, column.key)}
                            </div>
                          ))}
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>
            )}
          </Card>

          <div className="mt-3 flex items-center justify-between text-xs text-muted">
            <span className="num">Page {page} of {pageCount} · {number(data?.total ?? 0)} transactions</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>
                <ChevronLeft className="h-4 w-4" /> Previous
              </Button>
              <Button variant="outline" size="sm" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>
                Next <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </>
      )}

      <Dialog open={Boolean(opened)} onOpenChange={(next) => !next && setOpened(null)}>
        <DialogContent side className="max-w-3xl">
          <div className="shrink-0 border-b border-line px-6 py-5 pr-14">
            <DialogTitle className="font-mono text-base text-ink">{opened}</DialogTitle>
            <DialogDescription className="mt-1 text-xs text-muted">Reconciled row and raw lifecycle evidence</DialogDescription>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-4">
            {detail.isLoading ? <TableSkeleton rows={6} /> : detail.isError ? (
              <p role="alert" className="text-sm text-red-400">{detail.error.message}</p>
            ) : detail.data ? (
              <>
                <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                  {[
                    ['Captured', money(detail.data.ledger.captured_amount)],
                    ['Refunded', money(detail.data.ledger.total_refunded)],
                    ['Remaining', money(detail.data.ledger.remaining_amount)],
                    ['Attempts', number(detail.data.ledger.attempt_count)],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-lg border border-line bg-elevated/40 p-2.5">
                      <p className="text-[10px] uppercase text-muted">{label}</p>
                      <p className="num mt-1 text-sm font-medium text-ink">{value}</p>
                    </div>
                  ))}
                </div>
                <div className="mt-4 rounded-lg border border-accent/30 bg-accent/5 p-3 text-xs text-ink">
                  <p className="mb-1 font-medium">Reconciliation notes</p>
                  <p className="text-muted">{detail.data.reconciliation_notes}</p>
                </div>
                <h3 className="mb-2 mt-5 text-xs font-semibold uppercase tracking-wide text-muted">Raw events</h3>
                <div className="overflow-x-auto rounded-lg border border-line">
                  <table className="w-full text-left text-[11px]">
                    <thead className="bg-elevated text-muted">
                      <tr><th className="px-2 py-1.5">Time</th><th className="px-2 py-1.5">Event</th><th className="px-2 py-1.5">Status</th><th className="px-2 py-1.5 text-right">Amount</th></tr>
                    </thead>
                    <tbody className="divide-y divide-line/60">
                      {detail.data.events.map((event, index) => (
                        <tr key={index}>
                          <td className="num px-2 py-1.5 text-muted">{dateTime(String(event.event_timestamp ?? ''))}</td>
                          <td className="px-2 py-1.5 text-ink">{String(event.event_type ?? '')}</td>
                          <td className="px-2 py-1.5 text-muted">{String(event.status ?? '')}</td>
                          <td className="num px-2 py-1.5 text-right text-ink">{money(Number(event.amount ?? 0))}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : null}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
