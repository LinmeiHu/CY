from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from cyq_game.data.events import EventStore

UTC = UTC


def test_event_sequences_are_monotonic_and_run_scoped(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "governance.jsonl")
    for index in range(3):
        store.append(
            "OPERATOR_DECISION",
            {"index": index},
            run_id="run-1",
            occurred_at=datetime(2024, 1, index + 1, tzinfo=UTC),
        )
    events = store.read_all(verify=True)
    assert [event.sequence for event in events] == [1, 2, 3]
    assert {event.run_id for event in events} == {"run-1"}
    assert events[0].previous_hash == "GENESIS"
    assert events[2].previous_hash == events[1].event_hash
