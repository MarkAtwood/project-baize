"""JSONL event log with blake3 hash chaining.

Each event is a single JSON line. Events are chained: each event's hash
includes the previous event's hash, forming a tamper-evident log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, TextIO

import blake3


@dataclass
class Event:
    """A single structured event in the log."""

    sequence: int
    timestamp: float
    event_type: str
    data: dict[str, Any]
    prev_hash: str
    event_hash: str

    def to_json_line(self) -> str:
        """Serialize to a single JSON line (no trailing newline)."""
        return json.dumps({
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "data": self.data,
            "prev_hash": self.prev_hash,
            "hash": self.event_hash,
        }, separators=(",", ":"))

    @staticmethod
    def from_json_line(line: str) -> Event:
        """Parse an Event from a single JSON line."""
        d = json.loads(line)
        return Event(
            sequence=d["sequence"],
            timestamp=d["timestamp"],
            event_type=d["event_type"],
            data=d["data"],
            prev_hash=d["prev_hash"],
            event_hash=d["hash"],
        )


def _compute_hash(
    sequence: int,
    timestamp: float,
    event_type: str,
    data: dict[str, Any],
    prev_hash: str,
) -> str:
    """Compute the blake3 hash for an event, chaining from prev_hash."""
    payload = json.dumps({
        "sequence": sequence,
        "timestamp": timestamp,
        "event_type": event_type,
        "data": data,
        "prev_hash": prev_hash,
    }, separators=(",", ":"), sort_keys=True)
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


# The genesis hash: used as prev_hash for the very first event.
GENESIS_HASH = "0" * 64


@dataclass
class EventLog:
    """Append-only JSONL event log with blake3 hash chaining."""

    _events: list[Event] = field(default_factory=list)
    _last_hash: str = GENESIS_HASH

    @property
    def events(self) -> list[Event]:
        """Return the list of events (read-only view)."""
        return list(self._events)

    @property
    def last_hash(self) -> str:
        """The hash of the most recent event, or GENESIS_HASH if empty."""
        return self._last_hash

    def __len__(self) -> int:
        return len(self._events)

    def append(
        self,
        event_type: str,
        data: dict[str, Any],
        timestamp: float | None = None,
    ) -> Event:
        """Append a new event to the log and return it."""
        seq = len(self._events)
        ts = timestamp if timestamp is not None else time.time()
        event_hash = _compute_hash(seq, ts, event_type, data, self._last_hash)
        event = Event(
            sequence=seq,
            timestamp=ts,
            event_type=event_type,
            data=data,
            prev_hash=self._last_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        self._last_hash = event_hash
        return event

    def verify(self) -> bool:
        """Verify the entire hash chain. Returns True if valid."""
        prev = GENESIS_HASH
        for event in self._events:
            if event.prev_hash != prev:
                return False
            expected = _compute_hash(
                event.sequence,
                event.timestamp,
                event.event_type,
                event.data,
                event.prev_hash,
            )
            if event.event_hash != expected:
                return False
            prev = event.event_hash
        return True

    def write_jsonl(self, fp: TextIO) -> None:
        """Write all events to a file-like object as JSONL."""
        for event in self._events:
            fp.write(event.to_json_line())
            fp.write("\n")

    @classmethod
    def read_jsonl(cls, fp: TextIO) -> EventLog:
        """Read events from a JSONL file-like object."""
        log = cls()
        for line in fp:
            stripped = line.strip()
            if not stripped:
                continue
            event = Event.from_json_line(stripped)
            log._events.append(event)
            log._last_hash = event.event_hash
        return log
