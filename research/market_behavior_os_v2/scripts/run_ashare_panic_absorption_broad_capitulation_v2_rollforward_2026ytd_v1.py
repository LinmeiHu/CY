#!/usr/bin/env python3
# ruff: noqa: E501
"""Mechanical annual roll-forward of frozen broad panic absorption V2.

Stage ``freeze`` first proves the frozen 2024/2025 detector, cluster selection,
and replay semantics, then freezes mature 2026 identities without reading their
outcomes.  Stage ``evaluate`` verifies that freeze before attaching the fixed
T10/H20/no-stop replay through the registered 2026-09-04 data end.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_panic_absorption_broad_capitulation_v2 as parent,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1 as coordinate,
)


ROOT = Path(__file__).resolve().parents[3]
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-V2-ROLLFORWARD-2026YTD-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

ROLL_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_panic_absorption_broad_capitulation_v2_rollforward_2026ytd_v1"
)
STAGE_A = ROLL_ROOT / "stage_a"
STAGE_B = ROLL_ROOT / "stage_b"
DETECTOR_DAILY = STAGE_A / "detector_daily_2025q4_through_mature_cutoff.parquet"
RAW_2026 = STAGE_A / "raw_candidates_2026_mature.parquet"
SELECTED_2026 = STAGE_A / "selected_candidates_2026_mature.parquet"
STAGE_A_FREEZE = STAGE_A / "stage_a_freeze.json"
OUTCOME_DAILY = STAGE_B / "outcome_daily_2025q4_2026ytd.parquet"
FUTURE_PATHS = STAGE_B / "future_paths_2026_mature.parquet"
OUTCOMES_2026 = STAGE_B / "outcomes_2026_mature.parquet"
EXTERNAL_RESULT = STAGE_B / "result.json"

CY033_ROOT = Path(
    "/Users/linmei/Documents/CY/data/registered_inputs/"
    "CY-033-PIT-B-DAILY-2018-20260904-V1"
)
CY033_MANIFEST = CY033_ROOT / "asset_manifest.json"
REGISTRY = ROOT / "configs/data_asset_registry.json"
CURRENT_DAILY = parent.CURRENT_DAILY
DATA_END = pd.Timestamp("2026-09-04")
COORDINATE_OVERLAP_END = pd.Timestamp("2026-03-31")
DETECTOR_START = pd.Timestamp("2025-10-01")
PROFILE = parent.PROFILE
ABS_TOL = 1e-12
BOARD_PREFIXES = ("000", "001", "002", "003", "300", "301", "302", "600", "601", "603", "605")

HISTORICAL_CANDIDATES = parent.DEV_CANDIDATES
HISTORICAL_OUTCOMES = parent.DEV_OUTCOMES
FROZEN_2024_RAW = parent.FROZEN_2024
FROZEN_2024_SELECTED = parent.SELECTED_2024
FROZEN_2024_OUTCOMES = parent.OUTCOMES_2024
FROZEN_2025_ROOT = parent.EXT_ROOT / "fresh_2025"
FROZEN_2025_RAW = FROZEN_2025_ROOT / "raw_candidates.parquet"
FROZEN_2025_SELECTED = FROZEN_2025_ROOT / "selected_candidates.parquet"
FROZEN_2025_OUTCOMES = FROZEN_2025_ROOT / "outcomes.parquet"
PARENT_2025_FREEZE = OS_ROOT / (
    "experiments/ASHARE-PANIC-ABSORPTION-BROAD-CAPITULATION-"
    "V2-2025-EXTENSION_freeze.json"
)
COORDINATE_RUNNER = Path(coordinate.__file__)

DAILY_COLUMNS = [
    "trade_date", "cal_idx", "symbol", "sleeve", "open", "high", "low", "close",
    "volume", "amount", "turnover_fraction", "is_st", "industry", "causal_industry",
    "trade_status", "current_day_data_tradable", "up_limit_price", "down_limit_price",
    "market_rule_valid", "corporate_action_count", "corporate_action_valid",
    "corporate_action_blocking", "industry_valid", "historical_identity_valid", "hard_valid",
    "available_at", "decision_at", "history_valid", "current_valid", "adjusted_close",
    "invalid_step_cum", "coordinate_factor", "coord_open", "coord_high", "coord_low",
    "coord_close", "prior_coord_close", "snapshot_id",
]

RAW_FIELDS = [
    "open", "high", "low", "close", "volume", "amount", "turnover_fraction",
    "trade_status", "is_st", "up_limit_price", "down_limit_price", "industry",
    "corporate_action_count", "corporate_action_valid", "corporate_action_blocking",
    "market_rule_valid", "industry_valid", "historical_identity_valid", "hard_valid",
    "current_day_data_tradable", "available_at", "decision_at",
]


class RollforwardError(RuntimeError):
    """Fail closed on any source, identity, timing, or replay drift."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RollforwardError(message)


