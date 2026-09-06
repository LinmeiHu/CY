from __future__ import annotations

import argparse
import json
from pathlib import Path

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
from .io import load_input_config, write_json, write_parquet
from .strategies.atrdr import (
    build_market_state,
    build_oai_mother,
    build_simple_bull,
    build_slow_mother,
    route_v27_bear,
    select_fast_bear,
    select_fast_capacity,
)
from .strategies.mcb import build_v53, build_v64, build_v65, build_v72


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


def run_atrdr(inputs: dict[str, Path], output: Path) -> dict[str, object]:
    """Run the closed 2014-2023 ATRDR source interval.

    The registered post-2023 producers are not yet in this bundle, so this
    function deliberately reports historical-route closure rather than FULL.
    """
    output.mkdir(parents=True, exist_ok=True)
    daily_hist = inputs["daily_hist"]
    market = build_market_state(daily_hist, output / "market_state.parquet")
    oai = build_oai_mother(daily_hist, output / "fast_oai_mother.parquet")
    fast_signal = select_fast_bear(oai, market, output / "fast_signal.parquet")
    trade_daily = load_daily([daily_hist], fast_signal.symbol.tolist())
    long_outcomes = fixed_target_outcomes(fast_signal, trade_daily, target=0.20, horizon=60, profile="T20_H60_NO_STOP")
    eligible_ids = set(long_outcomes.loc[long_outcomes.status.eq("COMPLETED"), "event_id"])
    fast_outcomes = fixed_target_outcomes(
        fast_signal.loc[fast_signal.event_id.isin(eligible_ids)],
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
    accepted, skipped, nav = replay_shared_router(union, portfolio_daily)
    write_parquet(accepted, output / "accepted.parquet")
    write_parquet(skipped, output / "skipped.parquet")
    write_parquet(nav, output / "nav.parquet")
    result = {
        "strategy": "ATRDR",
        "status": "SOURCE_CHAIN_INCOMPLETE",
        "closed_interval": "2014-01-01/2023-12-31",
        "limitation": "post-2023 registered Bear/Bull producer closure is not bundled; historical shared-account replay is closed",
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
        ],
    }
    rows = []
    for layer, key, identity, values in specs.get(strategy, []):
        if key not in golden:
            continue
        actual = output / f"{layer}.parquet"
        row = compare_parquet(actual, golden[key], identity, values)
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
    elif args.strategy == "ATRDR":
        result = run_atrdr(inputs, target)
    else:
        raise ReproductionError(f"{args.strategy}: SOURCE_CHAIN_INCOMPLETE in this delivery")
    if args.golden_config:
        golden = load_input_config(args.golden_config)
        table = comparisons(args.strategy, target, golden)
        table.to_csv(target / "layer_manifest.csv", index=False)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
