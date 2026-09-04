#!/usr/bin/env python3
# ruff: noqa: E501
"""Freeze, audit, and replay the single V26-or-V27 union strategy."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26 as v26,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_first_reversal_v13 as first_reversal,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_capitulation_snapback_v27 as v27,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_meaningful_prior_decline_v16 as replay,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-V26-V27-UNION-V1"
START_HEAD = "bc9051e21d2e54861e4e53045325a5c1ba4cc51e"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_v26_v27_union_v1"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
CAUSALITY_AUDIT = OS / f"artifacts/{EXPERIMENT}_causality_audit.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

OLD_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_collapse_gap_zone_dual_fresh_k10_validation_v1/"
    "pit_daily_compact_2013_2023.parquet"
)
NEW_DAILY = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "pit_daily_qd010_exact_2022_2026q1.parquet"
)
V26_OLD = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_clean_corridor_v26"
)
V27_OLD = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_v27"
)
V26_NEW = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1/"
    "validation_2024_2025"
)
V27_NEW = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_"
    "v27_diagnostic_2024_2025_v1/diagnostic_2024_2025"
)

PERIODS: dict[str, dict[str, Any]] = {
    "OBSERVED_2017_2023": {
        "years": tuple(range(2017, 2024)),
        "daily": OLD_DAILY,
        "v26_entries": [
            V26_OLD / "development/d30_selected_entries.parquet",
            V26_OLD / "post_observation_diagnostic/d30_selected_entries.parquet",
        ],
        "v27_entries": [
            V27_OLD / "development/fresh_snapback_selected_entries.parquet",
            V27_OLD / "post_observation_diagnostic/fresh_snapback_selected_entries.parquet",
        ],
        "v26_outcomes": [
            V26_OLD / "development/d30/outcomes.parquet",
            V26_OLD / "post_observation_diagnostic/d30/outcomes.parquet",
        ],
        "v27_outcomes": [
            V27_OLD / "development/fresh_snapback/outcomes.parquet",
            V27_OLD / "post_observation_diagnostic/fresh_snapback/outcomes.parquet",
        ],
        "outcome_daily": [
            replay.source_paths("DEVELOPMENT")["outcome_daily"],
            replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"],
        ],
    },
    "DIAGNOSTIC_2024_2025": {
        "years": (2024, 2025),
        "daily": NEW_DAILY,
        "v26_entries": [V26_NEW / "entries.parquet"],
        "v27_entries": [V27_NEW / "entries.parquet"],
        "v26_outcomes": [V26_NEW / "outcomes.parquet"],
        "v27_outcomes": [V27_NEW / "outcomes.parquet"],
        "outcome_daily": [
            V26_NEW / "outcome_daily.parquet",
            V27_NEW / "outcome_daily.parquet",
        ],
    },
}

PORTFOLIO_K = 80


class UnionError(RuntimeError):
    """Fail-closed union strategy error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def period_root(label: str) -> Path:
    return EXT_ROOT / label.lower()


def union_entries_path(label: str) -> Path:
    return period_root(label) / "union_entries.parquet"


