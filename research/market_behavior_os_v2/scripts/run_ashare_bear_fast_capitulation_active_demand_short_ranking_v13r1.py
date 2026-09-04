#!/usr/bin/env python3
"""Fail-closed reproduction of the causal V13 short-horizon ranking lane.

This runner does not reconstruct or rerun security outcomes.  It consumes the
frozen V11 T10/H20 outcome ledger, applies the V13 ranking/capacity contract,
fails closed on unknown ranking inputs, and replays the frozen portfolio.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


EXPERIMENT = "ASHARE-BEAR-FAST-CAPITULATION-ACTIVE-DEMAND-SHORT-RANKING-V13R1"
ROOT = Path("/Volumes/quant/CY_quant_research")
V11 = ROOT / "ashare_bear_fast_capitulation_active_demand_fast_v11/stage_b"
RAW_OUTCOMES = V11 / "raw_outcomes.parquet"
CANDIDATES = (
    ROOT
    / "ashare_oversold_stabilized_demand_reversal_v2/stage_a/"
    "candidates_2014_2023_outcome_blind.parquet"
)
REGIME = (
    ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a/"
    "causal_market_regime_2014_2023.parquet"
)
DAILY = (
    ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
OUT = ROOT / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1"

RANK_COLUMNS = [
    "stock_minus_industry_ret20",
    "close_vs_prior10_high",
    "close_location_x_f",
]
RANK_ASCENDING = [False, False, False]
K_PER_SLEEVE = 75
DAILY_ENTRY_CAP = 20
ENTRY_COST = 0.002
EXIT_COST = 0.002
SELECTION_END = pd.Timestamp("2020-12-31")
CHALLENGE_START = pd.Timestamp("2021-01-01")


class ResearchError(RuntimeError):
    """Fail-closed research implementation error."""


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


def release_before_open(
    active: dict[str, Any], entry_date: pd.Timestamp
) -> list[str]:
    """Release positions legally gone before a new entry at this day's open."""
    released: list[str] = []
    for symbol, row in list(active.items()):
        exit_date = pd.Timestamp(row.exit_date)
        open_exit = str(row.exit_reason) != "TARGET_10"
        if exit_date < entry_date or (exit_date == entry_date and open_exit):
            del active[symbol]
            released.append(symbol)
    return released


