#!/usr/bin/env python3
"""Build the frozen 399-cycle opportunity-to-P&L conversion panel."""

from __future__ import annotations

import csv
import importlib.util
import json
import math
import statistics
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/opportunity_conversion"
PRIOR = ROOT / "research/chinext_v1/regime_attribution"
PRIOR_SCRIPT = PRIOR / "scripts/run_phase1_yearly_decomposition.py"
YEARLY_TRADES = PRIOR / "artifacts/yearly_trades.csv"
MECHANISM = PRIOR / "artifacts/trade_mechanism_attribution.csv"
FEATURES = PRIOR / "artifacts/daily_regime_features.parquet"
OUTPUT_PANEL = WORK / "artifacts/trade_conversion_panel.csv"
OUTPUT_PATH = WORK / "artifacts/trade_holding_path.csv"
OUTPUT_MANIFEST = WORK / "artifacts/phase1_conversion_manifest.json"
REPORT = WORK / "reports/phase1_conversion_panel.md"

EXPECTED_YEARLY_SHA256 = (
    "77f28da56a3e36801373b0b356a6e36236095b17dbdb3183a8b1b0a4c8ab3deb"
)
EXPECTED_MECHANISM_SHA256 = (
    "2b026a4117b3b6a257085d46f2048657cbbf95df963198979f72152ef16d6b41"
)
EXPECTED_FEATURE_SHA256 = (
    "5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6"
)


