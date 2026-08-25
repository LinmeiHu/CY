"""Research absorption ranking, non-overlap and adaptive-exit study.

Signals use only close-of-day information and fill on the next valid open.
This is deliberately a small predeclared experiment, not a parameter sweep.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DAILY = ROOT / "data/processed/pit_b_daily_2018_2026_v2/daily/partition_year=*/data_0.parquet"
FEATURES = ROOT / "data/processed/chip_state_features_2018_2026_v2/bucket=*/data.parquet"
OUT = ROOT / "data/audit/chip_absorption_ranked_nonoverlap_2020_2023.csv"
COST = 0.0031


@dataclass
class Trade:
    symbol: str
    signal_date: str
    entry_date: str
    entry_open: float
    regime: str
    score: float
    exit_date: str
    gross: float
    exit_rule: str


def load_candidates(start: str, end: str) -> list[dict]:
    con = duckdb.connect()
    q = f"""
    WITH md AS (
      SELECT trade_date,avg(market_close) market_close
      FROM read_parquet('{DAILY}',union_by_name=true)
      WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '{end}' GROUP BY trade_date
    ), m AS (
      SELECT *,avg(market_close) OVER(ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING) avg20,
        lag(market_close,20) OVER(ORDER BY trade_date) close20 FROM md
    ), x AS (
      SELECT d.symbol,d.trade_date signal_date,d.trade_date,d.close,d.open,d.high,d.low,
        f.average_cost,f.asr,f.concentration_20,f.profit_ratio,f.trapped_ratio,
        lag(d.close) OVER w prev_close,
        lag(f.asr) OVER w prev_asr,lag(f.concentration_20) OVER w prev_conc,
        lead(d.open) OVER w entry_open,lead(d.trade_date) OVER w entry_date,
        lead(d.hard_valid) OVER w entry_valid,lead(d.buy_blocked_open) OVER w entry_blocked,
        CASE WHEN m.market_close>m.avg20 AND m.close20 IS NOT NULL AND m.market_close>=m.close20 THEN 'BULL'
          WHEN m.market_close<m.avg20 AND m.close20 IS NOT NULL AND m.market_close<m.close20 THEN 'BEAR' ELSE 'RANGE' END regime
      FROM read_parquet('{DAILY}',union_by_name=true) d
      JOIN read_parquet('{FEATURES}',union_by_name=true) f USING(symbol,trade_date)
      JOIN m USING(trade_date)
      WHERE d.trade_date BETWEEN DATE '2018-01-02' AND DATE '{end}'
        AND d.hard_valid AND f.strict_sample AND f.state_chain_valid
      WINDOW w AS (PARTITION BY d.symbol ORDER BY d.trade_date)
    ), c AS (
      SELECT *, (asr-coalesce(prev_asr,asr)) asr_delta,
        (coalesce(prev_conc,concentration_20)-concentration_20) conc_improve,
        (average_cost-close)/nullif(average_cost,0) cost_gap
      FROM x WHERE close<=average_cost AND close>prev_close
        AND asr>=coalesce(prev_asr,asr) AND concentration_20<=coalesce(prev_conc,concentration_20)
        AND entry_date>signal_date AND entry_open>0 AND entry_valid AND NOT entry_blocked
        AND signal_date>=DATE '{start}'
    ), f AS (
      SELECT c.*,d.trade_date::VARCHAR future_date,d.high future_high,d.low future_low,d.close future_close,
        ff.asr future_asr,ff.concentration_20 future_conc,
        row_number() OVER(PARTITION BY c.symbol,c.signal_date ORDER BY d.trade_date) seq
      FROM c JOIN read_parquet('{DAILY}',union_by_name=true) d ON d.symbol=c.symbol AND d.trade_date>c.trade_date
        AND d.trade_date<=c.trade_date+INTERVAL 40 DAY AND d.hard_valid
      JOIN read_parquet('{FEATURES}',union_by_name=true) ff ON ff.symbol=d.symbol AND ff.trade_date=d.trade_date
      QUALIFY seq<=20
    ) SELECT * FROM f ORDER BY symbol,signal_date,seq
    """
    rows = con.execute(q).fetchdf().to_dict("records")
    return rows


def make_trades(rows: list[dict], adaptive: bool) -> list[Trade]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        grouped[(r["symbol"], r["signal_date"])].append(r)
    trades: list[Trade] = []
    for (symbol, signal), path in grouped.items():
        first = path[0]
        stop = take = None
        adaptive_exit = None
        for r in path:
            if r["future_low"] <= first["entry_open"] * 0.92 and stop is None:
                stop = r
            if r["future_high"] >= first["entry_open"] * 1.12 and take is None:
                take = r
            if adaptive and r["future_asr"] < first["asr"] and r["future_conc"] > first["concentration_20"]:
                adaptive_exit = r
                break
        choices = [("STOP", stop), ("TAKE", take), ("ADAPTIVE", adaptive_exit)]
        choices = [(n, r) for n, r in choices if r is not None]
        if choices:
            name, out = min(choices, key=lambda x: (x[1]["future_date"], 0 if x[0] == "STOP" else 1))
        else:
            out = path[-1]
            name = "TIME"
        gross = ((-0.08 if name == "STOP" else 0.12) if name in {"STOP", "TAKE"} else (out["future_close"] - first["entry_open"]) / first["entry_open"])
        score = max(0.0, float(first["asr_delta"] or 0)) + max(0.0, float(first["conc_improve"] or 0)) + max(0.0, float(first["cost_gap"] or 0))
        trades.append(Trade(symbol, signal, str(first["entry_date"]), float(first["entry_open"]), first["regime"], score, out["future_date"], float(gross), name))
    return trades


def select(trades: list[Trade], capacity: int = 20) -> list[Trade]:
    chosen: list[Trade] = []
    last_exit: dict[str, str] = {}
    by_day: dict[str, list[Trade]] = defaultdict(list)
    for t in trades:
        by_day[t.entry_date].append(t)
    for day in sorted(by_day):
        batch = sorted(by_day[day], key=lambda t: (-t.score, t.symbol))
        n = 0
        for t in batch:
            if t.entry_date <= last_exit.get(t.symbol, ""):
                continue
            chosen.append(t)
            last_exit[t.symbol] = t.exit_date
            n += 1
            if n >= capacity:
                break
    return chosen


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-02")
    ap.add_argument("--end", default="2023-12-29")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    rows = load_candidates(args.start, args.end)
    all_rows: list[dict] = []
    for variant, adaptive in (("FIXED_RANKED", False), ("ADAPTIVE_RANKED", True)):
        selected = select(make_trades(rows, adaptive))
        for t in selected:
            all_rows.append({"variant": variant, "sample_group": "FIT_2020_2022" if t.entry_date < "2023-01-01" else "HOLDOUT_2023", "symbol": t.symbol, "signal_date": t.signal_date, "entry_date": t.entry_date, "exit_date": t.exit_date, "regime": t.regime, "score": t.score, "exit_rule": t.exit_rule, "gross_return": t.gross, "net_return": t.gross-COST})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(all_rows[0]))
        w.writeheader()
        w.writerows(all_rows)
    for variant in ("FIXED_RANKED", "ADAPTIVE_RANKED"):
        for group in ("FIT_2020_2022", "HOLDOUT_2023"):
            rr = [r for r in all_rows if r["variant"] == variant and r["sample_group"] == group]
            net = [float(r["net_return"]) for r in rr]
            print(variant, group, "n", len(rr), "mean_net", round(sum(net)/len(net), 6) if net else None, "win", round(sum(x > 0 for x in net)/len(net), 4) if net else None)
    print(args.out)


if __name__ == "__main__":
    main()
