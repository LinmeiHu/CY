#!/usr/bin/env python3
"""Run the single authorized frozen ChinNext V1 PIT-B baseline replay."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from cyq_game.data import DataAssetRegistry, DataPurpose
from run_chinext_v1_full_survivor import (
    INITIAL_CASH,
    performance_extensions,
    read_jsonl,
    year_metrics,
)
from run_chinext_v1_smoke import (
    DEFAULT_CALENDAR,
    DEFAULT_DAILY_ROOT,
    DEFAULT_MARKET,
    atomic_text,
    fmt_pct,
    run,
    sha256_file,
    write_json,
)

ROOT = Path(__file__).resolve().parents[3]
START = date(2024, 1, 2)
END = date(2025, 12, 31)
AUTHORIZATION_ID = "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1"
AUTHORIZATION_PURPOSE = DataPurpose.CHINEXT_PIT_B_RESEARCH
REGISTRY = ROOT / "configs/data_asset_registry.json"
MANIFEST = ROOT / "research/chinext_v1/reports/chinext_v1_pit_master_manifest.json"
DAILY_MEMBERSHIP = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
SECURITY_MASTER = ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CURRENT_SURVIVOR = ROOT / "research/supermind_v6/manifests/chinext_current_survivor_universe.json"
CURRENT_SUMMARY = ROOT / "research/chinext_v1/reports/chinext_v1_full_survivor_summary.json"
SOURCE_CAPTURE = ROOT / "research/chinext_v1/data/pit_2024_2025/raw/source_capture.json"
BAOSTOCK_BASIC = ROOT / "research/chinext_v1/data/pit_2024_2025/raw/baostock_stock_basic.csv"
LOCAL_MASTER = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet")
TRADE_CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
BUILD_SCRIPT = ROOT / "research/chinext_v1/scripts/build_chinext_v1_pit_master.py"
CONSUMER = Path(__file__).resolve()
EXPECTED = {
    MANIFEST: "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7",
    DAILY_MEMBERSHIP: "9a6a0a071916b2af99a0f3f16b887672716b78428d28b4368f09bdd32d208c3d",
    SECURITY_MASTER: "dc8aaacbe76c6096e38c98630d632c64270a9563d466b7eb2ff5b91635ad9591",
    STRATEGY: "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    BAOSTOCK_BASIC: "2438d4fe64af83f3f8b20daffe458621b86777ed1fcf53b1e3150ad7c78bd65f",
    SOURCE_CAPTURE: "92dc323d48d992665fa993bbc70189ab7f6fe44371e56b0a354964f6f21151f1",
    LOCAL_MASTER: "385b222370b26bb3d09a5c06181e26cf1b636fde8f7c50d0ed04521f7a197d50",
    TRADE_CALENDAR: "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
    CY006_MANIFEST: "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
    BUILD_SCRIPT: "b862e140dc3281cf55c4f23692318fb2f0f5d448a06487fa2332e53c3facce83",
}
CURRENT_COMPARATOR = {
    "total_return": 1.052422,
    "max_drawdown": -0.262272,
    "top20_positive_pnl_concentration": 0.842544,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-root", type=Path, default=DEFAULT_DAILY_ROOT)
    parser.add_argument("--market", type=Path, default=DEFAULT_MARKET)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR)
    parser.add_argument(
        "--summary",
        type=Path,
        default=ROOT / "research/chinext_v1/reports/chinext_v1_pit_replay_summary.json",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "research/chinext_v1/reports/chinext_v1_pit_replay.md",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "research/chinext_v1/output/chinext_v1_pit_replay",
    )
    return parser.parse_args()


def validate_identities() -> tuple[dict[str, str], Any]:
    actual = {str(path): sha256_file(path) for path in EXPECTED}
    mismatches = {
        str(path): {"expected": expected, "actual": actual[str(path)]}
        for path, expected in EXPECTED.items()
        if actual[str(path)] != expected
    }
    if mismatches:
        raise RuntimeError(f"frozen PIT identity mismatch: {mismatches}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    daily = manifest["artifacts"]["daily_membership"]
    master = manifest["artifacts"]["security_master"]
    if manifest["date_range"] != [START.isoformat(), END.isoformat()]:
        raise RuntimeError("frozen PIT manifest date range mismatch")
    if (daily["date_count"], daily["unique_symbols"], daily["rows"]) != (485, 1404, 661802):
        raise RuntimeError("frozen PIT manifest cardinality mismatch")
    if daily["path"] != str(DAILY_MEMBERSHIP) or master["path"] != str(SECURITY_MASTER):
        raise RuntimeError("frozen PIT artifact path mismatch")
    current = json.loads(CURRENT_SUMMARY.read_text(encoding="utf-8"))
    if abs(float(current["portfolio"]["total_return"]) - CURRENT_COMPARATOR["total_return"]) > 5e-7:
        raise RuntimeError("frozen current-survivor return comparator mismatch")
    if abs(float(current["portfolio"]["max_drawdown"]) - CURRENT_COMPARATOR["max_drawdown"]) > 5e-7:
        raise RuntimeError("frozen current-survivor drawdown comparator mismatch")
    registry = DataAssetRegistry.load(REGISTRY)
    authorization = registry.authorize_bounded_research(
        AUTHORIZATION_ID,
        purpose=AUTHORIZATION_PURPOSE,
        manifest_path=MANIFEST,
        manifest_sha256=actual[str(MANIFEST)],
        artifacts={
            "daily_membership": (DAILY_MEMBERSHIP, actual[str(DAILY_MEMBERSHIP)]),
            "security_master": (SECURITY_MASTER, actual[str(SECURITY_MASTER)]),
        },
        start=START,
        end=END,
        dependency_asset_id="QD-007",
        consumer_path=CONSUMER,
        strategy_path=STRATEGY,
        strategy_sha256=actual[str(STRATEGY)],
        current_survivor_fallback=False,
    )
    if registry.assets["QD-007"].status != "DISCOVERY_ONLY":
        raise RuntimeError("QD-007 global status changed")
    return actual, authorization


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
                    "entry_signal_date": row["signal_date"],
                    "entry_execution_date": row["execution_date"],
                    "entry_reason": row["signal_reason"],
                    "buy_shares": 0.0,
                    "buy_notional": 0.0,
                    "buy_cost": 0.0,
                    "realized_pnl": 0.0,
                }
            if symbol not in active:
                raise ValueError(f"rebalance buy without active cycle for {symbol}")
            cycle = active[symbol]
            cycle["buy_shares"] += float(row["shares"])
            cycle["buy_notional"] += float(row["notional"])
            cycle["buy_cost"] += float(row["notional"]) + float(row["cost"])
        else:
            if symbol not in active:
                raise ValueError(f"sell without active cycle for {symbol}")
            cycle = active[symbol]
            cycle["realized_pnl"] += float(row["realized_pnl"])
            if row.get("completed_round_trip") is True:
                cycle = active.pop(symbol)
                cycle.update(
                    {
                        "entry_price": cycle["buy_notional"] / cycle["buy_shares"],
                        "capital": cycle["buy_cost"],
                        "exit_signal_date": row["signal_date"],
                        "exit_execution_date": row["execution_date"],
                        "exit_price": float(row["execution_price"]),
                        "exit_reason": row["signal_reason"],
                        "round_trip_return": float(row["round_trip_return"]),
                        "execution_date": row["execution_date"],
                        "return": float(row["round_trip_return"]),
                        "pnl": cycle["realized_pnl"],
                    }
                )
                result.append(cycle)
    return result


def concentration(round_trips: list[dict[str, Any]], total_return: float) -> dict[str, Any]:
    if not round_trips:
        raise ValueError("PIT replay produced no completed round trips")
    ordered = sorted(
        round_trips,
        key=lambda row: (-float(row["realized_pnl"]), row["symbol"], row["exit_execution_date"]),
    )
    positive_total = sum(max(0.0, float(row["realized_pnl"])) for row in ordered)
    if positive_total <= 0:
        raise ValueError("PIT replay has no positive completed-round-trip P&L")
    result: dict[str, Any] = {"positive_round_trip_pnl": positive_total}
    for count in (10, 20):
        top = ordered[:count]
        result[f"top{count}_positive_pnl_concentration"] = (
            sum(max(0.0, float(row["realized_pnl"])) for row in top) / positive_total
        )
        result[f"return_ex_best{count}"] = total_return - sum(
            float(row["realized_pnl"]) for row in top
        ) / INITIAL_CASH
    result["top20_trades"] = ordered[:20]
    return result


def universe_attribution(
    summary: dict[str, Any],
    executions: list[dict[str, Any]],
    round_trips: list[dict[str, Any]],
) -> dict[str, Any]:
    membership = pd.read_parquet(DAILY_MEMBERSHIP, columns=["symbol"])
    pit_symbols = set(membership["symbol"].astype(str))
    current_payload = json.loads(CURRENT_SURVIVOR.read_text(encoding="utf-8"))
    current_symbols = {str(row["symbol"]) for row in current_payload["records"]}
    historical_non_survivors = pit_symbols - current_symbols
    selected_symbols = {
        str(row["symbol"])
        for row in executions
        if row.get("status") == "FILLED"
        and row.get("side") == "BUY"
        and row.get("new_position") is True
    }
    non_survivor_selected = selected_symbols & historical_non_survivors
    contributions = {
        str(symbol): float(value)
        for symbol, value in summary["portfolio"]["pnl_contribution_by_symbol"].items()
    }
    master = pd.read_parquet(SECURITY_MASTER)
    master["list_date"] = pd.to_datetime(master["list_date"]).dt.date
    delisted = set(master.loc[master["out_date"].notna(), "symbol"].astype(str))
    delisted_selected = non_survivor_selected & delisted
    non_survivor_trips = [row for row in round_trips if row["symbol"] in non_survivor_selected]
    delisted_trips = [row for row in round_trips if row["symbol"] in delisted_selected]
    static_future_listed = set(
        master.loc[master["list_date"] > START, "symbol"].astype(str)
    ) & current_symbols
    reason_counts = Counter()
    for symbol in historical_non_survivors:
        reason_counts["delisted" if symbol in delisted else "other_unresolved"] += 1
    return {
        "historical_non_survivor_symbol_count": len(historical_non_survivors),
        "historical_non_survivor_selected_count": len(non_survivor_selected),
        "historical_non_survivor_trade_count": len(non_survivor_trips),
        "historical_non_survivor_pnl": sum(contributions.get(symbol, 0.0) for symbol in non_survivor_selected),
        "historical_non_survivor_total_return_contribution": sum(
            contributions.get(symbol, 0.0) for symbol in non_survivor_selected
        ) / INITIAL_CASH,
        "delisted_historical_securities_selected": len(delisted_selected),
        "delisted_historical_trades": len(delisted_trips),
        "delisted_historical_pnl": sum(contributions.get(symbol, 0.0) for symbol in delisted_selected),
        "future_listed_exclusion_count": len(static_future_listed),
        "reason_classification": {
            "status": "PARTIAL",
            "fact_counts": dict(sorted(reason_counts.items())),
            "unresolved": "non-delisted current-pool exclusions cannot be reliably split into later ST versus other reasons",
        },
        "historical_non_survivor_symbols": sorted(historical_non_survivors),
        "selected_historical_non_survivors": sorted(non_survivor_selected),
        "selected_delisted_historical_securities": sorted(delisted_selected),
        "future_listed_static_current_survivors": sorted(static_future_listed),
    }


def bias_assessment(summary: dict[str, Any]) -> str:
    pit_return = float(summary["portfolio"]["total_return"])
    concentration20 = float(summary["pnl_concentration"]["top20_positive_pnl_concentration"])
    return_ex20 = float(summary["pnl_concentration"]["return_ex_best20"])
    return_delta = pit_return - CURRENT_COMPARATOR["total_return"]
    survivorship_sensitive = return_delta <= -0.25
    winner_concentrated = concentration20 > 0.75 or return_ex20 <= 0
    if survivorship_sensitive and winner_concentrated:
        return "MIXED"
    if survivorship_sensitive:
        return "SURVIVORSHIP_SENSITIVE"
    if winner_concentrated:
        return "WINNER_CONCENTRATED"
    return "ROBUST"


def write_report(path: Path, summary: dict[str, Any]) -> None:
    p = summary["portfolio"]
    c = summary["pnl_concentration"]
    x = summary["pit_vs_current_survivor"]
    a = summary["survivorship_attribution"]
    top_lines = [
        "| Rank | Symbol | Entry signal | Entry execution | Exit execution | P&L | Return |",
        "|---:|---|---|---|---|---:|---:|",
    ]
    for rank, row in enumerate(c["top20_trades"], 1):
        top_lines.append(
            f"| {rank} | {row['symbol']} | {row['entry_signal_date']} | "
            f"{row['entry_execution_date']} | {row['exit_execution_date']} | "
            f"{row['realized_pnl']:,.2f} | {row['round_trip_return']:.4%} |"
        )
    report = f"""# ChinNext V1 — frozen PIT-B replay