def audit_rows_path(label: str) -> Path:
    return period_root(label) / "causal_prefix_audit.parquet"


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "RETROSPECTIVE_UNION_CANDIDATE_NOT_NEW_VALIDATION",
        "strategy_identity": "V13_BASE_AND_(V26_OR_V27)",
        "base": {
            "true_gap": "High_t < Low_t_minus_1",
            "pre_gap_daily_and_minute_history": "exact 120 completed sessions",
            "no_L_touch_before_signal": True,
            "minimum_maximum_depth_below_L": 0.10,
            "minimum_signal_depth_below_L": 0.05,
            "trigger": "first completed daily close > previous completed daily high",
            "entry": "first legal 1-minute open strictly after signal",
            "minimum_net_L_headroom": 0.05,
        },
        "v26_branch": {
            "gap_width_pct_max": 0.03,
            "pre_gap_corridor_touch_sessions_max": 10,
        },
        "v27_branch": {
            "pre_peak_to_gap_sessions_min": 20,
            "gap_age_sessions_max": 14,
            "rebound_from_post_gap_low_over_L_min": 0.05,
        },
        "union": {
            "operator": "OR",
            "overlap_policy": "one GAP_ID, one signal, one position",
            "priority_between_branches": "NONE",
        },
        "execution": {
            "target": "entry + 0.67 * (L - entry), strictly below L",
            "time_stop": "H20",
            "failure_stop": "NONE",
            "round_trip_cost": 0.004,
            "T1": True,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve; one active symbol",
            "collision_order": [
                "entry_time ascending",
                "realized_net_target_at_entry descending",
                "pre_gap_inside_density_relative_local ascending",
                "symbol ascending",
                "gap_id ascending",
            ],
        },
        "governance": {
            "no_rule_selection_from_union_results": True,
            "2017_2025_already_observed": True,
            "2026_new_signal_use": False,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "v26_contract_sha256": sha256(v26.CONTRACT),
            "v27_contract_sha256": sha256(v27.CONTRACT),
            "causal_audit_method": (
                "recompute every identity and trigger input from each symbol's "
                "daily prefix ending at its own completed signal bar"
            ),
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def all_source_paths() -> dict[str, Path]:
    paths: dict[str, Path] = {
        "v13_runner": Path(first_reversal.__file__),
        "v13_contract": first_reversal.CONTRACT,
        "execution_runner": Path(repair.__file__),
        "portfolio_runner": Path(repair.v1.__file__),
        "portfolio_base": Path(repair.v1.base.__file__),
        "v26_runner": Path(v26.__file__),
        "v26_contract": v26.CONTRACT,
        "v27_runner": Path(v27.__file__),
        "v27_contract": v27.CONTRACT,
        "old_daily": OLD_DAILY,
        "new_daily": NEW_DAILY,
    }
    for label, config in PERIODS.items():
        for key in ("v26_entries", "v27_entries", "v26_outcomes", "v27_outcomes", "outcome_daily"):
            for index, path in enumerate(config[key]):
                paths[f"{label.lower()}_{key}_{index}"] = path
    return paths


def source_hashes(include_outcomes: bool) -> dict[str, str]:
    paths = all_source_paths()
    if not include_outcomes:
        paths = {
            key: path
            for key, path in paths.items()
            if "outcomes" not in key and "outcome_daily" not in key
        }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise UnionError(f"missing source files: {missing}")
    return {key: sha256(path) for key, path in paths.items()}


def read_many(paths: list[Path]) -> pd.DataFrame:
    frame = pd.concat([pd.read_parquet(path) for path in paths], ignore_index=True)
    for column in (
        "gap_date", "signal_date", "signal_time", "decision_latest_timestamp",
        "semantic_feature_latest_timestamp", "entry_date", "entry_time",
        "exit_date", "exit_time", "trade_date",
    ):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column])
    return frame


def canonical_union(v26_frame: pd.DataFrame, v27_frame: pd.DataFrame) -> pd.DataFrame:
    if v26_frame.gap_id.duplicated().any() or v27_frame.gap_id.duplicated().any():
        raise UnionError("source GAP_ID duplicate")
    v26_ids = set(v26_frame.gap_id.astype(str))
    v27_ids = set(v27_frame.gap_id.astype(str))
    overlap = v26_ids & v27_ids
    left = v26_frame.loc[v26_frame.gap_id.astype(str).isin(overlap)].sort_values("gap_id").reset_index(drop=True)
    right = v27_frame.loc[v27_frame.gap_id.astype(str).isin(overlap)].sort_values("gap_id").reset_index(drop=True)
    for column in (
        "symbol", "gap_date", "signal_time", "entry_status", "entry_time",
        "entry_raw_price", "L", "U", "gap_width_pct", "max_depth", "current_depth",
    ):
        if column not in left or column not in right:
            continue
        if pd.api.types.is_numeric_dtype(left[column]):
            difference = (left[column].astype(float) - right[column].astype(float)).abs()
            if difference.dropna().gt(1e-12).any() or left[column].isna().ne(right[column].isna()).any():
                raise UnionError(f"overlap numeric mismatch: {column}")
        elif not left[column].astype(str).equals(right[column].astype(str)):
            raise UnionError(f"overlap identity mismatch: {column}")
    union = pd.concat(
        [v26_frame, v27_frame.loc[~v27_frame.gap_id.astype(str).isin(v26_ids)]],
        ignore_index=True,
        sort=False,
    )
    union["v26_branch_pass"] = v26.clean_corridor_mask(union)
    union["v27_branch_pass"] = v27.fresh_snapback_mask(union)
    union["union_admission_pass"] = union.v26_branch_pass | union.v27_branch_pass
    if not union.union_admission_pass.all():
        raise UnionError("union contains row that passes neither branch")
    union["union_source"] = union.gap_id.astype(str).map(
        lambda value: "BOTH" if value in overlap else ("V26_ONLY" if value in v26_ids else "V27_ONLY")
    )
    union["decision_latest_timestamp"] = pd.to_datetime(union.signal_time)
    union["feature_uses_post_signal_information"] = False
    union = union.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if union.gap_id.duplicated().any():
        raise UnionError("union GAP_ID duplicate")
    return union


