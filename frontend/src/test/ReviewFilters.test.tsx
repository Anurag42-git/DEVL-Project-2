import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ReviewFilters, emptyFilters, type ReviewFilterValues } from '@/components/review/ReviewFilters';

const facets = {
  priorities: ['high', 'medium', 'low'] as const,
  reasons: ['OVER_REFUND', 'RETRY_STORM'],
  outcomes: ['pending', 'reviewed_normal'] as const,
  record_types: ['transaction', 'device'] as const,
};

describe('ReviewFilters', () => {
  it('reports search and date-range changes through onChange', () => {
    const onChange = vi.fn();
    const value: ReviewFilterValues = { ...emptyFilters };
    render(<ReviewFilters value={value} onChange={onChange} facets={facets as never} />);

    fireEvent.change(screen.getByLabelText('Search flagged records'), { target: { value: 'TXN-42' } });
    expect(onChange).toHaveBeenLastCalledWith({ ...emptyFilters, search: 'TXN-42' });

    fireEvent.change(screen.getByLabelText('From date'), { target: { value: '2024-04-01' } });
    expect(onChange).toHaveBeenLastCalledWith({
      ...emptyFilters, search: '', from_date: '2024-04-01',
    });
  });

  it('clears every filter and exposes the available facets', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <ReviewFilters
        value={{ ...emptyFilters, reason: 'OVER_REFUND', search: 'abc' }}
        onChange={onChange}
        facets={facets as never}
      />,
    );

    expect(screen.getByLabelText('Filter by reason code')).toBeInTheDocument();
    expect(screen.getByLabelText('Filter by priority')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /clear/i }));
    expect(onChange).toHaveBeenCalledWith(emptyFilters);
  });
});
