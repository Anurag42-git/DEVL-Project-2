import { Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { humanize } from '@/lib/format';
import type { Outcome, Priority, ReviewQueueResponse } from '@/types/api';

export interface ReviewFilterValues {
  search: string;
  priority: string;
  reason: string;
  outcome: string;
  from_date: string;
  to_date: string;
}

export const emptyFilters: ReviewFilterValues = {
  search: '', priority: '', reason: '', outcome: '', from_date: '', to_date: '',
};

interface Props {
  value: ReviewFilterValues;
  onChange: (next: ReviewFilterValues) => void;
  facets?: ReviewQueueResponse['facets'];
}

export function ReviewFilters({ value, onChange, facets }: Props) {
  const set = (key: keyof ReviewFilterValues, next: string) => onChange({ ...value, [key]: next });
  const active = Object.values(value).some(Boolean);

  return (
    <div className="flex flex-wrap items-center gap-2" role="group" aria-label="Review queue filters">
      <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
        <Input
          aria-label="Search flagged records"
          placeholder="Search ID, reason or entity…"
          value={value.search}
          onChange={(event) => set('search', event.target.value)}
          className="pl-9"
        />
      </div>

      <Select value={value.priority || 'all'} onValueChange={(next) => set('priority', next === 'all' ? '' : next)}>
        <SelectTrigger className="w-32" aria-label="Filter by priority"><SelectValue placeholder="Priority" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All priorities</SelectItem>
          {facets?.priorities.map((item) => <SelectItem key={item} value={item}>{humanize(item)}</SelectItem>)}
        </SelectContent>
      </Select>

      <Select value={value.reason || 'all'} onValueChange={(next) => set('reason', next === 'all' ? '' : next)}>
        <SelectTrigger className="w-44" aria-label="Filter by reason code"><SelectValue placeholder="Reason" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All reasons</SelectItem>
          {facets?.reasons.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}
        </SelectContent>
      </Select>

      <Select value={value.outcome || 'all'} onValueChange={(next) => set('outcome', next === 'all' ? '' : next)}>
        <SelectTrigger className="w-40" aria-label="Filter by outcome"><SelectValue placeholder="Outcome" /></SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All outcomes</SelectItem>
          {facets?.outcomes.map((item: Outcome) => <SelectItem key={item} value={item}>{humanize(item)}</SelectItem>)}
        </SelectContent>
      </Select>

      <Input type="date" aria-label="From date" value={value.from_date}
        onChange={(event) => set('from_date', event.target.value)} className="w-36" />
      <Input type="date" aria-label="To date" value={value.to_date}
        onChange={(event) => set('to_date', event.target.value)} className="w-36" />

      {active && (
        <button type="button" onClick={() => onChange(emptyFilters)}
          className="inline-flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-muted transition-colors hover:bg-elevated hover:text-ink">
          <X className="h-3.5 w-3.5" /> Clear
        </button>
      )}
    </div>
  );
}

export const priorityOptions: Priority[] = ['high', 'medium', 'low'];
