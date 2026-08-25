#!/usr/bin/env python3
"""Validate a fixed week directly from persisted chip operators."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime
from datetime import time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cyq_game.chip.ensemble_v2 import SELLER_MODEL_ORDER  # noqa: E402
from cyq_game.chip.state_v2 import SellerModel, tolerance  # noqa: E402
from cyq_game.strategy.chip_lineage import (  # noqa: E402
    PersistedChipLineageResolver,
)
from cyq_game.strategy.markup_retest import (  # noqa: E402
    ChipMassMethod,
    ChipMassProfile,
    LifecycleAnchor,
    LifecycleObservation,
)

TZ = ZoneInfo("Asia/Shanghai")
INITIAL_DATE = date(2020, 6, 12)
START_DATE = date(2020, 6, 15)
END_DATE = date(2020, 6, 19)
EXPECTED_DATES = (
    INITIAL_DATE,
    START_DATE,
    date(2020, 6, 16),
    date(2020, 6, 17),
    date(2020, 6, 18),
    END_DATE,
)
PERSISTED_ROOT = ROOT / "data/processed/benchmark_chip_000001_v11_20260823/year=2020"
OUTPUT_PATH = ROOT / "output/real_chip_week_validation_000001_v11.json"
STORAGE_VERSION = "chip-operator-log-v11"
CORPORATE_ACTION_CASE = "002030.SZ"
CORPORATE_ACTION_DATE = date(2020, 6, 18)
WEEK_SYMBOLS = (
    "000001.SZ",
    "000006.SZ",
    "000029.SZ",
    "000572.SZ",
    "000670.SZ",
    "000687.SZ",
    "000760.SZ",
    "000792.SZ",
    "000906.SZ",
    "000927.SZ",
    "002030.SZ",
    "002649.SZ",
    "300015.SZ",
    "300165.SZ",
    "300750.SZ",
    "600000.SH",
    "600511.SH",
    "600519.SH",
    "603222.SH",
    "601318.SH",
)
SYMBOLS = ("000001.SZ",)


def _aware(day: date) -> datetime:
    return datetime.combine(day, clock_time(15, 30), tzinfo=TZ)


def _path(symbol: str, persisted_root: Path) -> Path:
    filename = f"{symbol.replace('.', '_')}.parquet"
    matches = tuple(persisted_root.glob(f"parts/bucket=*/{filename}"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one persisted file for {symbol}, found {len(matches)}")
    return matches[0]


def _selected_validity(row: dict[str, Any], validity_mode: str) -> bool:
    if validity_mode == "strict":
        return bool(row["hard_valid"])
    if validity_mode == "research":
        return bool(row.get("research_valid", row["hard_valid"]))
    raise ValueError(f"unsupported validity mode: {validity_mode}")


def _validity_summary(rows: list[dict[str, Any]], validity_mode: str) -> dict[str, Any]:
    """Keep diagnostic tags separate from rows blocked by a validity contract."""
    diagnostic_tags = Counter(
        code for row in rows for code in row.get("quality_reason_codes", ())
    )
    research_blocking_tags = Counter(
        code
        for row in rows
        if not bool(row.get("research_valid", row["hard_valid"]))
        for code in row.get("quality_reason_codes", ())
    )
    strict_valid_rows = sum(bool(row["hard_valid"]) for row in rows)
    research_valid_rows = sum(
        bool(row.get("research_valid", row["hard_valid"])) for row in rows
    )
    return {
        "mode": validity_mode,
        "rows": len(rows),
        "strict_valid_rows": strict_valid_rows,
        "strict_invalid_rows": len(rows) - strict_valid_rows,
        "research_valid_rows": research_valid_rows,
        "research_invalid_rows": len(rows) - research_valid_rows,
        "diagnostic_tag_rows": dict(sorted(diagnostic_tags.items())),
        "research_blocking_tag_rows": dict(sorted(research_blocking_tags.items())),
    }


def _observation(
    symbol: str,
    row: dict[str, Any],
    validity_mode: str,
) -> LifecycleObservation:
    price = float(row["cost_p50"])
    return LifecycleObservation(
        symbol=symbol,
        decision_at=_aware(END_DATE),
        available_at=_aware(END_DATE),
        snapshot_ids=(str(row["snapshot_id"]),),
        # LifecycleMachine deliberately has one fail-closed validity input.
        # The adapter chooses the declared research/strict contract; it does
        # not relabel the persisted strict field.
        hard_valid=_selected_validity(row, validity_mode),
        tradable=True,
        pit_grade="B_RESEARCH_ONLY",
        setup_score=0.0,
        breakout_excess_atr=0.0,
        support_regained=False,
        chip_profile=ChipMassProfile.from_histogram(
            (price,),
            (1.0,),
            mass_tolerance=1e-12,
        ),
        cost_p10=float(row["cost_p10"]),
        cost_p90=float(row["cost_p90"]),
        peak_count=1,
        recent_band_overlap=0.0,
        distribution_score=0.0,
        structure_support=float(row["cost_p10"]),
        close=price,
        low=price,
        volume=0.0,
        turnover=0.0,
        average_cost=float(row["average_cost"]),
        cost_p50=price,
        main_peak=float(row["main_peak"]),
        prior_average_cost=float(row["average_cost"]),
        prior_cost_p50=price,
        prior_main_peak=float(row["main_peak"]),
        atr=max(price * 0.01, 0.01),
    )


def _lineage(
    symbol: str,
    rows_by_model: dict[SellerModel, dict[date, dict[str, Any]]],
    persisted_root: Path,
    validity_mode: str,
) -> tuple[bool, str, dict[str, float | None]]:
    anchor_row = rows_by_model[SellerModel.UNIFORM][START_DATE]
    current_row = rows_by_model[SellerModel.UNIFORM][END_DATE]
    if anchor_row["known_cost_fraction"] <= 1e-12:
        unknown_preserved = math.isclose(
            float(anchor_row["unknown_cost_fraction"]), 1.0, abs_tol=1e-12
        )
        return unknown_preserved, "NOT_APPLICABLE_UNKNOWN_COST", {
            "central": None,
            "lower": None,
            "upper": None,
        }
    anchor_id = f"persisted-week:{symbol}:{START_DATE.isoformat()}"
    anchor = LifecycleAnchor(
        anchor_id=anchor_id,
        symbol=symbol,
        source_snapshot_id=str(anchor_row["snapshot_id"]),
        root_anchor_id=anchor_id,
        parent_anchor_id=None,
        role="ROOT",
        created_at=START_DATE,
        lower=float(anchor_row["cost_p10"]),
        upper=float(anchor_row["cost_p90"]),
        reference_mass=float(anchor_row["known_cost_fraction"]),
        average_cost=float(anchor_row["average_cost"]),
        cost_p50=float(anchor_row["cost_p50"]),
        main_peak=float(anchor_row["main_peak"]),
        band_width=float(anchor_row["cost_p90"] - anchor_row["cost_p10"]),
        peak_count=1,
        mass_method=ChipMassMethod.HISTOGRAM_EXACT,
    )
    estimate = PersistedChipLineageResolver(persisted_root)(
        anchor, _observation(symbol, current_row, validity_mode)
    )
    if estimate is None:
        return False, "MISSING", {"central": None, "lower": None, "upper": None}
    passed = 0.0 <= estimate.lower <= estimate.central <= estimate.upper <= 1.0
    return passed, "TRACKED", {
        "central": estimate.central,
        "lower": estimate.lower,
        "upper": estimate.upper,
    }


def _run_symbol(payload: tuple[str, str, str]) -> dict[str, Any]:
    symbol, persisted_root_value, validity_mode = payload
    persisted_root = Path(persisted_root_value)
    try:
        path = _path(symbol, persisted_root)
        rows = [
            row
            for row in pq.read_table(path).to_pylist()
            if INITIAL_DATE <= row["trade_date"] <= END_DATE
        ]
        if len(rows) != len(EXPECTED_DATES) * len(SELLER_MODEL_ORDER):
            raise ValueError(f"expected 18 persisted rows, found {len(rows)}")
        if {row["storage_version"] for row in rows} != {STORAGE_VERSION}:
            raise ValueError("unexpected storage version")
        rows_by_model = {
            model: {
                row["trade_date"]: row
                for row in rows
                if row["seller_model"] == model.value
            }
            for model in SELLER_MODEL_ORDER
        }
        if any(tuple(sorted(items)) != EXPECTED_DATES for items in rows_by_model.values()):
            raise ValueError("persisted rows do not cover the fixed six dates")

        max_mass_error = max(abs(float(row["conservation_error_shares"])) for row in rows)
        mass_pass = all(
            abs(float(row["conservation_error_shares"]))
            <= tolerance(float(row["free_float_shares"]))
            for row in rows
        )
        max_same_day_resale = max(abs(float(row["same_day_resale_shares"])) for row in rows)
        t1_pass = all(
            abs(float(row["same_day_resale_shares"]))
            <= tolerance(float(row["fixed_pre_eligible_shares"]))
            for row in rows
        )
        unknown_pass = all(
            0.0 <= float(row["known_cost_fraction"]) <= 1.0
            and 0.0 <= float(row["unknown_cost_fraction"]) <= 1.0
            and math.isclose(
                float(row["known_cost_fraction"]) + float(row["unknown_cost_fraction"]),
                1.0,
                abs_tol=1e-9,
            )
            for row in rows
        )
        real_minute_pass = not any(bool(row["minute_fallback"]) for row in rows)
        lineage_pass, lineage_mode, lineage_values = _lineage(
            symbol, rows_by_model, persisted_root, validity_mode
        )
        selected_validity_pass = all(
            _selected_validity(row, validity_mode) for row in rows
        )
        validity = _validity_summary(rows, validity_mode)

        action_pass = True
        action_evidence: dict[str, Any] | None = None
        if symbol == CORPORATE_ACTION_CASE:
            uniform = rows_by_model[SellerModel.UNIFORM]
            before = float(uniform[date(2020, 6, 17)]["free_float_shares"])
            after_row = uniform[CORPORATE_ACTION_DATE]
            after = float(after_row["free_float_shares"])
            adjustment = math.fsum(float(x) for x in after_row["inventory_adjustment_shares"])
            action_pass = after > before and adjustment > 0 and mass_pass
            action_evidence = {
                "date": CORPORATE_ACTION_DATE.isoformat(),
                "float_before": before,
                "float_after": after,
                "operator_adjustment_shares": adjustment,
            }

        checks = {
            "persisted_dates": True,
            "real_minute": real_minute_pass,
            "t1": t1_pass,
            "mass": mass_pass,
            "unknown_cost": unknown_pass,
            "selected_validity": selected_validity_pass,
            "lineage": lineage_pass,
            "corporate_action": action_pass,
        }
        return {
            "symbol": symbol,
            "status": "PASS" if all(checks.values()) else "FAIL",
            "path": str(path),
            "checks": checks,
            "max_same_day_resale_shares": max_same_day_resale,
            "max_abs_mass_error_shares": max_mass_error,
            "validity": validity,
            "lineage": {"mode": lineage_mode, **lineage_values},
            "corporate_action": action_evidence,
        }
    except Exception as error:
        return {"symbol": symbol, "status": "FAIL", "error": f"{type(error).__name__}: {error}"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=PERSISTED_ROOT)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--symbols",
        default=",".join(SYMBOLS),
        help="comma-separated symbols; use 'week20' for the fixed 20-stock set",
    )
    parser.add_argument(
        "--validity-mode",
        choices=("research", "strict"),
        default="research",
    )
    args = parser.parse_args()
    started = time.perf_counter()
    symbols = (
        WEEK_SYMBOLS
        if args.symbols == "week20"
        else tuple(item.strip() for item in args.symbols.split(",") if item.strip())
    )
    if not symbols:
        parser.error("at least one symbol is required")
    payloads = tuple(
        (symbol, str(args.input), args.validity_mode) for symbol in symbols
    )
    if args.workers == 1:
        results = [_run_symbol(payload) for payload in payloads]
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as executor:
            results = list(executor.map(_run_symbol, payloads))
    results.sort(key=lambda item: item["symbol"])
    check_names = (
        "persisted_dates",
        "real_minute",
        "t1",
        "mass",
        "unknown_cost",
        "selected_validity",
        "lineage",
        "corporate_action",
    )
    checks = {
        name: all(item.get("checks", {}).get(name, False) for item in results)
        for name in check_names
    }
    passed = all(checks.values()) and all(item["status"] == "PASS" for item in results)
    evidence = {
        "status": "PASS" if passed else "FAIL",
        "period": [START_DATE.isoformat(), END_DATE.isoformat()],
        "input": str(args.input),
        "storage_version": STORAGE_VERSION,
        "workers": args.workers,
        "validity_mode": args.validity_mode,
        "symbols": len(symbols),
        "checks": checks,
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {key: evidence[key] for key in ("status", "checks", "elapsed_seconds")},
            ensure_ascii=False,
        )
    )
    print(args.output)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
