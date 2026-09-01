"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, fetchRun, postFutureAction } from "../lib/api";
import type { ActionResponse, Future, RunData, TimeEvent } from "../lib/types";

const eventLabels: Record<string, string> = {
  invoice_created: "Invoice created",
  customer_payment: "Customer paid",
  payment_webhook: "Payment webhook",
  agent_wakeup: "Agent wakeup",
};

const branchEventLabels: Record<string, string> = {
  invoice_created: "Invoice",
  customer_payment: "Paid",
  payment_webhook: "Webhook",
  agent_wakeup: "Wake",
};

function eventLabel(kind: string) {
  return eventLabels[kind] ?? kind.replaceAll("_", " ");
}

function formatMoment(value: string) {
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function shortHash(value?: string) {
  return value ? value.slice(0, 12) : "not recorded";
}

function ActionButton({
  children,
  variant = "primary",
  disabled,
  onClick,
}: {
  children: React.ReactNode;
  variant?: "primary" | "secondary";
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button className={`action-button ${variant}`} type="button" disabled={disabled} onClick={onClick}>
      {children}
    </button>
  );
}

function FutureRow({
  future,
  selected,
  index,
  onSelect,
}: {
  future: Future;
  selected: boolean;
  index: number;
  onSelect: (future: Future) => void;
}) {
  return (
    <button
      className={`future-row ${future.status.toLowerCase()} ${selected ? "selected" : ""}`}
      type="button"
      aria-pressed={selected}
      style={{ animationDelay: `${Math.min(index, 10) * 35}ms` }}
      onClick={() => onSelect(future)}
    >
      <span className="branch-line" aria-hidden="true" />
      <span className="future-id">
        <strong>{future.future_id}</strong>
        <small>seed {future.seed}</small>
      </span>
      <span className="events" aria-label={`Events in ${future.future_id}`}>
        {future.events.map((event, eventIndex) => (
          <span className="event-group" key={`${event.at}-${event.kind}-${eventIndex}`}>
            {eventIndex > 0 ? <span className="arrow" aria-hidden="true">→</span> : null}
            <span className="event">
              <span className="event-dot" aria-hidden="true" />
              {branchEventLabels[event.kind] ?? eventLabel(event.kind)}
            </span>
          </span>
        ))}
      </span>
      <span className={`result ${future.status}`}>{future.status}</span>
    </button>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<RunData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<{
    futureId: string;
    action: "compare" | "minimize" | "regress";
    payload: ActionResponse;
  } | null>(null);
  const [actionError, setActionError] = useState("");
  const [workingAction, setWorkingAction] = useState<string | null>(null);

  const loadRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextData = await fetchRun();
      setData(nextData);
      setSelectedId((current) => {
        if (current && nextData.futures.some((future) => future.future_id === current)) return current;
        return nextData.futures.find((future) => future.status === "FAIL")?.future_id
          ?? nextData.futures[0]?.future_id
          ?? null;
      });
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The saved trace could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // The effect is the initial synchronization point with the external API.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRun();
  }, [loadRun]);

  const futures = useMemo(() => data?.futures ?? [], [data]);
  const failures = useMemo(() => futures.filter((future) => future.status === "FAIL"), [futures]);
  const selected = futures.find((future) => future.future_id === selectedId) ?? futures[0];
  const selectedAction = actionResult?.futureId === selected?.future_id ? actionResult : null;
  const displayEvents = selectedAction?.action === "minimize" && selectedAction.payload.minimal_events
    ? selectedAction.payload.minimal_events
    : selected?.events ?? [];
  const coverage = data?.summary?.coverage;
  const patchedPasses = failures.filter((future) => future.comparison?.patched === "PASS").length;
  const patchedKnown = failures.length > 0 && failures.every((future) => future.comparison?.patched);
  const violation = selectedAction?.action === "minimize"
    ? selectedAction.payload.minimal_violation
    : selected?.violation;
  const isSolari = data?.execution_mode === "solari";
  const cloudSameInput = Boolean(
    selected?.input_hash
      && selected.patched_run?.input_hash
      && selected.input_hash === selected.patched_run.input_hash,
  );

  function selectFuture(future: Future) {
    setSelectedId(future.future_id);
    setActionResult(null);
    setActionError("");
  }

  async function runAction(action: "compare" | "minimize" | "regress") {
    if (!selected) return;
    setWorkingAction(action);
    setActionError("");
    try {
      const payload = await postFutureAction(selected.future_id, action);
      setActionResult({ futureId: selected.future_id, action, payload });
    } catch (caught) {
      setActionError(caught instanceof ApiError ? caught.message : "Action unavailable.");
    } finally {
      setWorkingAction(null);
    }
  }

  return (
    <main className="shell">
      <aside className="side" aria-label="Workspace navigation">
        <div className="brand">
          <div className="mark">TC</div>
          <div className="brand-name">TimeCapsule</div>
        </div>
        <div className="overline">Workspace</div>
        <nav className="nav">
          <a className="active" href="#future-tree"><span className="nav-icon">◌</span>Future tree</a>
          <a href="#evidence"><span className="nav-icon">⌁</span>Evidence</a>
          <a href="#coverage"><span className="nav-icon">◇</span>Coverage</a>
        </nav>
        <div className="side-bottom">
          <div className="overline">Execution</div>
          <p>{isSolari ? "Solari cloud isolation" : "Deterministic local proof"}</p>
          <p>{isSolari ? "Sandbox + browser / future" : "Event-driven clock"}</p>
        </div>
      </aside>

      <div className="content">
        <div className="topbar">
          <div className="crumbs"><span>Projects</span><span aria-hidden="true">›</span><b>Collections agent</b></div>
          <div className="top-actions">
            <span className={`mode-badge ${isSolari ? "cloud" : ""}`}>
              <span aria-hidden="true" />{isSolari ? "Solari run" : "Local proof"}
            </span>
            <a className="docs-link" href="https://github.com/qeinstein/solari-cookbook/tree/main/examples/timecapsule-py" target="_blank" rel="noreferrer">Documentation</a>
            <div className="avatar" aria-label="Workspace owner">Q</div>
          </div>
        </div>

        <section className="intro">
          <div>
            <div className="kicker">Temporal reliability workspace</div>
            <h1>Find the future before it happens.</h1>
            <p>Branch a real agent workflow across time, isolate the unsafe future, and replay that exact input against the fix.</p>
          </div>
          <div className="run-info">Latest exploration<strong>{loading ? "Loading saved run…" : data?.run_id ?? "No saved run"}</strong></div>
        </section>

        <div className="workspace" id="future-tree">
          <section aria-labelledby="future-tree-title">
            <div className="section-head">
              <div><h2 id="future-tree-title">Future tree</h2><p>Deterministic branches from one shared invoice state.</p></div>
              <div className="section-meta">{loading ? "Loading trace" : error ? "Trace unavailable" : `${failures.length} unsafe / ${futures.length} explored`}</div>
            </div>
            {error ? (
              <div className="empty error-state" role="alert">
                <strong>Trace unavailable</strong>
                <span>{error}</span>
                <button type="button" onClick={() => void loadRun()}>Try again</button>
              </div>
            ) : loading ? (
              <div className="tree" aria-label="Loading futures"><div className="skeleton-row" /><div className="skeleton-row" /><div className="skeleton-row" /></div>
            ) : futures.length === 0 ? (
              <div className="empty"><strong>No saved run yet.</strong><span>Run <code>python3 main.py run --futures 25</code> first.</span></div>
            ) : (
              <>
                <div className="branch-root"><span className="root-node" aria-hidden="true" />Shared world <b>INV-1842</b></div>
                <div className="tree">
                  {futures.map((future, index) => (
                    <FutureRow
                      key={future.future_id}
                      future={future}
                      index={index}
                      selected={selected?.future_id === future.future_id}
                      onSelect={selectFuture}
                    />
                  ))}
                </div>
              </>
            )}
          </section>

          <aside className={`inspector ${selected?.status === "PASS" ? "pass-inspector" : ""}`} aria-labelledby="inspector-title">
            <div className="inspector-kicker"><span>{selected?.status === "FAIL" ? "Invariant violated" : "Invariant held"}</span><span>{selected?.future_id ?? "—"}</span></div>
            <h3 id="inspector-title">{selected?.status === "FAIL" ? "Contact inside the stale window" : "No unsafe contact observed"}</h3>
            <p className="inspector-sub">
              {selected?.status === "FAIL"
                ? "Payment was already settled while the CRM and agent still believed the invoice was overdue."
                : "Every agent wakeup stayed outside the paid-but-stale interval for this branch."}
            </p>

            <div className="state-grid">
              <State label="Payment system" value={violation?.payment_status ?? selected?.payment_status?.toUpperCase() ?? selected?.observed?.payment?.toUpperCase() ?? "—"} />
              <State label="CRM state" value={violation?.crm_status ?? selected?.invoice_status?.toUpperCase() ?? selected?.observed?.crm?.toUpperCase() ?? "—"} bad={Boolean(violation)} />
              <State label={violation ? "Agent belief" : "Unsafe contact"} value={violation?.agent_belief ?? "NONE"} bad={Boolean(violation)} />
            </div>

            <div className="inspector-actions">
              <ActionButton disabled={!selected || workingAction !== null} onClick={() => void runAction("compare")}>Replay exact input</ActionButton>
              <ActionButton variant="secondary" disabled={!selected || selected.status !== "FAIL" || workingAction !== null} onClick={() => void runAction("minimize")}>Minimize</ActionButton>
              <ActionButton variant="secondary" disabled={!selected || selected.status !== "FAIL" || workingAction !== null} onClick={() => void runAction("regress")}>Save regression</ActionButton>
              <span className="action-output" role="status" aria-live="polite">
                {workingAction ? "Running evidence step…" : actionError || actionSummary(selectedAction)}
              </span>
            </div>

            <div className="timeline-heading">
              <span>{selectedAction?.action === "minimize" ? "Minimized counterexample" : "Candidate future"}</span>
              <b>{displayEvents.length} events</b>
            </div>
            <Timeline events={displayEvents} violationAt={violation?.at} />

            {selected?.status === "FAIL" ? (
              <div className="proof-flow" id="evidence" aria-label="Failure repair proof">
                <ProofStep label="Original" value="FAIL" tone="fail" />
                <span aria-hidden="true">→</span>
                <ProofStep
                  label="Minimize"
                  value={selectedAction?.action === "minimize"
                    ? `${selectedAction.payload.before_events}→${selectedAction.payload.events}`
                    : "ready"}
                />
                <span aria-hidden="true">→</span>
                <ProofStep label="Patched" value={selected.comparison?.patched ?? "—"} tone="pass" />
              </div>
            ) : null}

            <Evidence selected={selected} selectedAction={selectedAction} cloudSameInput={cloudSameInput} />
          </aside>
        </div>

        <section className="run-summary" aria-label="Run summary">
          <div className="metrics">
            <Metric label="Futures explored" value={loading ? "—" : futures.length.toLocaleString()} note="deterministic timelines" />
            <Metric label="Event-time" value={loading ? "—" : `${(data?.summary?.virtual_days ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 })}d`} note="summed branch spans" />
            <Metric label="Failures" value={loading ? "—" : failures.length.toLocaleString()} note="observed violations" tone="fail" />
            <Metric label="Patched replay" value={loading ? "—" : patchedKnown ? `${patchedPasses}/${failures.length}` : "—"} note="same generated input" tone="pass" />
          </div>

          <div className="coverage-panel" id="coverage">
            <div>
              <div className="coverage-label">Temporal coverage</div>
              <h2>{coverage?.covered ?? 0} / {coverage?.possible ?? 0} windows</h2>
              <p>Meaningful wakeup positions exercised by this run.</p>
            </div>
            <div className="patterns">
              {(coverage?.patterns ?? []).map((pattern) => (
                <span className="pattern" key={pattern.id}><b>{pattern.futures}</b>{pattern.label}</span>
              ))}
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function Timeline({ events, violationAt }: { events: TimeEvent[]; violationAt?: string }) {
  const visibleEvents = events.filter((event) => event.kind !== "invoice_created");
  return (
    <div className="mini-timeline">
      {visibleEvents.map((event, index) => {
        const violating = event.kind === "agent_wakeup" && event.at === violationAt;
        return (
          <div className={`step ${violating ? "violating" : ""}`} key={`${event.at}-${event.kind}-${index}`}>
            <span className="step-dot" aria-hidden="true" />
            <div>{eventLabel(event.kind)}{violating ? <em>violation</em> : null}<small>{formatMoment(event.at)}</small></div>
            {index < visibleEvents.length - 1 ? <span className="step-line" aria-hidden="true" /> : null}
          </div>
        );
      })}
      {visibleEvents.length === 0 ? <div className="timeline-empty">No event sequence selected.</div> : null}
    </div>
  );
}

function Evidence({
  selected,
  selectedAction,
  cloudSameInput,
}: {
  selected?: Future;
  selectedAction: { action: string; payload: ActionResponse } | null;
  cloudSameInput: boolean;
}) {
  const actionHash = selectedAction?.payload.input_hash;
  const sameInput = selectedAction?.payload.same_input || cloudSameInput;
  const recording = selected?.recording_status ?? selected?.patched_run?.recording_status;
  return (
    <div className="evidence-card">
      <div><span>Input fingerprint</span><code>{shortHash(actionHash ?? selected?.input_hash)}</code></div>
      <div><span>Counterfactual</span><strong className={sameInput ? "verified" : ""}>{sameInput ? "Same input verified" : selected?.comparison ? "Same generated seed" : "Not replayed"}</strong></div>
      {selected?.sandbox_id ? <div><span>Solari isolation</span><code>{selected.sandbox_id.slice(0, 12)}</code></div> : null}
      {recording ? <div><span>Session evidence</span><strong>{recording.replaceAll("_", " ")}</strong></div> : null}
    </div>
  );
}

function ProofStep({ label, value, tone }: { label: string; value: string; tone?: "fail" | "pass" }) {
  return <div><span>{label}</span><strong className={tone ?? ""}>{value}</strong></div>;
}

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "fail" | "pass" }) {
  return <div className="metric"><span className="metric-label">{label}</span><strong className={`metric-value ${tone ?? ""}`}>{value}</strong><span className="metric-note">{note}</span></div>;
}

function State({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return <div className="state"><span className="state-label">{label}</span><strong className={bad ? "bad" : ""}>{value}</strong></div>;
}

function actionSummary(result: { action: string; payload: ActionResponse } | null) {
  if (!result) return "";
  if (result.action === "regress") return `Regression saved · ${result.payload.events ?? "—"} events`;
  if (result.action === "minimize") return `${result.payload.removed_events ?? 0} events removed · patched ${result.payload.comparison?.patched ?? "—"}`;
  return `Original ${result.payload.comparison?.original ?? "—"} · patched ${result.payload.comparison?.patched ?? "—"}`;
}
