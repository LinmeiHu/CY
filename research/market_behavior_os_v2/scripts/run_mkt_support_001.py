#!/usr/bin/env python3
"""Construct frozen objective-support session and five-day representations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-001_spec.json"
SESSION_PATH = PROGRAM / "artifacts/MKT-SUPPORT-001_session_panel.csv"
TRAJECTORY_PATH = PROGRAM / "artifacts/MKT-SUPPORT-001_trajectory_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-001_representation.md"
EXPECTED_SPEC_SHA256 = "4c58431daa1a21268eedcb8d6ebc306aadfb4aac89f8c9218e956fc91e36bef4"

DATA_RUNNER_PATH = PROGRAM / "scripts/run_mkt_support_data_003.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_support_data_003_parent", DATA_RUNNER_PATH
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-SUPPORT-DATA-003 parent")
data003 = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(data003)

adapter = data003.adapter
sha256_file = data003.sha256_file

HORIZONS = (10, 20, 40)
PATHS = ("cont", "auction")
UNCONDITIONAL_ROLES = (
    "signed_test_geometry",
    "time_beyond_level",
    "test_recurrence",
    "closing_level_state",
)
CONDITIONAL_ROLES = (
    "recovery_speed",
    "recovery_amplitude",
    "recovery_volume_intensity",
)
PRIORITY = (
    "signed_test_geometry",
    "time_beyond_level",
    "test_recurrence",
    "closing_level_state",
    "recovery_speed",
    "recovery_amplitude",
    "recovery_volume_intensity",
)


class SupportRepresentationError(RuntimeError):
    """Fail-closed MKT-SUPPORT-001 error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportRepresentationError("MKT-SUPPORT-001 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_REPRESENTATION_CONSTRUCTION":
        raise SupportRepresentationError("representation spec is not frozen")
    if spec["outcome_access"] is not False:
        raise SupportRepresentationError("outcome boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportRepresentationError(f"input identity mismatch: {name}")
    data_result = json.loads(
        _resolve(spec["inputs"]["data_result"]["path"]).read_text(encoding="utf-8")
    )
    if (
        data_result["status"] != "COMPLETE_DATA_CONTRACT_PASS"
        or data_result["representation_claim"] != "NONE"
        or data_result["cy011_read"] is not False
    ):
        raise SupportRepresentationError("data-contract activation boundary changed")
    if spec["level_definitions"] != {
        "primary": 20,
        "fixed_neighbors": [10, 40],
        "source": "minimum causal action-coordinate daily low through t-1",
        "near_touch_threshold": None,
    }:
        raise SupportRepresentationError("level definitions changed")
    return spec


def _qd004_paths(spec: dict[str, Any], verify_content: bool) -> dict[int, Path]:
    inventory = _resolve(spec["inputs"]["qd004_inventory"]["path"])
    required = [f"bars/{year}_day_parquet_none.parquet" for year in spec["sample_contract"]["years"]]
    try:
        bound = adapter.inventory_files(inventory, required)
        if verify_content:
            adapter.verify_inventory_hashes(inventory, required)
    except adapter.VectorMinuteAdapterError as exc:
        raise SupportRepresentationError(str(exc)) from exc
    return {year: bound[f"bars/{year}_day_parquet_none.parquet"] for year in spec["sample_contract"]["years"]}


def _session_descriptor(rows: pd.DataFrame, level: float, include_auction: bool) -> dict[str, Any]:
    selected = rows if include_auction else rows.iloc[1:]
    if len(selected) != (241 if include_auction else 240):
        raise SupportRepresentationError("session path length changed")
    lows = selected["mapped_low"].to_numpy(dtype=float)
    closes = selected["mapped_close"].to_numpy(dtype=float)
    volumes = selected["volume"].to_numpy(dtype=float)
    if (
        not np.isfinite(level)
        or level <= 0
        or not np.isfinite(lows).all()
        or not np.isfinite(closes).all()
        or not np.isfinite(volumes).all()
        or not (lows > 0).all()
        or not (closes > 0).all()
        or (volumes < 0).any()
        or float(volumes.sum()) <= 0
    ):
        raise SupportRepresentationError("invalid descriptor input")
    minimum = float(lows.min())
    signed = minimum / level - 1.0
    tested_mask = lows <= level
    tested = bool(tested_mask.any())
    starts = tested_mask & ~np.r_[False, tested_mask[:-1]]
    output: dict[str, Any] = {
        "signed_test_geometry": signed,
        "tested": tested,
        "penetration_depth": max(0.0, -signed),
        "time_beyond_level": float(np.mean(closes < level)),
        "test_recurrence": int(starts.sum()),
        "closing_level_state": float(closes[-1] / level - 1.0),
        "recovery_completion": np.nan,
        "recovery_speed": np.nan,
        "recovery_amplitude": np.nan,
        "recovery_volume_intensity": np.nan,
    }
    if not tested:
        return output
    first_test = int(np.flatnonzero(tested_mask)[0])
    recovery_offsets = np.flatnonzero(closes[first_test:] >= level)
    recovered = len(recovery_offsets) > 0
    output["recovery_completion"] = bool(recovered)
    output["recovery_amplitude"] = float((closes[-1] - minimum) / level)
    if recovered:
        recovery_index = first_test + int(recovery_offsets[0])
        span = volumes[first_test : recovery_index + 1]
        bar_share = len(span) / len(volumes)
        volume_share = float(span.sum() / volumes.sum())
        output["recovery_speed"] = int(recovery_index - first_test)
        output["recovery_volume_intensity"] = volume_share / bar_share
    return output


def _rank_pct(series: pd.Series) -> pd.Series:
    valid = series.notna()
    output = pd.Series(np.nan, index=series.index, dtype=float)
    n = int(valid.sum())
    if n:
        output.loc[valid] = (series.loc[valid].rank(method="average") - 0.5) / n
    return output


def _spearman(left: Iterable[float], right: Iterable[float]) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    return float(frame["left"].rank(method="average").corr(frame["right"].rank(method="average")))


def _qualitative_sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _trajectory_values(values: np.ndarray) -> tuple[float, float, float]:
    if len(values) != 5 or not np.isfinite(values).all():
        return np.nan, np.nan, np.nan
    x = np.array([-2.0, -1.0, 0.0, 1.0, 2.0])
    slope = float(np.dot(x, values) / np.dot(x, x))
    endpoint = float(values[-1] - values[0])
    ordinal = _spearman(x, values)
    return slope, endpoint, ordinal


def _load_governed_frames(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    sample = pd.read_csv(
        _resolve(spec["inputs"]["sample"]["path"]),
        dtype={"source_symbol": str},
    )
    audit = pd.read_csv(_resolve(spec["inputs"]["coordinate_audit"]["path"]))
    for frame in (sample, audit):
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    contract = spec["sample_contract"]
    if len(sample) != contract["market_rows"] + contract["action_rows"]:
        raise SupportRepresentationError("sample row count mismatch")
    if len(audit) != len(sample) or not sample["audit_id"].is_unique or not audit["audit_id"].is_unique:
        raise SupportRepresentationError("governed cohort identity mismatch")
    identity = sample[["audit_id", "symbol", "trade_date"]].merge(
        audit[["audit_id", "symbol", "trade_date"]],
        on=["audit_id", "symbol", "trade_date"],
        validate="one_to_one",
    )
    if len(identity) != len(sample):
        raise SupportRepresentationError("sample/audit key mismatch")
    return sample, audit


def construct_session_panel(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    audit: pd.DataFrame,
    qd_paths: dict[int, Path],
) -> tuple[pd.DataFrame, dict[tuple[str, pd.Timestamp], pd.DataFrame]]:
    session_base = audit.copy()
    unique_targets = sample[
        ["symbol", "source_symbol", "trade_date", "target_year"]
    ].drop_duplicates()
    raw_sessions: dict[tuple[str, pd.Timestamp], pd.DataFrame] = {}
    for raw_year, targets in unique_targets.groupby("target_year", sort=True):
        year = int(raw_year)
        try:
            table = adapter.read_raw_table(
                qd_paths[year],
                pd.to_datetime(targets["trade_date"]).dt.date,
                targets["source_symbol"].astype(str),
            )
            adapter.vectorized_session_descriptors(table)
        except adapter.VectorMinuteAdapterError as exc:
            raise SupportRepresentationError(str(exc)) from exc
        raw = table.to_pandas()
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            key = (str(symbol), pd.Timestamp(trade_date))
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise SupportRepresentationError(f"raw session coverage mismatch: {key}")
            coordinate_rows = session_base.loc[
                session_base["symbol"].eq(symbol) & session_base["trade_date"].eq(trade_date)
            ]
            if coordinate_rows.empty:
                raise SupportRepresentationError(f"coordinate target missing: {key}")
            scale_values = coordinate_rows["coordinate_scale"].unique()
            if len(scale_values) != 1 or not np.isfinite(scale_values[0]) or scale_values[0] <= 0:
                raise SupportRepresentationError(f"coordinate scale disagreement: {key}")
            scale = float(scale_values[0])
            rows = rows.copy()
            rows["mapped_low"] = rows["low"].astype(float) * scale
            rows["mapped_close"] = rows["close"].astype(float) * scale
            raw_sessions[key] = rows
    if len(raw_sessions) != spec["sample_contract"]["unique_sessions"]:
        raise SupportRepresentationError("unique raw session count mismatch")

    records: list[dict[str, Any]] = []
    for row in session_base.itertuples(index=False):
        key = (str(row.symbol), pd.Timestamp(row.trade_date))
        raw = raw_sessions[key]
        record = row._asdict()
        for horizon in HORIZONS:
            level = float(getattr(row, f"support_low{horizon}"))
            for path_name, include_auction in (("cont", False), ("auction", True)):
                values = _session_descriptor(raw, level, include_auction)
                for role, value in values.items():
                    record[f"h{horizon}_{path_name}_{role}"] = value
        records.append(record)
    panel = pd.DataFrame(records)
    market = panel["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")
    primary_roles = [f"h20_cont_{role}" for role in PRIORITY]
    for column in primary_roles:
        panel[f"relative_rank__{column}"] = np.nan
        ranked = panel.loc[market].groupby(
            ["target_year", "market_view", "trade_date"], sort=False
        )[column].transform(_rank_pct)
        panel.loc[market, f"relative_rank__{column}"] = ranked
    return panel.sort_values("audit_id").reset_index(drop=True), raw_sessions


def construct_trajectory_panel(session: pd.DataFrame) -> pd.DataFrame:
    market = session.loc[
        session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")
    ].copy()
    group_fields = ["target_year", "market_view", "market_sequence_rank", "symbol"]
    records: list[dict[str, Any]] = []
    for key, rows in market.groupby(group_fields, sort=True):
        rows = rows.sort_values("relative_day")
        if len(rows) != 5 or rows["relative_day"].tolist() != [-5, -4, -3, -2, -1]:
            raise SupportRepresentationError(f"five-session sequence changed: {key}")
        record: dict[str, Any] = dict(zip(group_fields, key, strict=True))
        record["sequence_id"] = "|".join(str(value) for value in key)
        for horizon in HORIZONS:
            for role in UNCONDITIONAL_ROLES:
                column = f"h{horizon}_cont_{role}"
                slope, endpoint, ordinal = _trajectory_values(rows[column].to_numpy(dtype=float))
                prefix = f"h{horizon}_{role}"
                record[f"{prefix}__slope5"] = slope
                record[f"{prefix}__endpoint5"] = endpoint
                record[f"{prefix}__ordinal5"] = ordinal
            record[f"h{horizon}_tested_day_count"] = int(
                rows[f"h{horizon}_cont_tested"].sum()
            )
            record[f"h{horizon}_total_test_episode_count"] = int(
                rows[f"h{horizon}_cont_test_recurrence"].sum()
            )
        primary_tested = rows["h20_cont_tested"].astype(bool)
        record["h20_tested_days_for_conditional_recovery"] = int(primary_tested.sum())
        records.append(record)
    panel = pd.DataFrame(records)
    if len(panel) != 240 or not panel["sequence_id"].is_unique:
        raise SupportRepresentationError("trajectory population mismatch")
    return panel.sort_values("sequence_id").reset_index(drop=True)


def _cell_correlations(
    frame: pd.DataFrame, left: str, right: str
) -> list[float]:
    values: list[float] = []
    for _, cell in frame.groupby(["target_year", "market_view"], sort=True):
        rho = _spearman(cell[left], cell[right])
        if np.isfinite(rho):
            values.append(rho)
    return values


def evaluate_session_roles(spec: dict[str, Any], session: pd.DataFrame) -> dict[str, Any]:
    market = session.loc[
        session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")
    ].copy()
    gates = spec["stability_gates"]
    support = spec["support_gates"]
    test_count = int(market["h20_cont_tested"].sum())
    tests_by_year = market.groupby("target_year")["h20_cont_tested"].sum().astype(int)
    years_with_ten = int((tests_by_year >= 10).sum())
    recovery_volume_count = int(market["h20_cont_recovery_volume_intensity"].notna().sum())
    base_support_pass = (
        test_count >= support["primary_tested_market_rows_minimum"]
        and years_with_ten >= support["years_with_at_least_ten_primary_tests_minimum"]
    )
    output: dict[str, Any] = {
        "primary_tested_market_rows": test_count,
        "primary_tests_by_year": {str(year): int(value) for year, value in tests_by_year.items()},
        "years_with_at_least_ten_primary_tests": years_with_ten,
        "recovery_volume_rows": recovery_volume_count,
        "base_conditional_support_pass": base_support_pass,
        "recovery_volume_support_pass": recovery_volume_count
        >= support["primary_recovery_volume_rows_minimum"],
        "roles": {},
    }
    for role in PRIORITY:
        primary = f"h20_cont_{role}"
        role_result: dict[str, Any] = {
            "coverage": float(market[primary].notna().mean()),
            "level_neighbors": {},
            "auction_neighbor": {},
        }
        level_passes = []
        for neighbor in (10, 40):
            other = f"h{neighbor}_cont_{role}"
            if role in CONDITIONAL_ROLES:
                joint = market[[primary, other]].dropna()
                rho = _spearman(joint[primary], joint[other])
                passed = (
                    len(joint) >= support["conditional_neighbor_intersection_minimum"]
                    and np.isfinite(rho)
                    and rho >= gates["conditional_neighbor_global_spearman_minimum"]
                )
                detail = {"intersection": len(joint), "global_spearman": rho, "pass": passed}
            else:
                cell_rhos = _cell_correlations(market, primary, other)
                median = float(np.median(cell_rhos)) if cell_rhos else np.nan
                passing_cells = int(sum(value >= 0.50 for value in cell_rhos))
                passed = (
                    median >= gates["level_neighbor_median_within_year_view_spearman_minimum"]
                    and passing_cells >= gates["level_neighbor_cells_at_or_above_0_50_minimum"]
                )
                detail = {
                    "valid_cells": len(cell_rhos),
                    "median_spearman": median,
                    "cells_at_or_above_0_50": passing_cells,
                    "pass": passed,
                }
            role_result["level_neighbors"][str(neighbor)] = detail
            level_passes.append(bool(passed))
        auction = f"h20_auction_{role}"
        if role in CONDITIONAL_ROLES:
            joint = market[[primary, auction]].dropna()
            auction_rho = _spearman(joint[primary], joint[auction])
            auction_pass = (
                len(joint) >= support["conditional_neighbor_intersection_minimum"]
                and np.isfinite(auction_rho)
                and auction_rho >= gates["auction_neighbor_median_within_cell_spearman_minimum"]
            )
            auction_detail = {
                "intersection": len(joint),
                "global_spearman": auction_rho,
                "pass": auction_pass,
            }
        else:
            cell_rhos = _cell_correlations(market, primary, auction)
            auction_rho = float(np.median(cell_rhos)) if cell_rhos else np.nan
            auction_pass = (
                len(cell_rhos) == 24
                and auction_rho >= gates["auction_neighbor_median_within_cell_spearman_minimum"]
            )
            auction_detail = {
                "valid_cells": len(cell_rhos),
                "median_spearman": auction_rho,
                "pass": auction_pass,
            }
        role_result["auction_neighbor"] = auction_detail
        conditional_support = base_support_pass
        if role == "recovery_volume_intensity":
            conditional_support = conditional_support and output["recovery_volume_support_pass"]
        coverage_pass = (
            role_result["coverage"] >= spec["support_gates"]["all_session_role_coverage"]
            if role not in CONDITIONAL_ROLES
            else conditional_support
        )
        role_result["support_pass"] = bool(coverage_pass)
        role_result["pre_redundancy_pass"] = bool(
            coverage_pass and all(level_passes) and auction_pass
        )
        output["roles"][role] = role_result
    return output


def evaluate_trajectories(spec: dict[str, Any], trajectory: pd.DataFrame) -> dict[str, Any]:
    gates = spec["stability_gates"]
    output: dict[str, Any] = {"roles": {}}
    for role in UNCONDITIONAL_ROLES:
        prefix = f"h20_{role}"
        slope = f"{prefix}__slope5"
        endpoint = f"{prefix}__endpoint5"
        ordinal = f"{prefix}__ordinal5"
        coverage = {
            "slope": int(trajectory[slope].notna().sum()),
            "endpoint": int(trajectory[endpoint].notna().sum()),
            "ordinal": int(trajectory[ordinal].notna().sum()),
        }
        rho_endpoint = _spearman(trajectory[slope], trajectory[endpoint])
        rho_ordinal = _spearman(trajectory[slope], trajectory[ordinal])
        sign_years = 0
        year_details: dict[str, Any] = {}
        for year, cell in trajectory.groupby("target_year", sort=True):
            a = _spearman(cell[slope], cell[endpoint])
            b = _spearman(cell[slope], cell[ordinal])
            same_positive = _qualitative_sign(a) == 1 and _qualitative_sign(b) == 1
            sign_years += int(same_positive)
            year_details[str(year)] = {"slope_endpoint": a, "slope_ordinal": b}
        passed = (
            all(value == 240 for value in coverage.values())
            and np.isfinite(rho_endpoint)
            and rho_endpoint >= gates["trajectory_slope_endpoint_global_spearman_minimum"]
            and np.isfinite(rho_ordinal)
            and rho_ordinal >= gates["trajectory_slope_ordinal_global_spearman_minimum"]
            and sign_years >= gates["trajectory_same_qualitative_sign_years_minimum"]
        )
        output["roles"][role] = {
            "coverage": coverage,
            "slope_endpoint_spearman": rho_endpoint,
            "slope_ordinal_spearman": rho_ordinal,
            "positive_shape_years": sign_years,
            "year_details": year_details,
            "pass": bool(passed),
        }
    eligible = int(
        (
            trajectory["h20_tested_days_for_conditional_recovery"]
            >= spec["trajectory"]["conditional_recovery_minimum_tested_days"]
        ).sum()
    )
    output["conditional_recovery"] = {
        "eligible_sequences": eligible,
        "minimum_required": spec["support_gates"]["conditional_trajectory_sequences_minimum"],
        "status": (
            "NOT_ESTIMABLE_SUPPORT"
            if eligible < spec["support_gates"]["conditional_trajectory_sequences_minimum"]
            else "ESTIMABLE"
        ),
        "estimates_constructed": False,
    }
    output["tested_day_count_distribution"] = {
        str(key): int(value)
        for key, value in trajectory["h20_tested_day_count"].value_counts().sort_index().items()
    }
    return output


def evaluate_redundancy(
    spec: dict[str, Any], session: pd.DataFrame, session_evaluation: dict[str, Any]
) -> dict[str, Any]:
    market = session.loc[
        session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")
    ]
    boundary = spec["stability_gates"]["internal_redundancy_absolute_spearman_boundary"]
    decisions: dict[str, Any] = {}
    retained: list[str] = []
    for index, role in enumerate(PRIORITY):
        if not session_evaluation["roles"][role]["pre_redundancy_pass"]:
            decisions[role] = {
                "status": "FAILED_PRE_REDUNDANCY_GATES",
                "redundant_with": None,
            }
            continue
        redundant_with = None
        evidence = None
        for earlier in retained:
            left = f"h20_cont_{role}"
            right = f"h20_cont_{earlier}"
            joint = market[["target_year", "market_view", left, right]].dropna()
            global_rho = _spearman(joint[left], joint[right])
            cell_rhos = _cell_correlations(joint, left, right)
            median_abs = float(np.median(np.abs(cell_rhos))) if cell_rhos else np.nan
            if (
                len(joint) >= spec["support_gates"]["conditional_neighbor_intersection_minimum"]
                and np.isfinite(global_rho)
                and abs(global_rho) >= boundary
                and np.isfinite(median_abs)
                and median_abs >= boundary
            ):
                redundant_with = earlier
                evidence = {
                    "joint_rows": len(joint),
                    "global_spearman": global_rho,
                    "median_absolute_cell_spearman": median_abs,
                }
                break
        if redundant_with is None:
            retained.append(role)
            decisions[role] = {"status": "RETAINED", "redundant_with": None}
        else:
            decisions[role] = {
                "status": "REDUNDANT",
                "redundant_with": redundant_with,
                "evidence": evidence,
            }
    return {"boundary": boundary, "decisions": decisions, "retained_roles": retained}


def _manual_descriptor(rows: pd.DataFrame, level: float) -> dict[str, Any]:
    # Deliberately separate scalar reconstruction for audit cases.
    bars = rows.iloc[1:].reset_index(drop=True)
    minimum = min(float(value) for value in bars["mapped_low"])
    tested_indices = [
        index for index, value in enumerate(bars["mapped_low"]) if float(value) <= level
    ]
    episodes = 0
    previous_tested = False
    for value in bars["mapped_low"]:
        current = float(value) <= level
        if current and not previous_tested:
            episodes += 1
        previous_tested = current
    result: dict[str, Any] = {
        "signed_test_geometry": minimum / level - 1.0,
        "time_beyond_level": sum(float(value) < level for value in bars["mapped_close"]) / 240.0,
        "test_recurrence": episodes,
        "closing_level_state": float(bars["mapped_close"].iloc[-1]) / level - 1.0,
        "recovery_speed": np.nan,
        "recovery_amplitude": np.nan,
        "recovery_volume_intensity": np.nan,
    }
    if not tested_indices:
        return result
    first = tested_indices[0]
    result["recovery_amplitude"] = (
        float(bars["mapped_close"].iloc[-1]) - minimum
    ) / level
    recovery = next(
        (
            index
            for index in range(first, 240)
            if float(bars["mapped_close"].iloc[index]) >= level
        ),
        None,
    )
    if recovery is not None:
        result["recovery_speed"] = recovery - first
        total_volume = sum(float(value) for value in bars["volume"])
        span_volume = sum(float(value) for value in bars["volume"].iloc[first : recovery + 1])
        result["recovery_volume_intensity"] = (
            span_volume / total_volume
        ) / ((recovery - first + 1) / 240.0)
    return result


def manual_case_audit(
    session: pd.DataFrame, raw_sessions: dict[tuple[str, pd.Timestamp], pd.DataFrame]
) -> dict[str, Any]:
    tested = session["h20_cont_tested"].astype(bool)
    categories = {
        "no_test": ~tested,
        "penetration_recovery": tested & session["h20_cont_recovery_completion"].eq(True),
        "penetration_nonrecovery": tested & session["h20_cont_recovery_completion"].eq(False),
        "repeated_test": tested & session["h20_cont_test_recurrence"].ge(2),
        "supported_action": session["cohort"].eq("SUPPORTED_ACTION_AUDIT"),
    }
    cases: dict[str, Any] = {}
    used_audit_ids: set[str] = set()
    fields = [
        "signed_test_geometry",
        "time_beyond_level",
        "test_recurrence",
        "closing_level_state",
        "recovery_speed",
        "recovery_amplitude",
        "recovery_volume_intensity",
    ]
    for category, mask in categories.items():
        eligible = session.loc[mask & ~session["audit_id"].isin(used_audit_ids)].sort_values(
            "audit_id"
        )
        if eligible.empty:
            raise SupportRepresentationError(f"manual case category absent: {category}")
        row = eligible.iloc[0]
        raw = raw_sessions[(str(row.symbol), pd.Timestamp(row.trade_date))]
        manual = _manual_descriptor(raw, float(row.support_low20))
        exact = True
        comparisons: dict[str, bool] = {}
        for field in fields:
            expected = row[f"h20_cont_{field}"]
            observed = manual[field]
            if pd.isna(expected) and pd.isna(observed):
                matched = True
            else:
                matched = bool(expected == observed)
            comparisons[field] = matched
            exact = exact and matched
        if not exact:
            raise SupportRepresentationError(f"manual case disagreement: {category}")
        used_audit_ids.add(str(row.audit_id))
        cases[category] = {"audit_id": row.audit_id, "exact_fields": comparisons}
    if len(used_audit_ids) != len(categories):
        raise SupportRepresentationError("manual case identities are not distinct")
    return {
        "selection": "lexicographically first unused audit_id in frozen category order",
        "cases": cases,
    }


def mismatch_sensitivity(session: pd.DataFrame) -> dict[str, Any]:
    market = session.loc[
        session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")
    ].copy()
    mismatch = market["integer_cent_difference"].ne(0)
    roles = [f"h20_cont_{role}" for role in PRIORITY]
    return {
        "mismatch_rows": int(mismatch.sum()),
        "other_rows": int((~mismatch).sum()),
        "median_by_group": {
            role: {
                "mismatch": float(market.loc[mismatch, role].median())
                if market.loc[mismatch, role].notna().any()
                else np.nan,
                "other": float(market.loc[~mismatch, role].median())
                if market.loc[~mismatch, role].notna().any()
                else np.nan,
            }
            for role in roles
        },
        "promotional_gate": False,
    }


def _render_report(result: dict[str, Any]) -> str:
    session = result["session_evaluation"]
    trajectory = result["trajectory_evaluation"]
    lines = [
        "# MKT-SUPPORT-001 objective support representation",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Primary continuous 20-session tests: {session['primary_tested_market_rows']} market rows.",
        f"- Conditional recovery trajectories: `{trajectory['conditional_recovery']['status']}` on {trajectory['conditional_recovery']['eligible_sequences']} sequences versus {trajectory['conditional_recovery']['minimum_required']} required.",
        f"- Retained direct session roles: {', '.join(result['redundancy']['retained_roles']) or 'none'}.",
        "- PIT historical normalization is unavailable from isolated blocks and was not fabricated.",
        "- This is representation quality only; no touch is called defense and no payoff, habitat, timing, or strategy field was read.",
        "",
        "## Session roles",
        "",
        "| Role | Pre-redundancy | Final status |",
        "|---|---:|---|",
    ]
    for role in PRIORITY:
        lines.append(
            f"| `{role}` | {'PASS' if session['roles'][role]['pre_redundancy_pass'] else 'FAIL'} | `{result['redundancy']['decisions'][role]['status']}` |"
        )
    lines.extend(
        [
            "",
            "## Five-day trajectory roles",
            "",
            "| Role | Ordinal coverage | Slope/endpoint rho | Slope/ordinal rho | Result |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for role, detail in trajectory["roles"].items():
        lines.append(
            f"| `{role}` | {detail['coverage']['ordinal']} | {detail['slope_endpoint_spearman'] if detail['slope_endpoint_spearman'] is not None else 'NA'} | {detail['slope_ordinal_spearman'] if detail['slope_ordinal_spearman'] is not None else 'NA'} | {'PASS' if detail['pass'] else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Session panel SHA-256: `{result['hashes']['session_panel_sha256']}`",
            f"- Trajectory panel SHA-256: `{result['hashes']['trajectory_panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    qd_paths = _qd004_paths(spec, verify_partition_content)
    sample, audit = _load_governed_frames(spec)
    session, raw_sessions = construct_session_panel(spec, sample, audit, qd_paths)
    trajectory = construct_trajectory_panel(session)
    session_evaluation = evaluate_session_roles(spec, session)
    trajectory_evaluation = evaluate_trajectories(spec, trajectory)
    redundancy = evaluate_redundancy(spec, session, session_evaluation)
    manual = manual_case_audit(session, raw_sessions)
    mismatch = mismatch_sensitivity(session)

    session_out = session.copy()
    session_out["trade_date"] = pd.to_datetime(session_out["trade_date"]).dt.strftime("%Y-%m-%d")
    session_out.to_csv(SESSION_PATH, index=False, float_format="%.17g", lineterminator="\n")
    trajectory.to_csv(TRAJECTORY_PATH, index=False, float_format="%.17g", lineterminator="\n")

    retained = redundancy["retained_roles"]
    trajectory_roles = [
        role for role, detail in trajectory_evaluation["roles"].items() if detail["pass"]
    ]
    status = (
        "COMPLETE_REPRESENTATIONS_FROZEN"
        if retained or trajectory_roles
        else "COMPLETE_ZERO_REPRESENTATIONS_FROZEN"
    )
    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-001",
        "status": status,
        "representation_claim": "SESSION_AND_TRAJECTORY_ROLES_ONLY",
        "support_defense_claim": "NONE",
        "accumulation_or_distribution_claim": "NONE",
        "usefulness_claim": "NONE",
        "pit_historical_coordinate": "UNAVAILABLE_NOT_FABRICATED",
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "sample_counts": {
            "session_rows": int(len(session)),
            "market_rows": int(session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE").sum()),
            "action_rows": int(session["cohort"].eq("SUPPORTED_ACTION_AUDIT").sum()),
            "unique_sessions": int(session[["symbol", "trade_date"]].drop_duplicates().shape[0]),
            "trajectory_rows": int(len(trajectory)),
        },
        "session_evaluation": session_evaluation,
        "trajectory_evaluation": trajectory_evaluation,
        "redundancy": redundancy,
        "manual_case_audit": manual,
        "source_close_mismatch_sensitivity": mismatch,
        "accepted_session_roles": retained,
        "accepted_trajectory_roles": trajectory_roles,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "session_panel_sha256": sha256_file(SESSION_PATH),
            "trajectory_panel_sha256": sha256_file(TRAJECTORY_PATH),
            "bound_inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "accepted_session_roles": completed["accepted_session_roles"],
                "accepted_trajectory_roles": completed["accepted_trajectory_roles"],
                "conditional_recovery": completed["trajectory_evaluation"]["conditional_recovery"],
            },
            indent=2,
            sort_keys=True,
        )
    )
