from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from cyq_game.strategy.ledger import TrialLedger


def test_trial_ledger_is_append_only_and_hash_chained(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    first = ledger.append(
        "ENTRY_GRID_TRIAL",
        {"parameter_id": "entry-1", "status": "PASS"},
        recorded_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    second = ledger.append(
        "EXIT_GRID_TRIAL",
        {"parameter_id": "exit-1", "status": "FAIL"},
        recorded_at=datetime(2020, 1, 2, tzinfo=UTC),
    )

    entries = ledger.read_verified()

    assert entries == (first, second)
    assert second.previous_hash == first.entry_hash


def test_trial_ledger_rejects_tampering(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    ledger.append("TRIAL", {"result": 1})
    record = json.loads(ledger.path.read_text())
    record["payload"]["result"] = 2
    ledger.path.write_text(json.dumps(record) + "\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        ledger.read_verified()


def test_trial_ledger_rejects_incomplete_tail_and_nonfinite_payload(tmp_path) -> None:
    ledger = TrialLedger(tmp_path / "trials.jsonl")
    ledger.append("TRIAL", {"result": 1})
    ledger.path.write_text(ledger.path.read_text().rstrip("\n"))

    with pytest.raises(ValueError, match="incomplete trailing record"):
        ledger.read_verified()

    clean = TrialLedger(tmp_path / "clean.jsonl")
    with pytest.raises(ValueError, match="finite and JSON serializable"):
        clean.append("TRIAL", {"result": float("nan")})