> **FORMAL BOUNDED PIT-B RESEARCH / NOT STRICT ARCHIVAL PIT-A**

## Frozen run identity

- AUTHORIZATION_ID: `{summary['authorization']['authorization_id']}`
- AUTHORIZATION_VALID: `YES`
- QD007_GLOBAL_STATUS: `DISCOVERY_ONLY`; globally upgraded: `NO`
- ONLY_MATERIAL_DIFFERENCE_FROM_CURRENT_SURVIVOR_BASELINE: `PIT universe membership`
- CURRENT_SURVIVOR_USED_FOR_TRADING: `NO`
- DATE_RANGE: `{START} .. {END}` (`485` sessions)
- STRATEGY_SHA256: `{summary['frozen_identity'][str(STRATEGY)]}`
- PIT_MANIFEST_SHA256: `{summary['frozen_identity'][str(MANIFEST)]}`
- PIT_REBUILT: `NO`
- COST: fixed `10 bps/side`; separate stamp duty: `NONE` (matches frozen comparator)

The existing replay's signals, configuration, next-open execution, T+1/limit
checks, corporate-action handling, accounting and ledgers are reused. The only
decision-input change is replacing the static current-survivor pool with the
authorized date-specific PIT membership and its frozen listing-session age.

## Performance

- PIT_TOTAL_RETURN: `{fmt_pct(p['total_return'])}`
- PIT_ANNUALIZED_RETURN: `{fmt_pct(p['annualized_return'])}`
- PIT_MAX_DRAWDOWN: `{fmt_pct(p['max_drawdown'])}`
- VOLATILITY: `{fmt_pct(p['volatility'])}`
- SHARPE_RF0: `{p['sharpe_zero_risk_free']:.4f}`
- TRADE_COUNT: `{summary['execution']['completed_round_trip_count']}` completed round trips
- WIN_RATE: `{fmt_pct(p['win_rate'])}`
- MEDIAN_TRADE_RETURN: `{fmt_pct(p['median_trade_return'])}`
- MEAN_TRADE_RETURN: `{fmt_pct(p['average_trade_return'])}`
- 2024_RETURN: `{fmt_pct(summary['year_by_year']['2024']['return'])}`
- 2025_RETURN: `{fmt_pct(summary['year_by_year']['2025']['return'])}`
- PIT_TOP10_PNL_CONCENTRATION: `{fmt_pct(c['top10_positive_pnl_concentration'])}`
- PIT_TOP20_PNL_CONCENTRATION: `{fmt_pct(c['top20_positive_pnl_concentration'])}`
- RETURN_EX_BEST10: `{fmt_pct(c['return_ex_best10'])}` — {'still profitable' if c['return_ex_best10'] > 0 else 'not profitable'}
- RETURN_EX_BEST20: `{fmt_pct(c['return_ex_best20'])}` — {'still profitable' if c['return_ex_best20'] > 0 else 'not profitable'}

