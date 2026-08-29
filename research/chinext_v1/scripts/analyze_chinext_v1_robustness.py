#!/usr/bin/env python3
"""Post-process frozen ChinNext V1 ledgers without regenerating any signal."""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_full_survivor_summary.json"
EXECUTIONS = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/execution_ledger.jsonl"
NAV = ROOT / "research/chinext_v1/output/chinext_v1_full_survivor/daily_nav.jsonl"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
INDEX_399102 = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
INDEX_399006 = Path("/Users/linmei/Downloads/workspace/quant/data/lake/index_daily/sz399006.parquet")
QD003_MANIFEST = Path("/Users/linmei/Documents/CY/data/input_inventories/QD-003-20260820.json")
RESEARCH_CONFIG = ROOT / "configs/research.yaml"
OUTPUT_SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_robustness_summary.json"
OUTPUT_REPORT = ROOT / "research/chinext_v1/reports/chinext_v1_robustness.md"
START = "2024-01-02"
END = "2025-12-31"
INITIAL_CASH = 1_000_000.0
SESSIONS_PER_YEAR = 244
FROZEN_HASHES = {
    STRATEGY: "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    SUMMARY: "3d18027af56b41796d9c60d7712e7085efcae4e33d080db4a901b567ec23ef91",
    EXECUTIONS: "f3a83a9e974776f34477c952b1bf4c26f22a5ef00879adfc77cd6188f9eec9d5",
    NAV: "82c71b6824bf4058181c88dbaa626f989e2651912aab3777d4d5ffdce096e8ea",
    INDEX_399102: "e096e4d50d0b6ac5062d4940bf0c17c0165dd1c44d5f49ce12d0e3754daa8779",
    INDEX_399006: "0d0f8dbb573f1016eaa94f11aa847ea2bf2be296691caa591f93320ddd640c2c",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def assert_frozen_inputs() -> dict[str, str]:
    actual = {str(path): sha256_file(path) for path in FROZEN_HASHES}
    mismatches = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in FROZEN_HASHES.items()
        if actual[str(path)] != expected
    }
    if mismatches:
        raise RuntimeError(f"frozen robustness input changed: {mismatches}")
    return actual


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)


def max_drawdown(values: list[float]) -> float:
    peak = values[0]
    result = 0.0
    for value in values:
        peak = max(peak, value)
        result = min(result, value / peak - 1.0)
    return result


def path_metrics(values: list[float]) -> dict[str, float | None]:
    if len(values) < 2 or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("metric path must contain finite positive values")
    returns = [current / previous - 1.0 for previous, current in zip(values, values[1:], strict=False)]
    volatility = statistics.stdev(returns) * math.sqrt(SESSIONS_PER_YEAR)
    sharpe = (
        None
        if volatility <= 0
        else statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(SESSIONS_PER_YEAR)
    )
    return {
        "total_return": values[-1] / values[0] - 1.0,
        "annualized_return": (values[-1] / values[0]) ** (SESSIONS_PER_YEAR / (len(values) - 1)) - 1.0,
        "max_drawdown": max_drawdown(values),
        "volatility": volatility,
        "sharpe_rf0": sharpe,
    }


