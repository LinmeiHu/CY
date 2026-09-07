from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

from .compare import compare_parquet
from .errors import ReproductionError
from .execution.daily import (
    fixed_target_outcomes,
    load_daily,
    replay_shared_router,
    replay_sleeves,
    strict_fixed_target_outcomes,
)
from .io import load_input_config, sha256, write_json, write_parquet
from .strategies import ogr
from .strategies.atrdr import (
    build_market_state,
    build_oai_mother,
    build_simple_bull,
    build_slow_mother,
    route_v27_bear,
    select_fast_bear,
    select_fast_capacity,
)
from .strategies.atrdr_post import (
    apply_capacity as apply_v27_capacity,
)
from .strategies.atrdr_post import (
    build_bull_accelerating,
    build_bull_decelerating,
    replay_bull_decelerating,
    standardize_routes,
)
from .strategies.atrdr_post import (
    build_fast_bear as build_post_fast_bear,
)
from .strategies.atrdr_post import (
    replay_portfolio as replay_v27_portfolio,
)
from .strategies.ifcgr import select_issuer_facts
from .strategies.mcb import build_v53, build_v64, build_v65, build_v72
from .strategies.smv6 import FROZEN_SHA256 as SMV6_SHA256
from .strategies.smv6 import run_local as run_smv6_local


