#!/usr/bin/env python3
# ruff: noqa: E501
"""One-shot 2024-2025 challenge of the frozen V26 clean-corridor rule.

Stage A reconstructs the registered PIT daily/QD-010 coordinate through the
authorized horizon, freezes both 2024 and 2025 signal/entry identities without
attaching outcomes, and records deterministic hashes.  Stage B verifies that
freeze before attaching outcomes for both years in one predetermined run.
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    ashare_below_gap_rebound_v1_core as core,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26 as v26,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as first_reversal,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-CLEAN-CORRIDOR-V26-VALIDATION-2024-2025-V1"
START_HEAD = "aa1044023bd6cef0c681322b055238b4e2919734"

OLD_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
CY006_DAILY_ROOT = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily"
)
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1"
)

CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

LABEL = "VALIDATION_2024_2025"
SIGNAL_START = pd.Timestamp("2024-01-01")
SIGNAL_END = pd.Timestamp("2025-12-31")
TAIL_END = pd.Timestamp("2026-03-31")
VALIDATION_YEARS = (2024, 2025)
HISTORY_START = pd.Timestamp("2022-01-01")

TARGET_FRACTION = first_reversal.TARGET_FRACTION
TIME_STOP = first_reversal.TIME_STOP
PORTFOLIO_K = first_reversal.PORTFOLIO_K
MIN_ACCEPTED_TRADES_PER_YEAR = v26.MIN_ACCEPTED_TRADES_PER_YEAR
MAX_GAP_WIDTH_PCT = v26.MAX_GAP_WIDTH_PCT
MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS = (
    v26.MAX_PRE_GAP_CORRIDOR_TOUCH_SESSIONS
)

EXTENDED_DAILY = EXT_ROOT / "pit_daily_qd010_exact_2022_2026q1.parquet"
COORDINATE_AUDIT = EXT_ROOT / "coordinate_reproduction_2023.json"


class ValidationError(RuntimeError):
    """Fail-closed V26 external challenge error."""


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    repair.write_parquet(frame, path)


def sha256(path: Path) -> str:
    return repair.sha256(path)


def cy006_path(year: int) -> Path:
    return CY006_DAILY_ROOT / f"partition_year={year}" / "data_0.parquet"


def output_paths() -> dict[str, Path]:
    old_root = repair.EXT_ROOT
    try:
        repair.EXT_ROOT = EXT_ROOT
        return repair.paths(LABEL)
    finally:
        repair.EXT_ROOT = old_root


@contextmanager
def frozen_runtime() -> Iterator[None]:
    old_root = repair.EXT_ROOT
    old_target = repair.TARGET_FRACTION
    old_time_stop = repair.TIME_STOP
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.EXT_ROOT = EXT_ROOT
        repair.TARGET_FRACTION = TARGET_FRACTION
        repair.TIME_STOP = TIME_STOP
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        yield
    finally:
        repair.EXT_ROOT = old_root
        repair.TARGET_FRACTION = old_target
        repair.TIME_STOP = old_time_stop
        repair.v1.PORTFOLIO_K = old_k


def board_for_symbol(symbol: str) -> str | None:
    prefix = str(symbol)[:3]
    if prefix in {"000", "001", "002", "003", "600", "601", "603", "605"}:
        return "MAIN"
    if prefix in {"300", "301", "302"}:
        return "CHINEXT"
    return None


def _as_bool(value: Any) -> bool:
    return False if pd.isna(value) else bool(value)


def _finite_or(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def seed_state(history: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Recover each symbol's exact last state and last valid coordinate close."""
    result: dict[str, dict[str, Any]] = {}
    for symbol, part in history.groupby("symbol", sort=False):
        ordered = part.sort_values("trade_date", kind="mergesort")
        last = ordered.iloc[-1]
        valid = ordered.loc[ordered.current_valid.fillna(False)]
        last_valid = None if valid.empty else valid.iloc[-1]
        result[str(symbol)] = {
            "factor": float(last.coordinate_factor),
            "invalid_step_cum": float(last.invalid_step_cum),
            "previous_current_valid": _as_bool(last.current_valid),
            "last_valid_raw_close": (
                math.nan if last_valid is None else float(last_valid.close)
            ),
            "last_valid_coordinate_close": (
                math.nan if last_valid is None else float(last_valid.coord_close)
            ),
        }
    return result


