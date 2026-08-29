#!/usr/bin/env python3
"""Offline failure decomposition for the frozen V1 2018-2021 first view."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "research/chinext_v1/scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_chinext_v1_extended_replay as extended  # noqa: E402
from run_chinext_v1_full_survivor import INITIAL_CASH, read_jsonl  # noqa: E402
from run_chinext_v1_pit_replay import reconstruct_round_trips  # noqa: E402

REPORTS = ROOT / "research/chinext_v1/reports"
SUMMARY = REPORTS / "chinext_v1_extended_replay_summary.json"
ARTIFACT_MANIFEST = REPORTS / "chinext_v1_extended_replay_artifact_manifest.json"
RESULT = REPORTS / "chinext_v1_extended_failure_decomposition.json"
REPORT = REPORTS / "chinext_v1_extended_failure_decomposition.md"


class FailureDecompositionError(RuntimeError):
    """Raised when frozen first-view evidence cannot be reconstructed exactly."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(values: Iterable[float | int | None]) -> list[float]:
    return [float(value) for value in values if value is not None and math.isfinite(float(value))]


def quantiles(values: Iterable[float | int | None]) -> dict[str, float | int | None]:
    ordered = sorted(finite(values))
    if not ordered:
        return {key: None for key in ("count", "mean", "p10", "p25", "median", "p75", "p90")}

    def nearest(fraction: float) -> float:
        return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]

    return {
        "count": len(ordered),
        "mean": statistics.fmean(ordered),
        "p10": nearest(0.10),
        "p25": nearest(0.25),
        "median": statistics.median(ordered),
        "p75": nearest(0.75),
        "p90": nearest(0.90),
    }


def group_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    returns = finite(row["round_trip_return"] for row in rows)
    pnl = finite(row["realized_pnl"] for row in rows)
    winners = [value for value in returns if value > 0]
    losers = [value for value in returns if value <= 0]
    return {
        "count": len(rows),
        "win_rate": (len(winners) / len(returns) if returns else None),
        "return_distribution": quantiles(returns),
        "winner_distribution": quantiles(winners),
        "loser_distribution": quantiles(losers),
        "realized_pnl": sum(pnl),
        "mfe_distribution": quantiles(row["mfe"] for row in rows),
        "mae_distribution": quantiles(row["mae"] for row in rows),
        "holding_session_distribution": quantiles(row["holding_sessions"] for row in rows),
    }


def feature_value(event: dict[str, Any], path: str) -> float | bool | None:
    value: Any = event
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    if isinstance(value, bool):
        return value
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def feature_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    features = (
        "rs.score",
        "rs.r20",
        "rs.r60",
        "rs.r120",
        "rs.mom20",
        "rs.mom60",
        "rs.mom120",
        "full40.box_width",
        "full40.ma_dispersion",
        "full40.direction_efficiency",
        "full40.vol_ratio",
        "minvol.location",
        "minvol.minimum_volume_ratio",
        "breakout_volume.ratio",
    )
    return {
        feature: quantiles(feature_value(row["entry_event"], feature) for row in rows)
        for feature in features
    }


def verify_frozen_artifacts() -> tuple[dict[str, Any], dict[str, Any]]:
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    manifest = json.loads(ARTIFACT_MANIFEST.read_text(encoding="utf-8"))
    formal = summary["formal_replay"]
    if formal["execution_count"] != 1 or formal["sample_status_after_run"] != (
        "CONSUMED_PREREGISTERED_EXTENDED_HISTORY_VALIDATION"
    ):
        raise FailureDecompositionError("V1 first-view sample status is not frozen and consumed")
    for name, item in manifest["files"].items():
        path = Path(item["path"])
        if not path.is_file() or sha256_file(path) != item["sha256"]:
            raise FailureDecompositionError(f"frozen artifact hash mismatch: {name}")
    return summary, manifest


def canonical_exit_reason(
    trade: dict[str, Any],
    individual: set[tuple[str, str]],
    removals: set[tuple[str, str]],
) -> str:
    symbol = str(trade["symbol"])
    signal_date = str(trade["exit_signal_date"])
    raw = str(trade["exit_reason"])
    if raw == "MARKET_MA20_X2":
        return "MARKET_MA20_X2"
    if raw == "MARKET_CLOSE_LT_MA20_X0.96":
        return "MARKET_EMERGENCY_X0.96"
    has_individual = (symbol, signal_date) in individual
    has_removal = (symbol, signal_date) in removals
    if has_individual and has_removal:
        return "INDIVIDUAL_MA30_X2_AND_SET_REMOVAL"
    if has_individual:
        return "INDIVIDUAL_MA30_X2"
    if has_removal:
        return "SET_REMOVAL"
    return "UNRESOLVED_FAIL_CLOSED"


