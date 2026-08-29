"""Frozen Phase 3 single-module ablation controls for the existing replay engine."""

from __future__ import annotations

import hashlib
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

CHINEXT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CHINEXT_ROOT))

from strategy.chinext_v1_exploratory import (
    ChinNextV1Config,
    Full40Diagnostic,
    MinVolDiagnostic,
    close_above_ma,
    full40_diagnostic,
    sort_candidates,
    strict_breakout,
)

NO_RS_DOMAIN = "CHINEXT_V1_PHASE3_NO_RS_V1"
ARM_ORDER = (
    "A0_BASELINE",
    "A1_MINUS_MINVOL",
    "A2_MINUS_B60",
    "A3_MINUS_FULL40",
    "A4_NO_RS_SELECTION_CONTROL",
    "A5_MINUS_MARKET_ENTRY_GATE",
)


@dataclass(frozen=True)
class ArmPolicy:
    name: str
    minvol_hard_filter: bool = True
    b60_hard_filter: bool = True
    full40_hard_filter: bool = True
    rs_selection: bool = True
    market_entry_gate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Phase7ExitPolicy(ArmPolicy):
    individual_exit: bool = True
    market_exit: bool = True


def phase7_policy_for(name: str) -> Phase7ExitPolicy:
    if name == "E1_INDIVIDUAL_EXIT_DISABLED":
        return Phase7ExitPolicy(name, individual_exit=False)
    if name == "E2_MARKET_EXIT_DISABLED":
        return Phase7ExitPolicy(name, market_exit=False)
    raise ValueError(f"unregistered Phase 7 exit arm: {name}")


def phase8_policy_for(name: str) -> Phase7ExitPolicy:
    if name == "W1_WINNER_HOLD_THROUGH_MARKET_EXIT":
        return Phase7ExitPolicy(name)
    raise ValueError(f"unregistered Phase 8 exit arm: {name}")


POLICIES = {
    "A0_BASELINE": ArmPolicy("A0_BASELINE"),
    "A1_MINUS_MINVOL": ArmPolicy("A1_MINUS_MINVOL", minvol_hard_filter=False),
    "A2_MINUS_B60": ArmPolicy("A2_MINUS_B60", b60_hard_filter=False),
    "A3_MINUS_FULL40": ArmPolicy("A3_MINUS_FULL40", full40_hard_filter=False),
    "A4_NO_RS_SELECTION_CONTROL": ArmPolicy(
        "A4_NO_RS_SELECTION_CONTROL", rs_selection=False
    ),
    "A5_MINUS_MARKET_ENTRY_GATE": ArmPolicy(
        "A5_MINUS_MARKET_ENTRY_GATE", market_entry_gate=False
    ),
}


def policy_for(name: str) -> ArmPolicy:
    try:
        return POLICIES[name]
    except KeyError as exc:
        raise ValueError(f"unregistered Phase 3 ablation arm: {name}") from exc


def price_structure_for_arm(
    closes: Sequence[float], config: ChinNextV1Config, policy: ArmPolicy
) -> tuple[bool, Full40Diagnostic, dict[str, bool]]:
    b60_passed = strict_breakout(closes, config.breakout_days)
    entry_ma_passed = close_above_ma(closes, config.entry_ma)
    full = full40_diagnostic(closes, config)
    passed = (
        (b60_passed or not policy.b60_hard_filter)
        and entry_ma_passed
        and (full.passed or not policy.full40_hard_filter)
    )
    return passed, full, {
        "b60_diagnostic_passed": b60_passed,
        "entry_ma_passed": entry_ma_passed,
        "full40_diagnostic_passed": full.passed,
        "b60_hard_filter_active": policy.b60_hard_filter,
        "full40_hard_filter_active": policy.full40_hard_filter,
    }


def minvol_admission_for_arm(minimum: MinVolDiagnostic, policy: ArmPolicy) -> bool:
    return minimum.passed or not policy.minvol_hard_filter


def no_rs_priority_key(signal_date: date, normalized_symbol: str) -> str:
    preimage = f"{NO_RS_DOMAIN}|{signal_date.isoformat()}|{normalized_symbol}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def rank_candidates_for_arm(
    candidates: Iterable[str],
    rs: Mapping[str, Mapping[str, float]],
    signal_date: date,
    policy: ArmPolicy,
) -> list[str]:
    available = {symbol for symbol in candidates if symbol in rs}
    if policy.rs_selection:
        return sort_candidates(available, rs)
    return sorted(available, key=lambda symbol: no_rs_priority_key(signal_date, symbol))


def market_entry_allowed_for_arm(
    market_state: Mapping[str, bool], policy: ArmPolicy
) -> bool:
    if not policy.market_entry_gate:
        return True
    return bool(market_state["valid"] and market_state["entry_permission"])
