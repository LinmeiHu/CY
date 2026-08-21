from __future__ import annotations

from datetime import date, timedelta

from cyq_game.backtest.walkforward import build_walk_forward


def test_walk_forward_purges_embargoes_and_locks_final_holdout() -> None:
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=index) for index in range(180)]
    plan = build_walk_forward(
        dates,
        final_holdout_fraction=0.20,
        purge_days=5,
        embargo_days=5,
    )
    assert set(plan.development_dates).isdisjoint(plan.final_holdout_dates)
    assert max(plan.development_dates) < min(plan.final_holdout_dates)
    for fold in plan.folds:
        assert set(fold.train_dates).isdisjoint(fold.test_dates)
        assert len(fold.purge_dates) == 5
        assert len(fold.embargo_dates) <= 5
        assert max(fold.train_dates) < min(fold.test_dates)


def test_final_holdout_fraction_excludes_pre_roll_history() -> None:
    history_start = date(2020, 1, 1)
    evaluation_start = date(2024, 1, 1)
    dates = [history_start + timedelta(days=index) for index in range(1640)]
    evaluation = [item for item in dates if item >= evaluation_start]
    plan = build_walk_forward(
        dates,
        final_holdout_fraction=0.20,
        purge_days=5,
        embargo_days=5,
        evaluation_start=evaluation_start,
    )

    assert len(plan.final_holdout_dates) == round(len(evaluation) * 0.20)
    assert min(plan.final_holdout_dates) >= evaluation_start
    assert min(plan.development_dates) == history_start
