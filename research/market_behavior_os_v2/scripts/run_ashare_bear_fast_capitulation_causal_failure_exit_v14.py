#!/usr/bin/env python3
"""Develop one bounded causal failure-exit family for the frozen V13R1 lane."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as v13  # noqa: E402


EXPERIMENT = "ASHARE-BEAR-FAST-CAPITULATION-CAUSAL-FAILURE-EXIT-V14"
ROOT = Path("/Volumes/quant/CY_quant_research")
SOURCE = (
    ROOT
    / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1/"
    "selected_accepted_trades.parquet"
)
DAILY = v13.DAILY
REGIME = v13.REGIME
OUT = ROOT / "ashare_bear_fast_capitulation_causal_failure_exit_v14"
CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "experiments/ASHARE-BEAR-FAST-CAPITULATION-CAUSAL-FAILURE-EXIT-V14_contract.json"
)
EXPECTED_SOURCE_SHA256 = "8e62f4b3a9552cac769e95eb6e172ec65e8d53af207cccb06a60c6ad21ca8140"
PROFILES = [
    "F0_NO_FAILURE",
    "F1_SIGNAL_LOW_BREAK",
    "F2_BREADTH_REPAIR_LOST_UNDERWATER",
    "F3_HYBRID",
]
PROFILE_COMPLEXITY = {
    "F0_NO_FAILURE": 0,
    "F1_SIGNAL_LOW_BREAK": 1,
    "F2_BREADTH_REPAIR_LOST_UNDERWATER": 1,
    "F3_HYBRID": 2,
}


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, or execution drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()


def legal_state(row: Any) -> bool:
    required = (
        "trade_status",
        "current_day_data_tradable",
        "market_rule_valid",
        "corporate_action_valid",
        "corporate_action_blocking",
        "hard_valid",
    )
    if any(pd.isna(getattr(row, field)) for field in required):
        return False
    return bool(
        int(row.trade_status) == 1
        and row.current_day_data_tradable
        and row.market_rule_valid
        and row.corporate_action_valid
        and not row.corporate_action_blocking
        and row.hard_valid
    )


def sellable_open(row: Any) -> bool:
    values = (row.open, row.coord_open, row.down_limit_price, row.coordinate_factor)
    return bool(
        legal_state(row)
        and all(np.isfinite(float(value)) for value in values)
        and float(row.open) > 0
        and float(row.coord_open) > 0
        and round(float(row.open) * 100) > round(float(row.down_limit_price) * 100)
    )


def failure_reason(
    profile: str,
    *,
    coord_close: float,
    signal_coord_low: float,
    entry_price: float,
    breadth20: float,
    breadth20_lag5: float,
) -> str | None:
    signal_low_break = bool(
        np.isfinite(coord_close)
        and np.isfinite(signal_coord_low)
        and coord_close < signal_coord_low
    )
    breadth_failure = bool(
        np.isfinite(coord_close)
        and np.isfinite(entry_price)
        and np.isfinite(breadth20)
        and np.isfinite(breadth20_lag5)
        and breadth20 <= breadth20_lag5
        and coord_close < entry_price
    )
    if profile == "F1_SIGNAL_LOW_BREAK" and signal_low_break:
        return "FAIL_SIGNAL_LOW_BREAK"
    if profile == "F2_BREADTH_REPAIR_LOST_UNDERWATER" and breadth_failure:
        return "FAIL_BREADTH_REPAIR_LOST_UNDERWATER"
    if profile == "F3_HYBRID":
        if signal_low_break:
            return "FAIL_SIGNAL_LOW_BREAK"
        if breadth_failure:
            return "FAIL_BREADTH_REPAIR_LOST_UNDERWATER"
    return None


def load_paths(trades: pd.DataFrame) -> pd.DataFrame:
    regime = pd.read_parquet(REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    regime = regime.sort_values("trade_date", kind="mergesort")
    regime["breadth20_lag5"] = regime.market_positive_ret20_share.shift(5)
    connection = duckdb.connect()
    connection.register(
        "trades",
        trades[
            [
                "event_id",
                "symbol",
                "sleeve",
                "signal_date",
                "entry_date",
                "exit_date",
            ]
        ],
    )
    connection.register(
        "regime",
        regime[
            [
                "trade_date",
                "market_positive_ret20_share",
                "breadth20_lag5",
                "latest_source_timestamp",
            ]
        ],
    )
    paths = connection.execute(
        f"""
        SELECT t.event_id,t.symbol,t.sleeve,t.signal_date,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price,d.decision_at,
          r.market_positive_ret20_share,r.breadth20_lag5,
          r.latest_source_timestamp AS regime_latest_source_timestamp
        FROM trades t
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON t.symbol=d.symbol
         AND CAST(d.trade_date AS DATE)
             BETWEEN CAST(t.entry_date AS DATE) AND CAST(t.exit_date AS DATE)
        LEFT JOIN regime r
          ON CAST(d.trade_date AS DATE)=CAST(r.trade_date AS DATE)
        ORDER BY t.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    return paths


