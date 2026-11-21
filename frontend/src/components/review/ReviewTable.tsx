import { useEffect, useMemo, useRef } from 'react';
import {
  flexRender, getCoreRowModel, useReactTable, type ColumnDef,
} from '@tanstack/react-table';
import { useVirtualizer } from '@tanstack/react-virtual';
import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react';
import { Checkbox } from '@/components/ui/checkbox';
import { OutcomeBadge, PriorityBadge, ReasonChip } from '@/components/shared/Badges';
import { EmptyState } from '@/components/shared/States';
import { TableSkeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { dateTime, money, number } from '@/lib/format';
import type { ReviewItem } from '@/types/api';

interface Props {
  items: ReviewItem[];
  loading?: boolean;
  sortBy: string;
  sortDir: 'asc' | 'desc';
  onSort: (column: string) => void;
  selectedIds: Set<string>;
  onToggle: (id: string) => void;
  onToggleAll: (ids: string[], checked: boolean) => void;
  activeId: string | null;
  onActivate: (id: string) => void;
  onOpen: (id: string) => void;
}

function ScoreBar({ score }: { score: number }) {
  return (
    <div className="flex items-center gap-2" title={`Risk score ${score}`}>
      <span className="num w-7 text-right text-xs font-semibold text-ink">{score}</span>
      <div className="h-1.5 w-14 overflow-hidden rounded-full bg-elevated">
        <div
          className={cn('h-full rounded-full', score >= 45 ? 'bg-red-400' : score >= 22 ? 'bg-amber-400' : 'bg-sky-400')}
          style={{ width: `${Math.min(100, score)}%` }}
        />
      </div>
    </div>
  );
}

export function ReviewTable({
  items, loading, sortBy, sortDir, onSort, selectedIds, onToggle, onToggleAll,
  activeId, onActivate, onOpen,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  const columns = useMemo<ColumnDef<ReviewItem>[]>(() => [
    {
      id: 'select',
      size: 40,
      header: () => {
        const all = items.length > 0 && items.every((item) => selectedIds.has(item.record_id));
        const some = items.some((item) => selectedIds.has(item.record_id));
        return (
          <Checkbox
            aria-label="Select all visible records"
            checked={all ? true : some ? 'indeterminate' : false}
            onCheckedChange={(checked) => onToggleAll(items.map((item) => item.record_id), checked === true)}
          />
        );
      },
      cell: ({ row }) => (
        <Checkbox
          aria-label={`Select ${row.original.record_id}`}
          checked={selectedIds.has(row.original.record_id)}
          onCheckedChange={() => onToggle(row.original.record_id)}
          onClick={(event) => event.stopPropagation()}
        />
      ),
    },
    {
      accessorKey: 'priority',
      header: 'Priority',
      size: 104,
      cell: ({ row }) => <PriorityBadge priority={row.original.priority} />,
    },
    {
      accessorKey: 'score',
      header: 'Score',
      size: 116,
      cell: ({ row }) => <ScoreBar score={row.original.score} />,
    },
    {
      accessorKey: 'record_id',
      header: 'Record ID',
      size: 168,
      cell: ({ row }) => (
        <div className="min-w-0">
          <p className="truncate font-mono text-xs font-medium text-ink">{row.original.record_id}</p>
          <p className="text-[10px] uppercase tracking-wide text-muted">{row.original.record_type}</p>
        </div>
      ),
    },
    {
      accessorKey: 'customer_id',
      header: 'Customer',
      size: 112,
      cell: ({ row }) => <span className="font-mono text-[11px] text-muted">{row.original.customer_id || '—'}</span>,
    },
    {
      accessorKey: 'merchant_id',
      header: 'Merchant',
      size: 100,
      cell: ({ row }) => <span className="font-mono text-[11px] text-muted">{row.original.merchant_id || '—'}</span>,
    },
    {
      accessorKey: 'captured_amount',
      header: 'Amount',
      size: 104,
      cell: ({ row }) => <span className="num text-xs text-ink">{money(row.original.captured_amount)}</span>,
    },
    {
      accessorKey: 'reason_codes',
      header: 'Reasons',
      size: 260,
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex flex-wrap items-center gap-1">
          {row.original.reason_codes.slice(0, 3).map((code) => <ReasonChip key={code} code={code} />)}
          {row.original.reason_codes.length > 3 && (
            <span className="text-[10px] text-muted">+{row.original.reason_codes.length - 3}</span>
          )}
        </div>
      ),
    },
    {
      accessorKey: 'outcome',
      header: 'Outcome',
      size: 132,
      cell: ({ row }) => <OutcomeBadge outcome={row.original.outcome} />,
    },
    {
      accessorKey: 'first_event_time',
      header: 'Time',
      size: 150,
      cell: ({ row }) => <span className="text-[11px] text-muted">{dateTime(row.original.first_event_time)}</span>,
    },
  ], [items, onToggle, onToggleAll, selectedIds]);

  const table = useReactTable({
    data: items,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => row.record_id,
  });

  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 56,
    overscan: 8,
  });

  const activeIndex = items.findIndex((item) => item.record_id === activeId);
  useEffect(() => {
    if (activeIndex >= 0) virtualizer.scrollToIndex(activeIndex, { align: 'auto' });
  }, [activeIndex, virtualizer]);

  if (loading) return <TableSkeleton rows={10} />;
  if (!items.length) {
    return <EmptyState title="No flagged records" message="Adjust the filters to see more records." />;
  }

  const headerGroup = table.getHeaderGroups()[0];
  if (!headerGroup) {
    return <EmptyState title="No columns" message="Unable to render the review table." />;
  }

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      <div ref={scrollRef} className="h-[min(58vh,600px)] overflow-auto" role="grid" aria-label="Flagged records">
        <div style={{ width: table.getTotalSize(), minWidth: '100%' }}>
          <div className="sticky top-0 z-10 flex h-10 border-b border-line bg-elevated text-[11px] font-medium text-muted">
            {headerGroup.headers.map((header) => (
              <div key={header.id} style={{ width: header.getSize() }} className="flex shrink-0 items-center px-2">
                {header.column.getCanSort() && header.id !== 'select' ? (
                  <button
                    type="button"
                    className="flex items-center gap-1 rounded px-1 py-0.5 transition-colors hover:text-ink"
                    onClick={() => onSort(header.id)}
                    aria-label={`Sort by ${header.id}`}
                  >
                    {flexRender(header.column.columnDef.header, header.getContext())}
                    {sortBy === header.id ? (
                      sortDir === 'asc' ? <ArrowUp className="h-3 w-3" /> : <ArrowDown className="h-3 w-3" />
                    ) : <ChevronsUpDown className="h-3 w-3 opacity-40" />}
                  </button>
                ) : (
                  flexRender(header.column.columnDef.header, header.getContext())
                )}
              </div>
            ))}
          </div>

          <div className="relative" style={{ height: virtualizer.getTotalSize() }}>
            {virtualizer.getVirtualItems().map((virtualRow) => {
              const row = rows[virtualRow.index];
              if (!row) return null;
              const isActive = row.original.record_id === activeId;
              return (
                <div
                  key={row.id}
                  role="row"
                  tabIndex={0}
                  aria-selected={isActive}
                  onClick={() => { onActivate(row.original.record_id); onOpen(row.original.record_id); }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') onOpen(row.original.record_id);
                  }}
                  className={cn(
                    'absolute left-0 top-0 flex w-full cursor-pointer items-center border-b border-line/60 text-xs transition-colors duration-150 hover:bg-elevated/70',
                    isActive && 'bg-accent/10 ring-1 ring-inset ring-accent/40',
                    selectedIds.has(row.original.record_id) && 'bg-accent/5',
                  )}
                  style={{ height: virtualRow.size, transform: `translateY(${virtualRow.start}px)` }}
                >
                  {row.getVisibleCells().map((cell) => (
                    <div key={cell.id} style={{ width: cell.column.getSize() }} className="shrink-0 px-2">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </div>
                  ))}
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <div className="flex items-center justify-between border-t border-line px-3 py-2 text-[11px] text-muted">
        <span className="num">{number(items.length)} records in view</span>
        <span>J / K to move · Enter to open · 1–4 to set outcome</span>
      </div>
    </div>
  );
}
