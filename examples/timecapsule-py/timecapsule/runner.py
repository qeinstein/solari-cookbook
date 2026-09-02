"""Local exploration orchestration and run-report construction."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from .core import (
    INVARIANT_ID,
    comparison,
    execute,
    future_fingerprint,
    invariant_holds,
    invariant_violations,
    minimize_for_violation,
    save_future,
    violation_snapshot,
)
from .evidence import counterfactual_proof
from .search import SearchFuture, coverage_features, coverage_guided_search, find_failure_boundaries


COVERAGE_DIMENSIONS = {
    "payment-window:before": "Wakeup before payment",
    "payment-window:stale": "Wakeup in stale payment window",
    "payment-window:after": "Wakeup after payment sync",
    "dispute-window:before": "Wakeup before dispute",
    "dispute-window:active": "Wakeup during active dispute",
    "dispute-window:after": "Wakeup after dispute sync",
}


def event_span_days(events):
    if len(events) < 2:
        return 0
    return (events[-1].at - events[0].at).total_seconds() / 86400


def future_coverage(event_sequences):
    counts = {feature: 0 for feature in COVERAGE_DIMENSIONS}
    for events in event_sequences:
        features = coverage_features(events)
        for feature in counts:
            counts[feature] += feature in features
    patterns = [
        {"id": feature, "label": label, "futures": counts[feature]}
        for feature, label in COVERAGE_DIMENSIONS.items()
        if counts[feature]
    ]
    return {
        "covered": len(patterns),
        "possible": len(COVERAGE_DIMENSIONS),
        "patterns": patterns,
    }


def serializable_world(world):
    return {
        "payment_status": world.payment_status,
        "invoice_status": world.invoice_status,
        "dispute_status": world.dispute_status,
        "crm_dispute_status": world.crm_dispute_status,
        "messages": [
            {**message, "at": message["at"].isoformat()}
            for message in world.messages
        ],
        "trace": world.trace,
    }


def local_future_entry(future: SearchFuture) -> dict[str, Any]:
    world = execute(future.events)
    violations = invariant_violations(world)
    return {
        "future_id": future.future_id,
        "seed": future.seed,
        "agent": "original",
        "agent_mode": "policy",
        "agent_evidence": {
            "mode": "policy",
            "label": "DETERMINISTIC",
            "policy": "trust_crm_only",
            "stochastic": False,
        },
        "status": "PASS" if invariant_holds(world) else "FAIL",
        "invariant": INVARIANT_ID,
        "input_hash": future_fingerprint(future.events),
        "violation": violation_snapshot(world),
        "violations": violations,
        "failure_modes": sorted({item["type"] for item in violations}),
        "boundaries": find_failure_boundaries(future.events),
        "comparison": comparison(future.events),
        "counterfactual_proof": counterfactual_proof(future.events),
        "events": [event.as_dict() for event in future.events],
        "search": {
            "parent_future_id": future.parent_future_id,
            "mutation": future.mutation,
            "novel_features": sorted(future.novel_features),
            "shared_prefix_events": future.shared_prefix_events,
        },
        **serializable_world(world),
    }


def build_summary(entries, event_sequences, search, wall_clock_seconds, environments_used=0):
    failures = [entry for entry in entries if entry["status"] == "FAIL"]
    errors = [entry for entry in entries if entry["status"] == "ERROR"]
    errors.extend(
        entry["patched_run"]
        for entry in entries
        if entry.get("patched_run", {}).get("status") == "ERROR"
    )
    future_by_id = {future.future_id: future for future in search.futures}
    original_events = sum(len(entry["events"]) for entry in failures)
    minimal_events = sum(
        len(minimize_for_violation(
            future_by_id[entry["future_id"]].events,
            (entry.get("violation") or {}).get("type"),
        ))
        for entry in entries
        if entry["status"] == "FAIL"
    )
    failure_modes = Counter(
        mode for entry in entries for mode in entry.get("failure_modes", [])
    )
    return {
        "explored": len(entries),
        "failures": len(failures),
        "errors": len(errors),
        "completion_status": "COMPLETE_WITH_ERRORS" if errors else "COMPLETE",
        "failure_rate": round(len(failures) / len(entries), 4) if entries else 0,
        "failure_modes": dict(sorted(failure_modes.items())),
        "patched_replays": len(failures),
        "patched_passes": sum(
            entry.get("comparison", {}).get("patched") == "PASS" for entry in failures
        ),
        "virtual_days": round(sum(event_span_days(events) for events in event_sequences), 2),
        "wall_clock_seconds": round(wall_clock_seconds, 4),
        "minimization_ratio": round(minimal_events / original_events, 4)
        if original_events else None,
        "environments_used": environments_used,
        "coverage": future_coverage(event_sequences),
        "search": {
            "strategy": "coverage_guided_mutation",
            "candidates_evaluated": search.candidates_evaluated,
            "accepted_mutations": search.accepted_mutations,
            "features_discovered": len(search.features_discovered),
        },
    }


def local_run(count: int, seed_start: int, output: Path):
    started = perf_counter()
    search = coverage_guided_search(count, seed_start)
    entries = [local_future_entry(future) for future in search.futures]
    elapsed = perf_counter() - started
    summary = build_summary(
        entries,
        [future.events for future in search.futures],
        search,
        elapsed,
    )
    payload = {
        "run_id": f"local-{seed_start}-{seed_start + count - 1}",
        "execution_mode": "local",
        "started_at": datetime.now().astimezone().isoformat(),
        "futures": entries,
        "summary": summary,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"Futures explored: {count}")
    print(f"Candidates evaluated: {search.candidates_evaluated}")
    print(f"Coverage features: {len(search.features_discovered)}")
    print(f"Failures found: {summary['failures']} {summary['failure_modes']}")
    print(f"Wall clock: {summary['wall_clock_seconds']:.4f}s")
    print(f"Run saved: {output}")
    first_failure = next((future for future, entry in zip(search.futures, entries) if entry["status"] == "FAIL"), None)
    if first_failure:
        first_entry = next(entry for entry in entries if entry["future_id"] == first_failure.future_id)
        minimal = minimize_for_violation(
            first_failure.events,
            (first_entry.get("violation") or {}).get("type"),
        )
        minimal_path = output.parent / f"{first_failure.future_id}-minimal.json"
        save_future(minimal_path, minimal)
        result = comparison(minimal)
        print(f"First failure: {first_failure.future_id}")
        print(f"Minimal failing events: {len(minimal)}")
        print(f"Replay comparison: original={result['original']}, patched={result['patched']}")
        print(f"Minimal future saved: {minimal_path}")
    return payload
