"""JSONL event log with blake3 hash chaining.

Each event is a single JSON line. Events are chained: each event's hash
includes the previous event's hash, forming a tamper-evident log.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
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
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid JSON in event line: {exc}") from exc
        if not isinstance(d, dict):
            raise ValueError(
                f"event line must be a JSON object, got {type(d).__name__}"
            )
        required_keys = ("sequence", "timestamp", "event_type", "data", "prev_hash", "hash")
        missing = [k for k in required_keys if k not in d]
        if missing:
            raise ValueError(f"event line missing required keys: {missing}")
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
        if not isinstance(event_type, str):
            raise TypeError(
                f"event_type must be a string, got {type(event_type).__name__}"
            )
        if not isinstance(data, dict):
            raise TypeError(
                f"data must be a dict, got {type(data).__name__}"
            )
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


# ---------------------------------------------------------------------------
# Schema-format event log verification (event-log.schema.json format)
# ---------------------------------------------------------------------------

# Canonical hash fields per the schema: event_hash is computed over the JSON
# serialization of {game_id, sequence, event_type, player, state_hash,
# prev_hash, payload} with keys sorted and compact separators.
_CANONICAL_KEYS = (
    "game_id", "sequence", "event_type", "player",
    "state_hash", "prev_hash", "payload",
)


def _compute_event_hash(event: dict[str, Any]) -> str:
    """Recompute event_hash from the canonical fields of a schema-format event."""
    missing = [k for k in _CANONICAL_KEYS if k not in event]
    if missing:
        raise ValueError(
            f"event missing canonical keys for hash computation: {missing}"
        )
    canonical = {k: event[k] for k in _CANONICAL_KEYS}
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


@dataclass
class VerifyResult:
    """Result of verifying an event log's hash chain."""

    valid: bool
    events_checked: int
    error: str | None = None
    divergence_index: int | None = None


def verify_log(path: str | Path) -> VerifyResult:
    """Read a JSONL event log file and verify its entire hash chain.

    The file must use the schema format (event-log.schema.json) with fields:
    game_id, sequence, event_type, player, state_hash, prev_hash, event_hash,
    and payload.

    Checks performed:
    - Genesis event has prev_hash of all zeros
    - prev_hash of event N+1 matches event_hash of event N
    - Sequence numbers are consecutive starting from 0
    - No duplicate sequence numbers
    - Each event_hash matches recomputation from canonical fields
    """
    events: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as fp:
        for line in fp:
            stripped = line.strip()
            if not stripped:
                continue
            events.append(json.loads(stripped))

    if not events:
        return VerifyResult(valid=True, events_checked=0)

    seen_sequences: set[int] = set()

    for i, event in enumerate(events):
        seq = event.get("sequence")

        # Check for duplicate sequence number
        if seq in seen_sequences:
            return VerifyResult(
                valid=False,
                events_checked=i,
                error=f"duplicate sequence number {seq}",
                divergence_index=i,
            )
        seen_sequences.add(seq)

        # Check sequence numbers are consecutive starting from 0
        if seq != i:
            return VerifyResult(
                valid=False,
                events_checked=i,
                error=f"expected sequence {i}, got {seq}",
                divergence_index=i,
            )

        # Check genesis prev_hash
        if i == 0:
            if event.get("prev_hash") != GENESIS_HASH:
                return VerifyResult(
                    valid=False,
                    events_checked=i,
                    error="genesis event prev_hash is not all zeros",
                    divergence_index=0,
                )
        else:
            # Check chain linkage: prev_hash must match previous event_hash
            prev_event = events[i - 1]
            if "event_hash" not in prev_event:
                return VerifyResult(
                    valid=False,
                    events_checked=i,
                    error=f"event at sequence {i - 1} missing 'event_hash' field",
                    divergence_index=i - 1,
                )
            expected_prev = prev_event["event_hash"]
            if event.get("prev_hash") != expected_prev:
                return VerifyResult(
                    valid=False,
                    events_checked=i,
                    error=(
                        f"prev_hash mismatch at sequence {seq}: "
                        f"expected {expected_prev}, got {event.get('prev_hash')}"
                    ),
                    divergence_index=i,
                )

        # Check event_hash recomputation
        expected_hash = _compute_event_hash(event)
        if event.get("event_hash") != expected_hash:
            return VerifyResult(
                valid=False,
                events_checked=i,
                error=(
                    f"event_hash mismatch at sequence {seq}: "
                    f"expected {expected_hash}, got {event.get('event_hash')}"
                ),
                divergence_index=i,
            )

    return VerifyResult(valid=True, events_checked=len(events))
