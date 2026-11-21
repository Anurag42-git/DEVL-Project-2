/** Typed API client. The base URL comes from VITE_API_URL (never hard-coded). */

import type {
  AuditTrailResponse,
  DataQualityResponse,
  LedgerResponse,
  OutcomeResponse,
  OverviewResponse,
  ReportResponse,
  ReviewQueueResponse,
  TransactionDetail,
} from '@/types/api';

const RAW_URL = import.meta.env.VITE_API_URL as string | undefined;
export const API_URL = (RAW_URL ?? 'http://localhost:8000').replace(/\/$/, '');

export type QueryParams = Record<string, string | number | boolean | string[] | undefined>;

function buildPath(path: string, params?: QueryParams): string {
  if (!params) return path;
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === '' || value === false) return;
    if (Array.isArray(value)) {
      value.forEach((item) => search.append(key, item));
    } else {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: {
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...init?.headers,
      },
    });
  } catch (error) {
    throw new Error(`Cannot reach the API at ${API_URL}. Is the backend running?`, { cause: error });
  }
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) message = body.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
  return (await response.json()) as T;
}

export interface OutcomePayload {
  outcome: string;
  reviewer: string;
  notes: string;
}

export const api = {
  overview: () => request<OverviewResponse>('/api/overview'),
  ledger: (params: QueryParams) => request<LedgerResponse>(buildPath('/api/ledger', params)),
  transaction: (id: string) =>
    request<TransactionDetail>(`/api/transactions/${encodeURIComponent(id)}`),
  reviewQueue: (params: QueryParams) =>
    request<ReviewQueueResponse>(buildPath('/api/review-queue', params)),
  outcome: (id: string, payload: OutcomePayload) =>
    request<OutcomeResponse>(`/api/review/${encodeURIComponent(id)}/outcome`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  bulkOutcome: (ids: string[], payload: OutcomePayload) =>
    request<OutcomeResponse[]>('/api/review/bulk-outcome', {
      method: 'POST',
      body: JSON.stringify({ ...payload, record_ids: ids }),
    }),
  auditTrail: (id: string) =>
    request<AuditTrailResponse>(`/api/audit-trail/${encodeURIComponent(id)}`),
  dataQuality: () => request<DataQualityResponse>('/api/data-quality'),
  report: () => request<ReportResponse>('/api/report'),
  reload: () => request<{ status: string }>('/api/reload', { method: 'POST' }),
  downloadUrl: (format: 'md' | 'html' | 'csv') => `${API_URL}/api/report/download/${format}`,
};
