"""Matched search benchmark for the TimeCapsule future strategies."""

from __future__ import annotations

from dataclasses import dataclass
import json
import random
from statistics import median
from typing import Any, Iterable

from .core import Event, execute, future_fingerprint, invariant_violations
from .search import (
    _scenario_from_rng,
    coverage_features,
    mutate_scenario,
)


RARE_FAILURE_SIGNATURE = ("active_dispute_contact",)
POOL_SIZE = 8


def failure_signature(events: list[Event]) -> str:
    modes = tuple(sorted({item["type"] for item in invariant_violations(execute(events))}))
    return "+".join(modes) if modes else "safe"


def behavior_signature(features: set[str]) -> tuple[str, ...]:
    """Coarse observable behavior, independent of exact timestamps or IDs."""
    return tuple(sorted(features))


@dataclass
class TrialResult:
    strategy: str
    seed: int
    budget: int
    futures_evaluated: int
    unique_behaviors: int
    failure_signatures: list[str]
    failure_classes: list[str]
    features_discovered: int
    evaluations_to_first_rare_failure: int | None
    accepted_futures: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "seed": self.seed,
            "budget": self.budget,
            "futures_evaluated": self.futures_evaluated,
            "unique_behaviors": self.unique_behaviors,
            "failure_signatures": self.failure_signatures,
            "failure_classes": self.failure_classes,
            "features_discovered": self.features_discovered,
            "evaluations_to_first_rare_failure": self.evaluations_to_first_rare_failure,
            "accepted_futures": self.accepted_futures,
        }


def _trial_result(
    strategy: str,
    seed: int,
    budget: int,
    observed: list[tuple[list[Event], set[str], str]],
    accepted_futures: int,
) -> TrialResult:
    signatures = sorted({signature for _, _, signature in observed})
    classes = sorted({
        mode
        for _, _, signature in observed
        if signature != "safe"
        for mode in signature.split("+")
    })
    first_rare = next(
        (index for index, (_, _, signature) in enumerate(observed, start=1)
         if tuple(signature.split("+")) == RARE_FAILURE_SIGNATURE),
        None,
    )
    return TrialResult(
        strategy=strategy,
        seed=seed,
        budget=budget,
        futures_evaluated=len(observed),
        unique_behaviors=len({behavior_signature(features) for _, features, _ in observed}),
        failure_signatures=signatures,
        failure_classes=classes,
        features_discovered=len(set().union(*(features for _, features, _ in observed))) if observed else 0,
        evaluations_to_first_rare_failure=first_rare,
        accepted_futures=accepted_futures,
    )


def _observe(scenario) -> tuple[list[Event], set[str], str, str]:
    events = scenario.events()
    features = coverage_features(events)
    return events, features, failure_signature(events), future_fingerprint(events)


def random_trial(budget: int, seed: int) -> TrialResult:
    proposal_rng = random.Random(seed + 0xC0DE)
    selection_rng = random.Random(seed + 0xFACE)
    seen_inputs: set[str] = set()
    observed: list[tuple[list[Event], set[str], str]] = []
    corpus = []
    while len(observed) < budget:
        proposals = []
        if corpus:
            proposals.extend(
                mutate_scenario(proposal_rng.choice(corpus), proposal_rng)[0]
                for _ in range(4)
            )
        proposals.extend(_scenario_from_rng(proposal_rng) for _ in range(POOL_SIZE - len(proposals)))
        batch = []
        for scenario in proposals:
            events, features, signature, fingerprint = _observe(scenario)
            if fingerprint in seen_inputs:
                continue
            seen_inputs.add(fingerprint)
            batch.append((scenario, events, features, signature))
            observed.append((events, features, signature))
            if len(observed) >= budget:
                break
        if not batch:
            raise RuntimeError("random benchmark exhausted unique candidates")
        corpus.append(selection_rng.choice(batch)[0])
    return _trial_result("random", seed, budget, observed, len(corpus))


def coverage_guided_trial(budget: int, seed: int) -> TrialResult:
    proposal_rng = random.Random(seed + 0xC0DE)
    seen_inputs: set[str] = set()
    seen_features: set[str] = set()
    corpus = []
    observed: list[tuple[list[Event], set[str], str]] = []
    while len(observed) < budget:
        proposals = []
        if corpus:
            proposals.extend(
                mutate_scenario(proposal_rng.choice(corpus), proposal_rng)[0]
                for _ in range(4)
            )
        proposals.extend(_scenario_from_rng(proposal_rng) for _ in range(POOL_SIZE - len(proposals)))
        batch = []
        for scenario in proposals:
            events, features, signature, fingerprint = _observe(scenario)
            if fingerprint in seen_inputs:
                continue
            seen_inputs.add(fingerprint)
            batch.append((scenario, events, features, signature))
            observed.append((events, features, signature))
            if len(observed) >= budget:
                break
        if not batch:
            raise RuntimeError("coverage-guided benchmark exhausted unique candidates")
        selected = max(
            batch,
            key=lambda item: (
                len(item[2] - seen_features),
                len(item[2]),
                future_fingerprint(item[1]),
            ),
        )
        corpus.append(selected[0])
        seen_features.update(selected[2])
    return _trial_result("coverage_guided", seed, budget, observed, len(corpus))


