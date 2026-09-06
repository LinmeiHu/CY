#!/usr/bin/env python3
"""Quantify fixed-ledger selection/exit ceilings and strict post-exit paths."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/opportunity_conversion"
PRIOR = ROOT / "research/chinext_v1/regime_attribution"
PRIOR_SCRIPT = PRIOR / "scripts/run_phase1_yearly_decomposition.py"
PANEL = WORK / "artifacts/trade_conversion_panel.csv"
SPEC = WORK / "experiments/phase5_counterfactual_spec.json"
OUTPUT_JSON = WORK / "artifacts/phase5_counterfactual_diagnostics.json"
POST_EXIT_CSV = WORK / "artifacts/post_exit_paths.csv"
REPORT = WORK / "reports/phase5_entry_exit_counterfactual.md"
EXIT_ABLATION = ROOT / "research/chinext_v1/reports/chinext_v1_phase7_exit_ablation_summary.json"
WINNER_HOLD_DEV = ROOT / "research/chinext_v1/reports/chinext_v1_phase8_winner_hold_summary.json"
WINNER_HOLD_OOS = ROOT / "research/chinext_v1/reports/chinext_v1_phase9b_oos_validation_summary.json"
DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")


def load_prior_module() -> Any:
    spec = importlib.util.spec_from_file_location("frozen_phase1_p5", PRIOR_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load frozen Phase 1 module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def load_cycles(prior: Any) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for block, directory in prior.BLOCKS.items():
        cycles = prior.build_cycles(
            prior.read_jsonl(directory / "execution_ledger.jsonl"), block
        )
        for cycle in cycles:
            if cycle["trade_id"] in result:
                raise RuntimeError(f"duplicate cycle: {cycle['trade_id']}")
            result[cycle["trade_id"]] = cycle
    if len(result) != 399:
        raise RuntimeError("post-exit source must reconstruct 399 cycles")
    return result


def load_sessions_and_prices(
    prior: Any, symbols: list[str]
) -> tuple[list[str], dict[tuple[str, str], dict[str, Any]]]:
    connection = duckdb.connect()
    session_rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE)
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2018-01-01' AND DATE '2026-12-31'
        ORDER BY trade_date
        """,
        [str(prior.CALENDAR)],
    ).fetchall()
    paths = [
        str(DAILY_ROOT / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2027)
    ]
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE),symbol,high,close,
               corporate_action_count,corporate_action_available_date,
               corporate_action_blocking,corporate_action_valid,
               share_multiplier,cash_per_share,rights_ratio,
               hard_valid,available_at,snapshot_id
        FROM read_parquet(?,union_by_name=true)
        WHERE symbol IN (SELECT * FROM unnest(?))
          AND trade_date BETWEEN DATE '2018-01-01' AND DATE '2026-12-31'
        ORDER BY symbol,trade_date
        """,
        [paths, symbols],
    ).fetchall()
    connection.close()
    sessions = [row[0].isoformat() for row in session_rows]
    prices: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row[1]), row[0].isoformat())
        if key in prices:
            raise RuntimeError(f"duplicate daily row: {key}")
        prices[key] = {
            "high": row[2],
            "close": row[3],
            "corporate_action_count": row[4],
            "corporate_action_available_date": row[5],
            "corporate_action_blocking": row[6],
            "corporate_action_valid": row[7],
            "share_multiplier": row[8],
            "cash_per_share": row[9],
            "rights_ratio": row[10],
            "hard_valid": row[11],
            "available_at": row[12],
            "snapshot_id": row[13],
        }
    return sessions, prices


def post_exit_path(
    prior: Any,
    trade: dict[str, Any],
    sessions: list[str],
    session_index: dict[str, int],
    prices: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    start = session_index[trade["exit_execution_date"]]
    future = sessions[start + 1 : start + 21]
    result: dict[str, Any] = {
        "trade_id": trade["trade_id"],
        "post_exit_5d_covered": False,
        "post_exit_10d_covered": False,
        "post_exit_20d_covered": False,
        "post_exit_failure_reason": None,
    }
    if len(future) < 20:
        result["post_exit_failure_reason"] = "CALENDAR_END_BEFORE_20"
        return result
    exit_price = float(trade["exit_price"])
    share_factor = 1.0
    cash_per_exit_share = 0.0
    close_returns: list[float] = []
    high_returns: list[float] = []
    for offset, day in enumerate(future, start=1):
        row = prices.get((trade["symbol"], day))
        if row is None:
            result["post_exit_failure_reason"] = f"MISSING_SYMBOL_SESSION_AT_{offset}"
            break
        if row.get("hard_valid") is not True:
            result["post_exit_failure_reason"] = f"HARD_VALID_FALSE_AT_{offset}"
            break
        if int(row.get("corporate_action_count") or 0) > 0:
            valid, multiplier, cash = prior.action_values(row, day)
            if not valid:
                result["post_exit_failure_reason"] = f"CORPORATE_ACTION_INVALID_AT_{offset}"
                break
            cash_per_exit_share += share_factor * cash
            share_factor *= multiplier
        if not all(
            value is not None and math.isfinite(float(value))
            for value in (row["high"], row["close"])
        ):
            result["post_exit_failure_reason"] = f"NONFINITE_PRICE_AT_{offset}"
            break

        def total_return(price: float) -> float:
            return (
                (share_factor * price + cash_per_exit_share) / exit_price - 1.0
            )

        high_returns.append(total_return(float(row["high"])))
        close_returns.append(total_return(float(row["close"])))
        if offset in (5, 10, 20):
            result[f"post_exit_{offset}d_covered"] = True
            result[f"post_exit_close_return_{offset}d"] = close_returns[-1]
            result[f"post_exit_max_high_{offset}d"] = max(high_returns)
            result[f"post_exit_max_close_{offset}d"] = max(close_returns)
    if len(close_returns) == 20:
        result["post_exit_failure_reason"] = None
        result["premature_exit_oracle_10pct_20d"] = (
            result["post_exit_max_high_20d"] >= 0.10
        )
    else:
        result["premature_exit_oracle_10pct_20d"] = None
    return result


def ceiling_summary(group: pd.DataFrame) -> dict[str, Any]:
    negative = group.loc[group["terminal_return"] <= 0]
    false_breakouts = group.loc[group["false_breakout"].eq(True)]
    severe = group.loc[group["severe_loss_classification"].eq(True)]
    opportunities = group.loc[group["opportunity20"].eq(True)]
    return {
        "trade_count": int(len(group)),
        "actual_realized_pnl": float(group["realized_pnl"].sum()),
        "negative_trade_count": int(len(negative)),
        "perfect_terminal_sign_selection_ceiling": float(-negative["realized_pnl"].sum()),
        "false_breakout_count": int(len(false_breakouts)),
        "false_breakout_avoidance_ceiling": float(-false_breakouts["realized_pnl"].sum()),
        "severe_loss_count": int(len(severe)),
        "severe_loss_avoidance_ceiling": float(-severe["realized_pnl"].sum()),
        "false_breakout_severe_overlap_count": int(
            len(group.loc[group["false_breakout"].eq(True) & group["severe_loss_classification"].eq(True)])
        ),
        "all_trade_mfe_initial_capital_ceiling": float(
            (group["capital"] * (group["mfe"] - group["terminal_return"])).sum()
        ),
        "all_trade_peak_close_initial_capital_ceiling": float(
            (group["capital"] * (group["peak_close_return"] - group["terminal_return"])).sum()
        ),
        "opportunity20_count": int(len(opportunities)),
        "opportunity20_actual_pnl": float(opportunities["realized_pnl"].sum()),
        "opportunity20_mfe_initial_capital_ceiling": float(
            (
                opportunities["capital"]
                * (opportunities["mfe"] - opportunities["terminal_return"])
            ).sum()
        ),
        "opportunity20_peak_close_initial_capital_ceiling": float(
            (
                opportunities["capital"]
                * (
                    opportunities["peak_close_return"]
                    - opportunities["terminal_return"]
                )
            ).sum()
        ),
    }


def distribution(series: pd.Series) -> dict[str, Any]:
    values = series.dropna().astype(float)
    if values.empty:
        return {"count": 0, "mean": None, "median": None, "p25": None, "p75": None}
    return {
        "count": int(len(values)),
        "mean": float(values.mean()),
        "median": float(values.median()),
        "p25": float(values.quantile(0.25)),
        "p75": float(values.quantile(0.75)),
    }


def post_exit_group(group: pd.DataFrame) -> dict[str, Any]:
    covered = group.loc[group["post_exit_20d_covered"].eq(True)]
    return {
        "trade_count": int(len(group)),
        "covered20_count": int(len(covered)),
        "premature_exit_oracle_rate": (
            float(covered["premature_exit_oracle_10pct_20d"].mean())
            if len(covered)
            else None
        ),
        "close_return_5d": distribution(group["post_exit_close_return_5d"]),
        "close_return_10d": distribution(group["post_exit_close_return_10d"]),
        "close_return_20d": distribution(group["post_exit_close_return_20d"]),
        "max_high_20d": distribution(group["post_exit_max_high_20d"]),
    }


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("frozen_before_execution") is not True:
        raise RuntimeError("Phase 5 spec is not frozen")
    panel = pd.read_csv(PANEL)
    for column in (
        "false_breakout",
        "severe_loss_classification",
        "opportunity20",
        "opportunity50",
        "right_tail_classification",
        "positive_capture",
    ):
        panel[column] = panel[column].map(
            {True: True, False: False, "True": True, "False": False}
        )
    if len(panel) != 399 or panel["trade_id"].nunique() != 399:
        raise RuntimeError("fixed trade ledger mismatch")
    prior = load_prior_module()
    prior.validate_inputs()
    cycles = load_cycles(prior)
    sessions, prices = load_sessions_and_prices(prior, sorted(panel["symbol"].unique()))
    session_index = {day: index for index, day in enumerate(sessions)}
    post_exit_rows = [
        post_exit_path(prior, cycles[trade_id], sessions, session_index, prices)
        for trade_id in sorted(cycles)
    ]
    post_exit = pd.DataFrame(post_exit_rows)
    if len(post_exit) != 399 or post_exit["trade_id"].nunique() != 399:
        raise RuntimeError("post-exit population mismatch")
    atomic_csv(POST_EXIT_CSV, post_exit)
    joined = panel.merge(post_exit, on="trade_id", how="left", validate="one_to_one")

    yearly = {
        str(year): ceiling_summary(group)
        for year, group in joined.groupby("entry_year")
    }
    full_ceiling = ceiling_summary(joined)
    opportunities = joined.loc[joined["opportunity20"].eq(True)]
    nonconverted = opportunities.loc[~opportunities["right_tail_classification"].eq(True)]
    op50 = joined.loc[joined["opportunity50"].eq(True)]
    conversion_chain = {
        "completed_trades": 399,
        "opportunity20_count": int(len(opportunities)),
        "right_tail_terminal_count": int(joined["right_tail_classification"].sum()),
        "opportunity20_converted_to_right_tail_count": int(
            opportunities["right_tail_classification"].sum()
        ),
        "opportunity20_nonconversion_count": int(len(nonconverted)),
        "opportunity20_nonconversion_positive_count": int(
            (nonconverted["terminal_return"] > 0).sum()
        ),
        "opportunity20_nonconversion_nonpositive_count": int(
            (nonconverted["terminal_return"] <= 0).sum()
        ),
        "opportunity20_nonconversion_pnl": float(nonconverted["realized_pnl"].sum()),
        "opportunity50_count": int(len(op50)),
        "opportunity50_to_right_tail_count": int(op50["right_tail_classification"].sum()),
        "opportunity50_to_extreme_winner_count": int(
            (op50["terminal_return"] >= 0.50).sum()
        ),
        "false_breakout_count": int(joined["false_breakout"].sum()),
        "severe_loss_count": int(joined["severe_loss_classification"].sum()),
    }

    coverage = {
        horizon: int(joined[f"post_exit_{horizon}d_covered"].sum())
        for horizon in (5, 10, 20)
    }
    failure_counts = (
        joined["post_exit_failure_reason"].fillna("NONE").value_counts().to_dict()
    )
    post_exit_groups: dict[str, Any] = {
        "all": post_exit_group(joined),
        "opportunity20": post_exit_group(opportunities),
        "opportunity20_nonconversion": post_exit_group(nonconverted),
        "false_breakout": post_exit_group(joined.loc[joined["false_breakout"].eq(True)]),
        "severe_loss": post_exit_group(joined.loc[joined["severe_loss_classification"].eq(True)]),
        "by_exit_reason": {
            reason: post_exit_group(group)
            for reason, group in joined.groupby("canonical_exit_reason")
        },
        "by_year": {
            str(year): post_exit_group(group)
            for year, group in joined.groupby("entry_year")
        },
    }

    exit_ablation = json.loads(EXIT_ABLATION.read_text(encoding="utf-8"))
    winner_dev = json.loads(WINNER_HOLD_DEV.read_text(encoding="utf-8"))
    winner_oos = json.loads(WINNER_HOLD_OOS.read_text(encoding="utf-8"))
    arms = exit_ablation["arms"]
    baseline_year_returns = {2024: 0.4904941877500004, 2025: 0.377007823927356}
    executable = {
        "development_exit_ablation": {
            arm: {
                "total_return": arms[arm]["total_return"],
                "total_return_delta_pp": 100
                * (arms[arm]["total_return"] - arms["E0_FROZEN_PHASE1B"]["total_return"]),
                "max_drawdown": arms[arm]["max_drawdown"],
                "average_invested_fraction": arms[arm]["average_invested_fraction"],
                "year_return_delta_pp": {
                    year: 100
                    * (
                        arms[arm]["year_by_year"][str(year)]["return"]
                        - baseline_year_returns[year]
                    )
                    for year in (2024, 2025)
                },
            }
            for arm in ("E1_INDIVIDUAL_EXIT_DISABLED", "E2_MARKET_EXIT_DISABLED")
        },
        "winner_hold_development": {
            "baseline_total_return": winner_dev["W0_BASELINE"]["total_return"],
            "candidate_total_return": winner_dev["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["total_return"],
            "total_return_delta_pp": 100
            * (
                winner_dev["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["total_return"]
                - winner_dev["W0_BASELINE"]["total_return"]
            ),
            "year_return_delta_pp": {
                year: 100
                * (
                    winner_dev["W1_WINNER_HOLD_THROUGH_MARKET_EXIT"]["year_by_year"][str(year)]["return"]
                    - baseline_year_returns[year]
                )
                for year in (2024, 2025)
            },
        },
        "winner_hold_oos": {
            "baseline_total_return": winner_oos["O0_BASELINE"]["total_return"],
            "candidate_total_return": winner_oos["O1_WINNER_HOLD"]["total_return"],
            "total_return_delta_pp": winner_oos["O1_MINUS_O0"]["return_delta_pp"],
            "max_drawdown_delta_pp": winner_oos["O1_MINUS_O0"]["max_drawdown_delta_pp"],
            "year_consistency": winner_oos["year_consistency"],
            "generalization": winner_oos["winner_hold_generalization"],
            "activation_count": winner_oos["diagnostics"]["winner_deferred_count"],
        },
    }

    payload = {
        "experiment_id": "OC-EXP-P5-001",
        "status": "PASS",
        "strategy_modified": False,
        "formal_replays": 0,
        "spec_sha256": sha256_file(SPEC),
        "conversion_chain": conversion_chain,
        "fixed_ledger_ceilings": {
            "all_years": full_ceiling,
            "by_entry_year": yearly,
            "non_additivity_warning": spec["selection_ceilings"]["warning"],
            "exit_oracle_warning": spec["exit_ceilings"]["warning"],
        },
        "post_exit": {
            "coverage": coverage,
            "failure_counts": failure_counts,
            "groups": post_exit_groups,
            "future_outcome_warning": spec["post_exit_path"]["warning"],
        },
        "frozen_executable_counterevidence": executable,
        "source_hashes": {
            "panel": sha256_file(PANEL),
            "spec": sha256_file(SPEC),
            "exit_ablation": sha256_file(EXIT_ABLATION),
            "winner_hold_development": sha256_file(WINNER_HOLD_DEV),
            "winner_hold_oos": sha256_file(WINNER_HOLD_OOS),
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, indent=2, sort_keys=True) + "\n")

    lines = [
        "# Phase 5 — Entry versus Exit Counterfactual Diagnostics",
        "",
        "OC-EXP-P5-001: **PASS**. All ceilings are static, non-additive diagnostics; no new strategy replay was run.",
        "",
        "## Conversion chain counts",
        "",
        "| Stage | Count |",
        "|---|---:|",
        f"| Completed trades | {conversion_chain['completed_trades']} |",
        f"| MFE >=20% opportunity | {conversion_chain['opportunity20_count']} |",
        f"| Opportunity20 -> terminal >=20% | {conversion_chain['opportunity20_converted_to_right_tail_count']} |",
        f"| Opportunity20 nonconversion | {conversion_chain['opportunity20_nonconversion_count']} |",
        f"| Nonconversion ending positive | {conversion_chain['opportunity20_nonconversion_positive_count']} |",
        f"| Nonconversion ending nonpositive | {conversion_chain['opportunity20_nonconversion_nonpositive_count']} |",
        f"| MFE >=50% opportunity | {conversion_chain['opportunity50_count']} |",
        f"| Opportunity50 -> terminal >=20% | {conversion_chain['opportunity50_to_right_tail_count']} |",
        f"| Opportunity50 -> terminal >=50% | {conversion_chain['opportunity50_to_extreme_winner_count']} |",
        "",
        "## Fixed-ledger ceilings (currency P&L or initial-capital oracle units)",
        "",
        "| Diagnostic | Amount |",
        "|---|---:|",
        f"| Actual realized P&L | {full_ceiling['actual_realized_pnl']:,.0f} |",
        f"| Perfect terminal-sign selection | {full_ceiling['perfect_terminal_sign_selection_ceiling']:,.0f} |",
        f"| False-breakout avoidance | {full_ceiling['false_breakout_avoidance_ceiling']:,.0f} |",
        f"| Severe-loss avoidance | {full_ceiling['severe_loss_avoidance_ceiling']:,.0f} |",
        f"| Opportunity20 MFE-high giveback oracle | {full_ceiling['opportunity20_mfe_initial_capital_ceiling']:,.0f} |",
        f"| Opportunity20 peak-close giveback oracle | {full_ceiling['opportunity20_peak_close_initial_capital_ceiling']:,.0f} |",
        "",
        "Selection ceilings overlap. Exit ceilings use hindsight highs/peaks and initial capital, ignore portfolio vacancy/crowding and alternate-path feedback, and are not NAVs.",
        "",
        "## Strict post-exit outcomes",
        "",
        f"Coverage is {coverage[5]}/399 at 5 sessions, {coverage[10]}/399 at 10, and {coverage[20]}/399 at 20. Exit-day close is excluded.",
        "",
        "| Group | N | Covered20 | Median close20 | Median max-high20 | Max-high >=10% |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    display_groups = {
        "All": post_exit_groups["all"],
        "Opportunity20": post_exit_groups["opportunity20"],
        "Opp20 nonconversion": post_exit_groups["opportunity20_nonconversion"],
        "False breakout": post_exit_groups["false_breakout"],
        "Severe loss": post_exit_groups["severe_loss"],
    }
    for name, row in display_groups.items():
        close = row["close_return_20d"]["median"]
        high = row["max_high_20d"]["median"]
        rate = row["premature_exit_oracle_rate"]
        lines.append(
            f"| {name} | {row['trade_count']} | {row['covered20_count']} | "
            f"{close:.2%} | {high:.2%} | {rate:.2%} |"
        )
    lines += [
        "",
        "## Frozen executable counterevidence",
        "",
        "| Replay | Total-return delta | Year deltas | Interpretation |",
        "|---|---:|---|---|",
    ]
    for arm, row in executable["development_exit_ablation"].items():
        lines.append(
            f"| {arm} | {row['total_return_delta_pp']:.2f} pp | "
            f"2024 {row['year_return_delta_pp'][2024]:.2f} pp; 2025 {row['year_return_delta_pp'][2025]:.2f} pp | Mixed years; lower total return |"
        )
    dev = executable["winner_hold_development"]
    oos = executable["winner_hold_oos"]
    lines += [
        f"| Winner hold, development | {dev['total_return_delta_pp']:.2f} pp | 2024 {dev['year_return_delta_pp'][2024]:.2f} pp; 2025 {dev['year_return_delta_pp'][2025]:.2f} pp | Development-only promise |",
        f"| Winner hold, 2022-2023 OOS | {oos['total_return_delta_pp']:.2f} pp | {oos['year_consistency']['classification']} | {oos['generalization']}; only {oos['activation_count']} activations |",
        "",
        "Large hindsight giveback therefore establishes an economic ceiling, not a stable executable exit improvement. Post-exit maxima are future outcomes and cannot reverse the frozen OOS failure.",
    ]
    atomic_write(REPORT, "\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

