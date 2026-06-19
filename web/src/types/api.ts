export interface Aggregation {
  func: 'sum' | 'avg' | 'count' | 'min' | 'max';
  field: string;
  alias?: string;
}

export interface Filter {
  field: string;
  operator: '=' | '!=' | '>' | '<' | '>=' | '<=' | 'in';
  value: string | number | string[];
}

export interface OrderBy {
  field: string;
  direction: 'asc' | 'desc';
}

export interface Join {
  table: string;
  on_field: string;
  join_type: 'inner' | 'left' | 'right';
  alias?: string;
}

export interface TimeRange {
  start?: string;
  end?: string;
}

export interface PostProcess {
  type: 'group_top_n' | 'proportion';
  metric: string;
  group_by?: string[];
  top_n?: number;
  direction?: 'asc' | 'desc';
  output_field?: string;
}

export interface DSL {
  metrics?: Aggregation[];
  dimensions?: string[];
  filters?: Filter[];
  order_by?: OrderBy[];
  limit?: number;
  data_source: string;
  joins?: Join[];
  offset?: number;
  time_field?: string;
  time_range?: TimeRange;
  post_process?: PostProcess;
}

export interface QueryRequest {
  question: string;
  user_id: string;
  tenant_id: string;
}

export interface QueryResponse {
  status: string;
  data: Record<string, unknown>[] | null;
  dsl: DSL | null;
  sql: string | null;
  execution_time_ms: number;
}

export interface StreamEvent {
  node: string;
  status: string;
  data?: unknown;
  timestamp: number;
}

export interface ClarificationItem {
  type: string;
  question: string;
  options: string[];
}

export interface ClarificationResponse {
  ambiguities: ClarificationItem[] | null;
}

export interface AuditItem {
  id?: string;
  query_id: string;
  created_at: string;
  timestamp?: string;
  user_id: string;
  tenant_id?: string;
  question: string;
  status: 'success' | 'error' | 'clarification' | 'pending_review';
  execution_time_ms: number;
  rows_returned?: number;
  error_code?: string | null;
}

export interface AuditListResponse {
  items: AuditItem[];
  total: number;
}

export interface TraceStep {
  step: string;
  status: string;
  duration_ms?: number;
  input?: unknown;
  output?: unknown;
}

export interface AuditDetailResponse {
  id: string;
  question: string;
  dsl: DSL;
  sql: string;
  trace: TraceStep[];
  status: string;
}

export interface SchemaResponse {
  metrics: Record<string, { expr: string; description?: string }>;
  dimensions: Record<string, { column: string; description?: string }>;
  data_sources: Record<string, { table: string; metrics: string[]; dimensions: string[] }>;
}

export interface FeedbackRequest {
  query_id: string;
  is_correct: boolean;
  issue_type?: 'data_error' | 'ambiguity' | 'performance' | 'other';
  comment?: string;
}
