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
    rs_floor: float = RS_CROSS_SECTIONAL_MEDIAN

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


POLICIES = {
    "V2_R120_MEDIAN": V2EntryPolicy("V2_R120_MEDIAN", ("r120",)),
    "V2_ALL_HORIZON_MEDIAN": V2EntryPolicy(
        "V2_ALL_HORIZON_MEDIAN", ("r20", "r60", "r120")
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
        if parsed[horizon] < policy.rs_floor
    ]
    return {
        "valid": True,
        "passed": not failed,
        "failed_horizons": failed,
        "reason": "PASS" if not failed else "BELOW_CROSS_SECTIONAL_MEDIAN",
    }
