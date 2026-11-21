import type { ReactNode } from 'react';
import { AlertTriangle, Inbox, RotateCw } from 'lucide-react';
import { Button } from '@/components/ui/button';

export function EmptyState({ title, message }: { title: string; message: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-14 text-center">
      <Inbox className="h-7 w-7 text-muted" aria-hidden />
      <p className="text-sm font-medium text-ink">{title}</p>
      <p className="max-w-sm text-xs text-muted">{message}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
      <AlertTriangle className="h-7 w-7 text-amber-500" aria-hidden />
      <p className="text-sm font-medium text-ink">Unable to load this view</p>
      <p className="max-w-md text-xs text-muted">{message}</p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCw className="h-3.5 w-3.5" /> Try again
        </Button>
      )}
    </div>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>
      </div>
      {actions}
    </div>
  );
}
