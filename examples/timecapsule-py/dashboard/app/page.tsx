"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, fetchRun, postFutureAction } from "../lib/api";
import type { ActionResponse, Future, RunData } from "../lib/types";

const eventLabels: Record<string, string> = {
  invoice_created: "Invoice created",
  customer_payment: "Customer paid",
  payment_webhook: "Payment webhook",
  agent_wakeup: "Agent wakeup",
};

const patternLabels: Record<string, string> = {
  customer_payment: "payment",
  agent_wakeup: "wakeup",
  payment_webhook: "webhook",
};

function eventLabel(kind: string) {
  return eventLabels[kind] ?? kind.replaceAll("_", " ");
}

function formatDate(value: string) {
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
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
  const events = future.events;

  return (
    <button
      className={`future-row ${future.status.toLowerCase()} ${selected ? "selected" : ""}`}
      type="button"
      aria-pressed={selected}
      style={{ animationDelay: `${Math.min(index, 10) * 40}ms` }}
      onClick={() => onSelect(future)}
    >
      <span className="future-id">
        <strong>{future.future_id}</strong>
        <small>seed {future.seed}</small>
      </span>
      <span className="events" aria-label={`Events in ${future.future_id}`}>
        {events.map((event, index) => (
          <span className="event-group" key={`${event.at}-${event.kind}`}>
            {index > 0 ? <span className="arrow" aria-hidden="true">→</span> : null}
            <span className="event">
              <span className="event-dot" aria-hidden="true" />
              {eventLabel(event.kind)}
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
  const [actionMessage, setActionMessage] = useState("");
  const [workingAction, setWorkingAction] = useState<string | null>(null);

  const loadRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextData = await fetchRun();
      setData(nextData);
      setSelectedId((current) => {
        if (current && nextData.futures.some((future) => future.future_id === current)) return current;
        return nextData.futures.find((future) => future.status === "FAIL")?.future_id ?? nextData.futures[0]?.future_id ?? null;
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
  const selected = futures.find((future) => future.future_id === selectedId) ?? failures[0];
  const coverage = data?.summary?.coverage;
  const patchedPasses = failures.filter((future) => future.comparison?.patched === "PASS").length;
  const patchedKnown = failures.length > 0 && failures.every((future) => future.comparison?.patched);

  async function runAction(action: "compare" | "minimize" | "regress") {
    if (!selected) return;
    setWorkingAction(action);
    setActionMessage("Working…");
    try {
      const result = await postFutureAction(selected.future_id, action);
      setActionMessage(actionMessageFor(action, result));
    } catch (caught) {
      setActionMessage(caught instanceof ApiError ? caught.message : "Action unavailable.");
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
          <a href="#regressions"><span className="nav-icon">⌁</span>Regressions</a>
          <a href="#coverage"><span className="nav-icon">◇</span>Coverage</a>
        </nav>
        <div className="side-bottom">
          <div className="overline">Environment</div>
          <p>Collections / local</p>
          <p>Event-driven clock</p>
        </div>
      </aside>

      <div className="content">
        <div className="topbar">
          <div className="crumbs"><span>Projects</span><span aria-hidden="true">›</span><b>Collections agent</b></div>
          <div className="top-actions">
            <a className="docs-link" href="https://github.com/qeinstein/solari-cookbook/tree/main/examples/timecapsule-py" target="_blank" rel="noreferrer">Documentation</a>
            <div className="avatar" aria-label="Workspace owner">Q</div>
          </div>
        </div>

        <section className="intro">
          <div>
            <div className="kicker">Temporal reliability workspace</div>
            <h1>Find the future<br />before it happens.</h1>
            <p>Explore the event sequences that make an autonomous collections agent unsafe, then replay the same future against a fix.</p>
          </div>
          <div className="run-info">Latest exploration<strong>{loading ? "Loading saved run…" : data?.run_id ?? "No saved run"}</strong></div>
        </section>

        <section className="metrics" aria-label="Run metrics">
          <Metric label="Futures explored" value={loading ? "—" : futures.length.toLocaleString()} note="isolated timelines" />
          <Metric label="Event-time advanced" value={loading ? "—" : (data?.summary?.virtual_days ?? 0).toLocaleString(undefined, { maximumFractionDigits: 1 })} note="measured across futures" />
          <Metric label="Failures found" value={loading ? "—" : failures.length.toLocaleString()} note="invariant violations" tone="fail" />
          <Metric label="Patched replay" value={loading ? "—" : patchedKnown ? `${patchedPasses}/${failures.length}` : "—"} note="same future, new agent" tone="pass" />
        </section>

        <section className="coverage-panel" id="coverage" aria-labelledby="coverage-title">
          <div>
            <div className="coverage-label">Temporal coverage</div>
            <h2 id="coverage-title">{coverage?.covered ?? 0} / {coverage?.possible ?? 0} orderings</h2>
            <p>Distinct event orders observed in this exploration.</p>
          </div>
          <div className="patterns">
            {(coverage?.patterns ?? []).map((pattern) => (
              <span className="pattern" key={pattern.join("-")}>{pattern.map((kind) => patternLabels[kind] ?? kind).join(" → ")}</span>
            ))}
          </div>
        </section>

        <div className="workspace" id="future-tree">
          <section aria-labelledby="future-tree-title">
            <div className="section-head">
              <div><h2 id="future-tree-title">Future tree</h2><p>Each row is a branch from the same starting world.</p></div>
              <div className="section-meta">{loading ? "Loading trace" : error ? "Trace unavailable" : `${failures.length} failure${failures.length === 1 ? "" : "s"} found`}</div>
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
              <div className="tree">
                {futures.map((future, index) => <FutureRow key={future.future_id} future={future} index={index} selected={selected?.future_id === future.future_id} onSelect={(next) => setSelectedId(next.status === "FAIL" ? next.future_id : selectedId)} />)}
              </div>
            )}
          </section>

          <aside className={`inspector ${selected?.status === "PASS" ? "pass-inspector" : ""}`} aria-labelledby="inspector-title">
            <div className="inspector-kicker"><span>{selected?.status === "FAIL" ? "Selected failure" : "Selected future"}</span><span>{selected?.future_id ?? "—"}</span></div>
            <h3 id="inspector-title">{selected?.status === "FAIL" ? "Stale payment contact" : "Waiting for a failure"}</h3>
            <p className="inspector-sub">{selected?.status === "FAIL" ? "The agent contacted a customer after payment, before the CRM received its webhook." : "Run an exploration to inspect the causal sequence."}</p>
            <div className="state-grid">
              <State label="Payment system" value={selected?.status === "FAIL" ? "PAID" : "—"} />
              <State label="CRM state" value={selected?.status === "FAIL" ? "OVERDUE" : "—"} bad={selected?.status === "FAIL"} />
              <State label="Agent belief" value={selected?.status === "FAIL" ? "OVERDUE" : "—"} bad={selected?.status === "FAIL"} />
            </div>
            <div className="timeline-title">Minimal failing future</div>
            <div className="mini-timeline">
              {(selected?.events ?? []).filter((event) => event.kind !== "invoice_created").map((event, index, events) => (
                <div className="step" key={`${event.at}-${event.kind}`}>
                  <span className="step-dot" aria-hidden="true" />
                  <div>{eventLabel(event.kind)}<small>{formatDate(event.at)}</small></div>
                  {index < events.length - 1 ? <span className="step-line" aria-hidden="true" /> : null}
                </div>
              ))}
              {!selected ? <div className="timeline-empty">No event sequence selected.</div> : null}
            </div>
            <div className="inspector-actions" id="regressions">
              <ActionButton disabled={!selected || workingAction !== null} onClick={() => void runAction("compare")}>Replay comparison</ActionButton>
              <ActionButton variant="secondary" disabled={!selected || workingAction !== null} onClick={() => void runAction("minimize")}>Minimize future</ActionButton>
              <ActionButton variant="secondary" disabled={!selected || workingAction !== null} onClick={() => void runAction("regress")}>Save regression</ActionButton>
              <span className="action-output" role="status" aria-live="polite">{actionMessage}</span>
            </div>
          </aside>
        </div>
      </div>
    </main>
  );
}

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone?: "fail" | "pass" }) {
  return <div className="metric"><span className="metric-label">{label}</span><strong className={`metric-value ${tone ?? ""}`}>{value}</strong><span className="metric-note">{note}</span></div>;
}

function State({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return <div className="state"><span className="state-label">{label}</span><strong className={bad ? "bad" : ""}>{value}</strong></div>;
}

function actionMessageFor(action: "compare" | "minimize" | "regress", result: ActionResponse) {
  if (action === "regress") return `Regression saved · ${result.events ?? "—"} events`;
  if (action === "minimize") return `${result.events ?? "—"} events · patched ${result.comparison?.patched ?? "—"} · saved`;
  return `Original ${result.comparison?.original ?? "—"} · Patched ${result.comparison?.patched ?? "—"}`;
}