def load_trade_paths(
    prepared_root: Path,
    trades: list[dict[str, Any]],
    cycle_legs: dict[str, list[dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    paths = [
        str(prepared_root / f"partition_year={year}" / "data_0.parquet")
        for year in range(2018, 2022)
    ]
    symbols = sorted({str(row["symbol"]) for row in trades})
    connection = duckdb.connect()
    raw_rows = connection.execute(
        """
        SELECT CAST(trade_date AS DATE),symbol,high,low,close,
               corporate_action_count,corporate_action_blocking,
               corporate_action_valid,share_multiplier,cash_per_share
        FROM read_parquet(?,union_by_name=true)
        WHERE trade_date BETWEEN DATE '2018-01-02' AND DATE '2021-12-31'
          AND symbol IN (SELECT * FROM unnest(?))
        ORDER BY symbol,trade_date
        """,
        [paths, symbols],
    ).fetchall()
    connection.close()
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for day, symbol, high, low, close, action_count, blocking, valid, multiplier, cash in raw_rows:
        if all(value is not None and math.isfinite(float(value)) for value in (high, low, close)):
            by_symbol[str(symbol)].append(
                {
                    "date": day,
                    "high": float(high),
                    "low": float(low),
                    "close": float(close),
                    "action_count": int(action_count or 0),
                    "action_blocking": blocking,
                    "action_valid": valid,
                    "share_multiplier": float(multiplier or 1.0),
                    "cash_per_share": float(cash or 0.0),
                }
            )
    output: dict[str, list[dict[str, Any]]] = {}
    for trade in trades:
        trade_id = str(trade["trade_id"])
        start = date.fromisoformat(str(trade["entry_execution_date"]))
        signal_end = date.fromisoformat(str(trade["exit_signal_date"]))
        execution_end = date.fromisoformat(str(trade["exit_execution_date"]))
        rows = [
            row
            for row in by_symbol[str(trade["symbol"])]
            if start <= row["date"] <= execution_end
        ]
        legs_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)
        for leg in cycle_legs[trade_id]:
            legs_by_date[date.fromisoformat(str(leg["execution_date"]))].append(leg)
        shares = 0.0
        cumulative_buy_cost = 0.0
        cumulative_sell_proceeds = 0.0
        cumulative_dividends = 0.0
        path: list[dict[str, Any]] = []
        reconciled_return: float | None = None
        for row in rows:
            day = row["date"]
            if row["action_count"]:
                if row["action_blocking"] is not False or row["action_valid"] is not True:
                    raise FailureDecompositionError(
                        f"blocking corporate action reached held cycle: {trade_id} {day}"
                    )
                cumulative_dividends += shares * row["cash_per_share"]
                shares = round(shares * row["share_multiplier"])
            for leg in legs_by_date.get(day, []):
                if leg["side"] == "BUY":
                    shares += float(leg["shares"])
                    cumulative_buy_cost += float(leg["notional"]) + float(leg["cost"])
                else:
                    shares -= float(leg["shares"])
                    cumulative_sell_proceeds += float(leg["notional"]) - float(leg["cost"])
            if cumulative_buy_cost <= 0:
                continue
            base = cumulative_sell_proceeds + cumulative_dividends - cumulative_buy_cost
            if day <= signal_end:
                path.append(
                    {
                        "date": day.isoformat(),
                        "holding_session": len(path) + 1,
                        "close_return": (base + shares * row["close"]) / cumulative_buy_cost,
                        "high_return": (base + shares * row["high"]) / cumulative_buy_cost,
                        "low_return": (base + shares * row["low"]) / cumulative_buy_cost,
                    }
                )
            if day == execution_end:
                if abs(shares) > 1e-9:
                    raise FailureDecompositionError(f"cycle did not close: {trade_id}")
                reconciled_return = base / cumulative_buy_cost
        if reconciled_return is None or not math.isclose(
            reconciled_return, float(trade["round_trip_return"]), rel_tol=0.0, abs_tol=1e-12
        ):
            raise FailureDecompositionError(
                f"cycle return reconciliation mismatch: {trade_id}: "
                f"{reconciled_return} != {trade['round_trip_return']}"
            )
        output[trade_id] = path
    return output


def build_cycle_legs(executions: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    counters: Counter[str] = Counter()
    active: dict[str, str] = {}
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in executions:
        if row.get("status") != "FILLED":
            continue
        symbol = str(row["symbol"])
        if row["side"] == "BUY" and row.get("new_position") is True:
            counters[symbol] += 1
            active[symbol] = f"{symbol}-{counters[symbol]:03d}"
        if symbol not in active:
            raise FailureDecompositionError(f"filled leg outside active cycle: {symbol}")
        output[active[symbol]].append(row)
        if row["side"] == "SELL" and row.get("completed_round_trip") is True:
            active.pop(symbol)
    if active:
        raise FailureDecompositionError(f"unexpected unclosed cycles: {sorted(active)}")
    return dict(output)


def path_point_summary(rows: list[dict[str, Any]], sessions: int) -> dict[str, Any]:
    values = [
        row["path"][sessions - 1]["close_return"]
        for row in rows
        if len(row["path"]) >= sessions
    ]
    return quantiles(values)


def max_loss_streak(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (row["exit_execution_date"], row["trade_id"]))
    current: list[str] = []
    longest: list[str] = []
    for row in ordered:
        if float(row["round_trip_return"]) <= 0:
            current.append(row["trade_id"])
            if len(current) > len(longest):
                longest = list(current)
        else:
            current = []
    return {"count": len(longest), "trade_ids": longest}


def main() -> int:
    summary, manifest = verify_frozen_artifacts()
    executions = read_jsonl(Path(manifest["files"]["execution_ledger"]["path"]))
    events = read_jsonl(Path(manifest["files"]["event_ledger"]["path"]))
    nav = read_jsonl(Path(manifest["files"]["daily_nav"]["path"]))
    trips = reconstruct_round_trips(executions)
    cycle_legs = build_cycle_legs(executions)
    if len(trips) != 194:
        raise FailureDecompositionError(f"expected 194 frozen trips, found {len(trips)}")

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
    enriched: list[dict[str, Any]] = []
    symbol_counts: Counter[str] = Counter()
    for trip in trips:
        symbol = str(trip["symbol"])
        symbol_counts[symbol] += 1
        trade_id = f"{symbol}-{symbol_counts[symbol]:03d}"
        entry_key = (symbol, str(trip["entry_signal_date"]))
        if entry_key not in entry_events:
            raise FailureDecompositionError(f"entry event missing for {entry_key}")
        enriched.append(
            {
                **trip,
                "trade_id": trade_id,
                "entry_event": entry_events[entry_key],
                "canonical_exit_reason": canonical_exit_reason(trip, individual, removals),
            }
        )

    with tempfile.TemporaryDirectory(prefix="chinext-v1-failure-input-") as temporary:
        prepared_root = Path(temporary)
        prepared = extended.materialize_transient_inputs(prepared_root)
        paths = load_trade_paths(prepared_root, enriched, cycle_legs)
    if prepared["canonical_sha256"] != summary["formal_replay"]["input_manifest"][
        "canonical_sha256"
    ]:
        raise FailureDecompositionError("reconstructed input differs from frozen formal replay")

    for row in enriched:
        path = paths[row["trade_id"]]
        if not path:
            raise FailureDecompositionError(f"empty holding path: {row['trade_id']}")
        row["path"] = path
        row["holding_sessions"] = len(path)
        row["mfe"] = max(point["high_return"] for point in path)
        row["mae"] = min(point["low_return"] for point in path)
        row["mfe_session"] = max(path, key=lambda point: point["high_return"])[
            "holding_session"
        ]
        row["mae_session"] = min(path, key=lambda point: point["low_return"])[
            "holding_session"
        ]
        row["giveback_from_mfe"] = row["mfe"] - float(row["round_trip_return"])
        row["year"] = str(row["exit_execution_date"])[:4]

    top = sorted(enriched, key=lambda row: (-float(row["realized_pnl"]), row["trade_id"]))
    top20_ids = {row["trade_id"] for row in top[:20]}
    winners = [row for row in enriched if float(row["round_trip_return"]) > 0]
    losers = [row for row in enriched if float(row["round_trip_return"]) <= 0]
    top20 = [row for row in enriched if row["trade_id"] in top20_ids]
    remaining = [row for row in enriched if row["trade_id"] not in top20_ids]

    positive_pnl = sum(max(0.0, float(row["realized_pnl"])) for row in enriched)
    concentration = {}
    for count in (1, 5, 10, 20):
        removed_pnl = sum(float(row["realized_pnl"]) for row in top[:count])
        concentration[f"top{count}_positive_pnl_concentration"] = (
            sum(max(0.0, float(row["realized_pnl"])) for row in top[:count]) / positive_pnl
        )
        concentration[f"return_ex_best{count}"] = (
            float(summary["portfolio"]["total_return"]) - removed_pnl / INITIAL_CASH
        )

    year_groups = {
        year: [row for row in enriched if row["year"] == year]
        for year in ("2018", "2019", "2020", "2021")
    }
    exit_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        exit_groups[row["canonical_exit_reason"]].append(row)

    month_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in enriched:
        month_groups[str(row["exit_execution_date"])[:7]].append(row)
    month_metrics = [
        {
            "month": month,
            **group_metrics(rows),
        }
        for month, rows in sorted(month_groups.items())
    ]

    nav_by_year: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in nav:
        nav_by_year[str(row["trade_date"])[:4]].append(row)
    exposure = {}
    for year, rows in sorted(nav_by_year.items()):
        exposure[year] = {
            "sessions": len(rows),
            "average_invested_ratio": statistics.fmean(
                float(row["invested_ratio"]) for row in rows
            ),
            "median_invested_ratio": statistics.median(
                float(row["invested_ratio"]) for row in rows
            ),
            "average_holdings": statistics.fmean(float(row["holdings"]) for row in rows),
            "median_holdings": statistics.median(float(row["holdings"]) for row in rows),
            "max_holdings": max(int(row["holdings"]) for row in rows),
            "flat_session_fraction": sum(int(row["holdings"]) == 0 for row in rows) / len(rows),
            "full_10_position_fraction": sum(int(row["holdings"]) == 10 for row in rows)
            / len(rows),
            "market_entry_permission_fraction": sum(
                bool(row["market_entry_permission"]) for row in rows
            )
            / len(rows),
        }

    breakout_groups = {
        "SHADOW_PASS": [
            row
            for row in enriched
            if feature_value(row["entry_event"], "breakout_volume.passed") is True
        ],
        "SHADOW_FAIL": [
            row
            for row in enriched
            if feature_value(row["entry_event"], "breakout_volume.passed") is False
        ],
    }
    rs_scores = sorted(
        finite(feature_value(row["entry_event"], "rs.score") for row in enriched)
    )
    q1 = rs_scores[max(0, math.ceil(0.25 * len(rs_scores)) - 1)]
    q3 = rs_scores[max(0, math.ceil(0.75 * len(rs_scores)) - 1)]
    rs_groups = {
        "BOTTOM_QUARTILE": [
            row
            for row in enriched
            if float(feature_value(row["entry_event"], "rs.score") or 0.0) <= q1
        ],
        "MIDDLE_HALF": [
            row
            for row in enriched
            if q1 < float(feature_value(row["entry_event"], "rs.score") or 0.0) < q3
        ],
        "TOP_QUARTILE": [
            row
            for row in enriched
            if float(feature_value(row["entry_event"], "rs.score") or 0.0) >= q3
        ],
    }

    loss_bands = {
        "LE_NEGATIVE_10_PCT": [row for row in enriched if float(row["round_trip_return"]) <= -0.10],
        "NEGATIVE_10_TO_5_PCT": [
            row for row in enriched if -0.10 < float(row["round_trip_return"]) <= -0.05
        ],
        "NEGATIVE_5_TO_0_PCT": [
            row for row in enriched if -0.05 < float(row["round_trip_return"]) <= 0
        ],
        "POSITIVE_0_TO_20_PCT": [
            row for row in enriched if 0 < float(row["round_trip_return"]) < 0.20
        ],
        "GE_POSITIVE_20_PCT": [row for row in enriched if float(row["round_trip_return"]) >= 0.20],
    }

    decomposition: dict[str, Any] = {
        "artifact_id": "CHINEXT-V1-EXTENDED-FAILURE-DECOMPOSITION-2018-2021-V1",
        "authorization": {
            "formal_replay_executions": 0,
            "new_nav": 0,
            "new_trades": 0,
            "pit_rebuilt": "TRANSIENT_INPUT_RECONSTRUCTION_ONLY",
            "sample_status": "IN_SAMPLE_MECHANISM_RESEARCH_AFTER_FROZEN_V1_FIRST_VIEW",
            "strategy_modified": "NO",
            "used_2022_2025_for_v2_selection": "NO",
        },
        "frozen_bindings": {
            "artifact_manifest_sha256": sha256_file(ARTIFACT_MANIFEST),
            "canonical_input_sha256": prepared["canonical_sha256"],
            "event_ledger_sha256": manifest["files"]["event_ledger"]["sha256"],
            "execution_ledger_sha256": manifest["files"]["execution_ledger"]["sha256"],
            "nav_sha256": manifest["files"]["daily_nav"]["sha256"],
            "strategy_sha256": summary["formal_replay"]["strategy_sha256"],
            "summary_sha256": sha256_file(SUMMARY),
        },
        "v1_extended_history_generalization": {
            "label": "MIXED",
            "evidence": [
                "positive 64.8224% four-year aggregate and 3/4 positive calendar years",
                "2018 negative; 2020 weak relative to its drawdown; annual contribution uneven",
                "median trade remains negative despite positive mean",
                "return excluding the best 20 completed cycles is -50.1573%",
            ],
        },
        "overall": group_metrics(enriched),
        "annual": {
            year: {
                "portfolio_return": summary["year_by_year"][year]["return"],
                "portfolio_max_drawdown": summary["year_by_year"][year]["max_drawdown"],
                **group_metrics(rows),
            }
            for year, rows in year_groups.items()
        },
        "return_distribution": {
            "bands": {name: group_metrics(rows) for name, rows in loss_bands.items()},
            "positive_pnl": positive_pnl,
            "negative_pnl": sum(min(0.0, float(row["realized_pnl"])) for row in enriched),
        },
        "right_tail": {
            **concentration,
            "top20": [
                {
                    "trade_id": row["trade_id"],
                    "symbol": row["symbol"],
                    "entry_signal_date": row["entry_signal_date"],
                    "exit_execution_date": row["exit_execution_date"],
                    "year": row["year"],
                    "return": row["round_trip_return"],
                    "realized_pnl": row["realized_pnl"],
                    "mfe": row["mfe"],
                    "mae": row["mae"],
                    "holding_sessions": row["holding_sessions"],
                    "exit_reason": row["canonical_exit_reason"],
                }
                for row in top[:20]
            ],
            "top20_metrics": group_metrics(top20),
            "remaining_metrics": group_metrics(remaining),
        },
        "holding_path": {
            "return_method": (
                "cycle cash-on-cash mark including filled rebalance legs, transaction costs, "
                "dividends, and split-adjusted shares; every final cycle return reconciled "
                "exactly to the frozen execution ledger"
            ),
            "all": group_metrics(enriched),
            "winners": group_metrics(winners),
            "losers": group_metrics(losers),
            "top20": group_metrics(top20),
            "entry_to_close_return": {
                group: {
                    str(sessions): path_point_summary(rows, sessions)
                    for sessions in (1, 3, 5, 10, 20)
                }
                for group, rows in (
                    ("all", enriched),
                    ("winners", winners),
                    ("losers", losers),
                    ("top20", top20),
                )
            },
            "mfe_session_distribution": quantiles(row["mfe_session"] for row in enriched),
            "mae_session_distribution": quantiles(row["mae_session"] for row in enriched),
            "giveback_from_mfe_distribution": quantiles(
                row["giveback_from_mfe"] for row in enriched
            ),
        },
        "exit_interactions": {
            reason: group_metrics(rows) for reason, rows in sorted(exit_groups.items())
        },
        "loss_clustering": {
            "maximum_consecutive_nonpositive_trades": max_loss_streak(enriched),
            "worst_exit_months_by_realized_pnl": sorted(
                month_metrics, key=lambda row: (row["realized_pnl"], row["month"])
            )[:10],
            "best_exit_months_by_realized_pnl": sorted(
                month_metrics, key=lambda row: (-row["realized_pnl"], row["month"])
            )[:10],
        },
        "exposure": exposure,
        "security_selection": {
            "entry_feature_distributions": {
                "all": feature_summary(enriched),
                "winners": feature_summary(winners),
                "losers": feature_summary(losers),
                "top20": feature_summary(top20),
                "remaining": feature_summary(remaining),
            },
            "breakout_volume_shadow_interaction": {
                name: group_metrics(rows) for name, rows in breakout_groups.items()
            },
            "rs_score_quartile_interaction": {
                "boundaries": {"q1": q1, "q3": q3},
                "groups": {name: group_metrics(rows) for name, rows in rs_groups.items()},
            },
        },
        "primary_observations": [],
    }
    decomposition["primary_observations"] = [
        {
            "id": "OBS-001",
            "finding": "V1 retains a negative median trade while mean return is positive",
            "evidence": {
                "median": summary["portfolio"]["median_trade_return"],
                "mean": summary["portfolio"]["average_trade_return"],
            },
        },
        {
            "id": "OBS-002",
            "finding": "The aggregate result remains dependent on a small right tail",
            "evidence": {
                "top20_concentration": concentration["top20_positive_pnl_concentration"],
                "return_ex_best20": concentration["return_ex_best20"],
            },
        },
        {
            "id": "OBS-003",
            "finding": "Year-level behavior is non-uniform despite three positive years",
            "evidence": {
                year: summary["year_by_year"][year]["return"] for year in year_groups
            },
        },
    ]
    extended.gate_c.atomic_write(RESULT, extended.canonical_bytes(decomposition))

    exit_lines = [
        f"| {reason} | {metrics['count']} | {metrics['win_rate']:.2%} | "
        f"{metrics['return_distribution']['median']:.2%} | {metrics['realized_pnl']:,.2f} |"
        for reason, metrics in decomposition["exit_interactions"].items()
    ]
    year_lines = [
        f"| {year} | {metrics['count']} | {metrics['portfolio_return']:.2%} | "
        f"{metrics['win_rate']:.2%} | {metrics['return_distribution']['median']:.2%} | "
        f"{metrics['return_distribution']['mean']:.2%} |"
        for year, metrics in decomposition["annual"].items()
    ]
    lines = [
        "# ChinNext V1 — 2018–2021 frozen first-view failure decomposition",
        "",
        "> Offline only: no replay, new trade, NAV, strategy change, or 2022–2025 performance use.",
        "",
        "- V1_EXTENDED_HISTORY_GENERALIZATION: `MIXED`",
        "- 2018_2021_STATUS: `IN_SAMPLE_MECHANISM_RESEARCH_AFTER_FROZEN_V1_FIRST_VIEW`",
        "- 2022_2025_USED_FOR_V2_SELECTION: `NO`",
        "- FORMAL_REPLAY_EXECUTIONS: `0`",
        "",
        "## Annual pattern",
        "",
        "| Year | Trades | Portfolio return | Win rate | Median trade | Mean trade |",
        "|---:|---:|---:|---:|---:|---:|",
        *year_lines,
        "",
        "## Structural result",
        "",
        f"- TOTAL_RETURN: `{summary['portfolio']['total_return']:.4%}`",
        f"- MAX_DRAWDOWN: `{summary['portfolio']['max_drawdown']:.4%}`",
        f"- MEDIAN_TRADE: `{summary['portfolio']['median_trade_return']:.4%}`",
        f"- MEAN_TRADE: `{summary['portfolio']['average_trade_return']:.4%}`",
        f"- TOP20_PNL_CONCENTRATION: `{concentration['top20_positive_pnl_concentration']:.4%}`",
        f"- RETURN_EX_BEST20: `{concentration['return_ex_best20']:.4%}`",
        "",
        "## Exit interaction",
        "",
        "| Exit lineage | Trades | Win rate | Median return | Realized P&L |",
        "|---|---:|---:|---:|---:|",
        *exit_lines,
        "",
        "## Interpretation boundary",
        "",
        (
            "MFE, MAE, path, feature, month, and exit-lineage relationships are ex-post "
            "descriptive evidence used only to rank mechanism hypotheses. They are not "
            "causal counterfactuals or standalone trading rules. The full machine-readable "
            "distributions and frozen hashes are in the companion JSON."
        ),
        "",
    ]
    extended.gate_c.atomic_write(REPORT, "\n".join(lines).encode("utf-8"))
    print(
        json.dumps(
            {
                "result": "PASS",
                "trades": len(enriched),
                "generalization": "MIXED",
                "top20_concentration": concentration["top20_positive_pnl_concentration"],
                "return_ex_best20": concentration["return_ex_best20"],
                "used_2022_2025": "NO",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
