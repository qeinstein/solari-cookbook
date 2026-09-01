"""Coverage-guided mutation and failure-boundary search for temporal futures."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
import random
from typing import Any

from .core import Event, event_sort_key, execute, future_fingerprint, invariant_violations


START = datetime(2026, 9, 1, 9)
PAYMENT_DELAYS = (0, 120, 360, 720, 1440, 2160, 4320)
WAKE_OFFSETS = (-1440, -360, 0, 180, 540, 1080, 1800, 3240, 5040)
DISPUTE_OFFSETS = (-360, 120, 720, 1800)
DISPUTE_DELAYS = (0, 120, 720, 1440, 2160, 4320)


@dataclass(frozen=True)
class Scenario:
    payment_day: int
    payment_delay_minutes: int
    wake_offsets: tuple[int, ...]
    dispute_offset_minutes: int | None = None
    dispute_delay_minutes: int = 0

    def events(self, start: datetime = START) -> list[Event]:
        payment = start + timedelta(days=self.payment_day)
        events = [
            Event(start, "invoice_created"),
            Event(
                payment,
                "customer_payment",
                {"webhook_delay_hours": self.payment_delay_minutes / 60},
            ),
            Event(payment + timedelta(minutes=self.payment_delay_minutes), "payment_webhook"),
        ]
        if self.dispute_offset_minutes is not None:
            dispute = payment + timedelta(minutes=self.dispute_offset_minutes)
            events.extend([
                Event(
                    dispute,
                    "dispute_opened",
                    {"webhook_delay_minutes": self.dispute_delay_minutes},
                ),
                Event(dispute + timedelta(minutes=self.dispute_delay_minutes), "dispute_webhook"),
            ])
        events.extend(
            Event(payment + timedelta(minutes=offset), "agent_wakeup")
            for offset in self.wake_offsets
        )
        return sorted(events, key=event_sort_key)


@dataclass
class SearchFuture:
    future_id: str
    seed: int
    events: list[Event]
    parent_future_id: str | None
    mutation: str
    features: set[str]
    novel_features: set[str]
    shared_prefix_events: int


@dataclass
class SearchResult:
    futures: list[SearchFuture]
    candidates_evaluated: int
    features_discovered: set[str]
    accepted_mutations: int


def seed_scenario(seed: int) -> Scenario:
    return _scenario_from_rng(random.Random(seed))


def _scenario_from_rng(rng: random.Random) -> Scenario:
    wake_count = rng.choice((1, 2, 2, 3))
    dispute_enabled = rng.random() < 0.5
    return Scenario(
        payment_day=rng.randint(1, 4),
        payment_delay_minutes=rng.choice(PAYMENT_DELAYS),
        wake_offsets=tuple(sorted(rng.sample(WAKE_OFFSETS, wake_count))),
        dispute_offset_minutes=rng.choice(DISPUTE_OFFSETS) if dispute_enabled else None,
        dispute_delay_minutes=rng.choice(DISPUTE_DELAYS) if dispute_enabled else 0,
    )


def mutate_scenario(scenario: Scenario, rng: random.Random) -> tuple[Scenario, str]:
    mutation = rng.choice((
        "payment_delay",
        "wakeup_jitter",
        "wakeup_count",
        "toggle_dispute",
        "dispute_timing",
        "dispute_delay",
    ))
    if mutation == "payment_delay":
        return replace(scenario, payment_delay_minutes=rng.choice(PAYMENT_DELAYS)), mutation
    if mutation == "wakeup_jitter":
        wakes = list(scenario.wake_offsets)
        wakes[rng.randrange(len(wakes))] = rng.choice(WAKE_OFFSETS)
        return replace(scenario, wake_offsets=tuple(sorted(set(wakes)))), mutation
    if mutation == "wakeup_count":
        wakes = set(scenario.wake_offsets)
        if len(wakes) > 1 and rng.random() < 0.45:
            wakes.remove(rng.choice(sorted(wakes)))
        else:
            wakes.add(rng.choice(WAKE_OFFSETS))
        return replace(scenario, wake_offsets=tuple(sorted(wakes))[:3]), mutation
    if mutation == "toggle_dispute":
        if scenario.dispute_offset_minutes is None:
            return replace(
                scenario,
                dispute_offset_minutes=rng.choice(DISPUTE_OFFSETS),
                dispute_delay_minutes=rng.choice(DISPUTE_DELAYS),
            ), mutation
        return replace(scenario, dispute_offset_minutes=None, dispute_delay_minutes=0), mutation
    if mutation == "dispute_timing":
        return replace(
            scenario,
            dispute_offset_minutes=rng.choice(DISPUTE_OFFSETS),
            dispute_delay_minutes=scenario.dispute_delay_minutes or rng.choice(DISPUTE_DELAYS),
        ), mutation
    return replace(
        scenario,
        dispute_offset_minutes=scenario.dispute_offset_minutes
        if scenario.dispute_offset_minutes is not None else rng.choice(DISPUTE_OFFSETS),
        dispute_delay_minutes=rng.choice(DISPUTE_DELAYS),
    ), mutation


def _bucket(minutes: int) -> str:
    if minutes == 0:
        return "zero"
    if minutes <= 360:
        return "short"
    if minutes <= 1440:
        return "medium"
    return "long"


def coverage_features(events: list[Event]) -> set[str]:
    features = {f"kind:{event.kind}" for event in events}
    kinds = [event.kind for event in events]
    features.update(f"pair:{left}>{right}" for left, right in zip(kinds, kinds[1:]))
    payment = _single_event(events, "customer_payment")
    payment_webhook = _single_event(events, "payment_webhook")
    payment_delay = int((payment_webhook.at - payment.at).total_seconds() / 60)
    features.add(f"payment-delay:{_bucket(payment_delay)}")
    wakes = [event for event in events if event.kind == "agent_wakeup"]
    features.add(f"wake-count:{len(wakes)}")
    for wake in wakes:
        window = "before" if wake.at < payment.at else "stale" if wake.at < payment_webhook.at else "after"
        features.add(f"payment-window:{window}")
    dispute = _optional_single_event(events, "dispute_opened")
    dispute_webhook = _optional_single_event(events, "dispute_webhook")
    if (dispute is None) != (dispute_webhook is None):
        raise ValueError("dispute_opened and dispute_webhook must be provided together")
    if dispute and dispute_webhook:
        delay = int((dispute_webhook.at - dispute.at).total_seconds() / 60)
        features.add(f"dispute-delay:{_bucket(delay)}")
        for wake in wakes:
            window = "before" if wake.at < dispute.at else "active" if wake.at < dispute_webhook.at else "after"
            features.add(f"dispute-window:{window}")
    violations = invariant_violations(execute(events))
    if not violations:
        features.add("outcome:safe")
    modes = sorted({violation["type"] for violation in violations})
    features.update(f"failure:{mode}" for mode in modes)
    features.add(f"outcome-signature:{'+'.join(modes) if modes else 'safe'}")
    return features


def shared_prefix_length(left: list[Event], right: list[Event]) -> int:
    count = 0
    for left_event, right_event in zip(left, right):
        if left_event.as_dict() != right_event.as_dict():
            break
        count += 1
    return count


def coverage_guided_search(count: int, seed_start: int = 0) -> SearchResult:
    if count < 1:
        return SearchResult([], 0, set(), 0)
    # Keep the search prefix stable: asking for 25 futures must retain the same
    # first 10 branches as asking for 10 with the same seed.
    rng = random.Random((seed_start + 1) * 1_000_003)
    selected: list[tuple[Scenario, SearchFuture]] = []
    seen_features: set[str] = set()
    seen_inputs: set[str] = set()
    candidates_evaluated = 0
    accepted_mutations = 0

    while len(selected) < count:
        pool: list[tuple[int, int, Scenario, str, int | None, set[str], list[Event]]] = []
        round_index = len(selected)
        for offset in range(8):
            seed = seed_start + round_index * 8 + offset
            scenario = seed_scenario(seed)
            events = scenario.events()
            features = coverage_features(events)
            candidates_evaluated += 1
            pool.append((len(features - seen_features), seed, scenario, "seed", None, features, events))
        for parent_index, (parent_scenario, _) in enumerate(selected):
            for _ in range(4):
                scenario, mutation = mutate_scenario(parent_scenario, rng)
                events = scenario.events()
                features = coverage_features(events)
                candidates_evaluated += 1
                pool.append((
                    len(features - seen_features),
                    seed_start + round_index,
                    scenario,
                    mutation,
                    parent_index,
                    features,
                    events,
                ))
        unique_pool = [item for item in pool if future_fingerprint(item[6]) not in seen_inputs]
        if not unique_pool:
            raise RuntimeError("coverage-guided search exhausted unique candidates")
        novelty, seed, scenario, mutation, parent_index, features, events = max(
            unique_pool,
            key=lambda item: (item[0], len(item[5]), future_fingerprint(item[6])),
        )
        future_id = f"future-{len(selected)}"
        parent_id = selected[parent_index][1].future_id if parent_index is not None else None
        shared_prefix = shared_prefix_length(events, selected[parent_index][1].events) if parent_index is not None else 1
        future = SearchFuture(
            future_id=future_id,
            seed=seed,
            events=events,
            parent_future_id=parent_id,
            mutation=mutation,
            features=features,
            novel_features=features - seen_features,
            shared_prefix_events=shared_prefix,
        )
        selected.append((scenario, future))
        seen_inputs.add(future_fingerprint(events))
        seen_features.update(features)
        accepted_mutations += mutation != "seed"

    return SearchResult(
        futures=[future for _, future in selected],
        candidates_evaluated=candidates_evaluated,
        features_discovered=seen_features,
        accepted_mutations=accepted_mutations,
    )


def _with_webhook_delay(events: list[Event], mode: str, minutes: int) -> list[Event]:
    if mode == "stale_payment_contact":
        source_kind, webhook_kind = "customer_payment", "payment_webhook"
    elif mode == "active_dispute_contact":
        source_kind, webhook_kind = "dispute_opened", "dispute_webhook"
    else:
        raise ValueError(f"unsupported failure mode: {mode}")
    source = _single_event(events, source_kind)
    _single_event(events, webhook_kind)
    adjusted = []
    for event in events:
        if event.kind == source_kind:
            payload = dict(event.payload)
            if mode == "stale_payment_contact":
                payload["webhook_delay_hours"] = minutes / 60
            else:
                payload["webhook_delay_minutes"] = minutes
            adjusted.append(Event(event.at, event.kind, payload))
        elif event.kind == webhook_kind:
            adjusted.append(Event(source.at + timedelta(minutes=minutes), event.kind, dict(event.payload)))
        else:
            adjusted.append(event)
    return sorted(adjusted, key=event_sort_key)


def _single_event(events: list[Event], kind: str) -> Event:
    matches = [event for event in events if event.kind == kind]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {kind} event, found {len(matches)}")
    return matches[0]


def _optional_single_event(events: list[Event], kind: str) -> Event | None:
    matches = [event for event in events if event.kind == kind]
    if len(matches) > 1:
        raise ValueError(f"expected at most one {kind} event, found {len(matches)}")
    return matches[0] if matches else None


def _fails_with(events: list[Event], mode: str) -> bool:
    return any(item["type"] == mode for item in invariant_violations(execute(events)))


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if not hours:
        return f"{remainder}m"
    if not remainder:
        return f"{hours}h"
    return f"{hours}h {remainder}m"


def find_failure_boundaries(events: list[Event]) -> list[dict[str, Any]]:
    boundaries = []
    modes = sorted({item["type"] for item in invariant_violations(execute(events))})
    for mode in modes:
        if mode == "stale_payment_contact":
            source = _single_event(events, "customer_payment")
            webhook = _single_event(events, "payment_webhook")
            label = "Payment webhook lag"
        else:
            source = _single_event(events, "dispute_opened")
            webhook = _single_event(events, "dispute_webhook")
            label = "Dispute webhook lag"
        high = int((webhook.at - source.at).total_seconds() / 60)
        if high <= 0 or not _fails_with(_with_webhook_delay(events, mode, high), mode):
            continue
        low = 0
        while high - low > 1:
            middle = (low + high) // 2
            if _fails_with(_with_webhook_delay(events, mode, middle), mode):
                high = middle
            else:
                low = middle
        boundaries.append({
            "failure_type": mode,
            "variable": "webhook_delay_minutes",
            "label": label,
            "last_passing_minutes": low,
            "first_failing_minutes": high,
            "failure_begins_at": format_duration(high),
            "resolution_minutes": 1,
        })
    return boundaries
