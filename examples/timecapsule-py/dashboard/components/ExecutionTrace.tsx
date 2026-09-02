import type { Future } from "../lib/types";
import { eventLabel, formatMoment, shortHash } from "../lib/presentation";

type StepState = "complete" | "attention";

function actionLabel(value: unknown) {
  const action = String(value ?? "");
  if (action === "agent/original") return "Original policy wakeup";
  if (action === "agent/fixed") return "Patched policy wakeup";
  if (action === "pay") return "Customer payment";
  if (action === "webhook") return "Payment webhook";
  if (action === "dispute") return "Dispute opened";
  if (action === "dispute-webhook") return "Dispute webhook";
  return action ? eventLabel(action) : "No action recorded";
}

function browserValue(value?: string) {
  return value ? value.toUpperCase() : "NOT RECORDED";
}

function BrowserValue({ label, value, alert = false }: { label: string; value?: string; alert?: boolean }) {
  return (
    <div className="browser-value">
      <span>{label}</span>
      <strong className={alert ? "alert" : ""}>{browserValue(value)}</strong>
    </div>
  );
}

function stepState(future: Future, final = false): StepState {
  return final && future.status !== "PASS" ? "attention" : "complete";
}

export function ExecutionTrace({ future, isCloud }: { future?: Future; isCloud: boolean }) {
  if (!future) return null;

  const observed = future.observed;
  const trace = observed?.trace ?? future.recording_keyframes ?? [];
  const lastAction = trace.at(-1);
  const lastEvent = future.events.filter((event) => event.kind !== "invoice_created").at(-1);
  const lastActionValue = lastAction?.action ?? lastEvent?.kind;
  const lastActionAt = lastAction?.at ?? lastEvent?.at;
  const payment = observed?.payment ?? future.payment_status;
  const crm = observed?.crm ?? future.invoice_status;
  const dispute = observed?.dispute ?? future.dispute_status;
  const crmDispute = observed?.crm_dispute ?? future.crm_dispute_status;
  const messageCount = observed?.message_count ?? future.messages?.length ?? 0;
  const statusCopy = future.status === "ERROR"
    ? "Execution interrupted"
    : future.status === "FAIL"
      ? "Invariant violated"
      : "Invariant held";
  const actionCount = future.events.filter((event) => event.kind !== "invoice_created").length;
  const policy = future.agent === "fixed" ? "patched" : "original";
  const hasParity = future.browser_simulator_parity?.verified;
  const steps = [
    {
      title: "Navigate to isolated world",
      detail: isCloud ? "Sandbox preview loaded in a fresh browser" : "Deterministic world fixture prepared",
      state: "complete" as StepState,
    },
    {
      title: "Write the world fixture",
      detail: isCloud ? "server.py + index.html written into the sandbox" : "Collections state loaded from the checked-in fixture",
      state: "complete" as StepState,
    },
    {
      title: "Execute the temporal input",
      detail: `${actionCount} ordered actions · ${shortHash(future.input_hash)}`,
      state: "complete" as StepState,
    },
    {
      title: "Capture browser evidence",
      detail: trace.length ? `${trace.length} observed actions${hasParity ? " · parity verified" : ""}` : "Trace persisted with the future",
      state: "complete" as StepState,
    },
    {
      title: "Analyze the invariant",
      detail: statusCopy,
      state: stepState(future, true),
    },
  ];

  return (
    <section className="replay-theatre" id="replay" aria-labelledby="replay-title">
      <div className="replay-heading">
        <div>
          <div className="kicker">Replay theatre</div>
          <h2 id="replay-title">See the run as it happened.</h2>
          <p>Observable policy actions on the left. Browser state and captured evidence on the right.</p>
        </div>
        <div className={`replay-status ${future.status.toLowerCase()}`}><span aria-hidden="true" />{statusCopy}</div>
      </div>

      <div className="replay-grid">
        <div className="logic-panel">
          <div className="panel-head"><span>Execution path</span><small>Observable actions + evidence</small></div>
          <ol className="execution-steps">
            {steps.map((step, index) => (
              <li className={`execution-step ${step.state}`} key={step.title} style={{ animationDelay: `${index * 70}ms` }}>
                <span className="execution-index">0{index + 1}</span>
                <span className="execution-node" aria-hidden="true" />
                <div><strong>{step.title}</strong><small>{step.detail}</small></div>
              </li>
            ))}
          </ol>
          <div className="logic-note">
            <span>Trust boundary</span>
            <p>This panel shows recorded actions and evidence, not hidden chain-of-thought.</p>
          </div>
        </div>

        <div className="browser-panel" aria-label="Browser evidence replay">
          <div className="browser-chrome">
            <span className="chrome-dots" aria-hidden="true"><i /><i /><i /></span>
            <code>{isCloud ? "sandbox://collections-world" : "local://collections-world"}</code>
            <span className="browser-badge"><i />{isCloud ? "SOLARI BROWSER" : "SIMULATED WORLD"}</span>
          </div>
          <div className="browser-viewport">
            <div className="browser-topline"><span>Collections control room</span><b>INV-1842</b></div>
            <div className="browser-title-row"><h3>Temporal state</h3><strong className={`browser-verdict ${future.status}`}>{future.status}</strong></div>
            <div className="browser-values">
              <BrowserValue label="Payment source" value={payment} />
              <BrowserValue label="CRM mirror" value={crm} alert={future.status === "FAIL" && payment !== crm} />
              <BrowserValue label="Dispute source" value={dispute} />
              <BrowserValue label="CRM dispute mirror" value={crmDispute} alert={future.status === "FAIL" && dispute !== crmDispute} />
            </div>
            <div className="browser-action">
              <span className={`browser-action-icon ${future.status.toLowerCase()}`} aria-hidden="true">{future.status === "ERROR" ? "!" : "↗"}</span>
              <div><strong>{actionLabel(lastActionValue)}</strong><small>{lastActionAt ? formatMoment(String(lastActionAt)) : `${messageCount} message${messageCount === 1 ? "" : "s"} observed`}</small></div>
              <span className="browser-action-label">{policy} policy</span>
            </div>
            <div className="browser-trace-strip" aria-label="Observed browser actions">
              {(trace.length ? trace.slice(-4) : future.events.slice(-4)).map((item, index) => {
                const action = "action" in item ? item.action : item.kind;
                return <span key={`${String(action)}-${index}`}><i />{actionLabel(action)}</span>;
              })}
            </div>
            <div className="browser-footer"><span><i />{hasParity ? "Browser + simulator aligned" : "Evidence captured"}</span><code>{shortHash(future.input_hash)}</code></div>
          </div>
        </div>
      </div>
    </section>
  );
}
