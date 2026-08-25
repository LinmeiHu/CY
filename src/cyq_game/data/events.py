from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO


@dataclass(frozen=True)
class EventEnvelope:
    sequence: int
    event_id: str
    event_type: str
    occurred_at: str
    run_id: str
    payload: dict[str, Any]
    previous_hash: str
    event_hash: str


class EventStore:
    """Append-only JSONL event store with a deterministic hash chain."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._cached_sequence: int | None = None
        self._cached_previous_hash: str | None = None
        self._cached_size: int | None = None
        self._cached_events_by_id: dict[str, EventEnvelope] | None = None
        self._append_handle: TextIO | None = None

    def append(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        run_id: str,
        occurred_at: datetime | None = None,
        event_id: str | None = None,
    ) -> EventEnvelope:
        self._ensure_append_tail()
        assert self._cached_sequence is not None
        assert self._cached_previous_hash is not None
        assert self._cached_events_by_id is not None
        if event_id is not None and event_id in self._cached_events_by_id:
            existing = self._cached_events_by_id[event_id]
            if _same_logical_event(existing, event_type, payload, run_id):
                return existing
            raise ValueError("event_id already exists with different event content")
        sequence = self._cached_sequence + 1
        previous_hash = self._cached_previous_hash
        timestamp = (occurred_at or datetime.now(UTC)).isoformat()
        stable_id = event_id or hashlib.sha256(
            f"{run_id}|{sequence}|{event_type}|{timestamp}".encode()
        ).hexdigest()[:24]
        if stable_id in self._cached_events_by_id:
            raise ValueError("generated event_id already exists")
        body = {
            "sequence": sequence,
            "event_id": stable_id,
            "event_type": event_type,
            "occurred_at": timestamp,
            "run_id": run_id,
            "payload": payload,
            "previous_hash": previous_hash,
        }
        event_hash = _hash(body)
        envelope = EventEnvelope(
            sequence=sequence,
            event_id=stable_id,
            event_type=event_type,
            occurred_at=timestamp,
            run_id=run_id,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self._append_handle is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._append_handle = self.path.open("a", encoding="utf-8", buffering=1024 * 1024)
        line = json.dumps(asdict(envelope), sort_keys=True, ensure_ascii=False) + "\n"
        self._append_handle.write(line)
        self._append_handle.flush()
        self._cached_sequence = sequence
        self._cached_previous_hash = event_hash
        self._cached_size = (self._cached_size or 0) + len(line.encode("utf-8"))
        self._cached_events_by_id[stable_id] = envelope
        return envelope

    def _ensure_append_tail(self) -> None:
        current_size = self.path.stat().st_size if self.path.exists() else 0
        if self._cached_size == current_size:
            return
        events = self.read_all(verify=True)
        self._cached_sequence = len(events)
        self._cached_previous_hash = events[-1].event_hash if events else "GENESIS"
        self._cached_size = current_size
        self._cached_events_by_id = {event.event_id: event for event in events}

    def read_all(self, *, verify: bool = True) -> list[EventEnvelope]:
        if not self.path.exists():
            return []
        result: list[EventEnvelope] = []
        seen_event_ids: set[str] = set()
        previous = "GENESIS"
        with self.path.open(encoding="utf-8") as handle:
            for expected_sequence, line in enumerate(handle, start=1):
                raw = json.loads(line)
                envelope = EventEnvelope(
                    sequence=int(raw["sequence"]),
                    event_id=str(raw["event_id"]),
                    event_type=str(raw["event_type"]),
                    occurred_at=str(raw["occurred_at"]),
                    run_id=str(raw["run_id"]),
                    payload=dict(raw["payload"]),
                    previous_hash=str(raw["previous_hash"]),
                    event_hash=str(raw["event_hash"]),
                )
                if verify:
                    body = {key: raw[key] for key in raw if key != "event_hash"}
                    if envelope.sequence != expected_sequence:
                        raise ValueError("event sequence is not append-only")
                    if envelope.previous_hash != previous:
                        raise ValueError("event hash chain is broken")
                    if _hash(body) != envelope.event_hash:
                        raise ValueError("event content hash mismatch")
                    if envelope.event_id in seen_event_ids:
                        raise ValueError("duplicate event_id in persisted event log")
                seen_event_ids.add(envelope.event_id)
                previous = envelope.event_hash
                result.append(envelope)
        return result

    def count(self) -> int:
        """Return the verified append tail without reparsing an unchanged log."""
        self._ensure_append_tail()
        assert self._cached_sequence is not None
        return self._cached_sequence

    def digest(self) -> str:
        events = self.read_all(verify=True)
        return events[-1].event_hash if events else "GENESIS"


def replay_state(events: list[EventEnvelope]) -> dict[str, Any]:
    state: dict[str, Any] = {}
    seen: set[str] = set()
    for event in events:
        if event.event_id in seen:
            continue
        seen.add(event.event_id)
        if event.event_type == "STATE_SET":
            state[str(event.payload["key"])] = event.payload["value"]
        elif event.event_type == "STATE_DELETE":
            state.pop(str(event.payload["key"]), None)
    return state


def _hash(body: dict[str, Any]) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _same_logical_event(
    existing: EventEnvelope,
    event_type: str,
    payload: dict[str, Any],
    run_id: str,
) -> bool:
    return (
        existing.event_type == event_type
        and existing.run_id == run_id
        and _canonical_json(existing.payload) == _canonical_json(payload)
    )


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
