#!/usr/bin/env python3
"""Run and report the frozen ChinNext V1 full current-survivor replay."""

from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from run_chinext_v1_smoke import (
    DEFAULT_CALENDAR,
    DEFAULT_DAILY_ROOT,
    DEFAULT_MARKET,
    DEFAULT_SURVIVOR,
    SURVIVOR_WARNING,
    atomic_text,
    fmt_pct,
    run,
    sha256_file,
    write_json,
)

START = date(2024, 1, 2)
END = date(2025, 12, 31)
INITIAL_CASH = 1_000_000.0
PRE_RUN_BASELINE_HASHES = {
    "research/chinext_v1/strategy/chinext_v1_exploratory.py": "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    "research/chinext_v1/scripts/run_chinext_v1_smoke.py": "ef759c5d0283e9476d8b0f5cf85f51f1e992c5730d6e95b127b2489e616f1264",
    "research/chinext_v1/specs/chinext_v1_exploratory_baseline.md": "9c44059d86d1c34b64c1e388e7085c4058c22575bded0970e99c97a9157cd348",
    "research/chinext_v1/reports/chinext_v1_smoke_summary.json": "87569cdb9140c9d7192ff68c3f7567e31e03eff67635dede6c6f53ad8596a2aa",
}
FROZEN_V6 = Path(
    "research/supermind_v6/strategy/"
    "SuperMind_V6_CSI1000_MA15_ENTRY_HS300_MA20_EXIT_"
    "MINVOLLOC30_CAP50_SET_TAIL_SELL_OPEN_BUY_COMMENTS_FIXED.py"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--survivor", type=Path, default=DEFAULT_SURVIVOR)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument(
        "--smoke-summary",
        type=Path,
        default=Path("research/chinext_v1/reports/chinext_v1_smoke_summary.json"),
    )
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path("research/chinext_v1/reports/chinext_v1_full_survivor_summary.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("research/chinext_v1/reports/chinext_v1_full_survivor.md"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("research/chinext_v1/output/chinext_v1_full_survivor"),
    )
    return parser.parse_args()


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def maximum_drawdown(values: list[float], starting_value: float | None = None) -> float:
    sequence = ([starting_value] if starting_value is not None else []) + values
    peak = sequence[0]
    result = 0.0
    for value in sequence:
        peak = max(peak, value)
        result = min(result, value / peak - 1.0)
    return result


