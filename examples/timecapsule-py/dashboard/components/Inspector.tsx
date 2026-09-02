import type { ActionResponse, CounterfactualProof, FailureBoundary, Future, TimeEvent, ViolationSnapshot } from "../lib/types";
import { eventLabel, formatMoment, shortHash } from "../lib/presentation";

export type FutureAction = "compare" | "minimize" | "regress";
export type SelectedAction = { futureId: string; action: FutureAction; payload: ActionResponse } | null;

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
  return <button className={`action-button ${variant}`} type="button" disabled={disabled} onClick={onClick}>{children}</button>;
}

function State({ label, value, bad = false }: { label: string; value: string; bad?: boolean }) {
  return <div className="state"><span className="state-label">{label}</span><strong className={bad ? "bad" : ""}>{value}</strong></div>;
}

function Timeline({ events, violationAt }: { events: TimeEvent[]; violationAt?: string }) {
  const visible = events.filter((event) => event.kind !== "invoice_created");
  return (
    <div className="mini-timeline">
      {visible.map((event, index) => {
        const violating = event.kind === "agent_wakeup" && event.at === violationAt;
        return (
          <div className={`step ${violating ? "violating" : ""}`} key={`${event.at}-${event.kind}-${index}`}>
            <span className="step-dot" aria-hidden="true" />
            <div>{eventLabel(event.kind)}{violating ? <em>violation</em> : null}<small>{formatMoment(event.at)}</small></div>
            {index < visible.length - 1 ? <span className="step-line" aria-hidden="true" /> : null}
          </div>
        );
      })}
    </div>
  );
}

function BoundaryCard({
  future,
  boundaries,
  violationType,
}: {
  future?: Future;
  boundaries?: FailureBoundary[];
  violationType?: ViolationSnapshot["type"];
}) {
  const candidates = boundaries ?? future?.boundaries ?? [];
  const boundary = candidates.find((item) => item.failure_type === violationType) ?? candidates[0];
  if (!boundary) return null;
  return (
    <div className="boundary-card">
      <div><span>Failure boundary · 1-minute resolution</span><strong>Failure begins at {boundary.failure_begins_at}</strong></div>
      <div className="boundary-scale">
        <span className="safe-edge"><b>{boundary.last_passing_minutes}m</b> pass</span>
        <span className="boundary-cut" aria-hidden="true" />
        <span className="fail-edge"><b>{boundary.first_failing_minutes}m</b> fail</span>
      </div>
      <small>{boundary.label} binary-searched while every other event stayed fixed.</small>
    </div>
  );
}

function CounterfactualDiff({ proof, modelMode }: { proof?: CounterfactualProof; modelMode: boolean }) {
  if (!proof) return null;
  const runtimeError = proof.runtime?.status === "ERROR";
  return (
    <div className="counterfactual-diff">
      <div className="diff-title"><span>Same future manifest</span><b>{proof.verified ? "VERIFIED" : "UNVERIFIED"}</b></div>
      <div className="diff-row"><span>Environment</span><code>{shortHash(proof.original.environment_hash)}</code><strong>=</strong><code>{shortHash(proof.patched.environment_hash)}</code></div>
      <div className="diff-row"><span>Event input</span><code>{shortHash(proof.original.event_hash)}</code><strong>=</strong><code>{shortHash(proof.patched.event_hash)}</code></div>
      <div className="diff-row"><span>World assets</span><code>{shortHash(proof.original.world_asset_hash)}</code><strong>=</strong><code>{shortHash(proof.patched.world_asset_hash)}</code></div>
      <div className="diff-row changed"><span>{modelMode ? "Instruction" : "Policy"}</span><code>{proof.only_change.original}</code><strong>→</strong><code>{proof.only_change.patched}</code></div>
      <p className={modelMode ? "model-warning" : undefined}>{modelMode ? `All ${proof.identical_fields.length} environment inputs match. Model behavior is stochastic; identical future inputs do not guarantee identical actions.` : `All ${proof.identical_fields.length} environment inputs match. Only the built-in policy changes.`}</p>
      {runtimeError ? <p className="runtime-error">Patched replay returned ERROR · no counterfactual runtime verification was established.</p> : proof.runtime?.verified ? <p className="runtime-proof">Runtime verified · same input/environment · fresh sandbox and browser for patched replay.</p> : null}
    </div>
  );
}

function RecordingEvidence({ future }: { future: Future }) {
  const originalAvailable = Boolean(future.recording_path);
  const fixedAvailable = Boolean(future.patched_run?.recording_path);
  if (!originalAvailable && !fixedAvailable && !future.recording_keyframes?.length) return null;
  const keyframes = (future.recording_keyframes ?? []).filter((item) => item.action).slice(0, 4);
  return (
    <div className="recording-card">
      <div className="recording-head"><span>Solari session evidence</span><b>{future.recording_events ?? keyframes.length} events</b></div>
      {keyframes.length ? <div className="keyframes">{keyframes.map((item, index) => <span key={`${String(item.action)}-${index}`}><i />{String(item.action).replace("agent/", "agent · ")}</span>)}</div> : null}
      <div className="recording-links">
        {originalAvailable ? <a href={`/api/futures/${future.future_id}/recording/original`} target="_blank" rel="noreferrer">View original recording ↗</a> : null}
        {fixedAvailable ? <a href={`/api/futures/${future.future_id}/recording/fixed`} target="_blank" rel="noreferrer">View patched recording ↗</a> : null}
      </div>
    </div>
  );
}