def reconstruct_qd010_coordinate(
    raw: pd.DataFrame,
    seeds: dict[str, dict[str, Any]],
    calendar: pd.DataFrame,
) -> pd.DataFrame:
    """Reproduce the accepted compact-daily QD-010 coordinate exactly.

    Invalid rows and the first recovery row break coordinate lineage.  Their
    factor preserves the last valid coordinate close and increments the lineage
    counter.  A causally known valid corporate action applies the accepted
    theoretical ex-price transform.
    """
    frame = raw.copy()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    frame = frame.merge(calendar, on="trade_date", how="left", validate="many_to_one")
    if frame.cal_idx.isna().any():
        raise ValidationError("daily row missing global calendar index")
    frame["sleeve"] = frame.symbol.map(board_for_symbol)
    if frame.sleeve.isna().any():
        raise ValidationError("non-Main/ChiNext symbol entered reconstruction")
    frame = frame.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)

    n = len(frame)
    factor_values = np.full(n, np.nan, dtype=float)
    invalid_values = np.full(n, np.nan, dtype=float)
    current_values = np.zeros(n, dtype=bool)
    history_values = np.zeros(n, dtype=bool)
    prior_coord_values = np.full(n, np.nan, dtype=float)

    groups = frame.groupby("symbol", sort=False).indices
    for symbol, positions in groups.items():
        state = dict(
            seeds.get(
                str(symbol),
                {
                    "factor": math.nan,
                    "invalid_step_cum": 0.0,
                    "previous_current_valid": False,
                    "last_valid_raw_close": math.nan,
                    "last_valid_coordinate_close": math.nan,
                },
            )
        )
        for position in positions:
            row = frame.iloc[int(position)]
            close = _finite_or(row.close, math.nan)
            current_valid = (
                _as_bool(row.hard_valid)
                and _as_bool(row.current_day_data_tradable)
                and _as_bool(row.corporate_action_valid)
                and not _as_bool(row.corporate_action_blocking)
            )
            previous_valid = bool(state["previous_current_valid"])
            factor = _finite_or(state["factor"], math.nan)
            last_raw = _finite_or(state["last_valid_raw_close"], math.nan)
            last_coord = _finite_or(
                state["last_valid_coordinate_close"], math.nan
            )
            prior_coord_values[int(position)] = last_coord

            if not (previous_valid and current_valid):
                state["invalid_step_cum"] = float(state["invalid_step_cum"]) + 1.0
                if math.isfinite(last_coord) and math.isfinite(close) and close > 0:
                    factor = last_coord / close
                elif math.isfinite(close) and close > 0:
                    factor = 1.0 / close
            elif int(_finite_or(row.corporate_action_count, 0.0)) > 0:
                share_multiplier = _finite_or(row.share_multiplier, 1.0)
                rights_ratio = _finite_or(row.rights_ratio, 0.0)
                cash_per_share = _finite_or(row.cash_per_share, 0.0)
                rights_price = _finite_or(row.rights_price, 0.0)
                denominator = share_multiplier + rights_ratio
                theoretical_ex_price = (
                    last_raw - cash_per_share + rights_price * rights_ratio
                ) / denominator if denominator > 0 else math.nan
                if not (
                    math.isfinite(factor)
                    and math.isfinite(last_raw)
                    and last_raw > 0
                    and math.isfinite(theoretical_ex_price)
                    and theoretical_ex_price > 0
                ):
                    raise ValidationError(
                        f"invalid QD-010 action transform {symbol} {row.trade_date}"
                    )
                factor = factor * last_raw / theoretical_ex_price

            if not (math.isfinite(factor) and factor > 0):
                raise ValidationError(
                    f"non-finite coordinate factor {symbol} {row.trade_date}"
                )
            coordinate_close = close * factor
            factor_values[int(position)] = factor
            invalid_values[int(position)] = float(state["invalid_step_cum"])
            current_values[int(position)] = current_valid
            history_values[int(position)] = current_valid
            if current_valid:
                state["last_valid_raw_close"] = close
                state["last_valid_coordinate_close"] = coordinate_close
            state["factor"] = factor
            state["previous_current_valid"] = current_valid

    frame["history_valid"] = history_values
    frame["current_valid"] = current_values
    frame["invalid_step_cum"] = invalid_values
    frame["coordinate_factor"] = factor_values
    frame["adjusted_close"] = frame.close.astype(float) * frame.coordinate_factor
    for name in ("open", "high", "low", "close"):
        frame[f"coord_{name}"] = frame[name].astype(float) * frame.coordinate_factor
    frame["prior_coord_close"] = prior_coord_values
    frame["causal_industry"] = frame.industry
    frame["cal_idx"] = frame.cal_idx.astype(np.int64)
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise ValidationError("reconstructed daily identity duplicate")
    return frame


