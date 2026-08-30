#!/usr/bin/env python3
"""Zero-replay unified yearly decomposition of frozen CHINEXT V1 artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any, Iterable

import duckdb

ROOT = Path(__file__).resolve().parents[4]
WORK = ROOT / "research/chinext_v1/regime_attribution"
BASELINE_MANIFEST = WORK / "artifacts/baseline_manifest.json"
OUTPUT_JSON = WORK / "artifacts/yearly_decomposition.json"
OUTPUT_METRICS_CSV = WORK / "artifacts/yearly_metrics.csv"
OUTPUT_TRADES_CSV = WORK / "artifacts/yearly_trades.csv"
REPORT = WORK / "reports/phase1_yearly_decomposition.md"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
DAILY_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
CY006_MANIFEST = Path(
    "/Users/linmei/Documents/CY/data/input_inventories/"
    "CY-006-pit-b-daily-v2-2018-2026-20260821.json"
)
CALENDAR = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet"
)
INITIAL_CASH = 1_000_000.0
EXPECTED_STRATEGY = "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a"
EXPECTED_CY006_MANIFEST = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
EXPECTED_CALENDAR = "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae"
EXPECTED_YEAR_RETURN = {
    2018: -0.03783516999999992,
    2019: 0.23490683088052555,
    2020: 0.05267228742443164,
    2021: 0.31776904262665284,
    2022: -0.1729136755700007,
    2023: 0.021392085054959376,
    2024: 0.4904941877500004,
    2025: 0.377007823927356,
}
EXPECTED_YEAR_TRADES = {
    2018: 11,
    2019: 47,
    2020: 74,
    2021: 62,
    2022: 37,
    2023: 57,
    2024: 38,
    2025: 73,
}
EXPECTED_TERMINAL_OPEN_CYCLES = {
    "EXTENDED_2018_2021": 0,
    "HOLDOUT_O0_2022_2023": 0,
    "DEVELOPMENT_2024_2025": 10,
}

BLOCKS = {
    "EXTENDED_2018_2021": ROOT
    / "research/chinext_v1/output/chinext_v1_extended_2018_2021",
    "HOLDOUT_O0_2022_2023": ROOT
    / "research/chinext_v1/output/chinext_v1_phase9b_oos/O0_BASELINE",
    "DEVELOPMENT_2024_2025": ROOT
    / "research/chinext_v1/output/chinext_v1_pit_replay",
}


class DecompositionError(RuntimeError):
    """Raised when frozen inputs or accounting invariants do not reconcile."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def validate_inputs() -> tuple[dict[str, Any], dict[str, dict[str, str]]]:
    baseline = json.loads(BASELINE_MANIFEST.read_text(encoding="utf-8"))
    if sha256_file(STRATEGY) != EXPECTED_STRATEGY:
        raise DecompositionError("authoritative strategy hash mismatch")
    if sha256_file(CY006_MANIFEST) != EXPECTED_CY006_MANIFEST:
        raise DecompositionError("CY-006 manifest hash mismatch")
    if sha256_file(CALENDAR) != EXPECTED_CALENDAR:
        raise DecompositionError("calendar hash mismatch")
    actual: dict[str, dict[str, str]] = {}
    for block, directory in BLOCKS.items():
        manifest = baseline["blocks"][block]
        paths = {
            "daily_nav": directory / "daily_nav.jsonl",
            "event_ledger": directory / "event_ledger.jsonl",
            "execution_ledger": directory / "execution_ledger.jsonl",
        }
        actual[block] = {name: sha256_file(path) for name, path in paths.items()}
        for name, digest in actual[block].items():
            if digest != manifest[f"{name}_sha256"]:
                raise DecompositionError(f"{block} {name} hash mismatch")
    return baseline, actual


def build_cycles(executions: list[dict[str, Any]], block: str) -> list[dict[str, Any]]:
    active: dict[str, dict[str, Any]] = {}
    counters: Counter[str] = Counter()
    result: list[dict[str, Any]] = []
    for row in executions:
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY":
            if row.get("new_position") is True:
                if symbol in active:
                    raise DecompositionError(f"overlapping position cycle: {block} {symbol}")
                counters[symbol] += 1
                active[symbol] = {
                    "baseline_block": block,
                    "trade_id": f"{block}:{symbol}-{counters[symbol]:03d}",
                    "symbol": symbol,
                    "entry_signal_date": str(row["signal_date"]),
                    "entry_execution_date": str(row["execution_date"]),
                    "entry_price": float(row["execution_price"]),
                    "entry_reason": str(row["signal_reason"]),
                    "buy_shares": 0.0,
                    "buy_notional": 0.0,
                    "buy_cost": 0.0,
                    "realized_pnl": 0.0,
                    "buy_fill_count": 0,
                    "sell_fill_count": 0,
                }
            if symbol not in active:
                raise DecompositionError(f"buy without active cycle: {block} {symbol}")
            cycle = active[symbol]
            cycle["buy_shares"] += float(row["shares"])
            cycle["buy_notional"] += float(row["notional"])
            cycle["buy_cost"] += float(row["notional"]) + float(row["cost"])
            cycle["buy_fill_count"] += 1
        else:
            if symbol not in active:
                raise DecompositionError(f"sell without active cycle: {block} {symbol}")
            cycle = active[symbol]
            cycle["realized_pnl"] += float(row["realized_pnl"])
            cycle["sell_fill_count"] += 1
            if row.get("completed_round_trip") is True:
                cycle = active.pop(symbol)
                cycle.update(
                    {
                        "weighted_average_buy_price": cycle["buy_notional"]
                        / cycle["buy_shares"],
                        "capital": cycle["buy_cost"],
                        "exit_signal_date": str(row["signal_date"]),
                        "exit_execution_date": str(row["execution_date"]),
                        "exit_price": float(row["execution_price"]),
                        "raw_exit_reason": str(row["signal_reason"]),
                        "round_trip_return": float(row["round_trip_return"]),
                    }
                )
                result.append(cycle)
    expected_open = EXPECTED_TERMINAL_OPEN_CYCLES.get(block, 0)
    if len(active) != expected_open:
        raise DecompositionError(
            f"unexpected terminal open cycles: {block}: "
            f"{len(active)} != {expected_open}: {sorted(active)}"
        )
    return result