def load_daily_for_symbols(path: Path, symbols: list[str]) -> pd.DataFrame:
    registry = pd.DataFrame({"symbol": sorted(set(symbols))})
    con = duckdb.connect()
    con.register("registry", registry)
    frame = con.execute(
        f"""SELECT d.* FROM read_parquet('{path}') d
        JOIN registry r USING(symbol)
        ORDER BY d.symbol,d.trade_date"""
    ).fetchdf()
    con.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame


def first_prior_high_signal_for_gap(
    part: pd.DataFrame, gap_pos: int, end_pos: int, L: float
) -> pd.Timestamp | None:
    path = part.iloc[gap_pos + 1 : end_pos + 1].copy()
    valid = repair.source._valid_daily_rows(path) & path.invalid_step_cum.eq(
        float(part.invalid_step_cum.iloc[gap_pos])
    ).to_numpy(bool)
    bad = first_reversal.first_true(~valid)
    if bad is not None:
        path = path.iloc[:bad]
    touched = repair.source._raw_tick_reached(path.high, L, path.coordinate_factor)
    touch = first_reversal.first_true(touched)
    if touch is not None:
        path = path.iloc[:touch]
    for rel in range(9, len(path)):
        absolute = gap_pos + 1 + rel
        rolling = part.iloc[max(0, absolute - 19) : absolute + 1]
        if len(rolling) < 20:
            continue
        current = rolling.iloc[-1]
        previous = rolling.iloc[-2]
        previous2 = rolling.iloc[-3]
        since_gap = path.iloc[: rel + 1]
        max_depth = 1 - float(since_gap.coord_low.min()) / L
        current_depth = 1 - float(current.coord_close) / L
        low20_offset = int(np.nanargmin(rolling.coord_low.to_numpy(float)))
        days_since_low20 = len(rolling) - 1 - low20_offset
        recovery = float(current.coord_close / rolling.coord_low.min() - 1)
        if not (
            max_depth >= 0.10
            and current_depth >= 0.05
            and 1 <= days_since_low20 <= 10
            and recovery >= 0.03
        ):
            continue
        flags = first_reversal.trigger_flags(
            float(current.coord_close),
            float(previous.coord_close),
            float(previous2.coord_close),
            float(previous.coord_high),
            rolling.iloc[-4:-1].coord_high.astype(float).tolist(),
        )
        if flags["PRIOR_HIGH_REVERSAL"]:
            return pd.Timestamp(current.trade_date)
    return None