def select_capacity(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    missing = frame[RANK_COLUMNS].isna().any(axis=1)
    fail_closed = frame.loc[missing].copy()
    fail_closed["v13r1_capacity_status"] = "EXCLUDED"
    fail_closed["v13r1_skip_reason"] = "MISSING_REQUIRED_RANK_INPUT"

    eligible = frame.loc[~missing].copy()
    eligible = eligible.sort_values(
        ["entry_date", "sleeve", *RANK_COLUMNS, "event_id"],
        ascending=[True, True, *RANK_ASCENDING, True],
        kind="mergesort",
    )
    active: dict[str, dict[str, Any]] = {"MAIN": {}, "CHINEXT": {}}
    accepted_ids: list[str] = []
    skip_reason: dict[str, str] = {}
    max_active = 0
    same_open_release_then_entry = 0

    for entry_date, date_rows in eligible.groupby("entry_date", sort=True):
        entry_date = pd.Timestamp(entry_date)
        released_today: dict[str, set[str]] = {}
        for sleeve in active:
            released_today[sleeve] = set(
                release_before_open(active[sleeve], entry_date)
            )
        for sleeve, sleeve_rows in date_rows.groupby("sleeve", sort=True):
            accepted_today = 0
            for row in sleeve_rows.itertuples(index=False):
                if row.symbol in active[sleeve]:
                    skip_reason[row.event_id] = "ACTIVE_SYMBOL"
                    continue
                if len(active[sleeve]) >= K_PER_SLEEVE:
                    skip_reason[row.event_id] = "K75_ACTIVE_CAP"
                    continue
                if accepted_today >= DAILY_ENTRY_CAP:
                    skip_reason[row.event_id] = "DAILY_ENTRY_CAP_20"
                    continue
                accepted_ids.append(str(row.event_id))
                active[sleeve][str(row.symbol)] = row
                accepted_today += 1
                if str(row.symbol) in released_today[sleeve]:
                    same_open_release_then_entry += 1
        max_active = max(max_active, *(len(value) for value in active.values()))

    accepted = eligible.loc[eligible.event_id.isin(accepted_ids)].copy()
    accepted["v13r1_capacity_status"] = "ACCEPTED"
    accepted["v13r1_skip_reason"] = None
    capacity_skipped = eligible.loc[~eligible.event_id.isin(accepted_ids)].copy()
    capacity_skipped["v13r1_capacity_status"] = "SKIPPED"
    capacity_skipped["v13r1_skip_reason"] = capacity_skipped.event_id.map(skip_reason)
    skipped = pd.concat([fail_closed, capacity_skipped], ignore_index=True)
    audit = {
        "raw_rows": int(len(frame)),
        "missing_required_rank_input_rows": int(missing.sum()),
        "accepted_rows": int(len(accepted)),
        "capacity_skipped_rows": int(len(capacity_skipped)),
        "max_active_during_selection": int(max_active),
        "same_open_release_then_entry_count": int(same_open_release_then_entry),
    }
    return accepted, skipped, audit


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "date_count": 0,
            "date_equal_mean": None,
            "top5_positive_pnl_share": None,
            "mean_excluding_best5_signal_dates": None,
        }
    by_date = frame.groupby("signal_date").net_return.agg(["sum", "mean", "count"])
    best_dates = by_date.nlargest(min(5, len(by_date)), "sum").index
    positive_pnl = frame.loc[frame.net_return.gt(0), "net_return"].sum()
    top_pnl = by_date.loc[best_dates, "sum"].sum()
    remainder = frame.loc[~frame.signal_date.isin(best_dates), "net_return"]
    return {
        "date_count": int(len(by_date)),
        "date_equal_mean": float(by_date["mean"].mean()),
        "top5_positive_pnl_share": (
            None if positive_pnl <= 0 else float(top_pnl / positive_pnl)
        ),
        "mean_excluding_best5_signal_dates": (
            None if remainder.empty else float(remainder.mean())
        ),
    }


def trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    returns = pd.to_numeric(frame.net_return, errors="coerce")
    payload = {
        "trades": int(len(frame)),
        "mean_net": None if frame.empty else float(returns.mean()),
        "median_net": None if frame.empty else float(returns.median()),
        "win_rate": None if frame.empty else float(returns.gt(0).mean()),
        "severe10": None if frame.empty else float(returns.le(-0.10).mean()),
        "target_hit": (
            None if frame.empty else float(frame.exit_reason.eq("TARGET_10").mean())
        ),
        "average_holding_sessions": (
            None if frame.empty else float(frame.holding_sessions.mean())
        ),
        "median_holding_sessions": (
            None if frame.empty else float(frame.holding_sessions.median())
        ),
    }
    payload.update(concentration(frame))
    return payload


def annual_trade_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for year in range(2014, 2024):
        part = frame.loc[frame.signal_date.dt.year.eq(year)]
        rows.append({"year": year, **trade_metrics(part)})
    return rows


