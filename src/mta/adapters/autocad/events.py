"""Reads the probe's NDJSON event file (probe-protocol.md §2-3) and checks the stream's integrity.

On the wire the session events are `session.start` / `session.error` / `session.shutdown`. The protocol's
`probe.*` names would reveal the probe to the plugin under test (Constitution §11).
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

START, ERROR, SHUTDOWN = "session.start", "session.error", "session.shutdown"


class ProbeEvent(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)  # newer minor versions may add fields

    v: int
    seq: int
    ts: datetime
    run_id: str
    type: str
    data: dict[str, Any]


@dataclass
class ProbeLog:
    events: list[ProbeEvent] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)  # unreadable lines, sequence gaps

    def of_type(self, *types: str) -> list[ProbeEvent]:
        return [e for e in self.events if e.type in types]

    @property
    def started(self) -> bool:
        return bool(self.events) and self.events[0].type == START

    @property
    def shut_down(self) -> bool:
        return bool(self.events) and self.events[-1].type == SHUTDOWN

    @property
    def clean(self) -> bool:
        """Started, ended normally, no gaps and no internal errors: a missing shutdown means a crash."""
        return self.started and self.shut_down and not self.problems and not self.of_type(ERROR)


def read_events(path: Path) -> ProbeLog:
    log = ProbeLog()
    if not path.is_file():
        log.problems.append(f"{path.name} not found: the session never started")
        return log
    expected = 1
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = ProbeEvent.model_validate(json.loads(line))
        except (ValueError, ValidationError) as exc:
            log.problems.append(f"line {number}: unreadable event ({str(exc)[:120]})")
            continue
        if event.v != 1:
            log.problems.append(f"line {number}: unsupported protocol version {event.v}")
        if event.seq != expected:
            log.problems.append(f"line {number}: seq {event.seq}, expected {expected} (events lost)")
        expected = event.seq + 1
        log.events.append(event)
    return log