def run_mcb(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    v53 = build_v53(inputs["daily_hist"], inputs["mcb_market_industry_state"], output / "v53.parquet")
    v64 = build_v64(v53, output / "v64.parquet")
    v65 = build_v65(v53, output / "v65.parquet")
    v72 = build_v72(v65, output / "signals.parquet")
    daily = load_daily([inputs["daily_hist"], inputs["daily_tail"]], v72.symbol.tolist())
    outcomes = fixed_target_outcomes(v72, daily, target=0.15, horizon=15, profile="T15_H15_NO_STOP")
    for column in ("industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"):
        outcomes = outcomes.merge(v72[["event_id", column]], on="event_id", how="left", validate="one_to_one")
    write_parquet(outcomes, output / "trades.parquet")
    accepted, skipped, nav, metrics = replay_sleeves(
        outcomes,
        daily,
        rank_columns=("industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"),
        k_per_sleeve=30,
        daily_cap=10,
    )
    write_parquet(accepted, output / "accepted.parquet")
    write_parquet(skipped, output / "skipped.parquet")
    write_parquet(nav, output / "nav.parquet")
    write_json(output / "result.json", {"strategy": "MCB", "metrics": metrics, "counts": {"v53": len(v53), "v64": len(v64), "v65": len(v65), "signals": len(v72), "outcomes": len(outcomes), "accepted": len(accepted), "nav": len(nav)}})
    return {"strategy": "MCB", "status": "FULL_END_TO_END_REPRODUCIBLE", "metrics": metrics}


def run_ogr(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    """Run the audited V13 -> V27 -> V28 -> V28R1 -> V28R2 chain."""
    output.mkdir(parents=True, exist_ok=True)
    layers = ogr.build_signal_chain(
        inputs["daily_hist"],
        inputs["raw_minute_root"],
        inputs["cy033_daily_amount"],
        output,
    )
    signals = layers["v28r2"]
    daily = ogr.load_daily(inputs["daily_hist"], end="2022-03-31")
    actions = ogr.load_actions(
        inputs["qd010_distributions"],
        inputs["qd010_rights"],
        signals.symbol.astype(str).tolist(),
    )
    entries = ogr.build_entries(signals, daily, inputs["raw_minute_root"], actions)
    outcomes = ogr.build_outcomes(entries, daily, inputs["raw_minute_root"], actions)
    accepted, skipped, nav = ogr.replay_portfolio(outcomes, daily)
    write_parquet(entries, output / "entries.parquet")
    write_parquet(outcomes, output / "trades.parquet")
    write_parquet(accepted, output / "accepted.parquet")
    write_parquet(skipped, output / "skipped.parquet")
    write_parquet(nav, output / "nav.parquet")
    result = {
        "strategy": "OGR",
        "status": "FULL_END_TO_END_REPRODUCIBLE",
        "counts": {
            "v13": len(layers["v13"]),
            "v27": len(layers["v27"]),
            "v28": len(layers["v28"]),
            "v28r1": len(layers["v28r1"]),
            "signals": len(signals),
            "executable": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
            "outcomes": len(outcomes),
            "accepted": len(accepted),
            "nav": len(nav),
        },
    }
    write_json(output / "result.json", result)
    return result


def run_ifcgr(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    """Generate OGR in the same run, then apply the frozen PIT-B fact gate."""
    output.mkdir(parents=True, exist_ok=True)
    ogr_output = output / "parent_ogr"
    parent_result = run_ogr(inputs, ogr_output)
    parents = pd.read_parquet(ogr_output / "signals.parquet")
    kept, rejected, facts = select_issuer_facts(
        parents,
        inputs["ifcgr_route_index"],
        inputs["ifcgr_sse_titles"],
        inputs["ifcgr_szse_titles"],
    )
    parent_trades = pd.read_parquet(ogr_output / "trades.parquet")
    trades = parent_trades.loc[
        parent_trades.gap_id.isin(set(kept.gap_id.astype(str)))
    ].copy()
    daily = ogr.load_daily(inputs["daily_hist"], end="2022-03-31")
    accepted, skipped, nav = ogr.replay_portfolio(trades, daily)
    write_parquet(parents, output / "parent_population.parquet")
    write_parquet(facts, output / "fact_matches.parquet")
    write_parquet(kept, output / "kept.parquet")
    write_parquet(rejected, output / "rejected.parquet")
    write_parquet(trades, output / "trades.parquet")
    write_parquet(accepted, output / "accepted.parquet")
    write_parquet(skipped, output / "skipped.parquet")
    write_parquet(nav, output / "nav.parquet")
    result = {
        "strategy": "IFCGR",
        "status": "END_TO_END_REPRODUCIBLE_WITH_PIT_B",
        "pit_classification": "PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE",
        "parent": parent_result,
        "counts": {
            "parents": len(parents),
            "facts": len(facts),
            "kept": len(kept),
            "rejected": len(rejected),
            "outcomes": len(trades),
            "accepted": len(accepted),
            "nav": len(nav),
        },
    }
    write_json(output / "result.json", result)
    return result


def run_smv6(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    """Run exact frozen callbacks and a separate deterministic cash execution."""
    output.mkdir(parents=True, exist_ok=True)
    strategy_events, local_events, accounts = run_smv6_local(
        inputs["smv6_qmt_root"],
        inputs["smv6_hybrid_root"],
        start=date(2010, 1, 1),
        end=date(2026, 8, 28),
    )
    write_parquet(strategy_events, output / "events.parquet")
    write_parquet(local_events, output / "local_execution_events.parquet")
    write_parquet(accounts, output / "nav.parquet")
    result = {
        "strategy": "SMV6",
        "status": "LOCAL_END_TO_END_REPRODUCIBLE_PLATFORM_EQUIVALENCE_UNVERIFIED",
        "strategy_source_sha256": SMV6_SHA256,
        "counts": {
            "strategy_events": len(strategy_events),
            "local_execution_events": len(local_events),
            "nav": len(accounts),
        },
        "minimum_cash": float(accounts.cash.min()),
        "local_execution": {
            "lot_size": 100,
            "commission_rate": 0.0002,
            "slippage_total": 0.0016,
            "slippage_per_side": 0.0008,
            "minute_volume_limit": 0.5,
        },
        "native_platform_equivalence": "UNVERIFIED",
    }
    write_json(output / "result.json", result)
    return result


def _legacy_v27_outcomes(
    candidates: pd.DataFrame,
    daily: pd.DataFrame,
    *,
    candidate_source: bool = False,
) -> pd.DataFrame:
    frame = strict_fixed_target_outcomes(
        candidates,
        daily,
        target=0.10,
        horizon=20,
        profile="T10_H20_NO_STOP",
        max_path_sessions=100,
    )
    frame["target_return"], frame["horizon_sessions"] = 0.10, 20
    if candidate_source:
        frame = frame.merge(
            candidates[["event_id", "candidate_source"]],
            on="event_id", how="left", validate="one_to_one",
        )
    return frame


def _run_atrdr_post_interval(
    daily: Path,
    output: Path,
    *,
    start: str,
    signal_end: str,
    nav_end: str,
    expected_sha256: str,
    maturity_lag: int | None = None,
) -> dict[str, object]:
    if sha256(daily) != expected_sha256:
        raise ReproductionError(f"registered ATRDR daily asset/version mismatch: {daily}")
    stage_a, stage_b = output / "stage_a", output / "stage_b"
    stage_a.mkdir(parents=True, exist_ok=True)
    stage_b.mkdir(parents=True, exist_ok=True)
    market = build_market_state(
        daily, stage_a / "market.parquet", start=start, end=signal_end,
        history_start="2022-01-04", post_v27_contract=True,
    )
    fast = build_post_fast_bear(
        daily, market, stage_a / "fast_candidates.parquet", start=start, end=signal_end
    )
    slow_all = build_slow_mother(
        daily, stage_a / "market.parquet", stage_a / "slow_mother_all.parquet",
        history_start="2022-01-04", start=start, end=signal_end,
    )
    slow = slow_all.merge(
        market[["trade_date", "market_median_ret20", "market_median_ret60", "latest_source_timestamp"]],
        left_on="signal_date", right_on="trade_date", how="left", validate="many_to_one",
    )
    deep_market = slow.market_median_ret60.le(-0.05)
    slow = slow.loc[
        slow.market_regime.eq("BEAR")
        & slow.market_median_ret20.ge(slow.market_median_ret60)
        & (~deep_market | slow.exact_prior20_return.le(-0.15) | slow.last5_downside_turnover.le(0.01))
    ].copy()
    slow["lane"] = "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    slow["rank1"] = slow.previous5_downside_turnover - slow.last5_downside_turnover
    slow["rank2"], slow["rank3"] = -slow.exact_prior20_return, slow.close_location
    accelerating = build_bull_accelerating(
        daily, market, stage_a / "bull_accelerating_candidates.parquet",
        start=start, end=signal_end,
    )
    decelerating = build_bull_decelerating(
        daily, market, stage_a / "bull_decelerating_candidates.parquet",
        start=start, end=signal_end,
    )

    mature_cal_idx: int | None = None
    if maturity_lag is not None:
        con = duckdb.connect()
        try:
            mature_cal_idx = int(con.execute(
                f"SELECT max(cal_idx)-{maturity_lag} FROM read_parquet('{daily.as_posix()}')"
            ).fetchone()[0])
        finally:
            con.close()
        fast["mature_by_fixed_horizon"] = fast.signal_cal_idx.le(mature_cal_idx)
        slow["mature_by_fixed_horizon"] = slow.signal_cal_idx.le(mature_cal_idx)
        accelerating["mature_by_fixed_horizon"] = accelerating.signal_cal_idx.le(mature_cal_idx)
        decelerating["mature_by_fixed_horizon"] = decelerating.signal_cal_idx.le(mature_cal_idx)
    write_parquet(slow, stage_a / "slow_candidates.parquet")
    write_parquet(fast, stage_a / "fast_candidates.parquet")
    write_parquet(accelerating, stage_a / "bull_accelerating_candidates.parquet")
    write_parquet(decelerating, stage_a / "bull_decelerating_candidates.parquet")

    mature_slow = slow if mature_cal_idx is None else slow.loc[slow.signal_cal_idx.le(mature_cal_idx)].copy()
    symbols = set(fast.symbol) | set(mature_slow.symbol) | set(accelerating.symbol)
    trade_daily = load_daily([daily], sorted(symbols))
    fast_outcomes = _legacy_v27_outcomes(fast, trade_daily)
    slow_outcomes = _legacy_v27_outcomes(mature_slow, trade_daily)
    accelerating_outcomes = _legacy_v27_outcomes(
        accelerating, trade_daily, candidate_source=True
    )
    decelerating_outcomes = replay_bull_decelerating(decelerating, daily)
    write_parquet(fast_outcomes, stage_b / "fast_outcomes.parquet")
    write_parquet(slow_outcomes, stage_b / "slow_outcomes.parquet")
    write_parquet(accelerating_outcomes, stage_b / "bull_accelerating_outcomes.parquet")
    write_parquet(decelerating_outcomes, stage_b / "bull_decelerating_outcomes.parquet")

    raw = standardize_routes(
        fast_outcomes, fast, slow_outcomes, mature_slow,
        accelerating_outcomes, accelerating, decelerating_outcomes, decelerating,
    )
    accepted, skipped = apply_v27_capacity(raw)
    accepted = accepted.sort_values(["entry_date", "sleeve", "event_id"], kind="mergesort").reset_index(drop=True)
    nav = replay_v27_portfolio(accepted, daily, start=start, end=nav_end)
    write_parquet(raw, stage_b / "routed_raw_trades.parquet")
    write_parquet(accepted, stage_b / "accepted_trades.parquet")
    write_parquet(skipped, stage_b / "capacity_skips.parquet")
    write_parquet(nav, stage_b / "portfolio_nav.parquet")
    return {
        "registered_daily_sha256": expected_sha256,
        "market_dates": len(market),
        "mature_signal_cal_idx": mature_cal_idx,
        "candidates": {
            "fast": len(fast), "slow": len(slow),
            "bull_accelerating": len(accelerating), "bull_decelerating": len(decelerating),
        },
        "outcomes": {
            "fast": len(fast_outcomes), "slow": len(slow_outcomes),
            "bull_accelerating": len(accelerating_outcomes),
            "bull_decelerating": len(decelerating_outcomes),
        },
        "raw_trades": len(raw), "accepted_trades": len(accepted),
        "capacity_skips": len(skipped), "nav_rows": len(nav),
    }


def run_atrdr(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    """Run the closed historical ATRDR and registered-input V27 continuations."""
    output.mkdir(parents=True, exist_ok=True)
    daily_hist = inputs["daily_hist"]
    market = build_market_state(daily_hist, output / "market_state.parquet")
    oai = build_oai_mother(daily_hist, output / "fast_oai_mother.parquet")
    fast_signal = select_fast_bear(oai, market, output / "fast_signal.parquet")
    trade_daily = load_daily([daily_hist], fast_signal.symbol.tolist())
    fast_outcomes = fixed_target_outcomes(
        fast_signal,
        trade_daily,
        target=0.10,
        horizon=20,
        profile="T10_H20_NO_STOP",
    )
    fast_fields = [
        "event_id", "step_return", "signal_decision_at", "regime_latest_source_timestamp",
        "b20_l5_source_timestamp", "market_positive_ret20_share", "b20_l5", "prior10_return",
        "close_location_x", "turnover_ratio_x", "invalid_step_cum",
        "stock_minus_industry_ret20", "close_vs_prior10_high",
    ]
    fast_outcomes = fast_outcomes.merge(fast_signal[fast_fields], on="event_id", how="left", validate="one_to_one").rename(columns={"invalid_step_cum": "signal_invalid"})
    write_parquet(fast_outcomes, output / "fast_outcomes.parquet")
    fast_accepted = select_fast_capacity(fast_outcomes, output / "fast_accepted.parquet")
    fast_accepted = fast_accepted.merge(
        fast_signal[["event_id", "market_regime", "market_median_ret20", "market_median_ret60", "latest_source_timestamp"]],
        on="event_id", how="left", validate="one_to_one",
    )

    slow = build_slow_mother(daily_hist, output / "market_state.parquet", output / "slow_mother.parquet")
    slow_daily = load_daily([daily_hist, inputs["daily_tail"]], slow.symbol.tolist())
    slow_outcomes = strict_fixed_target_outcomes(
        slow, slow_daily, target=0.10, horizon=20, profile="T10_H20_NO_STOP", max_path_sessions=100
    )
    write_parquet(slow_outcomes, output / "slow_outcomes.parquet")
    bear = route_v27_bear(fast_accepted, slow_outcomes, slow, market, output / "v27_bear_routes.parquet")

    bull = build_simple_bull(daily_hist, output / "bull_mother.parquet")
    bull_daily = load_daily([daily_hist], bull.symbol.tolist())
    bull_outcomes = fixed_target_outcomes(
        bull, bull_daily, target=0.15, horizon=15, profile="T15_H15_NO_STOP", split_cost=True
    )
    write_parquet(bull_outcomes, output / "bull_outcomes.parquet")
    bull_trades = bull_outcomes.loc[bull_outcomes.status.eq("COMPLETED")].merge(
        bull[["event_id", "lane", "industry_breadth20_delta5", "ret60", "turnover_ratio"]],
        on="event_id", how="left", validate="one_to_one",
    )
    bull_trades["source"] = "V29_SIMPLE_BULL"
    bull_trades["source_event_id"] = bull_trades.event_id.astype(str)
    bull_trades["event_id"] = "V29|BULL|" + bull_trades.source_event_id
    bull_trades["source_rank1"] = bull_trades.industry_breadth20_delta5
    bull_trades["source_rank2"] = -bull_trades.ret60
    bull_trades["source_rank3"] = bull_trades.turnover_ratio
    bear_trades = bear.copy()
    bear_trades["source"] = "V27_BEAR"
    bear_trades["source_event_id"] = bear_trades.event_id.astype(str)
    bear_trades["event_id"] = "V29|V27|" + bear_trades.source_event_id
    bear_trades["source_rank1"], bear_trades["source_rank2"], bear_trades["source_rank3"] = bear_trades.rank1, bear_trades.rank2, bear_trades.rank3
    union = pd.concat([bear_trades, bull_trades], ignore_index=True, sort=False).sort_values(
        ["signal_date", "sleeve", "source", "source_rank1", "source_rank2", "source_rank3", "event_id"],
        ascending=[True, True, True, False, False, False, True], kind="mergesort",
    ).reset_index(drop=True)
    union["source_rank_order"] = union.groupby(["signal_date", "sleeve", "source"], sort=False).cumcount()
    write_parquet(union, output / "source_completed_trades.parquet")
    portfolio_daily = load_daily([daily_hist, inputs["daily_tail"]], union.symbol.tolist())
    accepted, skipped, nav = replay_shared_router(
        union, portfolio_daily, nav_end=pd.Timestamp("2023-12-31")
    )
    write_parquet(accepted, output / "accepted.parquet")
    write_parquet(skipped, output / "skipped.parquet")
    write_parquet(nav, output / "nav.parquet")
    post = {
        "2024_2025": _run_atrdr_post_interval(
            inputs["atrdr_daily_2024_2025"], output / "post_2024_2025",
            start="2024-01-01", signal_end="2025-12-31", nav_end="2026-03-31",
            expected_sha256="95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9",
        ),
        "2026": _run_atrdr_post_interval(
            inputs["atrdr_daily_2026"], output / "post_2026",
            start="2026-01-01", signal_end="2026-08-12", nav_end="2026-08-12",
            expected_sha256="d092206b2c36212cf95ab0540bf6905a3274f1ba4706a50510e7cd24c9e1929c",
            maturity_lag=24,
        ),
    }
    result = {
        "strategy": "ATRDR",
        "status": "HISTORICAL_ATRDR_V29_PLUS_REGISTERED_V27_CONTINUATIONS",
        "ATRDR_REPRO_STATUS": "HISTORICAL_ATRDR_V29_PLUS_REGISTERED_V27_CONTINUATIONS",
        "closed_interval": "2014-01-01/2023-12-31",
        "continuation_intervals": "2024-01-01/2026-08-12",
        "continuation_identity": "REGISTERED_V27_NOT_ATRDR_V29",
        "post_2023": post,
        "float_tolerance": 1e-12,
        "float_tolerance_scope": "binary coordinate equality only; no threshold-crossing difference accepted",
        "counts": {"oai": len(oai), "fast_signal": len(fast_signal), "fast_accepted": len(fast_accepted), "slow_mother": len(slow), "v27_bear": len(bear), "bull_mother": len(bull), "source_completed": len(union), "accepted": len(accepted), "nav": len(nav)},
    }
    write_json(output / "result.json", result)
    return result


def comparisons(strategy: str, output: Path, golden: dict[str, Path]) -> pd.DataFrame:
    specs: dict[str, list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]] = {
        "MCB": [
            ("v53", "mcb_v53", ("event_id",), ("symbol", "signal_date", "turnover_ratio")),
            ("v64", "mcb_v64", ("event_id",), ("symbol", "signal_date")),
            ("v65", "mcb_v65", ("event_id",), ("symbol", "signal_date", "lane")),
            ("signals", "mcb_v72", ("event_id",), ("symbol", "signal_date", "cross_board_confirmation")),
            ("accepted", "mcb_accepted", ("event_id",), ("entry_date", "entry_price", "exit_date", "exit_price", "net_return", "qty", "entry_outlay")),
            ("nav", "mcb_nav", ("trade_date",), ("combined_nav",)),
        ],
        "ATRDR": [
            ("market_state", "atrdr_market", ("trade_date",), ("market_median_ret20", "market_median_ret60", "market_positive_ret20_share", "market_positive_ret60_share", "market_regime")),
            ("fast_oai_mother", "atrdr_oai", ("event_id",), ("symbol", "trade_date", "prior10_return", "close_location_x", "turnover_ratio_x")),
            ("fast_outcomes", "atrdr_fast_outcomes", ("event_id",), ("entry_date", "entry_price", "exit_date", "exit_price", "net_return")),
            ("fast_accepted", "atrdr_fast_accepted", ("event_id",), ("entry_date", "entry_price", "exit_date", "exit_price", "net_return")),
            ("v27_bear_routes", "atrdr_v27_bear", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return")),
            ("bull_mother", "atrdr_bull_mother", ("event_id",), ("symbol", "signal_date", "lane", "industry_breadth20_delta5", "ret60", "turnover_ratio")),
            ("source_completed_trades", "atrdr_source_union", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return")),
            ("accepted", "atrdr_accepted", ("event_id",), ("entry_date", "entry_price", "exit_date", "exit_price", "net_return", "qty", "entry_outlay")),
            ("nav", "atrdr_nav", ("trade_date",), ("combined_nav",)),
            ("post_2024_2025/stage_a/market", "atrdr_2024_2025_market", ("trade_date",), ("market_median_ret20", "market_median_ret60", "market_positive_ret20_share", "market_positive_ret60_share", "market_regime")),
            ("post_2024_2025/stage_a/fast_candidates", "atrdr_2024_2025_fast", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_a/slow_candidates", "atrdr_2024_2025_slow", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_a/bull_accelerating_candidates", "atrdr_2024_2025_bull_accelerating", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_a/bull_decelerating_candidates", "atrdr_2024_2025_bull_decelerating", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_b/routed_raw_trades", "atrdr_2024_2025_source_union", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_b/accepted_trades", "atrdr_2024_2025_accepted", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return", "rank1", "rank2", "rank3")),
            ("post_2024_2025/stage_b/portfolio_nav", "atrdr_2024_2025_nav", ("trade_date",), ("main_nav", "chinext_nav", "combined_nav", "utilization", "ret", "active_positions")),
            ("post_2026/stage_a/market", "atrdr_2026_market", ("trade_date",), ("market_median_ret20", "market_median_ret60", "market_positive_ret20_share", "market_positive_ret60_share", "market_regime")),
            ("post_2026/stage_a/fast_candidates", "atrdr_2026_fast", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2026/stage_a/slow_candidates", "atrdr_2026_slow", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2026/stage_a/bull_accelerating_candidates", "atrdr_2026_bull_accelerating", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2026/stage_a/bull_decelerating_candidates", "atrdr_2026_bull_decelerating", ("event_id",), ("symbol", "signal_date", "lane", "rank1", "rank2", "rank3")),
            ("post_2026/stage_b/routed_raw_trades", "atrdr_2026_source_union", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return", "rank1", "rank2", "rank3")),
            ("post_2026/stage_b/accepted_trades", "atrdr_2026_accepted", ("event_id",), ("lane", "entry_date", "entry_price", "exit_date", "exit_price", "net_return", "rank1", "rank2", "rank3")),
            ("post_2026/stage_b/portfolio_nav", "atrdr_2026_nav", ("trade_date",), ("main_nav", "chinext_nav", "combined_nav", "utilization", "ret", "active_positions")),
        ],
        "OGR": [
            ("v13_signals", "ogr_v13", ("gap_id",), ("symbol", "signal_date", "pre_gap_inside_density_relative_local")),
            ("v27", "ogr_v27", ("gap_id",), ("symbol", "signal_date")),
            ("v28", "ogr_v28", ("gap_id",), ("symbol", "signal_date")),
            ("v28r1", "ogr_v28r1", ("gap_id",), ("symbol", "signal_date")),
            ("signals", "ogr_v28r2", ("gap_id",), ("symbol", "signal_date")),
            ("trades", "ogr_trades", ("gap_id",), ("entry_time", "entry_raw_price", "exit_time", "exit_raw_price", "net_return")),
            ("accepted", "ogr_accepted", ("gap_id",), ("entry_time", "entry_raw_price", "exit_time", "exit_raw_price", "net_return", "qty", "entry_outlay")),
            ("nav", "ogr_nav", ("trade_date", "board"), ("nav", "cash", "gross_exposure", "active_positions")),
        ],
        "IFCGR": [
            ("parent_population", "ifcgr_parents", ("gap_id",), ("symbol", "signal_date")),
            ("kept", "ifcgr_kept", ("gap_id",), ("v29r2_issuer_fact_cooldown_gate",)),
            ("rejected", "ifcgr_rejected", ("gap_id",), ("v29r2_rejection_reason",)),
            ("trades", "ifcgr_trades", ("gap_id",), ("entry_time", "entry_raw_price", "exit_time", "exit_raw_price", "net_return")),
            ("accepted", "ifcgr_accepted", ("gap_id",), ("entry_time", "entry_raw_price", "exit_time", "exit_raw_price", "net_return", "qty", "entry_outlay")),
            ("nav", "ifcgr_nav", ("trade_date", "board"), ("nav", "cash", "gross_exposure", "active_positions")),
        ],
        "SMV6": [
            ("events", "smv6_events", ("trade_date", "symbol", "event_type"), ("stage", "price_pre_adj", "reason", "target_weight")),
        ],
    }
    rows = []
    tolerances = {("OGR", "v13_signals"): 2e-15}
    for layer, key, identity, values in specs.get(strategy, []):
        if key not in golden:
            continue
        actual = output / f"{layer}.parquet"
        atol = 5e-14 if strategy == "ATRDR" else tolerances.get((strategy, layer), 0.0)
        row = compare_parquet(actual, golden[key], identity, values, atol=atol)
        rows.append({"strategy": strategy, "layer": layer, "producer": f"five_strategy_bundle.{strategy.lower()}", **row})
    return pd.DataFrame(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True, choices=("OGR", "IFCGR", "MCB", "ATRDR", "SMV6"))
    parser.add_argument("--input-config", required=True, type=Path)
    parser.add_argument("--golden-config", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    inputs = load_input_config(args.input_config)
    target = args.output_root / args.strategy.lower()
    if args.strategy == "MCB":
        result = run_mcb(inputs, target)
    elif args.strategy == "OGR":
        result = run_ogr(inputs, target)
    elif args.strategy == "IFCGR":
        result = run_ifcgr(inputs, target)
    elif args.strategy == "SMV6":
        result = run_smv6(inputs, target)
    elif args.strategy == "ATRDR":
        result = run_atrdr(inputs, target)
    else:
        raise ReproductionError(f"unsupported strategy: {args.strategy}")
    if args.golden_config:
        golden = load_input_config(args.golden_config)
        table = comparisons(args.strategy, target, golden)
        table.to_csv(target / "layer_manifest.csv", index=False)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