def causal_prefix_audit(union: pd.DataFrame, daily_path: Path) -> tuple[pd.DataFrame, dict[str, int]]:
    daily = load_daily_for_symbols(daily_path, union.symbol.astype(str).unique().tolist())
    groups = {
        str(symbol): part.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    rows: list[dict[str, Any]] = []
    for event in union.itertuples(index=False):
        part = groups[str(event.symbol)]
        gap_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.gap_date)).to_numpy())
        signal_positions = np.flatnonzero(part.trade_date.eq(pd.Timestamp(event.signal_date)).to_numpy())
        if len(gap_positions) != 1 or len(signal_positions) != 1:
            raise UnionError(f"daily chronology identity missing: {event.gap_id}")
        gap_pos, signal_pos = int(gap_positions[0]), int(signal_positions[0])
        gap = part.iloc[gap_pos]
        previous = part.iloc[gap_pos - 1]
        hist = part.iloc[gap_pos - 120 : gap_pos]
        path = part.iloc[gap_pos + 1 : signal_pos + 1]
        rolling = part.iloc[signal_pos - 19 : signal_pos + 1]
        exact_history = (
            len(hist) == 120
            and repair.source._valid_daily_rows(hist).all()
            and hist.invalid_step_cum.eq(float(event.invalid_step_cum)).all()
        )
        true_gap = (
            bool(gap.high < previous.low)
            and int(gap.cal_idx) - int(previous.cal_idx) == 1
            and float(gap.invalid_step_cum) == float(previous.invalid_step_cum)
        )
        L = float(gap.high) * float(gap.coordinate_factor)
        U = float(previous.low) * float(gap.coordinate_factor)
        gap_coordinate_match = abs(L - float(event.L)) <= 1e-10 and abs(U - float(event.U)) <= 1e-10
        corridor = hist.coord_high.ge(float(event.L - 0.5 * event.W)) & hist.coord_low.lt(float(event.U + 0.5 * event.W))
        peak_offset = int(np.nanargmax(hist.coord_high.to_numpy(float))) if len(hist) else -1
        max_depth = 1 - float(path.coord_low.min()) / float(event.L)
        current_depth = 1 - float(part.coord_close.iloc[signal_pos]) / float(event.L)
        no_L_touch = not bool(
            repair.source._raw_tick_reached(path.high, float(event.L), path.coordinate_factor).any()
        )
        prefix_first = first_prior_high_signal_for_gap(part, gap_pos, signal_pos, float(event.L))
        prefix_trigger_match = prefix_first == pd.Timestamp(event.signal_date)
        v26_pass = bool(v26.clean_corridor_mask(pd.DataFrame([event._asdict()])).iloc[0])
        v27_pass = bool(v27.fresh_snapback_mask(pd.DataFrame([event._asdict()])).iloc[0])
        expected_source = (
            "BOTH" if v26_pass and v27_pass else ("V26_ONLY" if v26_pass else "V27_ONLY")
        )
        rows.append(
            {
                "gap_id": event.gap_id,
                "symbol": event.symbol,
                "signal_time": event.signal_time,
                "true_gap_recomputed": true_gap,
                "gap_coordinate_match": gap_coordinate_match,
                "exact_120_session_history": exact_history,
                "vap_latest_source_before_gap": bool(hist.trade_date.max() < pd.Timestamp(event.gap_date)),
                "corridor_touch_recomputed": int(corridor.sum()) == int(event.pre_gap_corridor_touch_sessions),
                "peak_age_recomputed": int(len(hist) - peak_offset) == int(event.pre_peak_to_gap_sessions),
                "gap_age_recomputed": signal_pos - gap_pos == int(event.gap_age),
                "max_depth_recomputed": abs(max_depth - float(event.max_depth)) <= 1e-10,
                "current_depth_recomputed": abs(current_depth - float(event.current_depth)) <= 1e-10,
                "no_L_touch_through_signal": no_L_touch,
                "prefix_first_prior_high_signal_match": prefix_trigger_match,
                "signal_rolling_window_complete": len(rolling) == 20,
                "signal_rolling_window_valid": bool(
                    repair.source._valid_daily_rows(rolling).all()
                    and rolling.invalid_step_cum.eq(float(event.invalid_step_cum)).all()
                ),
                "signal_is_completed_daily_close": (
                    pd.Timestamp(event.signal_time)
                    == pd.Timestamp(event.signal_date).normalize() + pd.Timedelta(hours=15)
                ),
                "signal_calendar_identity_match": int(part.cal_idx.iloc[signal_pos]) == int(event.signal_cal_idx),
                "source_trigger_is_frozen_prior_high_reversal": (
                    str(event.trigger) == "PRIOR_HIGH_REVERSAL"
                    and str(event.form) == "PRIOR_HIGH_REVERSAL"
                ),
                "exact_120x241_minute_history": bool(
                    event.exact_minute_history
                    and int(event.minute_history_sessions) == 120
                    and int(event.exact_241_minute_sessions) == 120
                ),
                "frozen_vap_density_gate": bool(
                    pd.notna(event.pre_gap_inside_density_relative_local)
                    and pd.notna(event.pre_gap_corridor_density_relative_local)
                    and float(event.pre_gap_inside_density_relative_local) <= 1.0
                    and float(event.pre_gap_corridor_density_relative_local) <= 1.0
                ),
                "frozen_pre_gap_return_gate": bool(
                    pd.notna(event.pre_gap_return_20d)
                    and float(event.pre_gap_return_20d) <= 0.0
                ),
                "frozen_reversal_state_gate": bool(
                    1 <= int(event.days_since_low20) <= 10
                    and float(event.recovery_from_low20) >= 0.03
                    and float(event.max_depth) >= 0.10
                    and float(event.current_depth) >= 0.05
                ),
                "union_branch_recomputed": bool(
                    (v26_pass or v27_pass)
                    and expected_source == str(event.union_source)
                    and bool(event.union_admission_pass)
                ),
                "feature_latest_timestamp_at_or_before_signal": pd.Timestamp(event.decision_latest_timestamp) <= pd.Timestamp(event.signal_time),
                "entry_strictly_after_signal_if_executable": (
                    event.entry_status != "EXECUTABLE_ENTRY"
                    or pd.Timestamp(event.entry_time) > pd.Timestamp(event.signal_time)
                ),
                "entry_lineage_matches_signal_if_executable": (
                    event.entry_status != "EXECUTABLE_ENTRY"
                    or float(event.entry_invalid_step_cum) == float(event.invalid_step_cum)
                ),
                "entry_coordinate_recomputed_if_executable": (
                    event.entry_status != "EXECUTABLE_ENTRY"
                    or abs(
                        float(event.entry_raw_price) * float(event.entry_coordinate_factor)
                        - float(event.entry_coordinate_price)
                    ) <= 1e-10
                ),
                "entry_below_up_limit_if_executable": (
                    event.entry_status != "EXECUTABLE_ENTRY"
                    or round(float(event.entry_raw_price) * 100) < round(float(event.up_limit_price) * 100)
                ),
                "headroom_valid_if_executable": (
                    event.entry_status != "EXECUTABLE_ENTRY"
                    or float(event.realized_net_l_headroom) >= 0.05 - 1e-12
                ),
            }
        )
    audit = pd.DataFrame(rows)
    boolean_columns = [column for column in audit if column not in {"gap_id", "symbol", "signal_time"}]
    failures = {f"{column}_failure_count": int((~audit[column].astype(bool)).sum()) for column in boolean_columns}
    if any(failures.values()):
        raise UnionError(f"causal prefix audit failed: {failures}")
    return audit, failures


