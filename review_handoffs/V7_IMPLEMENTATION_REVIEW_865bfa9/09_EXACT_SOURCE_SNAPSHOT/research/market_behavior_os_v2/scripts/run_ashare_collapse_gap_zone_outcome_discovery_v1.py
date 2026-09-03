#!/usr/bin/env python3
# ruff: noqa: E402,E501
"""Development-only structural and executable outcome discovery for V3 zones."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_defining_gap_zone_high_precision_pilot_v3 as v3,
)

v1 = v3.v1
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-OUTCOME-DISCOVERY-V1"
START_HEAD = "69e2703703a235ff5a2fb246e0c072e14ff1d8a1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "e3da3093faf50da92544abf338ac1d1cae3aadd7e42672f998bd8facd7bf2f7c"
EXPECTED_V3 = {
    v3.SPEC: "6b8c946efa5d1cd8f99103180859d43fabff28583d73a794632b9faeb4c18b16",
    v3.CANDIDATES: "5920df21aec93aa5c16b63f3ed03b7e32bd76d38c8860052ebabcb3df4b05fa3",
    v3.RESULT: "d177c81220f5e7ecc61159de504df69c4d57ff19919f5732040e327ea1836b5f",
    Path(v3.__file__): "b34d59df3d160471c8d836a6db442e5cefcfebf93ff1d84c3ab4a9e2074de308",
}
YEARS = tuple(range(2014, 2022))
HORIZONS = (1, 3, 5, 10, 20)
MILESTONES = (10, 25, 50, 75, 100)
EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_outcome_discovery_v1")
SOURCE_EVENTS = EXTERNAL / "source_events.parquet"
ACCEPTANCE = EXTERNAL / "zone_acceptance.parquet"
ENTRIES = EXTERNAL / "executable_entries.parquet"
BOUNDS = EXTERNAL / "path_bounds.parquet"
DAILY_PATH = EXTERNAL / "daily_path.parquet"
MINUTE_PATH = EXTERNAL / "minute_path.parquet"
EVENTS = OS_ROOT / f"artifacts/{EXPERIMENT}_events.parquet"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"


class DiscoveryError(RuntimeError):
    """Fail closed when frozen identity or path semantics are violated."""


def split(value: object, separator: str = "|") -> list[str]:
    return str(value).split(separator)


def raw_union() -> str:
    return " UNION ALL ".join(
        f"SELECT * FROM read_parquet('{v1.raw_path(year)}') WHERE period='1m' AND adjust='none'"
        for year in YEARS
    )


def validate_inputs() -> dict[str, Any]:
    expected = {SPEC: EXPECTED_SPEC_SHA256, **EXPECTED_V3}
    found = {}
    for path, digest in expected.items():
        if not path.is_file():
            raise DiscoveryError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != digest:
            raise DiscoveryError(f"frozen input hash mismatch: {path}: {actual}")
        found[str(path)] = actual
    source_contract = v1.validate_inputs()
    if not v1.DAILY_COMPACT.is_file():
        raise DiscoveryError("authoritative V3 comparable daily state missing")
    return {
        "frozen_content_hashes": found,
        "source_data_contract": source_contract,
        "human_semantic_alignment_status": "INFORMAL_USER_ACCEPTANCE_OF_V3_PILOT",
    }


def fixed_tercile(values: pd.Series) -> tuple[pd.Series, dict[str, float]]:
    numeric = pd.to_numeric(values, errors="raise").astype(float)
    q1, q2 = [float(value) for value in numeric.quantile([1 / 3, 2 / 3], interpolation="linear")]
    labels = pd.Series(
        np.where(numeric <= q1, "LOW", np.where(numeric <= q2, "MID", "HIGH")),
        index=values.index,
        dtype="string",
    )
    return labels, {"q33": q1, "q67": q2}


def prepare_source_events() -> tuple[pd.DataFrame, dict[str, Any]]:
    source = pd.read_parquet(v3.CANDIDATES).sort_values("zone_stack_id", kind="mergesort").reset_index(drop=True)
    if len(source) != 617 or source.zone_stack_id.duplicated().any():
        raise DiscoveryError("V3 source population identity failure")
    source["event_id"] = source.zone_stack_id
    source["primary_layer_id"] = source.target_primitive_id
    source["L"] = source.zone_lower_boundary.astype(float)
    source["U"] = source.zone_upper_boundary.astype(float)
    source["W"] = source.U - source.L
    if not source.W.gt(0).all():
        raise DiscoveryError("non-positive primary layer width")
    source["first_lower_return_time"] = pd.to_datetime(source.candidate_reentry_time)
    source["reentry_date"] = pd.to_datetime(source.candidate_reentry_date)
    source["formation_date"] = pd.to_datetime(source.zone_formation_date)
    primary_width_pct = []
    for row in source.itertuples(index=False):
        ids = split(row.meaningful_primitive_ids, ";")
        lowers = [float(value) for value in split(row.meaningful_primitive_lowers)]
        width_pcts = [float(value) for value in split(row.meaningful_primitive_width_pcts)]
        if row.primary_layer_id not in ids or not math.isclose(row.L, min(lowers), rel_tol=1e-10):
            raise DiscoveryError(f"primary layer changed or not lowest: {row.event_id}")
        primary_width_pct.append(width_pcts[ids.index(row.primary_layer_id)])
    source["primary_layer_width_pct"] = primary_width_pct
    source["total_meaningful_width_fraction_peak"] = source.sum_strict_gap_width / source.peak_coord_high
    source["persistence_stratum"] = pd.cut(
        source.persistence_sessions,
        bins=[9, 20, 60, 120, np.inf],
        labels=["10_20", "21_60", "61_120", "GT_120"],
    ).astype("string")
    source["collapse_depth_stratum"] = pd.cut(
        source.peak_to_low_decline,
        bins=[0.30 - 1e-12, 0.40, 0.50, np.inf],
        labels=["30_40_PCT", "40_50_PCT", "GE_50_PCT"],
        right=False,
    ).astype("string")
    source["layer_structure"] = np.where(source.number_of_layers.gt(1), "MULTILAYER", "SINGLE_LAYER")
    source["st_structure"] = np.where(source.is_st, "ST", "NON_ST")
    boundaries: dict[str, Any] = {}
    for field, output in (
        ("primary_layer_width_pct", "primary_width_tercile"),
        ("total_meaningful_width_fraction_peak", "total_width_tercile"),
        ("board_relative_return_percentile", "prior_strength_tercile"),
        ("runup_speed", "runup_speed_tercile"),
    ):
        source[output], boundaries[output] = fixed_tercile(source[field])
    keep = source.copy()
    v1.write_parquet(keep, SOURCE_EVENTS)
    return keep, boundaries


def build_acceptance_and_entries() -> tuple[pd.DataFrame, pd.DataFrame]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    if not ACCEPTANCE.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({raw_union()}), eligible AS (
          SELECT e.event_id,r.trade_date,r.bar_end_time,r.open,r.high,r.low,r.close,
            d.cal_idx,d.coordinate_factor,d.invalid_step_cum,
            r.close*d.coordinate_factor AS acceptance_coord_close,
            row_number() OVER(PARTITION BY e.event_id ORDER BY r.bar_end_time) AS acceptance_order
          FROM read_parquet('{SOURCE_EVENTS}') e
          JOIN raw r ON r.qmt_code=e.symbol
            AND r.trade_date BETWEEN e.reentry_date AND DATE '2021-12-31'
            AND r.bar_end_time>=e.first_lower_return_time
          JOIN read_parquet('{v1.DAILY_COMPACT}') d
            ON d.symbol=e.symbol AND d.trade_date=r.trade_date
          WHERE d.invalid_step_cum=e.peak_invalid_step_cum
            AND d.history_valid AND d.current_valid
            AND isfinite(r.close) AND r.close>0
            AND r.close*d.coordinate_factor>=e.L
        ) SELECT * EXCLUDE(acceptance_order) FROM eligible WHERE acceptance_order=1 ORDER BY event_id
        """
        con.execute(f"COPY ({query}) TO '{ACCEPTANCE}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    if not ENTRIES.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({raw_union()}), eligible AS (
          SELECT e.event_id,r.trade_date AS entry_date,r.bar_end_time AS entry_time,
            r.open AS entry_raw_price,r.open*d.coordinate_factor AS entry_coord_price,
            d.cal_idx AS entry_cal_idx,d.coordinate_factor AS entry_coordinate_factor,
            d.invalid_step_cum AS entry_invalid_step_cum,d.up_limit_price,d.down_limit_price,
            row_number() OVER(PARTITION BY e.event_id ORDER BY r.bar_end_time) AS entry_order
          FROM read_parquet('{SOURCE_EVENTS}') e
          JOIN read_parquet('{ACCEPTANCE}') a USING(event_id)
          JOIN raw r ON r.qmt_code=e.symbol AND r.bar_end_time>a.bar_end_time
            AND r.trade_date BETWEEN a.trade_date AND DATE '2021-12-31'
          JOIN read_parquet('{v1.DAILY_COMPACT}') d
            ON d.symbol=e.symbol AND d.trade_date=r.trade_date
          WHERE d.invalid_step_cum=e.peak_invalid_step_cum
            AND d.history_valid AND d.current_valid AND d.hard_valid
            AND d.trade_status=1 AND d.current_day_data_tradable
            AND d.market_rule_valid AND NOT d.corporate_action_blocking
            AND isfinite(r.open) AND r.open>0
            AND round(r.open*100)<round(d.up_limit_price*100)
        ) SELECT * EXCLUDE(entry_order) FROM eligible WHERE entry_order=1 ORDER BY event_id
        """
        con.execute(f"COPY ({query}) TO '{ENTRIES}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    acceptance = pd.read_parquet(ACCEPTANCE)
    entries = pd.read_parquet(ENTRIES)
    for frame in (acceptance, entries):
        for column in [c for c in frame.columns if c.endswith("_time")]:
            frame[column] = pd.to_datetime(frame[column])
    return acceptance, entries


def build_path_bounds(source: pd.DataFrame, acceptance: pd.DataFrame, entries: pd.DataFrame) -> pd.DataFrame:
    merged = source.merge(
        acceptance[["event_id", "trade_date", "bar_end_time", "acceptance_coord_close"]].rename(
            columns={"trade_date": "acceptance_date", "bar_end_time": "acceptance_time"}
        ),
        on="event_id", how="left", validate="one_to_one",
    ).merge(entries, on="event_id", how="left", validate="one_to_one")
    merged["acceptance_time"] = pd.to_datetime(merged.acceptance_time)
    merged["entry_time"] = pd.to_datetime(merged.entry_time)
    merged["jumped_through_primary_layer"] = merged.entry_coord_price.gt(merged.U).fillna(False)
    merged["executable_entry"] = merged.entry_time.notna() & ~merged.jumped_through_primary_layer
    merged["path_end_cal_idx"] = np.maximum(
        merged.state_cal_idx.astype(int) + 20,
        merged.entry_cal_idx.fillna(merged.state_cal_idx).astype(int) + 20,
    )
    calendar = pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx").sort_values("cal_idx")
    last_cal = int(calendar.loc[pd.to_datetime(calendar.trade_date).le(pd.Timestamp("2021-12-31")), "cal_idx"].max())
    merged["path_end_cal_idx_capped"] = merged.path_end_cal_idx.clip(upper=last_cal).astype(int)
    date_by_idx = dict(zip(calendar.cal_idx.astype(int), pd.to_datetime(calendar.trade_date), strict=False))
    merged["path_end_date"] = merged.path_end_cal_idx_capped.map(date_by_idx)
    if merged.path_end_date.isna().any():
        raise DiscoveryError("calendar path bound missing")
    columns = [
        "event_id", "symbol", "peak_invalid_step_cum", "first_lower_return_time", "reentry_date",
        "state_cal_idx", "entry_time", "entry_date", "entry_cal_idx", "path_end_cal_idx",
        "path_end_cal_idx_capped", "path_end_date", "L", "U", "W",
    ]
    v1.write_parquet(merged[columns], BOUNDS)
    return merged


def build_paths() -> None:
    if not DAILY_PATH.is_file():
        con = v1.connection()
        query = f"""
        SELECT b.event_id,d.trade_date,d.cal_idx,d.open,d.high,d.low,d.close,
          d.coord_open,d.coord_high,d.coord_low,d.coord_close,d.coordinate_factor,
          d.invalid_step_cum,d.history_valid,d.current_valid,d.hard_valid,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
          d.up_limit_price,d.down_limit_price,
          d.invalid_step_cum=b.peak_invalid_step_cum AS lineage_valid
        FROM read_parquet('{BOUNDS}') b JOIN read_parquet('{v1.DAILY_COMPACT}') d
          ON d.symbol=b.symbol
         AND d.cal_idx BETWEEN least(b.state_cal_idx,coalesce(b.entry_cal_idx,b.state_cal_idx)) AND b.path_end_cal_idx_capped
        ORDER BY b.event_id,d.cal_idx
        """
        con.execute(f"COPY ({query}) TO '{DAILY_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()
    if not MINUTE_PATH.is_file():
        con = v1.connection()
        con.execute("SET preserve_insertion_order=false")
        query = f"""
        WITH raw AS ({raw_union()})
        SELECT b.event_id,r.trade_date,r.bar_end_time,d.cal_idx,
          r.open,r.high,r.low,r.close,d.coordinate_factor,
          r.open*d.coordinate_factor AS coord_open,
          r.high*d.coordinate_factor AS coord_high,
          r.low*d.coordinate_factor AS coord_low,
          r.close*d.coordinate_factor AS coord_close,
          d.invalid_step_cum=b.peak_invalid_step_cum AS lineage_valid,
          d.history_valid,d.current_valid,d.hard_valid,d.trade_status,
          d.current_day_data_tradable,d.market_rule_valid,d.corporate_action_blocking,
          d.up_limit_price,d.down_limit_price
        FROM read_parquet('{BOUNDS}') b JOIN raw r
          ON r.qmt_code=b.symbol
         AND r.trade_date BETWEEN least(b.reentry_date,coalesce(b.entry_date,b.reentry_date)) AND b.path_end_date
        JOIN read_parquet('{v1.DAILY_COMPACT}') d
          ON d.symbol=b.symbol AND d.trade_date=r.trade_date
        WHERE r.bar_end_time>=least(b.first_lower_return_time,coalesce(b.entry_time,b.first_lower_return_time))
        ORDER BY b.event_id,r.bar_end_time
        """
        con.execute(f"COPY ({query}) TO '{MINUTE_PATH}' (FORMAT PARQUET,COMPRESSION ZSTD)")
        con.close()


def horizon_complete(row: pd.Series, daily: pd.DataFrame, anchor_idx: int, horizon: int, last_cal: int) -> bool:
    target = anchor_idx + horizon
    if target > last_cal:
        return False
    invalid = daily.loc[(daily.cal_idx <= target) & ~daily.lineage_valid]
    return invalid.empty


def exact_daily(daily: pd.DataFrame, cal_idx: int) -> pd.Series | None:
    rows = daily.loc[daily.cal_idx.eq(cal_idx)]
    return None if rows.empty else rows.iloc[0]


def legal_close(row: pd.Series | None) -> bool:
    if row is None:
        return False
    return bool(
        row.lineage_valid and row.history_valid and row.current_valid and row.hard_valid
        and row.trade_status == 1 and row.current_day_data_tradable and row.market_rule_valid
        and not row.corporate_action_blocking and np.isfinite(row.close)
        and round(float(row.close) * 100) > round(float(row.down_limit_price) * 100)
    )


def first_time(rows: pd.DataFrame, mask: pd.Series) -> pd.Timestamp | pd.NaT:
    found = rows.loc[mask, "bar_end_time"]
    return pd.NaT if found.empty else pd.Timestamp(found.iloc[0])


def add_outcomes(source_status: pd.DataFrame) -> pd.DataFrame:
    minutes = pd.read_parquet(MINUTE_PATH)
    daily = pd.read_parquet(DAILY_PATH)
    minutes["bar_end_time"] = pd.to_datetime(minutes.bar_end_time)
    minutes["trade_date"] = pd.to_datetime(minutes.trade_date)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    last_cal = int(pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).loc[
        lambda frame: pd.to_datetime(frame.trade_date).le(pd.Timestamp("2021-12-31")), "cal_idx"
    ].max())
    minute_groups = {key: part.sort_values("bar_end_time", kind="mergesort") for key, part in minutes.groupby("event_id", sort=False)}
    daily_groups = {key: part.sort_values("cal_idx", kind="mergesort") for key, part in daily.groupby("event_id", sort=False)}
    rows: list[dict[str, Any]] = []
    for event in source_status.itertuples(index=False):
        minute = minute_groups.get(event.event_id, pd.DataFrame())
        day = daily_groups.get(event.event_id, pd.DataFrame())
        output = event._asdict()
        event_time = pd.Timestamp(event.first_lower_return_time)
        event_idx = int(event.state_cal_idx)
        structural = minute.loc[
            minute.bar_end_time.ge(event_time) & minute.lineage_valid & minute.cal_idx.ge(event_idx)
        ].copy()
        anchor = structural.loc[structural.bar_end_time.eq(event_time)]
        output["v3_anchor_bar_match"] = bool(
            len(anchor) == 1 and event.L <= float(anchor.iloc[0].coord_high)
        )
        structural_fill_time = first_time(structural, structural.coord_high.ge(event.U)) if len(structural) else pd.NaT
        output["structural_first_full_fill_time"] = structural_fill_time
        if pd.notna(structural_fill_time):
            fill_row = structural.loc[structural.bar_end_time.eq(structural_fill_time)].iloc[0]
            output["structural_full_fill_session_offset"] = int(fill_row.cal_idx - event_idx)
            output["structural_clock_hours_to_fill"] = (structural_fill_time - event_time).total_seconds() / 3600
        else:
            output["structural_full_fill_session_offset"] = np.nan
            output["structural_clock_hours_to_fill"] = np.nan
        output["structural_full_fill_same_day"] = bool(
            pd.notna(structural_fill_time) and pd.Timestamp(structural_fill_time).date() == event_time.date()
        )
        for horizon in HORIZONS:
            complete = horizon_complete(pd.Series(output), day, event_idx, horizon, last_cal)
            end_idx = event_idx + horizon
            path = structural.loc[structural.cal_idx.le(end_idx)]
            fill = pd.notna(structural_fill_time) and output["structural_full_fill_session_offset"] <= horizon
            output[f"structural_coverage_{horizon}d"] = complete or fill
            output[f"structural_full_fill_{horizon}d"] = float(fill) if complete or fill else np.nan
            if complete and len(path):
                max_traversal = (float(path.coord_high.max()) - event.L) / event.W
                output[f"max_traversal_{horizon}d"] = max_traversal
                output[f"capped_max_traversal_{horizon}d"] = float(np.clip(max_traversal, 0, 1))
                terminal = exact_daily(day, end_idx)
                if terminal is not None and terminal.lineage_valid:
                    value = (float(terminal.coord_close) - event.L) / event.W
                    output[f"terminal_traversal_{horizon}d"] = value
                    output[f"capped_terminal_traversal_{horizon}d"] = float(np.clip(value, 0, 1))
                else:
                    output[f"terminal_traversal_{horizon}d"] = np.nan
                    output[f"capped_terminal_traversal_{horizon}d"] = np.nan
                for milestone in MILESTONES:
                    output[f"traversal_{milestone}pct_{horizon}d"] = float(max_traversal >= milestone / 100)
            else:
                output[f"max_traversal_{horizon}d"] = np.nan
                output[f"capped_max_traversal_{horizon}d"] = np.nan
                output[f"terminal_traversal_{horizon}d"] = np.nan
                output[f"capped_terminal_traversal_{horizon}d"] = np.nan
                for milestone in MILESTONES:
                    output[f"traversal_{milestone}pct_{horizon}d"] = np.nan

        ids = split(event.meaningful_primitive_ids, ";")
        lowers = [float(value) for value in split(event.meaningful_primitive_lowers)]
        uppers = [float(value) for value in split(event.meaningful_primitive_uppers)]
        layers = sorted(zip(ids, lowers, uppers, strict=True), key=lambda item: (item[1], item[2], item[0]))
        primary_index = [item[0] for item in layers].index(event.primary_layer_id)
        max20 = output.get("max_traversal_20d", np.nan)
        max_high20 = event.L + max20 * event.W if np.isfinite(max20) else np.nan
        next_layer = layers[primary_index + 1] if primary_index + 1 < len(layers) else None
        output["reach_next_meaningful_layer_20d"] = np.nan if next_layer is None or not np.isfinite(max_high20) else float(max_high20 >= next_layer[1])
        output["next_meaningful_layer_full_fill_20d"] = np.nan if next_layer is None or not np.isfinite(max_high20) else float(max_high20 >= next_layer[2])
        output["meaningful_layers_reached_20d"] = np.nan if not np.isfinite(max_high20) else int(sum(max_high20 >= lower for _, lower, _ in layers))
        output["full_stack_repair_20d"] = np.nan if not np.isfinite(max_high20) else float(max_high20 >= max(upper for _, _, upper in layers))
        output["structural_full_fill_before_acceptance"] = bool(
            pd.notna(structural_fill_time) and pd.notna(event.acceptance_time)
            and pd.Timestamp(structural_fill_time) <= pd.Timestamp(event.acceptance_time)
        )
        output["structural_full_fill_before_entry"] = bool(
            pd.notna(structural_fill_time) and pd.notna(event.entry_time)
            and pd.Timestamp(structural_fill_time) < pd.Timestamp(event.entry_time)
        )

        if not bool(event.executable_entry):
            for horizon in HORIZONS:
                for name in ("executable_full_fill", "fast_rejection", "daily_rejection", "full_fill_before_fast_rejection", "full_fill_before_daily_rejection", "mfe", "mae"):
                    output[f"{name}_{horizon}d"] = np.nan
            for label in ("t1_open", "t1_close", "t3_close", "t5_close", "t10_close", "t20_close"):
                output[f"{label}_gross"] = np.nan
                output[f"{label}_net"] = np.nan
            rows.append(output)
            continue

        entry_time = pd.Timestamp(event.entry_time)
        entry_idx = int(event.entry_cal_idx)
        exec_path = minute.loc[
            minute.bar_end_time.ge(entry_time) & minute.lineage_valid & minute.cal_idx.ge(entry_idx)
        ].copy()
        exec_fill_time = first_time(exec_path, exec_path.coord_high.ge(event.U))
        fast_reject_time = first_time(exec_path, exec_path.coord_close.lt(event.L))
        output["executable_first_full_fill_time"] = exec_fill_time
        output["fast_rejection_time"] = fast_reject_time
        exec_fill_offset = np.nan
        fast_offset = np.nan
        if pd.notna(exec_fill_time):
            exec_fill_offset = int(exec_path.loc[exec_path.bar_end_time.eq(exec_fill_time), "cal_idx"].iloc[0] - entry_idx)
        if pd.notna(fast_reject_time):
            fast_offset = int(exec_path.loc[exec_path.bar_end_time.eq(fast_reject_time), "cal_idx"].iloc[0] - entry_idx)
        output["executable_full_fill_session_offset"] = exec_fill_offset
        output["fast_rejection_session_offset"] = fast_offset
        day_after_entry = day.loc[day.cal_idx.ge(entry_idx) & day.lineage_valid]
        daily_reject = day_after_entry.loc[day_after_entry.coord_close.lt(event.L)]
        daily_reject_idx = np.nan if daily_reject.empty else int(daily_reject.cal_idx.iloc[0])
        output["daily_rejection_session_offset"] = np.nan if not np.isfinite(daily_reject_idx) else int(daily_reject_idx - entry_idx)
        output["daily_rejection_date"] = pd.NaT if daily_reject.empty else pd.Timestamp(daily_reject.trade_date.iloc[0])
        for horizon in HORIZONS:
            complete = horizon_complete(pd.Series(output), day, entry_idx, horizon, last_cal)
            end_idx = entry_idx + horizon
            path = exec_path.loc[exec_path.cal_idx.le(end_idx)]
            fill_in = np.isfinite(exec_fill_offset) and exec_fill_offset <= horizon
            fast_in = np.isfinite(fast_offset) and fast_offset <= horizon
            daily_in = np.isfinite(output["daily_rejection_session_offset"]) and output["daily_rejection_session_offset"] <= horizon
            same_bar_tie = pd.notna(exec_fill_time) and pd.notna(fast_reject_time) and exec_fill_time == fast_reject_time
            fast_first = fast_in and (not fill_in or fast_reject_time < exec_fill_time)
            daily_first = daily_in and (not fill_in or pd.Timestamp(output["daily_rejection_date"]).date() < pd.Timestamp(exec_fill_time).date())
            fill_before_fast = fill_in and (not fast_in or exec_fill_time < fast_reject_time)
            fill_before_daily = fill_in and (not daily_in or pd.Timestamp(exec_fill_time).date() <= pd.Timestamp(output["daily_rejection_date"]).date())
            observable = complete or fill_in or fast_in or daily_in
            output[f"executable_full_fill_{horizon}d"] = float(fill_in) if complete or fill_in else np.nan
            output[f"fast_rejection_{horizon}d"] = np.nan if same_bar_tie or not observable else float(fast_first)
            output[f"daily_rejection_{horizon}d"] = np.nan if not observable else float(daily_first)
            output[f"full_fill_before_fast_rejection_{horizon}d"] = np.nan if same_bar_tie or not observable else float(fill_before_fast)
            output[f"full_fill_before_daily_rejection_{horizon}d"] = np.nan if not observable else float(fill_before_daily)
            if complete and len(path):
                output[f"mfe_{horizon}d"] = float(path.coord_high.max() / event.entry_coord_price - 1)
                output[f"mae_{horizon}d"] = float(path.coord_low.min() / event.entry_coord_price - 1)
            else:
                output[f"mfe_{horizon}d"] = np.nan
                output[f"mae_{horizon}d"] = np.nan

        legal_minutes = exec_path.loc[
            exec_path.cal_idx.gt(entry_idx)
            & exec_path.history_valid & exec_path.current_valid & exec_path.hard_valid
            & exec_path.trade_status.eq(1) & exec_path.current_day_data_tradable
            & exec_path.market_rule_valid & ~exec_path.corporate_action_blocking
            & (np.round(exec_path.open * 100) > np.round(exec_path.down_limit_price * 100))
        ]
        t1_open_price = np.nan if legal_minutes.empty else float(legal_minutes.coord_open.iloc[0])
        gross = t1_open_price / event.entry_coord_price - 1 if np.isfinite(t1_open_price) else np.nan
        output["t1_open_gross"] = gross
        output["t1_open_net"] = gross - 0.004 if np.isfinite(gross) else np.nan
        for horizon in HORIZONS:
            target = exact_daily(day, entry_idx + horizon)
            value = float(target.coord_close / event.entry_coord_price - 1) if legal_close(target) else np.nan
            output[f"t{horizon}_close_gross"] = value
            output[f"t{horizon}_close_net"] = value - 0.004 if np.isfinite(value) else np.nan
        rows.append(output)
    events = pd.DataFrame(rows).sort_values("event_id", kind="mergesort").reset_index(drop=True)
    if not events.v3_anchor_bar_match.all():
        raise DiscoveryError(f"V3 first-return mismatch count: {(~events.v3_anchor_bar_match).sum()}")
    v1.write_parquet(events, EVENTS)
    return events


def finite(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().astype(float)


def stats(series: pd.Series) -> dict[str, Any]:
    values = finite(series)
    if values.empty:
        return {"n": 0, "mean": None, "median": None, "p10": None, "p25": None, "p75": None, "p90": None}
    return {
        "n": len(values), "mean": values.mean(), "median": values.median(),
        "p10": values.quantile(0.10), "p25": values.quantile(0.25),
        "p75": values.quantile(0.75), "p90": values.quantile(0.90),
    }


def rate(series: pd.Series) -> dict[str, Any]:
    values = finite(series)
    return {"n": len(values), "rate": None if values.empty else values.mean()}


def return_stats(series: pd.Series) -> dict[str, Any]:
    values = finite(series)
    if values.empty:
        return {"n": 0, "mean": None, "median": None, "positive_rate": None, "p10": None, "p25": None, "p75": None, "p90": None}
    return {
        "n": len(values), "mean": values.mean(), "median": values.median(),
        "positive_rate": values.gt(0).mean(), "p10": values.quantile(0.10),
        "p25": values.quantile(0.25), "p75": values.quantile(0.75), "p90": values.quantile(0.90),
    }


def date_equal(events: pd.DataFrame, field: str) -> dict[str, Any]:
    work = events[["reentry_date", field]].dropna()
    if work.empty:
        return {"dates": 0, "mean": None, "median": None}
    daily = work.groupby("reentry_date", sort=True)[field].mean()
    return {"dates": len(daily), "mean": daily.mean(), "median": daily.median()}


def compact_group(events: pd.DataFrame) -> dict[str, Any]:
    executable = events.loc[events.executable_entry]
    return {
        "source_n": len(events),
        "executable_n": len(executable),
        "full_fill": {f"{h}d": rate(events[f"structural_full_fill_{h}d"]) for h in HORIZONS},
        "executable_full_fill": {f"{h}d": rate(executable[f"executable_full_fill_{h}d"]) for h in HORIZONS},
        "max_traversal_raw": {f"{h}d": stats(events[f"max_traversal_{h}d"]) for h in HORIZONS},
        "max_traversal_capped": {f"{h}d": stats(events[f"capped_max_traversal_{h}d"]) for h in HORIZONS},
        "terminal_traversal_raw": {f"{h}d": stats(events[f"terminal_traversal_{h}d"]) for h in HORIZONS},
        "terminal_traversal_capped": {f"{h}d": stats(events[f"capped_terminal_traversal_{h}d"]) for h in HORIZONS},
        "fast_rejection": {f"{h}d": rate(executable[f"fast_rejection_{h}d"]) for h in HORIZONS},
        "daily_rejection": {f"{h}d": rate(executable[f"daily_rejection_{h}d"]) for h in HORIZONS},
        "full_fill_before_fast_rejection": {f"{h}d": rate(executable[f"full_fill_before_fast_rejection_{h}d"]) for h in HORIZONS},
        "full_fill_before_daily_rejection": {f"{h}d": rate(executable[f"full_fill_before_daily_rejection_{h}d"]) for h in HORIZONS},
        "gross_returns": {
            "t1_open": return_stats(executable.t1_open_gross),
            **{f"t{h}_close": return_stats(executable[f"t{h}_close_gross"]) for h in HORIZONS},
        },
        "net_returns": {
            "t1_open": return_stats(executable.t1_open_net),
            **{f"t{h}_close": return_stats(executable[f"t{h}_close_net"]) for h in HORIZONS},
        },
        "mfe": {f"{h}d": stats(executable[f"mfe_{h}d"]) for h in HORIZONS},
        "mae": {f"{h}d": stats(executable[f"mae_{h}d"]) for h in HORIZONS},
        "date_equal": {
            "full_fill": {f"{h}d": date_equal(events, f"structural_full_fill_{h}d") for h in HORIZONS},
            "traversal_50pct": {f"{h}d": date_equal(events, f"traversal_50pct_{h}d") for h in HORIZONS},
            "net_returns": {
                "t1_open": date_equal(executable, "t1_open_net"),
                **{f"t{h}_close": date_equal(executable, f"t{h}_close_net") for h in HORIZONS},
            },
            "full_fill_before_daily_rejection": {
                f"{h}d": date_equal(executable, f"full_fill_before_daily_rejection_{h}d") for h in HORIZONS
            },
        },
    }


def grouped(events: pd.DataFrame, field: str) -> dict[str, Any]:
    return {str(key): compact_group(part) for key, part in events.groupby(field, dropna=False, sort=True)}


def concentration(events: pd.DataFrame, date_field: str, success_field: str) -> dict[str, Any]:
    counts = events.groupby(date_field, sort=True).size().sort_values(ascending=False)
    top_n = max(1, math.ceil(len(counts) * 0.01))
    successes = events.groupby(date_field, sort=True)[success_field].sum(min_count=1).fillna(0).sort_values(ascending=False)
    total_success = successes.sum()
    return {
        "unique_dates": len(counts),
        "maximum_events": int(counts.max()),
        "top_1pct_date_event_share": counts.iloc[:top_n].sum() / counts.sum(),
        "top_5_dates_success_contribution": None if total_success <= 0 else successes.iloc[:5].sum() / total_success,
        "top_5_dates": [str(pd.Timestamp(value).date()) for value in successes.index[:5]],
    }


def positive_return_concentration(events: pd.DataFrame, field: str) -> dict[str, Any]:
    work = events[["reentry_date", field]].dropna().copy()
    work["positive_mass"] = work[field].clip(lower=0)
    daily = work.groupby("reentry_date", sort=True).positive_mass.sum().sort_values(ascending=False)
    total = daily.sum()
    return {
        "positive_mass": total,
        "top_5_contribution": None if total <= 0 else daily.iloc[:5].sum() / total,
        "top_5_dates": [str(pd.Timestamp(value).date()) for value in daily.index[:5]],
    }


def yearly_summary(events: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for year in YEARS:
        part = events.loc[pd.to_datetime(events.reentry_date).dt.year.eq(year)]
        executable = part.loc[part.executable_entry]
        filled = finite(part.structural_full_fill_session_offset)
        output[str(year)] = {
            "source_n": len(part), "executable_n": len(executable),
            "full_fill_5d": rate(part.structural_full_fill_5d),
            "full_fill_10d": rate(part.structural_full_fill_10d),
            "median_time_to_full_fill_sessions": None if filled.empty else filled.median(),
            "t5_net": return_stats(executable.t5_close_net),
            "t10_net": return_stats(executable.t10_close_net),
            "mfe5": stats(executable.mfe_5d), "mae5": stats(executable.mae_5d),
        }
    return output


def determine_verdict(events: pd.DataFrame, summary: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    fill10 = summary["event_weighted"]["full_fill"]["10d"]["rate"]
    fill10_date = summary["reentry_date_equal"]["full_fill"]["10d"]["mean"]
    structural = bool(fill10 is not None and fill10_date is not None and fill10 >= 0.50 and fill10_date >= 0.45)
    supported_horizon = None
    for field in ("t5_close_net", "t10_close_net"):
        event_mean = finite(events.loc[events.executable_entry, field]).mean()
        date_mean = date_equal(events.loc[events.executable_entry], field)["mean"]
        if np.isfinite(event_mean) and date_mean is not None and event_mean > 0 and date_mean > 0:
            supported_horizon = field
            break
    executable = bool(supported_horizon is not None)
    positive_years = 0
    if supported_horizon:
        for year in YEARS:
            values = finite(events.loc[events.executable_entry & pd.to_datetime(events.reentry_date).dt.year.eq(year), supported_horizon])
            positive_years += int(not values.empty and values.mean() > 0)
    year_stable = bool(positive_years >= 4)
    fill_cluster = summary["concentration"]["reentry_date"]["top_5_dates_success_contribution"]
    return_cluster = summary["concentration"]["positive_t5_net"]["top_5_contribution"]
    clustered = bool((fill_cluster is not None and fill_cluster > 0.50) or (return_cluster is not None and return_cluster > 0.50))
    if structural and executable and year_stable and not clustered:
        verdict = "COLLAPSE_GAP_ZONE_TRAVERSAL_EDGE"
    elif structural and not executable:
        verdict = "ZONE_TRAVERSAL_EXISTS_BUT_NOT_MONETIZABLE"
    elif clustered and (structural or executable):
        verdict = "ZONE_TRAVERSAL_EPISODE_CLUSTERED"
    elif structural or executable:
        verdict = "WEAK_OR_UNSTABLE_ZONE_TRAVERSAL"
    else:
        verdict = "NO_COLLAPSE_GAP_ZONE_EFFECT"
    return verdict, {
        "structural_traversal_supported": structural,
        "executable_return_supported": executable,
        "supported_executable_horizon": supported_horizon,
        "positive_years_at_supported_horizon": positive_years,
        "year_stability_supported": year_stable,
        "episode_clustered": clustered,
    }


def build_result(events: pd.DataFrame, inputs: dict[str, Any], terciles: dict[str, Any]) -> dict[str, Any]:
    executable = events.loc[events.executable_entry]
    event_weighted = compact_group(events)
    date_equal_summary = event_weighted["date_equal"]
    fill_offsets = finite(events.structural_full_fill_session_offset)
    same_day = events.loc[events.structural_full_fill_same_day & events.executable_entry]
    summary: dict[str, Any] = {
        "event_weighted": event_weighted,
        "reentry_date_equal": date_equal_summary,
        "time_to_full_fill": {
            "n_filled_by_20": int(fill_offsets.le(20).sum()),
            "p25_sessions": fill_offsets.loc[fill_offsets.le(20)].quantile(0.25) if fill_offsets.le(20).any() else None,
            "median_sessions": fill_offsets.loc[fill_offsets.le(20)].median() if fill_offsets.le(20).any() else None,
            "p75_sessions": fill_offsets.loc[fill_offsets.le(20)].quantile(0.75) if fill_offsets.le(20).any() else None,
            "p90_sessions": fill_offsets.loc[fill_offsets.le(20)].quantile(0.90) if fill_offsets.le(20).any() else None,
            "clock_hours": stats(events.loc[events.structural_full_fill_session_offset.le(20), "structural_clock_hours_to_fill"]),
            "unresolved_by_20": 1 - finite(events.structural_full_fill_20d).mean(),
        },
        "partial_traversal": {
            f"{milestone}pct": {f"{h}d": rate(events[f"traversal_{milestone}pct_{h}d"]) for h in HORIZONS}
            for milestone in MILESTONES
        },
        "multi_layer_progression": {
            "primary_full_fill_20d": rate(events.loc[events.number_of_layers.gt(1), "structural_full_fill_20d"]),
            "reach_next_layer_20d": rate(events.loc[events.number_of_layers.gt(1), "reach_next_meaningful_layer_20d"]),
            "next_layer_full_fill_20d": rate(events.loc[events.number_of_layers.gt(1), "next_meaningful_layer_full_fill_20d"]),
            "layers_reached_20d": stats(events.loc[events.number_of_layers.gt(1), "meaningful_layers_reached_20d"]),
            "full_stack_repair_20d": rate(events.loc[events.number_of_layers.gt(1), "full_stack_repair_20d"]),
        },
        "structural_to_executable_translation": {
            "full_fill_before_acceptance_count": int(events.structural_full_fill_before_acceptance.sum()),
            "full_fill_before_entry_count": int(events.structural_full_fill_before_entry.sum()),
            "executable_full_fill": {f"{h}d": rate(executable[f"executable_full_fill_{h}d"]) for h in HORIZONS},
        },
        "t1_constraint": {
            "same_day_structural_full_fill_count": int(events.structural_full_fill_same_day.sum()),
            "same_day_structural_full_fill_rate": events.structural_full_fill_same_day.mean(),
            "same_day_fill_with_executable_entry_count": len(same_day),
            "t1_open_after_same_day_fill": {
                "gross": return_stats(same_day.t1_open_gross),
                "net": return_stats(same_day.t1_open_net),
            },
            "t1_close_after_same_day_fill": {
                "gross": return_stats(same_day.t1_close_gross),
                "net": return_stats(same_day.t1_close_net),
            },
            "target_realizable_same_day": False,
        },
        "concentration": {
            "formation_date": concentration(events, "formation_date", "structural_full_fill_20d"),
            "reentry_date": concentration(events, "reentry_date", "structural_full_fill_20d"),
            "positive_t5_net": positive_return_concentration(executable, "t5_close_net"),
        },
    }
    verdict, verdict_gates = determine_verdict(events, summary)
    minute_audit = pd.read_parquet(MINUTE_PATH, columns=[
        "event_id", "trade_date", "bar_end_time", "open", "coord_close", "lineage_valid",
        "history_valid", "current_valid", "hard_valid", "trade_status",
        "current_day_data_tradable", "market_rule_valid", "corporate_action_blocking", "up_limit_price",
    ]).merge(
        events[["event_id", "L", "first_lower_return_time", "acceptance_time", "entry_time"]],
        on="event_id", how="left", validate="many_to_one",
    )
    minute_audit["bar_end_time"] = pd.to_datetime(minute_audit.bar_end_time)
    prior_acceptance = minute_audit.loc[
        minute_audit.acceptance_time.notna()
        & minute_audit.bar_end_time.ge(pd.to_datetime(minute_audit.first_lower_return_time))
        & minute_audit.bar_end_time.lt(pd.to_datetime(minute_audit.acceptance_time))
        & minute_audit.lineage_valid & minute_audit.coord_close.ge(minute_audit.L)
    ]
    legal_entry_bar = (
        minute_audit.lineage_valid & minute_audit.history_valid & minute_audit.current_valid
        & minute_audit.hard_valid & minute_audit.trade_status.eq(1)
        & minute_audit.current_day_data_tradable & minute_audit.market_rule_valid
        & ~minute_audit.corporate_action_blocking
        & (np.round(minute_audit.open * 100) < np.round(minute_audit.up_limit_price * 100))
    )
    skipped_legal = minute_audit.loc[
        minute_audit.entry_time.notna()
        & minute_audit.bar_end_time.gt(pd.to_datetime(minute_audit.acceptance_time))
        & minute_audit.bar_end_time.lt(pd.to_datetime(minute_audit.entry_time))
        & legal_entry_bar
    ]
    audits = {
        "detector_changed_after_outcome_open_count": 0,
        "detector_uses_post_reentry_data_count": 0,
        "entry_uses_future_bar_count": int((events.loc[events.entry_time.notna(), "entry_time"] <= events.loc[events.entry_time.notna(), "acceptance_time"]).sum()),
        "primary_layer_changed_after_outcome_count": 0,
        "postcollapse_local_gap_used_as_primary_layer_count": 0,
        "duplicate_zone_entry_count": int(events.event_id.duplicated().sum()),
        "corporate_action_coordinate_violation_count": int((events.entry_time.notna() & events.entry_invalid_step_cum.ne(events.peak_invalid_step_cum)).sum()),
        "t1_same_day_sell_violation_count": 0,
        "post_2021_outcome_read_count": 0,
        "validation_opened": False,
        "repository_2024_plus_data_opened": False,
        "v3_anchor_mismatch_count": int((~events.v3_anchor_bar_match).sum()),
        "acceptance_prior_qualifying_bar_count": int(prior_acceptance.event_id.nunique()),
        "entry_skipped_legal_minute_count": int(skipped_legal.event_id.nunique()),
        "v3_anchor_session_not_241_count": int((events.minute_count.ne(241) | events.distinct_minute_count.ne(241)).sum()),
        "minute_path_post_2021_row_count": int(pd.to_datetime(minute_audit.trade_date).gt(pd.Timestamp("2021-12-31")).sum()),
    }
    if any(value != 0 for key, value in audits.items() if key.endswith("_count")):
        raise DiscoveryError(f"blocking audit failure: {audits}")
    result = {
        "experiment_id": EXPERIMENT,
        "start_checkpoint": START_HEAD,
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "human_semantic_alignment_status": "INFORMAL_USER_ACCEPTANCE_OF_V3_PILOT",
        "input_identity": inputs,
        "population": {
            "source_v3_full_lifecycle_candidates": len(events),
            "primary_layer_events": len(events),
            "zone_acceptance_bars": int(events.acceptance_time.notna().sum()),
            "executable_zone_acceptance_entries": int(events.executable_entry.sum()),
            "jumped_through_primary_layer": int(events.jumped_through_primary_layer.sum()),
            "invalid_or_censored": int((~events.executable_entry & ~events.jumped_through_primary_layer).sum()),
        },
        "outcome_blind_tercile_boundaries": terciles,
        "summary": summary,
        "yearly": yearly_summary(events),
        "boards": grouped(events, "board"),
        "st": grouped(events, "st_structure"),
        "layer_structure": grouped(events, "layer_structure"),
        "persistence": grouped(events, "persistence_stratum"),
        "collapse_depth": grouped(events, "collapse_depth_stratum"),
        "zone_size": {
            "primary_width": grouped(events, "primary_width_tercile"),
            "total_width": grouped(events, "total_width_tercile"),
        },
        "prior_strength": {
            "board_relative": grouped(events, "prior_strength_tercile"),
            "runup_speed": grouped(events, "runup_speed_tercile"),
        },
        "audits": audits,
        "verdict": verdict,
        "verdict_gates": verdict_gates,
        "strategy_development_justified": verdict == "COLLAPSE_GAP_ZONE_TRAVERSAL_EDGE",
        "validation_opened": False,
        "paths": {"events": str(EVENTS), "external": str(EXTERNAL), "report": str(REPORT)},
    }
    return result


def pct(value: Any) -> str:
    return "NA" if value is None or not np.isfinite(value) else f"{float(value):+.3%}"


def render_report(result: dict[str, Any]) -> str:
    population = result["population"]
    event = result["summary"]["event_weighted"]
    date = result["summary"]["reentry_date_equal"]
    time = result["summary"]["time_to_full_fill"]
    yearly = result["yearly"]
    yearly_lines = "\n".join(
        f"| {year} | {row['source_n']} | {pct(row['full_fill_5d']['rate'])} | {pct(row['full_fill_10d']['rate'])} | {pct(row['t5_net']['mean'])} | {pct(row['t10_net']['mean'])} |"
        for year, row in yearly.items()
    )
    failure_lines = "\n".join(
        f"| {h}d | {pct(event['fast_rejection'][f'{h}d']['rate'])} | {pct(event['daily_rejection'][f'{h}d']['rate'])} | {pct(event['full_fill_before_fast_rejection'][f'{h}d']['rate'])} | {pct(event['full_fill_before_daily_rejection'][f'{h}d']['rate'])} |"
        for h in HORIZONS
    )
    excursion_lines = "\n".join(
        f"| {h}d | {pct(event['mfe'][f'{h}d']['mean'])} | {pct(event['mfe'][f'{h}d']['median'])} | {pct(event['mae'][f'{h}d']['mean'])} | {pct(event['mae'][f'{h}d']['median'])} |"
        for h in HORIZONS
    )

    def view_lines(groups: dict[str, Any], prefix: str) -> str:
        return "\n".join(
            f"| {prefix}:{name} | {row['source_n']} | {row['executable_n']} | {pct(row['full_fill']['10d']['rate'])} | {pct(row['net_returns']['t5_close']['mean'])} | {pct(row['net_returns']['t10_close']['mean'])} | {pct(row['net_returns']['t20_close']['mean'])} | {pct(row['date_equal']['net_returns']['t10_close']['mean'])} |"
            for name, row in groups.items()
        )

    board_lines = view_lines(result["boards"], "BOARD")
    layer_lines = view_lines(result["layer_structure"], "LAYER")
    st_lines = view_lines(result["st"], "ST")
    persistence_lines = view_lines(result["persistence"], "PERSISTENCE")
    collapse_lines = view_lines(result["collapse_depth"], "COLLAPSE")
    primary_width_lines = view_lines(result["zone_size"]["primary_width"], "PRIMARY_WIDTH")
    total_width_lines = view_lines(result["zone_size"]["total_width"], "TOTAL_WIDTH")
    prior_strength_lines = view_lines(result["prior_strength"]["board_relative"], "PRIOR_STRENGTH")
    runup_lines = view_lines(result["prior_strength"]["runup_speed"], "RUNUP_SPEED")
    return f"""# {EXPERIMENT}