def _quantiles(values: Iterable[float | int]) -> dict[str, float | int | None]:
    ordered = sorted(values)
    if not ordered:
        return {"p25": None, "median": None, "p75": None}
    midpoint = median(ordered)
    p25 = ordered[(len(ordered) - 1) // 4]
    p75 = ordered[((len(ordered) - 1) * 3) // 4]
    return {"p25": p25, "median": midpoint, "p75": p75}


def summarize_trials(trials: list[TrialResult]) -> dict[str, Any]:
    rare_hits = [
        trial.evaluations_to_first_rare_failure
        for trial in trials
        if trial.evaluations_to_first_rare_failure is not None
    ]
    return {
        "trials": len(trials),
        "futures_evaluated": _quantiles(trial.futures_evaluated for trial in trials),
        "unique_behaviors": _quantiles(trial.unique_behaviors for trial in trials),
        "failure_signatures_found": _quantiles(len(trial.failure_signatures) for trial in trials),
        "failure_classes_found": _quantiles(len(trial.failure_classes) for trial in trials),
        "features_discovered": _quantiles(trial.features_discovered for trial in trials),
        "evaluations_to_first_rare_failure": {
            **_quantiles(rare_hits),
            "found": len(rare_hits),
            "not_found": len(trials) - len(rare_hits),
            "hit_rate": round(len(rare_hits) / len(trials), 4) if trials else 0,
        },
    }


def paired_summary(random_trials: list[TrialResult], guided_trials: list[TrialResult]) -> dict[str, Any]:
    if len(random_trials) != len(guided_trials):
        raise ValueError("paired benchmark arms must contain the same number of trials")
    behavior_deltas = [
        guided.unique_behaviors - baseline.unique_behaviors
        for baseline, guided in zip(random_trials, guided_trials)
    ]
    random_hits = [trial.evaluations_to_first_rare_failure for trial in random_trials]
    guided_hits = [trial.evaluations_to_first_rare_failure for trial in guided_trials]
    both_hit = [
        (baseline, guided)
        for baseline, guided in zip(random_hits, guided_hits)
        if baseline is not None and guided is not None
    ]
    return {
        "unique_behavior_delta_guided_minus_random": _quantiles(behavior_deltas),
        "guided_behavior_wins": sum(delta > 0 for delta in behavior_deltas),
        "random_behavior_wins": sum(delta < 0 for delta in behavior_deltas),
        "behavior_ties": sum(delta == 0 for delta in behavior_deltas),
        "rare_first_failure_when_both_found": {
            "trials": len(both_hit),
            "guided_wins": sum(guided < baseline for baseline, guided in both_hit),
            "random_wins": sum(baseline < guided for baseline, guided in both_hit),
            "ties": sum(baseline == guided for baseline, guided in both_hit),
        },
    }


def run_benchmark(trials: int = 200, budget: int = 128, seed_start: int = 0) -> dict[str, Any]:
    if trials < 1 or budget < 1:
        raise ValueError("trials and budget must be positive")
    random_trials = [random_trial(budget, seed_start + index) for index in range(trials)]
    guided_trials = [coverage_guided_trial(budget, seed_start + index) for index in range(trials)]
    report = {
        "config": {
            "trials": trials,
            "unique_candidate_budget": budget,
            "seed_start": seed_start,
            "rare_failure_signature": "+".join(RARE_FAILURE_SIGNATURE),
            "pool_size": POOL_SIZE,
            "paired_trial_seeds": True,
        },
        "random": {
            "summary": summarize_trials(random_trials),
            "trials": [trial.as_dict() for trial in random_trials],
        },
        "coverage_guided": {
            "summary": summarize_trials(guided_trials),
            "trials": [trial.as_dict() for trial in guided_trials],
        },
    }
    report["paired"] = paired_summary(random_trials, guided_trials)
    return report


def print_benchmark(report: dict[str, Any]) -> None:
    config = report["config"]
    print(
        f"Matched trials: {config['trials']} | unique candidate budget: "
        f"{config['unique_candidate_budget']} | rare failure: {config['rare_failure_signature']}"
    )
    print("strategy,futures_evaluated,unique_behaviors,failure_signatures,first_rare_failure,rare_hit_rate")
    for name in ("random", "coverage_guided"):
        summary = report[name]["summary"]
        rare = summary["evaluations_to_first_rare_failure"]
        print(
            f"{name},{summary['futures_evaluated']['median']},"
            f"{summary['unique_behaviors']['median']},"
            f"{summary['failure_signatures_found']['median']},"
            f"{rare['median'] if rare['median'] is not None else 'not-found'},"
            f"{rare['hit_rate']}"
        )
        print(f"  unique behaviors p25/p75: {summary['unique_behaviors']['p25']}/{summary['unique_behaviors']['p75']}")
        print(f"  first rare p25/p75: {rare['p25']}/{rare['p75']} | not found: {rare['not_found']}")
    paired = report["paired"]
    rare = paired["rare_first_failure_when_both_found"]
    print(
        "paired: guided behavior wins/ties/losses "
        f"{paired['guided_behavior_wins']}/{paired['behavior_ties']}/{paired['random_behavior_wins']}; "
        "rare first wins guided/random/ties "
        f"{rare['guided_wins']}/{rare['random_wins']}/{rare['ties']}"
    )


def save_benchmark(path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2) + "\n")