def enrich_event_lineage(
    trades: list[dict[str, Any]], events: list[dict[str, Any]]
) -> None:
    entry_events = {
        (str(row["symbol"]), str(row["signal_date"])): row
        for row in events
        if row.get("event") == "ENTRY_SIGNAL_EVALUATED"
    }
    individual = {
        (str(row["symbol"]), str(row["signal_date"]))
        for row in events
        if row.get("event") == "INDIVIDUAL_EXIT_SIGNAL"
    }
    removals = {
        (str(symbol), str(row["signal_date"]))
        for row in events
        if row.get("event") == "DESIRED_SET_CHANGED"
        for symbol in row.get("previous", [])
        if symbol not in row.get("desired", [])
    }
    for trade in trades:
        entry_key = (trade["symbol"], trade["entry_signal_date"])
        if entry_key not in entry_events:
            raise DecompositionError(f"missing entry event: {trade['trade_id']}")
        event = entry_events[entry_key]
        trade["entry_event"] = event
        exit_key = (trade["symbol"], trade["exit_signal_date"])
        raw = trade["raw_exit_reason"]
        if raw == "MARKET_MA20_X2":
            canonical = "MARKET_MA20_X2"
        elif raw == "MARKET_CLOSE_LT_MA20_X0.96":
            canonical = "MARKET_EMERGENCY_X0.96"
        elif exit_key in individual and exit_key in removals:
            canonical = "INDIVIDUAL_MA30_X2_AND_SET_REMOVAL"
        elif exit_key in individual:
            canonical = "INDIVIDUAL_MA30_X2"
        elif exit_key in removals:
            canonical = "SET_REMOVAL"
        else:
            canonical = "UNRESOLVED_FAIL_CLOSED"
        trade["canonical_exit_reason"] = canonical


def load_sessions() -> list[str]:
    connection = duckdb.connect()
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE)
        FROM read_parquet(?)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2025-12-31'
        ORDER BY trade_date
        """,
        [str(CALENDAR)],
    ).fetchall()
    connection.close()
    return [row[0].isoformat() for row in rows]


def load_trade_price_rows(
    symbols: set[str],
) -> dict[tuple[str, str], dict[str, Any]]:
    paths = [
        str(DAILY_ROOT / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2026)
    ]
    connection = duckdb.connect()
    rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE),symbol,high,low,close,
               corporate_action_count,corporate_action_available_date,
               corporate_action_blocking,corporate_action_valid,
               share_multiplier,cash_per_share,rights_ratio,
               hard_valid,available_at,snapshot_id
        FROM read_parquet(?,union_by_name=true)
        WHERE symbol IN (SELECT * FROM unnest(?))
          AND trade_date BETWEEN DATE '2018-01-02' AND DATE '2025-12-31'
        ORDER BY symbol,trade_date
        """,
        [paths, sorted(symbols)],
    ).fetchall()
    connection.close()
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row[1]), row[0].isoformat())
        if key in result:
            raise DecompositionError(f"duplicate daily price key: {key}")
        result[key] = {
            "high": row[2],
            "low": row[3],
            "close": row[4],
            "corporate_action_count": row[5],
            "corporate_action_available_date": row[6],
            "corporate_action_blocking": row[7],
            "corporate_action_valid": row[8],
            "share_multiplier": row[9],
            "cash_per_share": row[10],
            "rights_ratio": row[11],
            "hard_valid": row[12],
            "available_at": row[13],
            "snapshot_id": row[14],
        }
    return result


def finite_or_default(value: Any, default: float) -> float:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return default
    return converted if math.isfinite(converted) else default


def action_values(row: dict[str, Any], day: str) -> tuple[bool, float, float]:
    if int(row.get("corporate_action_count") or 0) <= 0:
        return False, 1.0, 0.0
    multiplier = finite_or_default(row.get("share_multiplier"), 1.0)
    cash = finite_or_default(row.get("cash_per_share"), 0.0)
    rights = finite_or_default(row.get("rights_ratio"), 0.0)
    available = row.get("corporate_action_available_date")
    visible = available is not None and str(available)[:10] <= day
    valid = (
        row.get("corporate_action_blocking") is False
        and row.get("corporate_action_valid") is True
        and visible
        and rights == 0.0
        and multiplier > 0.0
        and all(math.isfinite(value) for value in (multiplier, cash, rights))
    )
    return valid, multiplier, cash


