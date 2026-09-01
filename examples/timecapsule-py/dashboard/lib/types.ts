export type FutureStatus = "PASS" | "FAIL";

export type TimeEvent = {
  at: string;
  kind: string;
  payload?: Record<string, unknown>;
};

export type FutureComparison = {
  original: FutureStatus | "NOT_RUN";
  patched: FutureStatus | "NOT_RUN";
};

export type ViolationSnapshot = {
  at?: string;
  payment_status: string;
  crm_status: string;
  agent_belief: string;
  message: string;
};

export type ObservedState = {
  payment?: string;
  crm?: string;
  messages?: string;
  trace?: Array<Record<string, unknown>>;
};

export type PatchedRun = {
  agent?: string;
  status?: FutureStatus;
  input_hash?: string;
  sandbox_id?: string;
  browser_session_id?: string;
  recording_status?: string;
  recording_path?: string;
  recording_bytes?: number;
  recording_events?: number;
  observed?: ObservedState;
};

export type Future = {
  future_id: string;
  seed: number;
  status: FutureStatus;
  invariant?: string;
  input_hash?: string;
  violation?: ViolationSnapshot | null;
  comparison?: FutureComparison;
  events: TimeEvent[];
  payment_status?: string;
  invoice_status?: string;
  messages?: Array<Record<string, unknown>>;
  observed?: ObservedState;
  sandbox_id?: string;
  browser_session_id?: string;
  recording_status?: string;
  recording_path?: string;
  patched_run?: PatchedRun;
};

export type CoveragePattern = {
  id: string;
  label: string;
  futures: number;
};

export type Coverage = {
  covered?: number;
  possible?: number;
  patterns?: CoveragePattern[];
};

export type RunSummary = {
  explored?: number;
  failures?: number;
  patched_replays?: number;
  patched_passes?: number;
  virtual_days?: number;
  coverage?: Coverage;
};

export type RunData = {
  run_id?: string;
  execution_mode?: "local" | "solari";
  started_at?: string;
  futures: Future[];
  summary?: RunSummary;
};

export type ActionResponse = {
  events?: number;
  before_events?: number;
  removed_events?: number;
  original_events?: TimeEvent[];
  minimal_events?: TimeEvent[];
  minimal_violation?: ViolationSnapshot | null;
  comparison?: FutureComparison;
  input_hash?: string;
  minimal_input_hash?: string;
  same_input?: boolean;
  saved?: string;
  regression?: string;
  error?: string;
};
