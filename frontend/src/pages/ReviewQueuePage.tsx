import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useSearchParams } from 'react-router-dom';
import { ChevronLeft, ChevronRight, Layers3, X } from 'lucide-react';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { ErrorState, PageHeader } from '@/components/shared/States';
import { ReviewFilters, emptyFilters, type ReviewFilterValues } from '@/components/review/ReviewFilters';
import { ReviewTable } from '@/components/review/ReviewTable';
import { ReviewDetail } from '@/components/review/ReviewDetail';
import { api } from '@/lib/api';
import { humanize, number, percent } from '@/lib/format';
import type { Outcome } from '@/types/api';

const OUTCOME_KEYS: Outcome[] = ['pending', 'reviewed_normal', 'needs_follow_up', 'escalated'];
const PAGE_SIZE = 25;

function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable;
}

export function ReviewQueuePage() {
  const [searchParams] = useSearchParams();
  const client = useQueryClient();
  const [filters, setFilters] = useState<ReviewFilterValues>({
    ...emptyFilters, search: searchParams.get('search') ?? '',
  });
  const [search, setSearch] = useState(filters.search);
  const [page, setPage] = useState(1);
  const [sortBy, setSortBy] = useState('score');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [activeId, setActiveId] = useState<string | null>(null);
  const [openedId, setOpenedId] = useState<string | null>(null);
  const [presetOutcome, setPresetOutcome] = useState<Outcome | undefined>();
  const [bulkOutcome, setBulkOutcome] = useState<Outcome>('reviewed_normal');
  const [bulkNotes, setBulkNotes] = useState('');

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setSearch(filters.search);
      setPage(1);
    }, 250);
    return () => window.clearTimeout(timer);
  }, [filters.search]);

  const queryParams = useMemo(() => ({
    search,
    priority: filters.priority || undefined,
    reason: filters.reason || undefined,
    outcome: filters.outcome || undefined,
    from_date: filters.from_date || undefined,
    to_date: filters.to_date || undefined,
    sort_by: sortBy,
    sort_dir: sortDir,
    page,
    page_size: PAGE_SIZE,
  }), [search, filters, sortBy, sortDir, page]);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['review-queue', queryParams],
    queryFn: () => api.reviewQueue(queryParams),
  });

  const items = useMemo(() => data?.items ?? [], [data]);
  const selectedItem = items.find((item) => item.record_id === openedId) ?? null;

  const updateFilters = (next: ReviewFilterValues) => {
    setFilters(next);
    setPage(1);
  };

  function toggle(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }

  function toggleAll(ids: string[], checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      ids.forEach((id) => (checked ? next.add(id) : next.delete(id)));
      return next;
    });
  }

  function sort(column: string) {
    if (column === sortBy) setSortDir((current) => (current === 'asc' ? 'desc' : 'asc'));
    else { setSortBy(column); setSortDir('desc'); }
  }

  const bulk = useMutation({
    mutationFn: () => api.bulkOutcome([...selectedIds], {
      outcome: bulkOutcome, reviewer: 'bulk-reviewer', notes: bulkNotes || 'Bulk outcome from review queue',
    }),
    onSuccess: () => {
      toast.success(`Updated ${selectedIds.size} records`);
      setSelectedIds(new Set());
      void client.invalidateQueries({ queryKey: ['review-queue'] });
      void client.invalidateQueries({ queryKey: ['overview'] });
    },
    onError: (cause: Error) => toast.error(cause.message),
  });

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (isTyping(event.target) || !items.length) return;
      const key = event.key.toLowerCase();
      if (key === 'j' || key === 'k') {
        event.preventDefault();
        const current = items.findIndex((item) => item.record_id === activeId);
        const next = key === 'j'
          ? Math.min(items.length - 1, current + 1)
          : Math.max(0, current - 1);
        setActiveId(items[next]?.record_id ?? items[0]?.record_id ?? null);
      } else if (key === 'enter' && activeId) {
        event.preventDefault();
        setOpenedId(activeId);
        setPresetOutcome(undefined);
      } else if (['1', '2', '3', '4'].includes(key)) {
        event.preventDefault();
        const outcome = OUTCOME_KEYS[Number(key) - 1];
        const target = activeId ?? items[0]?.record_id ?? null;
        if (target) { setOpenedId(target); setPresetOutcome(outcome); }
      }
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [items, activeId]);

  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <>
      <PageHeader
        title="Review Queue"
        description={`${number(data?.flagged_transactions ?? 0)} of ${number(data?.total_transactions ?? 0)} transactions flagged for review (${percent(data?.flag_rate ?? 0)}) — each flag lists the unusual patterns and evidence that triggered it.`}
      />

      <Card className="mb-4 p-3">
        <ReviewFilters value={filters} onChange={updateFilters} facets={data?.facets} />
      </Card>

      {selectedIds.size > 0 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 rounded-xl border border-accent/40 bg-accent/5 p-3">
          <Layers3 className="h-4 w-4 text-accent" aria-hidden />
          <span className="num text-xs font-medium text-ink">{selectedIds.size} selected</span>
          <Select value={bulkOutcome} onValueChange={(value) => setBulkOutcome(value as Outcome)}>
            <SelectTrigger className="w-44" aria-label="Bulk outcome"><SelectValue /></SelectTrigger>
            <SelectContent>
              {OUTCOME_KEYS.map((value) => <SelectItem key={value} value={value}>{humanize(value)}</SelectItem>)}
            </SelectContent>
          </Select>
          <Input value={bulkNotes} onChange={(event) => setBulkNotes(event.target.value)}
            placeholder="Reviewer notes (required for follow-up/escalated)" aria-label="Bulk reviewer notes"
            className="max-w-sm" />
          <Button size="sm" disabled={bulk.isPending} onClick={() => bulk.mutate()}>Apply to selected</Button>
          <button type="button" onClick={() => setSelectedIds(new Set())}
            className="ml-auto rounded-lg p-1.5 text-muted hover:bg-elevated hover:text-ink" aria-label="Clear selection">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {isError ? (
        <Card><ErrorState message={error.message} onRetry={() => void refetch()} /></Card>
      ) : (
        <>
          <ReviewTable
            items={items}
            loading={isLoading}
            sortBy={sortBy}
            sortDir={sortDir}
            onSort={sort}
            selectedIds={selectedIds}
            onToggle={toggle}
            onToggleAll={toggleAll}
            activeId={activeId ?? items[0]?.record_id ?? null}
            onActivate={setActiveId}
            onOpen={(id) => { setOpenedId(id); setPresetOutcome(undefined); }}
          />
          <div className="mt-3 flex items-center justify-between text-xs text-muted">
            <span className="num">Page {page} of {pageCount} · {number(total)} records</span>
            <div className="flex items-center gap-2">
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

      <ReviewDetail
        item={selectedItem}
        open={Boolean(openedId)}
        onClose={() => { setOpenedId(null); setPresetOutcome(undefined); }}
        presetOutcome={presetOutcome}
      />
    </>
  );
}