def holding_features(
    trade: dict[str, Any],
    sessions: list[str],
    session_index: dict[str, int],
    price_rows: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    start = session_index[trade["entry_execution_date"]]
    end = session_index[trade["exit_execution_date"]]
    entry_price = float(trade["entry_price"])
    share_factor = 1.0
    cash_per_original_share = 0.0
    high_returns: list[tuple[int, float]] = []
    low_returns: list[tuple[int, float]] = []
    close_returns: list[tuple[int, float]] = []
    early: dict[str, float] = {}
    for offset, day in enumerate(sessions[start : end + 1]):
        key = (trade["symbol"], day)
        if key not in price_rows:
            raise DecompositionError(f"held attribution row missing: {trade['trade_id']} {day}")
        row = price_rows[key]
        if day > trade["entry_execution_date"] and int(
            row.get("corporate_action_count") or 0
        ) > 0:
            valid, multiplier, cash = action_values(row, day)
            if not valid:
                raise DecompositionError(
                    f"held path reached unresolved corporate action: {trade['trade_id']} {day}"
                )
            cash_per_original_share += share_factor * cash
            share_factor *= multiplier

        def total_return(price: float) -> float:
            return (share_factor * price + cash_per_original_share) / entry_price - 1.0

        if day == trade["exit_execution_date"]:
            value = total_return(float(trade["exit_price"]))
            high_returns.append((offset, value))
            low_returns.append((offset, value))
            close_returns.append((offset, value))
        else:
            if not all(
                value is not None and math.isfinite(float(value))
                for value in (row["high"], row["low"], row["close"])
            ):
                raise DecompositionError(f"nonfinite held path: {trade['trade_id']} {day}")
            high_returns.append((offset, total_return(float(row["high"]))))
            low_returns.append((offset, total_return(float(row["low"]))))
            close_value = total_return(float(row["close"]))
            close_returns.append((offset, close_value))
            if offset + 1 in (5, 10, 20):
                early[f"return_{offset + 1}d"] = close_value
    mfe_day, mfe = max(high_returns, key=lambda item: item[1])
    mae_day, mae = min(low_returns, key=lambda item: item[1])
    peak_day, peak = max(close_returns, key=lambda item: item[1])
    _, trough = min(close_returns, key=lambda item: item[1])
    return {
        "holding_trading_days": end - start,
        "mfe": mfe,
        "mae": mae,
        "peak_close_return": peak,
        "trough_close_return": trough,
        "giveback_from_peak": peak - float(trade["round_trip_return"]),
        "days_to_mfe": mfe_day,
        "days_to_mae": mae_day,
        "days_from_peak_to_exit": end - start - peak_day,
        **early,
    }


def quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def distribution(values: Iterable[float]) -> dict[str, Any]:
    finite = [float(value) for value in values if math.isfinite(float(value))]
    if not finite:
        return {
            "count": 0,
            "mean": None,
            "p10": None,
            "p25": None,
            "median": None,
            "p75": None,
            "p90": None,
        }
    return {
        "count": len(finite),
        "mean": statistics.fmean(finite),
        "p10": quantile(finite, 0.10),
        "p25": quantile(finite, 0.25),
        "median": statistics.median(finite),
        "p75": quantile(finite, 0.75),
        "p90": quantile(finite, 0.90),
    }


def pnl_bucket(value: float) -> str:
    if value >= 0.50:
        return "SUPER_WINNER_GE_50"
    if value >= 0.20:
        return "TOP_WINNER_20_TO_50"
    if value > 0.0:
        return "ORDINARY_WINNER_0_TO_20"
    if value > -0.10:
        return "SMALL_LOSS_0_TO_NEG10"
    if value > -0.20:
        return "SEVERE_LOSS_NEG10_TO_NEG20"
    return "EXTREME_LOSS_LE_NEG20"


def group_trade_metrics(trades: list[dict[str, Any]], start_nav: float) -> dict[str, Any]:
    returns = [float(row["round_trip_return"]) for row in trades]
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value <= 0]
    ordered = sorted(
        trades,
        key=lambda row: (-float(row["realized_pnl"]), row["trade_id"]),
    )
    positive_pnl = sum(max(0.0, float(row["realized_pnl"])) for row in trades)
    negative_pnl = sum(min(0.0, float(row["realized_pnl"])) for row in trades)
    buckets: dict[str, dict[str, Any]] = {}
    for name in (
        "SUPER_WINNER_GE_50",
        "TOP_WINNER_20_TO_50",
        "ORDINARY_WINNER_0_TO_20",
        "SMALL_LOSS_0_TO_NEG10",
        "SEVERE_LOSS_NEG10_TO_NEG20",
        "EXTREME_LOSS_LE_NEG20",
    ):
        rows = [row for row in trades if pnl_bucket(float(row["round_trip_return"])) == name]
        buckets[name] = {
            "count": len(rows),
            "rate": len(rows) / len(trades) if trades else None,
            "realized_pnl": sum(float(row["realized_pnl"]) for row in rows),
        }
    top: dict[str, Any] = {}
    for count in (5, 10, 20):
        rows = ordered[:count]
        top[f"top{count}_positive_pnl_share"] = (
            sum(max(0.0, float(row["realized_pnl"])) for row in rows) / positive_pnl
            if positive_pnl > 0
            else None
        )
        top[f"ex_best{count}_pnl_return"] = -sum(
            float(row["realized_pnl"]) for row in rows
        ) / start_nav
    positive_shares = [
        float(row["realized_pnl"]) / positive_pnl
        for row in trades
        if float(row["realized_pnl"]) > 0 and positive_pnl > 0
    ]
    mfe_values = [float(row["mfe"]) for row in trades]
    capture = [
        float(row["round_trip_return"]) / float(row["mfe"])
        for row in trades
        if float(row["mfe"]) > 0
    ]
    return {
        "trade_count": len(trades),
        "win_rate": sum(value > 0 for value in returns) / len(returns) if returns else None,
        "return_distribution": distribution(returns),
        "average_winner": statistics.fmean(winners) if winners else None,
        "average_loser": statistics.fmean(losers) if losers else None,
        "payoff_ratio": (
            statistics.fmean(winners) / abs(statistics.fmean(losers))
            if winners and losers and statistics.fmean(losers) != 0
            else None
        ),
        "profit_factor_pnl": positive_pnl / abs(negative_pnl) if negative_pnl else None,
        "realized_pnl": positive_pnl + negative_pnl,
        "positive_pnl": positive_pnl,
        "negative_pnl": negative_pnl,
        "severe_loss_rate_le_neg10": (
            sum(value <= -0.10 for value in returns) / len(returns) if returns else None
        ),
        "extreme_loss_rate_le_neg20": (
            sum(value <= -0.20 for value in returns) / len(returns) if returns else None
        ),
        "top_winner_rate_ge_20": (
            sum(value >= 0.20 for value in returns) / len(returns) if returns else None
        ),
        "super_winner_rate_ge_50": (
            sum(value >= 0.50 for value in returns) / len(returns) if returns else None
        ),
        "mfe_ge_20_rate": sum(value >= 0.20 for value in mfe_values) / len(mfe_values),
        "mfe_ge_50_rate": sum(value >= 0.50 for value in mfe_values) / len(mfe_values),
        "mfe_distribution": distribution(mfe_values),
        "mae_distribution": distribution(float(row["mae"]) for row in trades),
        "holding_distribution": distribution(
            float(row["holding_trading_days"]) for row in trades
        ),
        "days_to_mfe_distribution": distribution(float(row["days_to_mfe"]) for row in trades),
        "giveback_distribution": distribution(
            float(row["giveback_from_peak"]) for row in trades
        ),
        "mfe_capture_ratio_distribution": distribution(capture),
        "pnl_buckets": buckets,
        "positive_pnl_hhi": sum(value * value for value in positive_shares),
        **top,
    }