def sha256(path: Path) -> str:
    require(path.is_file(), f"missing required file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing JSON: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False, default=str) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        temporary.unlink()
    connection = duckdb.connect()
    connection.register("frame", frame)
    connection.execute(
        f"COPY frame TO '{temporary.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)"
    )
    connection.close()
    temporary.replace(path)


def cy033_path(year: int) -> Path:
    return CY033_ROOT / f"daily/partition_year={year}/data_0.parquet"


def _source_paths() -> dict[str, Path]:
    return {
        "parent_contract": parent.CONTRACT,
        "parent_rule_freeze": parent.RULE_FREEZE,
        "parent_runner": Path(parent.__file__),
        "parent_2025_extension_freeze": PARENT_2025_FREEZE,
        "historical_frozen_candidates": HISTORICAL_CANDIDATES,
        "historical_frozen_outcomes": HISTORICAL_OUTCOMES,
        "frozen_2024_raw": FROZEN_2024_RAW,
        "frozen_2024_selected": FROZEN_2024_SELECTED,
        "frozen_2024_outcomes": FROZEN_2024_OUTCOMES,
        "frozen_2025_raw": FROZEN_2025_RAW,
        "frozen_2025_selected": FROZEN_2025_SELECTED,
        "frozen_2025_outcomes": FROZEN_2025_OUTCOMES,
        "frozen_coordinate_daily_through_2026q1": CURRENT_DAILY,
        "coordinate_reconstruction_runner": COORDINATE_RUNNER,
        "cy033_manifest": CY033_MANIFEST,
        "cy033_2024_partition": cy033_path(2024),
        "cy033_2025_partition": cy033_path(2025),
        "cy033_2026_partition": cy033_path(2026),
    }


def verify_sources() -> dict[str, Any]:
    spec = read_json(SPEC)
    require(spec.get("experiment") == EXPERIMENT, "roll-forward specification identity drift")
    require(spec.get("source_strategy") == parent.EXPERIMENT, "parent strategy identity drift")
    execution = spec.get("frozen_execution", {})
    require(execution.get("entry") == "first legal non-limit-up open in signal+1 through signal+3", "entry rule drift")
    require(execution.get("profit_target") == "+10% from coordinate entry, evaluated only after the entry session", "target drift")
    require(execution.get("time_stop") == "H20 decision followed by the first legal sellable open", "horizon drift")
    require(execution.get("failure_stop") == "NONE", "failure stop drift")
    require(math.isclose(float(execution.get("round_trip_cost")), 0.004, rel_tol=0.0, abs_tol=ABS_TOL), "cost drift")
    expected = spec.get("source_hashes_sha256", {})
    paths = _source_paths()
    actual = {name: sha256(path) for name, path in paths.items()}
    drift = {
        name: {"expected": expected.get(name), "actual": value}
        for name, value in actual.items()
        if expected.get(name) != value
    }
    require(not drift, f"frozen/registered source drift: {drift}")

    registry = read_json(REGISTRY)
    assets = [item for item in registry.get("assets", []) if item.get("asset_id") == "CY-033"]
    require(len(assets) == 1, "CY-033 must resolve exactly once in registry")
    asset = assets[0]
    require(asset.get("status") == "RESEARCH_CONDITIONAL", "CY-033 status is not research-conditional")
    require(asset.get("physical_state") == "MATERIALIZED", "CY-033 is not materialized")
    require(Path(str(asset.get("location"))) == CY033_ROOT, "CY-033 location drift")
    require(asset.get("coverage", {}).get("end") == str(DATA_END.date()), "CY-033 coverage end drift")
    require(asset.get("quality_evidence", {}).get("gate_pass") is True, "CY-033 quality gate is not PASS")
    require(asset.get("lineage", {}).get("manifest_sha256") == actual["cy033_manifest"], "registry manifest hash drift")
    require(asset.get("lineage", {}).get("record_available_at") is True, "CY-033 record availability missing")
    require(asset.get("lineage", {}).get("record_snapshot_id") is True, "CY-033 snapshot lineage missing")

    manifest = read_json(CY033_MANIFEST)
    require(manifest.get("asset_id") == "CY-033" and manifest.get("status") == "PASS", "CY-033 manifest not active")
    require(manifest.get("quality_evidence", {}).get("gate_pass") is True, "CY-033 manifest quality gate failed")
    require(manifest.get("snapshot_id") == asset.get("lineage", {}).get("snapshot_id"), "CY-033 snapshot drift")
    listed = {str(item.get("path")): item for item in manifest.get("files", [])}
    for year in (2024, 2025, 2026):
        path = cy033_path(year)
        relative = str(path.relative_to(CY033_ROOT))
        require(listed.get(relative, {}).get("sha256") == actual[f"cy033_{year}_partition"], f"CY-033 manifest partition drift: {year}")
    return {
        "spec_sha256": sha256(SPEC),
        "registry_sha256_at_run": sha256(REGISTRY),
        "registered_snapshot_id": manifest["snapshot_id"],
        "source_hashes_sha256": actual,
    }


def raw_overlap_audit(year: int) -> dict[str, Any]:
    comparisons = ",\n".join(
        f"sum(CASE WHEN o.{field} IS DISTINCT FROM n.{field} THEN 1 ELSE 0 END)::BIGINT AS {field}_mismatch"
        for field in RAW_FIELDS
    )
    prefixes = ",".join(f"'{item}'" for item in BOARD_PREFIXES)
    query = f"""
    WITH o AS (
      SELECT 1 AS present, CAST(trade_date AS DATE) AS trade_date,symbol,{','.join(RAW_FIELDS)}
      FROM read_parquet('{CURRENT_DAILY.as_posix()}')
      WHERE year(trade_date)={year}
    ), n AS (
      SELECT 1 AS present, CAST(trade_date AS DATE) AS trade_date,symbol,{','.join(RAW_FIELDS)}
      FROM read_parquet('{cy033_path(year).as_posix()}')
      WHERE substr(symbol,1,3) IN ({prefixes})
    ), j AS (
      SELECT o.*,n.* EXCLUDE (trade_date,symbol)
      FROM o FULL OUTER JOIN n USING(symbol,trade_date)
    )
    SELECT count(*)::BIGINT AS union_rows,
      sum(CASE WHEN o.present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_frozen,
      sum(CASE WHEN n.present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_registered,
      {comparisons}
    FROM j
    """
    # Qualifying duplicate names from a FULL JOIN are clearer with explicit aliases.
    field_select = ",".join(f"o.{field} AS o_{field},n.{field} AS n_{field}" for field in RAW_FIELDS)
    comparisons = ",\n".join(
        f"sum(CASE WHEN o_{field} IS DISTINCT FROM n_{field} THEN 1 ELSE 0 END)::BIGINT AS {field}_mismatch"
        for field in RAW_FIELDS
    )
    query = f"""
    WITH o AS (
      SELECT 1 AS present, CAST(trade_date AS DATE) AS trade_date,symbol,{','.join(RAW_FIELDS)}
      FROM read_parquet('{CURRENT_DAILY.as_posix()}') WHERE year(trade_date)={year}
    ), n AS (
      SELECT 1 AS present, CAST(trade_date AS DATE) AS trade_date,symbol,{','.join(RAW_FIELDS)}
      FROM read_parquet('{cy033_path(year).as_posix()}')
      WHERE substr(symbol,1,3) IN ({prefixes})
    ), j AS (
      SELECT o.present AS old_present,n.present AS new_present,{field_select}
      FROM o FULL OUTER JOIN n USING(symbol,trade_date)
    )
    SELECT count(*)::BIGINT AS union_rows,
      sum(CASE WHEN old_present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_frozen,
      sum(CASE WHEN new_present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_registered,
      {comparisons}
    FROM j
    """
    row = duckdb.connect().execute(query).fetch_df().iloc[0].to_dict()
    payload = {key: int(value) for key, value in row.items()}
    blocking = {key: value for key, value in payload.items() if key != "union_rows" and value != 0}
    require(not blocking, f"CY-033 raw overlap drift {year}: {blocking}")
    payload["exact_match"] = True
    return payload


def compare_frames(reference: pd.DataFrame, rebuilt: pd.DataFrame, key: str, columns: list[str], label: str) -> dict[str, Any]:
    left = reference.copy()
    right = rebuilt.copy()
    require(key in left and key in right, f"{label}: missing comparison key")
    require(not left[key].duplicated().any() and not right[key].duplicated().any(), f"{label}: duplicate identity")
    left_ids = set(left[key].astype(str))
    right_ids = set(right[key].astype(str))
    require(left_ids == right_ids, f"{label}: identity mismatch missing={len(left_ids-right_ids)} extra={len(right_ids-left_ids)}")
    left[key] = left[key].astype(str)
    right[key] = right[key].astype(str)
    left = left.set_index(key).sort_index()
    right = right.set_index(key).sort_index()
    numeric_max: dict[str, float] = {}
    for column in columns:
        require(column in left and column in right, f"{label}: missing field {column}")
        if "date" in column or column.endswith("_at"):
            a = pd.to_datetime(left[column], errors="coerce")
            b = pd.to_datetime(right[column], errors="coerce")
            mismatch = ~((a.eq(b)) | (a.isna() & b.isna()))
        elif pd.api.types.is_numeric_dtype(left[column]) or pd.api.types.is_numeric_dtype(right[column]):
            a = pd.to_numeric(left[column], errors="coerce").to_numpy(dtype=float)
            b = pd.to_numeric(right[column], errors="coerce").to_numpy(dtype=float)
            difference = np.abs(a - b)
            finite = difference[np.isfinite(difference)]
            numeric_max[column] = 0.0 if not len(finite) else float(finite.max())
            mismatch = ~np.isclose(a, b, rtol=0.0, atol=ABS_TOL, equal_nan=True)
        else:
            a = left[column].astype("string")
            b = right[column].astype("string")
            mismatch = ~((a.eq(b)).fillna(False) | (a.isna() & b.isna()))
        count = int(np.asarray(mismatch).sum())
        require(count == 0, f"{label}: {column} mismatch count={count}")
    return {
        "reference_rows": int(len(left)),
        "rebuilt_rows": int(len(right)),
        "identity_match": True,
        "field_match": True,
        "numeric_max_absolute_difference": numeric_max,
    }


def build_paths(candidates: pd.DataFrame, daily: Path, end: pd.Timestamp) -> pd.DataFrame:
    connection = duckdb.connect()
    connection.register(
        "candidate_ids",
        candidates[["event_id", "symbol", "sleeve", "signal_date", "cal_idx", "invalid_step_cum"]],
    )
    result = connection.execute(
        f"""
        SELECT c.event_id,c.symbol,c.sleeve,c.signal_date,
          c.cal_idx AS signal_cal_idx,c.invalid_step_cum AS signal_invalid_step_cum,
          d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,
          d.coordinate_factor,d.invalid_step_cum,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,
          d.corporate_action_valid,d.corporate_action_blocking,d.hard_valid,
          d.up_limit_price,d.down_limit_price
        FROM candidate_ids c
        JOIN read_parquet('{daily.as_posix()}') d
          ON c.symbol=d.symbol AND d.cal_idx>c.cal_idx
        WHERE d.trade_date<=DATE '{end:%Y-%m-%d}'
        ORDER BY c.event_id,d.cal_idx
        """
    ).fetch_df()
    connection.close()
    result["trade_date"] = pd.to_datetime(result.trade_date)
    return result


def replay(candidates: pd.DataFrame, paths: pd.DataFrame, incomplete_label: str | None = None) -> pd.DataFrame:
    groups = {str(key): part for key, part in paths.groupby("event_id", sort=False)}
    result = pd.DataFrame(
        [
            parent.replay_one(candidate, groups.get(str(candidate.event_id), pd.DataFrame()))
            for candidate in candidates.itertuples(index=False)
        ]
    )
    if incomplete_label is not None and "status" in result:
        result.loc[result.status.eq("INCOMPLETE_BY_2025_03_31"), "status"] = incomplete_label
    for column in ("signal_date", "entry_date", "exit_date"):
        if column in result:
            result[column] = pd.to_datetime(result[column])
    return result


def reproduce_year(year: int) -> dict[str, Any]:
    start = "2023-10-01" if year == 2024 else "2024-10-01"
    connection = duckdb.connect()
    high = connection.execute(parent.candidate_query(CURRENT_DAILY, start, f"{year}-12-31")).fetch_df()
    connection.close()
    raw = parent.apply_cooldown(high)
    raw = raw.loc[raw.signal_date.dt.year.eq(year)].copy()
    raw["same_date_signal_count"] = raw.groupby("signal_date").event_id.transform("size")
    selected = raw.loc[raw.same_date_signal_count.ge(2)].copy().reset_index(drop=True)
    raw = raw.reset_index(drop=True)

    raw_reference_path = FROZEN_2024_RAW if year == 2024 else FROZEN_2025_RAW
    selected_reference_path = FROZEN_2024_SELECTED if year == 2024 else FROZEN_2025_SELECTED
    outcome_reference_path = FROZEN_2024_OUTCOMES if year == 2024 else FROZEN_2025_OUTCOMES
    raw_reference = parent.read_parquet(raw_reference_path)
    selected_reference = parent.read_parquet(selected_reference_path)
    candidate_columns = [column for column in raw_reference.columns if column != "event_id"]
    raw_audit = compare_frames(raw_reference, raw, "event_id", candidate_columns, f"{year} raw detector")
    selected_audit = compare_frames(selected_reference, selected, "event_id", candidate_columns, f"{year} cluster selection")

    tail = pd.Timestamp("2025-03-31") if year == 2024 else pd.Timestamp("2026-03-31")
    paths = build_paths(selected, CURRENT_DAILY, tail)
    outcomes = replay(selected, paths)
    outcome_reference = parent.read_parquet(outcome_reference_path)
    outcome_columns = [column for column in outcome_reference.columns if column != "event_id"]
    outcome_audit = compare_frames(outcome_reference, outcomes, "event_id", outcome_columns, f"{year} replay")
    return {
        "raw": raw_audit,
        "selected": selected_audit,
        "outcomes": outcome_audit,
        "raw_count": int(len(raw)),
        "selected_count": int(len(selected)),
        "status_counts": {str(key): int(value) for key, value in outcomes.status.value_counts().sort_index().items()},
        "all_semantics_reproduced": True,
    }


def historical_summary() -> dict[str, Any]:
    candidates = parent.read_parquet(HISTORICAL_CANDIDATES)
    candidates["signal_date"] = pd.to_datetime(candidates.signal_date)
    candidates["same_date_signal_count"] = candidates.groupby("signal_date").event_id.transform("size")
    selected = candidates.loc[candidates.same_date_signal_count.ge(2)].copy()
    outcomes = parent.read_parquet(HISTORICAL_OUTCOMES, f"profile = '{PROFILE}'")
    summary = parent.summarize(selected, outcomes, range(2014, 2022))
    summary["source_status"] = "CONSUMED_HISTORY_MECHANICAL_SUMMARY"
    summary["2021_disclosure"] = "Consumed during chart-rule formation; descriptive history, not validation."
    return summary


def load_seed(end: pd.Timestamp) -> dict[str, dict[str, Any]]:
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        WITH last_row AS (
          SELECT symbol,coordinate_factor,invalid_step_cum,current_valid
          FROM read_parquet('{CURRENT_DAILY.as_posix()}')
          WHERE trade_date<=DATE '{end:%Y-%m-%d}'
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        ), last_valid AS (
          SELECT symbol,close,coord_close
          FROM read_parquet('{CURRENT_DAILY.as_posix()}')
          WHERE trade_date<=DATE '{end:%Y-%m-%d}' AND current_valid
          QUALIFY row_number() OVER(PARTITION BY symbol ORDER BY trade_date DESC)=1
        )
        SELECT l.symbol,l.coordinate_factor AS factor,l.invalid_step_cum,
          l.current_valid AS previous_current_valid,v.close AS last_valid_raw_close,
          v.coord_close AS last_valid_coordinate_close
        FROM last_row l LEFT JOIN last_valid v USING(symbol)
        ORDER BY l.symbol
        """
    ).fetch_df()
    connection.close()
    return {
        str(row.symbol): {
            "factor": float(row.factor),
            "invalid_step_cum": float(row.invalid_step_cum),
            "previous_current_valid": False if pd.isna(row.previous_current_valid) else bool(row.previous_current_valid),
            "last_valid_raw_close": float(row.last_valid_raw_close),
            "last_valid_coordinate_close": float(row.last_valid_coordinate_close),
        }
        for row in frame.itertuples(index=False)
    }


def load_cy033(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    fields = """
      CAST(trade_date AS DATE) AS trade_date,decision_at,symbol,
      open,high,low,close,volume,amount,turnover_fraction,trade_status,is_st,
      up_limit_price,down_limit_price,industry,corporate_action_count,
      corporate_action_valid,corporate_action_blocking,share_multiplier,
      cash_per_share,rights_ratio,rights_price,market_rule_valid,industry_valid,
      historical_identity_valid,hard_valid,current_day_data_tradable,available_at,
      snapshot_id
    """
    prefixes = ",".join(f"'{item}'" for item in BOARD_PREFIXES)
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        SELECT {fields} FROM read_parquet('{cy033_path(2026).as_posix()}')
        WHERE trade_date BETWEEN DATE '{start:%Y-%m-%d}' AND DATE '{end:%Y-%m-%d}'
          AND substr(symbol,1,3) IN ({prefixes})
        ORDER BY symbol,trade_date
        """
    ).fetch_df()
    connection.close()
    require(not frame.empty, f"empty CY-033 interval {start.date()}..{end.date()}")
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    active = frame.hard_valid.fillna(False)
    bad_time = active & (
        pd.to_datetime(frame.available_at).isna()
        | pd.to_datetime(frame.decision_at).isna()
        | pd.to_datetime(frame.available_at).gt(pd.to_datetime(frame.decision_at))
    )
    require(not bad_time.any(), "hard-valid CY-033 row lacks causal availability")
    return frame