def load_old_daily(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    con = duckdb.connect()
    frame = con.execute(
        f"""SELECT * FROM read_parquet('{OLD_DAILY}')
        WHERE trade_date BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
        ORDER BY symbol,trade_date"""
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def load_seed_state(end: pd.Timestamp) -> dict[str, dict[str, Any]]:
    con = duckdb.connect()
    frame = con.execute(
        f"""WITH last_row AS (
          SELECT symbol,coordinate_factor,invalid_step_cum,current_valid
          FROM read_parquet('{OLD_DAILY}')
          WHERE trade_date<=DATE '{end:%Y-%m-%d}'
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        ), last_valid AS (
          SELECT symbol,close,coord_close
          FROM read_parquet('{OLD_DAILY}')
          WHERE trade_date<=DATE '{end:%Y-%m-%d}' AND current_valid
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        )
        SELECT l.symbol,l.coordinate_factor AS factor,
          l.invalid_step_cum,l.current_valid AS previous_current_valid,
          v.close AS last_valid_raw_close,
          v.coord_close AS last_valid_coordinate_close
        FROM last_row l LEFT JOIN last_valid v USING(symbol)
        ORDER BY l.symbol"""
    ).fetchdf()
    con.close()
    return {
        str(row.symbol): {
            "factor": float(row.factor),
            "invalid_step_cum": float(row.invalid_step_cum),
            "previous_current_valid": _as_bool(row.previous_current_valid),
            "last_valid_raw_close": _finite_or(row.last_valid_raw_close, math.nan),
            "last_valid_coordinate_close": _finite_or(
                row.last_valid_coordinate_close, math.nan
            ),
        }
        for row in frame.itertuples(index=False)
    }


def load_old_calendar(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    con = duckdb.connect()
    frame = con.execute(
        f"""SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date,cal_idx::BIGINT AS cal_idx
        FROM read_parquet('{OLD_DAILY}')
        WHERE trade_date BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
        ORDER BY trade_date"""
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def load_authoritative_2023_audit() -> pd.DataFrame:
    columns = (
        "trade_date,symbol,coordinate_factor,invalid_step_cum,history_valid,"
        "current_valid,hard_valid"
    )
    con = duckdb.connect()
    frame = con.execute(
        f"""SELECT {columns} FROM read_parquet('{OLD_DAILY}')
        WHERE trade_date BETWEEN DATE '2023-01-01' AND DATE '2023-12-31'
        ORDER BY symbol,trade_date"""
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def load_cy006(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    fields = """
      CAST(trade_date AS DATE) AS trade_date,decision_at,symbol,
      open,high,low,close,volume,amount,turnover_fraction,trade_status,is_st,
      up_limit_price,down_limit_price,industry,corporate_action_count,
      corporate_action_valid,corporate_action_blocking,share_multiplier,
      cash_per_share,rights_ratio,rights_price,market_rule_valid,industry_valid,
      historical_identity_valid,hard_valid,current_day_data_tradable,available_at
    """
    pieces: list[pd.DataFrame] = []
    for year in range(int(start.year), int(end.year) + 1):
        path = cy006_path(year)
        if not path.is_file():
            raise ValidationError(f"missing registered PIT daily partition {path}")
        lower = max(start, pd.Timestamp(f"{year}-01-01"))
        upper = min(end, pd.Timestamp(f"{year}-12-31"))
        con = duckdb.connect()
        frame = con.execute(
            f"""SELECT {fields} FROM read_parquet('{path}')
            WHERE trade_date BETWEEN DATE '{lower:%Y-%m-%d}' AND DATE '{upper:%Y-%m-%d}'
              AND substr(symbol,1,3) IN ('000','001','002','003','300','301','302','600','601','603','605')
            ORDER BY symbol,trade_date"""
        ).fetchdf()
        con.close()
        if len(frame):
            pieces.append(frame)
    if not pieces:
        raise ValidationError("registered PIT daily read is empty")
    result = pd.concat(pieces, ignore_index=True)
    result["trade_date"] = pd.to_datetime(result.trade_date)
    return result


def calendar_for_raw(
    raw: pd.DataFrame, first_index: int, authoritative: pd.DataFrame | None = None
) -> pd.DataFrame:
    dates = pd.DataFrame(
        {"trade_date": pd.to_datetime(raw.trade_date.drop_duplicates()).sort_values()}
    ).reset_index(drop=True)
    if authoritative is not None:
        known = authoritative[["trade_date", "cal_idx"]].drop_duplicates("trade_date")
        dates = dates.merge(known, on="trade_date", how="left", validate="one_to_one")
        if dates.cal_idx.isna().any():
            raise ValidationError("authoritative reproduction calendar incomplete")
        dates["cal_idx"] = dates.cal_idx.astype(np.int64)
    else:
        dates["cal_idx"] = np.arange(
            first_index, first_index + len(dates), dtype=np.int64
        )
    return dates


def audit_2023_coordinate_reproduction(rebuilt_daily: pd.DataFrame) -> dict[str, Any]:
    reference = load_authoritative_2023_audit()
    rebuilt = rebuilt_daily.loc[
        rebuilt_daily.trade_date.between(
            pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")
        ),
        [
            "trade_date", "symbol", "coordinate_factor", "invalid_step_cum",
            "history_valid", "current_valid", "hard_valid",
        ],
    ].copy()
    compare = reference.merge(
        rebuilt,
        on=["symbol", "trade_date"],
        suffixes=("_reference", "_rebuilt"),
        how="left",
        indicator=True,
        validate="one_to_one",
    )
    if not compare._merge.eq("both").all():
        raise ValidationError("authoritative 2023 coordinate rows missing from reconstruction")
    factor_difference = (
        compare.coordinate_factor_reference - compare.coordinate_factor_rebuilt
    ).abs()
    payload = {
        "reference_rows": len(reference),
        "rebuilt_rows": len(rebuilt),
        "additional_registered_rows_not_in_old_compact": int(len(rebuilt) - len(reference)),
        "maximum_coordinate_factor_absolute_difference": float(factor_difference.max()),
        "coordinate_factor_mismatch_gt_1e_10_count": int(factor_difference.gt(1e-10).sum()),
        "invalid_step_cum_mismatch_count": int(
            compare.invalid_step_cum_reference.ne(compare.invalid_step_cum_rebuilt).sum()
        ),
        "history_valid_mismatch_count": int(
            compare.history_valid_reference.ne(compare.history_valid_rebuilt).sum()
        ),
        "current_valid_mismatch_count": int(
            compare.current_valid_reference.ne(compare.current_valid_rebuilt).sum()
        ),
        "hard_valid_mismatch_count": int(
            compare.hard_valid_reference.ne(compare.hard_valid_rebuilt).sum()
        ),
    }
    blocking = {
        key: value
        for key, value in payload.items()
        if key.endswith("_count") and int(value) != 0
    }
    if blocking:
        raise ValidationError(f"2023 coordinate reproduction failed {blocking}")
    write_json(COORDINATE_AUDIT, payload)
    return payload


def build_extended_daily() -> pd.DataFrame:
    seeds = load_seed_state(pd.Timestamp("2021-12-31"))
    old_calendar = load_old_calendar(HISTORY_START, pd.Timestamp("2023-12-31"))
    raw = load_cy006(HISTORY_START, TAIL_END)
    dates = pd.DataFrame(
        {"trade_date": pd.to_datetime(raw.trade_date.drop_duplicates()).sort_values()}
    ).reset_index(drop=True)
    calendar = dates.merge(
        old_calendar, on="trade_date", how="left", validate="one_to_one"
    )
    future = calendar.trade_date.gt(pd.Timestamp("2023-12-31"))
    calendar.loc[future, "cal_idx"] = np.arange(
        int(old_calendar.cal_idx.max()) + 1,
        int(old_calendar.cal_idx.max()) + 1 + int(future.sum()),
        dtype=np.int64,
    )
    if calendar.cal_idx.isna().any():
        raise ValidationError("2022-2023 registered calendar differs from authority")
    calendar["cal_idx"] = calendar.cal_idx.astype(np.int64)
    rebuilt = reconstruct_qd010_coordinate(raw, seeds, calendar)
    required = {
        "trade_date", "cal_idx", "symbol", "sleeve", "open", "high", "low",
        "close", "volume", "amount", "turnover_fraction", "is_st", "industry",
        "causal_industry", "trade_status", "current_day_data_tradable",
        "up_limit_price", "down_limit_price", "market_rule_valid",
        "corporate_action_count", "corporate_action_valid",
        "corporate_action_blocking", "industry_valid", "historical_identity_valid",
        "hard_valid", "available_at", "decision_at", "history_valid",
        "current_valid", "adjusted_close", "invalid_step_cum", "coordinate_factor",
        "coord_open", "coord_high", "coord_low", "coord_close", "prior_coord_close",
    }
    missing = sorted(required - set(rebuilt.columns))
    if missing:
        raise ValidationError(f"extended daily missing required columns {missing}")
    daily = rebuilt[sorted(required)].copy()
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    daily["symbol_seq"] = daily.groupby("symbol", sort=False).cumcount()
    if daily.duplicated(["symbol", "trade_date"]).any():
        raise ValidationError("extended daily duplicate symbol-date")
    if daily.trade_date.max() < TAIL_END:
        raise ValidationError("extended daily does not cover authorized tail end")
    write_parquet(daily, EXTENDED_DAILY)
    return daily


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "ONE_SHOT_REPOSITORY_FUTURE_COHORT_CHALLENGE",
        "source_v26_experiment": v26.EXPERIMENT,
        "source_v26_head": START_HEAD,
        "validation_signal_period": ["2024-01-01", "2025-12-31"],
        "authorized_trade_completion_tail": "2026-03-31",
        "one_shot_governance": (
            "2024 and 2025 identities freeze together before either year's outcomes; "
            "no 2024 inspection, modification, or selection before 2025 evaluation"
        ),
        "frozen_rule": v26.contract_value()["unchanged_v13"]
        | {
            "gap_width_pct": "source minimum 1%; maximum 3%",
            "pre_gap_corridor_touch_sessions": "<=10 of exact 120 completed sessions",
            "corridor": "[L-0.5W,U+0.5W]",
        },
        "validation_checks_frozen_before_outcomes": {
            "accepted_trades_per_signal_year_strictly_greater_than": 50.0,
            "combined_mean_net_min": 0.03,
            "combined_median_net_positive": True,
            "each_2024_2025_trade_mean_positive": True,
            "each_2024_2025_calendar_portfolio_return_positive": True,
            "combined_severe10_max": 0.15,
        },
        "daily_extension": {
            "source": str(CY006_DAILY_ROOT),
            "same_qd010_coordinate_semantics": True,
            "mandatory_full_2023_reproduction_before_signal_freeze": True,
        },
        "governance": {
            "2026_signal_feature_or_selection_use": False,
            "2026_use": "trade completion only for signals formed by 2025-12-31",
            "rule_threshold_entry_target_cost_horizon_portfolio_change": False,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "freeze_status": "BEFORE_2024_2025_OUTCOME_OPEN",
            "signal_years": list(VALIDATION_YEARS),
            "stage_b_is_single_predetermined_execution": True,
            "selection_after_2024_outcomes": "PROHIBITED",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    values = {
        "v26_runner": Path(v26.__file__),
        "v26_contract": v26.CONTRACT,
        "v26_stage_a_freeze": v26.STAGE_A_FREEZE,
        "v26_result": v26.RESULT,
        "v13_runner": Path(first_reversal.__file__),
        "replay_helper": Path(repair.__file__),
        "gap_core": Path(core.__file__),
    }
    missing = [str(path) for path in values.values() if not path.is_file()]
    if missing:
        raise ValidationError(f"missing frozen source files {missing}")
    return {key: sha256(path) for key, path in values.items()}


def build_stage_a_population(daily: pd.DataFrame) -> dict[str, Any]:
    paths = output_paths()
    paths["root"].mkdir(parents=True, exist_ok=True)
    signal_daily = daily.loc[daily.trade_date.le(SIGNAL_END)].copy()
    gaps = core.build_all_true_gaps(signal_daily)
    candidates = first_reversal.build_reversal_candidates(signal_daily, gaps)
    candidates = candidates.loc[
        candidates.trigger.eq("PRIOR_HIGH_REVERSAL")
        & pd.to_datetime(candidates.signal_date).dt.year.isin(VALIDATION_YEARS)
    ].copy()
    candidates = candidates.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if candidates.empty or candidates.gap_id.duplicated().any():
        raise ValidationError("2024-2025 prior-high candidate identity failure")
    write_parquet(candidates, paths["candidates"])

    repair.v1.configure_external(paths["root"], SIGNAL_END)
    vap, _profiles = repair.v1.build_vap_for_signals(candidates, signal_daily)
    panel = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    selected = panel.loc[repair.fixed_signal_mask(panel)].copy()
    selected = selected.loc[v26.clean_corridor_mask(selected)].copy()
    selected["signal_year"] = pd.to_datetime(selected.signal_date).dt.year
    selected["decision_latest_timestamp"] = pd.to_datetime(selected.signal_time)
    selected["feature_uses_post_signal_information"] = False
    selected["v26_gap_width_gate"] = True
    selected["v26_low_corridor_touch_gate"] = True
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise ValidationError("2024-2025 V26 selected identity failure")
    if not set(selected.signal_year.astype(int)).issubset(set(VALIDATION_YEARS)):
        raise ValidationError("post-2025 signal entered frozen population")
    write_parquet(selected, paths["signals"])

    symbols = selected.symbol.drop_duplicates().astype(str).tolist()
    actions = repair.build_actions(
        symbols, TAIL_END, paths["actions"], paths["action_registry"]
    )
    state_columns = [
        "trade_date", "cal_idx", "symbol", "sleeve", "coordinate_factor",
        "invalid_step_cum", "history_valid", "current_valid", "hard_valid",
        "trade_status", "current_day_data_tradable", "market_rule_valid",
        "corporate_action_blocking", "up_limit_price", "down_limit_price",
    ]
    execution_state = daily.loc[
        daily.symbol.isin(symbols)
        & daily.trade_date.between(pd.Timestamp(selected.signal_date.min()), TAIL_END),
        state_columns,
    ].copy()
    execution_state["coordinate_lineage_carried"] = False
    if set(symbols) - set(execution_state.symbol.astype(str)):
        raise ValidationError("selected symbol absent from exact execution state")
    write_parquet(execution_state, paths["execution_state"])
    entries = repair.build_buy_entries(
        selected, actions, SIGNAL_END, TAIL_END, paths
    )
    yearly = (
        entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
        .assign(_year=lambda x: pd.to_datetime(x.signal_date).dt.year)
        .groupby("_year")
        .size()
    )
    return {
        "direct_prior_high_candidates": len(candidates),
        "selected_signals": len(selected),
        "selected_symbols": len(symbols),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "evaluation_eligible_entries": int(entries.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "eligible_entries_by_signal_year": {
            str(year): int(yearly.get(year, 0)) for year in VALIDATION_YEARS
        },
        "feature_uses_post_signal_information_count": int(
            selected.feature_uses_post_signal_information.sum()
        ),
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "post_2025_signal_count": int(pd.to_datetime(selected.signal_date).gt(SIGNAL_END).sum()),
        "execution_state_rows": len(execution_state),
        "hashes": {
            "daily": sha256(EXTENDED_DAILY),
            "coordinate_audit": sha256(COORDINATE_AUDIT),
            "candidates": sha256(paths["candidates"]),
            "signals": sha256(paths["signals"]),
            "actions": sha256(paths["actions"]),
            "action_registry": sha256(paths["action_registry"]),
            "execution_state": sha256(paths["execution_state"]),
            "entries": sha256(paths["entries"]),
            "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
        },
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    daily = build_extended_daily()
    coordinate_audit = audit_2023_coordinate_reproduction(daily)
    population = build_stage_a_population(daily)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_SIMULTANEOUS_2024_2025_IDENTITY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "coordinate_reproduction_2023": coordinate_audit,
        "population": population,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "2024_outcomes_opened_before_2025_identity_freeze": "NO",
        "2026_signal_feature_or_selection_use": "NO",
        "repository_2024_2025_data_opened": "YES_AUTHORIZED_IDENTITY_AND_ENTRY_ONLY",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise ValidationError("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    current_sources = source_hashes()
    if current_sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), current_sources]
    paths = output_paths()
    artifacts = {
        "daily": sha256(EXTENDED_DAILY),
        "coordinate_audit": sha256(COORDINATE_AUDIT),
        "candidates": sha256(paths["candidates"]),
        "signals": sha256(paths["signals"]),
        "actions": sha256(paths["actions"]),
        "action_registry": sha256(paths["action_registry"]),
        "execution_state": sha256(paths["execution_state"]),
        "entries": sha256(paths["entries"]),
        "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
    }
    if artifacts != freeze["population"]["hashes"]:
        drift["stage_a_artifacts"] = [freeze["population"]["hashes"], artifacts]
    if drift:
        raise ValidationError(f"Stage-A freeze drift {drift}")
    return {"verified": True, "checks": checks}


def build_exact_outcome_daily(
    entries: pd.DataFrame, daily: pd.DataFrame, paths: dict[str, Path]
) -> pd.DataFrame:
    symbols = sorted(
        entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "symbol"]
        .astype(str)
        .unique()
    )
    start = pd.Timestamp(entries.signal_date.min()).normalize()
    result = daily.loc[
        daily.symbol.isin(symbols) & daily.trade_date.between(start, TAIL_END)
    ].copy()
    calendar = (
        daily.loc[daily.trade_date.between(start, TAIL_END), ["trade_date", "cal_idx"]]
        .drop_duplicates("trade_date")
        .sort_values("trade_date", kind="mergesort")
    )
    missing = calendar.loc[~calendar.trade_date.isin(result.trade_date.unique())]
    if len(missing):
        sentinel = pd.DataFrame(
            {column: np.nan for column in result.columns}, index=range(len(missing))
        )
        sentinel["trade_date"] = missing.trade_date.to_numpy()
        sentinel["cal_idx"] = missing.cal_idx.to_numpy()
        sentinel["symbol"] = "__CALENDAR__"
        sentinel["sleeve"] = "CALENDAR"
        result = pd.concat([result, sentinel], ignore_index=True)
    result = result.sort_values(["trade_date", "symbol"], kind="mergesort").reset_index(drop=True)
    if result.empty or result.duplicated(["symbol", "trade_date"]).any():
        raise ValidationError("outcome daily identity failure")
    write_parquet(result, paths["outcome_daily"])
    return result


def accepted_year_metrics(accepted: pd.DataFrame) -> dict[str, Any]:
    frame = accepted.copy()
    frame["entry_date"] = pd.to_datetime(frame.entry_date)
    payload: dict[str, Any] = {}
    for year in VALIDATION_YEARS:
        part = frame.loc[frame.entry_date.dt.year.eq(year)]
        payload[str(year)] = {
            "trades": len(part),
            "mean_net": None if part.empty else float(part.net_return.mean()),
            "median_net": None if part.empty else float(part.net_return.median()),
            "win": None if part.empty else float(part.net_return.gt(0).mean()),
            "target_hit": None if part.empty else float(part.exit_reason.eq("PRE_L_TARGET").mean()),
            "severe10": None if part.empty else float(part.net_return.le(-0.10).mean()),
            "mean_holding_sessions": None if part.empty else float(part.holding_sessions.mean()),
            "median_holding_sessions": None if part.empty else float(part.holding_sessions.median()),
        }
    return payload


def validation_checks(
    combined: dict[str, Any], yearly: dict[str, Any]
) -> dict[str, bool]:
    annual = combined["annual_returns"]
    return {
        "accepted_trades_per_signal_year_gt_50": (
            sum(int(yearly[str(year)]["trades"]) for year in VALIDATION_YEARS)
            / len(VALIDATION_YEARS)
            > MIN_ACCEPTED_TRADES_PER_YEAR
        ),
        "combined_mean_net_ge_3pct": float(combined["mean_net"]) >= 0.03,
        "combined_median_net_positive": float(combined["median_net"]) > 0,
        "combined_severe10_le_15pct": float(combined["severe10"]) <= 0.15,
        "each_2024_2025_trade_mean_positive": all(
            yearly[str(year)]["mean_net"] is not None
            and float(yearly[str(year)]["mean_net"]) > 0
            for year in VALIDATION_YEARS
        ),
        "each_2024_2025_calendar_portfolio_return_positive": all(
            float(annual.get(str(year), 0.0)) > 0 for year in VALIDATION_YEARS
        ),
    }


def run_stage_b() -> dict[str, Any]:
    verification = verify_stage_a()
    paths = output_paths()
    entries = pd.read_parquet(paths["entries"])
    actions = pd.read_parquet(paths["actions"])
    daily = pd.read_parquet(EXTENDED_DAILY)
    for frame, columns in (
        (entries, ("signal_time", "signal_date", "entry_time", "entry_date")),
        (actions, ("known_date", "effective_date")),
        (daily, ("trade_date",)),
    ):
        for column in columns:
            if column in frame:
                frame[column] = pd.to_datetime(frame[column])

    with frozen_runtime():
        outcome_daily = build_exact_outcome_daily(entries, daily, paths)
        sell_opens = repair.build_sell_opens(entries, TAIL_END, paths)
        outcome_minutes = repair.build_outcome_minutes(
            entries, outcome_daily, TAIL_END, paths
        )
        outcomes, outcome_audit = repair.build_outcomes(
            entries,
            outcome_daily,
            outcome_minutes,
            sell_opens,
            actions,
            TAIL_END,
            paths,
        )
        max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
        replay_years = tuple(range(min(VALIDATION_YEARS), int(max_exit.year) + 1))
        portfolio_daily = outcome_daily.loc[outcome_daily.trade_date.le(max_exit)].copy()
        repair.v1.configure_external(paths["root"], max_exit)
        portfolio = repair.v1.run_portfolio(outcomes, portfolio_daily, replay_years)

    accepted = pd.read_parquet(paths["root"] / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    yearly = accepted_year_metrics(accepted)
    combined = portfolio["COMBINED"]
    checks = validation_checks(combined, yearly)
    if all(checks.values()):
        verdict = "V26_VALIDATED_2024_2025"
    elif (
        float(combined["mean_net"]) > 0
        and all(
            yearly[str(year)]["mean_net"] is not None
            and float(yearly[str(year)]["mean_net"]) > 0
            for year in VALIDATION_YEARS
        )
        and all(
            float(combined["annual_returns"].get(str(year), 0.0)) > 0
            for year in VALIDATION_YEARS
        )
    ):
        verdict = "V26_VALIDATION_MIXED"
    else:
        verdict = "V26_VALIDATION_FAILED"

    eligible = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    audit = {
        "rule_changed_after_2024_2025_open_count": 0,
        "validation_parameter_selection_count": 0,
        "2024_outcome_used_to_change_2025_identity_count": 0,
        "feature_uses_post_signal_information_count": int(
            entries.feature_uses_post_signal_information.sum()
        ),
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "eligible_entry_without_outcome_count": int(len(eligible) - len(outcomes)),
        "t1_violation_count": int(outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()),
        "target_at_or_above_L_count": int(outcomes.target_coordinate.ge(outcomes.L).sum()),
        "unresolved_action_block_count": int(outcome_audit.get("unresolved_action_block_count", 0)),
        "max_k_violation_count": int(portfolio["audit"]["max_k_violation_count"]),
        "negative_cash_or_leverage_count": int(portfolio["audit"]["negative_cash_or_leverage_count"]),
        "post_2025_signal_count": int(pd.to_datetime(entries.signal_date).gt(SIGNAL_END).sum()),
        "2026_signal_feature_or_selection_use_count": 0,
        "2026_trade_completion_count": int(pd.to_datetime(outcomes.exit_date).dt.year.eq(2026).sum()),
        "repository_2024_2025_outcomes_opened": "YES_AUTHORIZED_ONE_SHOT_VALIDATION",
        "repository_2026_data_opened": "YES_AUTHORIZED_2025_TRADE_COMPLETION_ONLY",
    }
    nonblocking = {"2026_trade_completion_count"}
    blocking = {
        key: value
        for key, value in audit.items()
        if key.endswith("_count") and key not in nonblocking and int(value) != 0
    }
    if blocking:
        raise ValidationError(f"Stage-B blocking audit {blocking}")

    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "signal_period": [str(SIGNAL_START.date()), str(SIGNAL_END.date())],
        "authorized_tail_end": str(TAIL_END.date()),
        "maximum_exit_date_used": str(max_exit.date()),
        "selected_signals": len(entries),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "evaluation_eligible_entries": len(eligible),
        "complete_outcomes": len(outcomes),
        "event_metrics": repair.v1.trade_metrics(outcomes),
        "accepted_trade_yearly": yearly,
        "portfolio": portfolio,
        "goal_checks": checks,
        "verdict": verdict,
        "audit": audit,
        "hashes": {
            "stage_a_freeze": sha256(STAGE_A_FREEZE),
            "outcome_daily": sha256(paths["outcome_daily"]),
            "sell_opens": sha256(paths["sell_opens"]),
            "outcome_bounds": sha256(paths["outcome_bounds"]),
            "outcome_minutes": sha256(paths["outcome_minutes"]),
            "outcomes": sha256(paths["outcomes"]),
            "portfolio_nav": sha256(paths["portfolio_nav"]),
            "portfolio_accepted": sha256(paths["root"] / "portfolio_accepted.parquet"),
        },
    }
    write_json(RESULT, result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report() -> None:
    result = json.loads(RESULT.read_text(encoding="utf-8"))
    combined = result["portfolio"]["COMBINED"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen challenge",
        "",
        "Both 2024 and 2025 signal identities were frozen together before either year's outcomes were attached. V26 signal, two-condition admission, entry, A67 target, H20, 40 bp costs, K80 and 50/50 board sleeves are unchanged.",
        "",
        "|Signal year|Accepted trades|Mean net|Median net|Win|Target hit|Severe10|Mean hold|Calendar portfolio return|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in VALIDATION_YEARS:
        item = result["accepted_trade_yearly"][str(year)]
        lines.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['target_hit'])}|{pct(item['severe10'])}|{item['mean_holding_sessions']:.2f}|{pct(combined['annual_returns'].get(str(year), 0.0))}|"
        )
    lines += [
        "",
        "## Combined",
        "",
        f"Accepted trades: {combined['trades']}; mean {pct(combined['mean_net'])}; median {pct(combined['median_net'])}; win {pct(combined['win'])}; target hit {pct(combined['u_hit'])}; severe10 {pct(combined['severe10'])}.",
        f"Total portfolio return through the last authorized completion: {pct(combined['total_return'])}; CAGR {pct(combined['cagr'])}; MaxDD {pct(combined['max_drawdown'])}; Sharpe {combined['sharpe']:.3f}.",
        "",
        "## Board sleeves",
        "",
        "|Sleeve|Trades|Mean|Median|Win|Severe10|Total return|MaxDD|Sharpe|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for board in ("MAIN", "CHINEXT"):
        item = result["portfolio"][board]
        lines.append(
            f"|{board}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['severe10'])}|{pct(item['total_return'])}|{pct(item['max_drawdown'])}|{item['sharpe']:.3f}|"
        )
    lines += [
        "",
        "## Frozen checks",
        "",
        *[f"- {key}: `{value}`" for key, value in result["goal_checks"].items()],
        "",
        "## Governance",
        "",
        "2026 was used only to complete positions whose signals formed no later than 2025-12-31. No 2026 signal, feature, threshold or selection entered the challenge.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not (args.stage_a or args.stage_b or args.all):
        parser.error("choose --stage-a, --stage-b, or --all")
    if args.stage_a or args.all:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    if args.stage_b or args.all:
        result = run_stage_b()
        render_report()
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