def maximum_drawdown(
    nav_rows: list[dict[str, Any]], starting_nav: float
) -> dict[str, Any]:
    peak_value = starting_nav
    peak_date = "BLOCK_OR_YEAR_START"
    worst = 0.0
    worst_peak = peak_date
    worst_trough = str(nav_rows[0]["trade_date"])
    for row in nav_rows:
        value = float(row["nav"])
        day = str(row["trade_date"])
        if value > peak_value:
            peak_value = value
            peak_date = day
        drawdown = value / peak_value - 1.0
        if drawdown < worst:
            worst = drawdown
            worst_peak = peak_date
            worst_trough = day
    return {
        "max_drawdown": worst,
        "peak_date": worst_peak,
        "trough_date": worst_trough,
    }


def annual_nav_metrics(
    nav_rows: list[dict[str, Any]],
    executions: list[dict[str, Any]],
    trades: list[dict[str, Any]],
    year: int,
    starting_nav: float,
) -> dict[str, Any]:
    rows = [row for row in nav_rows if int(str(row["trade_date"])[:4]) == year]
    if not rows:
        raise DecompositionError(f"missing NAV rows for {year}")
    filled = [
        row
        for row in executions
        if row.get("status") == "FILLED"
        and int(str(row["execution_date"])[:4]) == year
    ]
    average_nav = statistics.fmean(float(row["nav"]) for row in rows)
    average_invested_ratio = statistics.fmean(
        float(row["invested_ratio"]) for row in rows
    )
    portfolio_return = float(rows[-1]["nav"]) / starting_nav - 1.0
    filled_notional = sum(float(row["notional"]) for row in filled)
    turnover = filled_notional / average_nav
    dd = maximum_drawdown(rows, starting_nav)
    window_start = "0000-00-00" if dd["peak_date"] == "BLOCK_OR_YEAR_START" else dd["peak_date"]
    drawdown_trades = [
        row
        for row in trades
        if window_start <= row["exit_execution_date"] <= dd["trough_date"]
    ]
    return {
        "sessions": len(rows),
        "start_nav": starting_nav,
        "end_nav": float(rows[-1]["nav"]),
        "portfolio_return": portfolio_return,
        **dd,
        "average_nav": average_nav,
        "average_invested_ratio": average_invested_ratio,
        "portfolio_return_per_average_invested_ratio": (
            portfolio_return / average_invested_ratio
            if average_invested_ratio > 0
            else None
        ),
        "median_invested_ratio": statistics.median(
            float(row["invested_ratio"]) for row in rows
        ),
        "flat_session_fraction": sum(int(row["holdings"]) == 0 for row in rows)
        / len(rows),
        "full_position_fraction": sum(int(row["holdings"]) == 10 for row in rows)
        / len(rows),
        "average_holdings": statistics.fmean(float(row["holdings"]) for row in rows),
        "max_holdings": max(int(row["holdings"]) for row in rows),
        "market_entry_permission_fraction": sum(
            bool(row["market_entry_permission"]) for row in rows
        )
        / len(rows),
        "filled_notional": filled_notional,
        "turnover_total_filled_notional_over_average_nav": turnover,
        "portfolio_return_per_turnover": portfolio_return / turnover if turnover > 0 else None,
        "drawdown_window_exit_trade_count": len(drawdown_trades),
        "drawdown_window_realized_pnl": sum(
            float(row["realized_pnl"]) for row in drawdown_trades
        ),
        "drawdown_window_severe_loss_pnl": sum(
            float(row["realized_pnl"])
            for row in drawdown_trades
            if float(row["round_trip_return"]) <= -0.10
        ),
        "drawdown_attribution_status": (
            "PARTIAL_REALIZED_EXIT_PNL_ONLY; unrealized position marks also drive NAV drawdown"
        ),
    }