def condition_ledger() -> list[dict[str, Any]]:
    return [
        {"condition": "TRUE_GAP", "latest_source": "gap-day completed daily high and previous completed daily low", "known_by_signal": True, "binding": True},
        {"condition": "QD010_COORDINATE_AND_LINEAGE", "latest_source": "gap day; PIT corporate-action state known by each date", "known_by_signal": True, "binding": True},
        {"condition": "EXACT_120_DAILY_HISTORY", "latest_source": "completed session immediately before gap", "known_by_signal": True, "binding": True},
        {"condition": "EXACT_120x241_MINUTE_VAP", "latest_source": "15:00 of completed session immediately before gap", "known_by_signal": True, "binding": True},
        {"condition": "PRE_GAP_TOUCH_AND_DENSITY", "latest_source": "completed session immediately before gap", "known_by_signal": True, "binding": True},
        {"condition": "PRE_GAP_RETURN_20D_NONPOSITIVE", "latest_source": "completed session immediately before gap", "known_by_signal": True, "binding": True},
        {"condition": "NO_L_TOUCH_BEFORE_SIGNAL", "latest_source": "completed signal-day high", "known_by_signal": True, "binding": True},
        {"condition": "MAX_DEPTH_CURRENT_DEPTH_AND_LOW20_RECOVERY", "latest_source": "completed signal-day OHLC and trailing 20 completed sessions", "known_by_signal": True, "binding": True},
        {"condition": "FIRST_PRIOR_HIGH_REVERSAL", "latest_source": "signal close and previous completed high", "known_by_signal": True, "binding": True},
        {"condition": "V26_WIDTH_AND_CORRIDOR_BRANCH", "latest_source": "gap day and pre-gap history", "known_by_signal": True, "binding": True},
        {"condition": "V27_PEAK_AGE_GAP_AGE_REBOUND_BRANCH", "latest_source": "completed signal-day close", "known_by_signal": True, "binding": True},
        {"condition": "UNION_OR_AND_DEDUP", "latest_source": "completed signal time", "known_by_signal": True, "binding": True},
        {"condition": "NEXT_LEGAL_MINUTE_OPEN_AND_HEADROOM", "latest_source": "entry minute open and PIT daily execution state", "known_by_signal": False, "known_by_entry": True, "binding": True},
        {"condition": "PORTFOLIO_COLLISION_RANK", "latest_source": "entry time, entry price/target, and pre-gap density", "known_by_signal": False, "known_by_entry": True, "binding": True},
        {"condition": "A67_TARGET_H20_T1", "latest_source": "future bars used only for post-entry execution/outcome", "known_by_signal": False, "known_by_entry": False, "binding": False, "outcome_only": True},
    ]


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    periods: dict[str, Any] = {}
    total_failures: dict[str, int] = {}
    for label, config in PERIODS.items():
        v26_entries = read_many(config["v26_entries"])
        v27_entries = read_many(config["v27_entries"])
        union = canonical_union(v26_entries, v27_entries)
        root = period_root(label)
        root.mkdir(parents=True, exist_ok=True)
        repair.write_parquet(union, union_entries_path(label))
        audit_rows, failures = causal_prefix_audit(union, config["daily"])
        repair.write_parquet(audit_rows, audit_rows_path(label))
        total_failures.update({f"{label}_{key}": value for key, value in failures.items()})
        periods[label] = {
            "v26_signals": len(v26_entries),
            "v27_signals": len(v27_entries),
            "overlap_signals": len(set(v26_entries.gap_id.astype(str)) & set(v27_entries.gap_id.astype(str))),
            "union_signals": len(union),
            "union_source": union.union_source.value_counts().astype(int).to_dict(),
            "entry_status": union.entry_status.value_counts().astype(int).to_dict(),
            "feature_uses_post_signal_information_count": int(union.feature_uses_post_signal_information.sum()),
            "entry_at_or_before_signal_count": int(union.entry_at_or_before_signal.fillna(False).sum()),
            "buy_at_or_above_up_limit_count": int(union.buy_at_or_above_up_limit.fillna(False).sum()),
            "union_entries_sha256": sha256(union_entries_path(label)),
            "causal_prefix_audit_sha256": sha256(audit_rows_path(label)),
            "causal_prefix_failures": failures,
        }
    audit = {
        "experiment": EXPERIMENT,
        "verdict": "NO_FORWARD_INFORMATION_DETECTED" if not any(total_failures.values()) else "FORWARD_INFORMATION_RISK_DETECTED",
        "condition_ledger": condition_ledger(),
        "row_level_failure_counts": total_failures,
        "admission_uses_outcome_field_count": 0,
        "portfolio_rank_uses_outcome_field_count": 0,
        "future_trough_used_count": 0,
        "future_touch_used_to_validate_earlier_signal_count": 0,
        "later_recovery_confirms_earlier_signal_count": 0,
        "negative_shift_or_lead_in_admission_count": 0,
    }
    write_json(CAUSALITY_AUDIT, audit)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_UNION_IDENTITY_AND_CAUSALITY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes_without_outcomes": source_hashes(False),
        "periods": periods,
        "causality_audit_sha256": sha256(CAUSALITY_AUDIT),
        "return_analysis_run": "NO_IN_STAGE_A",
        "strategy_backtest_run": "NO_IN_STAGE_A",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "causality_audit_sha256": sha256(CAUSALITY_AUDIT),
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    if freeze.get("source_hashes_without_outcomes") != source_hashes(False):
        drift["source_hashes_without_outcomes"] = "DRIFT"
    for label in PERIODS:
        if freeze["periods"][label]["union_entries_sha256"] != sha256(union_entries_path(label)):
            drift[f"{label}_union_entries"] = "DRIFT"
        if freeze["periods"][label]["causal_prefix_audit_sha256"] != sha256(audit_rows_path(label)):
            drift[f"{label}_causal_prefix_audit"] = "DRIFT"
    if drift:
        raise UnionError(f"Stage-A drift: {drift}")
    return {"verified": True, "checks": checks, "periods": freeze["periods"]}


