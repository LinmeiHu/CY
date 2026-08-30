#!/usr/bin/env python3
"""Clean H-022 execution after the frozen block-diagnostic type failure."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_day5_market_stock_decomposition as base  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-D5D-002_spec.json"
OUTPUT_TABLE = WORK / "artifacts/day5_market_stock_decomposition_v2.csv"
OUTPUT_JSON = WORK / "artifacts/day5_market_stock_decomposition_v2.json"
REPORT = WORK / "reports/day5_market_stock_decomposition_v2.md"
EVIDENCE_PACKET = WORK / "reports/day5_market_stock_decomposition_v2_evidence_packet.md"


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-D5D-002":
        raise base.DecompositionError("unexpected clean-execution identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_VALID_COMPONENT_OUTCOME_TEST":
        raise base.DecompositionError("clean experiment is not frozen before results")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        actual = base.sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.DecompositionError(f"clean frozen input mismatch: {mismatches}")
    return spec, identities


def block_rho_values(blocks: dict[str, dict[str, Any]]) -> list[float]:
    """Extract the intended rho scalar from each rank-association packet."""

    values: list[float] = []
    for block, packet in blocks.items():
        if not isinstance(packet, dict) or "rho" not in packet:
            raise base.DecompositionError(f"invalid block packet: {block}")
        rho = packet["rho"]
        if rho is None:
            raise base.DecompositionError(f"missing block rho: {block}")
        values.append(float(rho))
    return values


def analyze(frame: pd.DataFrame, accepted_result: dict[str, Any]) -> dict[str, Any]:
    """Execute the byte-equivalent H-022 science with the scalar block fix."""

    endpoint = "extreme_winner"
    stock = "stock_specific_day5_excess"
    market = "market_day5_log_return"
    stock_raw = wla.rank_association(frame, stock, endpoint)
    stock_controlled = base.controlled_loyo(
        frame, stock, endpoint, extra_controls=(market,)
    )
    market_raw = wla.rank_association(frame, market, endpoint)
    market_controlled = base.controlled_loyo(
        frame, market, endpoint, extra_controls=(stock,)
    )
    beta_raw = wla.rank_association(frame, "beta_adjusted_day5_excess", endpoint)
    beta_controlled = base.controlled_loyo(
        frame, "beta_adjusted_day5_excess", endpoint, extra_controls=(market,)
    )
    simple = wla.rank_association(frame, "simple_day5_excess", endpoint)
    total = wla.rank_association(frame, "return_5d", endpoint)
    accepted_total = accepted_result["primary"]["raw"]
    if abs(float(total["rho"]) - float(accepted_total["rho"])) > 1e-15:
        raise base.DecompositionError("accepted H-013 day-5 association did not reproduce")

    duration_exit = base.partial_rank(
        frame,
        stock,
        endpoint,
        extra_controls=(market, "holding_trading_days"),
        category_controls=("entry_year", "canonical_exit_reason"),
    )
    top4 = wla.deterministic_top_flag(frame, 4)
    ex_top4 = wla.rank_association(frame.loc[~top4], stock, endpoint)
    securities = sorted(frame.loc[frame.extreme_winner, "symbol"].astype(str).unique())
    security = wla.omit_group_sensitivity(
        frame, stock, endpoint, "symbol", securities
    )
    industry = wla.omit_group_sensitivity(
        frame[frame.entry_industry.notna()], stock, endpoint, "entry_industry"
    )
    blocks = {
        str(name): wla.safe_spearman(rows[stock], rows[endpoint])
        for name, rows in frame.groupby("baseline_block", sort=True)
    }

    stock_raw_gate = bool(
        stock_raw["rho"] is not None
        and stock_raw["rho"] >= 0.20
        and stock_raw["within_year_rank_rho"] is not None
        and stock_raw["within_year_rank_rho"] > 0
        and stock_raw["loyo_positive_count"] >= 7
    )
    stock_controlled_gate = bool(
        stock_controlled["partial_rank_rho"] is not None
        and stock_controlled["partial_rank_rho"] >= 0.20
        and stock_controlled["loyo_positive_count"] >= 7
    )
    market_gate = bool(
        market_raw["rho"] is not None
        and market_raw["rho"] >= 0.10
        and market_raw["loyo_positive_count"] >= 7
        and market_controlled["partial_rank_rho"] is not None
        and market_controlled["partial_rank_rho"] >= 0.10
        and market_controlled["loyo_positive_count"] >= 7
    )
    neighbor_gate = bool(
        beta_raw["rho"] is not None
        and beta_raw["rho"] >= 0.15
        and beta_raw["loyo_positive_count"] >= 6
        and beta_controlled["partial_rank_rho"] is not None
        and beta_controlled["partial_rank_rho"] >= 0.15
        and beta_controlled["loyo_positive_count"] >= 6
        and simple["rho"] is not None
        and simple["rho"] > 0
        and simple["loyo_positive_count"] >= 6
    )
    block_values = block_rho_values(blocks)
    temporal_gate = bool(
        len(block_values) == 3
        and sum(value > 0 for value in block_values) >= 2
        and min(block_values) >= -0.05
    )
    falsification_gate = bool(
        ex_top4["rho"] is not None
        and ex_top4["rho"] > 0
        and duration_exit["partial_rank_rho"] is not None
        and duration_exit["partial_rank_rho"] >= 0.10
        and security["positive_fraction"] is not None
        and security["positive_fraction"] >= 0.80
        and industry["positive_fraction"] is not None
        and industry["positive_fraction"] >= 0.80
    )

    stock_core = stock_raw_gate and stock_controlled_gate
    stock_full = stock_core and neighbor_gate and temporal_gate and falsification_gate
    if stock_full and not market_gate:
        decision = "DEEPEN"
        verdict = "DAY5_SEPARATION_IS_PRIMARILY_STOCK_SPECIFIC"
    elif stock_full and market_gate:
        decision = "REFINE"
        verdict = "DAY5_SEPARATION_HAS_STOCK_SPECIFIC_AND_MARKET_COMPONENTS"
    elif stock_core:
        decision = "REFINE"
        verdict = "STOCK_SPECIFIC_COMPONENT_SURVIVES_CORE_BUT_NOT_FULL_FALSIFICATION"
    elif market_gate:
        decision = "PIVOT"
        verdict = "DAY5_SEPARATION_IS_PRIMARILY_CONTEMPORANEOUS_MARKET_DRIVEN"
    elif stock_raw_gate:
        decision = "PIVOT"
        verdict = "RAW_STOCK_SPECIFIC_COMPONENT_IS_REDUNDANT_OR_UNSTABLE"
    else:
        decision = "REJECT"
        verdict = "NO_STABLE_MARKET_OR_STOCK_SPECIFIC_DAY5_COMPONENT"

    return {
        "experiment_id": "EXP-D5D-002",
        "decision": decision,
        "mechanism_verdict": verdict,
        "primary": {
            "stock_specific_raw": stock_raw,
            "stock_specific_controlled": stock_controlled,
            "market_raw": market_raw,
            "market_controlled": market_controlled,
            "beta_adjusted_raw": beta_raw,
            "beta_adjusted_controlled": beta_controlled,
            "simple_excess_neighbor": simple,
            "accepted_total_return_benchmark": total,
            "duration_exit_control": duration_exit,
            "ex_top4_pnl": ex_top4,
            "leave_one_extreme_security_out": security,
            "leave_one_industry_out": industry,
            "blocks": blocks,
            "stock_raw_gate": stock_raw_gate,
            "stock_controlled_gate": stock_controlled_gate,
            "market_gate": market_gate,
            "neighbor_gate": neighbor_gate,
            "temporal_gate": temporal_gate,
            "falsification_gate": falsification_gate,
        },
        "secondary": {
            endpoint_name: wla.rank_association(frame, stock, endpoint_name)
            for endpoint_name in (
                "winner20",
                "false_breakout",
                "severe_loss",
                "mfe",
                "round_trip_return",
            )
        },
        "strategy_modification": "NONE",
        "interpretation_boundary": (
            "Both components use post-entry information through the fifth held "
            "session and overlap arithmetically with the terminal outcome; the "
            "experiment explains H-013 but authorizes no entry, hold, or exit action"
        ),
    }


def main() -> int:
    spec, identities = validate_spec()
    accepted_result = json.loads(base.ACCEPTED_RESULT.read_text(encoding="utf-8"))
    if accepted_result.get("experiment_id") != "EXP-PEL-001":
        raise base.DecompositionError("accepted H-013 result identity changed")
    frame, audit = base.load_frame(spec)
    result = analyze(frame, accepted_result)
    result.update(
        {
            "spec_sha256": base.sha256_file(SPEC),
            "input_identities": identities,
            "audit": audit,
            "evidence_grade": "EXPLORATORY_HOLDING_PATH_COMPONENT_ATTRIBUTION",
            "breadth_h004_status": "PROSPECTIVE_VALIDATION_PENDING_FROZEN",
        }
    )
    columns = [
        "trade_id",
        "baseline_block",
        "symbol",
        "entry_execution_date",
        "day5_session_date",
        "entry_year",
        "entry_industry",
        "return_5d",
        "stock_day5_log_return",
        "market_entry_open",
        "market_day5_close",
        "market_day5_log_return",
        "stock_specific_day5_excess",
        "beta_adjusted_day5_excess",
        "market_day5_simple_return",
        "simple_day5_excess",
        "extreme_winner",
        "winner20",
        "false_breakout",
        "severe_loss",
        "mfe",
        "round_trip_return",
        "realized_pnl",
        "holding_trading_days",
        "canonical_exit_reason",
        *base.BASE_CONTROLS,
    ]
    base.atomic_write(
        OUTPUT_TABLE,
        frame[columns].sort_values("trade_id").to_csv(
            index=False, lineterminator="\n", float_format="%.17g"
        ),
    )
    base.atomic_write(
        OUTPUT_JSON, json.dumps(wla.clean_json(result), indent=2, sort_keys=True) + "\n"
    )
    base.atomic_write(
        REPORT,
        base.build_report(result, audit).replace("EXP-D5D-001", "EXP-D5D-002"),
    )
    base.atomic_write(
        EVIDENCE_PACKET,
        base.build_evidence_packet(result, audit).replace(
            "EXP-D5D-001", "EXP-D5D-002"
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