def replay_one(event: Any, path: pd.DataFrame, profile: str) -> dict[str, Any]:
    pending_reason: str | None = None
    pending_decision_idx: int | None = None
    chosen: Any | None = None
    exit_price = math.nan
    exit_reason: str | None = None
    target = float(event.entry_price) * 1.10
    path = path.sort_values("cal_idx", kind="mergesort")
    for row in path.itertuples(index=False):
        if int(row.cal_idx) <= int(event.entry_cal_idx):
            continue
        if (
            not np.isfinite(float(row.invalid_step_cum))
            or float(row.invalid_step_cum) != float(event.signal_invalid)
        ):
            raise ResearchError(f"coordinate lineage changed for {event.event_id}")
        if pending_reason is not None and sellable_open(row):
            chosen = row
            exit_price = float(row.coord_open)
            exit_reason = pending_reason
            break
        if (
            legal_state(row)
            and np.isfinite(float(row.coord_high))
            and float(row.coord_high) >= target
        ):
            chosen = row
            exit_price = target
            exit_reason = "TARGET_10"
            pending_decision_idx = int(event.entry_cal_idx)
            break
        if profile != "F0_NO_FAILURE" and legal_state(row):
            reason = failure_reason(
                profile,
                coord_close=float(row.coord_close),
                signal_coord_low=float(event.coord_low),
                entry_price=float(event.entry_price),
                breadth20=float(row.market_positive_ret20_share),
                breadth20_lag5=float(row.breadth20_lag5),
            )
            if reason is not None:
                pending_reason = reason
                pending_decision_idx = int(row.cal_idx)
        if legal_state(row) and int(row.cal_idx) >= int(event.entry_cal_idx) + 20:
            if pending_reason is None:
                pending_reason = "H20_TIME_STOP"
                pending_decision_idx = int(row.cal_idx)
    if chosen is None or exit_reason is None:
        raise ResearchError(f"no completed exit for {event.event_id} under {profile}")
    gross = float(exit_price) / float(event.entry_price) - 1.0
    return {
        "event_id": str(event.event_id),
        "symbol": str(event.symbol),
        "sleeve": str(event.sleeve),
        "signal_date": pd.Timestamp(event.signal_date),
        "entry_date": pd.Timestamp(event.entry_date),
        "entry_cal_idx": int(event.entry_cal_idx),
        "entry_price": float(event.entry_price),
        "exit_date": pd.Timestamp(chosen.trade_date),
        "exit_cal_idx": int(chosen.cal_idx),
        "exit_price": float(exit_price),
        "exit_reason": exit_reason,
        "exit_decision_cal_idx": int(pending_decision_idx),
        "holding_sessions": int(chosen.cal_idx) - int(event.entry_cal_idx),
        "gross_return": gross,
        "net_return": gross - 0.004,
        "profile": profile,
    }