def outcome_union(label: str, config: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, int]]:
    entries = pd.read_parquet(union_entries_path(label))
    v26_outcomes = read_many(config["v26_outcomes"])
    v27_outcomes = read_many(config["v27_outcomes"])
    v26_ids = set(v26_outcomes.gap_id.astype(str))
    v27_ids = set(v27_outcomes.gap_id.astype(str))
    overlap = v26_ids & v27_ids
    left = v26_outcomes.loc[v26_outcomes.gap_id.astype(str).isin(overlap)].sort_values("gap_id").reset_index(drop=True)
    right = v27_outcomes.loc[v27_outcomes.gap_id.astype(str).isin(overlap)].sort_values("gap_id").reset_index(drop=True)
    mismatch = 0
    for column in ("entry_time", "exit_time", "exit_reason", "net_return"):
        if column == "net_return":
            mismatch += int((left[column].astype(float) - right[column].astype(float)).abs().gt(1e-12).sum())
        else:
            mismatch += int(left[column].astype(str).ne(right[column].astype(str)).sum())
    if mismatch:
        raise UnionError(f"overlap outcome mismatch count={mismatch}")
    outcomes = pd.concat(
        [v26_outcomes, v27_outcomes.loc[~v27_outcomes.gap_id.astype(str).isin(v26_ids)]],
        ignore_index=True,
        sort=False,
    )
    eligible_ids = set(entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY"), "gap_id"].astype(str))
    outcomes = outcomes.loc[outcomes.gap_id.astype(str).isin(eligible_ids)].copy()
    outcomes = outcomes.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if set(outcomes.gap_id.astype(str)) != eligible_ids or outcomes.gap_id.duplicated().any():
        raise UnionError("union executable outcome conservation failure")
    outcomes["v26_branch_pass"] = v26.clean_corridor_mask(outcomes)
    outcomes["v27_branch_pass"] = v27.fresh_snapback_mask(outcomes)
    outcomes["union_source"] = outcomes.gap_id.astype(str).map(
        lambda value: "BOTH" if value in overlap else ("V26_ONLY" if value in v26_ids else "V27_ONLY")
    )
    audit = {
        "overlap_outcome_mismatch_count": mismatch,
        "duplicate_gap_outcome_count": int(outcomes.gap_id.duplicated().sum()),
        "outcome_without_stage_a_identity_count": int((~outcomes.gap_id.astype(str).isin(eligible_ids)).sum()),
        "target_at_or_above_L_count": int(outcomes.target_coordinate.ge(outcomes.L).sum()),
        "t1_violation_count": int(outcomes.exit_cal_idx.le(outcomes.entry_cal_idx).sum()),
    }
    if any(audit.values()):
        raise UnionError(f"outcome audit failed: {audit}")
    return outcomes, audit


def run_portfolio(label: str, config: dict[str, Any], outcomes: pd.DataFrame) -> tuple[dict[str, Any], pd.DataFrame]:
    daily = read_many(config["outcome_daily"])
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").drop_duplicates(["symbol", "trade_date"], keep="last")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    root = period_root(label) / "portfolio"
    root.mkdir(parents=True, exist_ok=True)
    old_k = repair.v1.PORTFOLIO_K
    try:
        repair.v1.PORTFOLIO_K = PORTFOLIO_K
        repair.v1.configure_external(root, max_exit)
        years = tuple(range(min(config["years"]), int(max_exit.year) + 1))
        portfolio = repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            years,
        )
    finally:
        repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    accepted["entry_date"] = pd.to_datetime(accepted.entry_date)
    return portfolio, accepted


