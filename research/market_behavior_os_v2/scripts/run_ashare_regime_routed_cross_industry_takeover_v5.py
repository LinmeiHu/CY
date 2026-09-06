#!/usr/bin/env python3
"""Evaluate V5: route seller-cost takeovers by causal market state.

Development is quarantined to signals through 2021-11-30 and market/outcome
bars through 2021-12-31. Challenge mode is fail-closed until an immutable
development freeze records that every robustness gate passed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

import run_ashare_cross_industry_sell_pressure_depressed_takeover_v3 as v3


mother = v3.mother
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-REGIME-ROUTED-CROSS-INDUSTRY-TAKEOVER-V5"
FREEZE = OS_ROOT / f"experiments/{EXPERIMENT}_freeze.json"
OUTPUT_ROOT = Path("/Volumes/quant/CY_quant_research") / EXPERIMENT.lower()
EXPECTED_FREEZE_SHA256 = "b173048b185841695762a7ffd316ba8d7995974c88c40063daeb31a1f63190b3"

MIN_TAKEOVER_STOCKS = 11
MIN_TAKEOVER_INDUSTRIES = 8
MAX_PER_INDUSTRY = 3
DEEP_MARKET_RETURN_60 = -0.10


class ResearchError(RuntimeError):
    """Fail closed on chronology, identity, market state, or freeze drift."""


def market_regime_table(daily: Path, max_signal_date: str) -> pd.DataFrame:
    """Build a same-close, cross-sectional 60-session market return."""
    con = duckdb.connect()
    market = con.execute(
        f"""
        WITH lagged AS (
          SELECT trade_date,adjusted_close/nullif(
            lag(adjusted_close,60) OVER (PARTITION BY symbol ORDER BY cal_idx),0.0
          )-1.0 AS derived_ret60,
            hard_valid,history_valid,current_valid,current_day_data_tradable,
            market_rule_valid,corporate_action_valid,corporate_action_blocking,is_st
          FROM read_parquet('{daily.as_posix()}')
          WHERE trade_date<=DATE '{max_signal_date}'
        )
        SELECT trade_date,
          median(derived_ret60) FILTER (WHERE
            hard_valid AND history_valid AND current_valid
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND NOT is_st AND derived_ret60 IS NOT NULL
          ) AS market_median_ret60,
          count(derived_ret60) FILTER (WHERE
            hard_valid AND history_valid AND current_valid
            AND current_day_data_tradable AND market_rule_valid
            AND corporate_action_valid AND NOT corporate_action_blocking
            AND NOT is_st AND derived_ret60 IS NOT NULL
          ) AS market_valid_count
        FROM lagged
        GROUP BY trade_date
        ORDER BY trade_date
        """
    ).fetchdf()
    con.close()
    market["trade_date"] = pd.to_datetime(market.trade_date)
    return market


def attach_market_regime(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    """Attach a same-close market state, failing closed if it is unavailable.

    The rolling return is computed independently for every symbol using only
    observations no later than the latest candidate close. The daily market
    state is the median across the valid, tradable, non-ST PIT universe. The
    challenge asset starts in 2022, so only dates lacking its 60-session warmup
    use the separately frozen historical asset; current-asset values always win.
    """
    if candidates.empty:
        result = candidates.copy()
        result["market_median_ret60"] = pd.Series(dtype=float)
        result["market_valid_count"] = pd.Series(dtype="int64")
        return result
    max_signal_date = pd.to_datetime(candidates.signal_date).max().date().isoformat()
    market = market_regime_table(daily, max_signal_date)
    if daily == mother.CURRENT_DAILY:
        historical = market_regime_table(mother.OLD_DAILY, max_signal_date)
        market = market.merge(
            historical,
            on="trade_date",
            how="outer",
            suffixes=("", "_historical"),
            validate="one_to_one",
        )
        fallback = market.market_median_ret60.isna()
        market.loc[fallback, "market_median_ret60"] = market.loc[
            fallback, "market_median_ret60_historical"
        ]
        market.loc[fallback, "market_valid_count"] = market.loc[
            fallback, "market_valid_count_historical"
        ]
        market = market[["trade_date", "market_median_ret60", "market_valid_count"]]
    result = candidates.merge(
        market,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    required = ["market_median_ret60", "market_valid_count"]
    if result[required].isna().any().any() or result.market_valid_count.le(0).any():
        raise ResearchError("missing required same-close market regime")
    return result.drop(columns="trade_date")


def select(candidates: pd.DataFrame, daily: Path) -> pd.DataFrame:
    work = v3.attach_features(candidates, daily)
    work = work.loc[
        work.signal_close.ge(work.prior_high)
        & work.signal_turnover.ge(1.5 * work.signal_prior20_turnover)
    ].copy()
    work["same_date_takeover_count"] = work.groupby("signal_date")[
        "event_id"
    ].transform("size")
    work["same_date_industry_count"] = work.groupby("signal_date")[
        "causal_industry"
    ].transform("nunique")
    work = work.loc[
        work.same_date_takeover_count.ge(MIN_TAKEOVER_STOCKS)
        & work.same_date_industry_count.ge(MIN_TAKEOVER_INDUSTRIES)
    ].copy()
    work = attach_market_regime(work, daily)
    admitted = (
        work.market_median_ret60.ge(0.0)
        | work.market_median_ret60.le(DEEP_MARKET_RETURN_60)
    )
    work = work.loc[admitted].copy()
    work["market_route"] = "BULL_TREND"
    work.loc[
        work.market_median_ret60.le(DEEP_MARKET_RETURN_60), "market_route"
    ] = "DEEP_CAPITULATION"

    # Prefer the strongest observed supply shock, while capping duplicate
    # exposure to any one point-in-time industry.
    work = work.sort_values(
        ["signal_date", "causal_industry", "anchor_return", "symbol", "event_id"],
        kind="mergesort",
    )
    work["industry_rank"] = work.groupby(
        ["signal_date", "causal_industry"], sort=False
    ).cumcount() + 1
    work = work.loc[work.industry_rank.le(MAX_PER_INDUSTRY)].copy()
    work = work.sort_values(
        ["signal_date", "industry_rank", "anchor_return", "symbol", "event_id"],
        kind="mergesort",
    )
    work["diversified_rank"] = work.groupby("signal_date", sort=False).cumcount() + 1
    # V3's unchanged replay serializes this field; it is only an audit rank.
    work["depressed_rank"] = work.diversified_rank
    work = work.reset_index(drop=True)
    if work.event_id.duplicated().any():
        raise ResearchError("duplicate selected event")
    return work


def summarize(selected: pd.DataFrame, outcomes: pd.DataFrame, years: list[int]) -> dict[str, Any]:
    pooled = v3.metrics(outcomes)
    yearly = {
        str(year): v3.metrics(
            outcomes.loc[pd.to_datetime(outcomes.signal_date).dt.year.eq(year)]
        )
        for year in years
    }
    complete = outcomes.loc[outcomes.status.eq("COMPLETED")].copy()
    by_date = (
        complete.groupby("signal_date", as_index=False)
        .agg(
            completed=("event_id", "size"),
            mean_net=("net_return", "mean"),
            mean_holding=("holding_sessions", "mean"),
        )
        if not complete.empty
        else pd.DataFrame()
    )
    top10_ids = set(
        selected.loc[selected.diversified_rank.le(10), "event_id"].astype(str)
    )
    top10 = v3.metrics(outcomes.loc[outcomes.event_id.astype(str).isin(top10_ids)])
    completed_per_year = pooled["completed"] / len(years)
    date_equal_mean = None if by_date.empty else float(by_date.mean_net.mean())
    largest_date_share = None if by_date.empty else float(by_date.completed.max() / len(complete))
    gates = {
        "completed_per_year_gt_50": completed_per_year > 50,
        "pooled_mean_net_ge_4pct": pooled["mean_net"] is not None and pooled["mean_net"] >= 0.04,
        "pooled_mean_holding_lt_15": pooled["mean_holding"] is not None and pooled["mean_holding"] < 15,
        "signal_date_equal_mean_ge_4pct": date_equal_mean is not None and date_equal_mean >= 0.04,
        "diversified_top10_mean_net_ge_4pct": top10["mean_net"] is not None and top10["mean_net"] >= 0.04,
        "at_least_24_signal_dates": len(by_date) >= 24,
        "largest_date_share_le_20pct": largest_date_share is not None and largest_date_share <= 0.20,
        "every_year_has_positive_trades": all(
            row["completed"] > 0 and row["mean_net"] is not None and row["mean_net"] > 0
            for row in yearly.values()
        ),
    }
    selected_routes = selected.market_route.value_counts().sort_index().to_dict()
    complete_with_route = complete.merge(
        selected[["event_id", "market_route"]], on="event_id", validate="one_to_one"
    )
    route_metrics = {
        route: v3.metrics(complete_with_route.loc[complete_with_route.market_route.eq(route)])
        for route in sorted(selected_routes)
    }
    return {
        "selected_signals": int(len(selected)),
        "completed_per_year": float(completed_per_year),
        "pooled": pooled,
        "yearly": yearly,
        "distinct_signal_dates": int(len(by_date)),
        "signal_date_equal_weight_mean_net": date_equal_mean,
        "largest_date_share": largest_date_share,
        "positive_signal_date_share": None if by_date.empty else float(by_date.mean_net.gt(0).mean()),
        "diversified_top10_per_date": top10,
        "selected_by_market_route": selected_routes,
        "completed_metrics_by_market_route": route_metrics,
        "by_signal_date": by_date.to_dict("records"),
        "gates": gates,
        "all_gates_pass": bool(all(gates.values())),
    }


def verify_challenge_authorization() -> dict[str, Any]:
    if not FREEZE.is_file():
        raise ResearchError("final V5 freeze missing; challenge remains closed")
    if mother.execution.sha256(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise ResearchError("final V5 freeze drift")
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    result_path = OUTPUT_ROOT / "development/result.json"
    if not result_path.is_file():
        raise ResearchError("development result missing; challenge remains closed")
    expected_result = freeze.get("development_artifacts", {}).get("result_sha256")
    if mother.execution.sha256(result_path) != expected_result:
        raise ResearchError("frozen V5 development result drift")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("summary", {}).get("all_gates_pass"):
        raise ResearchError("V5 development gates failed; challenge remains closed")
    return freeze


def run(mode: str) -> dict[str, Any]:
    if mode == "development":
        daily = mother.OLD_DAILY
        v3.verify_common(daily, v3.EXPECTED["development_daily"])
        if mother.execution.sha256(v3.DEV_SOURCE) != v3.EXPECTED["development_candidates"]:
            raise ResearchError("frozen development candidate drift")
        candidates = pd.read_parquet(v3.DEV_SOURCE)
        candidates = candidates.loc[
            pd.to_datetime(candidates.signal_date).between("2014-01-01", "2021-11-30")
        ].copy()
        outcome_end = "2021-12-31"
        years = list(range(2014, 2022))
    else:
        verify_challenge_authorization()
        daily = mother.CURRENT_DAILY
        v3.verify_common(daily, v3.EXPECTED["challenge_daily"])
        if mother.execution.sha256(mother.OLD_DAILY) != v3.EXPECTED["development_daily"]:
            raise ResearchError("historical market-regime fallback drift")
        candidates = mother.build_candidates(daily, "2022-01-01", "2025-12-31")
        outcome_end = "2026-03-31"
        years = list(range(2022, 2026))

    selected = select(candidates, daily)
    paths = mother.build_paths(daily, selected, outcome_end)
    paths = v3.attach_market_returns(paths, daily, outcome_end)
    outcomes = v3.replay(selected, paths)
    summary = summarize(selected, outcomes, years)
    output = OUTPUT_ROOT / mode
    output.mkdir(parents=True, exist_ok=True)
    mother.execution.write_parquet(selected, output / "selected_candidates.parquet")
    mother.execution.write_parquet(paths, output / "future_paths.parquet")
    mother.execution.write_parquet(outcomes, output / "outcomes.parquet")
    result = {
        "experiment": EXPERIMENT,
        "mode": mode,
        "summary": summary,
        "status_counts": outcomes.status.value_counts().sort_index().to_dict(),
        "future_market_function": False,
        "same_bar_fill": False,
        "round_trip_cost": v3.ROUND_TRIP_COST,
        "market_regime_source": (
            "frozen development daily"
            if mode == "development"
            else "current daily with frozen historical fallback only during 60-session warmup"
        ),
        "date_quarantine": {
            "signal_end": "2021-11-30" if mode == "development" else "2025-12-31",
            "outcome_end": outcome_end,
        },
    }
    mother.execution.write_json(output / "result.json", result)
    result["output_hashes"] = {
        name: mother.execution.sha256(output / name)
        for name in ("selected_candidates.parquet", "future_paths.parquet", "outcomes.parquet", "result.json")
    }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("development", "challenge"), required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.mode), ensure_ascii=False, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