def calendar_2026() -> pd.DataFrame:
    connection = duckdb.connect()
    dates = connection.execute(
        f"SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date FROM read_parquet('{cy033_path(2026).as_posix()}') ORDER BY trade_date"
    ).fetch_df()
    old = connection.execute(
        f"""
        SELECT DISTINCT CAST(trade_date AS DATE) AS trade_date,cal_idx::BIGINT AS cal_idx
        FROM read_parquet('{CURRENT_DAILY.as_posix()}')
        WHERE year(trade_date)=2026 ORDER BY trade_date
        """
    ).fetch_df()
    connection.close()
    dates["trade_date"] = pd.to_datetime(dates.trade_date)
    old["trade_date"] = pd.to_datetime(old.trade_date)
    require(dates.trade_date.max().normalize() == DATA_END, "registered calendar does not reach data end")
    calendar = dates.merge(old, on="trade_date", how="left", validate="one_to_one")
    future = calendar.trade_date.gt(COORDINATE_OVERLAP_END)
    require(calendar.loc[~future, "cal_idx"].notna().all(), "frozen Q1 calendar overlap incomplete")
    last = int(old.cal_idx.max())
    calendar.loc[future, "cal_idx"] = np.arange(last + 1, last + 1 + int(future.sum()), dtype=np.int64)
    require(calendar.cal_idx.notna().all(), "calendar index construction incomplete")
    calendar["cal_idx"] = calendar.cal_idx.astype(np.int64)
    require(calendar.cal_idx.diff().dropna().eq(1).all(), "2026 global calendar is not contiguous")
    return calendar


