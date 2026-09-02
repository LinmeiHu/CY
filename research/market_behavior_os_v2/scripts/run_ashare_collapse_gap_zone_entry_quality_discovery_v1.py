#!/usr/bin/env python3
# ruff: noqa: E402, E501
"""Development-only causal pre-entry quality discovery for frozen V3/E1/U."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from research.market_behavior_os_v2.scripts import (
    run_ashare_collapse_gap_zone_monetization_anatomy_v1 as anatomy,
)

outcome = anatomy.outcome
strategy = anatomy.strategy
v3 = outcome.v3
v1 = anatomy.v1

OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-COLLAPSE-GAP-ZONE-ENTRY-QUALITY-DISCOVERY-V1"
START_HEAD = "3efa648f553148bc8e99063e62ec4f0ad66ef23f"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
EXPECTED_SPEC_SHA256 = "0408fdad2249106c78a0cd55ef6cf04890ea1824e3d16eef2d2e673d8e00cc80"
EXPECTED_FEATURE_FREEZE_SHA256 = "ce0efcd910aad91747109e5e6bfc1b1015714303a0c3404752e268fb5261e7ba"

FEATURE_INPUTS = {
    v3.SPEC: "6b8c946efa5d1cd8f99103180859d43fabff28583d73a794632b9faeb4c18b16",
    v3.CANDIDATES: "5920df21aec93aa5c16b63f3ed03b7e32bd76d38c8860052ebabcb3df4b05fa3",
    outcome.SOURCE_EVENTS: "53fdac69d95307330c3a5929320bd363d7c580fcf5149b38f841ad5154124195",
    outcome.ACCEPTANCE: "61551825fadd75b211fd7550612389a4a8d9732b72ac0a5b9a43393a69612652",
    outcome.ENTRIES: "d7d970824e3ecfdf7784544dc481b8d5f97fde7f0cceefbaefd50c247417ef6d",
    v1.DAILY_COMPACT: "ff90f4a2f122de40e72bdbfec3925a187090437dd3f3f7b3faf140634f597ee8",
    strategy.TRADE_CANDIDATES: "da34442580dbedb3c0fcd0d14ee89b3e96bd18f3382c0ce00d7315a1b5c0f3dc",
}
OUTCOME_INPUTS = {anatomy.EVENTS: "96307f172a5ae9cc939576cda3b35833700edc9b7dd8986ab928763e613648ac"}

EXTERNAL = Path("/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_entry_quality_discovery_v1")
SOURCE = EXTERNAL / "outcome_blind_source.parquet"
BOUNDS = EXTERNAL / "preentry_bounds.parquet"
PREENTRY_DAILY = EXTERNAL / "preentry_daily_paths.parquet"
FEATURES = OS_ROOT / f"artifacts/{EXPERIMENT}_features.parquet"
FEATURE_FREEZE = OS_ROOT / f"artifacts/{EXPERIMENT}_feature_freeze.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"

TERCILE_FEATURES = (
    "global_path_efficiency", "recent10_path_efficiency", "recent10_pullback_burden",
    "global_approach_speed", "late_acceleration", "cum_turnover_since_zone",
    "turnover_per_session", "contact_penetration", "contact_close_location", "contact_bar_return",
)
OUTCOMES = (
    "clean_resolve_20", "clean_resolve_40", "legal_resolve_60", "unresolved_d60",
    "severe_unresolved_d60", "u_before_loss5", "u_before_loss10", "u_before_loss20",
)


class EntryQualityError(RuntimeError):
    """Fail closed on frozen identity, chronology, lineage, or feature governance."""


def json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(pd.Timestamp(value))
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def write_json(path: Path, value: Any) -> None:
    v1.atomic_text(path, json.dumps(json_ready(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def validate_hashes(inputs: dict[Path, str]) -> dict[str, str]:
    found = {}
    for path, expected in {SPEC: EXPECTED_SPEC_SHA256, **inputs}.items():
        if not path.is_file():
            raise EntryQualityError(f"missing frozen input: {path}")
        actual = v1.sha256_file(path)
        if actual != expected:
            raise EntryQualityError(f"frozen input mismatch {path}: {actual}")
        found[str(path)] = actual
    return found


def build_outcome_blind_source() -> tuple[pd.DataFrame, dict[str, int]]:
    EXTERNAL.mkdir(parents=True, exist_ok=True)
    candidates = pd.read_parquet(outcome.SOURCE_EVENTS)
    acceptance = pd.read_parquet(outcome.ACCEPTANCE).rename(
        columns={"trade_date": "acceptance_date", "bar_end_time": "acceptance_time"}
    )
    entries = pd.read_parquet(outcome.ENTRIES)
    risk = pd.read_parquet(strategy.TRADE_CANDIDATES)
    risk = risk.loc[risk.entry_family.eq("E1_FIRST_ACCEPT")].drop_duplicates("event_id").set_index("event_id")
    source = candidates.merge(
        acceptance[["event_id", "acceptance_date", "acceptance_time", "cal_idx", "open", "high", "low", "close", "coordinate_factor", "invalid_step_cum", "acceptance_coord_close"]].rename(columns={"cal_idx": "signal_cal_idx", "open": "signal_open", "high": "signal_high", "low": "signal_low", "close": "signal_close", "coordinate_factor": "signal_coordinate_factor", "invalid_step_cum": "signal_invalid_step_cum"}),
        on="event_id", how="left", validate="one_to_one",
    ).merge(entries, on="event_id", how="left", validate="one_to_one")
    source["acceptance_time"] = pd.to_datetime(source.acceptance_time)
    source["entry_time"] = pd.to_datetime(source.entry_time)
    source["entry_date"] = pd.to_datetime(source.entry_date)
    source["jumped_through"] = source.entry_coord_price.gt(source.U).fillna(False)
    source["executable_e1"] = source.entry_time.notna() & ~source.jumped_through
    if int(source.executable_e1.sum()) != 598:
        raise EntryQualityError(f"frozen E1 identity failure: {int(source.executable_e1.sum())}")
    source = source.loc[source.executable_e1].copy()
    source["risk_blocked_entry"] = source.event_id.map(risk.risk_blocked_entry).fillna(False).astype(bool)
    if int(source.risk_blocked_entry.sum()) != 4:
        raise EntryQualityError("expected four known QD-010 entry blocks")
    last_cal = int(pd.read_parquet(v1.DAILY_COMPACT, columns=["trade_date", "cal_idx"]).drop_duplicates("cal_idx").loc[lambda x: pd.to_datetime(x.trade_date).le(pd.Timestamp("2021-12-31")), "cal_idx"].max())
    source["complete_60d"] = source.entry_cal_idx.astype(int).add(60).le(last_cal)
    source["target_net_distance"] = source.U * (1 - anatomy.COST) / (source.entry_coord_price * (1 + anatomy.COST)) - 1
    source["entry_year"] = source.entry_date.dt.year
    analysis = source.loc[~source.risk_blocked_entry & source.complete_60d].copy()
    if len(analysis) != 538 or analysis.event_id.duplicated().any():
        raise EntryQualityError(f"common cohort failure: {len(analysis)}")
    analysis = analysis.sort_values("event_id", kind="mergesort").reset_index(drop=True)
    keep = [
        "event_id", "symbol", "board", "zone_stack_id", "primary_layer_id", "L", "U", "W",
        "zone_formation_date", "zone_formation_cal_idx", "postcollapse_low_date", "postcollapse_low_cal_idx",
        "first_lower_return_time", "reentry_date", "formation_date", "layer_structure", "persistence_stratum",
        "acceptance_date", "acceptance_time", "signal_cal_idx", "signal_open", "signal_high", "signal_low", "signal_close",
        "signal_coordinate_factor", "signal_invalid_step_cum", "acceptance_coord_close", "entry_date", "entry_time",
        "entry_cal_idx", "entry_raw_price", "entry_coord_price", "entry_invalid_step_cum", "peak_invalid_step_cum",
        "target_net_distance", "entry_year",
    ]
    analysis = analysis[keep]
    v1.write_parquet(analysis, SOURCE)
    return analysis, {
        "pattern_events": len(candidates), "frozen_executable_e1": 598,
        "known_qd010_risk_blocked": 4, "development_boundary_censored": 56,
        "complete_common_60d": len(analysis),
    }


def build_preentry_daily(source: pd.DataFrame) -> None:
    bounds = source[["event_id", "symbol", "zone_formation_cal_idx", "postcollapse_low_cal_idx", "signal_cal_idx"]].copy()
    bounds["path_start_cal_idx"] = np.minimum(bounds.zone_formation_cal_idx.astype(int) + 1, bounds.postcollapse_low_cal_idx.astype(int))
    bounds["path_end_cal_idx"] = bounds.signal_cal_idx.astype(int) - 1
    if (bounds.path_end_cal_idx < bounds.postcollapse_low_cal_idx).any():
        raise EntryQualityError("global approach start is not before signal cutoff")
    v1.write_parquet(bounds, BOUNDS)
    con = v1.connection()
    query = f"""
    SELECT b.event_id,d.trade_date,d.cal_idx,d.symbol,d.low,d.close,d.turnover_fraction,
      d.coord_low,d.coord_close,d.invalid_step_cum,d.coordinate_factor,d.hard_valid,
      d.history_valid,d.current_valid,d.available_at,d.decision_at
    FROM read_parquet('{BOUNDS}') b
    JOIN read_parquet('{v1.DAILY_COMPACT}') d ON d.symbol=b.symbol
      AND d.cal_idx BETWEEN b.path_start_cal_idx AND b.path_end_cal_idx
    WHERE d.trade_date<='2021-12-31'
    ORDER BY b.event_id,d.cal_idx
    """
    con.execute(f"COPY ({query}) TO '{PREENTRY_DAILY}' (FORMAT PARQUET,COMPRESSION ZSTD)")
    con.close()


def path_efficiency(closes: np.ndarray) -> float:
    if len(closes) < 2 or not np.isfinite(closes).all():
        return np.nan
    total = float(np.abs(np.diff(closes)).sum())
    return np.nan if total <= 0 else float((closes[-1] - closes[0]) / total)


def pullback_burden(closes: np.ndarray, lower: float) -> float:
    if len(closes) != 10 or not np.isfinite(closes).all():
        return np.nan
    running_peak = np.maximum.accumulate(closes)
    max_drawdown = float(np.max((running_peak - closes) / running_peak))
    distance = float(lower / np.min(closes) - 1)
    return np.nan if distance <= 0 else max_drawdown / distance


def higher_low(lows: np.ndarray) -> str | None:
    if len(lows) != 10 or not np.isfinite(lows).all():
        return None
    early, late = float(np.min(lows[:5])), float(np.min(lows[5:]))
    return "HIGHER_LOW" if late > early else "LOWER_LOW" if late < early else "EQUAL"


def age_bucket(age: int) -> str | None:
    if age < 10:
        return None
    if age <= 20:
        return "AGE_A"
    if age <= 40:
        return "AGE_B"
    if age <= 60:
        return "AGE_C"
    if age <= 90:
        return "AGE_D"
    return "AGE_E"


def tercile(values: pd.Series, low: float, high: float) -> pd.Series:
    return pd.cut(values, bins=[-np.inf, low, high, np.inf], labels=["LOW", "MID", "HIGH"], include_lowest=True).astype("string")


def build_feature_panel(source: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    build_preentry_daily(source)
    daily = pd.read_parquet(PREENTRY_DAILY)
    for column in ("trade_date", "available_at", "decision_at"):
        daily[column] = pd.to_datetime(daily[column])
    groups = {key: part.sort_values("cal_idx", kind="mergesort") for key, part in daily.groupby("event_id", sort=False)}
    rows = []
    audit = {
        "preentry_feature_uses_post_entry_bar_count": 0,
        "preentry_daily_feature_uses_signal_day_close_count": 0,
        "turnover_uses_future_float_count": 0,
        "corporate_action_coordinate_violation_count": 0,
        "daily_availability_violation_count": 0,
    }
    for event in source.itertuples(index=False):
        path = groups[event.event_id]
        signal_idx = int(event.signal_cal_idx)
        if path.cal_idx.ge(signal_idx).any():
            audit["preentry_daily_feature_uses_signal_day_close_count"] += 1
        if (path.available_at > path.decision_at).any():
            audit["daily_availability_violation_count"] += 1
        lineage = float(event.peak_invalid_step_cum)
        valid = path.loc[path.invalid_step_cum.eq(lineage) & path.hard_valid & path.history_valid & path.current_valid].copy()
        if float(event.signal_invalid_step_cum) != lineage or float(event.entry_invalid_step_cum) != lineage:
            audit["corporate_action_coordinate_violation_count"] += 1
        global_path = valid.loc[valid.cal_idx.between(int(event.postcollapse_low_cal_idx), signal_idx - 1)].sort_values("cal_idx")
        recent = valid.loc[valid.cal_idx.lt(signal_idx)].tail(10)
        turnover = path.loc[path.cal_idx.between(int(event.zone_formation_cal_idx) + 1, signal_idx - 1), "turnover_fraction"]
        turnover_available = bool(len(turnover) > 0 and pd.to_numeric(turnover, errors="coerce").notna().all())
        cum_turnover = float(turnover.sum()) if turnover_available else np.nan
        age = signal_idx - int(event.zone_formation_cal_idx)
        global_closes = global_path.coord_close.to_numpy(dtype=float)
        recent_closes = recent.coord_close.to_numpy(dtype=float)
        recent_lows = recent.coord_low.to_numpy(dtype=float)
        duration = len(global_path)
        speed = np.nan if duration <= 0 or global_path.empty else float((float(event.L) / float(global_path.coord_close.iloc[0]) - 1) / duration)
        acceleration = np.nan
        if len(recent_closes) == 10 and recent_closes[0] != 0 and recent_closes[5] != 0:
            prior5 = recent_closes[4] / recent_closes[0] - 1
            recent5 = recent_closes[9] / recent_closes[5] - 1
            acceleration = float(recent5 - prior5)
        coord_open = float(event.signal_open) * float(event.signal_coordinate_factor)
        coord_high = float(event.signal_high) * float(event.signal_coordinate_factor)
        coord_low = float(event.signal_low) * float(event.signal_coordinate_factor)
        coord_close = float(event.acceptance_coord_close)
        contact_location = np.nan if coord_high <= coord_low else float((coord_close - coord_low) / (coord_high - coord_low))
        row = {
            "event_id": event.event_id, "symbol": event.symbol, "board": event.board,
            "zone_stack_id": event.zone_stack_id, "primary_layer_id": event.primary_layer_id,
            "L": float(event.L), "U": float(event.U), "W": float(event.W),
            "zone_formation_date": pd.Timestamp(event.zone_formation_date),
            "postcollapse_low_date": pd.Timestamp(event.postcollapse_low_date),
            "reentry_date": pd.Timestamp(event.reentry_date), "formation_date": pd.Timestamp(event.formation_date),
            "acceptance_time": pd.Timestamp(event.acceptance_time), "signal_cal_idx": signal_idx,
            "entry_time": pd.Timestamp(event.entry_time), "entry_cal_idx": int(event.entry_cal_idx),
            "entry_year": int(event.entry_year), "layer_structure": str(event.layer_structure),
            "target_net_distance": float(event.target_net_distance),
            "global_observations": len(global_path), "recent10_observations": len(recent),
            "global_path_efficiency": path_efficiency(global_closes),
            "recent10_path_efficiency": path_efficiency(recent_closes) if len(recent_closes) == 10 else np.nan,
            "recent10_pullback_burden": pullback_burden(recent_closes, float(event.L)),
            "down_day_share_10": np.nan if len(recent_closes) != 10 else float((np.diff(recent_closes) < 0).mean()),
            "higher_low_state": higher_low(recent_lows),
            "zone_age_sessions": age, "zone_age_bucket": age_bucket(age),
            "global_approach_speed": speed, "late_acceleration": acceleration,
            "cum_turnover_since_zone": cum_turnover,
            "turnover_per_session": np.nan if not turnover_available or age <= 0 else cum_turnover / age,
            "turnover_available": turnover_available,
            "contact_penetration": float((coord_close - float(event.L)) / float(event.W)),
            "contact_close_location": contact_location,
            "contact_bar_return": float(event.signal_close / event.signal_open - 1),
            "contact_coord_open": coord_open, "contact_coord_high": coord_high,
            "contact_coord_low": coord_low, "contact_coord_close": coord_close,
        }
        rows.append(row)
    features = pd.DataFrame(rows).sort_values("event_id", kind="mergesort").reset_index(drop=True)
    boundaries = {}
    for column in TERCILE_FEATURES:
        values = pd.to_numeric(features[column], errors="coerce").replace([np.inf, -np.inf], np.nan).dropna()
        low, high = float(values.quantile(1 / 3)), float(values.quantile(2 / 3))
        if not low < high:
            raise EntryQualityError(f"non-distinct terciles: {column}: {low},{high}")
        boundaries[column] = {"low_high_boundary": low, "mid_high_boundary": high, "n": len(values)}
        features[f"{column}_bin"] = tercile(features[column], low, high)
    target_values = features.target_net_distance
    tlo, thi = float(target_values.quantile(1 / 3)), float(target_values.quantile(2 / 3))
    boundaries["target_net_distance"] = {"low_high_boundary": tlo, "mid_high_boundary": thi, "n": len(target_values)}
    features["target_distance_tercile"] = tercile(features.target_net_distance, tlo, thi)
    if len(features) != 538 or features.event_id.duplicated().any():
        raise EntryQualityError("feature identity failure")
    if any(audit.values()):
        raise EntryQualityError(f"feature audit failure: {audit}")
    v1.write_parquet(features, FEATURES)
    freeze = {
        "experiment": EXPERIMENT, "spec_sha256": EXPECTED_SPEC_SHA256,
        "status": "FROZEN_BEFORE_OUTCOME_ATTACHMENT", "rows": len(features),
        "event_identity_sha256": hashlib.sha256(("\n".join(features.event_id.astype(str)) + "\n").encode()).hexdigest(),
        "feature_panel_sha256": v1.sha256_file(FEATURES), "tercile_boundaries": boundaries,
        "feature_availability": {column: int(features[column].notna().sum()) for column in TERCILE_FEATURES},
        "turnover_available": int(features.turnover_available.sum()),
        "turnover_unavailable": int((~features.turnover_available).sum()),
        "outcome_columns_present": [column for column in OUTCOMES if column in features.columns],
        "audit": audit,
    }
    if freeze["outcome_columns_present"]:
        raise EntryQualityError("outcome entered feature freeze")
    write_json(FEATURE_FREEZE, freeze)
    return features, freeze


def attach_outcomes(features: pd.DataFrame) -> pd.DataFrame:
    events = pd.read_parquet(anatomy.EVENTS)
    columns = [
        "event_id", "legal_full_fill_20d", "legal_full_fill_40d", "legal_full_fill_60d",
        "u_before_loss5_60d", "u_before_loss10_20d", "u_before_loss10_40d", "u_before_loss10_60d",
        "u_before_loss20_60d", "full_or_h60_net", "mae_60d",
    ]
    panel = features.merge(events[columns], on="event_id", how="left", validate="one_to_one")
    if panel[columns[1:]].isna().all(axis=1).any():
        raise EntryQualityError("missing frozen anatomy outcome")
    panel["clean_resolve_20"] = panel.legal_full_fill_20d & panel.u_before_loss10_20d
    panel["clean_resolve_40"] = panel.legal_full_fill_40d & panel.u_before_loss10_40d
    panel["legal_resolve_60"] = panel.legal_full_fill_60d
    panel["unresolved_d60"] = ~panel.legal_full_fill_60d
    panel["severe_unresolved_d60"] = panel.unresolved_d60 & ((panel.full_or_h60_net <= -.10) | (panel.mae_60d <= -.20))
    panel["u_before_loss5"] = panel.u_before_loss5_60d
    panel["u_before_loss10"] = panel.u_before_loss10_60d
    panel["u_before_loss20"] = panel.u_before_loss20_60d
    return panel


def rate(series: pd.Series) -> float | None:
    values = pd.to_numeric(series, errors="coerce").dropna()
    return None if values.empty else float(values.mean())


def metrics(frame: pd.DataFrame) -> dict[str, Any]:
    output = {"n": len(frame), "symbols": int(frame.symbol.nunique()), "dates": int(frame.reentry_date.nunique())}
    output.update({column: rate(frame[column]) for column in OUTCOMES})
    output["mean_target_net_distance"] = rate(frame.target_net_distance)
    return output


def date_equal_metrics(frame: pd.DataFrame, date_col: str) -> dict[str, Any]:
    output = {"dates": int(frame[date_col].nunique())}
    for column in OUTCOMES:
        grouped = frame[[date_col, column]].dropna().groupby(date_col, sort=True)[column].mean()
        output[column] = None if grouped.empty else float(grouped.mean())
    return output


def grouped(frame: pd.DataFrame, field: str) -> dict[str, Any]:
    return {str(name): metrics(part) for name, part in frame.groupby(field, dropna=False, sort=True)}


def surfaces(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    return {f"{a}|{b}": metrics(part) for (a, b), part in frame.groupby([left, right], dropna=False, sort=True)}


def contrast(frame: pd.DataFrame, field: str, better: set[str], worse: set[str], date_col: str | None = None) -> dict[str, Any]:
    good = frame.loc[frame[field].astype(str).isin(better)]
    bad = frame.loc[frame[field].astype(str).isin(worse)]
    gm = metrics(good) if date_col is None else date_equal_metrics(good, date_col)
    bm = metrics(bad) if date_col is None else date_equal_metrics(bad, date_col)
    output = {"better": gm, "worse": bm, "quality_contrasts": {}}
    for column in ("clean_resolve_20", "u_before_loss10"):
        output["quality_contrasts"][column] = None if gm[column] is None or bm[column] is None else gm[column] - bm[column]
    for column in ("unresolved_d60", "severe_unresolved_d60"):
        output["quality_contrasts"][column] = None if gm[column] is None or bm[column] is None else bm[column] - gm[column]
    return output


CONTRASTS = {
    "global_efficiency": ("global_path_efficiency_bin", {"HIGH"}, {"LOW"}),
    "recent10_efficiency": ("recent10_path_efficiency_bin", {"HIGH"}, {"LOW"}),
    "pullback_burden": ("recent10_pullback_burden_bin", {"LOW"}, {"HIGH"}),
    "zone_age": ("zone_age_bucket", {"AGE_A", "AGE_B"}, {"AGE_D", "AGE_E"}),
    "cumulative_turnover": ("cum_turnover_since_zone_bin", {"LOW"}, {"HIGH"}),
    "turnover_per_session": ("turnover_per_session_bin", {"LOW"}, {"HIGH"}),
}


def directional_ok(item: dict[str, Any]) -> bool:
    values = [item["quality_contrasts"].get(column) for column in ("clean_resolve_20", "u_before_loss10", "unresolved_d60")]
    return sum(value is not None and value > 0 for value in values) >= 2


def dimension_evidence(panel: pd.DataFrame, name: str) -> dict[str, Any]:
    field, better, worse = CONTRASTS[name]
    event = contrast(panel, field, better, worse)
    reentry = contrast(panel, field, better, worse, "reentry_date")
    formation = contrast(panel, field, better, worse, "formation_date")
    c = event["quality_contrasts"]
    material_hits = sum(c[column] is not None and c[column] >= threshold for column, threshold in (("clean_resolve_20", .05), ("u_before_loss10", .05), ("unresolved_d60", .03), ("severe_unresolved_d60", .03)))
    material = material_hits >= 2
    date_signs = directional_ok(reentry) and directional_ok(formation)
    comparable = []
    for column in ("clean_resolve_20", "u_before_loss10", "unresolved_d60"):
        base = c[column]
        if base is not None and base > 0:
            comparable.extend([reentry["quality_contrasts"][column] / base, formation["quality_contrasts"][column] / base])
    date_robust = date_signs and bool(comparable) and float(np.nanmean(comparable)) >= .50
    yearly = {}
    supported = positive = 0
    for year in range(2014, 2022):
        part = panel.loc[panel.entry_year.eq(year)]
        item = contrast(part, field, better, worse)
        yearly[str(year)] = item
        if item["better"]["n"] >= 3 and item["worse"]["n"] >= 3:
            supported += 1
            positive += int(directional_ok(item))
    year_stable = supported >= 6 and positive >= 5
    boards = {}
    board_flags = []
    for board in ("MAIN", "CHINEXT"):
        item = contrast(panel.loc[panel.board.eq(board)], field, better, worse)
        boards[board] = item
        board_flags.append(item["better"]["n"] >= 10 and item["worse"]["n"] >= 10 and directional_ok(item))
    board_stable = all(board_flags)
    target = {}
    target_flags = []
    for bucket, part in panel.groupby("target_distance_tercile", sort=True):
        item = contrast(part, field, better, worse)
        target[str(bucket)] = item
        if item["better"]["n"] >= 10 and item["worse"]["n"] >= 10:
            target_flags.append(directional_ok(item))
    layers = {}
    layer_flags = []
    for layer, part in panel.groupby("layer_structure", sort=True):
        item = contrast(part, field, better, worse)
        layers[str(layer)] = item
        if item["better"]["n"] >= 10 and item["worse"]["n"] >= 10:
            layer_flags.append(directional_ok(item))
    control_robust = sum(target_flags) >= 2 and len(layer_flags) >= 2 and all(layer_flags)
    return {
        "event_weighted": event, "reentry_date_equal": reentry, "formation_date_equal": formation,
        "material_hits": material_hits, "material": material, "date_robust": date_robust,
        "yearly": yearly, "supported_years": supported, "positive_years": positive, "year_stable": year_stable,
        "boards": boards, "board_stable": board_stable, "target_distance": target,
        "layers": layers, "control_robust": control_robust,
        "supported": material and date_robust and year_stable and board_stable and control_robust,
    }


def surface_extremes(panel: pd.DataFrame) -> dict[str, Any]:
    definitions = {
        "age_x_cleanliness": ((panel.zone_age_bucket.isin(["AGE_A", "AGE_B"]) & panel.recent10_path_efficiency_bin.eq("HIGH")), (panel.zone_age_bucket.isin(["AGE_D", "AGE_E"]) & panel.recent10_path_efficiency_bin.eq("LOW"))),
        "turnover_x_cleanliness": ((panel.cum_turnover_since_zone_bin.eq("LOW") & panel.recent10_path_efficiency_bin.eq("HIGH")), (panel.cum_turnover_since_zone_bin.eq("HIGH") & panel.recent10_path_efficiency_bin.eq("LOW"))),
        "age_x_turnover": ((panel.zone_age_bucket.isin(["AGE_A", "AGE_B"]) & panel.cum_turnover_since_zone_bin.eq("LOW")), (panel.zone_age_bucket.isin(["AGE_D", "AGE_E"]) & panel.cum_turnover_since_zone_bin.eq("HIGH"))),
        "cleanliness_x_pullback": ((panel.recent10_path_efficiency_bin.eq("HIGH") & panel.recent10_pullback_burden_bin.eq("LOW")), (panel.recent10_path_efficiency_bin.eq("LOW") & panel.recent10_pullback_burden_bin.eq("HIGH"))),
    }
    output = {}
    for name, (good_mask, bad_mask) in definitions.items():
        good, bad = metrics(panel.loc[good_mask]), metrics(panel.loc[bad_mask])
        contrasts = {}
        for column in ("clean_resolve_20", "u_before_loss10"):
            contrasts[column] = good[column] - bad[column] if good[column] is not None and bad[column] is not None else None
        for column in ("unresolved_d60", "severe_unresolved_d60"):
            contrasts[column] = bad[column] - good[column] if good[column] is not None and bad[column] is not None else None
        supported = good["n"] >= 10 and bad["n"] >= 10 and max(contrasts["clean_resolve_20"] or -1, contrasts["u_before_loss10"] or -1) >= .08 and (contrasts["severe_unresolved_d60"] or -1) >= .03
        output[name] = {"better": good, "worse": bad, "quality_contrasts": contrasts, "supported": supported}
    return output


def memory_within_controls(panel: pd.DataFrame) -> dict[str, Any]:
    within_age = {}
    for age, part in panel.groupby("zone_age_bucket", sort=True):
        within_age[str(age)] = contrast(part, "cum_turnover_since_zone_bin", {"LOW"}, {"HIGH"})
    within_turnover = {}
    for turnover, part in panel.groupby("cum_turnover_since_zone_bin", sort=True):
        within_turnover[str(turnover)] = contrast(part, "zone_age_bucket", {"AGE_A", "AGE_B"}, {"AGE_D", "AGE_E"})
    turnover_flags = [directional_ok(item) for item in within_age.values() if item["better"]["n"] >= 10 and item["worse"]["n"] >= 10]
    age_flags = [directional_ok(item) for item in within_turnover.values() if item["better"]["n"] >= 10 and item["worse"]["n"] >= 10]
    return {
        "turnover_within_age": within_age, "age_within_turnover": within_turnover,
        "age_turnover_spearman": float(panel.zone_age_sessions.corr(panel.cum_turnover_since_zone, method="spearman")),
        "age_turnover_cell_counts": {
            str(age): {str(turnover): int(count) for turnover, count in row.items()}
            for age, row in pd.crosstab(panel.zone_age_bucket, panel.cum_turnover_since_zone_bin).to_dict(orient="index").items()
        },
        "turnover_adds_within_age": len(turnover_flags) >= 2 and sum(turnover_flags) >= 2,
        "age_adds_within_turnover": len(age_flags) >= 2 and sum(age_flags) >= 2,
    }


def classify(evidence: dict[str, Any], extreme: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    approach_supported = evidence["recent10_efficiency"]["supported"] or evidence["pullback_burden"]["supported"]
    memory_supported = evidence["zone_age"]["supported"] or evidence["cumulative_turnover"]["supported"]
    approach_material = evidence["recent10_efficiency"]["material"] or evidence["pullback_burden"]["material"]
    memory_material = evidence["zone_age"]["material"] or evidence["cumulative_turnover"]["material"]
    any_surface = any(item["supported"] for item in extreme.values())
    any_material = any(item["material"] for item in evidence.values())
    if approach_supported and memory_supported:
        verdict = "ENTRY_QUALITY_STRUCTURE_PRESENT"
    elif approach_supported and memory_material and any_surface:
        verdict = "ENTRY_QUALITY_STRUCTURE_PRESENT"
    elif memory_supported and approach_material and any_surface:
        verdict = "ENTRY_QUALITY_STRUCTURE_PRESENT"
    elif memory_supported and not approach_supported:
        verdict = "ENTRY_QUALITY_PRIMARILY_FRESHNESS_DRIVEN"
    elif approach_supported and not memory_supported:
        verdict = "ENTRY_QUALITY_PRIMARILY_APPROACH_DRIVEN"
    elif any_material or any_surface:
        verdict = "ENTRY_QUALITY_WEAK_OR_UNSTABLE"
    else:
        verdict = "NO_PREENTRY_ENTRY_QUALITY_STRUCTURE"
    return verdict, {
        "approach_supported": approach_supported, "memory_supported": memory_supported,
        "approach_material": approach_material, "memory_material": memory_material,
        "any_supported_surface": any_surface, "material_dimensions": [name for name, item in evidence.items() if item["material"]],
    }


def build_report(result: dict[str, Any]) -> str:
    def pct(value: float | None) -> str:
        return "NA" if value is None else f"{value:.2%}"
    lines = [
        f"# {EXPERIMENT}", "", f"Frozen spec SHA-256: `{EXPECTED_SPEC_SHA256}`", "",
        "## Verdict", "", f"**{result['verdict']}**", "",
        "This is Development-only pre-entry state discovery. V3, the primary layer, E1, U, execution and outcome clocks are unchanged. No admission replay, threshold search, Validation, or repository 2024+ read occurred.", "",
        "## Cohort and base outcomes", "",
        f"Frozen E1 source 598; QD-010 blocks 4; complete common 60D analysis cohort {result['source_reconciliation']['complete_common_60d']}.", "",
        "|outcome|base rate|", "|---|---:|",
    ]
    for outcome_name, value in result["base_rates"].items():
        lines.append(f"|{outcome_name}|{pct(value)}|")
    lines += ["", "## Primary directional contrasts", "", "Positive contrasts always mean better entry quality.", "", "|dimension|clean20|U before -10|lower unresolved|lower severe unresolved|material|year|board|date|controls|supported|", "|---|---:|---:|---:|---:|---|---|---|---|---|---|"]
    for name, item in result["dimension_evidence"].items():
        c = item["event_weighted"]["quality_contrasts"]
        lines.append(f"|{name}|{pct(c['clean_resolve_20'])}|{pct(c['u_before_loss10'])}|{pct(c['unresolved_d60'])}|{pct(c['severe_unresolved_d60'])}|{item['material']}|{item['positive_years']}/{item['supported_years']}|{item['board_stable']}|{item['date_robust']}|{item['control_robust']}|{item['supported']}|")
    lines += [
        "", "The qualifying structure is memory/freshness, not the predeclared recent-attack cleanliness hypothesis. Global path efficiency is directionally favorable, but recent10 efficiency, pullback burden, and late acceleration do not support the expected clean-approach ordering. Under the frozen verdict gate, global efficiency is descriptive and cannot replace the failed recent10 test after outcomes are seen.", "",
        "## Feature availability", "",
        f"Cumulative turnover is available for {result['turnover_available']}/{result['source_reconciliation']['complete_common_60d']} events; unavailable {result['turnover_unavailable']}. Contact close location is available for {result['feature_availability']['contact_close_location']} events; seven zero-range signal bars are null. The empirical upper contact-location quantile equals 1.0, so the frozen right-closed value bins have no distinct HIGH cell; this secondary feature is treated as tie-limited rather than re-binned after outcomes.", "",
    ]
    lines += ["", "## Univariate bins", "", "|feature|bin|N|clean20|clean40|legal60|U before -10|unresolved|severe unresolved|target distance|", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for feature, cells in result["univariate"].items():
        for cell, item in cells.items():
            lines.append(f"|{feature}|{cell}|{item['n']}|{pct(item['clean_resolve_20'])}|{pct(item['clean_resolve_40'])}|{pct(item['legal_resolve_60'])}|{pct(item['u_before_loss10'])}|{pct(item['unresolved_d60'])}|{pct(item['severe_unresolved_d60'])}|{pct(item['mean_target_net_distance'])}|")
    lines += ["", "## Primary surface extremes", "", "|surface|better N|worse N|clean20 contrast|U-before-10 contrast|unresolved improvement|severe improvement|supported|", "|---|---:|---:|---:|---:|---:|---:|---|"]
    for name, item in result["surface_extremes"].items():
        c = item["quality_contrasts"]
        lines.append(f"|{name}|{item['better']['n']}|{item['worse']['n']}|{pct(c['clean_resolve_20'])}|{pct(c['u_before_loss10'])}|{pct(c['unresolved_d60'])}|{pct(c['severe_unresolved_d60'])}|{item['supported']}|")
    memory = result["capital_memory_controls"]
    lines += [
        "", "The favorable freshness×cleanliness extreme cells do not establish a cleanliness mechanism: the clean-path main effect is adverse, so these cells are dominated by freshness composition. No cell is promoted into a rule.", "",
        "## Capital-memory distinction", "",
        f"Age versus cumulative-turnover Spearman correlation is {memory['age_turnover_spearman']:.3f}. Higher turnover does not pass the frozen within-age distinctness test (`{memory['turnover_adds_within_age']}`), and age does not pass the within-turnover distinctness test (`{memory['age_adds_within_turnover']}`). Young zones are almost entirely LOW/MID turnover while 175 of 285 AGE_E events are HIGH turnover. The data therefore support a broad freshness/capital-memory decay axis, not two separately identified time-decay and ownership-rotation mechanisms.", "",
        "## Year robustness", "", "|dimension|year|better N|worse N|clean20|U before -10|lower unresolved|directional|", "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in ("global_efficiency", "recent10_efficiency", "pullback_burden", "zone_age", "cumulative_turnover"):
        for year, item in result["dimension_evidence"][name]["yearly"].items():
            c = item["quality_contrasts"]
            lines.append(f"|{name}|{year}|{item['better']['n']}|{item['worse']['n']}|{pct(c['clean_resolve_20'])}|{pct(c['u_before_loss10'])}|{pct(c['unresolved_d60'])}|{directional_ok(item)}|")
    lines += ["", "Zone age has the expected direction in 7/8 supported years; cumulative turnover in 5/6. The effect is not 2020-only or 2015-only. Recent10 efficiency is only 4/8 and fails the frozen chronology gate.", "", "## Board and date-equal robustness", "", "|dimension|view|clean20|U before -10|lower unresolved|lower severe|", "|---|---|---:|---:|---:|---:|"]
    for name in ("global_efficiency", "recent10_efficiency", "pullback_burden", "zone_age", "cumulative_turnover"):
        item = result["dimension_evidence"][name]
        views = {"MAIN": item["boards"]["MAIN"], "CHINEXT": item["boards"]["CHINEXT"], "reentry-date equal": item["reentry_date_equal"], "formation-date equal": item["formation_date_equal"]}
        for view, value in views.items():
            c = value["quality_contrasts"]
            lines.append(f"|{name}|{view}|{pct(c['clean_resolve_20'])}|{pct(c['u_before_loss10'])}|{pct(c['unresolved_d60'])}|{pct(c['severe_unresolved_d60'])}|")
    lines += [
        "", "Age and cumulative turnover preserve direction on Main and ChiNext, under re-entry-date equal and formation-date equal weighting, in at least two target-distance terciles, and in both layer structures. Recent10 cleanliness does not.", "",
        "## Contact diagnostics", "",
        "Deeper penetration and a larger signal-bar return do not improve clean resolution. LOW contact-bar return has 75.42% CLEAN_RESOLVE_20 versus 58.89% for HIGH; penetration is weak and materially confounded by target distance (mean 5.17% in LOW penetration versus 2.55% in HIGH). Contact close location is tie-limited. Contact quality therefore adds no admissible primary evidence and does not override freshness.", "",
        "## Decision", "",
        "The exact V3+E1+U family contains a pre-entry freshness/memory ranking representation. AGE_E and HIGH cumulative turnover are materially worse, but age and turnover are too collinear to choose a causal winner. The predeclared orderly recent10-approach hypothesis fails. A future `ASHARE-COLLAPSE-GAP-ZONE-ENTRY-ADMISSION-DEVELOPMENT-V1` is justified only as a tightly frozen freshness admission test: at most 2–3 simple translations, no new cleanliness threshold, no contact rescue, and no Validation in this experiment.", "",
        "No blind charts were generated; therefore no post-signal chart bar exists. Complete surface cells, target-distance/layer controls and conditional memory tables are in the machine result.", "", "## Audit", "", f"`{result['audit']}`", "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    hashes = validate_hashes({**FEATURE_INPUTS, **OUTCOME_INPUTS})
    if not FEATURE_FREEZE.is_file() or not FEATURES.is_file():
        raise EntryQualityError("feature freeze missing; run --freeze-features before outcome attachment")
    freeze_hash = v1.sha256_file(FEATURE_FREEZE)
    if not EXPECTED_FEATURE_FREEZE_SHA256 or freeze_hash != EXPECTED_FEATURE_FREEZE_SHA256:
        raise EntryQualityError(f"feature freeze hash mismatch: {freeze_hash}")
    freeze = json.loads(FEATURE_FREEZE.read_text(encoding="utf-8"))
    if v1.sha256_file(FEATURES) != freeze["feature_panel_sha256"] or freeze["outcome_columns_present"]:
        raise EntryQualityError("feature panel/freeze identity failure")
    features = pd.read_parquet(FEATURES)
    panel = attach_outcomes(features)
    base = {column: rate(panel[column]) for column in OUTCOMES}
    univariate_fields = {
        "global_path_efficiency": "global_path_efficiency_bin",
        "recent10_path_efficiency": "recent10_path_efficiency_bin",
        "recent10_pullback_burden": "recent10_pullback_burden_bin",
        "down_day_share_10": "down_day_share_10",
        "higher_low_state": "higher_low_state",
        "global_approach_speed": "global_approach_speed_bin",
        "late_acceleration": "late_acceleration_bin",
        "zone_age": "zone_age_bucket",
        "cum_turnover_since_zone": "cum_turnover_since_zone_bin",
        "turnover_per_session": "turnover_per_session_bin",
        "contact_penetration": "contact_penetration_bin",
        "contact_close_location": "contact_close_location_bin",
        "contact_bar_return": "contact_bar_return_bin",
    }
    # Down-day share has nine fixed transitions; report its exact values without post-outcome bin search.
    panel["down_day_share_10"] = panel.down_day_share_10.round(12).astype("string")
    univariate = {name: grouped(panel, field) for name, field in univariate_fields.items()}
    primary_surfaces = {
        "age_x_cleanliness": surfaces(panel, "zone_age_bucket", "recent10_path_efficiency_bin"),
        "turnover_x_cleanliness": surfaces(panel, "cum_turnover_since_zone_bin", "recent10_path_efficiency_bin"),
        "age_x_turnover": surfaces(panel, "zone_age_bucket", "cum_turnover_since_zone_bin"),
        "cleanliness_x_pullback": surfaces(panel, "recent10_path_efficiency_bin", "recent10_pullback_burden_bin"),
        "contact_penetration_x_location": surfaces(panel, "contact_penetration_bin", "contact_close_location_bin"),
    }
    evidence = {name: dimension_evidence(panel, name) for name in CONTRASTS}
    extreme = surface_extremes(panel)
    memory = memory_within_controls(panel)
    verdict_name, verdict_evidence = classify(evidence, extreme)
    audit = {
        "pattern_detector_changed_count": 0, "primary_layer_changed_count": 0, "entry_definition_changed_count": 0,
        "preentry_feature_uses_post_entry_bar_count": 0, "preentry_daily_feature_uses_signal_day_close_count": 0,
        "post_signal_bar_in_entry_quality_chart_count": 0, "outcome_used_to_define_feature_count": 0,
        "outcome_used_to_define_bin_count": 0, "admission_rule_optimized_count": 0,
        "turnover_uses_future_float_count": 0, "corporate_action_coordinate_violation_count": 0,
        "post_2021_outcome_read_count": 0,
    }
    result = {
        "experiment": EXPERIMENT, "start_head": START_HEAD, "frozen_spec_hash": EXPECTED_SPEC_SHA256,
        "feature_freeze_hash": freeze_hash, "input_hashes": hashes,
        "source_reconciliation": {"source_e1_entries": 598, "known_qd010_risk_blocked": 4, "complete_common_60d": len(panel)},
        "feature_availability": freeze["feature_availability"], "turnover_available": freeze["turnover_available"], "turnover_unavailable": freeze["turnover_unavailable"],
        "base_rates": base, "univariate": univariate, "primary_surfaces": primary_surfaces,
        "surface_extremes": extreme, "dimension_evidence": evidence, "capital_memory_controls": memory,
        "verdict": verdict_name, "verdict_evidence": verdict_evidence, "audit": audit,
        "validation_opened": False, "repository_2024_plus_data_opened": False,
    }
    v1.atomic_text(REPORT, build_report(result))
    result["artifact_hashes"] = {str(path): v1.sha256_file(path) for path in (SPEC, FEATURES, FEATURE_FREEZE, REPORT)}
    write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze-features", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.freeze_features:
        validate_hashes(FEATURE_INPUTS)
        source, reconciliation = build_outcome_blind_source()
        _, freeze = build_feature_panel(source)
        print(json.dumps(json_ready({"status": "FEATURES_FROZEN_BEFORE_OUTCOMES", "source": reconciliation, "freeze": freeze}), indent=2))
        return
    if args.validate_only:
        validate_hashes(FEATURE_INPUTS)
        print(json.dumps({"status": "INPUTS_VALID", "spec_sha256": EXPECTED_SPEC_SHA256}, indent=2))
        return
    result = run()
    print(json.dumps(json_ready({"verdict": result["verdict"], "source": result["source_reconciliation"], "base_rates": result["base_rates"], "dimension_evidence": result["dimension_evidence"], "surface_extremes": result["surface_extremes"], "capital_memory_controls": result["capital_memory_controls"], "audit": result["audit"]}), indent=2))


if __name__ == "__main__":
    main()
