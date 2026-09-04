#!/usr/bin/env python3
# ruff: noqa: E501
"""Causality/execution repair replay for the frozen V4 early-repair rule.

This runner does not alter V4 alpha semantics.  It repairs three implementation
defects discovered after the V4 diagnostic: inconsistent Development/diagnostic
signal constructors, a V6-subset legal-open dependency, and silent omission of
executable entries without a completed outcome.  2022-2023 is explicitly a
post-observation corrected diagnostic.  Data after a signal-period boundary may
be read only to execute or close a position whose signal was already formed;
post-boundary rows can never create signals, features, rules, or thresholds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_strategy_development_v1 as qd010,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4 as v4,
)

v1 = v4.v1
source = v1.source
base = v1.base

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4R1-CAUSAL-REPLAY"
START_HEAD = "8b5d70fc5b57746139861bd1af3a01849505ac2a"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_early_repair_v4r1_causal_replay"
)
CY006_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
MECHANICAL_AMENDMENT = OS / f"artifacts/{EXPERIMENT}_mechanical_amendment_001.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
INVALIDATION = OS / "artifacts/ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4_final_challenge_invalidation.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

COST = 0.002
MIN_RECOVERY = 0.03
TARGET_FRACTION = 0.80
TIME_STOP = 20
PORTFOLIO_K = 20
DEVELOPMENT_YEARS = (2017, 2018, 2019, 2020, 2021)
DIAGNOSTIC_YEARS = (2022, 2023)
PERIODS = {
    "DEVELOPMENT": (
        pd.Timestamp("2021-12-31"),
        pd.Timestamp("2022-03-31"),
        DEVELOPMENT_YEARS,
    ),
    "POST_OBSERVATION_DIAGNOSTIC": (
        pd.Timestamp("2023-12-31"),
        pd.Timestamp("2024-03-31"),
        DIAGNOSTIC_YEARS,
    ),
}


class ReplayRepairError(RuntimeError):
    """Fail-closed error for the corrected V4 replay."""


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    frame.to_parquet(tmp, index=False, compression="zstd")
    tmp.replace(path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def period_root(label: str) -> Path:
    return EXT_ROOT / label.lower()


def paths(label: str) -> dict[str, Path]:
    root = period_root(label)
    return {
        "root": root,
        "candidates": root / "direct_first_ma5_candidates.parquet",
        "signals": root / "signals.parquet",
        "actions": root / "qd010_actions.parquet",
        "action_registry": root / "action_registry_symbols.parquet",
        "entry_seed": root / "entry_seed.parquet",
        "execution_state": root / "execution_state.parquet",
        "entries": root / "entries.parquet",
        "outcome_daily": root / "outcome_daily.parquet",
        "sell_opens": root / "sell_opens.parquet",
        "outcome_bounds": root / "outcome_bounds.parquet",
        "outcome_minutes": root / "outcome_minutes.parquet",
        "outcomes": root / "outcomes.parquet",
        "portfolio_nav": root / "portfolio_nav.parquet",
    }


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "IMPLEMENTATION_CORRECTION_REPLAY_NOT_NEW_ALPHA",
        "source_v4_contract_sha256": sha256(v4.CONTRACT),
        "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
        "source_v4_result_sha256": sha256(v4.VALIDATION_RESULT),
        "repository_2024_plus": "SIGNAL_AND_SELECTION_SEALED; AUTHORIZED_OUTCOME_TAIL_ONLY",
        "development": ["2017-01-01", "2021-12-31"],
        "post_observation_diagnostic": ["2022-01-01", "2023-12-31"],
        "frozen_rule": {
            "true_gap": "High_t < Low_t_minus_1",
            "minimum_gap_width_pct": 0.01,
            "pre_gap_vap": "exact 120 sessions x 241 minutes",
            "inside_density_max": 1.0,
            "corridor_density_max": 1.0,
            "pre_gap_return_20d_max": 0.0,
            "maximum_post_gap_depth_min": 0.10,
            "signal_depth_below_L_min": 0.05,
            "recent_low_age_sessions": [2, 10],
            "minimum_recovery": MIN_RECOVERY,
            "trigger": "first completed daily MA5 reclaim",
            "minimum_net_headroom_to_L": 0.05,
            "entry": "first buyable 1-minute open strictly after signal",
            "target": "entry + 0.80*(L-entry)",
            "failure_stop": "NONE",
            "time_stop": "H20 close information then next sellable 1-minute open",
            "costs": {"entry": COST, "exit": COST},
            "portfolio": "50/50 Main/ChiNext; K20 per sleeve",
        },
        "repairs": {
            "signal_constructor": "direct first-MA5 constructor in both periods",
            "execution_coverage": "period-local full selected-symbol buy/sell opens",
            "buy_limit": "buy open must be strictly below authoritative upper limit",
            "sell_limit": "sell open must be strictly above authoritative lower limit",
            "outcome_tail": "follow every pre-cutoff signal through H20 and its next legal exit, including later calendar data",
            "outcome_conservation": "every evaluation-eligible executable entry must have exactly one outcome",
            "lineage_break": "target disabled after lineage break; raw-share H20/risk exit remains mandatory",
            "corporate_actions": "authoritative QD-010 known-at pre-effective risk exit and cash entitlement",
        },
        "non_changes": [
            "no threshold change",
            "no feature addition",
            "no target or holding change",
            "no board deletion",
            "no model",
            "no 2024+ signal, feature, selection, threshold, or new-entry research",
        ],
        "authorized_tail_boundaries": {
            "Development_2021_signal_cohort": "outcomes/execution only through 2022-03-31",
            "Diagnostic_2023_signal_cohort": "outcomes/execution only through 2024-03-31",
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    contract_hash = sha256(CONTRACT)
    spec = {
        "experiment": EXPERIMENT,
        "contract_sha256": contract_hash,
        "freeze_status": "BEFORE_CORRECTED_OUTCOME_OPEN",
        "old_v4_economics_status": "INVALIDATED_BY_IMPLEMENTATION_AUDIT",
        "interpretation": (
            "This replay may determine whether the unchanged V4 hypothesis survives "
            "implementation correction. It cannot restore pristine status to 2022-2023."
        ),
        "post_cutoff_tail_authorization": (
            "User explicitly authorized later data when needed to complete a trade. "
            "Such data are restricted to entry/exit/trading-state resolution for "
            "signals already formed no later than each frozen signal_end."
        ),
        "post_cutoff_signal_feature_selection_use": "PROHIBITED",
        "success_target": {
            "mean_net_each_period_min": 0.03,
            "median_net_each_period_positive": True,
            "annual_evaluation_entries_target_range": [40, 80],
            "severe_loss10_max": 0.15,
        },
    }
    write_json(SPEC, spec)
    return {"contract_sha256": contract_hash, "spec_sha256": sha256(SPEC)}


def fixed_signal_mask(frame: pd.DataFrame) -> pd.Series:
    return v4.fixed_signal_mask(frame)


def build_actions(symbols: list[str], end: pd.Timestamp, output: Path, registry: Path) -> pd.DataFrame:
    registry_frame = pd.DataFrame(
        {"symbol": sorted(set(symbols)), "raw_symbol": [x.split(".")[0] for x in sorted(set(symbols))]}
    )
    write_parquet(registry_frame, registry)
    con = duckdb.connect()
    con.register("registry", registry_frame)
    distributions = con.execute(
        f"""
        SELECT r.symbol,a.event_id,
          CASE WHEN coalesce(a.share_multiplier,1)>1 THEN 'RISK_SHARE' ELSE 'CASH_ONLY' END AS action_kind,
          CAST(a.known_at AS DATE) AS known_date,CAST(a.effective_date AS DATE) AS effective_date,
          coalesce(a.cash_per_share_gross,0)::DOUBLE AS cash_per_share,
          coalesce(a.share_multiplier,1)::DOUBLE AS share_multiplier,
          a.source_terms_complete
        FROM read_parquet('{qd010.QD010_DISTRIBUTIONS}') a
        JOIN registry r ON r.raw_symbol=a.symbol
        WHERE a.effective_date BETWEEN DATE '2014-01-01' AND DATE '{end:%Y-%m-%d}'
        """
    ).fetchdf()
    rights = con.execute(
        f"""
        SELECT r.symbol,a.event_id,'RISK_RIGHTS' AS action_kind,
          CAST(a.known_at AS DATE) AS known_date,CAST(a.effective_date AS DATE) AS effective_date,
          0.0::DOUBLE AS cash_per_share,1.0::DOUBLE AS share_multiplier,
          a.source_terms_complete
        FROM read_parquet('{qd010.QD010_RIGHTS}') a
        JOIN registry r ON r.raw_symbol=a.symbol
        WHERE a.effective_date BETWEEN DATE '2014-01-01' AND DATE '{end:%Y-%m-%d}'
        """
    ).fetchdf()
    con.close()
    actions = pd.concat([distributions, rights], ignore_index=True)
    if actions.empty:
        actions = pd.DataFrame(
            columns=[
                "symbol", "event_id", "action_kind", "known_date", "effective_date",
                "cash_per_share", "share_multiplier", "source_terms_complete",
            ]
        )
    for column in ("known_date", "effective_date"):
        actions[column] = pd.to_datetime(actions[column])
    actions = actions.sort_values(
        ["symbol", "known_date", "effective_date", "event_id"], kind="mergesort"
    ).drop_duplicates(["symbol", "event_id", "action_kind"], keep="last")
    if len(actions):
        if actions[["known_date", "effective_date"]].isna().any().any():
            raise ReplayRepairError("QD-010 missing known/effective timestamp")
        if (~actions.source_terms_complete.fillna(False)).any():
            raise ReplayRepairError("QD-010 incomplete source terms")
        if actions.known_date.ge(actions.effective_date).any():
            raise ReplayRepairError("QD-010 non-causal known/effective ordering")
    write_parquet(actions, output)
    return actions


def cy006_path(year: int) -> Path:
    return CY006_DAILY_ROOT / f"partition_year={year}" / "data_0.parquet"


def build_global_calendar(start: pd.Timestamp, tail_end: pd.Timestamp) -> pd.DataFrame:
    """Build the market-session clock without reading post-cutoff security returns."""
    con = duckdb.connect()
    old_end = min(pd.Timestamp(tail_end), pd.Timestamp("2023-12-31"))
    old = con.execute(
        f"""
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date,cal_idx::BIGINT AS cal_idx
        FROM read_parquet('{source.DAILY}')
        WHERE trade_date BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{old_end:%Y-%m-%d}'
        ORDER BY trade_date
        """
    ).fetchdf()
    con.close()
    old["trade_date"] = pd.to_datetime(old.trade_date)
    pieces = [old]
    next_idx = int(old.cal_idx.max()) + 1 if len(old) else 0
    for year in range(max(2024, int(start.year)), int(tail_end.year) + 1):
        path = cy006_path(year)
        if not path.is_file():
            raise ReplayRepairError(f"missing authorized outcome-tail daily partition: {path}")
        con = duckdb.connect()
        dates = con.execute(
            f"""
            SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date
            FROM read_parquet('{path}')
            WHERE trade_date BETWEEN DATE '{max(start, pd.Timestamp(f'{year}-01-01')):%Y-%m-%d}'
              AND DATE '{min(tail_end, pd.Timestamp(f'{year}-12-31')):%Y-%m-%d}'
            ORDER BY trade_date
            """
        ).fetchdf()
        con.close()
        dates["trade_date"] = pd.to_datetime(dates.trade_date)
        dates["cal_idx"] = np.arange(next_idx, next_idx + len(dates), dtype=np.int64)
        next_idx += len(dates)
        pieces.append(dates)
    calendar = pd.concat(pieces, ignore_index=True)
    calendar = calendar.loc[
        calendar.trade_date.between(pd.Timestamp(start), pd.Timestamp(tail_end))
    ].sort_values("trade_date", kind="mergesort")
    if calendar.empty or calendar.trade_date.duplicated().any() or calendar.cal_idx.duplicated().any():
        raise ReplayRepairError("global outcome-tail calendar identity failure")
    if not calendar.cal_idx.diff().dropna().eq(1).all():
        raise ReplayRepairError("global outcome-tail calendar is not contiguous")
    return calendar.reset_index(drop=True)


def build_execution_state(
    symbols: list[str],
    start: pd.Timestamp,
    tail_end: pd.Timestamp,
    output: Path,
) -> pd.DataFrame:
    """Build selected-symbol legal-execution state; omit post-cutoff OHLC returns."""
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    calendar = build_global_calendar(start, tail_end)
    con = duckdb.connect()
    con.register("registry", registry)
    old_end = min(pd.Timestamp(tail_end), pd.Timestamp("2023-12-31"))
    old = con.execute(
        f"""
        SELECT d.trade_date,d.cal_idx,d.symbol,d.sleeve,d.coordinate_factor,
          d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
          d.trade_status,d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_blocking,d.up_limit_price,d.down_limit_price,
          FALSE AS coordinate_lineage_carried
        FROM read_parquet('{source.DAILY}') d
        JOIN registry r USING(symbol)
        WHERE d.trade_date BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{old_end:%Y-%m-%d}'
        ORDER BY d.symbol,d.trade_date
        """
    ).fetchdf()
    con.close()
    old["trade_date"] = pd.to_datetime(old.trade_date)
    pieces = [old]
    if tail_end > pd.Timestamp("2023-12-31"):
        con = duckdb.connect()
        con.register("registry", registry)
        carry = con.execute(
            f"""
            SELECT d.symbol,d.sleeve,d.coordinate_factor,d.invalid_step_cum
            FROM read_parquet('{source.DAILY}') d
            JOIN registry r USING(symbol)
            QUALIFY row_number() OVER(PARTITION BY d.symbol ORDER BY d.trade_date DESC)=1
            """
        ).fetchdf()
        con.close()
        if set(registry.symbol) - set(carry.symbol):
            raise ReplayRepairError("selected symbol lacks pre-2024 coordinate lineage")
        for year in range(2024, int(tail_end.year) + 1):
            path = cy006_path(year)
            con = duckdb.connect()
            con.register("registry", registry)
            tail = con.execute(
                f"""
                SELECT d.trade_date,d.symbol,d.hard_valid,d.trade_status,
                  d.current_day_data_tradable,d.market_rule_valid,
                  d.corporate_action_blocking,d.up_limit_price,d.down_limit_price
                FROM read_parquet('{path}') d
                JOIN registry r USING(symbol)
                WHERE d.trade_date BETWEEN DATE '{max(pd.Timestamp(f'{year}-01-01'), pd.Timestamp('2024-01-01')):%Y-%m-%d}'
                  AND DATE '{min(tail_end, pd.Timestamp(f'{year}-12-31')):%Y-%m-%d}'
                ORDER BY d.symbol,d.trade_date
                """
            ).fetchdf()
            con.close()
            if tail.empty:
                continue
            tail["trade_date"] = pd.to_datetime(tail.trade_date)
            tail = tail.merge(calendar, on="trade_date", how="left", validate="many_to_one")
            tail = tail.merge(carry, on="symbol", how="left", validate="many_to_one")
            tail["history_valid"] = tail.hard_valid.fillna(False)
            tail["current_valid"] = tail.hard_valid.fillna(False)
            tail["coordinate_lineage_carried"] = True
            tail = tail[
                [
                    "trade_date", "cal_idx", "symbol", "sleeve", "coordinate_factor",
                    "invalid_step_cum", "history_valid", "current_valid", "hard_valid",
                    "trade_status", "current_day_data_tradable", "market_rule_valid",
                    "corporate_action_blocking", "up_limit_price", "down_limit_price",
                    "coordinate_lineage_carried",
                ]
            ]
            pieces.append(tail)
    state = pd.concat(pieces, ignore_index=True).sort_values(
        ["symbol", "trade_date"], kind="mergesort"
    )
    if state.empty or state.duplicated(["symbol", "trade_date"]).any():
        raise ReplayRepairError("execution-state identity failure")
    if set(symbols) - set(state.symbol.astype(str)):
        raise ReplayRepairError("selected symbol absent from execution state")
    write_parquet(state, output)
    return state


def build_buy_entries(
    selected: pd.DataFrame,
    actions: pd.DataFrame,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    output_paths: dict[str, Path],
) -> pd.DataFrame:
    seed = selected[
        ["gap_id", "symbol", "signal_time", "signal_date", "invalid_step_cum", "L"]
    ].copy()
    write_parquet(seed, output_paths["entry_seed"])
    pieces: list[pd.DataFrame] = []
    first_year = int(pd.to_datetime(seed.signal_date).dt.year.min())
    first_columns = [
        "gap_id", "symbol", "trade_date", "bar_end_time", "entry_raw_price",
        "entry_cal_idx", "entry_coordinate_factor", "entry_invalid_step_cum",
        "up_limit_price",
    ]
    remaining = seed.copy()
    for year in range(first_year, int(tail_end.year) + 1):
        if remaining.empty:
            break
        raw = source.raw_path(year)
        if not raw.is_file():
            raise ReplayRepairError(f"missing raw minute partition needed for entry: {raw}")
        con = duckdb.connect()
        con.register("remaining_seed", remaining)
        candidate = con.execute(
            f"""
            SELECT s.gap_id,s.symbol,r.trade_date,r.bar_end_time,r.open AS entry_raw_price,
              d.cal_idx AS entry_cal_idx,d.coordinate_factor AS entry_coordinate_factor,
              d.invalid_step_cum AS entry_invalid_step_cum,d.up_limit_price,
              row_number() OVER(PARTITION BY s.gap_id ORDER BY r.bar_end_time) AS candidate_order
            FROM remaining_seed s
            JOIN read_parquet('{source.raw_path(year)}') r
              ON r.qmt_code=s.symbol AND r.bar_end_time>s.signal_time
            JOIN read_parquet('{output_paths['execution_state']}') d
              ON d.symbol=s.symbol AND d.trade_date=r.trade_date
            WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
              AND r.trade_date<=DATE '{tail_end:%Y-%m-%d}'
              AND d.invalid_step_cum=s.invalid_step_cum
              AND d.history_valid AND d.current_valid AND d.hard_valid
              AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid
              AND NOT d.corporate_action_blocking
              AND isfinite(r.open) AND r.open>0
              AND round(r.open*100)<round(d.up_limit_price*100)
            QUALIFY candidate_order=1
            """
        ).fetchdf()
        con.close()
        if len(candidate):
            candidate = candidate.drop(columns="candidate_order")
            pieces.append(candidate)
            remaining = remaining.loc[
                ~remaining.gap_id.isin(candidate.gap_id.astype(str))
            ].copy()
    first = (
        pd.concat(pieces, ignore_index=True)
        .sort_values(["gap_id", "bar_end_time"], kind="mergesort")
        .drop_duplicates("gap_id", keep="first")
        if pieces
        else pd.DataFrame(columns=first_columns)
    )
    entries = selected.merge(first, on=["gap_id", "symbol"], how="left", validate="one_to_one")
    for column in ("signal_time", "signal_date", "trade_date", "bar_end_time"):
        if column in entries:
            entries[column] = pd.to_datetime(entries[column])
    entries = entries.rename(columns={"trade_date": "entry_date", "bar_end_time": "entry_time"})
    entries["entry_coordinate_price"] = entries.entry_raw_price * entries.entry_coordinate_factor
    entries["realized_net_l_headroom"] = (
        (entries.L / entries.entry_coordinate_price) * (1 - COST) / (1 + COST) - 1
    )
    entries["entry_status"] = np.where(
        entries.entry_time.isna(), "NO_NEXT_BUYABLE_OPEN", "EXECUTABLE_ENTRY"
    )
    action_groups = {
        key: part.sort_values(["known_date", "effective_date"], kind="mergesort")
        for key, part in actions.groupby("symbol", sort=False)
    }
    for index, row in entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].iterrows():
        act = action_groups.get(str(row.symbol), pd.DataFrame(columns=actions.columns))
        effective_between = act.loc[
            act.effective_date.gt(pd.Timestamp(row.signal_date).normalize())
            & act.effective_date.le(pd.Timestamp(row.entry_date).normalize())
        ]
        pending_risk = act.loc[
            act.action_kind.astype(str).str.startswith("RISK")
            & act.known_date.le(pd.Timestamp(row.entry_date).normalize())
            & act.effective_date.gt(pd.Timestamp(row.entry_date).normalize())
        ]
        if not effective_between.empty or not pending_risk.empty:
            entries.at[index, "entry_status"] = "RISK_BLOCKED_ENTRY"
        elif float(row.realized_net_l_headroom) < 0.05:
            entries.at[index, "entry_status"] = "INSUFFICIENT_L_HEADROOM"
    entries["entry_at_or_before_signal"] = (
        entries.entry_time.notna() & entries.entry_time.le(entries.signal_time)
    )
    entries["entry_after_signal_period_boundary"] = (
        entries.entry_time.notna() & entries.entry_date.gt(pd.Timestamp(signal_end))
    )
    entries["buy_at_or_above_up_limit"] = (
        entries.entry_time.notna()
        & (np.rint(entries.entry_raw_price * 100) >= np.rint(entries.up_limit_price * 100))
    )
    if entries.entry_at_or_before_signal.any() or entries.buy_at_or_above_up_limit.any():
        raise ReplayRepairError("entry causality/upper-limit failure")
    if entries.gap_id.duplicated().any() or len(entries) != len(selected):
        raise ReplayRepairError("entry identity conservation failure")
    write_parquet(entries, output_paths["entries"])
    return entries


def prepare_period_stage_a(
    label: str,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    years: tuple[int, ...],
) -> dict[str, Any]:
    output_paths = paths(label)
    output_paths["root"].mkdir(parents=True, exist_ok=True)
    daily = v1.load_daily(signal_end)
    gaps = core.build_all_true_gaps(daily)
    candidates = core.build_ma5_signal_candidates(daily, gaps)
    candidates = candidates.loc[pd.to_datetime(candidates.signal_date).dt.year.isin(years)].copy()
    candidates = candidates.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort")
    if candidates.empty or candidates.gap_id.duplicated().any():
        raise ReplayRepairError(f"{label} direct candidate identity failure")
    write_parquet(candidates, output_paths["candidates"])
    v1.configure_external(output_paths["root"], signal_end)
    vap, _profiles = v1.build_vap_for_signals(candidates, daily)
    panel = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    selected = panel.loc[fixed_signal_mask(panel)].copy()
    selected["signal_year"] = pd.to_datetime(selected.signal_date).dt.year
    selected["decision_latest_timestamp"] = pd.to_datetime(selected.signal_time)
    selected["feature_uses_post_signal_information"] = False
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty:
        raise ReplayRepairError(f"{label} selected signal population empty")
    write_parquet(selected, output_paths["signals"])
    actions = build_actions(
        selected.symbol.drop_duplicates().tolist(), tail_end, output_paths["actions"], output_paths["action_registry"]
    )
    execution_state = build_execution_state(
        selected.symbol.drop_duplicates().tolist(),
        pd.Timestamp(selected.signal_date.min()).normalize(),
        tail_end,
        output_paths["execution_state"],
    )
    entries = build_buy_entries(selected, actions, signal_end, tail_end, output_paths)
    selected_symbols = set(selected.symbol.astype(str))
    registered_symbols = set(pd.read_parquet(output_paths["action_registry"]).symbol.astype(str))
    if selected_symbols != registered_symbols:
        raise ReplayRepairError(f"{label} selected-symbol execution registry mismatch")
    return {
        "signal_end": str(signal_end.date()),
        "outcome_tail_end": str(tail_end.date()),
        "years": list(years),
        "direct_first_ma5_candidates": len(candidates),
        "selected_signals": len(selected),
        "selected_symbols": len(selected_symbols),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "evaluation_eligible_entries": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "entry_after_signal_period_boundary_count": int(
            entries.entry_after_signal_period_boundary.sum()
        ),
        "post_cutoff_signal_count": int(
            pd.to_datetime(selected.signal_date).gt(signal_end).sum()
        ),
        "missing_execution_registry_symbols": 0,
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "execution_state_rows": len(execution_state),
        "hashes": {
            "candidates": sha256(output_paths["candidates"]),
            "signals": sha256(output_paths["signals"]),
            "actions": sha256(output_paths["actions"]),
            "action_registry": sha256(output_paths["action_registry"]),
            "execution_state": sha256(output_paths["execution_state"]),
            "entries": sha256(output_paths["entries"]),
            "vap_metrics": sha256(output_paths["root"] / "vap_metrics.parquet"),
        },
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods: dict[str, Any] = {}
    for label, (signal_end, tail_end, years) in PERIODS.items():
        periods[label] = prepare_period_stage_a(label, signal_end, tail_end, years)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_CORRECTION_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_v4_contract_sha256": sha256(v4.CONTRACT),
        "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
        "periods": periods,
        "old_v4_outcomes_used_to_change_rule": False,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "post_cutoff_signal_or_selection_data_opened": "NO",
        "authorized_outcome_tail_opened": "YES",
        "repository_2024_plus_data_opened": "YES_AUTHORIZED_TRADE_RESOLUTION_ONLY",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ReplayRepairError("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "source_v4_contract_sha256": sha256(v4.CONTRACT),
        "pre_result_mechanical_amendment_sha256": sha256(MECHANICAL_AMENDMENT),
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    for label in PERIODS:
        current = {
            "candidates": sha256(paths(label)["candidates"]),
            "signals": sha256(paths(label)["signals"]),
            "actions": sha256(paths(label)["actions"]),
            "action_registry": sha256(paths(label)["action_registry"]),
            "execution_state": sha256(paths(label)["execution_state"]),
            "entries": sha256(paths(label)["entries"]),
            "vap_metrics": sha256(paths(label)["root"] / "vap_metrics.parquet"),
        }
        expected = freeze["periods"][label]["hashes"]
        if current != expected:
            drift[f"{label}_artifacts"] = [expected, current]
    if drift:
        raise ReplayRepairError(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks, "outcomes_opened": "NO"}


def build_outcome_daily(
    entries: pd.DataFrame,
    signal_start: pd.Timestamp,
    tail_end: pd.Timestamp,
    output_paths: dict[str, Path],
) -> pd.DataFrame:
    """Attach OHLC only after Stage A, for frozen pre-cutoff trade resolution."""
    eligible_symbols = sorted(
        entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "symbol"]
        .astype(str)
        .unique()
    )
    if not eligible_symbols:
        raise ReplayRepairError("no executable entries for outcome daily")
    registry = pd.DataFrame({"symbol": eligible_symbols})
    con = duckdb.connect()
    con.register("registry", registry)
    old_end = min(pd.Timestamp(tail_end), pd.Timestamp("2023-12-31"))
    old = con.execute(
        f"""
        SELECT e.*,d.open,d.high,d.low,d.close,
          d.open*e.coordinate_factor AS coord_open,
          d.high*e.coordinate_factor AS coord_high,
          d.low*e.coordinate_factor AS coord_low,
          d.close*e.coordinate_factor AS coord_close
        FROM read_parquet('{output_paths['execution_state']}') e
        JOIN registry r USING(symbol)
        JOIN read_parquet('{source.DAILY}') d USING(symbol,trade_date)
        WHERE e.trade_date BETWEEN DATE '{signal_start:%Y-%m-%d}' AND DATE '{old_end:%Y-%m-%d}'
        ORDER BY e.symbol,e.trade_date
        """
    ).fetchdf()
    con.close()
    pieces = [old]
    for year in range(2024, int(tail_end.year) + 1):
        path = cy006_path(year)
        con = duckdb.connect()
        con.register("registry", registry)
        tail = con.execute(
            f"""
            SELECT e.*,d.open,d.high,d.low,d.close,
              d.open*e.coordinate_factor AS coord_open,
              d.high*e.coordinate_factor AS coord_high,
              d.low*e.coordinate_factor AS coord_low,
              d.close*e.coordinate_factor AS coord_close
            FROM read_parquet('{output_paths['execution_state']}') e
            JOIN registry r USING(symbol)
            JOIN read_parquet('{path}') d USING(symbol,trade_date)
            WHERE e.trade_date BETWEEN DATE '{max(pd.Timestamp(f'{year}-01-01'), pd.Timestamp('2024-01-01')):%Y-%m-%d}'
              AND DATE '{min(tail_end, pd.Timestamp(f'{year}-12-31')):%Y-%m-%d}'
            ORDER BY e.symbol,e.trade_date
            """
        ).fetchdf()
        con.close()
        if len(tail):
            pieces.append(tail)
    daily = pd.concat(pieces, ignore_index=True)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort")
    if daily.empty or daily.duplicated(["symbol", "trade_date"]).any():
        raise ReplayRepairError("outcome daily identity failure")
    calendar = build_global_calendar(signal_start, tail_end)
    observed_dates = set(daily.trade_date.unique())
    missing_dates = calendar.loc[~calendar.trade_date.isin(observed_dates)].copy()
    if len(missing_dates):
        sentinel = pd.DataFrame({column: np.nan for column in daily.columns}, index=range(len(missing_dates)))
        sentinel["trade_date"] = missing_dates.trade_date.to_numpy()
        sentinel["cal_idx"] = missing_dates.cal_idx.to_numpy()
        sentinel["symbol"] = "__CALENDAR__"
        sentinel["sleeve"] = "CALENDAR"
        daily = pd.concat([daily, sentinel], ignore_index=True)
    daily = daily.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)
    write_parquet(daily, output_paths["outcome_daily"])
    return daily


def build_sell_opens(
    entries: pd.DataFrame, tail_end: pd.Timestamp, output_paths: dict[str, Path]
) -> pd.DataFrame:
    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    symbols = pd.DataFrame({"symbol": sorted(eligible.symbol.astype(str).unique())})
    pieces: list[pd.DataFrame] = []
    first_year = int(pd.to_datetime(eligible.entry_date).dt.year.min())
    for year in range(first_year, int(tail_end.year) + 1):
        raw = source.raw_path(year)
        if not raw.is_file():
            raise ReplayRepairError(f"missing raw minute partition needed for exit: {raw}")
        con = duckdb.connect()
        con.register("symbols", symbols)
        frame = con.execute(
            f"""
            SELECT r.qmt_code AS symbol,r.trade_date,r.bar_end_time,r.open AS raw_open,
              d.cal_idx,d.coordinate_factor,d.invalid_step_cum,d.down_limit_price,
              row_number() OVER(PARTITION BY r.qmt_code,r.trade_date ORDER BY r.bar_end_time) AS sell_order
            FROM read_parquet('{source.raw_path(year)}') r
            JOIN symbols s ON s.symbol=r.qmt_code
            JOIN read_parquet('{output_paths['execution_state']}') d ON d.symbol=r.qmt_code AND d.trade_date=r.trade_date
            WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
              AND r.trade_date<=DATE '{tail_end:%Y-%m-%d}'
              AND d.history_valid AND d.current_valid AND d.hard_valid
              AND d.trade_status=1 AND d.current_day_data_tradable AND d.market_rule_valid
              AND NOT d.corporate_action_blocking
              AND isfinite(r.open) AND r.open>0
              AND round(r.open*100)>round(d.down_limit_price*100)
            QUALIFY sell_order=1
            ORDER BY symbol,bar_end_time
            """
        ).fetchdf()
        con.close()
        if len(frame):
            pieces.append(frame.drop(columns="sell_order"))
    result = (
        pd.concat(pieces, ignore_index=True).sort_values(
            ["symbol", "bar_end_time"], kind="mergesort"
        )
        if pieces
        else pd.DataFrame()
    )
    if result.empty:
        raise ReplayRepairError("sell-open population empty")
    for column in ("trade_date", "bar_end_time"):
        result[column] = pd.to_datetime(result[column])
    if set(eligible.symbol.astype(str)) - set(result.symbol.astype(str)):
        raise ReplayRepairError("eligible symbol missing from sell-open coverage")
    write_parquet(result, output_paths["sell_opens"])
    return result


def build_outcome_minutes(
    entries: pd.DataFrame,
    daily: pd.DataFrame,
    tail_end: pd.Timestamp,
    output_paths: dict[str, Path],
) -> pd.DataFrame:
    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    calendar = daily[["trade_date", "cal_idx"]].drop_duplicates("cal_idx").sort_values("cal_idx")
    by_idx = calendar.set_index("cal_idx").trade_date
    bounds = eligible[
        ["gap_id", "symbol", "entry_date", "entry_time", "entry_cal_idx"]
    ].copy()
    bounds["path_end_cal_idx"] = bounds.entry_cal_idx.astype(int) + TIME_STOP
    bounds["path_end_date"] = bounds.path_end_cal_idx.map(by_idx)
    if bounds.path_end_date.isna().any() or pd.to_datetime(bounds.path_end_date).max() > tail_end:
        raise ReplayRepairError("outcome bound exceeds authorized trade-resolution tail")
    write_parquet(bounds, output_paths["outcome_bounds"])
    pieces: list[pd.DataFrame] = []
    first_year = int(pd.to_datetime(bounds.entry_date).dt.year.min())
    for year in range(first_year, int(tail_end.year) + 1):
        raw = source.raw_path(year)
        if not raw.is_file():
            raise ReplayRepairError(f"missing raw minute partition needed for outcome: {raw}")
        con = duckdb.connect()
        frame = con.execute(
            f"""
            SELECT b.gap_id,b.symbol,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,
              d.cal_idx,d.coordinate_factor,d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,
              d.trade_status,d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
              d.up_limit_price,d.down_limit_price,
              r.open*d.coordinate_factor AS coord_open,r.high*d.coordinate_factor AS coord_high,
              r.low*d.coordinate_factor AS coord_low,r.close*d.coordinate_factor AS coord_close
            FROM read_parquet('{output_paths['outcome_bounds']}') b
            JOIN read_parquet('{source.raw_path(year)}') r
              ON r.qmt_code=b.symbol AND r.trade_date BETWEEN b.entry_date AND b.path_end_date
              AND r.bar_end_time>=b.entry_time
            JOIN read_parquet('{output_paths['outcome_daily']}') d ON d.symbol=b.symbol AND d.trade_date=r.trade_date
            WHERE r.period='1m' AND r.adjust='none' AND year(r.trade_date)={year}
              AND r.trade_date<=DATE '{tail_end:%Y-%m-%d}'
            ORDER BY b.gap_id,r.bar_end_time
            """
        ).fetchdf()
        con.close()
        if len(frame):
            pieces.append(frame)
    result = (
        pd.concat(pieces, ignore_index=True).sort_values(
            ["gap_id", "bar_end_time"], kind="mergesort"
        )
        if pieces
        else pd.DataFrame()
    )
    if result.empty:
        raise ReplayRepairError("outcome minute population empty")
    for column in ("trade_date", "bar_end_time"):
        result[column] = pd.to_datetime(result[column])
    if set(eligible.gap_id.astype(str)) - set(result.gap_id.astype(str)):
        raise ReplayRepairError("eligible entry missing outcome minute path")
    write_parquet(result, output_paths["outcome_minutes"])
    return result


def first_target(
    path: pd.DataFrame,
    entry: Any,
    target: float,
    first_action_effective: pd.Timestamp | None = None,
) -> dict[str, Any] | None:
    eligible = path.loc[
        path.bar_end_time.gt(pd.Timestamp(entry.entry_time))
        & path.cal_idx.gt(int(entry.entry_cal_idx))
        & path.cal_idx.le(int(entry.entry_cal_idx) + TIME_STOP)
        & path.invalid_step_cum.eq(float(entry.entry_invalid_step_cum))
        & path.hard_valid.eq(True)
        & path.trade_status.eq(1)
        & path.current_day_data_tradable.eq(True)
        & path.market_rule_valid.eq(True)
        & path.corporate_action_blocking.eq(False)
    ].copy()
    if first_action_effective is not None:
        eligible = eligible.loc[
            eligible.trade_date.lt(pd.Timestamp(first_action_effective).normalize())
        ]
    reached = source._raw_tick_reached(eligible.high, target, eligible.coordinate_factor)
    rows = eligible.loc[reached]
    if rows.empty:
        return None
    row = rows.iloc[0]
    raw_target = float(source._boundary_ticks(target, float(row.coordinate_factor))) / 100.0
    execution = max(float(row.open), raw_target)
    if int(source._price_ticks(execution)) > int(source._price_ticks(float(row.high))):
        raise ReplayRepairError(f"impossible target fill {entry.gap_id}")
    return {
        "exit_time": pd.Timestamp(row.bar_end_time),
        "exit_date": pd.Timestamp(row.trade_date),
        "exit_raw_price": execution,
        "exit_cal_idx": int(row.cal_idx),
        "exit_reason": "PRE_L_TARGET",
    }


def next_sell_open(sell: pd.DataFrame, trigger: pd.Timestamp, before: pd.Timestamp | None = None) -> dict[str, Any] | None:
    rows = sell.loc[sell.bar_end_time.gt(trigger)]
    if before is not None:
        rows = rows.loc[rows.trade_date.lt(before.normalize())]
    if rows.empty:
        return None
    row = rows.iloc[0]
    return {
        "exit_time": pd.Timestamp(row.bar_end_time),
        "exit_date": pd.Timestamp(row.trade_date),
        "exit_raw_price": float(row.raw_open),
        "exit_cal_idx": int(row.cal_idx),
        "exit_reason": "LEGAL_SELL_OPEN",
    }


def risk_exit(
    actions: pd.DataFrame,
    calendar: pd.DataFrame,
    sell: pd.DataFrame,
    signal_time: pd.Timestamp,
    entry_date: pd.Timestamp,
    cutoff: pd.Timestamp,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    risks = actions.loc[
        actions.action_kind.astype(str).str.startswith("RISK")
        & actions.known_date.gt(signal_time.normalize())
        & actions.known_date.le(cutoff.normalize())
        & actions.effective_date.gt(entry_date.normalize())
    ].sort_values(["known_date", "effective_date", "event_id"], kind="mergesort")
    candidates: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for action in risks.itertuples(index=False):
        decision_days = calendar.loc[
            calendar.trade_date.ge(pd.Timestamp(action.known_date))
            & calendar.trade_date.lt(pd.Timestamp(action.effective_date))
        ]
        if decision_days.empty:
            blocked.append({"event_id": action.event_id, "effective_date": pd.Timestamp(action.effective_date)})
            continue
        decision_time = pd.Timestamp(decision_days.trade_date.iloc[0]) + pd.Timedelta(hours=15)
        fill = next_sell_open(sell, decision_time, pd.Timestamp(action.effective_date))
        if fill is None:
            blocked.append({"event_id": action.event_id, "effective_date": pd.Timestamp(action.effective_date)})
            continue
        fill["exit_reason"] = "CORPORATE_ACTION_RISK"
        fill["event_id"] = action.event_id
        fill["effective_date"] = pd.Timestamp(action.effective_date)
        candidates.append(fill)
    chosen = None if not candidates else sorted(candidates, key=lambda x: (x["exit_time"], str(x["event_id"])))[0]
    first_blocked = None if not blocked else sorted(blocked, key=lambda x: (x["effective_date"], str(x["event_id"])))[0]
    return chosen, first_blocked


def cash_events(actions: pd.DataFrame, entry_date: pd.Timestamp, exit_date: pd.Timestamp) -> tuple[float, str]:
    rows = actions.loc[
        actions.action_kind.eq("CASH_ONLY")
        & actions.effective_date.gt(entry_date.normalize())
        & actions.effective_date.le(exit_date.normalize())
    ]
    payload = [
        {
            "date": str(pd.Timestamp(row.effective_date).date()),
            "cash_per_share": float(row.cash_per_share),
            "event_id": str(row.event_id),
        }
        for row in rows.itertuples(index=False)
    ]
    return float(rows.cash_per_share.sum()), json.dumps(payload, sort_keys=True)


def build_outcomes(
    entries: pd.DataFrame,
    daily: pd.DataFrame,
    minutes: pd.DataFrame,
    sell_opens: pd.DataFrame,
    actions: pd.DataFrame,
    tail_end: pd.Timestamp,
    output_paths: dict[str, Path],
) -> tuple[pd.DataFrame, dict[str, int]]:
    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    minute_by = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in minutes.groupby("gap_id", sort=False)}
    calendar = (
        daily[["trade_date", "cal_idx"]]
        .drop_duplicates("trade_date")
        .sort_values("cal_idx", kind="mergesort")
    )
    sell_by = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in sell_opens.groupby("symbol", sort=False)}
    action_by = {key: part.sort_values(["known_date", "effective_date"], kind="mergesort") for key, part in actions.groupby("symbol", sort=False)}
    rows: list[dict[str, Any]] = []
    audit = Counter()
    unresolved: list[str] = []
    for entry in eligible.itertuples(index=False):
        path = minute_by.get(str(entry.gap_id), pd.DataFrame())
        sell = sell_by.get(str(entry.symbol), pd.DataFrame(columns=sell_opens.columns))
        act = action_by.get(str(entry.symbol), pd.DataFrame(columns=actions.columns))
        if path.empty or sell.empty:
            unresolved.append(str(entry.gap_id))
            continue
        target_coordinate = float(entry.entry_coordinate_price) + TARGET_FRACTION * (
            float(entry.L) - float(entry.entry_coordinate_price)
        )
        if not target_coordinate < float(entry.L):
            raise ReplayRepairError("target is not strictly below L")
        later_actions = act.loc[
            act.effective_date.gt(pd.Timestamp(entry.entry_date).normalize())
        ].sort_values(["effective_date", "event_id"], kind="mergesort")
        first_action_effective = (
            None
            if later_actions.empty
            else pd.Timestamp(later_actions.effective_date.iloc[0])
        )
        target = first_target(
            path,
            entry,
            target_coordinate,
            first_action_effective=first_action_effective,
        )
        checkpoint_idx = int(entry.entry_cal_idx) + TIME_STOP
        checkpoint = calendar.loc[calendar.cal_idx.eq(checkpoint_idx)]
        if checkpoint.empty:
            unresolved.append(str(entry.gap_id))
            continue
        time_trigger = pd.Timestamp(checkpoint.trade_date.iloc[0]) + pd.Timedelta(hours=15)
        time_exit = next_sell_open(sell, time_trigger)
        if time_exit is not None:
            time_exit["exit_reason"] = "H20_TIME_STOP"
        risk, blocked = risk_exit(
            act,
            calendar,
            sell,
            pd.Timestamp(entry.signal_time),
            pd.Timestamp(entry.entry_date),
            time_trigger,
        )
        choices = [value for value in (target, risk, time_exit) if value is not None]
        chosen = None if not choices else sorted(
            choices,
            key=lambda x: (
                pd.Timestamp(x["exit_time"]),
                0 if x["exit_reason"] == "PRE_L_TARGET" else 1,
                x["exit_reason"],
            ),
        )[0]
        if blocked is not None and (
            chosen is None or pd.Timestamp(chosen["exit_time"]) >= pd.Timestamp(blocked["effective_date"])
        ):
            audit["unresolved_action_block_count"] += 1
            unresolved.append(str(entry.gap_id))
            continue
        if chosen is None or pd.Timestamp(chosen["exit_date"]) > tail_end:
            unresolved.append(str(entry.gap_id))
            continue
        exit_date = pd.Timestamp(chosen["exit_date"])
        cash, cash_json = cash_events(act, pd.Timestamp(entry.entry_date), exit_date)
        net = (
            (float(chosen["exit_raw_price"]) * (1 - COST) + cash)
            / (float(entry.entry_raw_price) * (1 + COST))
            - 1
        )
        lineage_break = bool(
            path.loc[path.bar_end_time.le(pd.Timestamp(chosen["exit_time"])), "invalid_step_cum"]
            .ne(float(entry.entry_invalid_step_cum))
            .any()
            or act.effective_date.between(
                pd.Timestamp(entry.entry_date).normalize() + pd.Timedelta(days=1),
                exit_date.normalize(),
            ).any()
        )
        if lineage_break:
            audit["lineage_break_carried_to_raw_exit_count"] += 1
        if int(chosen["exit_cal_idx"]) <= int(entry.entry_cal_idx):
            audit["t1_violation_count"] += 1
        rows.append(
            {
                **entry._asdict(),
                "alpha": TARGET_FRACTION,
                "horizon": TIME_STOP,
                "stop": "NONE",
                "target_coordinate": target_coordinate,
                "exit_time": pd.Timestamp(chosen["exit_time"]),
                "exit_date": exit_date,
                "exit_cal_idx": int(chosen["exit_cal_idx"]),
                "exit_raw_price": float(chosen["exit_raw_price"]),
                "exit_reason": chosen["exit_reason"],
                "net_return": net,
                "holding_sessions": int(chosen["exit_cal_idx"]) - int(entry.entry_cal_idx),
                "cash_events_json": cash_json,
                "lineage_break_before_exit": lineage_break,
            }
        )
    if unresolved:
        raise ReplayRepairError(
            f"executable-entry outcome conservation failed count={len(unresolved)} ids={unresolved[:20]}"
        )
    outcomes = pd.DataFrame(rows).sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort")
    if len(outcomes) != len(eligible) or set(outcomes.gap_id.astype(str)) != set(eligible.gap_id.astype(str)):
        raise ReplayRepairError("outcome identity conservation failure")
    if audit["t1_violation_count"]:
        raise ReplayRepairError(f"T+1 violation: {dict(audit)}")
    write_parquet(outcomes, output_paths["outcomes"])
    return outcomes, dict(audit)


def run_period_stage_b(
    label: str,
    signal_end: pd.Timestamp,
    tail_end: pd.Timestamp,
    years: tuple[int, ...],
) -> dict[str, Any]:
    output_paths = paths(label)
    entries = pd.read_parquet(output_paths["entries"])
    actions = pd.read_parquet(output_paths["actions"])
    for frame, columns in (
        (entries, ("signal_time", "signal_date", "entry_time", "entry_date")),
        (actions, ("known_date", "effective_date")),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])
    signal_start = pd.Timestamp(f"{min(years)}-01-01")
    daily = build_outcome_daily(entries, signal_start, tail_end, output_paths)
    sell_opens = build_sell_opens(entries, tail_end, output_paths)
    minutes = build_outcome_minutes(entries, daily, tail_end, output_paths)
    outcomes, outcome_audit = build_outcomes(
        entries, daily, minutes, sell_opens, actions, tail_end, output_paths
    )
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    portfolio_daily = daily.loc[daily.trade_date.le(max_exit)].copy()
    replay_years = tuple(range(min(years), int(max_exit.year) + 1))
    v1.configure_external(output_paths["root"], max_exit)
    portfolio = v1.run_portfolio(outcomes, portfolio_daily, replay_years)
    event_metrics = v1.trade_metrics(outcomes)
    combined = portfolio["COMBINED"]
    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    audit = {
        "selected_symbol_execution_coverage_missing_count": 0,
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "eligible_entry_without_outcome_count": int(len(eligible) - len(outcomes)),
        "outcome_without_eligible_entry_count": len(
            set(outcomes.gap_id.astype(str)) - set(eligible.gap_id.astype(str))
        ),
        "terminal_completeness_filter_count": 0,
        "t1_violation_count": int(outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()),
        "target_at_or_above_L_count": int(outcomes.target_coordinate.ge(outcomes.L).sum()),
        "unresolved_action_block_count": int(outcome_audit.get("unresolved_action_block_count", 0)),
        "lineage_break_carried_to_raw_exit_count": int(outcome_audit.get("lineage_break_carried_to_raw_exit_count", 0)),
        "max_k_violation_count": int(portfolio["audit"]["max_k_violation_count"]),
        "negative_cash_or_leverage_count": int(portfolio["audit"]["negative_cash_or_leverage_count"]),
        "post_cutoff_signal_count": int(pd.to_datetime(entries.signal_date).gt(signal_end).sum()),
        "post_cutoff_outcome_exit_count": int(pd.to_datetime(outcomes.exit_date).gt(signal_end).sum()),
        "repository_2024_plus_data_opened": (
            "YES_AUTHORIZED_TRADE_RESOLUTION_ONLY"
            if tail_end > pd.Timestamp("2023-12-31")
            else "NO"
        ),
    }
    nonblocking_counts = {
        "lineage_break_carried_to_raw_exit_count",
        "post_cutoff_outcome_exit_count",
    }
    blocking = {
        key: value
        for key, value in audit.items()
        if key.endswith("_count") and key not in nonblocking_counts and value
    }
    if blocking:
        raise ReplayRepairError(f"{label} blocking audit: {blocking}")
    return {
        "label": label,
        "signal_end": str(signal_end.date()),
        "authorized_outcome_tail_end": str(tail_end.date()),
        "maximum_exit_date_used": str(max_exit.date()),
        "selected_signals": len(entries),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "evaluation_eligible_entries": len(eligible),
        "complete_outcomes": len(outcomes),
        "annual_evaluation_entries": len(eligible) / len(years),
        "event_metrics": event_metrics,
        "portfolio": portfolio,
        "combined_mean_net": float(combined["mean_net"]),
        "combined_median_net": float(combined["median_net"]),
        "combined_severe10": float(combined["severe10"]),
        "audit": audit,
        "hashes": {
            "sell_opens": sha256(output_paths["sell_opens"]),
            "outcome_daily": sha256(output_paths["outcome_daily"]),
            "outcome_bounds": sha256(output_paths["outcome_bounds"]),
            "outcome_minutes": sha256(output_paths["outcome_minutes"]),
            "outcomes": sha256(output_paths["outcomes"]),
            "portfolio_nav": sha256(output_paths["portfolio_nav"]),
        },
    }


def verdict(periods: dict[str, Any]) -> tuple[str, dict[str, bool]]:
    development = periods["DEVELOPMENT"]
    diagnostic = periods["POST_OBSERVATION_DIAGNOSTIC"]
    checks = {
        "development_mean_net_ge_3pct": development["combined_mean_net"] >= 0.03,
        "diagnostic_mean_net_ge_3pct": diagnostic["combined_mean_net"] >= 0.03,
        "development_median_positive": development["combined_median_net"] > 0,
        "diagnostic_median_positive": diagnostic["combined_median_net"] > 0,
        "development_frequency_40_to_80": 40 <= development["annual_evaluation_entries"] <= 80,
        "diagnostic_frequency_40_to_80": 40 <= diagnostic["annual_evaluation_entries"] <= 80,
        "development_severe10_le_15pct": development["combined_severe10"] <= 0.15,
        "diagnostic_severe10_le_15pct": diagnostic["combined_severe10"] <= 0.15,
    }
    return (
        "V4R1_CORRECTED_NUMERICAL_TARGET_RETAINED_POST_OBSERVATION_ONLY"
        if all(checks.values())
        else "V4R1_CORRECTION_INVALIDATES_V4_CANDIDATE",
        checks,
    )


def run_stage_b() -> dict[str, Any]:
    verification = verify_stage_a()
    periods: dict[str, Any] = {}
    for label, (signal_end, tail_end, years) in PERIODS.items():
        periods[label] = run_period_stage_b(label, signal_end, tail_end, years)
    classification, checks = verdict(periods)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "periods": periods,
        "goal_checks": checks,
        "verdict": classification,
        "scientific_interpretation": (
            "2022-2023 remains post-observation. Even a retained numerical target would require "
            "a new untouched signal cohort for external confirmation; 2024 was used only to "
            "resolve pre-2024 positions and never to form or select signals."
        ),
        "research_logic_changed": False,
        "return_analysis_rerun": True,
        "strategy_rerun": True,
        "post_cutoff_signal_or_selection_data_opened": "NO",
        "repository_2024_plus_data_opened": "YES_AUTHORIZED_TRADE_RESOLUTION_ONLY",
    }
    write_json(RESULT, result)
    write_json(
        INVALIDATION,
        {
            "candidate": "ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4",
            "old_final_challenge_proposal_status": "WITHDRAWN_BEFORE_AUTHORIZATION",
            "reason": [
                "silent future-outcome completeness filtering",
                "V6-subset legal-open coverage used as if full-universe",
                "Development and diagnostic signal-constructor mismatch",
            ],
            "replacement_evidence": EXPERIMENT,
            "replacement_result_sha256": sha256(RESULT),
            "post_cutoff_signal_or_selection_data_opened": "NO",
            "repository_2024_plus_data_opened": "YES_AUTHORIZED_TRADE_RESOLUTION_ONLY",
        },
    )
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    lines = [
        f"# {EXPERIMENT}",
        "",
        "## Conclusion",
        "",
        f"`{result['verdict']}`",
        "",
        "This is an implementation-correction replay of the unchanged V4 economic rule. The old V4 final-challenge proposal is withdrawn. Post-cutoff data were used only to resolve positions formed from pre-cutoff signals.",
        "",
        "## Corrected evidence",
        "",
        "|Period|Selected|Eligible entries|Complete outcomes|Annual entries|Mean net|Median net|Severe10|Total return|MaxDD|Sharpe|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in ("DEVELOPMENT", "POST_OBSERVATION_DIAGNOSTIC"):
        item = result["periods"][label]
        combined = item["portfolio"]["COMBINED"]
        lines.append(
            f"|{label}|{item['selected_signals']}|{item['evaluation_eligible_entries']}|{item['complete_outcomes']}|"
            f"{item['annual_evaluation_entries']:.1f}|{pct(combined['mean_net'])}|{pct(combined['median_net'])}|"
            f"{pct(combined['severe10'])}|{pct(combined['total_return'])}|{pct(combined['max_drawdown'])}|{combined['sharpe']:.3f}|"
        )
    lines += [
        "",
        "## Repair audit",
        "",
        "- Both periods use the same direct first-MA5 constructor.",
        "- Every selected symbol is registered in period-local execution assets.",
        "- Every evaluation-eligible executable entry conserves into exactly one outcome.",
        "- No fixed-end completeness filter is applied; every executable entry must conserve into one outcome.",
        "- Target realization is disabled after a coordinate-lineage break; raw-share H20/risk exit remains mandatory.",
        "- 2022-2023 is a post-observation diagnostic, not external validation.",
        "",
        "## Goal checks",
        "",
    ]
    lines += [f"- {key}: `{value}`" for key, value in result["goal_checks"].items()]
    lines += [
        "",
        "## Governance",
        "",
        "Post-cutoff signal/feature/selection data opened: **NO**.",
        "",
        "Repository 2024+ data opened: **YES — authorized trade-resolution tail only**.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage-a", "verify-stage-a", "stage-b", "report"))
    args = parser.parse_args()
    if args.stage == "stage-a":
        payload = run_stage_a()
    elif args.stage == "verify-stage-a":
        payload = verify_stage_a()
    elif args.stage == "stage-b":
        payload = run_stage_b()
    else:
        render_report()
        payload = {"report": str(REPORT)}
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