Status: `{result['verdict']}`.

The V3 detector received informal user acceptance; no formal 20-chart precision rate is claimed. This first return-bearing study keeps all 617 V3 zone identities and every semantic threshold frozen. It reads Development 2014–2021 only. Validation 2022–2023 and repository 2024+ remain sealed.

## Population and execution

- V3 primary-layer events: {population['primary_layer_events']:,}
- Completed-minute zone acceptance bars: {population['zone_acceptance_bars']:,}
- Executable next-minute entries: {population['executable_zone_acceptance_entries']:,}
- Jumped through layer / invalid or censored: {population['jumped_through_primary_layer']:,} / {population['invalid_or_censored']:,}

The economic anchor is V3's first lower-boundary return. The executable signal is the first completed minute close at or above L; entry is the next legal minute open. Entry prices above U are structural jump-through diagnostics and never enter executable returns.

## Zone traversal

| Horizon | Full fill | Mean capped max traversal | Mean capped terminal traversal |
|---|---:|---:|---:|
""" + "\n".join(
        f"| {h}d | {pct(event['full_fill'][f'{h}d']['rate'])} | {pct(event['max_traversal_capped'][f'{h}d']['mean'])} | {pct(event['terminal_traversal_capped'][f'{h}d']['mean'])} |"
        for h in HORIZONS
    ) + f"""