def load_prior_module() -> Any:
    spec = importlib.util.spec_from_file_location("frozen_phase1", PRIOR_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen Phase 1 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def same_float(actual: Any, expected: Any, tolerance: float = 1e-12) -> bool:
    if actual in (None, "") and expected in (None, ""):
        return True
    if actual in (None, "") or expected in (None, ""):
        return False
    return math.isclose(
        float(actual), float(expected), rel_tol=tolerance, abs_tol=tolerance
    )


def terminal_class(value: float) -> str:
    if value >= 0.50:
        return "EXTREME_WINNER"
    if value >= 0.20:
        return "RIGHT_TAIL_WINNER"
    if value > 0.02:
        return "ORDINARY_WINNER"
    if value >= -0.02:
        return "FLAT"
    if value > -0.10:
        return "SMALL_LOSER"
    return "SEVERE_LOSER"


def path_descriptors(
    path: list[dict[str, Any]], days_to_mfe: int, terminal_return: float
) -> dict[str, Any]:
    if not path:
        raise RuntimeError("empty holding path")
    close = [float(row["close_return"]) for row in path]
    low = [float(row["low_return"]) for row in path]
    peak_offset = max(range(len(close)), key=lambda index: close[index])
    pre_peak = close[: peak_offset + 1]
    pre_peak_changes = [
        pre_peak[index] - pre_peak[index - 1]
        for index in range(1, len(pre_peak))
    ]
    variation = sum(abs(value) for value in pre_peak_changes)
    efficiency = (
        abs(pre_peak[-1] - pre_peak[0]) / variation if variation > 0 else 0.0
    )
    running_peak = 1.0 + pre_peak[0]
    drawdowns: list[float] = []
    for value in pre_peak:
        wealth = 1.0 + value
        running_peak = max(running_peak, wealth)
        drawdowns.append(wealth / running_peak - 1.0)
    post_peak_changes = [
        close[index] - close[index - 1]
        for index in range(peak_offset + 1, len(close))
    ]
    peak_close_return = close[peak_offset]
    days_from_peak_to_exit = len(close) - 1 - peak_offset
    return {
        "pre_mfe_mae": min(low[: days_to_mfe + 1]),
        "pre_peak_direction_efficiency": efficiency,
        "pre_peak_positive_day_fraction": (
            sum(value > 0 for value in pre_peak_changes) / len(pre_peak_changes)
            if pre_peak_changes
            else None
        ),
        "pre_peak_max_drawdown": min(drawdowns),
        "post_peak_positive_day_fraction": (
            sum(value > 0 for value in post_peak_changes) / len(post_peak_changes)
            if post_peak_changes
            else None
        ),
        "holding_path_mean_close_return": statistics.fmean(close),
        "peak_close_return": peak_close_return,
        "peak_close_offset": peak_offset,
        "days_from_peak_to_exit": days_from_peak_to_exit,
        "post_peak_close_giveback": peak_close_return - terminal_return,
        "post_peak_decay_rate": (
            (peak_close_return - terminal_return)
            / max(1, days_from_peak_to_exit)
        ),
    }


def build_daily_path(
    prior: Any,
    trade: dict[str, Any],
    sessions: list[str],
    session_index: dict[str, int],
    price_rows: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    start = session_index[trade["entry_execution_date"]]
    end = session_index[trade["exit_execution_date"]]
    entry_price = float(trade["entry_price"])
    share_factor = 1.0
    cash_per_original_share = 0.0
    result: list[dict[str, Any]] = []
    for offset, day in enumerate(sessions[start : end + 1]):
        key = (trade["symbol"], day)
        if key not in price_rows:
            raise RuntimeError(f"missing holding row: {trade['trade_id']} {day}")
        row = price_rows[key]
        if day > trade["entry_execution_date"] and int(
            row.get("corporate_action_count") or 0
        ) > 0:
            valid, multiplier, cash = prior.action_values(row, day)
            if not valid:
                raise RuntimeError(
                    f"unresolved corporate action: {trade['trade_id']} {day}"
                )
            cash_per_original_share += share_factor * cash
            share_factor *= multiplier

        def total_return(price: float) -> float:
            return (
                (share_factor * price + cash_per_original_share) / entry_price - 1.0
            )

        if day == trade["exit_execution_date"]:
            high = low = close = total_return(float(trade["exit_price"]))
            price_source = "ACTUAL_EXIT_EXECUTION"
        else:
            values = (row["high"], row["low"], row["close"])
            if not all(
                value is not None and math.isfinite(float(value)) for value in values
            ):
                raise RuntimeError(f"nonfinite holding path: {trade['trade_id']} {day}")
            high = total_return(float(row["high"]))
            low = total_return(float(row["low"]))
            close = total_return(float(row["close"]))
            price_source = "PIT_B_DAILY_BAR"
        result.append(
            {
                "trade_id": trade["trade_id"],
                "baseline_block": trade["baseline_block"],
                "symbol": trade["symbol"],
                "trade_date": day,
                "holding_offset": offset,
                "high_return": high,
                "low_return": low,
                "close_return": close,
                "share_factor": share_factor,
                "cash_per_original_share": cash_per_original_share,
                "price_source": price_source,
            }
        )
    mfe_offset = max(
        range(len(result)), key=lambda index: float(result[index]["high_return"])
    )
    mae_offset = min(
        range(len(result)), key=lambda index: float(result[index]["low_return"])
    )
    peak_offset = max(
        range(len(result)), key=lambda index: float(result[index]["close_return"])
    )
    for row in result:
        offset = int(row["holding_offset"])
        row["is_mfe_day"] = offset == mfe_offset
        row["is_mae_day"] = offset == mae_offset
        row["is_peak_close_day"] = offset == peak_offset
    return result


def event_features(event: dict[str, Any]) -> dict[str, Any]:
    rs = event["rs"]
    full = event["full40"]
    minimum = event["minvol"]
    breakout = event["breakout_volume"]
    return {
        "entry_rs_score": rs["score"],
        "entry_mom20": rs["mom20"],
        "entry_mom60": rs["mom60"],
        "entry_mom120": rs["mom120"],
        "entry_box_width": full["box_width"],
        "entry_vol_ratio": full["vol_ratio"],
        "entry_minvol_location": minimum["location"],
        "entry_minimum_volume_ratio": minimum["minimum_volume_ratio"],
        "entry_breakout_volume_ratio": breakout["ratio"],
    }


def main() -> None:
    prior = load_prior_module()
    baseline, source_ledger_hashes = prior.validate_inputs()
    frozen_sources = {
        "yearly_trades": prior.sha256_file(YEARLY_TRADES),
        "trade_mechanism_attribution": prior.sha256_file(MECHANISM),
        "daily_regime_features": prior.sha256_file(FEATURES),
    }
    expected = {
        "yearly_trades": EXPECTED_YEARLY_SHA256,
        "trade_mechanism_attribution": EXPECTED_MECHANISM_SHA256,
        "daily_regime_features": EXPECTED_FEATURE_SHA256,
    }
    if frozen_sources != expected:
        raise RuntimeError(
            "frozen artifact hash mismatch: "
            + json.dumps({"actual": frozen_sources, "expected": expected})
        )

    yearly_rows = read_csv(YEARLY_TRADES)
    mechanism_rows = read_csv(MECHANISM)
    if len(yearly_rows) != 399 or len(mechanism_rows) != 399:
        raise RuntimeError("authoritative trade artifacts must each contain 399 rows")
    yearly_by_id = {row["trade_id"]: row for row in yearly_rows}
    mechanism_by_id = {row["trade_id"]: row for row in mechanism_rows}
    if len(yearly_by_id) != 399 or set(yearly_by_id) != set(mechanism_by_id):
        raise RuntimeError("trade IDs are not unique and one-to-one")

    trades: list[dict[str, Any]] = []
    for block, directory in prior.BLOCKS.items():
        executions = prior.read_jsonl(directory / "execution_ledger.jsonl")
        events = prior.read_jsonl(directory / "event_ledger.jsonl")
        block_trades = prior.build_cycles(executions, block)
        prior.enrich_event_lineage(block_trades, events)
        trades.extend(block_trades)
    if len(trades) != 399 or len({row["trade_id"] for row in trades}) != 399:
        raise RuntimeError("reconstructed cycle population is not exactly 399 unique trades")

    sessions = prior.load_sessions()
    session_index = {day: index for index, day in enumerate(sessions)}
    price_rows = prior.load_trade_price_rows({row["symbol"] for row in trades})
    panel: list[dict[str, Any]] = []
    daily_path: list[dict[str, Any]] = []
    checked_numeric_fields = [
        "round_trip_return",
        "realized_pnl",
        "capital",
        "mfe",
        "mae",
        "giveback_from_peak",
        "return_5d",
        "return_10d",
        "return_20d",
    ]
    checked_integer_fields = [
        "holding_trading_days",
        "days_to_mfe",
        "days_to_mae",
    ]
    for trade in sorted(trades, key=lambda row: row["trade_id"]):
        trade_id = trade["trade_id"]
        authoritative = yearly_by_id[trade_id]
        mechanism = mechanism_by_id[trade_id]
        inherited = prior.holding_features(trade, sessions, session_index, price_rows)
        reconstructed = {**trade, **inherited}
        for field in (
            "baseline_block",
            "symbol",
            "entry_signal_date",
            "entry_execution_date",
            "exit_signal_date",
            "exit_execution_date",
            "canonical_exit_reason",
        ):
            if str(reconstructed[field]) != authoritative[field]:
                raise RuntimeError(f"{trade_id} mismatch in {field}")
        for field in checked_numeric_fields:
            if not same_float(reconstructed.get(field), authoritative.get(field)):
                raise RuntimeError(
                    f"{trade_id} mismatch in {field}: "
                    f"{reconstructed.get(field)} != {authoritative.get(field)}"
                )
        for field in checked_integer_fields:
            if int(reconstructed[field]) != int(authoritative[field]):
                raise RuntimeError(f"{trade_id} mismatch in {field}")
        causal_features = event_features(trade["entry_event"])
        for field, value in causal_features.items():
            if not same_float(value, authoritative[field]):
                raise RuntimeError(f"{trade_id} entry feature mismatch in {field}")
        for field in (
            "holding_trading_days",
            "mfe",
            "mae",
            "days_to_mfe",
            "days_to_mae",
            "round_trip_return",
            "realized_pnl",
            "giveback_from_peak",
        ):
            if not same_float(reconstructed[field], mechanism[field]):
                raise RuntimeError(f"{trade_id} mechanism mismatch in {field}")

        path = build_daily_path(prior, trade, sessions, session_index, price_rows)
        daily_path.extend(path)
        terminal = float(trade["round_trip_return"])
        mfe = float(inherited["mfe"])
        descriptors = path_descriptors(path, int(inherited["days_to_mfe"]), terminal)
        if not same_float(descriptors["peak_close_return"], inherited["peak_close_return"]):
            raise RuntimeError(f"{trade_id} peak-close mismatch")
        if int(descriptors["days_from_peak_to_exit"]) != int(
            inherited["days_from_peak_to_exit"]
        ):
            raise RuntimeError(f"{trade_id} peak timing mismatch")

        holding = int(inherited["holding_trading_days"])
        row: dict[str, Any] = {
            "baseline_block": trade["baseline_block"],
            "trade_id": trade_id,
            "symbol": trade["symbol"],
            "entry_signal_date": trade["entry_signal_date"],
            "entry_execution_date": trade["entry_execution_date"],
            "exit_signal_date": trade["exit_signal_date"],
            "exit_execution_date": trade["exit_execution_date"],
            "entry_year": int(trade["entry_signal_date"][:4]),
            "entry_quarter": mechanism["entry_quarter"],
            "canonical_exit_reason": trade["canonical_exit_reason"],
            "capital": float(trade["capital"]),
            "realized_pnl": float(trade["realized_pnl"]),
            "terminal_return": terminal,
            "terminal_class": terminal_class(terminal),
            "right_tail_classification": terminal >= 0.20,
            "severe_loss_classification": terminal <= -0.10,
            "holding_trading_days": holding,
            "mfe": mfe,
            "mae": float(inherited["mae"]),
            "time_to_mfe": int(inherited["days_to_mfe"]),
            "time_to_mae": int(inherited["days_to_mae"]),
            "time_to_mfe_fraction": int(inherited["days_to_mfe"])
            / max(1, holding),
            "post_mfe_giveback": mfe - terminal,
            "mfe_realization": terminal / mfe if mfe > 0 else None,
            "opportunity20": mfe >= 0.20,
            "opportunity50": mfe >= 0.50,
            "right_tail_conversion20": terminal >= 0.20 if mfe >= 0.20 else None,
            "extreme_conversion50": terminal >= 0.50 if mfe >= 0.50 else None,
            "opportunity20_capture": terminal / mfe if mfe >= 0.20 else None,
            "positive_capture": terminal > 0 if mfe >= 0.20 else None,
            "false_breakout": mfe < 0.10 and terminal <= 0,
            **descriptors,
            "return_5d": inherited.get("return_5d"),
            "return_10d": inherited.get("return_10d"),
            "return_20d": inherited.get("return_20d"),
            "breadth_above_ma20": mechanism["breadth_above_ma20"] or None,
            "breadth_positive_return20": mechanism["breadth_positive_return20"]
            or None,
            "breadth_above_ma20_change20": mechanism[
                "breadth_above_ma20_change20"
            ]
            or None,
            "breadth_composite": mechanism["breadth_composite"] or None,
            "breadth_tercile": mechanism["breadth_tercile"] or None,
            **causal_features,
        }
        panel.append(row)

    if len(daily_path) != sum(int(row["holding_trading_days"]) + 1 for row in panel):
        raise RuntimeError("daily holding-path row count does not reconcile")
    write_csv(OUTPUT_PANEL, panel)
    write_csv(OUTPUT_PATH, daily_path)
    class_counts: dict[str, int] = {}
    for row in panel:
        name = str(row["terminal_class"])
        class_counts[name] = class_counts.get(name, 0) + 1
    manifest = {
        "experiment_id": "OC-EXP-P1-001",
        "status": "PASS",
        "strategy_modified": False,
        "formal_replays": 0,
        "trade_count": len(panel),
        "daily_holding_path_rows": len(daily_path),
        "block_trade_counts": {
            block: sum(row["baseline_block"] == block for row in panel)
            for block in prior.BLOCKS
        },
        "terminal_class_counts": class_counts,
        "opportunity20_count": sum(bool(row["opportunity20"]) for row in panel),
        "opportunity50_count": sum(bool(row["opportunity50"]) for row in panel),
        "false_breakout_count": sum(bool(row["false_breakout"]) for row in panel),
        "severe_loss_count": sum(
            bool(row["severe_loss_classification"]) for row in panel
        ),
        "source_hashes": {
            **frozen_sources,
            "strategy": prior.sha256_file(prior.STRATEGY),
            "cy006_manifest": prior.sha256_file(prior.CY006_MANIFEST),
            "calendar": prior.sha256_file(prior.CALENDAR),
        },
        "source_ledger_hashes": source_ledger_hashes,
        "baseline_manifest_sha256": prior.sha256_file(prior.BASELINE_MANIFEST),
        "baseline_manifest_blocks": sorted(baseline["blocks"]),
        "output_hashes": {
            "trade_conversion_panel": prior.sha256_file(OUTPUT_PANEL),
            "trade_holding_path": prior.sha256_file(OUTPUT_PATH),
        },
        "reconciliation": {
            "trade_id_one_to_one": True,
            "cycle_fields_exact": True,
            "holding_metrics_tolerance": 1e-12,
            "entry_features_tolerance": 1e-12,
            "exit_session_uses_actual_execution_only": True,
            "corporate_actions_fail_closed": True,
            "terminal_open_cycles_excluded": prior.EXPECTED_TERMINAL_OPEN_CYCLES,
        },
    }
    prior.atomic_write(
        OUTPUT_MANIFEST, json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )
    report = "# Phase 1 — Conversion Panel\n\n"
    report += "OC-EXP-P1-001: **PASS**.\n\n"
    report += (
        f"Reconstructed and reconciled `{len(panel)}` completed authoritative cycles "
        f"and `{len(daily_path)}` eligible holding-path rows. No strategy replay was "
        "run and authoritative V1 was not modified.\n\n"
    )
    report += "## Reconciliation\n\n"
    report += "- Trade IDs: 399/399 unique and one-to-one across inherited ledgers.\n"
    report += "- Entry/exit lineage, terminal return, realized P&L, capital, MFE, MAE, timing, giveback, and early returns match the frozen artifacts at 1e-12 tolerance.\n"
    report += "- All nine causal stock-level entry features match their persisted evaluation events at 1e-12 tolerance.\n"
    report += "- Corporate actions retain the inherited fail-closed total-return coordinates; the exit session uses only actual exit execution.\n\n"
    report += "## Population\n\n"
    report += "| Item | Count |\n|---|---:|\n"
    report += f"| Completed cycles | {len(panel)} |\n"
    report += f"| Opportunity20 | {manifest['opportunity20_count']} |\n"
    report += f"| Opportunity50 | {manifest['opportunity50_count']} |\n"
    report += f"| False breakouts | {manifest['false_breakout_count']} |\n"
    report += f"| Severe losses | {manifest['severe_loss_count']} |\n\n"
    report += "The new smoothness, pre-MFE adversity, peak timing, and decay fields are path outcomes. They are diagnostic variables and are not eligible entry-time predictors.\n"
    prior.atomic_write(REPORT, report)


if __name__ == "__main__":
    main()
