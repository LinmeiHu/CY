"""Minimal, bounded ChinNext V2 entry policies for 2018-2021 mechanism research."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from math import isfinite
from typing import Any

PARENT_V1_STRATEGY_SHA256 = (
    "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
)
RS_CROSS_SECTIONAL_MEDIAN = 0.50


@dataclass(frozen=True)
class V2EntryPolicy:
    name: str
    required_rs_horizons: tuple[str, ...]
    rs_floor: float | None = None
    close_loss_budget: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


POLICIES = {
    "V2_R120_MEDIAN": V2EntryPolicy(
        "V2_R120_MEDIAN", ("r120",), rs_floor=RS_CROSS_SECTIONAL_MEDIAN
    ),
    "V2_ALL_HORIZON_MEDIAN": V2EntryPolicy(
        "V2_ALL_HORIZON_MEDIAN",
        ("r20", "r60", "r120"),
        rs_floor=RS_CROSS_SECTIONAL_MEDIAN,
    ),
    "V2_LOSS_BUDGET_10": V2EntryPolicy(
        "V2_LOSS_BUDGET_10", (), close_loss_budget=-0.10
    ),
}


def policy_for(name: str) -> V2EntryPolicy:
    try:
        return POLICIES[name]
    except KeyError as exc:
        raise ValueError(f"unregistered ChinNext V2 candidate: {name}") from exc


def evaluate_rs_admission(
    rs: Mapping[str, float] | None,
    policy: V2EntryPolicy,
) -> dict[str, Any]:
    """Fail closed unless every preregistered RS horizon is finite and at/above median."""

    if rs is None:
        return {
            "valid": False,
            "passed": False,
            "failed_horizons": list(policy.required_rs_horizons),
            "reason": "MISSING_RS_ROW",
        }
    if policy.required_rs_horizons and policy.rs_floor is None:
        return {
            "valid": False,
            "passed": False,
            "failed_horizons": list(policy.required_rs_horizons),
            "reason": "MISSING_RS_FLOOR",
        }
    parsed: dict[str, float] = {}
    missing: list[str] = []
    for horizon in policy.required_rs_horizons:
        try:
            value = float(rs[horizon])
        except (KeyError, TypeError, ValueError):
            missing.append(horizon)
            continue
        if not isfinite(value):
            missing.append(horizon)
            continue
        parsed[horizon] = value
    if missing:
        return {
            "valid": False,
            "passed": False,
            "failed_horizons": missing,
            "reason": "MISSING_OR_NONFINITE_REQUIRED_HORIZON",
        }
    failed = [
        horizon
        for horizon in policy.required_rs_horizons
        if parsed[horizon] < float(policy.rs_floor)
    ]
    return {
        "valid": True,
        "passed": not failed,
        "failed_horizons": failed,
        "reason": "PASS" if not failed else "BELOW_CROSS_SECTIONAL_MEDIAN",
    }


def evaluate_loss_budget(
    *,
    shares: float,
    remaining_cost_basis: float,
    remaining_dividends: float,
    cycle_buy_cost: float,
    cycle_realized_pnl: float,
    close: float,
    policy: V2EntryPolicy,
) -> dict[str, Any]:
    """Mark the whole existing cycle at a completed close, including prior ledger cash flows."""

    if policy.close_loss_budget is None:
        return {
            "valid": True,
            "triggered": False,
            "cycle_mark_return": None,
            "reason": "NOT_APPLICABLE",
        }
    values = (
        shares,
        remaining_cost_basis,
        remaining_dividends,
        cycle_buy_cost,
        cycle_realized_pnl,
        close,
    )
    if not all(isfinite(float(value)) for value in values):
        return {
            "valid": False,
            "triggered": False,
            "cycle_mark_return": None,
            "reason": "NONFINITE_POSITION_LEDGER_OR_CLOSE",
        }
    if shares <= 0 or remaining_cost_basis < 0 or cycle_buy_cost <= 0 or close <= 0:
        return {
            "valid": False,
            "triggered": False,
            "cycle_mark_return": None,
            "reason": "INVALID_POSITION_LEDGER_OR_CLOSE",
        }
    marked_pnl = (
        cycle_realized_pnl
        + remaining_dividends
        + shares * close
        - remaining_cost_basis
    )
    cycle_mark_return = marked_pnl / cycle_buy_cost
    triggered = cycle_mark_return <= policy.close_loss_budget
    return {
        "valid": True,
        "triggered": triggered,
        "cycle_mark_return": cycle_mark_return,
        "reason": "LOSS_BUDGET_REACHED" if triggered else "ABOVE_LOSS_BUDGET",
    }
