import type { RunData } from "../lib/types";
import { percent } from "../lib/presentation";

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "fail" | "pass" }) {
  return <div className="metric"><span className="metric-label">{label}</span><strong className={`metric-value ${tone ?? ""}`}>{value}</strong><span className="metric-note">{note}</span></div>;
}

export function RunSummary({ data }: { data: RunData | null }) {
  const summary = data?.summary;
  const coverage = summary?.coverage;
  return (
    <section className="run-summary" aria-label="Run summary">
      <div className="metrics">
        <Metric label="Futures explored" value={(summary?.explored ?? data?.futures.length ?? 0).toLocaleString()} note={`${summary?.search?.candidates_evaluated ?? 0} candidates scored`} />
        <Metric label="Novel coverage" value={`${summary?.search?.features_discovered ?? 0}`} note="event + state features" />
        <Metric label="Failure rate" value={percent(summary?.failure_rate)} note="selected search corpus" tone="fail" />
        <Metric label="Minimized to" value={percent(summary?.minimization_ratio ?? undefined)} note="of failing input events" tone="pass" />
      </div>
      <div className="search-telemetry">
        <span><b className={summary?.completion_status === "COMPLETE_WITH_ERRORS" ? "error" : ""}>{summary?.completion_status ?? "COMPLETE"}</b> experiment status</span>
        <span><b className={summary?.errors ? "error" : ""}>{summary?.errors ?? 0}</b> runtime errors</span>
        <span><b>coverage-guided mutation</b> search strategy</span>
        <span><b>{summary?.search?.accepted_mutations ?? 0}</b> useful mutations accepted</span>
        <span><b>{summary?.wall_clock_seconds ?? 0}s</b> wall clock</span>
        <span><b>{summary?.environments_used ?? 0}</b> isolated environments</span>
      </div>
      <div className="coverage-panel" id="coverage">
        <div><div className="coverage-label">Temporal coverage</div><h2>{coverage?.covered ?? 0} / {coverage?.possible ?? 0} windows</h2><p>Payment and dispute propagation positions exercised.</p></div>
        <div className="patterns">{(coverage?.patterns ?? []).map((pattern) => <span className="pattern" key={pattern.id}><b>{pattern.futures}</b>{pattern.label}</span>)}</div>
      </div>
    </section>
  );
}