def reconstruct_interval(start: pd.Timestamp, end: pd.Timestamp, seed_end: pd.Timestamp, calendar: pd.DataFrame) -> pd.DataFrame:
    raw = load_cy033(start, end)
    cal = calendar.loc[calendar.trade_date.between(start, end), ["trade_date", "cal_idx"]].copy()
    rebuilt = coordinate.reconstruct_qd010_coordinate(raw, load_seed(seed_end), cal)
    missing = sorted(set(DAILY_COLUMNS) - set(rebuilt.columns))
    require(not missing, f"reconstructed daily missing fields: {missing}")
    result = rebuilt[DAILY_COLUMNS].copy()
    result = result.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    require(not result.duplicated(["symbol", "trade_date"]).any(), "reconstructed daily duplicate key")
    return result


def coordinate_bridge_audit(calendar: pd.DataFrame) -> dict[str, Any]:
    rebuilt = reconstruct_interval(pd.Timestamp("2026-01-01"), COORDINATE_OVERLAP_END, pd.Timestamp("2025-12-31"), calendar)
    connection = duckdb.connect()
    reference = connection.execute(
        f"""
        SELECT symbol,trade_date,coordinate_factor,invalid_step_cum,history_valid,
          current_valid,coord_open,coord_high,coord_low,coord_close,prior_coord_close
        FROM read_parquet('{CURRENT_DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '2026-01-01' AND DATE '2026-03-31'
        ORDER BY symbol,trade_date
        """
    ).fetch_df()
    connection.close()
    reference["row_id"] = reference.symbol.astype(str) + "|" + pd.to_datetime(reference.trade_date).dt.strftime("%Y-%m-%d")
    rebuilt["row_id"] = rebuilt.symbol.astype(str) + "|" + pd.to_datetime(rebuilt.trade_date).dt.strftime("%Y-%m-%d")
    fields = [
        "coordinate_factor", "invalid_step_cum", "history_valid", "current_valid",
        "coord_open", "coord_high", "coord_low", "coord_close", "prior_coord_close",
    ]
    audit = compare_frames(reference, rebuilt, "row_id", fields, "2026Q1 coordinate bridge")
    audit["period"] = ["2026-01-01", "2026-03-31"]
    audit["exact_reproduction"] = True
    return audit


