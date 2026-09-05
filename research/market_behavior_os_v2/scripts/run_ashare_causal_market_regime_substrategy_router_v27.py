#!/usr/bin/env python3
"""Causally route four frozen short-horizon mechanisms by market substate.

No security outcome is reconstructed here.  The runner consumes frozen outcome
ledgers, selects one bounded slow-Bear gate using 2014-2020 only, and reports
already-observed 2021-2023 separately.  Market state is joined at the signal
close and must have a source timestamp no later than that close decision.
"""

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

EXPERIMENT = "ASHARE-CAUSAL-MARKET-REGIME-SUBSTRATEGY-ROUTER-V27"
REPO = Path(__file__).resolve().parents[3]
OS_ROOT = REPO / "research/market_behavior_os_v2"
CONTRACT = OS_ROOT / f"experiments/{EXPERIMENT}_contract.json"
CONTRACT_SHA256 = "8fdaf43e7d0f44cb5607fb1a37d4a12fefbf43cb1ededf334bc5bf474f0a20a7"

ROOT = Path("/Volumes/quant/CY_quant_research")
OUT = ROOT / "ashare_causal_market_regime_substrategy_router_v27"
CACHE = OUT / "source_cache"
FAST = (
    ROOT
    / "ashare_bear_fast_capitulation_active_demand_short_ranking_v13r1"
    / "selected_accepted_trades.parquet"
)
BULL = (
    ROOT
    / "ashare_bull_delayed_supply_contraction_short_repricing_v15"
    / "selected_profile_trades.parquet"
)
BULL_FEATURES = (
    ROOT
    / "ashare_demand_impulse_inside_day_delayed_breakout_v5/stage_a"
    / "candidates_frozen.parquet"
)
SLOW_DEV_OUTCOMES = (
    ROOT
    / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
    / "development_2014_2020_outcomes.parquet"
)
SLOW_DEV_CANDIDATES = (
    ROOT
    / "ashare_distributed_accumulation_slow_exhaustion_mother_screen_v1"
    / "development_2014_2020_candidates.parquet"
)
QUIET_DEV = (
    ROOT
    / "ashare_causal_bear_bull_dual_engine_lane_specific_acceptance_v19r2"
    / "development_2014_2020_outcomes.parquet"
)
REGIME = (
    ROOT
    / "ashare_causal_market_regime_routed_simple_strategy_v1/stage_a"
    / "causal_market_regime_2014_2023.parquet"
)
DAILY = (
    ROOT
    / "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1"
    / "pit_daily_compact_2013_2023.parquet"
)

SLOW_2021_OUTCOMES = CACHE / "slow_outcomes_2021.parquet"
SLOW_2021_CANDIDATES = CACHE / "slow_candidates_2021.parquet"
SLOW_2022_2023_OUTCOMES = CACHE / "slow_outcomes_2022_2023.parquet"
SLOW_2022_2023_CANDIDATES = CACHE / "slow_candidates_2022_2023.parquet"
QUIET_2021 = CACHE / "quiet_outcomes_2021.parquet"
QUIET_2022_2023 = CACHE / "quiet_outcomes_2022_2023.parquet"

EXPECTED_HASHES = {
    "contract": CONTRACT_SHA256,
    "fast": "8e62f4b3a9552cac769e95eb6e172ec65e8d53af207cccb06a60c6ad21ca8140",
    "bull": "08fdec7808d6c462519f0d87cc63a3367543a4277da0a452b0b169ba3edaa883",
    "bull_features": "492be15a5ee8c2623587a89f2239f15584bec3f134ac4659f619dfa1278e3fff",
    "slow_dev_outcomes": "8e410688aba5f07f1a36c87bd0e061c8d052fe6d2b051656b59970589320285d",
    "slow_dev_candidates": "7c08a9ed2090fd1b9b27ee0068ed2c438b8583fc876872bc0523d5e00f5ab364",
    "slow_2021_outcomes": "081713b1a1f02f997356ee793e295ece6657d36d3238c34e4f5c3d48b2c0c0a7",
    "slow_2021_candidates": "66135de9a65b427bbba2f3c0094f8b7f1d019316a7d437440e097255cc372430",
    "slow_2022_2023_outcomes": "d71afdb8e4df17e133e9f51c987addf97367f23fe59f6135b19c6a3fae183ef3",
    "slow_2022_2023_candidates": "834f3b6fea29fe3fda85ff10ee6081c1a2880222006d2afad05e930e7f6ca54a",
    "quiet_dev": "53d552de91a87b31eb3a81c16d5acd00a44e89c10e95fc31edcf71af7e2e60fe",
    "quiet_2021": "deb4af98cd1dfc2cfe0b4f43299431c8ecc032e7654581f31f4a6a4622538711",
    "quiet_2022_2023": "d5d716be2e319f0be68cc5b91b5184a5491b35219e2198c5f9f049331fe3a0ef",
    "regime": "5f56af1a7650c5a4d4a885ee1b6e75496a2cb0d7449621801b299a1ccd931c0a",
    "daily": "53c9e1e62b4b1bbd45979c868f5543eea58114d0bf659f866cd37d979068cc00",
}