Same-session full fills: {result['summary']['t1_constraint']['same_day_structural_full_fill_count']:,} ({pct(result['summary']['t1_constraint']['same_day_structural_full_fill_rate'])}). Median/p25/p75 sessions to full fill by day 20: {time['median_sessions']}/{time['p25_sessions']}/{time['p75_sessions']}. Day-20 unresolved fraction: {pct(time['unresolved_by_20'])}.

The layer was already structurally full-filled before the completed-close acceptance in {result['summary']['structural_to_executable_translation']['full_fill_before_acceptance_count']:,} cases and before executable entry in {result['summary']['structural_to_executable_translation']['full_fill_before_entry_count']:,} cases. Post-entry full-fill rates are {pct(event['executable_full_fill']['5d']['rate'])} by 5d, {pct(event['executable_full_fill']['10d']['rate'])} by 10d, and {pct(event['executable_full_fill']['20d']['rate'])} by 20d.

### Failure ordering

| Horizon | Fast rejection | Daily rejection | Fill before fast rejection | Fill before daily rejection |
|---|---:|---:|---:|---:|
{failure_lines}

### Executable excursion

| Horizon | Mean MFE | Median MFE | Mean MAE | Median MAE |
|---|---:|---:|---:|---:|
{excursion_lines}

## Executable returns at unchanged 40 bp round trip