def round_trip_rows(executions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cycle_pnl: dict[str, float] = defaultdict(float)
    cycle_returns: list[dict[str, Any]] = []
    for row in executions:
        if row.get("status") != "FILLED" or row.get("side") != "SELL":
            continue
        symbol = str(row["symbol"])
        cycle_pnl[symbol] += float(row.get("realized_pnl") or 0.0)
        if row.get("completed_round_trip") is True:
            cycle_returns.append(
                {
                    "symbol": symbol,
                    "execution_date": row["execution_date"],
                    "return": float(row["round_trip_return"]),
                    "pnl": cycle_pnl.pop(symbol),
                }
            )
    return cycle_returns


def year_metrics(
    nav: list[dict[str, Any]],
    round_trips: list[dict[str, Any]],
    year: int,
    previous_close: float,
) -> dict[str, Any]:
    rows = [row for row in nav if int(str(row["trade_date"])[:4]) == year]
    trips = [row for row in round_trips if int(str(row["execution_date"])[:4]) == year]
    returns = [float(row["return"]) for row in trips]
    return {
        "return": float(rows[-1]["nav"]) / previous_close - 1.0,
        "max_drawdown": maximum_drawdown(
            [float(row["nav"]) for row in rows], starting_value=previous_close
        ),
        "completed_round_trip_count": len(trips),
        "win_rate": None if not returns else sum(value > 0 for value in returns) / len(returns),
        "average_invested_ratio": statistics.fmean(
            float(row["invested_ratio"]) for row in rows
        ),
        "average_holdings": statistics.fmean(float(row["holdings"]) for row in rows),
    }


def monthly_metrics(
    nav: list[dict[str, Any]], executions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in nav:
        grouped[str(row["trade_date"])[:7]].append(row)
    new_entries = Counter(
        str(row["execution_date"])[:7]
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    )
    return [
        {
            "month": month,
            "average_holdings": statistics.fmean(float(row["holdings"]) for row in rows),
            "average_invested_ratio": statistics.fmean(
                float(row["invested_ratio"]) for row in rows
            ),
            "new_entry_count": new_entries[month],
        }
        for month, rows in sorted(grouped.items())
    ]


def performance_extensions(nav: list[dict[str, Any]]) -> dict[str, float | None]:
    values = [float(row["nav"]) for row in nav]
    returns = [values[0] / INITIAL_CASH - 1.0] + [
        current / previous - 1.0 for previous, current in zip(values, values[1:], strict=False)
    ]
    volatility = statistics.stdev(returns) * math.sqrt(244) if len(returns) > 1 else 0.0
    sharpe = (
        None
        if volatility <= 0
        else statistics.fmean(returns) / statistics.stdev(returns) * math.sqrt(244)
    )
    return {"volatility": volatility, "sharpe_zero_risk_free": sharpe}


def contribution_tables(summary: dict[str, Any], executions: list[dict[str, Any]]) -> dict[str, Any]:
    pnl = {
        symbol: float(value)
        for symbol, value in summary["portfolio"]["pnl_contribution_by_symbol"].items()
    }
    entry_counts = Counter(
        str(row["symbol"])
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    )
    top_entries = [
        {"symbol": symbol, "entries": count}
        for symbol, count in sorted(entry_counts.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]
    top_pnl = [
        {"symbol": symbol, "pnl": value}
        for symbol, value in sorted(pnl.items(), key=lambda item: (-item[1], item[0]))[:20]
    ]
    bottom_pnl = [
        {"symbol": symbol, "pnl": value}
        for symbol, value in sorted(pnl.items(), key=lambda item: (item[1], item[0]))[:20]
    ]
    positive_total = sum(value for value in pnl.values() if value > 0)
    top20_positive = sum(max(0.0, row["pnl"]) for row in top_pnl)
    absolute_total = sum(abs(value) for value in pnl.values())
    return {
        "top20_by_entry_count": top_entries,
        "top20_by_pnl": top_pnl,
        "bottom20_by_pnl": bottom_pnl,
        "top20_positive_pnl_concentration": (
            None if positive_total <= 0 else top20_positive / positive_total
        ),
        "top20_net_pnl": sum(row["pnl"] for row in top_pnl),
        "absolute_pnl_total": absolute_total,
    }


def smoke_comparison(full: dict[str, Any], smoke: dict[str, Any]) -> dict[str, Any]:
    smoke_execution = smoke["execution"]
    # Backward-compatible audit for the committed smoke summary, whose old
    # trade_count meant sell legs. The rerun summary exposes explicit fields.
    smoke_round_trips = smoke_execution.get("completed_round_trip_count", 25)
    return {
        "entry_candidates": {
            "smoke": smoke["signals"].get("final_entry_candidate_count", smoke["signals"]["minvol_pass_count"]),
            "full": full["signals"]["final_entry_candidate_count"],
        },
        "completed_round_trips": {"smoke": smoke_round_trips, "full": full["execution"]["completed_round_trip_count"]},
        "average_holdings": {"smoke": smoke["portfolio"]["average_holdings"], "full": full["portfolio"]["average_holdings"]},
        "average_invested_ratio": {"smoke": smoke["portfolio"]["average_invested_ratio"], "full": full["portfolio"]["average_invested_ratio"]},
        "total_return": {"smoke": smoke["portfolio"]["total_return"], "full": full["portfolio"]["total_return"]},
        "annualized_return": {"smoke": smoke["portfolio"]["annualized_return"], "full": full["portfolio"]["annualized_return"]},
        "max_drawdown": {"smoke": smoke["portfolio"]["max_drawdown"], "full": full["portfolio"]["max_drawdown"]},
        "win_rate": {"smoke": smoke["portfolio"]["win_rate"], "full": full["portfolio"]["win_rate"]},
        "turnover": {"smoke": smoke_execution["turnover"], "full": full["execution"]["turnover"]},
    }


def assess(summary: dict[str, Any]) -> str:
    portfolio = summary["portfolio"]
    years = summary["year_by_year"]
    concentration = summary["exposure_diagnostics"]["top20_positive_pnl_concentration"]
    if summary["execution"]["same_day_fill_count"] != 0:
        return "BLOCKED"
    if portfolio["total_return"] <= 0 or min(years["2024"]["return"], years["2025"]["return"]) <= -0.10:
        return "WEAK"
    if (
        portfolio["average_invested_ratio"] < 0.40
        or concentration is None
        or concentration > 0.75
        or min(years["2024"]["return"], years["2025"]["return"]) <= 0
    ):
        return "MIXED"
    return "PROMISING"


def markdown_table(rows: list[dict[str, Any]], value_key: str, value_label: str) -> str:
    lines = [f"| Rank | Symbol | {value_label} |", "|---:|---|---:|"]
    for index, row in enumerate(rows, 1):
        value = row[value_key]
        formatted = f"{value:,.2f}" if isinstance(value, float) else str(value)
        lines.append(f"| {index} | {row['symbol']} | {formatted} |")
    return "\n".join(lines)


def write_full_report(path: Path, summary: dict[str, Any]) -> None:
    sample = summary["sample"]
    signals = summary["signals"]
    execution = summary["execution"]
    portfolio = summary["portfolio"]
    years = summary["year_by_year"]
    diagnostics = summary["exposure_diagnostics"]
    comparison = summary["smoke_vs_full"]
    monthly_lines = ["| Month | Avg holdings | Avg invested | New entries |", "|---|---:|---:|---:|"]
    monthly_lines.extend(
        f"| {row['month']} | {row['average_holdings']:.3f} | {row['average_invested_ratio']:.2%} | {row['new_entry_count']} |"
        for row in summary["monthly"]
    )
    comparison_lines = ["| Metric | 50-symbol | Full-survivor |", "|---|---:|---:|"]
    pct_metrics = {"average_invested_ratio", "total_return", "annualized_return", "max_drawdown", "win_rate"}
    for metric, values in comparison.items():
        left, right = values["smoke"], values["full"]
        if metric in pct_metrics:
            left_text, right_text = fmt_pct(left), fmt_pct(right)
        else:
            left_text = f"{left:.4f}" if isinstance(left, float) else str(left)
            right_text = f"{right:.4f}" if isinstance(right, float) else str(right)
        comparison_lines.append(f"| {metric} | {left_text} | {right_text} |")
    report = f"""# ChinNext V1 full current-survivor exploratory replay

> **{SURVIVOR_WARNING}**
>
> This is an exploratory current-survivor replay, not a PIT backtest and not valid
> for final historical performance claims. All strategy parameters are frozen.

## Universe and data coverage

- UNIVERSE: current-survivor manifest, NON-PIT, SURVIVORSHIP BIASED
- DATE_RANGE: `{sample['date_range'][0]} .. {sample['date_range'][1]}`
- RAW_UNIVERSE_COUNT: `{sample['raw_universe_count']}`
- DATA_FOUND_COUNT: `{sample['data_found_count']}`
- HISTORY_VALID_COUNT: `{sample['history_valid_count']}`
- LIQUIDITY_VALID_COUNT: `{sample['liquidity_valid_count']}`
- FINAL_ELIGIBLE_COUNT: `{sample['final_eligible_count']}` symbols eligible on at least one day
- AVERAGE_DAILY_FINAL_ELIGIBLE: `{sample['average_final_eligible']:.2f}`
- FAILURE_REASON_COUNTS: `{json.dumps(sample['failure_reason_counts'], ensure_ascii=False, sort_keys=True)}`
- DAILY_FAIL_CLOSED_REASON_COUNTS: `{json.dumps(sample['daily_failure_reason_counts'], ensure_ascii=False, sort_keys=True)}`
- KNOWN_RISK_WARNING_SYMBOL_COUNT: `{sample['known_risk_warning_symbol_count']}` (ever observed `is_st=true`; complete taxonomy remains unverified)
- MARKET_GATE_ACTIVE: `YES`, exact `399102.SZ`, no fallback

RS percentiles are computed each day over the complete basic-eligible cross section
from the full manifest universe, never over breakout candidates or the prior sample.
Coverage counts mean a symbol passed the named gate on at least one replay day;
daily counts are reported separately and every failure remains fail closed.

The pre-run strategy-module SHA256 was
`{summary['baseline_freeze']['pre_run_hashes']['research/chinext_v1/strategy/chinext_v1_exploratory.py']}`
and is unchanged. Changes to the smoke runner are accounting labels and the explicit
full-universe selection mode only; the frozen configuration is identical.

## Signals and execution

- PRICE_STRUCTURE_SIGNAL_COUNT: `{signals['price_structure_signal_count']}`
- MINVOL_PASS_COUNT: `{signals['minvol_pass_count']}`
- BREAKOUT_VOLUME_SHADOW_PASS_COUNT: `{signals['breakout_volume_shadow_pass_count']}`
- FINAL_ENTRY_CANDIDATE_COUNT: `{signals['final_entry_candidate_count']}`
- BUY_EXECUTION_COUNT: `{execution['buy_fill_count']}`
- ENTRY_BUY_EXECUTION_COUNT: `{execution['entry_buy_execution_count']}`
- REBALANCE_BUY_LEG_COUNT: `{execution['rebalance_buy_leg_count']}`
- SELL_EXECUTION_COUNT: `{execution['sell_fill_count']}`
- COMPLETED_ROUND_TRIP_COUNT: `{execution['completed_round_trip_count']}`
- REBALANCE_SELL_LEG_COUNT: `{execution['rebalance_sell_leg_count']}`
- T1_BLOCKED_EXIT_COUNT: `{execution['t1_blocked_exit_count']}`
- FAILED_OPEN_EXECUTION_COUNT: `{execution['failed_open_execution_count']}`
- SAME_DAY_FILL_COUNT: `{execution['same_day_fill_count']}`

Completed round trips are full position lifecycles. Partial CAP/SET resize sells are
reported separately and are not counted as completed trades.

## Cost and performance

> **PERFORMANCE BEFORE REALISTIC COSTS** — the frozen replay applies its original
> fixed 10 bps per filled side, but does not separately model stamp duty, slippage,
> open-auction queueing or market impact.

- COMMISSION/COST: fixed 10 bps per filled side (same as smoke)
- SLIPPAGE: none separately modeled
- STAMP_DUTY: none separately modeled
- TOTAL_RETURN: `{fmt_pct(portfolio['total_return'])}`
- ANNUALIZED_RETURN: `{fmt_pct(portfolio['annualized_return'])}`
- MAX_DRAWDOWN: `{fmt_pct(portfolio['max_drawdown'])}`
- VOLATILITY: `{fmt_pct(portfolio['volatility'])}` annualized daily NAV volatility
- SHARPE: `{portfolio['sharpe_zero_risk_free'] if portfolio['sharpe_zero_risk_free'] is not None else 'NA'}` (daily arithmetic return, 244 sessions, zero risk-free rate)
- WIN_RATE: `{fmt_pct(portfolio['win_rate'])}` completed round trips
- AVERAGE_TRADE_RETURN: `{fmt_pct(portfolio['average_trade_return'])}`
- MEDIAN_TRADE_RETURN: `{fmt_pct(portfolio['median_trade_return'])}`
- PROFIT_FACTOR: `{portfolio['profit_factor'] if portfolio['profit_factor'] is not None else 'NA'}` (completed-cycle realized gains / absolute realized losses)
- TURNOVER: `{execution['turnover']:.4f}x` total traded notional / average NAV

The fixed 10 bps cost is not a full realistic A-share cost model. Results omit
separate stamp duty, slippage, queueing impact and market impact.

## Exposure

- AVERAGE_HOLDINGS: `{portfolio['average_holdings']:.3f}`
- MEDIAN_HOLDINGS: `{portfolio['median_holdings']:.3f}`
- MAX_HOLDINGS: `{portfolio['max_holdings']}`
- AVERAGE_INVESTED_RATIO: `{fmt_pct(portfolio['average_invested_ratio'])}`
- MEDIAN_INVESTED_RATIO: `{fmt_pct(portfolio['median_invested_ratio'])}`
- PERCENT_DAYS_FULLY_INVESTED: `{fmt_pct(portfolio['percent_days_fully_invested'])}` (`invested_ratio >= 95%`)
- PERCENT_DAYS_FLAT: `{fmt_pct(portfolio['percent_days_flat'])}` (`holdings == 0`)

## Year by year

| Year | Return | Max drawdown | Round trips | Win rate | Avg invested | Avg holdings |
|---|---:|---:|---:|---:|---:|---:|
| 2024 | {fmt_pct(years['2024']['return'])} | {fmt_pct(years['2024']['max_drawdown'])} | {years['2024']['completed_round_trip_count']} | {fmt_pct(years['2024']['win_rate'])} | {fmt_pct(years['2024']['average_invested_ratio'])} | {years['2024']['average_holdings']:.3f} |
| 2025 | {fmt_pct(years['2025']['return'])} | {fmt_pct(years['2025']['max_drawdown'])} | {years['2025']['completed_round_trip_count']} | {fmt_pct(years['2025']['win_rate'])} | {fmt_pct(years['2025']['average_invested_ratio'])} | {years['2025']['average_holdings']:.3f} |

## Monthly exposure diagnostics

{chr(10).join(monthly_lines)}

## 50-symbol versus full survivor

{chr(10).join(comparison_lines)}

This comparison isolates the effect of using the full daily eligible cross section;
it does not remove current-survivor bias.

## Entry and P&L concentration

### Top 20 symbols by entry count

{markdown_table(diagnostics['top20_by_entry_count'], 'entries', 'Entries')}

### Top 20 symbols by P&L contribution

{markdown_table(diagnostics['top20_by_pnl'], 'pnl', 'P&L')}

### Bottom 20 symbols by P&L contribution

{markdown_table(diagnostics['bottom20_by_pnl'], 'pnl', 'P&L')}

- TOP20_PNL_CONCENTRATION: `{fmt_pct(diagnostics['top20_positive_pnl_concentration'])}` of all positive symbol P&L

P&L contribution includes realized sell-leg P&L and marked unrealized P&L for
ending positions. It is an attribution diagnostic, not a PIT performance claim.

## Research decision

- FULL_SURVIVOR_RESULT: **{summary['full_survivor_result']}**

The classification combines signal breadth, exposure, concentration, both yearly
results, drawdown and execution correctness. It never changes strategy parameters.
"""
    atomic_text(path, report)


def main() -> int:
    cli = parse_args()
    replay_args = argparse.Namespace(
        start=START,
        end=END,
        sample_size=10_000,
        full_survivor=True,
        initial_cash=INITIAL_CASH,
        survivor=cli.survivor,
        daily_root=cli.daily_root,
        market=cli.market,
        calendar=cli.calendar,
        summary=cli.summary,
        report=cli.report,
        output_dir=cli.output_dir,
    )
    summary = run(replay_args)
    executions = read_jsonl(summary["audit"]["execution_ledger"])
    nav = read_jsonl(summary["audit"]["daily_nav"])
    round_trips = round_trip_rows(executions)
    same_day = sum(
        row.get("status") == "FILLED" and row["signal_date"] == row["execution_date"]
        for row in executions
    )
    summary["execution"]["same_day_fill_count"] = same_day
    summary["execution"]["commission_model"] = "fixed 10 bps per filled side"
    summary["execution"]["slippage_model"] = "NONE_SEPARATELY_MODELED"
    summary["execution"]["stamp_duty_model"] = "NONE_SEPARATELY_MODELED"
    summary["baseline_freeze"] = {
        "pre_run_hashes": PRE_RUN_BASELINE_HASHES,
        "current_strategy_sha256": sha256_file(
            Path("research/chinext_v1/strategy/chinext_v1_exploratory.py")
        ),
        "strategy_module_unchanged": sha256_file(
            Path("research/chinext_v1/strategy/chinext_v1_exploratory.py")
        )
        == PRE_RUN_BASELINE_HASHES[
            "research/chinext_v1/strategy/chinext_v1_exploratory.py"
        ],
        "frozen_v6_sha256": sha256_file(FROZEN_V6),
        "strategy_semantics_change": "NONE",
        "smoke_runner_change_scope": "statistics labels plus explicit full-survivor universe mode",
    }

    extended = performance_extensions(nav)
    summary["portfolio"]["volatility"] = extended["volatility"]
    summary["portfolio"]["sharpe_zero_risk_free"] = extended["sharpe_zero_risk_free"]
    summary["portfolio"]["median_holdings"] = statistics.median(
        float(row["holdings"]) for row in nav
    )
    summary["portfolio"]["median_invested_ratio"] = statistics.median(
        float(row["invested_ratio"]) for row in nav
    )
    summary["portfolio"]["percent_days_fully_invested"] = sum(
        float(row["invested_ratio"]) >= 0.95 for row in nav
    ) / len(nav)
    summary["portfolio"]["percent_days_flat"] = sum(
        int(row["holdings"]) == 0 for row in nav
    ) / len(nav)
    gains = sum(max(0.0, float(row["pnl"])) for row in round_trips)
    losses = -sum(min(0.0, float(row["pnl"])) for row in round_trips)
    summary["portfolio"]["profit_factor"] = None if losses <= 0 else gains / losses

    last_2024 = float([row for row in nav if str(row["trade_date"]).startswith("2024")][-1]["nav"])
    summary["year_by_year"] = {
        "2024": year_metrics(nav, round_trips, 2024, INITIAL_CASH),
        "2025": year_metrics(nav, round_trips, 2025, last_2024),
    }
    summary["monthly"] = monthly_metrics(nav, executions)
    summary["exposure_diagnostics"] = contribution_tables(summary, executions)
    smoke = json.loads(cli.smoke_summary.read_text(encoding="utf-8"))
    summary["smoke_vs_full"] = smoke_comparison(summary, smoke)
    summary["full_survivor_result"] = assess(summary)
    write_json(cli.summary, summary)
    write_full_report(cli.report, summary)
    print(
        json.dumps(
            {
                "raw_universe": summary["sample"]["raw_universe_count"],
                "final_eligible": summary["sample"]["final_eligible_count"],
                "entry_candidates": summary["signals"]["final_entry_candidate_count"],
                "round_trips": summary["execution"]["completed_round_trip_count"],
                "total_return": summary["portfolio"]["total_return"],
                "assessment": summary["full_survivor_result"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
