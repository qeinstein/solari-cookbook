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

export type Future = {
  future_id: string;
  seed: number;
  status: FutureStatus;
  invariant?: string;
  comparison?: FutureComparison;
  events: TimeEvent[];
};

export type Coverage = {
  covered?: number;
  possible?: number;
  patterns?: string[][];
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
  started_at?: string;
  futures: Future[];
  summary?: RunSummary;
};

export type ActionResponse = {
  events?: number;
  comparison?: FutureComparison;
  saved?: string;
  regression?: string;
  error?: string;
};