def reconstruct_round_trips(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    result: list[dict[str, Any]] = []
    for row in executions:
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY":
            if row.get("new_position") is True:
                if symbol in active:
                    raise ValueError(f"overlapping position cycle for {symbol}")
                active[symbol] = {
                    "symbol": symbol,
                    "entry_date": row["execution_date"],
                    "buy_notional": 0.0,
                    "sell_notional": 0.0,
                    "baseline_pnl": 0.0,
                }
            if symbol not in active:
                raise ValueError(f"rebalance buy without active cycle for {symbol}")
            active[symbol]["buy_notional"] += float(row["notional"])
        else:
            if symbol not in active:
                raise ValueError(f"sell without active cycle for {symbol}")
            active[symbol]["sell_notional"] += float(row["notional"])
            active[symbol]["baseline_pnl"] += float(row["realized_pnl"])
            if row.get("completed_round_trip") is True:
                cycle = active.pop(symbol)
                cycle.update(
                    {
                        "exit_date": row["execution_date"],
                        "round_trip_return": float(row["round_trip_return"]),
                    }
                )
                result.append(cycle)
    return result


def cost_adjusted_nav(
    nav: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    *,
    side_bps: float,
    sell_stamp_bps: float = 0.0,
    baseline_side_bps: float = 10.0,
) -> list[dict[str, Any]]:
    """Fixed-fill cost sensitivity; positions/signals/fills never change."""

    if side_bps < baseline_side_bps or sell_stamp_bps < 0:
        raise ValueError("robustness costs cannot undercut the frozen baseline")
    extra_by_date: dict[str, float] = defaultdict(float)
    for row in executions:
        if row.get("status") != "FILLED":
            continue
        bps = side_bps - baseline_side_bps
        if row["side"] == "SELL":
            bps += sell_stamp_bps
        extra_by_date[str(row["execution_date"])] += float(row["notional"]) * bps / 10_000.0
    cumulative = 0.0
    result: list[dict[str, Any]] = []
    for row in nav:
        cumulative += extra_by_date[str(row["trade_date"])]
        value = float(row["nav"]) - cumulative
        if value <= 0:
            raise ValueError("cost sensitivity exhausted portfolio NAV")
        result.append({"trade_date": str(row["trade_date"]), "nav": value, "extra_cost": cumulative})
    return result


def load_benchmark_399102(required_dates: list[str]) -> dict[str, Any]:
    frame = pd.read_csv(INDEX_399102, dtype={"trade_date": str})
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m-%d")
    return normalize_benchmark(frame, required_dates, "399102.SZ", "创业板综", "QMT exact frozen daily")


def load_benchmark_399006(required_dates: list[str]) -> dict[str, Any]:
    manifest = json.loads(QD003_MANIFEST.read_text(encoding="utf-8"))
    record = next(item for item in manifest["files"] if item["path"] == "sz399006.parquet")
    if record["sha256"] != FROZEN_HASHES[INDEX_399006]:
        raise RuntimeError("QD-003 manifest hash disagrees with frozen 399006 input")
    frame = pd.read_parquet(INDEX_399006)
    if set(frame["index_symbol"].unique()) != {"sz399006"} or set(frame["index_name"].unique()) != {"创业板指"}:
        raise ValueError("399006 exact identity check failed")
    frame["trade_date"] = pd.to_datetime(frame["trade_date"]).dt.strftime("%Y-%m-%d")
    return normalize_benchmark(
        frame,
        required_dates,
        "399006.SZ",
        "创业板指",
        "registered QD-003 frozen local lake; ex-post benchmark only",
    )


def normalize_benchmark(
    frame: pd.DataFrame,
    required_dates: list[str],
    symbol: str,
    name: str,
    source: str,
) -> dict[str, Any]:
    if frame["trade_date"].duplicated().any():
        raise ValueError(f"duplicate benchmark dates for {symbol}")
    mapping = dict(zip(frame["trade_date"], pd.to_numeric(frame["close"], errors="coerce"), strict=True))
    missing = [day for day in required_dates if day not in mapping]
    if missing:
        raise ValueError(f"{symbol} missing required dates; fallback forbidden: {missing[:5]}")
    closes = [float(mapping[day]) for day in required_dates]
    if any(not math.isfinite(value) or value <= 0 for value in closes):
        raise ValueError(f"{symbol} has invalid required closes")
    return {
        "symbol": symbol,
        "name": name,
        "source": source,
        "dates": required_dates,
        "closes": closes,
        "metrics": path_metrics(closes),
    }


def year_path_metrics(rows: list[dict[str, Any]], year: int) -> dict[str, float | None]:
    selected = [row for row in rows if str(row["trade_date"]).startswith(str(year))]
    if year > 2024:
        prior = [row for row in rows if str(row["trade_date"]) < f"{year}-01-01"][-1]
        selected = [prior] + selected
    return path_metrics([float(row["nav"]) for row in selected])


def benchmark_year_metrics(benchmark: dict[str, Any], year: int) -> dict[str, float | None]:
    rows = [
        {"trade_date": day, "nav": close}
        for day, close in zip(benchmark["dates"], benchmark["closes"], strict=True)
    ]
    return year_path_metrics(rows, year)


def compound(values: list[float]) -> float:
    result = 1.0
    for value in values:
        result *= 1.0 + value
    return result - 1.0


def exposure_diagnostic(nav: list[dict[str, Any]], market: dict[str, Any]) -> dict[str, Any]:
    strategy_returns: list[float] = []
    market_returns: list[float] = []
    invested_flags: list[bool] = []
    for index in range(1, len(nav)):
        strategy_returns.append(float(nav[index]["nav"]) / float(nav[index - 1]["nav"]) - 1.0)
        market_returns.append(market["closes"][index] / market["closes"][index - 1] - 1.0)
        invested_flags.append(int(nav[index]["holdings"]) > 0)
    invested_strategy = [value for value, flag in zip(strategy_returns, invested_flags, strict=True) if flag]
    flat_strategy = [value for value, flag in zip(strategy_returns, invested_flags, strict=True) if not flag]
    invested_market = [value for value, flag in zip(market_returns, invested_flags, strict=True) if flag]
    flat_market = [value for value, flag in zip(market_returns, invested_flags, strict=True) if not flag]
    return {
        "definition": "close-to-close day classified by end-of-day holdings; open exits remain in that day's return",
        "return_while_invested": compound(invested_strategy),
        "return_while_flat": compound(flat_strategy),
        "average_invested_ratio": statistics.fmean(float(row["invested_ratio"]) for row in nav),
        "market_return_during_strategy_flat_days": compound(flat_market),
        "market_return_during_strategy_invested_days": compound(invested_market),
        "invested_day_count": len(invested_strategy),
        "flat_day_count": len(flat_strategy),
    }


def winner_bucket(value: float) -> str:
    if value > 0.50:
        return "> +50%"
    if value >= 0.20:
        return "+20% ~ +50%"
    if value >= 0.10:
        return "+10% ~ +20%"
    if value >= 0.0:
        return "0 ~ +10%"
    if value >= -0.10:
        return "-10% ~ 0"
    if value >= -0.20:
        return "-20% ~ -10%"
    return "< -20%"


def concentration_diagnostic(round_trips: list[dict[str, Any]], baseline_total_return: float) -> dict[str, Any]:
    ordered = sorted(round_trips, key=lambda row: (-float(row["baseline_pnl"]), row["symbol"], row["exit_date"]))
    positive_total = sum(max(0.0, float(row["baseline_pnl"])) for row in ordered)
    concentrations = {}
    exclusions = {}
    for count in (1, 5, 10, 20, 50):
        top = ordered[:count]
        concentrations[f"top{count}"] = sum(max(0.0, float(row["baseline_pnl"])) for row in top) / positive_total
        if count <= 20:
            exclusions[f"best{count}"] = baseline_total_return - sum(float(row["baseline_pnl"]) for row in top) / INITIAL_CASH
    bucket_order = ["> +50%", "+20% ~ +50%", "+10% ~ +20%", "0 ~ +10%", "-10% ~ 0", "-20% ~ -10%", "< -20%"]
    buckets = {name: {"count": 0, "pnl": 0.0} for name in bucket_order}
    for row in round_trips:
        bucket = winner_bucket(float(row["round_trip_return"]))
        buckets[bucket]["count"] += 1
        buckets[bucket]["pnl"] += float(row["baseline_pnl"])
    returns = [float(row["round_trip_return"]) for row in round_trips]
    return {
        "round_trip_count": len(round_trips),
        "mean_round_trip_return": statistics.fmean(returns),
        "median_round_trip_return": statistics.median(returns),
        "positive_round_trip_pnl": positive_total,
        "top_pnl_concentration_of_positive_round_trip_pnl": concentrations,
        "portfolio_return_excluding_best_round_trips": exclusions,
        "winner_distribution": buckets,
    }


def parse_stamp_contract() -> dict[str, Any]:
    text = RESEARCH_CONFIG.read_text(encoding="utf-8")
    match = re.search(r"^\s*stamp_duty_sell_bps:\s*([0-9.]+)\s*$", text, re.MULTILINE)
    if match is None:
        return {"status": "UNRESOLVED", "sell_bps": None, "evidence": str(RESEARCH_CONFIG)}
    return {
        "status": "VERIFIED_LOCAL_RESEARCH_CONTRACT",
        "sell_bps": float(match.group(1)),
        "evidence": [str(RESEARCH_CONFIG), str(ROOT / "src/cyq_game/config.py")],
        "interpretation": "separate sensitivity only; not part of frozen ChinNext baseline",
    }


def classify(summary: dict[str, Any]) -> str:
    concentration = summary["pnl_concentration"]["top_pnl_concentration_of_positive_round_trip_pnl"]
    exclusions = summary["pnl_concentration"]["portfolio_return_excluding_best_round_trips"]
    costs = summary["cost_sensitivity"]
    if costs["50bps_per_side"]["total_return"] <= 0 or exclusions["best5"] <= 0:
        return "WEAK"
    if concentration["top20"] > 0.75 or exclusions["best20"] <= 0:
        return "FRAGILE"
    if costs["50bps_per_side"]["total_return"] < costs["10bps_per_side"]["total_return"] * 0.75:
        return "ACCEPTABLE"
    return "STRONG"


def fmt_pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.4%}"


