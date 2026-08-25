"""Append-only, hash-chained experiment and operator event ledger."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

GENESIS_HASH = "0" * 64


@dataclass(frozen=True)
class LedgerEntry:
    sequence: int
    recorded_at: str
    event_type: str
    payload: Mapping[str, Any]
    previous_hash: str
    entry_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "recorded_at": self.recorded_at,
            "event_type": self.event_type,
            "payload": dict(self.payload),
            "previous_hash": self.previous_hash,
            "entry_hash": self.entry_hash,
        }


class TrialLedger:
    """Serialize appends under a file lock and reject any broken hash chain."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def read_verified(self) -> tuple[LedgerEntry, ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
            try:
                return _parse_and_verify(handle.read(), source=self.path)
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        recorded_at: datetime | None = None,
    ) -> LedgerEntry:
        if not event_type.strip():
            raise ValueError("ledger event_type cannot be empty")
        timestamp = recorded_at or datetime.now(UTC)
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("ledger recorded_at must be timezone-aware")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                handle.seek(0)
                entries = _parse_and_verify(handle.read(), source=self.path)
                previous_hash = entries[-1].entry_hash if entries else GENESIS_HASH
                sequence = len(entries) + 1
                recorded_at_text = timestamp.astimezone(UTC).isoformat()
                normalized_event_type = event_type.strip()
                normalized_payload = dict(payload)
                unsigned = {
                    "sequence": sequence,
                    "recorded_at": recorded_at_text,
                    "event_type": normalized_event_type,
                    "payload": normalized_payload,
                    "previous_hash": previous_hash,
                }
                entry_hash = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
                entry = LedgerEntry(
                    sequence=sequence,
                    recorded_at=recorded_at_text,
                    event_type=normalized_event_type,
                    payload=normalized_payload,
                    previous_hash=previous_hash,
                    entry_hash=entry_hash,
                )
                line = _canonical(entry.to_dict()) + "\n"
                handle.seek(0, os.SEEK_END)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
                return entry
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _parse_and_verify(raw: str, *, source: Path) -> tuple[LedgerEntry, ...]:
    if raw and not raw.endswith("\n"):
        raise ValueError(f"trial ledger has an incomplete trailing record: {source}")
    entries: list[LedgerEntry] = []
    previous_hash = GENESIS_HASH
    for expected_sequence, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            raise ValueError(f"trial ledger contains a blank record: {source}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"trial ledger is not valid JSON at line {expected_sequence}"
            ) from error
        if not isinstance(value, dict):
            raise ValueError(f"trial ledger record {expected_sequence} is not an object")
        expected_keys = {
            "sequence",
            "recorded_at",
            "event_type",
            "payload",
            "previous_hash",
            "entry_hash",
        }
        if set(value) != expected_keys:
            raise ValueError(f"trial ledger schema mismatch at line {expected_sequence}")
        if value["sequence"] != expected_sequence:
            raise ValueError(f"trial ledger sequence mismatch at line {expected_sequence}")
        if value["previous_hash"] != previous_hash:
            raise ValueError(f"trial ledger chain mismatch at line {expected_sequence}")
        unsigned = {key: value[key] for key in expected_keys if key != "entry_hash"}
        calculated = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
        if value["entry_hash"] != calculated:
            raise ValueError(f"trial ledger hash mismatch at line {expected_sequence}")
        if not isinstance(value["payload"], dict):
            raise ValueError(f"trial ledger payload is not an object at line {expected_sequence}")
        entry = LedgerEntry(
            sequence=int(value["sequence"]),
            recorded_at=str(value["recorded_at"]),
            event_type=str(value["event_type"]),
            payload=value["payload"],
            previous_hash=str(value["previous_hash"]),
            entry_hash=str(value["entry_hash"]),
        )
        entries.append(entry)
        previous_hash = entry.entry_hash
    return tuple(entries)


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("trial ledger payload must be finite and JSON serializable") from error
