from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class WalkForwardFold:
    fold_id: int
    train_dates: tuple[date, ...]
    purge_dates: tuple[date, ...]
    test_dates: tuple[date, ...]
    embargo_dates: tuple[date, ...]

    def __post_init__(self) -> None:
        if not self.train_dates or not self.test_dates:
            raise ValueError("walk-forward folds need non-empty train and test sets")
        if self.train_dates[-1] >= self.test_dates[0]:
            raise ValueError("training data must precede test data")
        if set(self.train_dates) & set(self.test_dates):
            raise ValueError("train/test leakage")


@dataclass(frozen=True)
class WalkForwardPlan:
    folds: tuple[WalkForwardFold, ...]
    development_dates: tuple[date, ...]
    final_holdout_dates: tuple[date, ...]
    purge_days: int
    embargo_days: int

    def fold_for(self, trade_date: date) -> WalkForwardFold | None:
        return next((fold for fold in self.folds if trade_date in fold.test_dates), None)


def build_walk_forward(
    dates: list[date],
    *,
    final_holdout_fraction: float,
    purge_days: int,
    embargo_days: int,
    evaluation_start: date | None = None,
    minimum_train_days: int = 60,
    test_days: int | None = None,
) -> WalkForwardPlan:
    """Create expanding-window folds and a final holdout from the evaluation slice."""

    unique = sorted(set(dates))
    if not 0.05 <= final_holdout_fraction <= 0.50:
        raise ValueError("final holdout fraction must be in [0.05, 0.50]")
    if purge_days < 0 or embargo_days < 0:
        raise ValueError("purge and embargo must be non-negative")
    if len(unique) < minimum_train_days + purge_days + 20:
        raise ValueError("not enough dates for a leakage-safe walk-forward plan")
    evaluation_start = evaluation_start or unique[0]
    evaluation = [item for item in unique if item >= evaluation_start]
    if len(evaluation) < 2:
        raise ValueError("evaluation slice needs at least two dates")
    holdout_count = max(1, round(len(evaluation) * final_holdout_fraction))
    holdout_start_date = evaluation[-holdout_count]
    holdout_start = unique.index(holdout_start_date)
    development = unique[:holdout_start]
    holdout = unique[holdout_start:]
    available_after_train = len(development) - minimum_train_days - purge_days
    block = test_days or max(20, available_after_train // 3)
    folds: list[WalkForwardFold] = []
    test_start = minimum_train_days + purge_days
    while test_start < len(development):
        train_end = test_start - purge_days
        test_end = min(len(development), test_start + block)
        if train_end < minimum_train_days:
            break
        embargo_end = min(len(development), test_end + embargo_days)
        folds.append(
            WalkForwardFold(
                fold_id=len(folds) + 1,
                train_dates=tuple(development[:train_end]),
                purge_dates=tuple(development[train_end:test_start]),
                test_dates=tuple(development[test_start:test_end]),
                embargo_dates=tuple(development[test_end:embargo_end]),
            )
        )
        test_start = embargo_end + purge_days
    if not folds:
        raise ValueError("walk-forward plan produced no folds")
    return WalkForwardPlan(
        folds=tuple(folds),
        development_dates=tuple(development),
        final_holdout_dates=tuple(holdout),
        purge_days=purge_days,
        embargo_days=embargo_days,
    )
