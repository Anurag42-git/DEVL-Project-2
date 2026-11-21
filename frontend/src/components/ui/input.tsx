import * as React from 'react';
import { cn } from '@/lib/utils';

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type = 'text', ...props }, ref) => (
    <input
      ref={ref}
      type={type}
      className={cn(
        'h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm text-ink placeholder:text-muted/70 transition-colors duration-150 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-50',
        className,
      )}
      {...props}
    />
  ),
);
Input.displayName = 'Input';

export const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => (
  <textarea
    ref={ref}
    className={cn(
      'min-h-20 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted/70 transition-colors duration-150 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent',
      className,
    )}
    {...props}
  />
));
Textarea.displayName = 'Textarea';