def replay(trades: pd.DataFrame, profile: str) -> pd.DataFrame:
    paths = load_paths(trades)
    groups = {key: value for key, value in paths.groupby("event_id", sort=False)}
    rows = [
        replay_one(event, groups[str(event.event_id)], profile)
        for event in trades.itertuples(index=False)
    ]
    return pd.DataFrame(rows).sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)


def cvar5(frame: pd.DataFrame) -> float:
    n = max(1, int(math.ceil(0.05 * len(frame))))
    return float(frame.net_return.nsmallest(n).mean())


def positive_date_equal_years(frame: pd.DataFrame) -> int:
    count = 0
    for _, part in frame.groupby(frame.signal_date.dt.year):
        date_equal = part.groupby("signal_date").net_return.mean().mean()
        count += int(date_equal > 0)
    return count


def profile_summary(
    trades: pd.DataFrame, nav: pd.DataFrame, profile: str
) -> dict[str, Any]:
    metrics = v13.trade_metrics(trades)
    metrics.update(
        {
            "profile": profile,
            "cvar5": cvar5(trades),
            "positive_date_equal_years": positive_date_equal_years(trades),
            "positive_portfolio_years": int(
                sum(
                    row["return"] > 0
                    for row in v13.annual_nav_metrics(nav)
                    if row["year"] <= 2020
                )
            ),
            "complexity": PROFILE_COMPLEXITY[profile],
            "failure_exit_count": int(
                trades.exit_reason.astype(str).str.startswith("FAIL_").sum()
            ),
            "portfolio": v13.nav_metrics(nav),
        }
    )
    return metrics


def select_profile(summaries: list[dict[str, Any]]) -> str:
    eligible = [
        item
        for item in summaries
        if item["mean_net"] > 0.03 and item["average_holding_sessions"] <= 15
    ]
    if not eligible:
        raise ResearchError("no frozen failure-exit profile passes development gates")
    eligible.sort(
        key=lambda item: (
            -item["positive_date_equal_years"],
            -item["positive_portfolio_years"],
            -item["mean_excluding_best5_signal_dates"],
            item["severe10"],
            item["complexity"],
            item["profile"],
        )
    )
    return str(eligible[0]["profile"])