def cohort_metrics(trades: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        groups[str(row[field])[:7]].append(row)
    result = []
    for cohort, rows in sorted(groups.items()):
        returns = [float(row["round_trip_return"]) for row in rows]
        result.append(
            {
                "cohort": cohort,
                "trade_count": len(rows),
                "win_rate": sum(value > 0 for value in returns) / len(returns),
                "median_return": statistics.median(returns),
                "mean_return": statistics.fmean(returns),
                "realized_pnl": sum(float(row["realized_pnl"]) for row in rows),
                "top_winner_count_ge_20": sum(value >= 0.20 for value in returns),
                "severe_loss_count_le_neg10": sum(value <= -0.10 for value in returns),
            }
        )
    return result


def exit_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in trades:
        groups[row["canonical_exit_reason"]].append(row)
    output: dict[str, Any] = {}
    for reason, rows in sorted(groups.items()):
        returns = [float(row["round_trip_return"]) for row in rows]
        output[reason] = {
            "trade_count": len(rows),
            "win_rate": sum(value > 0 for value in returns) / len(returns),
            "median_return": statistics.median(returns),
            "mean_return": statistics.fmean(returns),
            "realized_pnl": sum(float(row["realized_pnl"]) for row in rows),
            "median_holding_days": statistics.median(
                float(row["holding_trading_days"]) for row in rows
            ),
            "median_mfe": statistics.median(float(row["mfe"]) for row in rows),
            "median_mae": statistics.median(float(row["mae"]) for row in rows),
        }
    return output


def average_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    position = 0
    while position < len(indexed):
        end = position + 1
        while end < len(indexed) and indexed[end][1] == indexed[position][1]:
            end += 1
        rank = (position + 1 + end) / 2.0
        for original, _ in indexed[position:end]:
            ranks[original] = rank
        position = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    mean_left = statistics.fmean(left)
    mean_right = statistics.fmean(right)
    numerator = sum(
        (a - mean_left) * (b - mean_right) for a, b in zip(left, right, strict=True)
    )
    denominator = math.sqrt(
        sum((value - mean_left) ** 2 for value in left)
        * sum((value - mean_right) ** 2 for value in right)
    )
    return numerator / denominator if denominator else None


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(average_ranks(left), average_ranks(right))


def nested_value(row: dict[str, Any], path: str) -> float:
    value: Any = row
    for part in path.split("."):
        value = value[part]
    return float(value)


def safe_feature(event: dict[str, Any], *parts: str) -> float | None:
    value: Any = event
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def write_trade_csv(trades: list[dict[str, Any]]) -> None:
    fields = [
        "baseline_block",
        "trade_id",
        "symbol",
        "entry_signal_date",
        "entry_execution_date",
        "exit_signal_date",
        "exit_execution_date",
        "canonical_exit_reason",
        "round_trip_return",
        "realized_pnl",
        "capital",
        "holding_trading_days",
        "mfe",
        "mae",
        "days_to_mfe",
        "days_to_mae",
        "giveback_from_peak",
        "return_5d",
        "return_10d",
        "return_20d",
        "entry_rs_score",
        "entry_mom20",
        "entry_mom60",
        "entry_mom120",
        "entry_box_width",
        "entry_vol_ratio",
        "entry_minvol_location",
        "entry_minimum_volume_ratio",
        "entry_breakout_volume_ratio",
        "pnl_bucket",
    ]
    OUTPUT_TRADES_CSV.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT_TRADES_CSV.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for trade in sorted(trades, key=lambda row: (row["exit_execution_date"], row["trade_id"])):
            event = trade["entry_event"]
            writer.writerow(
                {
                    **{field: trade.get(field) for field in fields},
                    "return_5d": trade.get("return_5d"),
                    "return_10d": trade.get("return_10d"),
                    "return_20d": trade.get("return_20d"),
                    "entry_rs_score": safe_feature(event, "rs", "score"),
                    "entry_mom20": safe_feature(event, "rs", "mom20"),
                    "entry_mom60": safe_feature(event, "rs", "mom60"),
                    "entry_mom120": safe_feature(event, "rs", "mom120"),
                    "entry_box_width": safe_feature(event, "full40", "box_width"),
                    "entry_vol_ratio": safe_feature(event, "full40", "vol_ratio"),
                    "entry_minvol_location": safe_feature(event, "minvol", "location"),
                    "entry_minimum_volume_ratio": safe_feature(
                        event, "minvol", "minimum_volume_ratio"
                    ),
                    "entry_breakout_volume_ratio": safe_feature(
                        event, "breakout_volume", "ratio"
                    ),
                    "pnl_bucket": pnl_bucket(float(trade["round_trip_return"])),
                }
            )
    temporary.replace(OUTPUT_TRADES_CSV)


def write_metrics_csv(yearly: dict[str, Any]) -> None:
    fields = [
        "year",
        "baseline_block",
        "portfolio_return",
        "max_drawdown",
        "trade_count",
        "win_rate",
        "mean_trade_return",
        "median_trade_return",
        "top_winner_rate_ge_20",
        "super_winner_rate_ge_50",
        "severe_loss_rate_le_neg10",
        "extreme_loss_rate_le_neg20",
        "median_mfe",
        "median_mae",
        "median_holding_days",
        "average_invested_ratio",
        "return_per_average_invested_ratio",
        "turnover",
        "return_per_turnover",
        "top5_positive_pnl_share",
        "ex_best5_portfolio_return",
    ]
    temporary = OUTPUT_METRICS_CSV.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for year, row in sorted(yearly.items()):
            trade = row["trade_metrics"]
            nav = row["nav_metrics"]
            writer.writerow(
                {
                    "year": year,
                    "baseline_block": row["baseline_block"],
                    "portfolio_return": nav["portfolio_return"],
                    "max_drawdown": nav["max_drawdown"],
                    "trade_count": trade["trade_count"],
                    "win_rate": trade["win_rate"],
                    "mean_trade_return": trade["return_distribution"]["mean"],
                    "median_trade_return": trade["return_distribution"]["median"],
                    "top_winner_rate_ge_20": trade["top_winner_rate_ge_20"],
                    "super_winner_rate_ge_50": trade["super_winner_rate_ge_50"],
                    "severe_loss_rate_le_neg10": trade["severe_loss_rate_le_neg10"],
                    "extreme_loss_rate_le_neg20": trade["extreme_loss_rate_le_neg20"],
                    "median_mfe": trade["mfe_distribution"]["median"],
                    "median_mae": trade["mae_distribution"]["median"],
                    "median_holding_days": trade["holding_distribution"]["median"],
                    "average_invested_ratio": nav["average_invested_ratio"],
                    "return_per_average_invested_ratio": nav[
                        "portfolio_return_per_average_invested_ratio"
                    ],
                    "turnover": nav["turnover_total_filled_notional_over_average_nav"],
                    "return_per_turnover": nav["portfolio_return_per_turnover"],
                    "top5_positive_pnl_share": trade["top5_positive_pnl_share"],
                    "ex_best5_portfolio_return": nav["portfolio_return"]
                    + trade["ex_best5_pnl_return"],
                }
            )
    temporary.replace(OUTPUT_METRICS_CSV)


def pct(value: float | None) -> str:
    return "NA" if value is None else f"{value:.2%}"


def build_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Phase 1 — why CHINEXT V1 years differ",
        "",
        "> Zero-replay decomposition of 399 authoritative completed cycles and 1,942 daily NAV rows. No strategy signal, order, fill, NAV, or parameter was regenerated.",
        "",
        "## Annual decomposition",
        "",
        "| Year | Return | Max DD | Trades | Win | Mean / median trade | >=20% winners | <=-10% losses | Median MFE / MAE | Avg exposure | Top5 +P&L share | Ex-best5 return |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, row in sorted(payload["yearly"].items()):
        trade = row["trade_metrics"]
        nav = row["nav_metrics"]
        lines.append(
            f"| {year} | {pct(nav['portfolio_return'])} | {pct(nav['max_drawdown'])} | "
            f"{trade['trade_count']} | {pct(trade['win_rate'])} | "
            f"{pct(trade['return_distribution']['mean'])} / {pct(trade['return_distribution']['median'])} | "
            f"{pct(trade['top_winner_rate_ge_20'])} | {pct(trade['severe_loss_rate_le_neg10'])} | "
            f"{pct(trade['mfe_distribution']['median'])} / {pct(trade['mae_distribution']['median'])} | "
            f"{pct(nav['average_invested_ratio'])} | {pct(trade['top5_positive_pnl_share'])} | "
            f"{pct(nav['portfolio_return'] + trade['ex_best5_pnl_return'])} |"
        )
    lines += [
        "",
        "## FACT — first differing economics",
        "",
        "- 2022 is the clearest failed year: 13.51% win rate, negative mean and median trade, no >=20% realized winner, and very weak MFE. Low exposure limited activity but did not create positive expectancy.",
        "- 2024 is not a broad high-win-rate year. Its 49.05% portfolio return occurs with only a 31.58% win rate and a negative median trade; six >=50% cycles and a much stronger upper MFE tail create the result.",
        "- 2025 is broader: the win rate and median trade turn positive, exposure is highest, and the Top5 share is materially lower than in 2024.",
        "- 2019 and 2021 combine near-45–49% win rates with super-winners. 2020 has a similar win rate and seven 20–50% winners, but no >=50% winner, the second-highest severe-loss rate, and the only <=-20% loss before 2025; its positive tail is largely offset and drawdown is much larger.",
        "",
        "## EVIDENCE — realized P&L buckets",
        "",
        "| Year | >=50% P&L | 20–50% P&L | 0–20% P&L | 0 to -10% P&L | -10 to -20% P&L | <=-20% P&L |",
        "|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year, row in sorted(payload["yearly"].items()):
        buckets = row["trade_metrics"]["pnl_buckets"]
        lines.append(
            f"| {year} | {buckets['SUPER_WINNER_GE_50']['realized_pnl']:,.0f} | "
            f"{buckets['TOP_WINNER_20_TO_50']['realized_pnl']:,.0f} | "
            f"{buckets['ORDINARY_WINNER_0_TO_20']['realized_pnl']:,.0f} | "
            f"{buckets['SMALL_LOSS_0_TO_NEG10']['realized_pnl']:,.0f} | "
            f"{buckets['SEVERE_LOSS_NEG10_TO_NEG20']['realized_pnl']:,.0f} | "
            f"{buckets['EXTREME_LOSS_LE_NEG20']['realized_pnl']:,.0f} |"
        )
    lines += [
        "",
        "## EVIDENCE — Top-N concentration",
        "",
        "| Year | Top5 / 10 / 20 positive-P&L share | Ex-best5 / 10 / 20 portfolio return |",
        "|---:|---:|---:|",
    ]
    for year, row in sorted(payload["yearly"].items()):
        trade = row["trade_metrics"]
        lines.append(
            f"| {year} | {pct(trade['top5_positive_pnl_share'])} / "
            f"{pct(trade['top10_positive_pnl_share'])} / {pct(trade['top20_positive_pnl_share'])} | "
            f"{pct(trade['ex_best5_portfolio_return'])} / "
            f"{pct(trade['ex_best10_portfolio_return'])} / "
            f"{pct(trade['ex_best20_portfolio_return'])} |"
        )
    lines += [
        "",
        "## EVIDENCE — exposure, turnover, and drawdown window",
        "",
        "| Year | Avg exposure | Return / avg exposure | Turnover | Return / turnover | Max-DD peak -> trough | Realized exit P&L in DD window | Severe-loss P&L in DD window |",
        "|---:|---:|---:|---:|---:|---|---:|---:|",
    ]
    for year, row in sorted(payload["yearly"].items()):
        nav = row["nav_metrics"]
        lines.append(
            f"| {year} | {pct(nav['average_invested_ratio'])} | "
            f"{nav['portfolio_return_per_average_invested_ratio']:.3f} | "
            f"{nav['turnover_total_filled_notional_over_average_nav']:.2f}x | "
            f"{nav['portfolio_return_per_turnover']:.3f} | "
            f"{nav['peak_date']} -> {nav['trough_date']} | "
            f"{nav['drawdown_window_realized_pnl']:,.0f} | "
            f"{nav['drawdown_window_severe_loss_pnl']:,.0f} |"
        )
    lines += [
        "",
        "## EVIDENCE — exit and holding mechanism",
        "",
        "| Exit lineage | Trades | Win rate | Median return | Realized P&L | Median hold | Median MFE / MAE |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for reason, metrics in payload["overall_exit_lineage"].items():
        lines.append(
            f"| {reason} | {metrics['trade_count']} | {pct(metrics['win_rate'])} | "
            f"{pct(metrics['median_return'])} | {metrics['realized_pnl']:,.0f} | "
            f"{metrics['median_holding_days']:.1f} | "
            f"{pct(metrics['median_mfe'])} / {pct(metrics['median_mae'])} |"
        )
    best_entry = sorted(
        payload["overall_entry_month_cohorts"],
        key=lambda row: (-float(row["realized_pnl"]), row["cohort"]),
    )[:5]
    worst_entry = sorted(
        payload["overall_entry_month_cohorts"],
        key=lambda row: (float(row["realized_pnl"]), row["cohort"]),
    )[:5]
    lines += [
        "",
        "Entry-month cohorts are diagnostic, not regimes. The five strongest and weakest realized-P&L cohorts were:",
        "",
        "| Side | Entry month | Trades | Win rate | >=20% winners | <=-10% losses | Realized P&L |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for side, cohorts in (("BEST", best_entry), ("WORST", worst_entry)):
        for cohort in cohorts:
            lines.append(
                f"| {side} | {cohort['cohort']} | {cohort['trade_count']} | "
                f"{pct(cohort['win_rate'])} | {cohort['top_winner_count_ge_20']} | "
                f"{cohort['severe_loss_count_le_neg10']} | {cohort['realized_pnl']:,.0f} |"
            )
    lines += [
        "",
        "The machine artifact retains the complete annual exit tables, MFE/MAE, time-to-MFE, holding duration, giveback, and all entry/exit month cohorts. Individual/set-removal exits are descriptive lineage, not proof that the exit caused the loss.",
        "",
        "Across-year rank correlations with annual portfolio return are descriptive only (n=8):",
        "",
        "| Diagnostic | Spearman rho |",
        "|---|---:|",
    ]
    for item in sorted(
        payload["cross_year_associations"],
        key=lambda row: (-abs(float(row["spearman_rho"])), row["diagnostic"]),
    ):
        lines.append(f"| {item['diagnostic']} | {item['spearman_rho']:.3f} |")
    lines += [
        "",
        "## INTERPRETATION",
        "",
        "H-001 is supported at the yearly-decomposition level: changes in right-tail frequency/magnitude and favorable excursion explain more of the return ordering than the median trade alone. H-002 is also supported but qualified: bad years are not simply severe-loss years. The more fundamental failure is that ordinary losses are not offset by enough winners, while early/total favorable excursion is scarce.",
        "",
        "Regime causality is not established here. Exposure is a transmission channel, not a sufficient explanation: 2018 had little exposure and a small loss; 2022 had low exposure and a large loss; 2024 generated a large gain with moderate exposure. Phase 2 must therefore measure the market opportunity state present at entry rather than infer it from annual labels.",
        "",
        "## Important boundaries",
        "",
        "- Calendar-year trade P&L is assigned by exit execution year. Entry-month cohorts are separate.",
        "- Ex-best-N subtracts frozen realized completed-cycle P&L from the annual return denominator; it is a static concentration diagnostic, not a counterfactual NAV replay.",
        "- When a year has fewer than N positive cycles, Top-N positive-P&L share saturates at 100%, while ex-best-N still removes the N highest-P&L cycles, including later-ranked losses. This makes some annual ex-best-N sequences non-monotone by construction.",
        "- Maximum-drawdown trade attribution includes only cycles realized between the peak and trough. Unrealized marks also drive NAV drawdown, so that field is explicitly partial.",
        "- MFE/MAE is the first-entry-open gross underlying total-return path, corporate-action adjusted, with the actual exit open as the only exit-session observation. Later rebalance cash flows do not redefine it.",
        "- All three NAV blocks remain independent bounded PIT-B evaluations; no eight-year compounded NAV is claimed.",
        "",
        "## Phase 1 verdict",
        "",
        "**SUPPORTED:** right-tail availability and path persistence are the primary first-order differentiators. **SUPPORTED WITH QUALIFICATION:** win rate and ordinary-trade quality matter, particularly in 2022, but severe-loss frequency alone does not explain bad years. **UNRESOLVED:** which causal market states create or suppress those paths; this moves to the PIT feature audit.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    baseline, ledger_hashes = validate_inputs()
    sessions = load_sessions()
    session_index = {day: index for index, day in enumerate(sessions)}
    all_trades: list[dict[str, Any]] = []
    block_data: dict[str, dict[str, Any]] = {}
    for block, directory in BLOCKS.items():
        executions = read_jsonl(directory / "execution_ledger.jsonl")
        events = read_jsonl(directory / "event_ledger.jsonl")
        nav = read_jsonl(directory / "daily_nav.jsonl")
        trades = build_cycles(executions, block)
        enrich_event_lineage(trades, events)
        all_trades.extend(trades)
        block_data[block] = {"executions": executions, "events": events, "nav": nav, "trades": trades}
    if len(all_trades) != 399:
        raise DecompositionError(f"expected 399 completed cycles, found {len(all_trades)}")
    price_rows = load_trade_price_rows({row["symbol"] for row in all_trades})
    for trade in all_trades:
        trade.update(holding_features(trade, sessions, session_index, price_rows))

    yearly: dict[str, Any] = {}
    for block, data in block_data.items():
        nav = data["nav"]
        years = sorted({int(str(row["trade_date"])[:4]) for row in nav})
        starting_nav = INITIAL_CASH
        for year in years:
            trades = [
                row
                for row in data["trades"]
                if int(row["exit_execution_date"][:4]) == year
            ]
            nav_metrics = annual_nav_metrics(
                nav, data["executions"], data["trades"], year, starting_nav
            )
            trade_metrics = group_trade_metrics(trades, starting_nav)
            trade_metrics["ex_best5_portfolio_return"] = (
                nav_metrics["portfolio_return"] + trade_metrics["ex_best5_pnl_return"]
            )
            trade_metrics["ex_best10_portfolio_return"] = (
                nav_metrics["portfolio_return"] + trade_metrics["ex_best10_pnl_return"]
            )
            trade_metrics["ex_best20_portfolio_return"] = (
                nav_metrics["portfolio_return"] + trade_metrics["ex_best20_pnl_return"]
            )
            yearly[str(year)] = {
                "baseline_block": block,
                "nav_metrics": nav_metrics,
                "trade_metrics": trade_metrics,
                "exit_lineage": exit_metrics(trades),
                "entry_month_cohorts": cohort_metrics(trades, "entry_signal_date"),
                "exit_month_cohorts": cohort_metrics(trades, "exit_execution_date"),
            }
            if not math.isclose(
                nav_metrics["portfolio_return"],
                EXPECTED_YEAR_RETURN[year],
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise DecompositionError(f"annual return mismatch: {year}")
            if trade_metrics["trade_count"] != EXPECTED_YEAR_TRADES[year]:
                raise DecompositionError(f"annual trade count mismatch: {year}")
            starting_nav = nav_metrics["end_nav"]

    diagnostics = {
        "win_rate": "trade_metrics.win_rate",
        "mean_trade_return": "trade_metrics.return_distribution.mean",
        "median_trade_return": "trade_metrics.return_distribution.median",
        "top_winner_rate_ge_20": "trade_metrics.top_winner_rate_ge_20",
        "super_winner_rate_ge_50": "trade_metrics.super_winner_rate_ge_50",
        "severe_loss_rate_le_neg10": "trade_metrics.severe_loss_rate_le_neg10",
        "median_mfe": "trade_metrics.mfe_distribution.median",
        "median_mae": "trade_metrics.mae_distribution.median",
        "median_holding_days": "trade_metrics.holding_distribution.median",
        "average_invested_ratio": "nav_metrics.average_invested_ratio",
    }
    ordered_years = [str(year) for year in range(2018, 2026)]
    annual_returns = [nested_value(yearly[year], "nav_metrics.portfolio_return") for year in ordered_years]
    associations = []
    for diagnostic, path in diagnostics.items():
        values = [nested_value(yearly[year], path) for year in ordered_years]
        rho = spearman(annual_returns, values)
        associations.append(
            {
                "diagnostic": diagnostic,
                "spearman_rho": rho,
                "sample_years": 8,
                "status": "DESCRIPTIVE_NO_CAUSAL_OR_P_VALUE_CLAIM",
            }
        )

    write_trade_csv(all_trades)
    write_metrics_csv(yearly)
    payload = {
        "artifact_id": "CHINEXT-V1-PHASE1-YEARLY-DECOMPOSITION-2018-2025-V1",
        "experiment_id": "EXP-P1-001",
        "result": "PASS",
        "formal_replay_executions": 0,
        "new_strategy_trades": 0,
        "new_nav": 0,
        "strategy_modified": False,
        "pit_rebuilt": False,
        "input_identity": {
            "strategy_sha256": EXPECTED_STRATEGY,
            "cy006_manifest_sha256": EXPECTED_CY006_MANIFEST,
            "calendar_sha256": EXPECTED_CALENDAR,
            "baseline_manifest_sha256": sha256_file(BASELINE_MANIFEST),
            "ledger_hashes": ledger_hashes,
        },
        "definitions": {
            "trade_year": "exit_execution_year",
            "severe_loss": "round_trip_return <= -0.10",
            "extreme_loss": "round_trip_return <= -0.20",
            "top_winner": "round_trip_return >= +0.20",
            "super_winner": "round_trip_return >= +0.50",
            "turnover": "annual filled notional / annual average authoritative NAV",
            "ex_best_n": "annual frozen return minus top-N completed-cycle realized P&L / annual starting NAV",
            "holding_path": "first-entry-open gross total-return path; corporate-action adjusted; exit session uses actual exit open only",
        },
        "sample": {
            "completed_cycles": len(all_trades),
            "daily_nav_rows": sum(len(data["nav"]) for data in block_data.values()),
            "years": [2018, 2019, 2020, 2021, 2022, 2023, 2024, 2025],
            "nav_blocks": list(BLOCKS),
            "nav_blocks_are_independent": True,
        },
        "yearly": yearly,
        "cross_year_associations": associations,
        "overall_exit_lineage": exit_metrics(all_trades),
        "overall_entry_month_cohorts": cohort_metrics(all_trades, "entry_signal_date"),
        "overall_exit_month_cohorts": cohort_metrics(all_trades, "exit_execution_date"),
        "outputs": {
            "trades_csv": str(OUTPUT_TRADES_CSV),
            "trades_csv_sha256": sha256_file(OUTPUT_TRADES_CSV),
            "metrics_csv": str(OUTPUT_METRICS_CSV),
            "metrics_csv_sha256": sha256_file(OUTPUT_METRICS_CSV),
        },
        "findings": {
            "H-001": "SUPPORTED_AT_YEARLY_DECOMPOSITION_LEVEL",
            "H-002": "SUPPORTED_WITH_QUALIFICATION",
            "market_regime_causality": "UNRESOLVED_PENDING_PHASE2_AND_PHASE3",
        },
    }
    atomic_write(OUTPUT_JSON, json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n")
    atomic_write(REPORT, build_report(payload))
    print(
        json.dumps(
            {
                "result": "PASS",
                "trades": len(all_trades),
                "years": len(yearly),
                "json": str(OUTPUT_JSON),
                "report": str(REPORT),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
