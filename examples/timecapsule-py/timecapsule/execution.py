"""Structured execution records for local and replayable future runs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .core import Event, INVARIANT_ID, execute as execute_world, invariant_holds


@dataclass
class Execution:
    future_id: str
    seed: int | None
    agent: str
    events: list[Event]
    status: str
    invariant: str
    messages: list[dict[str, Any]]
    trace: list[dict[str, Any]]

    def as_dict(self) -> dict[str, Any]:
        return {
            "future_id": self.future_id,
            "seed": self.seed,
            "agent": self.agent,
            "status": self.status,
            "invariant": self.invariant,
            "events": [event.as_dict() for event in self.events],
            "messages": [
                {**message, "at": message["at"].isoformat()
                 if isinstance(message["at"], datetime) else message["at"]}
                for message in self.messages
            ],
            "trace": self.trace,
        }


def execute_future(
    future_id: str,
    events: list[Event],
    agent_name: str = "original",
    seed: int | None = None,
) -> Execution:
    """Execute one deterministic future and return a serializable record."""
    fixed = agent_name in {"fixed", "patched"}
    world = execute_world(events, fixed=fixed)
    return Execution(
        future_id=future_id,
        seed=seed,
        agent="fixed" if fixed else "original",
        events=events,
        status="PASS" if invariant_holds(world) else "FAIL",
        invariant=INVARIANT_ID,
        messages=world.messages,
        trace=world.trace,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def read_events(path: Path) -> list[Event]:
    data = json.loads(path.read_text())
    return [
        Event(datetime.fromisoformat(item["at"]), item["kind"], item.get("payload", {}))
        for item in data["events"]
    ]