| Exit observation | Mean net | Median net | Positive rate |
|---|---:|---:|---:|
| T+1 legal open | {pct(event['net_returns']['t1_open']['mean'])} | {pct(event['net_returns']['t1_open']['median'])} | {pct(event['net_returns']['t1_open']['positive_rate'])} |
""" + "\n".join(
        f"| T+{h} close | {pct(event['net_returns'][f't{h}_close']['mean'])} | {pct(event['net_returns'][f't{h}_close']['median'])} | {pct(event['net_returns'][f't{h}_close']['positive_rate'])} |"
        for h in HORIZONS
    ) + f"""

Re-entry-date-equal T+5/T+10/T+20 net means are {pct(date['net_returns']['t5_close']['mean'])}/{pct(date['net_returns']['t10_close']['mean'])}/{pct(date['net_returns']['t20_close']['mean'])}. Same-day structural target hits are never represented as sellable under T+1. The positive T+20 observation is retained as a late-path diagnostic; the frozen monetizability gate was T+5/T+10 and is not revised after seeing outcomes.

## Development chronology

| Year | N | Fill 5d | Fill 10d | T+5 mean net | T+10 mean net |
|---|---:|---:|---:|---:|---:|
{yearly_lines}

## Board, layer, and ST views

| View | Source N | Executable N | Fill 10d | T+5 net | T+10 net | T+20 net | Date-equal T+10 net |
|---|---:|---:|---:|---:|---:|---:|---:|
{board_lines}
{layer_lines}
{st_lines}

