#!/usr/bin/env python3
"""Deterministically combine the frozen causal BEAR and BULL short lanes."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import run_ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1 as v13  # noqa: E402


EXPERIMENT = "ASHARE-CAUSAL-BULL-BEAR-DUAL-MECHANISM-SHORT-V16"
ROOT = Path("/Volumes/quant/CY_quant_research")
BEAR = (
    ROOT
    / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1/"
    "selected_accepted_trades.parquet"
)
BULL = (
    ROOT
    / "ashare_bull_delayed_supply_contraction_short_repricing_v15/"
    "selected_profile_trades.parquet"
)
BULL_FEATURES = (
    ROOT
    / "ashare_demand_impulse_inside_day_delayed_breakout_v5/stage_a/"
    "candidates_frozen.parquet"
)
CONTRACT = (
    Path(__file__).resolve().parents[1]
    / "experiments/ASHARE-CAUSAL-BULL-BEAR-DUAL-MECHANISM-SHORT-V16_contract.json"
)
OUT = ROOT / "ashare_causal_bull_bear_dual_mechanism_short_v16"
EXPECTED = {
    "bear": "8e62f4b3a9552cac769e95eb6e172ec65e8d53af207cccb06a60c6ad21ca8140",
    "bull": "08fdec7808d6c462519f0d87cc63a3367543a4277da0a452b0b169ba3edaa883",
}


class ResearchError(RuntimeError):
    """Fail closed on frozen-source or portfolio drift."""


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


def load_lanes() -> pd.DataFrame:
    bear = pd.read_parquet(BEAR)
    bear["lane"] = "BEAR_FAST_CAPITULATION"
    bear["market_route"] = "BEAR"
    bear["rank1"] = bear.stock_minus_industry_ret20
    bear["rank2"] = bear.close_vs_prior10_high
    bear["rank3"] = bear.close_location_x_f

    bull = pd.read_parquet(BULL)
    bull = bull.loc[bull.status.eq("COMPLETED")].copy()
    features = duckdb.sql(
        f"SELECT event_id,impulse3,pre_impulse_ret60 FROM read_parquet('{BULL_FEATURES.as_posix()}')"
    ).df()
    bull = bull.merge(features, on="event_id", how="left", validate="one_to_one")
    bull["lane"] = "BULL_SUPPLY_CONTRACTION"
    bull["market_route"] = "BULL"
    bull["rank1"] = bull.impulse3
    bull["rank2"] = -bull.pre_impulse_ret60
    bull["rank3"] = 0.0

    columns = [
        "event_id",
        "symbol",
        "sleeve",
        "signal_date",
        "entry_date",
        "entry_cal_idx",
        "entry_price",
        "exit_date",
        "exit_cal_idx",
        "exit_price",
        "exit_reason",
        "exit_decision_cal_idx",
        "holding_sessions",
        "gross_return",
        "net_return",
        "lane",
        "market_route",
        "rank1",
        "rank2",
        "rank3",
    ]
    frame = pd.concat([bear[columns], bull[columns]], ignore_index=True)
    for column in ("signal_date", "entry_date", "exit_date"):
        frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    if frame.event_id.duplicated().any():
        raise ResearchError("cross-lane duplicate event identity")
    if frame[["rank1", "rank2", "rank3"]].isna().any(axis=None):
        raise ResearchError("unknown shared-capacity rank input")
    return frame


def apply_shared_capacity(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    ordered = frame.sort_values(
        ["entry_date", "sleeve", "rank1", "rank2", "rank3", "event_id"],
        ascending=[True, True, False, False, False, True],
        kind="mergesort",
    )
    active: dict[str, dict[str, Any]] = {"MAIN": {}, "CHINEXT": {}}
    accepted: list[str] = []
    reasons: dict[str, str] = {}
    max_active = 0
    same_open_release_then_entry = 0
    for date, date_rows in ordered.groupby("entry_date", sort=True):
        released: dict[str, set[str]] = {}
        for sleeve in active:
            released[sleeve] = set(v13.release_before_open(active[sleeve], date))
        for sleeve, sleeve_rows in date_rows.groupby("sleeve", sort=True):
            accepted_today = 0
            for row in sleeve_rows.itertuples(index=False):
                reason = None
                if row.symbol in active[sleeve]:
                    reason = "ACTIVE_SYMBOL"
                elif len(active[sleeve]) >= 75:
                    reason = "K75_ACTIVE_CAP"
                elif accepted_today >= 20:
                    reason = "DAILY_ENTRY_CAP_20"
                if reason is not None:
                    reasons[row.event_id] = reason
                    continue
                accepted.append(str(row.event_id))
                active[sleeve][str(row.symbol)] = row
                accepted_today += 1
                same_open_release_then_entry += int(row.symbol in released[sleeve])
        max_active = max(max_active, *(len(value) for value in active.values()))
    chosen = ordered.loc[ordered.event_id.isin(accepted)].copy()
    chosen["capacity_status"] = "ACCEPTED"
    chosen["skip_reason"] = None
    skipped = ordered.loc[~ordered.event_id.isin(accepted)].copy()
    skipped["capacity_status"] = "SKIPPED"
    skipped["skip_reason"] = skipped.event_id.map(reasons)
    return chosen, skipped, {
        "raw_trade_count": int(len(frame)),
        "accepted_trade_count": int(len(chosen)),
        "capacity_skip_count": int(len(skipped)),
        "max_active_during_selection": int(max_active),
        "same_open_release_then_entry_count": int(same_open_release_then_entry),
    }


def causal_source_audit(accepted: pd.DataFrame) -> dict[str, Any]:
    bear_ids = accepted.loc[
        accepted.market_route.eq("BEAR"), ["event_id"]
    ]
    bear_source = pd.read_parquet(BEAR).merge(
        bear_ids, on="event_id", how="inner", validate="one_to_one"
    )
    bear_after = {
        column: int(
            (
                pd.to_datetime(bear_source[column])
                > pd.to_datetime(bear_source.signal_decision_at)
            ).sum()
        )
        for column in (
            "available_at",
            "decision_at",
            "regime_latest_source_timestamp",
            "b20_l5_source_timestamp",
        )
    }
    bull_ids = accepted.loc[
        accepted.market_route.eq("BULL"), ["event_id"]
    ]
    connection = duckdb.connect()
    connection.register("bull_ids", bull_ids)
    bull = connection.execute(
        f"""
        SELECT f.event_id,f.symbol,f.setup_cal_idx,f.cal_idx,
          f.setup_high_coord,f.coord_close,f.invalid_step_cum,
          f.available_at,f.decision_at,f.impulse3,f.pre_impulse_ret60,
          r.market_regime,r.latest_source_timestamp
        FROM bull_ids i
        JOIN read_parquet('{BULL_FEATURES.as_posix()}') f USING(event_id)
        LEFT JOIN read_parquet('{v13.REGIME.as_posix()}') r
          ON CAST(f.signal_date AS DATE)=r.trade_date
        """
    ).fetch_df()
    # The economic strict-close test is tick-aware.  Two coordinate values in
    # the source differ by machine epsilon while both raw prices are identical.
    earlier_strict_tick_breakout = connection.execute(
        f"""
        SELECT COUNT(*)
        FROM bull_ids i
        JOIN read_parquet('{BULL_FEATURES.as_posix()}') f USING(event_id)
        JOIN read_parquet('{v13.DAILY.as_posix()}') setup
          ON f.symbol=setup.symbol AND f.setup_cal_idx=setup.cal_idx
        JOIN read_parquet('{v13.DAILY.as_posix()}') d
          ON f.symbol=d.symbol
         AND d.cal_idx>f.setup_cal_idx AND d.cal_idx<f.cal_idx
        WHERE ROUND(d.close*100)>ROUND(setup.high*100)
          AND d.hard_valid AND d.history_valid AND d.current_valid
          AND d.current_day_data_tradable AND d.market_rule_valid
          AND d.corporate_action_valid AND NOT d.corporate_action_blocking
          AND d.invalid_step_cum=f.invalid_step_cum
        """
    ).fetchone()[0]
    connection.close()
    return {
        "bear_timestamp_after_signal_count_by_field": bear_after,
        "bear_missing_rank_input_count": int(
            bear_source[
                [
                    "stock_minus_industry_ret20",
                    "close_vs_prior10_high",
                    "close_location_x_f",
                ]
            ]
            .isna()
            .any(axis=1)
            .sum()
        ),
        "bear_prior10_gate_violation_count": int(
            bear_source.prior10_return.gt(-0.08).sum()
        ),
        "bear_breadth_repair_violation_count": int(
            bear_source.market_positive_ret20_share.le(bear_source.b20_l5).sum()
        ),
        "bull_available_after_signal_count": int(
            (pd.to_datetime(bull.available_at) > pd.to_datetime(bull.decision_at)).sum()
        ),
        "bull_regime_after_signal_count": int(
            (
                pd.to_datetime(bull.latest_source_timestamp)
                > pd.to_datetime(bull.decision_at)
            ).sum()
        ),
        "bull_non_bull_route_count": int(bull.market_regime.ne("BULL").sum()),
        "bull_setup_not_before_signal_count": int(
            bull.setup_cal_idx.ge(bull.cal_idx).sum()
        ),
        "bull_trigger_after_five_sessions_count": int(
            bull.cal_idx.sub(bull.setup_cal_idx).gt(5).sum()
        ),
        "bull_signal_close_breakout_violation_count": int(
            bull.coord_close.le(bull.setup_high_coord).sum()
        ),
        "bull_earlier_strict_tick_breakout_count": int(earlier_strict_tick_breakout),
        "bull_missing_rank_input_count": int(
            bull[["impulse3", "pre_impulse_ret60"]].isna().any(axis=1).sum()
        ),
    }


def execution_lineage_audit(accepted: pd.DataFrame) -> dict[str, Any]:
    bear = pd.read_parquet(BEAR)[["event_id", "signal_invalid"]].rename(
        columns={"signal_invalid": "lineage"}
    )
    bull = duckdb.sql(
        f"SELECT event_id,invalid_step_cum AS lineage FROM read_parquet('{BULL_FEATURES.as_posix()}')"
    ).df()
    lineage = pd.concat([bear, bull], ignore_index=True)
    trades = accepted.merge(lineage, on="event_id", how="left", validate="one_to_one")
    connection = duckdb.connect()
    connection.register(
        "trades",
        trades[
            [
                "event_id",
                "symbol",
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "exit_reason",
                "lineage",
            ]
        ],
    )
    execution = connection.execute(
        f"""
        SELECT t.*,
          e.coord_open AS entry_open,e.open AS entry_raw_open,
          e.up_limit_price,e.trade_status AS entry_status,
          e.current_day_data_tradable AS entry_tradable,
          e.market_rule_valid AS entry_rule,
          e.corporate_action_valid AS entry_action,
          e.corporate_action_blocking AS entry_block,e.hard_valid AS entry_hard,
          x.coord_open AS exit_open,x.open AS exit_raw_open,x.down_limit_price,
          x.coord_high AS exit_high,x.trade_status AS exit_status,
          x.current_day_data_tradable AS exit_tradable,
          x.market_rule_valid AS exit_rule,
          x.corporate_action_valid AS exit_action,
          x.corporate_action_blocking AS exit_block,x.hard_valid AS exit_hard,
          p.min_lineage,p.max_lineage,p.null_lineage
        FROM trades t
        JOIN read_parquet('{v13.DAILY.as_posix()}') e
          ON t.symbol=e.symbol AND CAST(t.entry_date AS DATE)=CAST(e.trade_date AS DATE)
        JOIN read_parquet('{v13.DAILY.as_posix()}') x
          ON t.symbol=x.symbol AND CAST(t.exit_date AS DATE)=CAST(x.trade_date AS DATE)
        JOIN (
          SELECT t2.event_id,MIN(d.invalid_step_cum) AS min_lineage,
            MAX(d.invalid_step_cum) AS max_lineage,
            SUM(CASE WHEN d.invalid_step_cum IS NULL THEN 1 ELSE 0 END) AS null_lineage
          FROM trades t2
          JOIN read_parquet('{v13.DAILY.as_posix()}') d
            ON t2.symbol=d.symbol
           AND CAST(d.trade_date AS DATE)
               BETWEEN CAST(t2.entry_date AS DATE) AND CAST(t2.exit_date AS DATE)
          GROUP BY t2.event_id
        ) p USING(event_id)
        """
    ).fetch_df()
    connection.close()
    entry_legal = (
        execution.entry_status.eq(1)
        & execution.entry_tradable
        & execution.entry_rule
        & execution.entry_action
        & ~execution.entry_block
        & execution.entry_hard
        & (np.round(execution.entry_raw_open * 100) < np.round(execution.up_limit_price * 100))
        & np.isclose(execution.entry_price, execution.entry_open)
    )
    exit_legal = (
        execution.exit_status.eq(1)
        & execution.exit_tradable
        & execution.exit_rule
        & execution.exit_action
        & ~execution.exit_block
        & execution.exit_hard
    )
    target = execution.exit_reason.eq("TARGET_10")
    target_legal = (
        exit_legal
        & execution.exit_high.ge(execution.exit_price - 1e-12)
        & np.isclose(execution.exit_price / execution.entry_price - 1.0, 0.10)
    )
    open_exit_legal = (
        exit_legal
        & (np.round(execution.exit_raw_open * 100) > np.round(execution.down_limit_price * 100))
        & np.isclose(execution.exit_price, execution.exit_open)
    )
    lineage_legal = (
        np.isclose(execution.min_lineage, execution.lineage)
        & np.isclose(execution.max_lineage, execution.lineage)
        & execution.null_lineage.eq(0)
    )
    return {
        "entry_execution_violation_count": int((~entry_legal).sum()),
        "target_execution_violation_count": int((target & ~target_legal).sum()),
        "open_exit_execution_violation_count": int((~target & ~open_exit_legal).sum()),
        "corporate_action_coordinate_lineage_violation_count": int(
            (~lineage_legal).sum()
        ),
    }


def main() -> None:
    for path in (BEAR, BULL, BULL_FEATURES, CONTRACT):
        if not path.is_file():
            raise ResearchError(f"missing input: {path}")
    if sha256(BEAR) != EXPECTED["bear"] or sha256(BULL) != EXPECTED["bull"]:
        raise ResearchError("frozen lane source drift")
    raw = load_lanes()
    accepted, skipped, capacity_audit = apply_shared_capacity(raw)
    accepted = accepted.sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    nav, portfolio_audit = v13.replay_portfolio(accepted)
    overall = v13.trade_metrics(accepted)
    overall["average_completed_trades_per_year"] = len(accepted) / 10.0
    annual = v13.annual_trade_metrics(accepted)
    lanes = {
        lane: v13.trade_metrics(part)
        for lane, part in accepted.groupby("lane", sort=True)
    }
    challenge = accepted.loc[accepted.signal_date.dt.year.ge(2021)]
    challenge_metrics = v13.trade_metrics(challenge)
    challenge_metrics["average_completed_trades_per_year"] = len(challenge) / 3.0
    post_2018_annual_positive = all(
        row["trades"] == 0 or row["mean_net"] > 0
        for row in annual
        if row["year"] >= 2019
    )
    gates = {
        "average_trades_per_year_gt_50": overall["average_completed_trades_per_year"] > 50,
        "mean_net_gt_3pct": overall["mean_net"] > 0.03,
        "average_holding_sessions_le_15": overall["average_holding_sessions"] <= 15,
        "post_2018_every_year_mean_positive": post_2018_annual_positive,
        "top5_positive_pnl_share_lt_50pct": overall["top5_positive_pnl_share"] < 0.50,
        "mean_excluding_best5_dates_positive": overall[
            "mean_excluding_best5_signal_dates"
        ]
        > 0,
    }
    audit = {
        **capacity_audit,
        **portfolio_audit,
        **causal_source_audit(accepted),
        **execution_lineage_audit(accepted),
        "event_id_duplicate_count": int(accepted.event_id.duplicated().sum()),
        "entry_at_or_before_signal_count": int(
            accepted.entry_date.le(accepted.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(
            accepted.exit_date.le(accepted.entry_date).sum()
        ),
        "t1_same_day_exit_count": int(accepted.exit_date.eq(accepted.entry_date).sum()),
        "true_duplicate_active_symbol_count": int(v13.true_overlap_count(accepted)),
        "post_2023_signal_count": int(accepted.signal_date.dt.year.gt(2023).sum()),
        "post_2023_exit_count": int(accepted.exit_date.dt.year.gt(2023).sum()),
        "repository_2024_plus_data_opened": False,
    }
    required_zero = [
        audit[key]
        for key in (
            "negative_cash_count",
            "open_position_at_end_count",
            "event_id_duplicate_count",
            "entry_at_or_before_signal_count",
            "exit_at_or_before_entry_count",
            "t1_same_day_exit_count",
            "true_duplicate_active_symbol_count",
            "post_2023_signal_count",
            "post_2023_exit_count",
            "bear_missing_rank_input_count",
            "bear_prior10_gate_violation_count",
            "bear_breadth_repair_violation_count",
            "bull_available_after_signal_count",
            "bull_regime_after_signal_count",
            "bull_non_bull_route_count",
            "bull_setup_not_before_signal_count",
            "bull_trigger_after_five_sessions_count",
            "bull_signal_close_breakout_violation_count",
            "bull_earlier_strict_tick_breakout_count",
            "bull_missing_rank_input_count",
            "entry_execution_violation_count",
            "target_execution_violation_count",
            "open_exit_execution_violation_count",
            "corporate_action_coordinate_lineage_violation_count",
        )
    ]
    required_zero.extend(audit["bear_timestamp_after_signal_count_by_field"].values())
    if any(required_zero):
        raise ResearchError(f"combined audit failed: {audit}")
    verdict = (
        "DUAL_REGIME_HISTORICAL_TRADE_LEVEL_GOAL_MET"
        if all(gates.values())
        else "DUAL_REGIME_HISTORICAL_GOAL_NOT_MET"
    )
    OUT.mkdir(parents=True, exist_ok=True)
    accepted_path = OUT / "accepted_trades.parquet"
    skipped_path = OUT / "skipped_trades.parquet"
    nav_path = OUT / "portfolio_nav.parquet"
    write_parquet(accepted, accepted_path)
    write_parquet(skipped, skipped_path)
    write_parquet(nav, nav_path)
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "routing": {
            "BULL": "V15 delayed supply-contraction T10/H20",
            "BEAR": "V13R1 fast-capitulation active-demand T10/H20",
            "TRANSITION": "HOLD_CASH",
        },
        "overall": overall,
        "lanes": lanes,
        "challenge_2021_2023": challenge_metrics,
        "annual": annual,
        "portfolio": v13.nav_metrics(nav),
        "annual_portfolio": v13.annual_nav_metrics(nav),
        "gates": gates,
        "audit": audit,
        "contract_sha256": sha256(CONTRACT),
        "source_hashes": {"bear": sha256(BEAR), "bull": sha256(BULL)},
    }
    result_path = OUT / "result.json"
    write_json(result_path, result)
    write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (accepted_path, skipped_path, nav_path, result_path)
        },
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
