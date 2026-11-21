import { useState, type FormEvent } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { Send } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input, Textarea } from '@/components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { api } from '@/lib/api';
import { humanize } from '@/lib/format';
import type { Outcome, ReviewItem } from '@/types/api';

const OUTCOMES: Outcome[] = ['pending', 'reviewed_normal', 'needs_follow_up', 'escalated'];

interface Props {
  item: ReviewItem;
  presetOutcome?: Outcome;
  onSaved?: () => void;
}

export function OutcomeForm({ item, presetOutcome, onSaved }: Props) {
  const client = useQueryClient();
  const [outcome, setOutcome] = useState<Outcome>(presetOutcome ?? item.outcome);
  const [reviewer, setReviewer] = useState(item.reviewer);
  const [notes, setNotes] = useState(item.notes);
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.outcome(item.record_id, { outcome, reviewer, notes }),
    onSuccess: () => {
      toast.success(`Outcome saved for ${item.record_id}`);
      void client.invalidateQueries({ queryKey: ['review-queue'] });
      void client.invalidateQueries({ queryKey: ['overview'] });
      void client.invalidateQueries({ queryKey: ['audit-trail', item.record_id] });
      onSaved?.();
    },
    onError: (cause: Error) => toast.error(cause.message),
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if ((outcome === 'needs_follow_up' || outcome === 'escalated') && !notes.trim()) {
      setError('Notes are required for follow-up and escalated outcomes.');
      return;
    }
    setError(null);
    mutation.mutate();
  }

  return (
    <form onSubmit={submit} className="space-y-3" aria-label="Review outcome form">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="outcome-select" className="mb-1.5 block text-xs font-medium text-muted">Outcome</label>
          <Select value={outcome} onValueChange={(value) => setOutcome(value as Outcome)}>
            <SelectTrigger id="outcome-select"><SelectValue /></SelectTrigger>
            <SelectContent>
              {OUTCOMES.map((value) => <SelectItem key={value} value={value}>{humanize(value)}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label htmlFor="reviewer-input" className="mb-1.5 block text-xs font-medium text-muted">Reviewer</label>
          <Input id="reviewer-input" value={reviewer} onChange={(event) => setReviewer(event.target.value)}
            placeholder="Your name" />
        </div>
      </div>
      <div>
        <label htmlFor="notes-input" className="mb-1.5 block text-xs font-medium text-muted">Notes</label>
        <Textarea id="notes-input" value={notes} onChange={(event) => setNotes(event.target.value)}
          placeholder="What did you check? Add context for the next reviewer." />
      </div>
      {error && <p role="alert" className="text-xs text-red-400">{error}</p>}
      <Button type="submit" disabled={mutation.isPending} size="sm">
        <Send className="h-3.5 w-3.5" />
        {mutation.isPending ? 'Saving…' : 'Save outcome'}
      </Button>
    </form>
  );
}