Concentration is the share of all positive completed-round-trip P&L, matching the
frozen current-survivor robustness comparator. Return exclusions subtract those
completed-cycle P&Ls from final portfolio return; ending marked positions remain.

## Exact frozen comparison

| Metric | PIT | Current survivor | Delta (pp) | Relative change |
|---|---:|---:|---:|---:|
| Total return | {fmt_pct(p['total_return'])} | 105.2422% | {x['return_delta_pp']:.4f} | {x['return_relative_change']:.4%} |
| Max drawdown | {fmt_pct(p['max_drawdown'])} | -26.2272% | {x['drawdown_delta_pp']:.4f} | {x['drawdown_relative_change']:.4%} |
| Top20 concentration | {fmt_pct(c['top20_positive_pnl_concentration'])} | 84.2544% | {x['top20_concentration_delta_pp']:.4f} | {x['top20_concentration_relative_change']:.4%} |

- **FACT:** With universe membership as the only material change, the measured
  return treatment effect is `{x['return_delta_pp']:.4f}` percentage points.
- **INFERENCE:** This is a PIT/universe-treatment effect; it is not proof that every
  basis point is caused by one single survivorship-bias mechanism.

## Historical non-survivor attribution

- HISTORICAL_NON_SURVIVOR_SYMBOL_COUNT: `{a['historical_non_survivor_symbol_count']}`
- SELECTED_COUNT: `{a['historical_non_survivor_selected_count']}`
- TRADE_COUNT: `{a['historical_non_survivor_trade_count']}` completed cycles
- TOTAL_PNL: `{a['historical_non_survivor_pnl']:,.2f}` (realized plus ending mark, if any)
- TOTAL_RETURN_CONTRIBUTION: `{fmt_pct(a['historical_non_survivor_total_return_contribution'])}`
- DELISTED_HISTORICAL_SECURITIES_SELECTED: `{a['delisted_historical_securities_selected']}`
- DELISTED_HISTORICAL_TRADES: `{a['delisted_historical_trades']}`
- DELISTED_HISTORICAL_PNL: `{a['delisted_historical_pnl']:,.2f}`
- FUTURE_LISTED_EXCLUSION_COUNT: `{a['future_listed_exclusion_count']}`

