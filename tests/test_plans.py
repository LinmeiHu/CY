from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cyq_game.data.events import EventStore
from cyq_game.domain import Action, PlanStatus, StrategyFamily
from cyq_game.execution.plans import PlanRepository, TradingPlan

UTC = UTC


def test_plan_revisions_are_append_only_and_linked(tmp_path: Path) -> None:
    now = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
    events = EventStore(tmp_path / "events.jsonl")
    repository = PlanRepository(events, "run-1")
    first = TradingPlan.create(
        symbol="000001.SZ",
        family=StrategyFamily.ACCUMULATION_TREND,
        action=Action.BUY,
        now=now,
        expires_at=now + timedelta(days=3),
        entry_trigger="next tradable open",
        invalidation="base breaks",
        protective_stop=9.0,
        target_fraction=0.05,
        max_participation=0.03,
        edge_card_digest="abc",
    )
    repository.append(first, now)
    second = first.revised(
        now + timedelta(days=1),
        expires_at=now + timedelta(days=4),
        protective_stop=9.2,
    )
    repository.append(second, now + timedelta(days=1))
    assert repository.latest(first.plan_id).version == 2
    assert second.parent_version == 1
    assert len(events.read_all(verify=True)) == 2


def test_changed_thesis_requires_a_new_plan() -> None:
    now = datetime(2024, 1, 2, 8, 0, tzinfo=UTC)
    plan = TradingPlan.create(
        symbol="000001.SZ",
        family=StrategyFamily.ACCUMULATION_TREND,
        action=Action.BUY,
        now=now,
        expires_at=now + timedelta(days=3),
        entry_trigger="next tradable open",
        invalidation="base breaks",
        protective_stop=9.0,
        target_fraction=0.05,
        max_participation=0.03,
        edge_card_digest="abc",
    )

    with pytest.raises(ValueError, match="create a new plan"):
        plan.revised(now + timedelta(days=1), edge_card_digest="different-thesis")


def test_split_rebases_active_plan_stop_as_append_only_version(tmp_path: Path) -> None:
    now = datetime(2026, 5, 28, 15, 30, tzinfo=UTC)
    event_time = datetime(2026, 5, 29, 9, 30, tzinfo=UTC)
    events = EventStore(tmp_path / "events.jsonl")
    repository = PlanRepository(events, "run-1")
    draft = TradingPlan.create(
        symbol="605507.SH",
        family=StrategyFamily.ACCUMULATION_TREND,
        action=Action.BUY,
        now=now,
        expires_at=now + timedelta(days=3),
        entry_trigger="next tradable open",
        invalidation="base breaks",
        protective_stop=21.0,
        target_fraction=0.05,
        max_participation=0.03,
        edge_card_digest="abc",
    )
    active = replace(
        draft,
        version=2,
        parent_version=1,
        status=PlanStatus.ACTIVE,
    )
    repository.append(draft, now)
    repository.append(active, now)

    rebased = repository.rebase_active_for_split("605507.SH", 1.4, event_time)

    assert len(rebased) == 1
    assert rebased[0].version == 3
    assert rebased[0].parent_version == 2
    assert rebased[0].status == PlanStatus.ACTIVE
    assert rebased[0].protective_stop == pytest.approx(15.0)
    assert len(events.read_all(verify=True)) == 3
