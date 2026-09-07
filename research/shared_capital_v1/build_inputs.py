"""Generate historical pre-capital parents from registered raw data, through 2023."""
import argparse
import json
from pathlib import Path
import os

import duckdb
import pandas as pd

from five_strategy_bundle.execution.daily import fixed_target_outcomes, strict_fixed_target_outcomes, load_daily
from five_strategy_bundle.strategies import atrdr, mcb, ogr
from research.shared_capital_v1.causal_adapters import corrected_function, entered_population, route_v27_bear, select_fast_capacity
from research.shared_capital_v1.run_shared_capital_v1 import sha256

HERE = Path(__file__).resolve().parent


def emit(message):
    print(message, flush=True)


def execution_paths(inputs):
    """The registered tail is read only with an explicit <=2023 row predicate."""
    target = HERE / "cache/daily_tail_through_2023.parquet"
    receipt = target.with_suffix(".source.json")
    source_identity = {"path": str(inputs["daily_tail"]), "sha256": sha256(inputs["daily_tail"]), "filter": "trade_date < 2024-01-01"}
    if not target.exists() or not receipt.exists() or json.loads(receipt.read_text()) != source_identity:
        con = duckdb.connect()
        try:
            temporary = target.with_suffix(f".{os.getpid()}.parquet")
            con.read_parquet(str(inputs["daily_tail"])).filter("trade_date < DATE '2024-01-01'").write_parquet(str(temporary))
            temporary.replace(target)
            receipt.write_text(json.dumps(source_identity, sort_keys=True))
        finally:
            con.close()
    return [inputs["daily_hist"], target]


def atrdr_inputs(inputs, out):
    out.mkdir(parents=True, exist_ok=True)
    daily = inputs["daily_hist"]
    emit("ATRDR market and mother screens from raw <=2023")
    market = atrdr.build_market_state(daily, out / "market.parquet")
    mother = atrdr.build_oai_mother(daily, out / "fast_mother.parquet")
    fast = atrdr.select_fast_bear(mother, market, out / "fast_signals.parquet")
    fast_daily = load_daily(execution_paths(inputs), fast.symbol.tolist())
    outcomes = fixed_target_outcomes(fast, fast_daily, target=.10, horizon=20, profile="T10_H20_NO_STOP")
    fields = ["event_id", "stock_minus_industry_ret20", "close_vs_prior10_high", "close_location_x"]
    outcomes = outcomes.merge(fast[fields], on="event_id", validate="one_to_one")
    outcomes.to_parquet(out / "fast_outcomes.parquet", index=False)
    capacity = select_fast_capacity(entered_population(outcomes), out / "fast_capacity.parquet")
    capacity = capacity.merge(fast[["event_id", "market_regime", "market_median_ret20", "market_median_ret60", "latest_source_timestamp"]], on="event_id", validate="one_to_one")
    emit(f"ATRDR fast eligible={len(fast)} entered={outcomes.entry_date.notna().sum()}")
    slow = atrdr.build_slow_mother(daily, out / "market.parquet", out / "slow_signals.parquet")
    slow_daily = load_daily(execution_paths(inputs), slow.symbol.tolist())
    slow_out = strict_fixed_target_outcomes(slow, slow_daily, target=.10, horizon=20, profile="T10_H20_NO_STOP", max_path_sessions=100)
    slow_out.to_parquet(out / "slow_outcomes.parquet", index=False)
    bear = route_v27_bear(capacity, slow_out, slow, market, out / "bear_routes.parquet")
    emit(f"ATRDR slow eligible={len(slow)} entered={slow_out.entry_date.notna().sum()}")
    bull = atrdr.build_simple_bull(daily, out / "bull_signals.parquet")
    bull_daily = load_daily(execution_paths(inputs), bull.symbol.tolist())
    bull_out = fixed_target_outcomes(bull, bull_daily, target=.15, horizon=15, profile="T15_H15_NO_STOP", split_cost=True)
    bull_out.to_parquet(out / "bull_outcomes.parquet", index=False)
    bull_routes = entered_population(bull_out).merge(bull[["event_id", "lane", "industry_breadth20_delta5", "ret60", "turnover_ratio"]], on="event_id", validate="one_to_one")
    bull_routes["rank1"], bull_routes["rank2"], bull_routes["rank3"] = bull_routes.industry_breadth20_delta5, -bull_routes.ret60, bull_routes.turnover_ratio
    parts = []
    for route, frame in (("V27", bear), ("BULL", bull_routes)):
        frame = frame.copy()
        frame["parent_event_id"] = frame.event_id
        frame["event_id"] = "V29|" + route + "|" + frame.event_id
        frame["source"] = "V27_BEAR" if route == "V27" else "V29_SIMPLE_BULL"
        frame["route"] = route
        parts.append(frame)
    union = pd.concat(parts, ignore_index=True).sort_values(["signal_date", "sleeve", "source", "rank1", "rank2", "rank3", "event_id"], ascending=[True, True, True, False, False, False, True], kind="stable")
    union["source_rank_order"] = union.groupby(["signal_date", "sleeve", "source"]).cumcount()
    union.to_parquet(out / "precapital_entry_population.parquet", index=False)
    emit(f"ATRDR causal entry population={len(union)}; incomplete={union.exit_date.isna().sum()}")