def old_daily_prefix() -> pd.DataFrame:
    projection = ",".join(column for column in DAILY_COLUMNS if column != "snapshot_id")
    connection = duckdb.connect()
    frame = connection.execute(
        f"""
        SELECT {projection},NULL::VARCHAR AS snapshot_id
        FROM read_parquet('{CURRENT_DAILY.as_posix()}')
        WHERE trade_date BETWEEN DATE '{DETECTOR_START:%Y-%m-%d}' AND DATE '2026-03-31'
        ORDER BY symbol,trade_date
        """
    ).fetch_df()
    connection.close()
    frame["trade_date"] = pd.to_datetime(frame.trade_date)
    return frame[DAILY_COLUMNS]


def compose_daily(end: pd.Timestamp, calendar: pd.DataFrame) -> pd.DataFrame:
    pieces = [old_daily_prefix()]
    if end > COORDINATE_OVERLAP_END:
        pieces.append(
            reconstruct_interval(
                pd.Timestamp("2026-04-01"), end, COORDINATE_OVERLAP_END, calendar
            )
        )
    result = pd.concat(pieces, ignore_index=True, sort=False)[DAILY_COLUMNS]
    result = result.sort_values(["symbol", "trade_date"], kind="mergesort").reset_index(drop=True)
    require(not result.duplicated(["symbol", "trade_date"]).any(), "composed daily duplicate key")
    require(result.trade_date.max().normalize() == end.normalize(), "composed daily does not reach requested end")
    return result


