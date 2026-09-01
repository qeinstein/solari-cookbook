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
  type: "stale_payment_contact" | "active_dispute_contact";
  title: string;
  summary: string;
  source_label: string;
  source_value: string;
  mirror_label: string;
  mirror_value: string;
  agent_belief: string;
  message: string;
};

export type FailureBoundary = {
  failure_type: ViolationSnapshot["type"];
  variable: string;
  label: string;
  last_passing_minutes: number;
  first_failing_minutes: number;
  failure_begins_at: string;
  resolution_minutes: number;
};

export type EnvironmentManifest = {
  environment_hash: string;
  event_hash: string;
  world_contract: string;
  world_asset_hash: string;
  invoice_id: string;
  initial_state_hash: string;
  fixture_hash: string;
  event_count: number;
  agent_policy: string;
};

export type CounterfactualProof = {
  verified: boolean;
  identical_fields: string[];
  differing_fields: string[];
  only_change: { field: string; original: string; patched: string };
  original: EnvironmentManifest;
  patched: EnvironmentManifest;
  runtime?: {
    same_event_hash?: boolean;
    same_environment_hash?: boolean;
    fresh_isolation?: boolean;
    original_sandbox_id?: string;
    patched_sandbox_id?: string;
    original_browser_session_id?: string;
    patched_browser_session_id?: string;
  };
};

export type ObservedState = {
  payment?: string;
  crm?: string;
  dispute?: string;
  crm_dispute?: string;
  messages?: string;
  message_count?: number;
  trace?: Array<Record<string, unknown>>;
};

export type BrowserSimulatorParity = {
  verified?: boolean;
  trace_state_match?: boolean;
  state_match?: boolean;
  message_count_match?: boolean;
  violation_match?: boolean;
  simulator_failure_modes?: string[];
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
  recording_keyframes?: Array<Record<string, unknown>>;
  observed?: ObservedState;
  browser_simulator_parity?: BrowserSimulatorParity;
};

export type Future = {
  future_id: string;
  seed: number;
  status: FutureStatus;
  invariant?: string;
  input_hash?: string;
  violation?: ViolationSnapshot | null;
  violations?: ViolationSnapshot[];
  failure_modes?: ViolationSnapshot["type"][];
  boundaries?: FailureBoundary[];
  counterfactual_proof?: CounterfactualProof;
  comparison?: FutureComparison;
  events: TimeEvent[];
  payment_status?: string;
  invoice_status?: string;
  messages?: Array<Record<string, unknown>>;
  observed?: ObservedState;
  browser_simulator_parity?: BrowserSimulatorParity;
  sandbox_id?: string;
  browser_session_id?: string;
  recording_status?: string;
  recording_path?: string;
  recording_events?: number;
  recording_keyframes?: Array<Record<string, unknown>>;
  search?: {
    parent_future_id?: string | null;
    mutation?: string;
    novel_features?: string[];
    shared_prefix_events?: number;
  };
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
  wall_clock_seconds?: number;
  failure_rate?: number;
  minimization_ratio?: number | null;
  environments_used?: number;
  recordings_downloaded?: number;
  failure_modes?: Record<string, number>;
  search?: {
    strategy?: string;
    candidates_evaluated?: number;
    accepted_mutations?: number;
    features_discovered?: number;
  };
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
  boundaries?: FailureBoundary[];
  counterfactual_proof?: CounterfactualProof;
  comparison?: FutureComparison;
  input_hash?: string;
  minimal_input_hash?: string;
  same_input?: boolean;
  saved?: string;
  regression?: string;
  error?: string;
};