def mcb_inputs(inputs, out):
    out.mkdir(parents=True, exist_ok=True)
    emit("MCB raw signal chain <=2023")
    v53 = mcb.build_v53(inputs["daily_hist"], inputs["mcb_market_industry_state"], out / "v53.parquet")
    mcb.build_v64(v53, out / "v64.parquet")
    v65 = mcb.build_v65(v53, out / "v65.parquet")
    signals = mcb.build_v72(v65, out / "signals.parquet")
    daily = load_daily(execution_paths(inputs), signals.symbol.tolist())
    outcomes = fixed_target_outcomes(signals, daily, target=.15, horizon=15, profile="T15_H15_NO_STOP")
    outcomes.to_parquet(out / "outcomes.parquet", index=False)
    entries = entered_population(outcomes).merge(signals[["event_id", "industry_positive_ret20_share", "stock_minus_industry_ret20", "turnover_expansion"]], on="event_id", validate="one_to_one")
    entries.to_parquet(out / "precapital_entry_population.parquet", index=False)
    emit(f"MCB eligible={len(signals)} entered={len(entries)} incomplete={entries.exit_date.isna().sum()}")


def load_gap_actions(inputs, symbols):
    replacements = []
    for name in ('distributions_path', 'rights_path'):
        old = "FROM read_parquet('{_sql_path(" + name + ")}') a JOIN registry r ON r.raw_symbol=a.symbol\n          WHERE a.effective_date BETWEEN DATE '2014-01-01' AND DATE '2022-03-31'"
        replacements.append((old, old.replace('2022-03-31', '2023-12-31')))
    bounded = corrected_function(ogr.load_actions, replacements)
    return bounded(inputs["qd010_distributions"], inputs["qd010_rights"], symbols)