SELECTION_END = pd.Timestamp("2020-12-31")
CHALLENGE_START = pd.Timestamp("2021-01-01")
K_PER_SLEEVE = 75
DAILY_ENTRY_CAP = 20


class ResearchError(RuntimeError):
    """Fail closed on identity, chronology, routing, or replay drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_parquet(path: Path, columns: list[str] | None = None) -> pd.DataFrame:
    select = "*" if columns is None else ",".join(columns)
    return duckdb.sql(
        f"SELECT {select} FROM read_parquet('{path.as_posix()}')"
    ).df()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        + "\n",
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


def verify_inputs() -> dict[str, str]:
    paths = {
        "contract": CONTRACT,
        "fast": FAST,
        "bull": BULL,
        "bull_features": BULL_FEATURES,
        "slow_dev_outcomes": SLOW_DEV_OUTCOMES,
        "slow_dev_candidates": SLOW_DEV_CANDIDATES,
        "slow_2021_outcomes": SLOW_2021_OUTCOMES,
        "slow_2021_candidates": SLOW_2021_CANDIDATES,
        "slow_2022_2023_outcomes": SLOW_2022_2023_OUTCOMES,
        "slow_2022_2023_candidates": SLOW_2022_2023_CANDIDATES,
        "quiet_dev": QUIET_DEV,
        "quiet_2021": QUIET_2021,
        "quiet_2022_2023": QUIET_2022_2023,
        "regime": REGIME,
        "daily": DAILY,
    }
    actual: dict[str, str] = {}
    for name, path in paths.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        actual[name] = sha256(path)
        if actual[name] != EXPECTED_HASHES[name]:
            raise ResearchError(
                f"frozen input drift for {name}: {actual[name]} != {EXPECTED_HASHES[name]}"
            )
    return actual


def normalize_dates(frame: pd.DataFrame) -> pd.DataFrame:
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column]).dt.normalize()
    return frame


def market_panel() -> pd.DataFrame:
    columns = [
        "trade_date",
        "market_regime",
        "market_median_ret20",
        "market_median_ret60",
        "market_positive_ret20_share",
        "market_positive_ret60_share",
        "latest_source_timestamp",
    ]
    panel = read_parquet(REGIME, columns)
    panel["trade_date"] = pd.to_datetime(panel.trade_date).dt.normalize()
    panel["latest_source_timestamp"] = pd.to_datetime(panel.latest_source_timestamp)
    return panel


def attach_market(frame: pd.DataFrame, expected_regime: str) -> pd.DataFrame:
    panel = market_panel()
    overlapping = [
        column for column in panel.columns if column != "trade_date" and column in frame
    ]
    if "trade_date" in frame:
        overlapping.append("trade_date")
    routed = frame.drop(columns=overlapping).merge(
        panel,
        left_on="signal_date",
        right_on="trade_date",
        how="left",
        validate="many_to_one",
    ).drop(columns="trade_date")
    required = [
        "market_regime",
        "market_median_ret20",
        "market_median_ret60",
        "latest_source_timestamp",
    ]
    if routed[required].isna().any(axis=None):
        raise ResearchError("missing causal market-state field")
    if routed.market_regime.ne(expected_regime).any():
        raise ResearchError(f"source lane is not entirely {expected_regime}")
    return routed


def standard_columns(frame: pd.DataFrame) -> pd.DataFrame:
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
        "holding_sessions",
        "gross_return",
        "net_return",
        "lane",
        "rank1",
        "rank2",
        "rank3",
        "market_regime",
        "market_median_ret20",
        "market_median_ret60",
        "latest_source_timestamp",
    ]
    return frame[columns].copy()


def load_fast() -> pd.DataFrame:
    frame = normalize_dates(read_parquet(FAST))
    frame = frame.loc[frame.signal_date.dt.year.between(2014, 2023)].copy()
    frame = attach_market(frame, "BEAR")
    frame = frame.loc[
        frame.market_median_ret20.lt(frame.market_median_ret60)
    ].copy()
    frame["lane"] = "BEAR_WORSENING_FAST_CAPITULATION"
    frame["rank1"] = frame.stock_minus_industry_ret20
    frame["rank2"] = frame.close_vs_prior10_high
    frame["rank3"] = frame.close_location_x_f
    return standard_columns(frame)


def load_bull_accelerating() -> pd.DataFrame:
    frame = normalize_dates(read_parquet(BULL))
    frame = frame.loc[
        frame.status.eq("COMPLETED") & frame.signal_date.dt.year.between(2014, 2023)
    ].copy()
    features = read_parquet(
        BULL_FEATURES, ["event_id", "impulse3", "pre_impulse_ret60"]
    )
    frame = frame.merge(features, on="event_id", how="left", validate="one_to_one")
    frame = attach_market(frame, "BULL")
    frame = frame.loc[
        frame.market_median_ret20.ge(frame.market_median_ret60)
    ].copy()
    frame["lane"] = "BULL_ACCELERATING_DELAYED_SUPPLY_CONTRACTION"
    frame["rank1"] = frame.impulse3
    frame["rank2"] = -frame.pre_impulse_ret60
    frame["rank3"] = 0.0
    return standard_columns(frame)


def merge_slow_pair(outcome_path: Path, candidate_path: Path) -> pd.DataFrame:
    outcomes = normalize_dates(read_parquet(outcome_path))
    outcomes = outcomes.loc[
        outcomes.status.eq("COMPLETED")
        & outcomes.mechanism.eq("SLOW_SUPPLY_EXHAUSTION_TAKEOVER")
        & outcomes.market_regime.eq("BEAR")
    ].copy()
    feature_columns = [
        "event_id",
        "decision_at",
        "available_at",
        "market_latest_source_timestamp",
        "last5_downside_turnover",
        "previous5_downside_turnover",
        "exact_prior20_return",
        "close_location",
    ]
    candidates = read_parquet(candidate_path, feature_columns)
    return outcomes.merge(candidates, on="event_id", how="left", validate="one_to_one")


def load_slow_base() -> pd.DataFrame:
    frame = pd.concat(
        [
            merge_slow_pair(SLOW_DEV_OUTCOMES, SLOW_DEV_CANDIDATES),
            merge_slow_pair(SLOW_2021_OUTCOMES, SLOW_2021_CANDIDATES),
            merge_slow_pair(
                SLOW_2022_2023_OUTCOMES, SLOW_2022_2023_CANDIDATES
            ),
        ],
        ignore_index=True,
    )
    frame = frame.loc[frame.signal_date.dt.year.between(2014, 2023)].copy()
    frame = attach_market(frame, "BEAR")
    frame = frame.loc[
        frame.market_median_ret20.ge(frame.market_median_ret60)
    ].copy()
    for column in ("decision_at", "available_at", "market_latest_source_timestamp"):
        frame[column] = pd.to_datetime(frame[column])
    return frame


def load_quiet_decelerating() -> pd.DataFrame:
    development = normalize_dates(read_parquet(QUIET_DEV))
    challenge_2021 = normalize_dates(read_parquet(QUIET_2021))
    challenge_2022_2023 = normalize_dates(read_parquet(QUIET_2022_2023))
    frame = pd.concat(
        [development, challenge_2021, challenge_2022_2023], ignore_index=True
    )
    frame = frame.loc[
        frame.engine.eq("BULL_CONTINUATION")
        & frame.status.eq("COMPLETED")
        & frame.signal_date.dt.year.between(2014, 2023)
    ].copy()
    frame = frame.rename(columns={"chart_event_id": "event_id"})
    frame = attach_market(frame, "BULL")
    frame = frame.loc[
        frame.market_median_ret20.lt(frame.market_median_ret60)
    ].copy()
    frame["lane"] = "BULL_DECELERATING_QUIET_INVENTORY"
    frame["rank1"] = frame.confirmation_close_to_structure
    frame["rank2"] = frame.signal_coord_close / frame.structural_level - 1.0
    frame["rank3"] = 0.0
    if frame.entry_cal_idx.le(frame.confirmation_cal_idx).any():
        raise ResearchError("quiet-inventory entry does not follow confirmation")
    return standard_columns(frame)


def slow_candidate_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    deep_market = frame.market_median_ret60.le(-0.05)
    deep_stock = frame.exact_prior20_return.le(-0.15)
    low_recent_selling = frame.last5_downside_turnover.le(0.01)
    return {
        "NO_ADDITIONAL_GATE": pd.Series(True, index=frame.index),
        "DEEP_MARKET_REQUIRES_DEEP_STOCK_15": ~deep_market | deep_stock,
        "DEEP_MARKET_REQUIRES_LOW_LAST5_DOWNSIDE_TURNOVER_1PCT": (
            ~deep_market | low_recent_selling
        ),
        "DEEP_MARKET_REQUIRES_BOTH": (
            ~deep_market | (deep_stock & low_recent_selling)
        ),
        "DEEP_MARKET_REQUIRES_EITHER": (
            ~deep_market | (deep_stock | low_recent_selling)
        ),
    }


def concentration(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "signal_dates": 0,
            "symbols": 0,
            "top5_signal_date_share": None,
            "top10_symbol_share": None,
            "signal_date_equal_mean": None,
            "mean_excluding_best5_signal_dates": None,
        }
    date_counts = frame.signal_date.value_counts()
    symbol_counts = frame.symbol.value_counts()
    date_returns = frame.groupby("signal_date", sort=True).net_return.mean()
    best_dates = set(date_returns.nlargest(min(5, len(date_returns))).index)
    remainder = frame.loc[~frame.signal_date.isin(best_dates), "net_return"]
    return {
        "signal_dates": int(frame.signal_date.nunique()),
        "symbols": int(frame.symbol.nunique()),
        "top5_signal_date_share": float(date_counts.head(5).sum() / len(frame)),
        "top10_symbol_share": float(symbol_counts.head(10).sum() / len(frame)),
        "signal_date_equal_mean": float(date_returns.mean()),
        "mean_excluding_best5_signal_dates": (
            None if remainder.empty else float(remainder.mean())
        ),
    }


def trade_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    values = pd.to_numeric(frame.net_return, errors="coerce")
    payload = {
        "trades": len(frame),
        "mean_net": None if frame.empty else float(values.mean()),
        "median_net": None if frame.empty else float(values.median()),
        "win_rate": None if frame.empty else float(values.gt(0).mean()),
        "severe10": None if frame.empty else float(values.le(-0.10).mean()),
        "target_hit": (
            None if frame.empty else float(frame.exit_reason.str.startswith("TARGET_").mean())
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


def evaluate_slow_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    development = frame.loc[frame.signal_date.le(SELECTION_END)].copy()
    rows: list[dict[str, Any]] = []
    condition_counts = {
        "NO_ADDITIONAL_GATE": 0,
        "DEEP_MARKET_REQUIRES_DEEP_STOCK_15": 1,
        "DEEP_MARKET_REQUIRES_LOW_LAST5_DOWNSIDE_TURNOVER_1PCT": 1,
        "DEEP_MARKET_REQUIRES_BOTH": 2,
        "DEEP_MARKET_REQUIRES_EITHER": 1,
    }
    for name, mask in slow_candidate_masks(development).items():
        part = development.loc[mask]
        metrics = trade_metrics(part)
        annual_means = [
            part.loc[part.signal_date.dt.year.eq(year), "net_return"].mean()
            for year in range(2014, 2021)
        ]
        positive_years = int(sum(value > 0 for value in annual_means))
        eligible = len(part) >= 500 and positive_years >= 6
        rows.append(
            {
                "candidate": name,
                "development_trades": len(part),
                "development_mean_net": metrics["mean_net"],
                "development_median_net": metrics["median_net"],
                "development_signal_date_equal_mean": metrics[
                    "signal_date_equal_mean"
                ],
                "development_severe10": metrics["severe10"],
                "positive_development_years": positive_years,
                "additional_condition_count": condition_counts[name],
                "eligible": eligible,
            }
        )
    table = pd.DataFrame(rows)
    eligible = table.loc[table.eligible].sort_values(
        [
            "development_mean_net",
            "development_signal_date_equal_mean",
            "development_severe10",
            "additional_condition_count",
            "candidate",
        ],
        ascending=[False, False, True, True, True],
        kind="mergesort",
    )
    if eligible.empty:
        raise ResearchError("no bounded slow-Bear candidate is deployment eligible")
    table["selected"] = table.candidate.eq(str(eligible.iloc[0].candidate))
    return table.sort_values("candidate", kind="mergesort").reset_index(drop=True)


def select_slow(frame: pd.DataFrame, candidate: str) -> pd.DataFrame:
    mask = slow_candidate_masks(frame)[candidate]
    selected = frame.loc[mask].copy()
    selected["lane"] = "BEAR_STABILIZING_SLOW_SUPPLY_EXHAUSTION"
    selected["rank1"] = (
        selected.previous5_downside_turnover - selected.last5_downside_turnover
    )
    selected["rank2"] = -selected.exact_prior20_return
    selected["rank3"] = selected.close_location
    return standard_columns(selected)


def release_before_open(active: dict[str, Any], entry_date: pd.Timestamp) -> list[str]:
    released: list[str] = []
    for symbol, row in list(active.items()):
        open_exit = not str(row.exit_reason).startswith("TARGET_")
        if row.exit_date < entry_date or (row.exit_date == entry_date and open_exit):
            del active[symbol]
            released.append(symbol)
    return released


def apply_shared_capacity(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    missing = frame[["rank1", "rank2", "rank3"]].isna().any(axis=1)
    if missing.any():
        raise ResearchError("missing required shared-capacity rank input")
    ordered = frame.sort_values(
        ["entry_date", "sleeve", "rank1", "rank2", "rank3", "event_id"],
        ascending=[True, True, False, False, False, True],
        kind="mergesort",
    )
    active: dict[str, dict[str, Any]] = {"MAIN": {}, "CHINEXT": {}}
    accepted_ids: list[str] = []
    reasons: dict[str, str] = {}
    max_active = 0
    for entry_date, day in ordered.groupby("entry_date", sort=True):
        for sleeve in active:
            release_before_open(active[sleeve], entry_date)
        for sleeve, cohort in day.groupby("sleeve", sort=True):
            accepted_today = 0
            for row in cohort.itertuples(index=False):
                reason = None
                if row.symbol in active[sleeve]:
                    reason = "ACTIVE_SYMBOL"
                elif len(active[sleeve]) >= K_PER_SLEEVE:
                    reason = "K75_ACTIVE_CAP"
                elif accepted_today >= DAILY_ENTRY_CAP:
                    reason = "DAILY_ENTRY_CAP_20"
                if reason is not None:
                    reasons[str(row.event_id)] = reason
                    continue
                accepted_ids.append(str(row.event_id))
                active[sleeve][str(row.symbol)] = row
                accepted_today += 1
        max_active = max(max_active, *(len(values) for values in active.values()))
    chosen = ordered.loc[ordered.event_id.isin(accepted_ids)].copy()
    chosen["capacity_status"] = "ACCEPTED"
    chosen["skip_reason"] = None
    skipped = ordered.loc[~ordered.event_id.isin(accepted_ids)].copy()
    skipped["capacity_status"] = "SKIPPED"
    skipped["skip_reason"] = skipped.event_id.map(reasons)
    return chosen, skipped, {
        "raw_trade_count": len(frame),
        "accepted_trade_count": len(chosen),
        "capacity_skip_count": len(skipped),
        "max_active_during_selection": int(max_active),
        "capacity_skip_reasons": {
            str(key): int(value)
            for key, value in skipped.skip_reason.value_counts().sort_index().items()
        },
    }


def generic_overlap_count(frame: pd.DataFrame) -> int:
    compatible = frame.copy()
    compatible["exit_reason"] = np.where(
        compatible.exit_reason.str.startswith("TARGET_"),
        "TARGET_10",
        compatible.exit_reason,
    )
    return v13.true_overlap_count(compatible)


def replay_portfolio(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    compatible = frame.copy()
    compatible["exit_reason"] = np.where(
        compatible.exit_reason.str.startswith("TARGET_"),
        "TARGET_10",
        compatible.exit_reason,
    )
    return v13.replay_portfolio(compatible)


def attach_signal_decisions(frame: pd.DataFrame) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "events", frame[["event_id", "symbol", "signal_date"]]
    )
    decisions = connection.execute(
        f"""
        SELECT e.event_id,d.decision_at,d.available_at AS signal_available_at
        FROM events e
        JOIN read_parquet('{DAILY.as_posix()}') d
          ON e.symbol=d.symbol AND CAST(e.signal_date AS DATE)=CAST(d.trade_date AS DATE)
        """
    ).fetch_df()
    connection.close()
    decisions["decision_at"] = pd.to_datetime(decisions.decision_at)
    decisions["signal_available_at"] = pd.to_datetime(decisions.signal_available_at)
    return frame.merge(decisions, on="event_id", how="left", validate="one_to_one")


def execution_audit(frame: pd.DataFrame) -> dict[str, int]:
    connection = duckdb.connect()
    connection.register(
        "trades",
        frame[
            [
                "event_id",
                "symbol",
                "entry_date",
                "exit_date",
                "entry_price",
                "exit_price",
                "exit_reason",
            ]
        ],
    )
    execution = connection.execute(
        f"""
        SELECT t.*,
          e.coord_open AS entry_open,e.open AS entry_raw_open,
          e.up_limit_price AS entry_up_limit,e.trade_status AS entry_status,
          e.current_day_data_tradable AS entry_tradable,
          e.market_rule_valid AS entry_rule,e.corporate_action_valid AS entry_action,
          e.corporate_action_blocking AS entry_block,e.hard_valid AS entry_hard,
          x.coord_open AS exit_open,x.open AS exit_raw_open,x.coord_high AS exit_high,
          x.down_limit_price AS exit_down_limit,x.trade_status AS exit_status,
          x.current_day_data_tradable AS exit_tradable,
          x.market_rule_valid AS exit_rule,x.corporate_action_valid AS exit_action,
          x.corporate_action_blocking AS exit_block,x.hard_valid AS exit_hard,
          p.min_lineage,p.max_lineage,p.null_lineage
        FROM trades t
        JOIN read_parquet('{DAILY.as_posix()}') e
          ON t.symbol=e.symbol AND CAST(t.entry_date AS DATE)=CAST(e.trade_date AS DATE)
        JOIN read_parquet('{DAILY.as_posix()}') x
          ON t.symbol=x.symbol AND CAST(t.exit_date AS DATE)=CAST(x.trade_date AS DATE)
        JOIN (
          SELECT t2.event_id,MIN(d.invalid_step_cum) AS min_lineage,
            MAX(d.invalid_step_cum) AS max_lineage,
            SUM(CASE WHEN d.invalid_step_cum IS NULL THEN 1 ELSE 0 END) AS null_lineage
          FROM trades t2
          JOIN read_parquet('{DAILY.as_posix()}') d
            ON t2.symbol=d.symbol
           AND CAST(d.trade_date AS DATE)
               BETWEEN CAST(t2.entry_date AS DATE) AND CAST(t2.exit_date AS DATE)
          GROUP BY t2.event_id
        ) p USING(event_id)
        """
    ).fetch_df()
    connection.close()
    if len(execution) != len(frame):
        raise ResearchError("entry/exit execution audit join is not one-to-one")
    entry_legal = (
        execution.entry_status.eq(1)
        & execution.entry_tradable
        & execution.entry_rule
        & execution.entry_action
        & ~execution.entry_block
        & execution.entry_hard
        & np.isfinite(execution.entry_raw_open)
        & np.isfinite(execution.entry_open)
        & (np.round(execution.entry_raw_open * 100) < np.round(execution.entry_up_limit * 100))
        & np.isclose(execution.entry_price, execution.entry_open)
    )
    common_exit_legal = (
        execution.exit_status.eq(1)
        & execution.exit_tradable
        & execution.exit_rule
        & execution.exit_action
        & ~execution.exit_block
        & execution.exit_hard
    )
    is_target = execution.exit_reason.str.startswith("TARGET_")
    target_legal = common_exit_legal & execution.exit_high.ge(execution.exit_price)
    open_exit_legal = (
        common_exit_legal
        & (np.round(execution.exit_raw_open * 100) > np.round(execution.exit_down_limit * 100))
        & np.isclose(execution.exit_price, execution.exit_open)
    )
    lineage_legal = (
        execution.null_lineage.eq(0)
        & execution.min_lineage.eq(execution.max_lineage)
    )
    return {
        "entry_execution_violation_count": int((~entry_legal).sum()),
        "target_execution_violation_count": int((is_target & ~target_legal).sum()),
        "open_exit_execution_violation_count": int((~is_target & ~open_exit_legal).sum()),
        "corporate_action_coordinate_lineage_violation_count": int(
            (~lineage_legal).sum()
        ),
    }


def causal_audit(
    raw: pd.DataFrame,
    accepted: pd.DataFrame,
    slow_base: pd.DataFrame,
    candidate_table: pd.DataFrame,
    capacity_audit: dict[str, Any],
    portfolio_audit: dict[str, Any],
) -> dict[str, Any]:
    timed = attach_signal_decisions(raw)
    selected_candidate = str(candidate_table.loc[candidate_table.selected, "candidate"].iloc[0])
    return {
        **capacity_audit,
        **portfolio_audit,
        **execution_audit(accepted),
        "selected_candidate": selected_candidate,
        "challenge_rows_used_for_candidate_selection_count": 0,
        "candidate_selection_latest_date": str(SELECTION_END.date()),
        "post_2023_signal_count": int(raw.signal_date.dt.year.gt(2023).sum()),
        "post_2023_exit_count": int(raw.exit_date.dt.year.gt(2023).sum()),
        "missing_signal_decision_count": int(timed.decision_at.isna().sum()),
        "signal_available_after_decision_count": int(
            timed.signal_available_at.gt(timed.decision_at).sum()
        ),
        "market_state_after_signal_decision_count": int(
            pd.to_datetime(timed.latest_source_timestamp).gt(timed.decision_at).sum()
        ),
        "slow_feature_available_after_decision_count": int(
            slow_base.available_at.gt(slow_base.decision_at).sum()
        ),
        "slow_market_state_after_decision_count": int(
            slow_base.market_latest_source_timestamp.gt(slow_base.decision_at).sum()
        ),
        "event_id_duplicate_count": int(raw.event_id.duplicated().sum()),
        "same_symbol_signal_date_duplicate_count": int(
            raw.duplicated(["symbol", "signal_date"]).sum()
        ),
        "entry_at_or_before_signal_count": int(
            raw.entry_date.le(raw.signal_date).sum()
        ),
        "exit_at_or_before_entry_count": int(raw.exit_date.le(raw.entry_date).sum()),
        "t1_same_day_exit_count": int(raw.exit_date.eq(raw.entry_date).sum()),
        "true_duplicate_active_symbol_count": int(generic_overlap_count(accepted)),
        "rank_missing_count": int(raw[["rank1", "rank2", "rank3"]].isna().any(axis=1).sum()),
        "repository_2024_plus_security_rows_included": False,
        "security_outcome_reconstruction_run": False,
    }


def annual_metrics(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "year": year,
            **trade_metrics(frame.loc[frame.signal_date.dt.year.eq(year)]),
        }
        for year in range(2014, 2024)
    ]


def run() -> dict[str, Any]:
    source_hashes = verify_inputs()
    slow_base = load_slow_base()
    candidate_table = evaluate_slow_candidates(slow_base)
    selected_candidate = str(
        candidate_table.loc[candidate_table.selected, "candidate"].iloc[0]
    )
    expected_candidate = "DEEP_MARKET_REQUIRES_EITHER"
    if selected_candidate != expected_candidate:
        raise ResearchError(
            f"bounded 2014-2020 candidate selection drift: {selected_candidate}"
        )

    raw = pd.concat(
        [
            load_fast(),
            select_slow(slow_base, selected_candidate),
            load_bull_accelerating(),
            load_quiet_decelerating(),
        ],
        ignore_index=True,
    )
    raw = raw.sort_values(
        ["signal_date", "sleeve", "symbol", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    if raw.event_id.duplicated().any() or raw.duplicated(
        ["symbol", "signal_date"]
    ).any():
        raise ResearchError("cross-mechanism duplicate identity")

    accepted, skipped, capacity_audit = apply_shared_capacity(raw)
    accepted = accepted.sort_values(
        ["entry_date", "sleeve", "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    nav, portfolio_audit = replay_portfolio(accepted)
    audit = causal_audit(
        raw,
        accepted,
        slow_base,
        candidate_table,
        capacity_audit,
        portfolio_audit,
    )
    required_zero = [
        "challenge_rows_used_for_candidate_selection_count",
        "post_2023_signal_count",
        "post_2023_exit_count",
        "missing_signal_decision_count",
        "signal_available_after_decision_count",
        "market_state_after_signal_decision_count",
        "slow_feature_available_after_decision_count",
        "slow_market_state_after_decision_count",
        "event_id_duplicate_count",
        "same_symbol_signal_date_duplicate_count",
        "entry_at_or_before_signal_count",
        "exit_at_or_before_entry_count",
        "t1_same_day_exit_count",
        "true_duplicate_active_symbol_count",
        "rank_missing_count",
        "entry_execution_violation_count",
        "target_execution_violation_count",
        "open_exit_execution_violation_count",
        "corporate_action_coordinate_lineage_violation_count",
        "negative_cash_count",
        "open_position_at_end_count",
    ]
    if any(int(audit[name]) != 0 for name in required_zero):
        raise ResearchError(f"causal/execution audit failed: {audit}")

    overall = trade_metrics(accepted)
    overall["average_completed_trades_per_year"] = len(accepted) / 10.0
    challenge = accepted.loc[accepted.signal_date.ge(CHALLENGE_START)]
    challenge_metrics = trade_metrics(challenge)
    challenge_metrics["average_completed_trades_per_year"] = len(challenge) / 3.0
    annual = annual_metrics(accepted)
    annual_map = {row["year"]: row for row in annual}
    development = accepted.loc[accepted.signal_date.le(SELECTION_END)]
    development_metrics = trade_metrics(development)
    lanes = {
        str(name): trade_metrics(part)
        for name, part in accepted.groupby("lane", sort=True)
    }
    gates = {
        "average_trades_per_year_gt_50": overall[
            "average_completed_trades_per_year"
        ]
        > 50,
        "pooled_mean_net_gt_3pct": overall["mean_net"] > 0.03,
        "average_holding_sessions_le_15": overall["average_holding_sessions"] <= 15,
        "every_calendar_year_mean_positive": all(
            annual_map[year]["mean_net"] > 0 for year in range(2014, 2024)
        ),
        "2021_mean_net_gt_3pct": annual_map[2021]["mean_net"] > 0.03,
        "2022_mean_net_gt_3pct": annual_map[2022]["mean_net"] > 0.03,
        "2023_mean_net_gt_3pct": annual_map[2023]["mean_net"] > 0.03,
        "challenge_mean_net_gt_3pct": challenge_metrics["mean_net"] > 0.03,
        "mean_excluding_best5_dates_positive": overall[
            "mean_excluding_best5_signal_dates"
        ]
        > 0,
    }
    verdict = (
        "CAUSAL_MARKET_REGIME_SUBSTRATEGY_ROUTER_HISTORICAL_GOAL_MET"
        if all(gates.values())
        else "CAUSAL_MARKET_REGIME_SUBSTRATEGY_ROUTER_GOAL_NOT_MET"
    )

    OUT.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "raw": OUT / "routed_raw_trades.parquet",
        "accepted": OUT / "accepted_trades.parquet",
        "skipped": OUT / "capacity_skipped_trades.parquet",
        "candidate_table": OUT / "slow_bear_candidate_table.parquet",
        "nav": OUT / "portfolio_nav.parquet",
    }
    write_parquet(raw, artifacts["raw"])
    write_parquet(accepted, artifacts["accepted"])
    write_parquet(skipped, artifacts["skipped"])
    write_parquet(candidate_table, artifacts["candidate_table"])
    write_parquet(nav, artifacts["nav"])
    result = {
        "experiment": EXPERIMENT,
        "verdict": verdict,
        "selected_slow_bear_gate": selected_candidate,
        "routing": {
            "BEAR_WORSENING": "V13R1 fast capitulation active demand T10/H20",
            "BEAR_STABILIZING_MILD": "slow supply exhaustion T10/H20",
            "BEAR_STABILIZING_DEEP": (
                "slow supply exhaustion T10/H20 only when "
                "exact_prior20_return <= -0.15 OR last5_downside_turnover <= 0.01"
            ),
            "BULL_ACCELERATING": "V15 delayed supply contraction T10/H20",
            "BULL_DECELERATING": "V19R2 quiet inventory continuation T15/H15",
            "TRANSITION": "HOLD_CASH",
        },
        "development_2014_2020": development_metrics,
        "post_observation_challenge_2021_2023": challenge_metrics,
        "overall_2014_2023": overall,
        "annual": annual,
        "lanes": lanes,
        "portfolio": v13.nav_metrics(nav),
        "annual_portfolio": v13.annual_nav_metrics(nav),
        "slow_bear_candidate_table": candidate_table.to_dict("records"),
        "gates": gates,
        "audit": audit,
        "contract_sha256": source_hashes["contract"],
        "source_hashes": source_hashes,
        "post_observation_warning": (
            "2021-2023 are useful chronological diagnostics but are not pristine "
            "validation because predecessor outcomes were already observed."
        ),
    }
    result_path = OUT / "result.json"
    write_json(result_path, result)
    write_json(
        OUT / "artifact_hashes.json",
        {
            path.name: {"bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in (*artifacts.values(), result_path)
        },
    )
    return result


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
