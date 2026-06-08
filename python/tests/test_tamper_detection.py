"""Tests for event log tamper detection (schema-format JSONL)."""

import json
import tempfile
from pathlib import Path

import blake3
import pytest

from baize.events import GENESIS_HASH, VerifyResult, verify_log

VECTORS_PATH = Path(__file__).resolve().parent.parent.parent / "tests" / "vectors" / "event-log-examples.jsonl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CANONICAL_KEYS = (
    "game_id", "sequence", "event_type", "player",
    "state_hash", "prev_hash", "payload",
)


def _recompute_hash(event: dict) -> str:
    canonical = {k: event[k] for k in _CANONICAL_KEYS}
    payload = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return blake3.blake3(payload.encode("utf-8")).hexdigest()


def _load_events() -> list[dict]:
    with open(VECTORS_PATH, encoding="utf-8") as fp:
        return [json.loads(line) for line in fp if line.strip()]


def _write_events(events: list[dict], path: Path) -> None:
    with open(path, "w", encoding="utf-8") as fp:
        for e in events:
            fp.write(json.dumps(e, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidLog:
    def test_valid_log_passes(self):
        result = verify_log(str(VECTORS_PATH))
        assert result.valid is True
        assert result.events_checked == 10
        assert result.error is None
        assert result.divergence_index is None


class TestPayloadTamper:
    def test_modifying_payload_breaks_chain(self):
        """Changing an event's payload invalidates its event_hash."""
        events = _load_events()
        # Tamper with event 3's payload
        events[3]["payload"]["next_player"] = "Z"

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            _write_events(events, Path(fp.name))
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is False
        assert result.divergence_index == 3
        assert "event_hash mismatch" in result.error


class TestInsertEvent:
    def test_inserting_event_breaks_chain(self):
        """Inserting an event breaks sequence and/or chain linkage."""
        events = _load_events()
        # Duplicate event 2 and insert it at position 3
        inserted = events[2].copy()
        inserted["sequence"] = 3
        events.insert(3, inserted)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            _write_events(events, Path(fp.name))
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is False
        # The inserted event will fail: either hash mismatch or chain break
        assert result.divergence_index is not None


class TestDeleteEvent:
    def test_deleting_event_breaks_chain(self):
        """Removing an event breaks the chain linkage."""
        events = _load_events()
        # Delete event at index 4
        del events[4]

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            _write_events(events, Path(fp.name))
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is False
        assert result.divergence_index is not None


class TestWrongGenesisHash:
    def test_wrong_genesis_hash_detected(self):
        """A genesis event with non-zero prev_hash is detected."""
        events = _load_events()
        events[0]["prev_hash"] = "ff" * 32
        # Recompute event_hash with the tampered prev_hash so only the
        # genesis check catches it (not the hash recomputation check first).
        events[0]["event_hash"] = _recompute_hash(events[0])

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            _write_events(events, Path(fp.name))
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is False
        assert result.divergence_index == 0
        assert "genesis" in result.error.lower() or "prev_hash" in result.error.lower()


class TestDuplicateSequence:
    def test_duplicate_sequence_number_detected(self):
        """Two events with the same sequence number are rejected."""
        events = _load_events()
        # Give event at index 5 the same sequence as event at index 4
        events[5]["sequence"] = events[4]["sequence"]
        # Recompute event_hash to avoid hash mismatch catching it first
        events[5]["event_hash"] = _recompute_hash(events[5])

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            _write_events(events, Path(fp.name))
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is False
        assert result.divergence_index is not None
        assert "sequence" in result.error.lower() or "duplicate" in result.error.lower()


class TestEmptyLog:
    def test_empty_log_is_valid(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False
        ) as fp:
            fp.write("")
            tmp = fp.name

        result = verify_log(tmp)
        assert result.valid is True
        assert result.events_checked == 0


class TestVerifyResultDataclass:
    def test_defaults(self):
        r = VerifyResult(valid=True, events_checked=5)
        assert r.error is None
        assert r.divergence_index is None

    def test_all_fields(self):
        r = VerifyResult(
            valid=False,
            events_checked=3,
            error="broken",
            divergence_index=2,
        )
        assert r.valid is False
        assert r.events_checked == 3
        assert r.error == "broken"
        assert r.divergence_index == 2
