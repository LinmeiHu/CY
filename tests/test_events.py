from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from cyq_game.data.events import EventStore, replay_state

UTC = UTC


def test_replay_is_idempotent_by_event_id(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    now = datetime(2024, 1, 2, tzinfo=UTC)
    first = store.append(
        "STATE_SET",
        {"key": "x", "value": 1},
        run_id="r1",
        occurred_at=now,
        event_id="same",
    )
    duplicate = store.append(
        "STATE_SET",
        {"key": "x", "value": 1},
        run_id="r1",
        occurred_at=now,
        event_id="same",
    )
    assert duplicate == first
    assert len(store.read_all()) == 1
    assert replay_state(store.read_all()) == {"x": 1}

    with pytest.raises(ValueError, match="different event content"):
        store.append(
            "STATE_SET",
            {"key": "x", "value": 2},
            run_id="r1",
            occurred_at=now,
            event_id="same",
        )


def test_event_tampering_breaks_hash_chain(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.append("STATE_SET", {"key": "x", "value": 1}, run_id="r1")
    text = store.path.read_text(encoding="utf-8")
    store.path.write_text(text.replace('"value": 1', '"value": 9'), encoding="utf-8")
    with pytest.raises(ValueError, match="content hash mismatch"):
        store.read_all(verify=True)


def test_append_verifies_existing_chain_only_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    calls = 0
    original_read_all = store.read_all

    def counted_read_all(*, verify: bool = True):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        return original_read_all(verify=verify)

    monkeypatch.setattr(store, "read_all", counted_read_all)
    store.append("STATE_SET", {"key": "x", "value": 1}, run_id="r1")
    store.append("STATE_SET", {"key": "x", "value": 2}, run_id="r1")
    store.append("STATE_SET", {"key": "x", "value": 3}, run_id="r1")

    assert calls == 1
    assert len(original_read_all(verify=True)) == 3


def test_count_reuses_verified_append_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = EventStore(tmp_path / "events.jsonl")
    store.append("STATE_SET", {"key": "x", "value": 1}, run_id="r1")

    def unexpected_read_all(*, verify: bool = True):  # type: ignore[no-untyped-def]
        raise AssertionError(f"unchanged event log was reparsed (verify={verify})")

    monkeypatch.setattr(store, "read_all", unexpected_read_all)
    assert store.count() == 1


def test_append_revalidates_after_external_change(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    store = EventStore(path)
    store.append("STATE_SET", {"key": "x", "value": 1}, run_id="r1")
    path.write_text(path.read_text(encoding="utf-8") + "corrupt\n", encoding="utf-8")

    with pytest.raises(ValueError):
        store.append("STATE_SET", {"key": "x", "value": 2}, run_id="r1")