def mature_cutoff(calendar: pd.DataFrame) -> tuple[int, int, pd.Timestamp]:
    maximum = int(calendar.cal_idx.max())
    cutoff_index = maximum - 24
    match = calendar.loc[calendar.cal_idx.eq(cutoff_index), "trade_date"]
    require(len(match) == 1, "mature cutoff calendar identity failure")
    return maximum, cutoff_index, pd.Timestamp(match.iloc[0]).normalize()


def build_2026_candidates(cutoff: pd.Timestamp, cutoff_index: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    connection = duckdb.connect()
    high = connection.execute(
        parent.candidate_query(DETECTOR_DAILY, f"{DETECTOR_START:%Y-%m-%d}", f"{cutoff:%Y-%m-%d}")
    ).fetch_df()
    connection.close()
    raw = parent.apply_cooldown(high)
    raw = raw.loc[raw.signal_date.dt.year.eq(2026) & raw.cal_idx.le(cutoff_index)].copy()
    raw["same_date_signal_count"] = raw.groupby("signal_date").event_id.transform("size")
    selected = raw.loc[raw.same_date_signal_count.ge(2)].copy()
    for label, frame in (("raw", raw), ("selected", selected)):
        require(not frame.event_id.duplicated().any(), f"duplicate 2026 {label} identity")
        require(pd.to_datetime(frame.signal_date).le(cutoff).all(), f"post-cutoff 2026 {label} identity")
        require(pd.to_datetime(frame.available_at).notna().all(), f"unknown 2026 {label} availability")
        require(pd.to_datetime(frame.available_at).le(pd.to_datetime(frame.decision_at)).all(), f"post-decision 2026 {label} feature")
    return raw.reset_index(drop=True), selected.reset_index(drop=True)


def run_freeze() -> dict[str, Any]:
    require(not STAGE_A_FREEZE.exists(), f"Stage-A freeze already exists: {STAGE_A_FREEZE}")
    verified = verify_sources()
    raw_overlap = {str(year): raw_overlap_audit(year) for year in (2024, 2025)}
    semantic_overlap = {str(year): reproduce_year(year) for year in (2024, 2025)}
    history = historical_summary()
    calendar = calendar_2026()
    bridge = coordinate_bridge_audit(calendar)
    maximum_index, cutoff_index, cutoff = mature_cutoff(calendar)
    daily = compose_daily(cutoff, calendar)
    write_parquet(daily, DETECTOR_DAILY)
    raw, selected = build_2026_candidates(cutoff, cutoff_index)
    write_parquet(raw, RAW_2026)
    write_parquet(selected, SELECTED_2026)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_MATURE_2026_IDENTITY_FREEZE",
        "scientific_status": "UNCHANGED_RULE_MATURE_2026YTD_TEMPORAL_DIAGNOSTIC",
        "spec_sha256": verified["spec_sha256"],
        "runner_sha256": sha256(Path(__file__)),
        "registered_sources": verified,
        "overlap_reproduction": {
            "registered_raw_2024_2025": raw_overlap,
            "detector_cluster_outcome_2024_2025": semantic_overlap,
            "coordinate_bridge_2026q1": bridge,
            "all_required_gates_pass": True,
        },
        "consumed_history_2014_2021": history,
        "data_end": str(DATA_END.date()),
        "maximum_calendar_cal_idx": maximum_index,
        "maturity_tail_sessions": 24,
        "mature_signal_cutoff_cal_idx": cutoff_index,
        "mature_signal_cutoff": str(cutoff.date()),
        "raw_2026_mature_signals": int(len(raw)),
        "selected_2026_mature_signals": int(len(selected)),
        "selected_2026_signal_dates": int(selected.signal_date.nunique()),
        "maximum_selected_signal_date": None if selected.empty else str(selected.signal_date.max().date()),
        "new_2026_outcomes_attached": False,
        "new_2026_post_cutoff_prices_read": False,
        "rule_or_threshold_changed": False,
        "stage_a_output_hashes_sha256": {
            "detector_daily": sha256(DETECTOR_DAILY),
            "raw_candidates": sha256(RAW_2026),
            "selected_candidates": sha256(SELECTED_2026),
        },
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    freeze = read_json(STAGE_A_FREEZE)
    require(freeze.get("experiment") == EXPERIMENT, "Stage-A experiment drift")
    require(freeze.get("stage") == "OUTCOME_BLIND_MATURE_2026_IDENTITY_FREEZE", "Stage-A status drift")
    require(freeze.get("new_2026_outcomes_attached") is False, "Stage-A improperly attached 2026 outcomes")
    require(freeze.get("overlap_reproduction", {}).get("all_required_gates_pass") is True, "Stage-A overlap gate did not pass")
    verified = verify_sources()
    checks = {
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    for key, value in checks.items():
        require(freeze.get(key) == value, f"Stage-A {key} drift")
    require(freeze.get("registered_sources", {}).get("source_hashes_sha256") == verified["source_hashes_sha256"], "Stage-A source hash drift")
    outputs = {
        "detector_daily": sha256(DETECTOR_DAILY),
        "raw_candidates": sha256(RAW_2026),
        "selected_candidates": sha256(SELECTED_2026),
    }
    require(outputs == freeze.get("stage_a_output_hashes_sha256"), "Stage-A artifact drift")
    return freeze


def daily_prefix_audit(cutoff: pd.Timestamp) -> dict[str, Any]:
    fields = [column for column in DAILY_COLUMNS if column != "snapshot_id"]
    field_select = ",".join(f"a.{field} AS a_{field},b.{field} AS b_{field}" for field in fields if field not in {"symbol", "trade_date"})
    comparisons = ",".join(
        f"sum(CASE WHEN a_{field} IS DISTINCT FROM b_{field} THEN 1 ELSE 0 END)::BIGINT AS {field}_mismatch"
        for field in fields if field not in {"symbol", "trade_date"}
    )
    query = f"""
    WITH a AS (
      SELECT 1 AS present,* EXCLUDE(snapshot_id) FROM read_parquet('{DETECTOR_DAILY.as_posix()}')
    ), b AS (
      SELECT 1 AS present,* EXCLUDE(snapshot_id) FROM read_parquet('{OUTCOME_DAILY.as_posix()}')
      WHERE trade_date<=DATE '{cutoff:%Y-%m-%d}'
    ), j AS (
      SELECT a.present AS a_present,b.present AS b_present,{field_select}
      FROM a FULL OUTER JOIN b USING(symbol,trade_date)
    )
    SELECT count(*)::BIGINT AS union_rows,
      sum(CASE WHEN a_present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_detector,
      sum(CASE WHEN b_present IS NULL THEN 1 ELSE 0 END)::BIGINT AS missing_from_outcome_daily,
      {comparisons}
    FROM j
    """
    row = duckdb.connect().execute(query).fetch_df().iloc[0].to_dict()
    payload = {key: int(value) for key, value in row.items()}
    blocking = {key: value for key, value in payload.items() if key != "union_rows" and value != 0}
    require(not blocking, f"Stage-B daily prefix drift: {blocking}")
    payload["exact_match"] = True
    return payload


def annual_metrics(outcomes_2026: pd.DataFrame) -> tuple[dict[str, Any], dict[str, Any]]:
    history = historical_summary()["yearly"]
    old_candidates, old_outcomes = parent.load_old_validation_selected()
    validation = parent.summarize(old_candidates, old_outcomes, range(2022, 2024))["yearly"]
    official_2024 = parent.read_parquet(FROZEN_2024_OUTCOMES)
    official_2025 = parent.read_parquet(FROZEN_2025_OUTCOMES)
    yearly: dict[str, Any] = {**history, **validation}
    yearly["2024"] = parent.metrics(official_2024)
    yearly["2025"] = parent.metrics(official_2025)
    yearly["2026"] = parent.metrics(outcomes_2026)
    statuses = {
        "2024": {str(key): int(value) for key, value in official_2024.status.value_counts().sort_index().items()},
        "2025": {str(key): int(value) for key, value in official_2025.status.value_counts().sort_index().items()},
        "2026": {str(key): int(value) for key, value in outcomes_2026.status.value_counts().sort_index().items()},
    }
    return yearly, statuses


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}",
        "",
        "这是冻结规则的机械滚动与逐年汇总，不是参数优化，也不是新的外部验证。",
        "",
        f"数据截止 `{result['data_end']}`；2026 仅纳入信号日不晚于 `{result['mature_signal_cutoff']}`（全市场日历最大索引减 24）的成熟队列。",
        "",
        "## 冻结信号与执行",
        "",
        "母信号：精确20日跌幅不高于 -10%；开盘较前一坐标收盘不高于 -1%；创前5日新低；换手不低于前20日均值；收盘不低于前一日高点且位于日内区间上30%；非涨停收盘。V2 仅增加同一交易日独立母信号数不低于2，个股冷却严格大于20个全市场交易日。",
        "",
        "执行：信号后第1至3日首个合法非涨停开盘买入；入场日之后才检查 +10% 目标；否则 H20 决策后首个合法可卖开盘退出；无失败止损；往返40bp。",
        "",
        "## 逐信号年指标",
        "",
        "|年|信号|完成|平均净收益|中位净收益|胜率|<=-10%|目标命中|平均持有|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in range(2014, 2027):
        row = result["annual_by_signal_year"][str(year)]
        holding = "—" if row["mean_holding"] is None else f"{row['mean_holding']:.2f}"
        lines.append(
            f"|{year}|{row['signals']}|{row['completed']}|{pct(row['mean_net'])}|{pct(row['median_net'])}|{pct(row['win'])}|{pct(row['severe10'])}|{pct(row['target_hit'])}|{holding}|"
        )
    lines.extend(
        [
            "",
            "## 审计与边界",
            "",
            "2024、2025 的注册日线原始字段、detector、同日 cluster 选择及完整 replay 均在冻结 2026 身份前逐项复现；2026Q1 坐标桥逐行精确复现。2021 已在图表规则形成阶段被消费，只作描述性历史。2026 是 PIT-B 条件样本下的部分年度、成熟截止滚动诊断；截止后信号被右删失。缺失、无效、停牌、涨跌停阻塞或坐标谱系异常均不救援。",
            "",
        ]
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def run_evaluate() -> dict[str, Any]:
    freeze = verify_stage_a()
    calendar = calendar_2026()
    maximum_index, cutoff_index, cutoff = mature_cutoff(calendar)
    require(maximum_index == int(freeze["maximum_calendar_cal_idx"]), "maximum calendar index drift")
    require(cutoff_index == int(freeze["mature_signal_cutoff_cal_idx"]), "mature cutoff index drift")
    require(str(cutoff.date()) == freeze["mature_signal_cutoff"], "mature cutoff date drift")

    daily = compose_daily(DATA_END, calendar)
    write_parquet(daily, OUTCOME_DAILY)
    prefix_audit = daily_prefix_audit(cutoff)
    selected = parent.read_parquet(SELECTED_2026)
    selected["signal_date"] = pd.to_datetime(selected.signal_date)
    require(selected.signal_date.le(cutoff).all(), "post-cutoff selected identity entered Stage B")
    paths = build_paths(selected, OUTCOME_DAILY, DATA_END)
    outcomes = replay(selected, paths, "INCOMPLETE_BY_2026_09_04")

    complete = outcomes.loc[outcomes.status.eq("COMPLETED")]
    chronology = {
        "entry_at_or_before_signal": int(complete.entry_cal_idx.le(complete.signal_cal_idx).sum()),
        "exit_at_or_before_entry": int(complete.exit_cal_idx.le(complete.entry_cal_idx).sum()),
        "post_cutoff_signal": int(outcomes.signal_date.gt(cutoff).sum()),
        "exit_after_data_end": int(pd.to_datetime(complete.exit_date).gt(DATA_END).sum()),
    }
    require(not any(chronology.values()), f"2026 execution chronology failure: {chronology}")
    require(outcomes.profile.eq(PROFILE).all(), "2026 replay profile drift")
    write_parquet(paths, FUTURE_PATHS)
    write_parquet(outcomes, OUTCOMES_2026)

    yearly, status_counts = annual_metrics(outcomes)
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_OBSERVATION_UNCHANGED_RULE_ROLLFORWARD_NOT_PRISTINE_EXTERNAL_VALIDATION",
        "data_end": str(DATA_END.date()),
        "maximum_calendar_cal_idx": maximum_index,
        "mature_signal_cutoff_cal_idx": cutoff_index,
        "mature_signal_cutoff": str(cutoff.date()),
        "maturity_tail_sessions": 24,
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "stage_a_runner_sha256": freeze["runner_sha256"],
        "overlap_reproduction_passed_before_new_identity_freeze": True,
        "stage_b_detector_prefix_audit": prefix_audit,
        "annual_by_signal_year": yearly,
        "status_counts_by_signal_year": status_counts,
        "reported_annual_fields": [
            "signals", "completed", "mean_net", "median_net", "win", "severe10", "target_hit", "mean_holding"
        ],
        "frozen_signal_fields": [
            "ret20 <= -0.10", "open_gap <= -0.01", "coord_low <= prior_five_session_low",
            "turnover_fraction >= prior20_mean", "coord_close >= prior_high",
            "close_location >= 0.70", "non_upper_limit_close", "same_date_signal_count >= 2",
            "symbol_cooldown_global_sessions > 20",
        ],
        "frozen_execution": {
            "entry": "first legal non-limit-up open in signal+1..signal+3",
            "target": "+10% after entry session",
            "time_stop": "H20 decision then first legal sellable open",
            "failure_stop": None,
            "round_trip_cost": 0.004,
        },
        "execution_chronology_audit": chronology,
        "rule_threshold_execution_or_cost_changed": False,
        "rescue_or_substitution_used": False,
        "limitations": [
            "2014-2021 are consumed-history descriptive rows; 2021 is not validation evidence.",
            "2022-2025 are previously reported evidence, and 2026 is an unchanged-rule post-observation temporal diagnostic.",
            "2026 is partial-year and right-censored after the mature signal cutoff.",
            "CY-033 is PIT-B conditional on physically present registered rows, not a strict PIT-A or live-trading source.",
            "Incomplete, invalid, suspended, price-limit-blocked, and coordinate-lineage cases are not rescued.",
        ],
        "input_hashes_sha256": freeze["registered_sources"]["source_hashes_sha256"],
        "output_hashes_sha256": {
            "stage_a_freeze": sha256(STAGE_A_FREEZE),
            "detector_daily": sha256(DETECTOR_DAILY),
            "raw_candidates_2026": sha256(RAW_2026),
            "selected_candidates_2026": sha256(SELECTED_2026),
            "outcome_daily": sha256(OUTCOME_DAILY),
            "future_paths_2026": sha256(FUTURE_PATHS),
            "outcomes_2026": sha256(OUTCOMES_2026),
        },
    }
    write_json(EXTERNAL_RESULT, result)
    write_json(RESULT, result)
    render_report(result)
    return {
        **result,
        "external_result_sha256": sha256(EXTERNAL_RESULT),
        "repository_result_sha256": sha256(RESULT),
        "report_sha256": sha256(REPORT),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("freeze", "evaluate"), required=True)
    args = parser.parse_args()
    payload = run_freeze() if args.stage == "freeze" else run_evaluate()
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str))


if __name__ == "__main__":
    main()
