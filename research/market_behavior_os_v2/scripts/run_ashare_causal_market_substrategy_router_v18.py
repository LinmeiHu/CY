#!/usr/bin/env python3
"""Causal market-state router over the frozen V13R1 and V15 short lanes.

This runner never reconstructs security outcomes.  It uses only the frozen
trade ledgers and the completed-close causal market panel.  Candidate gate
selection is confined to 2014-2020; 2021-2023 are reported only afterward.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as v13  # noqa: E402
import run_ashare_causal_bull_bear_dual_mechanism_short_v16 as v16  # noqa: E402


EXPERIMENT = "ASHARE-CAUSAL-MARKET-SUBSTRATEGY-ROUTER-V18"
ROOT = Path("/Volumes/quant/CY_quant_research")
OUT = ROOT / "ashare_causal_market_substrategy_router_v18"
REGIME = v13.REGIME
CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "experiments/ASHARE-CAUSAL-MARKET-SUBSTRATEGY-ROUTER-V18_contract.json"
)
SELECTION_END = pd.Timestamp("2020-12-31")
CHALLENGE_START = pd.Timestamp("2021-01-01")
EXPECTED = {
    "bear": v16.EXPECTED["bear"],
    "bull": v16.EXPECTED["bull"],
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
}


class ResearchError(RuntimeError):
    """Fail closed on source, causality, selection, or execution drift."""


def bull_acceleration_mask(frame: pd.DataFrame) -> pd.Series:
    """Return the one-condition, completed-close BULL acceleration gate."""
    required = ["market_median_ret20", "market_median_ret60"]
    valid = frame[required].notna().all(axis=1)
    finite = np.isfinite(frame[required]).all(axis=1)
    return valid & finite & frame.market_median_ret20.ge(frame.market_median_ret60)


def candidate_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Bounded economically interpretable market-state candidate family."""
    return {
        "ALL_BULL": pd.Series(True, index=frame.index),
        "STRONG_60": frame.market_median_ret60.ge(0.05)
        & frame.market_positive_ret60_share.ge(0.60),
        "STRONG_20": frame.market_median_ret20.ge(0.02)
        & frame.market_positive_ret20_share.ge(0.60),
        "STRONG_BOTH": frame.market_median_ret60.ge(0.05)
        & frame.market_positive_ret60_share.ge(0.60)
        & frame.market_median_ret20.ge(0.02)
        & frame.market_positive_ret20_share.ge(0.60),
        "BREADTH_ACCELERATION": frame.market_positive_ret20_share.ge(
            frame.market_positive_ret60_share
        ),
        "RETURN_ACCELERATION": bull_acceleration_mask(frame),
        "STRONG60_AND_BREADTH_ACCELERATION": frame.market_median_ret60.ge(0.05)
        & frame.market_positive_ret60_share.ge(0.60)
        & frame.market_median_ret20.ge(0.02)
        & frame.market_positive_ret20_share.ge(0.60)
        & frame.market_positive_ret20_share.ge(frame.market_positive_ret60_share),
    }


def evaluate_bull_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    """Evaluate candidate gates only on rows at or before SELECTION_END."""
    train = frame.loc[frame.signal_date.le(SELECTION_END)].copy()
    rows: list[dict[str, Any]] = []
    for name, mask in candidate_masks(train).items():
        part = train.loc[mask]
        metrics = v13.trade_metrics(part)
        rows.append(
            {
                "candidate": name,
                "selection_rows": int(len(part)),
                "mean_net": metrics["mean_net"],
                "median_net": metrics["median_net"],
                "win_rate": metrics["win_rate"],
                "severe10": metrics["severe10"],
                "average_holding_sessions": metrics["average_holding_sessions"],
                "latest_selection_signal_date": (
                    None if part.empty else part.signal_date.max()
                ),
            }
        )
    result = pd.DataFrame(rows).sort_values(
        ["mean_net", "candidate"], ascending=[False, True], kind="mergesort"
    )
    result["selection_rank"] = np.arange(1, len(result) + 1)
    return result.reset_index(drop=True)


