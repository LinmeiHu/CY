#!/usr/bin/env python3
"""One-shot development replay of the frozen V27 chart-derived failure exit."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_causal_market_regime_substrategy_router_v27 as v27  # noqa: E402
import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as v13  # noqa: E402


EXPERIMENT = (
    "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27-"
    "NO-PROGRESS-COST-FAILURE-EXIT-V1"
)
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
ROOT = Path("/Volumes/quant/CY_quant_research")
V27_ROOT = ROOT / "ashare_causal_market_regime_substrategy_router_v27"
TRADES = V27_ROOT / "accepted_trades.parquet"
V27_RESULT = V27_ROOT / "result.json"
DAILY = (
    ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)
OUT = V27_ROOT / "stage_d5_no_progress_cost_failure_exit_v1"

SIGNAL_START = pd.Timestamp("2014-01-01")
SIGNAL_END = pd.Timestamp("2020-12-31")
EXPECTED_TRADES = 809
ROUND_TRIP_COST = 0.004
OBSERVATION_VALID_SESSIONS = 5
PROGRESS_FRACTION_OF_TARGET = 0.5

EXPECTED_HASHES = {
    SPEC: "5f581a37aa4ef343c5c3a3372bc6b2ab22d11e2099f546d6d8b91f4197560996",
    TRADES: "73ed476190c29044cae79c2d0f9e38c11f0ddf2ba200e756f240131d8e9143ea",
    V27_RESULT: "d50ea992529a2a202d8d17ed7eb5dc0908291224a74948616aa84a39fcf65537",
    DAILY: "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}


class ResearchError(RuntimeError):
    """Fail closed on identity, timing, execution, or coordinate drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[str(path)] = sha256(path)
        if actual[str(path)] != expected:
            raise ResearchError(
                f"frozen input drift for {path}: {actual[str(path)]} != {expected}"
            )
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if not spec.get("frozen_before_outcome_aggregation"):
        raise ResearchError("exit rule was not frozen before aggregation")
    return actual