**FACT:** `delisted` is assigned only where the frozen security master has an
explicit `out_date`. **UNRESOLVED:** the remaining current-pool exclusions cannot
be reliably separated into later ST versus other exclusion causes. The
future-listed count measures static current-survivor universe membership before
true listing, not actual fills; missing history may still have blocked a signal.

## Top 20 completed trades by P&L

{chr(10).join(top_lines)}

The standard execution ledger also preserves prices, shares, notional, target
weight, reason, costs, T+1 status and failed executions. It is the authoritative
leg-level audit trail; this table aggregates completed position cycles only.

## Bias assessment

- BIAS_ASSESSMENT: **{summary['bias_assessment']}**

Classification rules were frozen before inspecting the formal result: a return
drop of at least 25 percentage points is survivorship-sensitive; Top20 above 75%
or non-positive return without the best 20 is winner-concentrated; both is mixed.
No strategy parameter or execution rule is changed in response to this result.

## Correctness audit

- SAME_DAY_FILL_COUNT: `{summary['execution']['same_day_fill_count']}`
- STALE_HELD_VALUATION_COUNT: `{summary['audit']['stale_held_valuation_count']}`
- CURRENT_SURVIVOR_FALLBACK: `NO`
- EXECUTION_LEDGER: `{summary['audit']['execution_ledger']}` (`{summary['audit']['execution_ledger_sha256']}`)
- DAILY_NAV: `{summary['audit']['daily_nav']}` (`{summary['audit']['daily_nav_sha256']}`)
"""
    atomic_text(path, report)


def main() -> int:
    cli = parse_args()
    frozen_identity, authorization = validate_identities()
    replay_args = argparse.Namespace(
        start=START,
        end=END,
        sample_size=10_000,
        full_survivor=True,
        initial_cash=INITIAL_CASH,
        pit_membership=DAILY_MEMBERSHIP,
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
    round_trips = reconstruct_round_trips(executions)
    concentration_result = concentration(round_trips, float(summary["portfolio"]["total_return"]))
    same_day = sum(
        row.get("status") == "FILLED" and row["signal_date"] == row["execution_date"]
        for row in executions
    )
    if same_day != 0:
        raise RuntimeError("same-day fill detected in formal PIT replay")
    if summary["audit"]["stale_held_valuation_count"] != 0:
        raise RuntimeError("stale held valuation detected in formal PIT replay")
    if summary["execution"]["transaction_cost_bps_per_side"] != 10.0:
        raise RuntimeError("formal PIT replay cost differs from frozen comparator")
    if summary["execution"]["completed_round_trip_count"] != len(round_trips):
        raise RuntimeError("round-trip ledger count mismatch")
    extended = performance_extensions(nav)
    summary["portfolio"].update(
        {
            "volatility": extended["volatility"],
            "sharpe_zero_risk_free": extended["sharpe_zero_risk_free"],
        }
    )
    last_2024 = float([row for row in nav if str(row["trade_date"]).startswith("2024")][-1]["nav"])
    summary["year_by_year"] = {
        "2024": year_metrics(nav, round_trips, 2024, INITIAL_CASH),
        "2025": year_metrics(nav, round_trips, 2025, last_2024),
    }
    summary["pnl_concentration"] = concentration_result
    pit_return = float(summary["portfolio"]["total_return"])
    pit_drawdown = float(summary["portfolio"]["max_drawdown"])
    pit_concentration20 = float(concentration_result["top20_positive_pnl_concentration"])
    summary["pit_vs_current_survivor"] = {
        "current_frozen_comparator": CURRENT_COMPARATOR,
        "return_delta_pp": (pit_return - CURRENT_COMPARATOR["total_return"]) * 100.0,
        "drawdown_delta_pp": (pit_drawdown - CURRENT_COMPARATOR["max_drawdown"]) * 100.0,
        "top20_concentration_delta_pp": (
            pit_concentration20 - CURRENT_COMPARATOR["top20_positive_pnl_concentration"]
        ) * 100.0,
        "return_relative_change": pit_return / CURRENT_COMPARATOR["total_return"] - 1.0,
        "drawdown_relative_change": pit_drawdown / CURRENT_COMPARATOR["max_drawdown"] - 1.0,
        "top20_concentration_relative_change": (
            pit_concentration20 / CURRENT_COMPARATOR["top20_positive_pnl_concentration"] - 1.0
        ),
    }
    summary["survivorship_attribution"] = universe_attribution(summary, executions, round_trips)
    summary["authorization"] = {
        "authorization_id": authorization.authorization_id,
        "purpose": authorization.purpose.value,
        "asset_id": authorization.asset_id,
        "dependency_asset_id": authorization.dependency_asset_id,
        "dependency_status": authorization.dependency_status,
        "valid": True,
        "current_survivor_fallback": False,
    }
    summary["frozen_identity"] = frozen_identity
    summary["only_material_difference_from_current_survivor_baseline"] = "PIT universe membership"
    summary["pit_rebuilt"] = False
    summary["current_survivor_used_for_trading"] = False
    summary["execution"].update(
        {
            "same_day_fill_count": same_day,
            "commission_model": "fixed 10 bps per filled side",
            "slippage_model": "NONE_SEPARATELY_MODELED",
            "stamp_duty_model": "NONE_SEPARATELY_MODELED",
        }
    )
    summary["bias_assessment"] = bias_assessment(summary)
    write_json(cli.summary, summary)
    write_report(cli.report, summary)
    print(
        json.dumps(
            {
                "authorization_valid": True,
                "pit_total_return": pit_return,
                "pit_max_drawdown": pit_drawdown,
                "completed_round_trips": len(round_trips),
                "bias_assessment": summary["bias_assessment"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
