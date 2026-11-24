export type Model = {
  id: string;
  name: string;
  config: { output_limit: number };
};
export type Workspace = {
  name: string;
  role: string;
  catalog: string[];
  tokenizers: string[];
  connections: { id: string; provider: string; models: string[] }[];
  models: Model[];
  day_calls: number;
  day_micros: number | null;
  retention_days: number;
};
export type Evidence = { source: string; text: string; critical?: boolean };
export type Chat = {
  model: string;
  messages: { role: string; content: string }[];
  evidence: Evidence[];
  max_tokens?: number;
  temperature?: number;
  policy_id?: string;
};
export type Trace = {
  id: string;
  model_id: string;
  status: string;
  kind: string;
  input_tokens: number | null;
  output_tokens: number | null;
  elapsed_ms: number | null;
  cost: number | null;
  created: number;
  usage_source: string | null;
};
export type Block = {
  category: string;
  text: string;
  estimated_tokens: number;
  source?: string;
  repeated: boolean;
};
export type Finding = {
  category: string;
  evidence: string;
  risk: string;
  impact_tokens: number;
  confidence: string;
  strategy: string | null;
};
export type Detail = Trace & {
  request: Chat;
  sent_messages: Chat["messages"];
  output: string;
  analysis: { blocks: Block[]; findings: Finding[]; attribution: string };
  workflow?: {
    id: string;
    spans: { trace_id: string; status: string; elapsed_ms: number | null }[];
    findings: Finding[];
  };
  monitor?: unknown;
};
export type Investigation = {
  trace_id: string;
  strategies: string[];
  alternative_models: string[];
  activity: { tool: string; result: unknown }[];
};
export type Totals = {
  accuracy: number;
  input_tokens: number;
  output_tokens: number;
  inference_micros: number | null;
  p95_ms: number;
  usage_source: string;
  runs: number;
};
export type Study = {
  id: string;
  status: string;
  trace: string;
  created: number;
};
export type Report = {
  id: string;
  status: string;
  strategy: string;
  rollout_cost_scenario?: {
    projected_net_saving_micros: number;
    rollout_calls: number;
    discovery_and_study_micros: number;
  } | null;
  baseline?: Totals;
  candidate?: Totals;
  error?: string;
  conditions?: Record<string, boolean>;
  overhead: { local_processing_ms: number };
  pairs: {
    case: number;
    repeat: number;
    baseline?: { trace: string };
    candidate?: { trace: string };
    changes: { action: string; source: string }[];
  }[];
};
export type Policy = {
  id: string;
  experiment: string;
  active: boolean;
  model_id: string;
};
export type Overview = {
  requests: number;
  errors: number;
  input_tokens: number;
  output_tokens: number;
  estimated_micros: number;
  priced_requests: number;
  p95_ms: number | null;
  estimated_usage_requests: number;
  model_utilization: Record<string, number>;
};
export type Api = <T>(
  path: string,
  method?: string,
  body?: unknown,
  idempotencyKey?: string,
) => Promise<T>;
export type Act = (fn: () => Promise<void>) => void;
export const money = (v: number | null) =>
  v == null
    ? "Unknown"
    : new Intl.NumberFormat("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      }).format(v / 1e6);
export const when = (v: number) => new Date(v * 1000).toLocaleString();
export const label = (v: string) => v.replaceAll("_", " ");
