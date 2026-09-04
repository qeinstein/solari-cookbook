"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { FutureTree } from "../components/FutureTree";
import { ExecutionTrace } from "../components/ExecutionTrace";
import { Inspector, type FutureAction, type SelectedAction } from "../components/Inspector";
import { RunSummary } from "../components/RunSummary";
import { ApiError, fetchRun, postFutureAction } from "../lib/api";
import type { Future, RunData } from "../lib/types";

function bestInitialFuture(futures: Future[]) {
  const failures = futures.filter((future) => future.status === "FAIL");
  return failures.sort((left, right) => {
    const leftBoundary = Math.max(0, ...(left.boundaries ?? []).map((item) => item.first_failing_minutes));
    const rightBoundary = Math.max(0, ...(right.boundaries ?? []).map((item) => item.first_failing_minutes));
    return rightBoundary - leftBoundary;
  })[0] ?? futures[0];
}

export default function Dashboard() {
  const [data, setData] = useState<RunData | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<SelectedAction>(null);
  const [actionError, setActionError] = useState<{ futureId: string; message: string } | null>(null);
  const [workingAction, setWorkingAction] = useState<{ futureId: string; action: FutureAction } | null>(null);

  const loadRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const nextData = await fetchRun();
      setData(nextData);
      setSelectedId((current) => current && nextData.futures.some((future) => future.future_id === current)
        ? current
        : bestInitialFuture(nextData.futures)?.future_id ?? null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The saved trace could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadRun();
  }, [loadRun]);

  const futures = useMemo(() => data?.futures ?? [], [data]);
  const selected = futures.find((future) => future.future_id === selectedId) ?? futures[0];
  const failures = futures.filter((future) => future.status === "FAIL");
  const isSolari = data?.execution_mode === "solari";
  const isModel = data?.agent_config?.mode === "model" || selected?.agent_mode === "model";

  function selectFuture(future: Future) {
    setSelectedId(future.future_id);
    setActionResult(null);
    setActionError(null);
  }

  async function runAction(action: FutureAction) {
    if (!selected) return;
    const futureId = selected.future_id;
    setWorkingAction({ futureId, action });
    setActionError(null);
    try {
      const payload = await postFutureAction(futureId, action);
      setActionResult({ futureId, action, payload });
    } catch (caught) {
      setActionError({ futureId, message: caught instanceof ApiError ? caught.message : "Action unavailable." });
    } finally {
      setWorkingAction(null);
    }
  }

  return (
    <main className="shell">
      <aside className="side" aria-label="Workspace navigation">
        <div className="brand"><div className="mark">TC</div><div className="brand-name">TimeCapsule</div></div>
        <div className="overline">Workspace</div>
        <nav className="nav">
          <Link className="active" aria-current="location" href="/"><span className="nav-icon">01</span>Future tree</Link>
          <Link href="/"><span className="nav-icon">02</span>Replay theatre</Link>
          <Link href="/"><span className="nav-icon">03</span>Evidence</Link>
          <Link href="/"><span className="nav-icon">04</span>Coverage</Link>
        </nav>
        <div className="side-bottom">
          <div className="overline">Execution mode</div>
          <div className="execution-context"><span aria-hidden="true" /><strong>{isModel ? "OpenRouter model" : isSolari ? "Solari isolation" : "Local proof"}</strong></div>
          <p>Coverage-guided temporal search</p>
        </div>
      </aside>

      <div className="content">
        <div className="topbar">
          <div className="crumbs"><span>TimeCapsule</span><span aria-hidden="true">/</span><b>Collections reliability</b></div>
          <div className="top-actions">
            <span className={`mode-badge ${isSolari ? "cloud" : ""}`}><span aria-hidden="true" />{isSolari ? "Solari run" : "Local proof"}</span>
            <a className="docs-link" href="https://github.com/qeinstein/solari-cookbook/tree/main/examples/timecapsule-py" target="_blank" rel="noreferrer">Docs <span aria-hidden="true">↗</span></a>
          </div>
        </div>

        <section className="intro">
          <div><div className="kicker">Coverage-guided temporal fuzzing</div><h1>Find the failure boundary.</h1><p>{isModel ? "Mutate the collections workflow across time, preserve novel futures, and record each OpenRouter decision against the same isolated world." : "Mutate the collections workflow across time, preserve novel futures, and compare the exact input under the built-in original and patched policies."}</p></div>
          <div className="run-info">Latest exploration<strong>{loading ? "Loading saved run…" : data?.run_id ?? "No saved run"}</strong></div>
        </section>

        <ExecutionTrace future={selected} isCloud={isSolari} />

        <div className="workspace" id="future-tree">
          <section aria-labelledby="future-tree-title">
            <div className="section-head">
              <div><h2 id="future-tree-title">Future tree</h2><p>Seed branches mutate into children; connectors preserve their shared event prefix.</p></div>
              <div className="section-meta">{loading ? "Loading trace" : error ? "Trace unavailable" : `${failures.length} unsafe / ${futures.length} selected`}</div>
            </div>
            {error ? <div className="empty error-state" role="alert"><strong>Trace unavailable</strong><span>{error}</span><button type="button" onClick={() => void loadRun()}>Try again</button></div>
              : loading ? <div className="tree" aria-label="Loading futures"><div className="skeleton-row" /><div className="skeleton-row" /><div className="skeleton-row" /></div>
                : futures.length === 0 ? <div className="empty"><strong>No saved run yet.</strong><span>Run <code>python3 main.py run --futures 25</code> first.</span></div>
                  : <FutureTree futures={futures} selectedId={selected?.future_id} onSelect={selectFuture} />}
          </section>
          <Inspector
            future={selected}
            selectedAction={actionResult}
            workingAction={workingAction && selected && workingAction.futureId === selected.future_id ? workingAction.action : null}
            actionError={actionError && selected && actionError.futureId === selected.future_id ? actionError.message : ""}
            onAction={(action) => void runAction(action)}
          />
        </div>

        <RunSummary data={data} />
      </div>
    </main>
  );
}