def ogr_inputs(inputs, out, *, parents_only=False):
    out.mkdir(parents=True, exist_ok=True)
    emit("OGR raw daily gaps and V13 through 2023 (unchanged economic predicates)")
    daily = ogr.load_daily(inputs["daily_hist"], end="2023-12-31")
    candidates = ogr.build_v13_candidates(daily, ogr.build_all_true_gaps(daily))
    candidates = candidates.loc[candidates.signal_date.between("2017-01-01", "2023-12-31")].copy()
    candidates.to_parquet(out / "v13_candidates.parquet", index=False)
    v13 = ogr.attach_v13_vap(candidates, daily, inputs["raw_minute_root"], out)
    select_v27 = corrected_function(ogr.select_v27, [('(2017, 2018, 2019, 2020, 2021)', '(2017, 2018, 2019, 2020, 2021, 2022, 2023)')])
    def load_years(root, years, columns, include_prior=False):
        return ogr._load_cy033(root, (2018, 2019, 2020, 2021, 2022, 2023), columns, include_prior)
    v27 = select_v27(v13)
    selected = v27
    for name in ("select_v28", "select_v28r1", "select_v28r2"):
        function = corrected_function(getattr(ogr, name), [], _load_cy033=load_years)
        selected = function(selected, inputs["cy033_daily_amount"])
        selected.to_parquet(out / (name + ".parquet"), index=False)
        emit(f"OGR {name}={len(selected)}")
    selected.to_parquet(out / "signals.parquet", index=False)
    if parents_only:
        return selected
    actions = load_gap_actions(inputs, selected.symbol.tolist())
    # Entry generation is separate from exit outcomes. No future outcome status filter.
    build_entries = corrected_function(ogr.build_entries, [
        ('range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2023)', 'range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2024)'),
        ("r.trade_date<=DATE '2022-03-31'", "r.trade_date<=DATE '2023-12-31'"),
    ])
    entries = build_entries(selected, daily, inputs["raw_minute_root"], actions)
    entries.to_parquet(out / "entries.parquet", index=False)
    emit(f"OGR eligible={len(selected)} executable={entries.entry_status.eq('EXECUTABLE_ENTRY').sum()}")
    build_gap_outcomes(inputs)


def rebuild_gap_execution(inputs):
    out = HERE / 'cache/ogr'
    selected = pd.read_parquet(out / 'signals.parquet')
    daily = ogr.load_daily(inputs['daily_hist'], end='2023-12-31')
    actions = load_gap_actions(inputs, selected.symbol.tolist())
    function = corrected_function(ogr.build_entries, [
        ('range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2023)', 'range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2024)'),
        ("r.trade_date<=DATE '2022-03-31'", "r.trade_date<=DATE '2023-12-31'"),
    ])
    entries = function(selected, daily, inputs['raw_minute_root'], actions)
    entries.to_parquet(out / 'entries.parquet', index=False)
    build_gap_outcomes(inputs)


def build_gap_outcomes(inputs):
    out = HERE / "cache/ogr"
    entries = pd.read_parquet(out / "entries.parquet")
    daily = ogr.load_daily(inputs["daily_hist"], end="2023-12-31")
    actions = load_gap_actions(inputs, entries.symbol.tolist())
    function = corrected_function(ogr.build_outcomes, [
        ("range(int(eligible.entry_date.dt.year.min()), 2023)", "range(int(eligible.entry_date.dt.year.min()), 2024)"),
        ("r.trade_date<=DATE '2022-03-31'", "r.trade_date<=DATE '2023-12-31'"),
    ])
    outcomes = function(entries, daily, inputs["raw_minute_root"], actions)
    outcomes.to_parquet(out / "outcomes.parquet", index=False)
    emit(f"OGR native exit paths={len(outcomes)}; outcomes never select entry membership")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", choices=("ATRDR", "MCB", "OGR"), required=True)
    parser.add_argument("--input-config", type=Path, default=HERE.parent / "five_strategy_exit_risk_v1/input_config.json")
    args = parser.parse_args()
    inputs = {k: Path(v) for k, v in json.loads(args.input_config.read_text())["inputs"].items()}
    from research.shared_capital_v1.universe import verify
    universe = verify()
    if str(inputs["daily_hist"]) != universe["stock_input"]["path"]:
        raise ValueError("unregistered strategy universe input")
    {"ATRDR": atrdr_inputs, "MCB": mcb_inputs, "OGR": ogr_inputs}[args.strategy](inputs, HERE / "cache" / args.strategy.lower())


if __name__ == "__main__":
    main()