def attach_market_state(frame: pd.DataFrame) -> pd.DataFrame:
    regime = pd.read_parquet(REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date).dt.normalize()
    columns = [
        "trade_date",
        "market_median_ret20",
        "market_median_ret60",
        "market_positive_ret20_share",
        "market_positive_ret60_share",
        "market_regime",
        "latest_source_timestamp",
    ]
    routed = frame.merge(
        regime[columns],
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    required = columns[1:]
    if routed[required].isna().any(axis=None):
        raise ResearchError("missing required causal market-state input")
    return routed.drop(columns="trade_date")


def route_lanes(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    bull = frame.market_route.eq("BULL")
    bear = frame.market_route.eq("BEAR")
    accelerating = bull_acceleration_mask(frame)
    keep = bear | (bull & accelerating)
    routed = frame.loc[keep].copy()
    routed["router_state"] = np.where(
        routed.market_route.eq("BEAR"), "BEAR_REPAIR", "BULL_ACCELERATING"
    )
    cash = frame.loc[~keep].copy()
    cash["router_state"] = np.where(
        cash.market_route.eq("BULL"), "BULL_DECELERATING_CASH", "UNROUTABLE_CASH"
    )
    return routed, cash


def router_causal_audit(
    accepted: pd.DataFrame, cash: pd.DataFrame, candidate_table: pd.DataFrame
) -> dict[str, Any]:
    bull_ids = accepted.loc[accepted.market_route.eq("BULL"), ["event_id"]]
    bear_ids = accepted.loc[accepted.market_route.eq("BEAR"), ["event_id"]]
    bull_decisions = v16.duckdb.sql(
        f"SELECT event_id,decision_at FROM read_parquet('{v16.BULL_FEATURES.as_posix()}')"
    ).df()
    bear_decisions = pd.read_parquet(v16.BEAR, columns=["event_id", "signal_decision_at"])
    bull = accepted.loc[accepted.market_route.eq("BULL")].merge(
        bull_decisions.merge(bull_ids, on="event_id", how="inner"),
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    bear = accepted.loc[accepted.market_route.eq("BEAR")].merge(
        bear_decisions.merge(bear_ids, on="event_id", how="inner"),
        on="event_id",
        how="left",
        validate="one_to_one",
    )
    return {
        "selected_candidate": str(candidate_table.iloc[0].candidate),
        "selection_latest_signal_after_2020_count": int(
            pd.to_datetime(candidate_table.latest_selection_signal_date)
            .dropna()
            .gt(SELECTION_END)
            .sum()
        ),
        "challenge_rows_used_for_selection_count": 0,
        "router_missing_market_input_count": int(
            accepted[
                [
                    "market_median_ret20",
                    "market_median_ret60",
                    "market_positive_ret20_share",
                    "market_positive_ret60_share",
                    "latest_source_timestamp",
                ]
            ]
            .isna()
            .any(axis=1)
            .sum()
        ),
        "router_market_timestamp_after_signal_count": int(
            (pd.to_datetime(bull.latest_source_timestamp) > pd.to_datetime(bull.decision_at)).sum()
            + (
                pd.to_datetime(bear.latest_source_timestamp)
                > pd.to_datetime(bear.signal_decision_at)
            ).sum()
        ),
        "bull_base_state_violation_count": int(
            bull.market_regime.ne("BULL").sum()
        ),
        "bull_acceleration_gate_violation_count": int(
            (~bull_acceleration_mask(bull)).sum()
        ),
        "bear_base_state_violation_count": int(
            bear.market_regime.ne("BEAR").sum()
        ),
        "cash_routed_bull_acceleration_pass_count": int(
            bull_acceleration_mask(cash.loc[cash.market_route.eq("BULL")]).sum()
        ),
    }


def run() -> dict[str, Any]:
    for path in (v16.BEAR, v16.BULL, v16.BULL_FEATURES, REGIME, CONTRACT):
        if not path.is_file():
            raise ResearchError(f"missing input: {path}")
    actual = {
        "bear": v16.sha256(v16.BEAR),
        "bull": v16.sha256(v16.BULL),
        "regime": v16.sha256(REGIME),
    }
    if actual != EXPECTED:
        raise ResearchError(f"frozen source drift: {actual}")

    raw = attach_market_state(v16.load_lanes())
    bull_raw = raw.loc[raw.market_route.eq("BULL")].copy()
    candidates = evaluate_bull_candidates(bull_raw)
    if str(candidates.iloc[0].candidate) != "RETURN_ACCELERATION":
        raise ResearchError("2014-2020 bounded candidate selection drift")

    routed, cash = route_lanes(raw)
    accepted, skipped, capacity_audit = v16.apply_shared_capacity(routed)
    accepted = accepted.sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    nav, portfolio_audit = v13.replay_portfolio(accepted)
    overall = v13.trade_metrics(accepted)
    overall["average_completed_trades_per_year"] = len(accepted) / 10.0
    annual = v13.annual_trade_metrics(accepted)
    challenge = accepted.loc[accepted.signal_date.ge(CHALLENGE_START)]
    challenge_metrics = v13.trade_metrics(challenge)
    challenge_metrics["average_completed_trades_per_year"] = len(challenge) / 3.0
    lanes = {
        lane: v13.trade_metrics(part)
        for lane, part in accepted.groupby("router_state", sort=True)
    }
    audit = {
        **capacity_audit,
        **portfolio_audit,
        **router_causal_audit(accepted, cash, candidates),
        **v16.causal_source_audit(accepted),
        **v16.execution_lineage_audit(accepted),
        "event_id_duplicate_count": int(accepted.event_id.duplicated().sum()),
        "entry_at_or_before_signal_count": int(
            accepted.entry_date.le(accepted.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(
            accepted.exit_date.le(accepted.entry_date).sum()
        ),
        "t1_same_day_exit_count": int(accepted.exit_date.eq(accepted.entry_date).sum()),
        "true_duplicate_active_symbol_count": int(v13.true_overlap_count(accepted)),
        "post_2023_signal_count": int(accepted.signal_date.dt.year.gt(2023).sum()),
        "post_2023_exit_count": int(accepted.exit_date.dt.year.gt(2023).sum()),
        "repository_2024_plus_data_opened": False,
    }
    scalar_zero_keys = [
        "negative_cash_count",
        "open_position_at_end_count",
        "selection_latest_signal_after_2020_count",
        "challenge_rows_used_for_selection_count",
        "router_missing_market_input_count",
        "router_market_timestamp_after_signal_count",
        "bull_base_state_violation_count",
        "bull_acceleration_gate_violation_count",
        "bear_base_state_violation_count",
        "cash_routed_bull_acceleration_pass_count",
        "bear_missing_rank_input_count",
        "bear_prior10_gate_violation_count",
        "bear_breadth_repair_violation_count",
        "bull_available_after_signal_count",
        "bull_regime_after_signal_count",
        "bull_non_bull_route_count",
        "bull_setup_not_before_signal_count",
        "bull_trigger_after_five_sessions_count",
        "bull_signal_close_breakout_violation_count",
        "bull_earlier_strict_tick_breakout_count",
        "bull_missing_rank_input_count",
        "entry_execution_violation_count",
        "target_execution_violation_count",
        "open_exit_execution_violation_count",
        "corporate_action_coordinate_lineage_violation_count",
        "event_id_duplicate_count",
        "entry_at_or_before_signal_count",
        "exit_at_or_before_entry_count",
        "t1_same_day_exit_count",
        "true_duplicate_active_symbol_count",
        "post_2023_signal_count",
        "post_2023_exit_count",
    ]
    required_zero = [audit[key] for key in scalar_zero_keys]
    required_zero.extend(audit["bear_timestamp_after_signal_count_by_field"].values())
    if any(required_zero):
        raise ResearchError(f"V18 audit failed: {audit}")

    gates = {
        "average_trades_per_year_gt_50": overall["average_completed_trades_per_year"] > 50,
        "mean_net_gt_3pct": overall["mean_net"] > 0.03,
        "average_holding_sessions_le_15": overall["average_holding_sessions"] <= 15,
        "2022_mean_net_gt_3pct": annual[8]["mean_net"] > 0.03,
        "2023_mean_net_gt_3pct": annual[9]["mean_net"] > 0.03,
        "challenge_mean_net_gt_3pct": challenge_metrics["mean_net"] > 0.03,
        "mean_excluding_best5_dates_positive": overall[
            "mean_excluding_best5_signal_dates"
        ]
        > 0,
    }
    verdict = (
        "CAUSAL_MARKET_SUBSTRATEGY_ROUTER_HISTORICAL_GOAL_MET"
        if all(gates.values())
        else "CAUSAL_MARKET_SUBSTRATEGY_ROUTER_GOAL_NOT_MET"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    paths = {
        "accepted": OUT / "accepted_trades.parquet",
        "cash": OUT / "cash_routed_trades.parquet",
        "skipped": OUT / "capacity_skipped_trades.parquet",
        "candidates": OUT / "development_candidate_table.parquet",
        "nav": OUT / "portfolio_nav.parquet",
    }
    v16.write_parquet(accepted, paths["accepted"])
    v16.write_parquet(cash, paths["cash"])
    v16.write_parquet(skipped, paths["skipped"])
    v16.write_parquet(candidates, paths["candidates"])
    v16.write_parquet(nav, paths["nav"])
    candidate_records = candidates.copy()
    candidate_records["latest_selection_signal_date"] = pd.to_datetime(
        candidate_records.latest_selection_signal_date
    ).dt.strftime("%Y-%m-%d")
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "routing": {
            "BEAR_REPAIR": "V13R1 fast-capitulation active-demand T10/H20",
            "BULL_ACCELERATING": "V15 delayed supply-contraction T10/H20",
            "BULL_DECELERATING": "HOLD_CASH",
            "TRANSITION": "HOLD_CASH",
        },
        "selected_bull_gate": "market_median_ret20 >= market_median_ret60",
        "development_candidate_table": candidate_records.to_dict("records"),
        "overall": overall,
        "lanes": lanes,
        "challenge_2021_2023": challenge_metrics,
        "annual": annual,
        "portfolio": v13.nav_metrics(nav),
        "annual_portfolio": v13.annual_nav_metrics(nav),
        "gates": gates,
        "audit": audit,
        "contract_sha256": v16.sha256(CONTRACT),
        "source_hashes": actual,
        "post_observation_warning": (
            "2021-2023 are chronological diagnostics but not pristine because "
            "predecessor outcomes were already observed."
        ),
    }
    result_path = OUT / "result.json"
    v16.write_json(result_path, result)
    v16.write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: {"bytes": path.stat().st_size, "sha256": v16.sha256(path)}
            for path in (*paths.values(), result_path)
        },
    )
    return result


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