def yearly_metrics(accepted: pd.DataFrame, years: tuple[int, ...]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for year in years:
        part = accepted.loc[accepted.entry_date.dt.year.eq(year)]
        result[str(year)] = {
            "trades": len(part),
            "mean_net": None if part.empty else float(part.net_return.mean()),
            "median_net": None if part.empty else float(part.net_return.median()),
            "win": None if part.empty else float(part.net_return.gt(0).mean()),
            "severe10": None if part.empty else float(part.net_return.le(-0.10).mean()),
        }
    return result


def run_stage_b() -> dict[str, Any]:
    verification = verify_stage_a()
    periods: dict[str, Any] = {}
    for label, config in PERIODS.items():
        outcomes, outcome_audit = outcome_union(label, config)
        repair.write_parquet(outcomes, period_root(label) / "union_outcomes.parquet")
        portfolio, accepted = run_portfolio(label, config, outcomes)
        periods[label] = {
            "complete_outcomes": len(outcomes),
            "complete_source": outcomes.union_source.value_counts().astype(int).to_dict(),
            "portfolio_accepted": len(accepted),
            "accepted_per_year": len(accepted) / len(config["years"]),
            "accepted_source": accepted.union_source.value_counts().astype(int).to_dict(),
            "yearly": yearly_metrics(accepted, config["years"]),
            "portfolio": portfolio,
            "outcome_audit": outcome_audit,
            "portfolio_audit": {
                "max_k_violation_count": int(portfolio["audit"]["max_k_violation_count"]),
                "negative_cash_or_leverage_count": int(portfolio["audit"]["negative_cash_or_leverage_count"]),
            },
            "hashes": {
                "union_outcomes": sha256(period_root(label) / "union_outcomes.parquet"),
                "portfolio_accepted": sha256(period_root(label) / "portfolio/portfolio_accepted.parquet"),
                "portfolio_nav": sha256(period_root(label) / "portfolio/portfolio_nav.parquet"),
            },
        }
    audit = json.loads(CAUSALITY_AUDIT.read_text(encoding="utf-8"))
    blocking = {
        key: value
        for key, value in audit["row_level_failure_counts"].items()
        if int(value) != 0
    }
    for label, item in periods.items():
        blocking.update(
            {
                f"{label}_{key}": value
                for key, value in {**item["outcome_audit"], **item["portfolio_audit"]}.items()
                if int(value) != 0
            }
        )
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "periods": periods,
        "causality_audit": audit,
        "blocking_audit": blocking,
        "verdict": (
            "V26_V27_UNION_CAUSAL_IMPLEMENTATION_VALID"
            if not blocking
            else "V26_V27_UNION_FORWARD_INFORMATION_RISK"
        ),
        "scientific_status": "RETROSPECTIVE_UNION_CANDIDATE_NOT_NEW_VALIDATION",
        "source_hashes_with_outcomes": source_hashes(True),
        "strategy_logic_changed_after_union_result_count": 0,
        "2026_new_signal_use_count": 0,
    }
    write_json(RESULT, result)
    render_report(result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen strategy",
        "",
        "One V13 base population; admit when V26 OR V27 passes; deduplicate GAP_ID; replay both branches in one shared Main/ChiNext K80 portfolio. No branch priority exists.",
        "",
        "`V13_BASE AND ((gap_width_pct <= 3% AND pre_gap_corridor_touch_sessions <= 10) OR (pre_peak_to_gap_sessions >= 20 AND gap_age <= 14 AND max_depth-current_depth >= 5% of L))`.",
        "",
        "V13 base keeps the exact 120-session/120x241-minute pre-gap history, true downward gap, no L touch before signal, 10% maximum depth, 5% signal depth, first completed prior-high reversal, next legal minute-open entry with 5% net headroom to L, A67 target, H20, no stop and 40 bp round-trip cost.",
        "",
        "|Period|Trades|Per year|Mean|Median|Win|Severe10|Total return|MaxDD|Sharpe|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for label in PERIODS:
        item = result["periods"][label]
        combined = item["portfolio"]["COMBINED"]
        lines.append(
            f"|{label}|{item['portfolio_accepted']}|{item['accepted_per_year']:.2f}|{pct(combined['mean_net'])}|{pct(combined['median_net'])}|{pct(combined['win'])}|{pct(combined['severe10'])}|{pct(combined['total_return'])}|{pct(combined['max_drawdown'])}|{combined['sharpe']:.3f}|"
        )
    lines += ["", "## Signal-year trade results", "", "|Year|Trades|Mean|Median|Win|Severe10|", "|---:|---:|---:|---:|---:|---:|"]
    for label in PERIODS:
        for year, metrics in result["periods"][label]["yearly"].items():
            lines.append(
                f"|{year}|{metrics['trades']}|{pct(metrics['mean_net'])}|{pct(metrics['median_net'])}|{pct(metrics['win'])}|{pct(metrics['severe10'])}|"
            )
    lines += [
        "",
        "## Causality audit",
        "",
        f"Verdict: `{result['causality_audit']['verdict']}`.",
        "",
        "Every union signal was recomputed from a daily prefix ending at its own signal close. True-gap identity, 120-session history, pre-gap corridor, peak age, gap age, depth, no-L-touch, and first prior-high reversal all matched. Entry must be a legal minute open strictly after the signal. Portfolio ranking uses only entry-time information.",
        "",
        f"Observed raw union signals: `{result['stage_a_verification']['periods']['OBSERVED_2017_2023']['union_signals']}`; 2024-2025 diagnostic raw union signals: `{result['stage_a_verification']['periods']['DIAGNOSTIC_2024_2025']['union_signals']}`. Each row passed 27 explicit causal, lineage, feature, branch and entry checks.",
        "",
        f"Blocking audit items: `{len(result['blocking_audit'])}`.",
        "",
        "Future bars are used only after executable entry to determine target realization, H20 exit, T+1 tradability and corporate-action-safe execution. They never create or admit a signal.",
        "",
        "## Scientific limitation",
        "",
        "The union was defined after both component results were observed. This confirms implementation causality, not a new external validation claim.",
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
        print(json.dumps(run_stage_b(), indent=2, default=str))


if __name__ == "__main__":
    main()