def write_report(summary: dict[str, Any]) -> None:
    costs = summary["cost_sensitivity"]
    concentration = summary["pnl_concentration"]
    benchmarks = summary["benchmarks"]
    exposure = summary["exposure_aware"]
    years = summary["year_split"]
    cost_lines = ["| Scenario | Total return | Annualized | Max drawdown | Extra cost |", "|---|---:|---:|---:|---:|"]
    for name, row in costs.items():
        cost_lines.append(
            f"| {name} | {fmt_pct(row['total_return'])} | {fmt_pct(row['annualized_return'])} | {fmt_pct(row['max_drawdown'])} | {row['cumulative_extra_cost']:,.2f} |"
        )
    benchmark_lines = ["| Benchmark | Total return | Annualized | Max drawdown | Volatility | Sharpe rf=0 |", "|---|---:|---:|---:|---:|---:|"]
    for symbol, row in benchmarks.items():
        metric = row["metrics"]
        benchmark_lines.append(
            f"| {symbol} {row['name']} | {fmt_pct(metric['total_return'])} | {fmt_pct(metric['annualized_return'])} | {fmt_pct(metric['max_drawdown'])} | {fmt_pct(metric['volatility'])} | {metric['sharpe_rf0']:.4f} |"
        )
    winner_lines = ["| Round-trip return bucket | Count | P&L contribution |", "|---|---:|---:|"]
    for bucket, row in concentration["winner_distribution"].items():
        winner_lines.append(f"| {bucket} | {row['count']} | {row['pnl']:,.2f} |")
    year_lines = ["| Year | Cost scenario | Strategy return | Max drawdown | 399102 return | Excess | 399006 return | Excess |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for year, scenarios in years.items():
        for scenario, row in scenarios["strategy_costs"].items():
            year_lines.append(
                f"| {year} | {scenario} | {fmt_pct(row['total_return'])} | {fmt_pct(row['max_drawdown'])} | {fmt_pct(scenarios['benchmarks']['399102.SZ']['total_return'])} | {fmt_pct(row['total_return']-scenarios['benchmarks']['399102.SZ']['total_return'])} | {fmt_pct(scenarios['benchmarks']['399006.SZ']['total_return'])} | {fmt_pct(row['total_return']-scenarios['benchmarks']['399006.SZ']['total_return'])} |"
            )
    c = concentration["top_pnl_concentration_of_positive_round_trip_pnl"]
    x = concentration["portfolio_return_excluding_best_round_trips"]
    report = f"""# ChinNext V1 robustness validation

> **EXPLORATORY / CURRENT-SURVIVOR / NON-PIT / SURVIVORSHIP-BIASED**
>
> This report post-processes the frozen full-survivor execution and NAV ledgers.
> It regenerates no signal, changes no fill, selects no parameter and extends no date.

## Frozen scope

- DATE_RANGE: `{START} .. {END}`
- BASELINE_STRATEGY_SHA256: `{summary['frozen_inputs'][str(STRATEGY)]}`
- BASELINE_EXECUTION_LEDGER_SHA256: `{summary['frozen_inputs'][str(EXECUTIONS)]}`
- BASELINE_NAV_SHA256: `{summary['frozen_inputs'][str(NAV)]}`
- COMPLETED_ROUND_TRIPS: `{concentration['round_trip_count']}`

## Cost sensitivity — fixed fills

{chr(10).join(cost_lines)}

The baseline already deducts 10bps on every filled side. Higher-cost paths subtract
only incremental cost from the same fixed executions and never regenerate signals,
orders or quantities. Local research contracts explicitly specify 5bps sell-side
stamp duty, shown as a separate scenario; it is not retroactively inserted into the
frozen baseline. Slippage remains unresolved as a ChinNext-specific realized model.

## Round-trip concentration

| Cut | Share of all positive round-trip P&L | Portfolio return excluding best trades |
|---|---:|---:|
| Top 1 | {fmt_pct(c['top1'])} | {fmt_pct(x['best1'])} |
| Top 5 | {fmt_pct(c['top5'])} | {fmt_pct(x['best5'])} |
| Top 10 | {fmt_pct(c['top10'])} | {fmt_pct(x['best10'])} |
| Top 20 | {fmt_pct(c['top20'])} | {fmt_pct(x['best20'])} |
| Top 50 | {fmt_pct(c['top50'])} | — |

- MEAN_ROUND_TRIP_RETURN: `{fmt_pct(concentration['mean_round_trip_return'])}`
- MEDIAN_ROUND_TRIP_RETURN: `{fmt_pct(concentration['median_round_trip_return'])}`

Exclusion returns subtract selected completed-cycle P&L from final portfolio P&L;
all other realized P&L and the ten ending positions remain unchanged.

## Winner distribution

{chr(10).join(winner_lines)}

## Benchmark comparison

{chr(10).join(benchmark_lines)}

- STRATEGY_EXCESS_TOTAL_VS_399102: `{fmt_pct(summary['excess']['399102.SZ']['total_return'])}`
- STRATEGY_EXCESS_ANNUALIZED_VS_399102: `{fmt_pct(summary['excess']['399102.SZ']['annualized_return'])}`
- STRATEGY_EXCESS_TOTAL_VS_399006: `{fmt_pct(summary['excess']['399006.SZ']['total_return'])}`
- STRATEGY_EXCESS_ANNUALIZED_VS_399006: `{fmt_pct(summary['excess']['399006.SZ']['annualized_return'])}`

`399102.SZ` is the exact frozen QMT series. `399006.SZ` is exact `sz399006 / 创业板指`
from registered frozen QD-003 and is used only as an ex-post comparator, never as a
strategy input or fallback.

## Exposure-aware diagnostic

- RETURN_WHILE_INVESTED: `{fmt_pct(exposure['return_while_invested'])}`
- RETURN_WHILE_FLAT: `{fmt_pct(exposure['return_while_flat'])}`
- AVERAGE_INVESTED_RATIO: `{fmt_pct(exposure['average_invested_ratio'])}`
- 399102_RETURN_DURING_STRATEGY_FLAT_DAYS: `{fmt_pct(exposure['market_return_during_strategy_flat_days'])}`
- 399102_RETURN_DURING_STRATEGY_INVESTED_DAYS: `{fmt_pct(exposure['market_return_during_strategy_invested_days'])}`
- INVESTED_DAYS / FLAT_DAYS: `{exposure['invested_day_count']} / {exposure['flat_day_count']}`

The diagnostic classifies each close-to-close return by end-of-day holdings. An
open exit can therefore contribute to a day that finishes flat; this is intentional
and stated rather than silently reassigning return.

## Year split

{chr(10).join(year_lines)}

## Interpretation

- ROBUSTNESS_RESULT: **{summary['robustness_result']}**

Cost sensitivity is mild relative to the headline return, but concentration and
benchmark/exposure diagnostics determine whether that headline is genuinely broad.
No result here is a formal PIT performance claim.
"""
    atomic_text(OUTPUT_REPORT, report)


def main() -> int:
    frozen = assert_frozen_inputs()
    baseline = json.loads(SUMMARY.read_text(encoding="utf-8"))
    executions = read_jsonl(EXECUTIONS)
    nav = read_jsonl(NAV)
    dates = [str(row["trade_date"]) for row in nav]
    if dates[0] != START or dates[-1] != END:
        raise ValueError("baseline NAV date range changed")
    round_trips = reconstruct_round_trips(executions)
    if len(round_trips) != baseline["execution"]["completed_round_trip_count"]:
        raise ValueError("round-trip reconstruction disagrees with frozen summary")

    cost_specs = {
        "10bps_per_side": (10.0, 0.0),
        "20bps_per_side": (20.0, 0.0),
        "30bps_per_side": (30.0, 0.0),
        "50bps_per_side": (50.0, 0.0),
    }
    stamp = parse_stamp_contract()
    if stamp["status"] == "VERIFIED_LOCAL_RESEARCH_CONTRACT":
        cost_specs["10bps_per_side_plus_5bps_sell_stamp"] = (10.0, float(stamp["sell_bps"]))
    cost_paths: dict[str, list[dict[str, Any]]] = {}
    cost_summary: dict[str, Any] = {}
    for name, (side_bps, stamp_bps) in cost_specs.items():
        path = cost_adjusted_nav(nav, executions, side_bps=side_bps, sell_stamp_bps=stamp_bps)
        cost_paths[name] = path
        metrics = path_metrics([float(row["nav"]) for row in path])
        metrics["cumulative_extra_cost"] = float(path[-1]["extra_cost"])
        metrics["side_bps"] = side_bps
        metrics["sell_stamp_bps"] = stamp_bps
        cost_summary[name] = metrics
    if abs(cost_summary["10bps_per_side"]["total_return"] - baseline["portfolio"]["total_return"]) > 1e-12:
        raise ValueError("baseline cost reconstruction changed frozen return")

    benchmark_399102 = load_benchmark_399102(dates)
    benchmark_399006 = load_benchmark_399006(dates)
    benchmarks = {"399102.SZ": benchmark_399102, "399006.SZ": benchmark_399006}
    baseline_metrics = cost_summary["10bps_per_side"]
    excess = {
        symbol: {
            "total_return": float(baseline_metrics["total_return"]) - float(row["metrics"]["total_return"]),
            "annualized_return": float(baseline_metrics["annualized_return"]) - float(row["metrics"]["annualized_return"]),
        }
        for symbol, row in benchmarks.items()
    }
    years: dict[str, Any] = {}
    for year in (2024, 2025):
        years[str(year)] = {
            "strategy_costs": {
                name: year_path_metrics(path, year) for name, path in cost_paths.items()
            },
            "benchmarks": {
                symbol: benchmark_year_metrics(row, year) for symbol, row in benchmarks.items()
            },
        }

    concentration = concentration_diagnostic(round_trips, baseline["portfolio"]["total_return"])
    summary: dict[str, Any] = {
        "warning": "EXPLORATORY CURRENT-SURVIVOR NON-PIT SURVIVORSHIP-BIASED",
        "date_range": [START, END],
        "method": "post-process frozen executions/NAV; no signal or fill regeneration",
        "frozen_inputs": frozen,
        "cost_contract": stamp,
        "cost_sensitivity": cost_summary,
        "pnl_concentration": concentration,
        "benchmarks": benchmarks,
        "excess": excess,
        "exposure_aware": exposure_diagnostic(nav, benchmark_399102),
        "year_split": years,
    }
    # Avoid duplicating the full close arrays in the small machine summary.
    for row in summary["benchmarks"].values():
        row.pop("dates")
        row.pop("closes")
    summary["robustness_result"] = classify(summary)
    atomic_json(OUTPUT_SUMMARY, summary)
    write_report(summary)
    print(
        json.dumps(
            {
                "baseline_return": cost_summary["10bps_per_side"]["total_return"],
                "return_50bps": cost_summary["50bps_per_side"]["total_return"],
                "return_ex_best20": concentration["portfolio_return_excluding_best_round_trips"]["best20"],
                "result": summary["robustness_result"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