def load_paths(trades: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    connection = duckdb.connect()
    connection.register(
        "trades",
        trades[["event_id", "symbol", "entry_date", "exit_date"]],
    )
    paths = connection.execute(
        f"""
        SELECT t.event_id,
          CAST(d.trade_date AS DATE) AS trade_date,
          d.coord_open,d.coord_close
        FROM trades t
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON t.symbol=d.symbol
         AND CAST(d.trade_date AS DATE)
             BETWEEN CAST(t.entry_date AS DATE) AND CAST(t.exit_date AS DATE)
        """
    ).fetch_df()
    calendar = connection.execute(
        f"""
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date
        FROM read_parquet('{DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31'
        ORDER BY trade_date
        """
    ).fetch_df()
    connection.close()
    paths["trade_date"] = pd.to_datetime(paths.trade_date)
    dates = [pd.Timestamp(value) for value in pd.to_datetime(calendar.trade_date)]
    return paths, dates


def replay_portfolio(
    trades: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    paths, dates = load_paths(trades)
    expected = int((trades.exit_cal_idx - trades.entry_cal_idx + 1).sum())
    if len(paths) != expected:
        raise ResearchError(f"daily path coverage mismatch: {len(paths)} != {expected}")
    price = {
        (str(row.event_id), pd.Timestamp(row.trade_date)): (
            float(row.coord_open),
            float(row.coord_close),
        )
        for row in paths.itertuples(index=False)
    }
    entries = {key: value for key, value in trades.groupby("entry_date")}
    exits = {key: value for key, value in trades.groupby("exit_date")}
    state: dict[str, dict[str, Any]] = {
        "MAIN": {"cash": 0.5, "positions": {}},
        "CHINEXT": {"cash": 0.5, "positions": {}},
    }
    nav_rows: list[dict[str, Any]] = []
    negative_cash_count = 0

    for date in dates:
        exit_rows = exits.get(date)
        # Open-executable H20 exits are processed before open-executable entries.
        if exit_rows is not None:
            for row in exit_rows.itertuples(index=False):
                if str(row.exit_reason) == "TARGET_10":
                    continue
                sleeve = state[row.sleeve]
                position = sleeve["positions"].pop(str(row.event_id))
                sleeve["cash"] += (
                    position["quantity"] * float(row.exit_price) * (1.0 - EXIT_COST)
                )

        open_nav: dict[str, float] = {}
        for sleeve_name, sleeve in state.items():
            market_value = sum(
                position["quantity"] * price[(event_id, date)][0]
                for event_id, position in sleeve["positions"].items()
            )
            open_nav[sleeve_name] = float(sleeve["cash"] + market_value)

        entry_rows = entries.get(date)
        if entry_rows is not None:
            for sleeve_name, cohort in entry_rows.groupby("sleeve", sort=True):
                sleeve = state[sleeve_name]
                cohort_budget = min(0.10 * open_nav[sleeve_name], sleeve["cash"])
                per_name = min(
                    cohort_budget / len(cohort),
                    0.025 * open_nav[sleeve_name],
                )
                for row in cohort.sort_values("event_id").itertuples(index=False):
                    notional = min(per_name, sleeve["cash"] / (1.0 + ENTRY_COST))
                    if notional <= 0:
                        raise ResearchError("zero-notional accepted portfolio entry")
                    quantity = notional / float(row.entry_price)
                    sleeve["cash"] -= notional * (1.0 + ENTRY_COST)
                    sleeve["positions"][str(row.event_id)] = {
                        "quantity": quantity,
                        "symbol": str(row.symbol),
                    }

        # A target is an intraday event and does not finance this day's open entries.
        if exit_rows is not None:
            for row in exit_rows.itertuples(index=False):
                if str(row.exit_reason) != "TARGET_10":
                    continue
                sleeve = state[row.sleeve]
                position = sleeve["positions"].pop(str(row.event_id))
                sleeve["cash"] += (
                    position["quantity"] * float(row.exit_price) * (1.0 - EXIT_COST)
                )

        row_payload: dict[str, Any] = {"trade_date": date}
        invested = 0.0
        total_nav = 0.0
        active_positions = 0
        for sleeve_name, prefix in (("MAIN", "main"), ("CHINEXT", "chinext")):
            sleeve = state[sleeve_name]
            market_value = sum(
                position["quantity"] * price[(event_id, date)][1]
                for event_id, position in sleeve["positions"].items()
            )
            sleeve_nav = float(sleeve["cash"] + market_value)
            row_payload[f"{prefix}_nav"] = sleeve_nav
            row_payload[f"{prefix}_active"] = int(len(sleeve["positions"]))
            invested += market_value
            total_nav += sleeve_nav
            active_positions += len(sleeve["positions"])
            negative_cash_count += int(sleeve["cash"] < -1e-12)
        row_payload["combined_nav"] = total_nav
        row_payload["active_positions"] = int(active_positions)
        row_payload["utilization"] = 0.0 if total_nav == 0 else invested / total_nav
        nav_rows.append(row_payload)

    nav = pd.DataFrame(nav_rows)
    nav["ret"] = nav.combined_nav.pct_change().fillna(0.0)
    open_end = sum(len(value["positions"]) for value in state.values())
    return nav, {
        "negative_cash_count": int(negative_cash_count),
        "open_position_at_end_count": int(open_end),
    }


def nav_metrics(nav: pd.DataFrame) -> dict[str, Any]:
    start = float(nav.combined_nav.iloc[0])
    end = float(nav.combined_nav.iloc[-1])
    elapsed_days = int((nav.trade_date.iloc[-1] - nav.trade_date.iloc[0]).days)
    cagr = (end / start) ** (365.2425 / elapsed_days) - 1.0
    drawdown = nav.combined_nav / nav.combined_nav.cummax() - 1.0
    daily_std = float(nav.ret.std(ddof=1))
    sharpe = None if daily_std == 0 else float(nav.ret.mean() / daily_std * math.sqrt(242))
    return {
        "total_return": float(end / start - 1.0),
        "cagr": float(cagr),
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
        "average_utilization": float(nav.utilization.mean()),
        "max_active_positions": int(nav.active_positions.max()),
        "ending_nav": end,
    }


def annual_nav_metrics(nav: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    previous_nav = float(nav.combined_nav.iloc[0])
    for year in range(2014, 2024):
        part = nav.loc[nav.trade_date.dt.year.eq(year)].copy()
        if part.empty:
            continue
        annual_return = float(part.combined_nav.iloc[-1] / previous_nav - 1.0)
        path = pd.concat(
            [pd.Series([previous_nav]), part.combined_nav.reset_index(drop=True)],
            ignore_index=True,
        )
        maxdd = float((path / path.cummax() - 1.0).min())
        std = float(part.ret.std(ddof=1))
        sharpe = None if std == 0 else float(part.ret.mean() / std * math.sqrt(242))
        rows.append(
            {
                "year": year,
                "return": annual_return,
                "max_drawdown": maxdd,
                "sharpe": sharpe,
                "average_utilization": float(part.utilization.mean()),
                "max_active_positions": int(part.active_positions.max()),
            }
        )
        previous_nav = float(part.combined_nav.iloc[-1])
    return rows


def true_overlap_count(frame: pd.DataFrame) -> int:
    violations = 0
    for _, symbol_rows in frame.sort_values(
        ["symbol", "entry_date", "exit_date"]
    ).groupby("symbol"):
        records = list(symbol_rows.itertuples(index=False))
        for left, right in zip(records, records[1:]):
            if pd.Timestamp(right.entry_date) < pd.Timestamp(left.exit_date):
                violations += 1
            elif (
                pd.Timestamp(right.entry_date) == pd.Timestamp(left.exit_date)
                and str(left.exit_reason) == "TARGET_10"
            ):
                violations += 1
    return violations


def causal_audit(frame: pd.DataFrame) -> dict[str, Any]:
    regime = pd.read_parquet(REGIME)
    regime["trade_date"] = pd.to_datetime(regime.trade_date)
    regime = regime.sort_values("trade_date", kind="mergesort")
    regime["breadth20_lag5_rebuilt"] = regime.market_positive_ret20_share.shift(5)
    state = frame[["event_id", "signal_date"]].merge(
        regime,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    )
    bear_definition = (
        state.market_median_ret20.le(0)
        & state.market_median_ret60.le(0)
        & state.market_positive_ret20_share.le(0.50)
        & state.market_positive_ret60_share.le(0.50)
        & state.market_regime.eq("BEAR")
    )
    timestamp_columns = [
        "available_at",
        "decision_at",
        "regime_latest_source_timestamp",
        "b20_l5_source_timestamp",
    ]
    timestamp_violations = {
        column: int(
            (
                pd.to_datetime(frame[column])
                > pd.to_datetime(frame.signal_decision_at)
            ).sum()
        )
        for column in timestamp_columns
    }
    return {
        "event_id_duplicate_count": int(frame.event_id.duplicated().sum()),
        "accepted_missing_rank_input_count": int(
            frame[RANK_COLUMNS].isna().any(axis=1).sum()
        ),
        "hard_valid_false_count": int((~frame.hard_valid.fillna(False)).sum()),
        "timestamp_after_signal_count_by_field": timestamp_violations,
        "bear_definition_violation_count": int((~bear_definition).sum()),
        "breadth_repair_violation_count": int(
            (~frame.market_positive_ret20_share.gt(frame.b20_l5)).sum()
        ),
        "rebuilt_breadth_lag_mismatch_count": int(
            (~np.isclose(
                state.breadth20_lag5_rebuilt,
                frame.b20_l5.to_numpy(),
                equal_nan=False,
            )).sum()
        ),
        "prior10_gate_violation_count": int((~frame.prior10_return.le(-0.08)).sum()),
        "entry_at_or_before_signal_count": int(
            (frame.entry_date.le(frame.signal_date)).sum()
        ),
        "exit_at_or_before_entry_count": int(
            (frame.exit_date.le(frame.entry_date)).sum()
        ),
        "true_duplicate_active_symbol_count": int(true_overlap_count(frame)),
        "post_2023_signal_count": int(frame.signal_date.dt.year.gt(2023).sum()),
        "post_2023_exit_count": int(frame.exit_date.dt.year.gt(2023).sum()),
        "repository_2024_plus_data_opened": False,
        "security_outcomes_rerun": False,
    }


def main() -> None:
    for path in (RAW_OUTCOMES, CANDIDATES, REGIME, DAILY):
        if not path.exists():
            raise ResearchError(f"missing required input: {path}")
    raw = pd.read_parquet(RAW_OUTCOMES)
    features = pd.read_parquet(CANDIDATES)
    frame = raw.merge(
        features,
        on="event_id",
        how="left",
        suffixes=("", "_f"),
        validate="one_to_one",
    )
    for column in ("signal_date", "entry_date", "exit_date", "trade_date"):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    if len(frame) != 660 or frame.event_id.duplicated().any():
        raise ResearchError("frozen V11 population identity drift")
    if frame[RANK_COLUMNS].isna().all(axis=0).any():
        raise ResearchError("required ranking feature is entirely unavailable")

    selected, skipped, capacity_audit = select_capacity(frame)
    selected = selected.sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    nav, portfolio_audit = replay_portfolio(selected)
    causal = causal_audit(selected)
    if any(causal["timestamp_after_signal_count_by_field"].values()):
        raise ResearchError("post-signal feature timestamp detected")
    required_zero = [
        causal["event_id_duplicate_count"],
        causal["accepted_missing_rank_input_count"],
        causal["hard_valid_false_count"],
        causal["bear_definition_violation_count"],
        causal["breadth_repair_violation_count"],
        causal["rebuilt_breadth_lag_mismatch_count"],
        causal["prior10_gate_violation_count"],
        causal["entry_at_or_before_signal_count"],
        causal["exit_at_or_before_entry_count"],
        causal["true_duplicate_active_symbol_count"],
        portfolio_audit["negative_cash_count"],
        portfolio_audit["open_position_at_end_count"],
    ]
    if any(required_zero):
        raise ResearchError(f"final fail-closed audit failed: {required_zero}")

    selection = selected.loc[selected.signal_date.le(SELECTION_END)].copy()
    challenge = selected.loc[selected.signal_date.ge(CHALLENGE_START)].copy()
    overall = trade_metrics(selected)
    overall["average_completed_trades_per_year"] = len(selected) / 10.0
    blocks = {
        "selection_2014_2020": trade_metrics(selection),
        "challenge_2021_2023": trade_metrics(challenge),
    }
    blocks["selection_2014_2020"]["average_completed_trades_per_year"] = (
        len(selection) / 7.0
    )
    blocks["challenge_2021_2023"]["average_completed_trades_per_year"] = (
        len(challenge) / 3.0
    )
    annual = annual_trade_metrics(selected)
    gates = {
        "average_trades_per_year_gt_50": bool(
            overall["average_completed_trades_per_year"] > 50
        ),
        "mean_net_gt_3pct": bool(overall["mean_net"] > 0.03),
        "average_holding_sessions_le_15": bool(
            overall["average_holding_sessions"] <= 15
        ),
        "every_nonempty_year_mean_positive": bool(
            all(row["trades"] == 0 or row["mean_net"] > 0 for row in annual)
        ),
        "challenge_mean_positive": bool(blocks["challenge_2021_2023"]["mean_net"] > 0),
        "top5_positive_pnl_share_lt_50pct": bool(
            overall["top5_positive_pnl_share"] < 0.50
        ),
        "mean_excluding_best5_signal_dates_positive": bool(
            overall["mean_excluding_best5_signal_dates"] > 0
        ),
        "causal_audit_all_zero": True,
    }
    verdict = (
        "HISTORICAL_TRADE_LEVEL_GOAL_MET_PORTFOLIO_EFFICIENCY_LOW"
        if all(gates.values())
        else "HISTORICAL_TRADE_LEVEL_GOAL_NOT_MET"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    selected_path = OUT / "selected_accepted_trades.parquet"
    skipped_path = OUT / "skipped_trades.parquet"
    nav_path = OUT / "portfolio_nav.parquet"
    write_parquet(selected, selected_path)
    write_parquet(skipped, skipped_path)
    write_parquet(nav, nav_path)
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "economic_mechanism": (
            "In a causally known broad BEAR state, improving 20-session breadth "
            "combined with a stock-specific fast washout and completed-session "
            "active-demand ignition identifies forced-supply transfer; BULL and "
            "TRANSITION states hold cash."
        ),
        "regime_routing": {
            "BEAR": "evaluate the frozen signal",
            "BULL": "HOLD_CASH",
            "TRANSITION": "HOLD_CASH",
            "regime_is_future_realized_market_return": False,
        },
        "frozen_strategy": {
            "market_state": (
                "BEAR at completed signal close: both 20d/60d market medians <=0 "
                "and both positive-return shares <=50%"
            ),
            "breadth_repair": "positive-ret20 share > its value five completed market sessions earlier",
            "stock_signal": "exact OAI plus prior10_return <= -8%",
            "ranking": [
                "higher stock_minus_industry_ret20",
                "higher close_vs_prior10_high",
                "higher close_location",
                "event_id",
            ],
            "missing_rank_policy": "FAIL_CLOSED",
            "entry": "next legal open, no later than three market sessions",
            "target": "+10%",
            "time_stop": "H20 next legal open",
            "round_trip_cost": 0.004,
            "K_per_sleeve": K_PER_SLEEVE,
            "daily_entry_cap_per_sleeve": DAILY_ENTRY_CAP,
        },
        "selection_governance": {
            "ranking_family_selected_on": "2014-2020 only",
            "selected_ranking_inherited_from_v13": "RELATIVE_LEADER",
            "v13r1_change": "exclude every row with an unknown required ranking input",
            "challenge_2021_2023_used_to_change_rule": False,
            "post_observation_warning": "2022-2023 are not pristine because prior research observed outcomes",
        },
        "overall": overall,
        "blocks": blocks,
        "annual": annual,
        "portfolio": nav_metrics(nav),
        "annual_portfolio": annual_nav_metrics(nav),
        "gates": gates,
        "audit": {**capacity_audit, **portfolio_audit, **causal},
        "input_hashes": {
            str(RAW_OUTCOMES): sha256(RAW_OUTCOMES),
            str(CANDIDATES): sha256(CANDIDATES),
            str(REGIME): sha256(REGIME),
            str(DAILY): sha256(DAILY),
        },
    }
    result_path = OUT / "result.json"
    write_json(result_path, result)
    artifact_hashes = {
        path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
        for path in (selected_path, skipped_path, nav_path, result_path)
    }
    write_json(OUT / "artifact_hashes.json", artifact_hashes)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