function actionSummary(result: SelectedAction) {
  if (!result) return "";
  if (result.action === "regress") return `Regression saved · ${result.payload.events ?? "—"} events`;
  if (result.action === "minimize") return `${result.payload.removed_events ?? 0} events removed · patched ${result.payload.comparison?.patched ?? "—"}`;
  return `Original ${result.payload.comparison?.original ?? "—"} · patched ${result.payload.comparison?.patched ?? "—"}`;
}

export function Inspector({
  future,
  selectedAction,
  workingAction,
  actionError,
  onAction,
}: {
  future?: Future;
  selectedAction: SelectedAction;
  workingAction: string | null;
  actionError: string;
  onAction: (action: FutureAction) => void;
}) {
  const action = selectedAction?.futureId === future?.future_id ? selectedAction : null;
  const executionError = future?.status === "ERROR";
  const events = action?.action === "minimize" && action.payload.minimal_events ? action.payload.minimal_events : future?.events ?? [];
  const violation = action?.action === "minimize" ? action.payload.minimal_violation : future?.violation;
  const proof = action?.payload.counterfactual_proof ?? future?.counterfactual_proof;
  const modelMode = future?.agent_mode === "model" || future?.agent_evidence?.mode === "model";
  return (
    <aside className={`inspector ${future?.status === "PASS" ? "pass-inspector" : ""} ${executionError ? "error-inspector" : ""}`} aria-labelledby="inspector-title">
      <div className="inspector-kicker"><span>{executionError ? "Execution error" : future?.status === "FAIL" ? violation?.type.replaceAll("_", " ") : "Invariant held"}</span><span>{future?.future_id ?? "—"}</span></div>
      <h3 id="inspector-title">{executionError ? "Evidence unavailable" : violation?.title ?? "No unsafe contact observed"}</h3>
      <p className="inspector-sub">{executionError ? future.error?.message ?? "The isolated execution did not complete." : violation?.summary ?? "Every agent wakeup stayed outside stale payment and dispute intervals."}</p>
      {executionError ? <div className="execution-error" role="alert"><span>Verdict</span><strong>ERROR</strong><small>No PASS or FAIL was assigned because the environment did not complete.</small></div> : <div className="state-grid">
        <State label={violation?.source_label ?? "External sources"} value={violation?.source_value ?? "CONSISTENT"} />
        <State label={violation?.mirror_label ?? "CRM mirrors"} value={violation?.mirror_value ?? "SYNCED"} bad={Boolean(violation)} />
        <State label={violation ? "Agent belief" : "Unsafe contact"} value={violation?.agent_belief ?? "NONE"} bad={Boolean(violation)} />
      </div>}
      <div className="inspector-actions">
        <ActionButton disabled={!future || executionError || workingAction !== null} onClick={() => onAction("compare")}>Replay exact input</ActionButton>
        <ActionButton variant="secondary" disabled={!future || future.status !== "FAIL" || workingAction !== null} onClick={() => onAction("minimize")}>Minimize</ActionButton>
        <ActionButton variant="secondary" disabled={!future || future.status !== "FAIL" || workingAction !== null} onClick={() => onAction("regress")}>Save regression</ActionButton>
        <span className="action-output" role="status" aria-live="polite">{workingAction ? "Running evidence step…" : actionError || actionSummary(action)}</span>
      </div>
      <BoundaryCard future={future} boundaries={action?.payload.boundaries} violationType={violation?.type} />
      <div className="timeline-heading"><span>{action?.action === "minimize" ? "Minimized counterexample" : "Candidate future"}</span><b>{events.length} events</b></div>
      <Timeline events={events} violationAt={violation?.at} />
      {future?.status === "FAIL" ? <div className="proof-flow" id="evidence"><div><span>Original</span><strong className="fail">FAIL</strong></div><span>→</span><div><span>Minimize</span><strong>{action?.action === "minimize" ? `${action.payload.before_events}→${action.payload.events}` : "ready"}</strong></div><span>→</span><div><span>Patched</span><strong className="pass">{future.comparison?.patched ?? "—"}</strong></div></div> : null}
      <CounterfactualDiff proof={proof} modelMode={modelMode} />
      {future?.browser_simulator_parity?.verified ? <p className="runtime-proof">{modelMode ? "Browser and simulator agree on final temporal state; model action evidence is recorded separately." : "Browser and simulator agree on final state, message count, and failure class."}</p> : null}
      {future ? <RecordingEvidence future={future} /> : null}
    </aside>
  );
}
