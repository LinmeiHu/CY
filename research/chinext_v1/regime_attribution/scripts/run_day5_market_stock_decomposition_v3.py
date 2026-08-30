#!/usr/bin/env python3
"""Final clean H-022 execution with non-estimable blocks failing the gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
if str(WORK / "scripts") not in sys.path:
    sys.path.insert(0, str(WORK / "scripts"))

import run_day5_market_stock_decomposition as base  # noqa: E402
import run_day5_market_stock_decomposition_v2 as clean_v2  # noqa: E402
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC = WORK / "experiments/EXP-D5D-003_spec.json"
OUTPUT_TABLE = WORK / "artifacts/day5_market_stock_decomposition_v3.csv"
OUTPUT_JSON = WORK / "artifacts/day5_market_stock_decomposition_v3.json"
REPORT = WORK / "reports/day5_market_stock_decomposition_v3.md"
EVIDENCE_PACKET = WORK / "reports/day5_market_stock_decomposition_v3_evidence_packet.md"


def validate_spec() -> tuple[dict[str, Any], dict[str, str]]:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("experiment_id") != "EXP-D5D-003":
        raise base.DecompositionError("unexpected final clean-execution identity")
    if spec.get("status") != "FROZEN_BEFORE_FIRST_VALID_COMPONENT_OUTCOME_TEST":
        raise base.DecompositionError("final clean experiment is not frozen")
    identities: dict[str, str] = {}
    mismatches: dict[str, dict[str, str]] = {}
    for name, binding in spec["input_bindings"].items():
        path = base.resolve_path(binding["path"])
        actual = base.sha256_file(path) if path.is_file() else "MISSING"
        identities[str(path)] = actual
        if actual != binding["sha256"]:
            mismatches[name] = {"expected": binding["sha256"], "actual": actual}
    if mismatches:
        raise base.DecompositionError(f"final clean input mismatch: {mismatches}")
    return spec, identities


def estimable_block_rho_values(blocks: dict[str, dict[str, Any]]) -> list[float]:
    """Return estimable rhos; missing endpoint variation remains non-estimable."""

    values: list[float] = []
    for block, packet in blocks.items():
        if not isinstance(packet, dict) or "rho" not in packet:
            raise base.DecompositionError(f"invalid block packet: {block}")
        rho = packet["rho"]
        if rho is not None:
            values.append(float(rho))
    return values


def analyze(frame: Any, accepted_result: dict[str, Any]) -> dict[str, Any]:
    """Reuse exact D5D-002 science with only the non-estimable-block handling."""

    original = clean_v2.block_rho_values
    clean_v2.block_rho_values = estimable_block_rho_values
    try:
        result = clean_v2.analyze(frame, accepted_result)
    finally:
        clean_v2.block_rho_values = original
    result["experiment_id"] = "EXP-D5D-003"
    result["primary"]["non_estimable_block_policy"] = (
        "A block with no endpoint variation has rho=None, is excluded from "
        "estimable values, and therefore fails the unchanged len==3 temporal gate"
    )
    return result


def main() -> int:
    spec, identities = validate_spec()
    accepted_result = json.loads(base.ACCEPTED_RESULT.read_text(encoding="utf-8"))
    if accepted_result.get("experiment_id") != "EXP-PEL-001":
        raise base.DecompositionError("accepted H-013 result identity changed")
    frame, audit = base.load_frame(spec)
    block_endpoint_counts = {
        str(name): {
            "rows": int(len(rows)),
            "extreme_winners": int(rows.extreme_winner.sum()),
            "endpoint_levels": int(rows.extreme_winner.nunique()),
        }
        for name, rows in frame.groupby("baseline_block", sort=True)
    }
    expected_counts = spec["block_endpoint_counts"]
    if block_endpoint_counts != expected_counts:
        raise base.DecompositionError(
            f"block endpoint availability changed: {block_endpoint_counts}"
        )
    audit["block_endpoint_counts"] = block_endpoint_counts
    audit["non_estimable_blocks"] = [
        name for name, item in block_endpoint_counts.items() if item["endpoint_levels"] < 2
    ]
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
    report = base.build_report(result, audit).replace("EXP-D5D-001", "EXP-D5D-003")
    report += (
        "\nThe HOLDOUT block contains zero extreme winners, so its block rho is "
        "non-estimable and the frozen three-block temporal gate fails.\n"
    )
    base.atomic_write(REPORT, report)
    packet = base.build_evidence_packet(result, audit).replace(
        "EXP-D5D-001", "EXP-D5D-003"
    )
    packet += (
        "\nThe HOLDOUT block has no endpoint variation; this is recorded as a "
        "failed temporal gate, not imputed or omitted evidence.\n"
    )
    base.atomic_write(EVIDENCE_PACKET, packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