def load_development_trades() -> pd.DataFrame:
    frame = duckdb.sql(
        f"""
        SELECT * FROM read_parquet('{TRADES.as_posix()}')
        WHERE signal_date BETWEEN DATE '2014-01-01' AND DATE '2020-12-31'
        ORDER BY entry_date,sleeve,event_id
        """
    ).df()
    for column in ("signal_date", "entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    if len(frame) != EXPECTED_TRADES or frame.event_id.nunique() != EXPECTED_TRADES:
        raise ResearchError("development trade identity drift")
    if frame.signal_date.min() < SIGNAL_START or frame.signal_date.max() > SIGNAL_END:
        raise ResearchError("later trade outcome entered development replay")
    if frame.entry_date.le(frame.signal_date).any():
        raise ResearchError("entry does not follow signal")
    if frame.exit_date.le(frame.entry_date).any():
        raise ResearchError("nonpositive frozen lifecycle")
    return frame


def load_paths(trades: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "trades",
        trades[["event_id", "symbol", "entry_cal_idx", "exit_cal_idx"]],
    )
    frame = connection.execute(
        f"""
        SELECT t.event_id,d.symbol,CAST(d.trade_date AS DATE) AS trade_date,d.cal_idx,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.open AS raw_open,
          d.down_limit_price,d.trade_status,d.current_day_data_tradable,
          d.market_rule_valid,d.corporate_action_valid,d.corporate_action_blocking,
          d.hard_valid,d.available_at,d.decision_at,d.invalid_step_cum
        FROM trades t
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON t.symbol=d.symbol
         AND d.cal_idx BETWEEN t.entry_cal_idx AND t.exit_cal_idx
        ORDER BY t.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    frame["available_at"] = pd.to_datetime(frame.available_at)
    frame["decision_at"] = pd.to_datetime(frame.decision_at)
    expected = int((trades.exit_cal_idx - trades.entry_cal_idx + 1).sum())
    if len(frame) != expected:
        raise ResearchError(f"daily path coverage mismatch: {len(frame)} != {expected}")
    if frame.groupby("event_id").invalid_step_cum.nunique(dropna=False).gt(1).any():
        raise ResearchError("corporate-action coordinate lineage changes inside lifecycle")
    if frame.invalid_step_cum.isna().any():
        raise ResearchError("unknown coordinate lineage inside lifecycle")
    return frame


def observation_valid(frame: pd.DataFrame) -> pd.Series:
    finite = np.isfinite(
        frame[["coord_open", "coord_high", "coord_low", "coord_close"]]
    ).all(axis=1)
    return (
        frame.trade_status.eq(1)
        & frame.current_day_data_tradable.fillna(False)
        & frame.market_rule_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
        & frame.hard_valid.fillna(False)
        & finite
        & frame.available_at.le(frame.decision_at)
    )


def legal_sell_open(frame: pd.DataFrame) -> pd.Series:
    finite = np.isfinite(frame[["raw_open", "coord_open", "down_limit_price"]]).all(
        axis=1
    )
    above_down_limit = (
        np.round(frame.raw_open * 100) > np.round(frame.down_limit_price * 100)
    )
    return (
        frame.trade_status.eq(1)
        & frame.current_day_data_tradable.fillna(False)
        & frame.market_rule_valid.fillna(False)
        & frame.corporate_action_valid.fillna(False)
        & ~frame.corporate_action_blocking.fillna(True)
        & frame.hard_valid.fillna(False)
        & finite
        & above_down_limit
    )


def target_return_for_lane(lane: str) -> float:
    return 0.15 if lane == "BULL_DECELERATING_QUIET_INVENTORY" else 0.10


def evaluate_rule(
    trades: pd.DataFrame, paths: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    modified = trades.copy()
    modified["overlay_triggered"] = False
    modified["overlay_applied"] = False
    modified["overlay_decision_date"] = pd.NaT
    modified["overlay_progress_threshold"] = np.nan
    modified["overlay_max_high_5"] = np.nan
    modified["overlay_close_4"] = np.nan
    modified["overlay_close_5"] = np.nan

    path_map = {str(key): part.copy() for key, part in paths.groupby("event_id")}
    diagnostics: list[dict[str, Any]] = []
    insufficient_valid_sessions = 0
    no_legal_earlier_fill = 0
    target_or_exit_before_decision = 0

    for index, trade in modified.iterrows():
        event_id = str(trade.event_id)
        path = path_map[event_id].sort_values("cal_idx", kind="mergesort")
        valid = path.loc[observation_valid(path)].head(OBSERVATION_VALID_SESSIONS)
        if len(valid) < OBSERVATION_VALID_SESSIONS:
            insufficient_valid_sessions += 1
            continue
        if pd.Timestamp(valid.iloc[0].trade_date) != pd.Timestamp(trade.entry_date):
            raise ResearchError(f"entry row is not valid session 1 for {event_id}")

        decision = valid.iloc[OBSERVATION_VALID_SESSIONS - 1]
        decision_date = pd.Timestamp(decision.trade_date)
        if pd.Timestamp(trade.exit_date) <= decision_date:
            target_or_exit_before_decision += 1
            continue

        target_return = target_return_for_lane(str(trade.lane))
        progress_threshold = float(trade.entry_price) * (
            1.0 + PROGRESS_FRACTION_OF_TARGET * target_return
        )
        max_high = float(valid.coord_high.max())
        close4 = float(valid.iloc[3].coord_close)
        close5 = float(valid.iloc[4].coord_close)
        no_progress = max_high < progress_threshold
        cost_failure = close4 < float(trade.entry_price) and close5 < float(
            trade.entry_price
        )
        triggered = bool(no_progress and cost_failure)

        modified.at[index, "overlay_decision_date"] = decision_date
        modified.at[index, "overlay_progress_threshold"] = progress_threshold
        modified.at[index, "overlay_max_high_5"] = max_high
        modified.at[index, "overlay_close_4"] = close4
        modified.at[index, "overlay_close_5"] = close5
        modified.at[index, "overlay_triggered"] = triggered
        if not triggered:
            continue

        later = path.loc[path.cal_idx.gt(int(decision.cal_idx))].copy()
        legal = later.loc[legal_sell_open(later)]
        if legal.empty:
            no_legal_earlier_fill += 1
            continue
        fill = legal.iloc[0]
        if int(fill.cal_idx) > int(trade.exit_cal_idx):
            no_legal_earlier_fill += 1
            continue

        new_exit_price = float(fill.coord_open)
        modified.at[index, "overlay_applied"] = True
        modified.at[index, "exit_date"] = pd.Timestamp(fill.trade_date)
        modified.at[index, "exit_cal_idx"] = int(fill.cal_idx)
        modified.at[index, "exit_price"] = new_exit_price
        modified.at[index, "exit_reason"] = "D5_NO_PROGRESS_COST_FAILURE_EXIT"
        modified.at[index, "holding_sessions"] = int(fill.cal_idx) - int(
            trade.entry_cal_idx
        )
        modified.at[index, "gross_return"] = new_exit_price / float(
            trade.entry_price
        ) - 1.0
        modified.at[index, "net_return"] = (
            new_exit_price / float(trade.entry_price) - 1.0 - ROUND_TRIP_COST
        )
        diagnostics.append(
            {
                "event_id": event_id,
                "symbol": str(trade.symbol),
                "lane": str(trade.lane),
                "signal_date": pd.Timestamp(trade.signal_date),
                "entry_date": pd.Timestamp(trade.entry_date),
                "decision_date": decision_date,
                "original_exit_date": pd.Timestamp(trade.exit_date),
                "overlay_exit_date": pd.Timestamp(fill.trade_date),
                "target_return": target_return,
                "progress_threshold": progress_threshold,
                "max_high_5": max_high,
                "close_4": close4,
                "close_5": close5,
                "baseline_net_return": float(trade.net_return),
                "overlay_net_return": float(modified.at[index, "net_return"]),
                "return_delta": float(modified.at[index, "net_return"])
                - float(trade.net_return),
                "baseline_exit_reason": str(trade.exit_reason),
            }
        )

    audit = {
        "insufficient_five_valid_sessions": int(insufficient_valid_sessions),
        "frozen_exit_on_or_before_decision": int(target_or_exit_before_decision),
        "trigger_count": int(modified.overlay_triggered.sum()),
        "applied_count": int(modified.overlay_applied.sum()),
        "trigger_without_legal_earlier_fill": int(no_legal_earlier_fill),
    }
    return modified, pd.DataFrame(diagnostics), audit


def extended_trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    payload = v27.trade_metrics(frame)
    payload.update(
        {
            "profit_ge_4pct": None if frame.empty else float(values.ge(0.04).mean()),
            "profit_ge_4pct_count": int(values.ge(0.04).sum()),
        }
    )
    return payload


def metric_delta(
    baseline: dict[str, Any], overlay: dict[str, Any], keys: list[str]
) -> dict[str, Any]:
    return {
        key: (
            None
            if baseline.get(key) is None or overlay.get(key) is None
            else float(overlay[key]) - float(baseline[key])
        )
        for key in keys
    }


def group_comparison(
    baseline: pd.DataFrame, overlay: pd.DataFrame, group: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    values = sorted(str(value) for value in baseline[group].dropna().unique())
    for value in values:
        left = baseline.loc[baseline[group].astype(str).eq(value)]
        right = overlay.loc[overlay[group].astype(str).eq(value)]
        left_metrics = extended_trade_metrics(left)
        right_metrics = extended_trade_metrics(right)
        rows.append(
            {
                group: value,
                "baseline": left_metrics,
                "overlay": right_metrics,
                "delta": metric_delta(
                    left_metrics,
                    right_metrics,
                    [
                        "mean_net",
                        "median_net",
                        "win_rate",
                        "profit_ge_4pct",
                        "severe10",
                        "average_holding_sessions",
                    ],
                ),
                "trigger_count": int(right.overlay_triggered.sum()),
                "applied_count": int(right.overlay_applied.sum()),
            }
        )
    return rows


def portfolio_metrics(trades: pd.DataFrame, common_end: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    nav, audit = v27.replay_portfolio(trades)
    nav = nav.loc[nav.trade_date.le(common_end)].copy()
    if nav.empty:
        raise ResearchError("empty development NAV")
    return nav, {**v13.nav_metrics(nav), **audit}


def execution_audit(
    baseline: pd.DataFrame,
    overlay: pd.DataFrame,
    diagnostics: pd.DataFrame,
    paths: pd.DataFrame,
) -> dict[str, Any]:
    applied = overlay.loc[overlay.overlay_applied].copy()
    base_exec = v27.execution_audit(baseline)
    overlay_exec = v27.execution_audit(overlay)
    decision_after_entry = int(
        applied.overlay_decision_date.le(applied.entry_date).sum()
    )
    fill_not_after_decision = int(
        applied.exit_date.le(applied.overlay_decision_date).sum()
    )
    decision_rows = diagnostics[["event_id", "decision_date"]].merge(
        paths[["event_id", "trade_date", "available_at", "decision_at"]],
        left_on=["event_id", "decision_date"],
        right_on=["event_id", "trade_date"],
        how="left",
        validate="one_to_one",
    )
    missing_decision = int(decision_rows.decision_at.isna().sum())
    availability_violation = int(
        decision_rows.available_at.gt(decision_rows.decision_at).sum()
    )
    return {
        "baseline_execution": base_exec,
        "overlay_execution": overlay_exec,
        "overlay_decision_at_or_before_entry": decision_after_entry,
        "overlay_fill_at_or_before_decision": fill_not_after_decision,
        "missing_overlay_decision_timestamp": missing_decision,
        "overlay_information_after_decision": availability_violation,
        "post_2020_signal_rows": int(overlay.signal_date.gt(SIGNAL_END).sum()),
        "post_2021_01_21_exit_rows": int(
            overlay.exit_date.gt(pd.Timestamp("2021-01-21")).sum()
        ),
    }


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    baseline = load_development_trades()
    paths = load_paths(baseline)
    overlay, diagnostics, rule_audit = evaluate_rule(baseline, paths)

    audit = execution_audit(baseline, overlay, diagnostics, paths)
    required_zero = [
        *audit["baseline_execution"].values(),
        *audit["overlay_execution"].values(),
        audit["overlay_decision_at_or_before_entry"],
        audit["overlay_fill_at_or_before_decision"],
        audit["missing_overlay_decision_timestamp"],
        audit["overlay_information_after_decision"],
        audit["post_2020_signal_rows"],
        audit["post_2021_01_21_exit_rows"],
    ]
    if any(int(value) != 0 for value in required_zero):
        raise ResearchError(f"causal/execution audit failed: {audit}")

    baseline_metrics = extended_trade_metrics(baseline)
    overlay_metrics = extended_trade_metrics(overlay)
    trade_delta = metric_delta(
        baseline_metrics,
        overlay_metrics,
        [
            "mean_net",
            "median_net",
            "win_rate",
            "profit_ge_4pct",
            "severe10",
            "average_holding_sessions",
        ],
    )

    common_end = max(pd.Timestamp(baseline.exit_date.max()), pd.Timestamp(overlay.exit_date.max()))
    baseline_nav, baseline_portfolio = portfolio_metrics(baseline, common_end)
    overlay_nav, overlay_portfolio = portfolio_metrics(overlay, common_end)
    portfolio_delta = metric_delta(
        baseline_portfolio,
        overlay_portfolio,
        [
            "total_return",
            "cagr",
            "max_drawdown",
            "sharpe",
            "average_utilization",
        ],
    )

    joined = baseline[["event_id", "net_return"]].rename(
        columns={"net_return": "baseline_net"}
    ).merge(
        overlay[["event_id", "net_return", "overlay_triggered", "overlay_applied"]].rename(
            columns={"net_return": "overlay_net"}
        ),
        on="event_id",
        validate="one_to_one",
    )
    affected = joined.loc[joined.overlay_applied]
    outcome_transfer = {
        "baseline_profit_ge_4pct_sacrificed": int(
            (affected.baseline_net.ge(0.04) & affected.overlay_net.lt(0.04)).sum()
        ),
        "baseline_winners_turned_negative": int(
            (affected.baseline_net.gt(0) & affected.overlay_net.le(0)).sum()
        ),
        "baseline_severe_losses_avoided": int(
            (affected.baseline_net.le(-0.10) & affected.overlay_net.gt(-0.10)).sum()
        ),
        "trades_improved": int(affected.overlay_net.gt(affected.baseline_net).sum()),
        "trades_harmed": int(affected.overlay_net.lt(affected.baseline_net).sum()),
        "affected_mean_return_delta": (
            None
            if affected.empty
            else float((affected.overlay_net - affected.baseline_net).mean())
        ),
    }

    annual_baseline = v13.annual_nav_metrics(baseline_nav)
    annual_overlay = v13.annual_nav_metrics(overlay_nav)
    annual_portfolio = []
    for left, right in zip(annual_baseline, annual_overlay, strict=True):
        if left["year"] != right["year"]:
            raise ResearchError("annual NAV comparison misalignment")
        annual_portfolio.append(
            {
                "year": left["year"],
                "baseline": left,
                "overlay": right,
                "delta": metric_delta(
                    left,
                    right,
                    ["return", "max_drawdown", "sharpe", "average_utilization"],
                ),
            }
        )

    result = {
        "experiment": EXPERIMENT,
        "research_status": "POST_HOC_CHART_GENERATED_DEVELOPMENT_TEST",
        "rule": "At D5 close, if max high through D5 is below half of the frozen target and D4/D5 closes are below entry cost, exit at the first later legal open.",
        "sample": {
            "signal_start": str(baseline.signal_date.min().date()),
            "signal_end": str(baseline.signal_date.max().date()),
            "trades": int(len(baseline)),
            "post_2020_signal_cohort_outcomes_read": False,
            "december_2020_lifecycle_completion_max_date": "2021-01-21",
            "post_2023_outcomes_read": False,
            "cy011_read": False,
        },
        "rule_audit": rule_audit,
        "baseline_trade_metrics": baseline_metrics,
        "overlay_trade_metrics": overlay_metrics,
        "trade_metric_delta": trade_delta,
        "outcome_transfer": outcome_transfer,
        "baseline_portfolio": baseline_portfolio,
        "overlay_portfolio": overlay_portfolio,
        "portfolio_delta": portfolio_delta,
        "annual_trade_comparison": group_comparison(
            baseline.assign(year=baseline.signal_date.dt.year.astype(str)),
            overlay.assign(year=overlay.signal_date.dt.year.astype(str)),
            "year",
        ),
        "lane_comparison": group_comparison(baseline, overlay, "lane"),
        "annual_portfolio_comparison": annual_portfolio,
        "audit": audit,
        "source_hashes": source_hashes,
        "interpretation": (
            "The rule is retained only if it improves portfolio return/risk without "
            "using post-2020 trade outcomes. No neighboring threshold or rescue is allowed."
        ),
    }

    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "overlay_trades": OUT / "overlay_trades.parquet",
        "trigger_diagnostics": OUT / "trigger_diagnostics.parquet",
        "baseline_nav": OUT / "baseline_portfolio_nav.parquet",
        "overlay_nav": OUT / "overlay_portfolio_nav.parquet",
    }
    write_parquet(overlay, artifacts["overlay_trades"])
    write_parquet(diagnostics, artifacts["trigger_diagnostics"])
    write_parquet(baseline_nav, artifacts["baseline_nav"])
    write_parquet(overlay_nav, artifacts["overlay_nav"])
    result_path = OUT / "result.json"
    write_json(result_path, result)
    write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (*artifacts.values(), result_path)
        },
    )
    return result


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