def main() -> None:
    if not CONTRACT.is_file() or not SOURCE.is_file():
        raise ResearchError("missing frozen contract or V13R1 source")
    if sha256(SOURCE) != EXPECTED_SOURCE_SHA256:
        raise ResearchError("V13R1 accepted-trade source drift")
    source = pd.read_parquet(SOURCE)
    for column in ("signal_date", "entry_date", "exit_date"):
        source[column] = pd.to_datetime(source[column]).dt.normalize()
    development_source = source.loc[source.signal_date.dt.year.le(2020)].copy()

    development_summaries: list[dict[str, Any]] = []
    development_ledgers: dict[str, pd.DataFrame] = {}
    for profile in PROFILES:
        trades = replay(development_source, profile)
        development_ledgers[profile] = trades
        nav, portfolio_audit = v13.replay_portfolio(trades)
        if portfolio_audit["negative_cash_count"] or portfolio_audit["open_position_at_end_count"]:
            raise ResearchError(f"portfolio audit failed for {profile}: {portfolio_audit}")
        development_summaries.append(profile_summary(trades, nav, profile))

    baseline = development_ledgers["F0_NO_FAILURE"]
    expected = development_source.set_index("event_id")
    actual = baseline.set_index("event_id")
    baseline_mismatch = int(
        (~np.isclose(expected.loc[actual.index, "net_return"], actual.net_return)).sum()
        + (expected.loc[actual.index, "exit_date"] != actual.exit_date).sum()
        + (expected.loc[actual.index, "exit_reason"] != actual.exit_reason).sum()
    )
    if baseline_mismatch:
        raise ResearchError(f"frozen baseline replay mismatch: {baseline_mismatch}")

    selected_profile = select_profile(development_summaries)
    full_trades = replay(source, selected_profile)
    full_nav, portfolio_audit = v13.replay_portfolio(full_trades)
    challenge = full_trades.loc[full_trades.signal_date.dt.year.ge(2021)].copy()
    annual = v13.annual_trade_metrics(full_trades)
    overall = v13.trade_metrics(full_trades)
    overall["average_completed_trades_per_year"] = len(full_trades) / 10.0
    challenge_metrics = v13.trade_metrics(challenge)
    challenge_metrics["average_completed_trades_per_year"] = len(challenge) / 3.0

    paths = load_paths(full_trades)
    timestamp_after_close = int(
        (
            pd.to_datetime(paths.regime_latest_source_timestamp)
            > pd.to_datetime(paths.decision_at)
        ).sum()
    )
    audit = {
        "contract_sha256": sha256(CONTRACT),
        "source_sha256": sha256(SOURCE),
        "baseline_replay_mismatch_count": baseline_mismatch,
        "profile_selected_before_challenge_replay": True,
        "challenge_used_in_profile_selection": False,
        "regime_source_after_completed_close_count": timestamp_after_close,
        "entry_at_or_before_signal_count": int(
            full_trades.entry_date.le(full_trades.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(
            full_trades.exit_date.le(full_trades.entry_date).sum()
        ),
        "t1_same_day_exit_count": int(
            full_trades.exit_date.eq(full_trades.entry_date).sum()
        ),
        "true_duplicate_active_symbol_count": v13.true_overlap_count(full_trades),
        **portfolio_audit,
        "repository_2024_plus_data_opened": False,
    }
    if any(
        audit[key]
        for key in (
            "baseline_replay_mismatch_count",
            "regime_source_after_completed_close_count",
            "entry_at_or_before_signal_count",
            "exit_at_or_before_entry_count",
            "t1_same_day_exit_count",
            "true_duplicate_active_symbol_count",
            "negative_cash_count",
            "open_position_at_end_count",
        )
    ):
        raise ResearchError(f"V14 audit failed: {audit}")

    gates = {
        "average_trades_per_year_gt_50": overall["average_completed_trades_per_year"] > 50,
        "mean_net_gt_3pct": overall["mean_net"] > 0.03,
        "average_holding_sessions_le_15": overall["average_holding_sessions"] <= 15,
        "every_nonempty_year_mean_positive": all(
            row["trades"] == 0 or row["mean_net"] > 0 for row in annual
        ),
        "top5_positive_pnl_share_lt_50pct": overall["top5_positive_pnl_share"] < 0.50,
        "mean_excluding_best5_dates_positive": overall[
            "mean_excluding_best5_signal_dates"
        ]
        > 0,
    }
    verdict = (
        "CAUSAL_FAILURE_EXIT_IMPROVES_ROBUSTNESS"
        if selected_profile != "F0_NO_FAILURE" and all(gates.values())
        else (
            "NO_FAILURE_EXIT_REMAINS_PREFERRED"
            if selected_profile == "F0_NO_FAILURE"
            else "FAILURE_EXIT_DOES_NOT_MEET_GOAL"
        )
    )
    OUT.mkdir(parents=True, exist_ok=True)
    trades_path = OUT / "selected_trades.parquet"
    nav_path = OUT / "portfolio_nav.parquet"
    write_parquet(full_trades, trades_path)
    write_parquet(full_nav, nav_path)
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "development_profile_comparison": development_summaries,
        "selected_profile": selected_profile,
        "overall": overall,
        "challenge_2021_2023": challenge_metrics,
        "annual": annual,
        "portfolio": v13.nav_metrics(full_nav),
        "annual_portfolio": v13.annual_nav_metrics(full_nav),
        "gates": gates,
        "audit": audit,
    }
    result_path = OUT / "result.json"
    write_json(result_path, result)
    write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (trades_path, nav_path, result_path)
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