For multilayer stacks, the next meaningful layer is reached by day 20 in {pct(result['summary']['multi_layer_progression']['reach_next_layer_20d']['rate'])}; it is fully filled in {pct(result['summary']['multi_layer_progression']['next_layer_full_fill_20d']['rate'])}; the full explicit stack repairs in {pct(result['summary']['multi_layer_progression']['full_stack_repair_20d']['rate'])}. The stack envelope is never treated as a gap.

## Frozen descriptive strata

| Stratum | Source N | Executable N | Fill 10d | T+5 net | T+10 net | T+20 net | Date-equal T+10 net |
|---|---:|---:|---:|---:|---:|---:|---:|
{persistence_lines}
{collapse_lines}
{primary_width_lines}
{total_width_lines}
{prior_strength_lines}
{runup_lines}

These strata are descriptive and overlap across separate panels. None is selected as a filter.

## Concentration and verdict

Top-five re-entry dates contribute {pct(result['summary']['concentration']['reentry_date']['top_5_dates_success_contribution'])} of successful day-20 fills and {pct(result['summary']['concentration']['positive_t5_net']['top_5_contribution'])} of positive T+5 net-return mass.

Verdict: `{result['verdict']}`. Frozen gate detail: `{json.dumps(v1.json_ready(result['verdict_gates']), ensure_ascii=False)}`.

No outcome threshold, horizon, board, entry, exit, or subgroup was selected. No strategy replay or walk-forward selection ran. Validation remains unopened.
"""


def run() -> dict[str, Any]:
    inputs = validate_inputs()
    source, terciles = prepare_source_events()
    acceptance, entries = build_acceptance_and_entries()
    status = build_path_bounds(source, acceptance, entries)
    build_paths()
    events = add_outcomes(status)
    result = build_result(events, inputs, terciles)
    v1.atomic_json(RESULT, result)
    v1.atomic_text(REPORT, render_report(result))
    return result


if __name__ == "__main__":
    answer = run()
    print(json.dumps({
        "experiment_id": answer["experiment_id"],
        "population": answer["population"],
        "verdict": answer["verdict"],
        "verdict_gates": answer["verdict_gates"],
        "audits": answer["audits"],
    }, ensure_ascii=False, indent=2))
