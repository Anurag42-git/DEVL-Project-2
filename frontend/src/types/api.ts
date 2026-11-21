/** Types mirroring the FastAPI Pydantic responses. */

export type Priority = 'high' | 'medium' | 'low';
export type Outcome = 'pending' | 'reviewed_normal' | 'needs_follow_up' | 'escalated';
export type RecordType = 'transaction' | 'customer' | 'merchant' | 'device';

export interface Kpi {
  id: string;
  label: string;
  value: number;
  display: string;
  delta_pct: number | null;
  trend: 'up' | 'down' | 'flat';
}

export interface DailyPoint {
  date: string;
  transactions: number;
  captured: number;
  refunded: number;
  refund_ratio: number;
}

export interface NameCount {
  name: string;
  value: number;
}

export interface NeedsAttention {
  record_id: string;
  record_type: string;
  score: number;
  priority: Priority;
  reason_codes: string[];
  outcome: Outcome;
}

export interface OverviewResponse {
  kpis: Kpi[];
  daily: DailyPoint[];
  reason_counts: NameCount[];
  priority_counts: NameCount[];
  refund_threshold: number;
  needs_attention: NeedsAttention[];
  metrics: {
    flag_rate: number;
    flagged_transactions: number;
    total_transactions: number;
    queue_records: number;
    validation_violations: number;
    reconciliation: Record<string, number | boolean>;
  };
  conservation: Record<string, number | boolean>;
  disclaimer: string;
  generated_at: string;
}

export interface LedgerRow {
  transaction_id: string;
  customer_id: string;
  merchant_id: string;
  device_id: string;
  currency: string;
  final_status: string;
  captured_amount: number;
  total_refunded: number;
  remaining_amount: number;
  refund_ratio: number;
  refund_count: number;
  attempt_count: number;
  retry_count: number;
  duplicate_events_removed: number;
  over_refund_amount: number;
  first_event_time: string | null;
  last_event_time: string | null;
  reconciliation_notes: string;
}

export interface LedgerResponse {
  items: LedgerRow[];
  total: number;
  page: number;
  page_size: number;
  facets: { statuses: string[] };
}

export interface Reason {
  code: string;
  explanation: string;
  field: string;
  actual: number | null;
  threshold: number | null;
  operator: string;
  weight: number;
  detail: string;
}

export interface TimelineEvent {
  kind: string;
  time: string | null;
  label: string;
  status: string;
  amount: number | null;
  invalid: boolean;
}

export interface TransactionDetail {
  ledger: LedgerRow;
  events: Array<Record<string, unknown>>;
  refunds: Array<Record<string, unknown>>;
  status_history: Array<Record<string, unknown>>;
  timeline: TimelineEvent[];
  indicators: Record<string, unknown>;
  reasons: Reason[];
  reconciliation_notes: string;
  context: Record<string, string>;
}

export interface ReviewItem {
  record_id: string;
  record_type: RecordType;
  score: number;
  priority: Priority;
  reason_codes: string[];
  reasons: Reason[];
  outcome: Outcome;
  reviewer: string;
  notes: string;
  updated_at: string | null;
  customer_id: string;
  merchant_id: string;
  captured_amount: number;
  refund_ratio_amount: number;
  first_event_time: string | null;
}

export interface ReviewQueueResponse {
  items: ReviewItem[];
  total: number;
  page: number;
  page_size: number;
  facets: {
    priorities: Priority[];
    reasons: string[];
    outcomes: Outcome[];
    record_types: RecordType[];
  };
  flagged_transactions: number;
  total_transactions: number;
  flag_rate: number;
}

export interface OutcomeResponse {
  record_id: string;
  outcome: Outcome;
  reviewer: string;
  notes: string;
  updated_at: string;
}

export interface AuditEvent {
  id: number;
  record_id: string;
  old_outcome: string;
  new_outcome: string;
  reviewer: string;
  notes: string;
  changed_at: string;
}

export interface AuditTrailResponse {
  items: AuditEvent[];
  total: number;
}

export interface RuleSummary {
  rule: string;
  severity: 'low' | 'medium' | 'high';
  count: number;
  examples: string;
}

export interface Violation {
  rule: string;
  severity: string;
  source_file: string;
  record_id: string;
  detail: string;
  example: string;
}

export interface DataQualityResponse {
  summary: RuleSummary[];
  violations: Violation[];
  state_machine: Record<string, string[]>;
  totals: { rules: number; violations: number; high_severity: number };
}

export interface ReportSection {
  title: string;
  body: string;
}

export interface DetectionQuality {
  expected_pairs: number;
  detected_pairs: number;
  matched_pairs: number;
  precision: number;
  recall: number;
  f1: number;
  restricted_precision: number;
  by_reason: Array<{
    reason_code: string;
    injected: number;
    detected: number;
    missed: number;
    recall: number;
  }>;
}

export interface ReportResponse {
  sections: ReportSection[];
  detection_quality: DetectionQuality | null;
  review_outcomes: NameCount[];
  generated_at: string;
  disclaimer: string;
}
