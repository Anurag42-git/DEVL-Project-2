import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OutcomeForm } from '@/components/review/OutcomeForm';
import { api } from '@/lib/api';
import type { ReviewItem } from '@/types/api';

vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock('@/lib/api', () => ({ api: { outcome: vi.fn() } }));

const mockedOutcome = vi.mocked(api.outcome);

const baseItem: ReviewItem = {
  record_id: 'TXN-0042',
  record_type: 'transaction',
  score: 60,
  priority: 'high',
  reason_codes: ['OVER_REFUND'],
  reasons: [{
    code: 'OVER_REFUND', explanation: 'Refunds exceed captured amount.', field: 'over_refund_amount',
    actual: 30, threshold: 0, operator: '>', weight: 28,
    detail: 'over_refund_amount = 30 (> 0), weight 28',
  }],
  outcome: 'reviewed_normal',
  reviewer: '',
  notes: '',
  updated_at: null,
  customer_id: 'CUST-0001',
  merchant_id: 'MER-001',
  captured_amount: 100,
  refund_ratio_amount: 1.3,
  first_event_time: '2024-05-01T10:00:00',
};

function renderForm(item: ReviewItem = baseItem) {
  const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <OutcomeForm item={item} />
    </QueryClientProvider>,
  );
}

describe('OutcomeForm', () => {
  beforeEach(() => vi.clearAllMocks());

  it('requires notes for an escalated outcome', async () => {
    const user = userEvent.setup();
    renderForm({ ...baseItem, outcome: 'escalated' });
    await user.click(screen.getByRole('button', { name: /save outcome/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/notes are required/i);
    expect(mockedOutcome).not.toHaveBeenCalled();
  });

  it('submits reviewer and notes to the API', async () => {
    mockedOutcome.mockResolvedValue({
      record_id: 'TXN-0042', outcome: 'reviewed_normal', reviewer: 'alice',
      notes: 'checked refund receipt', updated_at: '2026-01-01T00:00:00+00:00',
    });
    const user = userEvent.setup();
    renderForm();

    await user.type(screen.getByLabelText('Reviewer'), 'alice');
    await user.type(screen.getByLabelText('Notes'), 'checked refund receipt');
    await user.click(screen.getByRole('button', { name: /save outcome/i }));

    await waitFor(() => expect(mockedOutcome).toHaveBeenCalledWith('TXN-0042', {
      outcome: 'reviewed_normal', reviewer: 'alice', notes: 'checked refund receipt',
    }));
  });
});
