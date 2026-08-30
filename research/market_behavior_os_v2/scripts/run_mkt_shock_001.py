#!/usr/bin/env python3
"""Construct frozen MKT-SHOCK-001 direction-neutral stress episodes."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPTS = PROGRAM / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-SHOCK-001_spec.json"
CLQ_PATH = PROGRAM / "artifacts/MKT-CLQ-001_correlation_liquidity_panel.csv"
VOL_PATH = PROGRAM / "artifacts/MKT-VOL-001_volatility_panel.csv"
PANEL_PATH = PROGRAM / "artifacts/MKT-SHOCK-001_shock_recovery_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SHOCK-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SHOCK-001_shock_recovery_representation.md"
EXPECTED_SPEC_SHA256 = "9fb559c5d4a59f8fc83b6b7408edfc6534125edb9e4badfd6f8c3e3dccfe5fe3"
KEYS = ["trade_date", "market_view", "denominator"]
CONFIGS = {
    "primary": {"stress": 0.90, "reset": 0.50, "impairment": 0.10},
    "permissive": {"stress": 0.85, "reset": 0.45, "impairment": 0.15},
    "strict": {"stress": 0.95, "reset": 0.55, "impairment": 0.05},
}
ROLE_PRIORITY = (
    "synchronization_pressure",
    "joint_stress_score",
    "shock_onset",
    "stress_dwell",
    "stress_relief",
    "activity_impairment",
)
ROLE_COLUMNS = {
    "synchronization_pressure": "synchronization_pressure",
    "joint_stress_score": "joint_stress_score",
    "shock_onset": "shock_onset_primary",
    "stress_dwell": "episode_age_primary",
    "stress_relief": "stress_relief_primary",
    "activity_impairment": "activity_impairment_primary",
}
VOLATILITY_CONTROLS = {
    "volatility_level": "realized_volatility_median20_pit_3y_pct",
    "intraday_range": "intraday_range_median_smooth5_pit_3y_pct",
    "volatility_concentration": "volatility_mass_share_top10_pit_3y_pct",
    "volatility_change": "realized_volatility_change5_pit_3y_pct",
}


class ShockRepresentationError(RuntimeError):
    """Raised when a frozen input or representation gate fails closed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def _spearman(left: pd.Series, right: pd.Series, minimum: int = 20) -> float:
    data = pd.DataFrame({"left": left, "right": right}).replace(
        [np.inf, -np.inf], np.nan
    ).dropna()
    if len(data) < minimum or data.left.nunique() < 2 or data.right.nunique() < 2:
        return float("nan")
    return float(data.left.corr(data.right, method="spearman"))


def _jaccard(left: set[int], right: set[int]) -> float:
    union = left | right
    return float(len(left & right) / len(union)) if union else float("nan")


def _finite_summary(values: list[float]) -> dict[str, float]:
    finite = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    if len(finite) == 0:
        return {"minimum": float("nan"), "median": float("nan")}
    return {"minimum": float(finite.min()), "median": float(np.median(finite))}


def _validate_input(path: Path, expected: str) -> None:
    if not path.is_file():
        raise ShockRepresentationError(f"bound input missing: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise ShockRepresentationError(f"bound input hash mismatch: {path}: {actual}")


def _validate_completed_close(frame: pd.DataFrame) -> None:
    decision = pd.to_datetime(frame.decision_at_clq, utc=True)
    available = pd.to_datetime(frame.available_at_clq, utc=True)
    vol_decision = pd.to_datetime(frame.decision_at_vol, utc=True)
    vol_available = pd.to_datetime(frame.available_at_vol, utc=True)
    if not (decision.eq(available) & decision.eq(vol_decision) & decision.eq(vol_available)).all():
        raise ShockRepresentationError("completed-close availability mismatch")
    local = decision.dt.tz_convert("Asia/Shanghai")
    if not (local.dt.hour.eq(15) & local.dt.minute.eq(0)).all():
        raise ShockRepresentationError("decision timestamp is not 15:00 Asia/Shanghai")


def load_bound_panels(spec: dict[str, Any]) -> pd.DataFrame:
    clq_item = spec["inputs"]["correlation_liquidity_panel"]
    vol_item = spec["inputs"]["volatility_panel"]
    _validate_input(CLQ_PATH, clq_item["sha256"])
    _validate_input(VOL_PATH, vol_item["sha256"])
    clq_columns = [
        *KEYS,
        "view_valid",
        "within_view_observation",
        "decision_at",
        "available_at",
        "snapshot_id",
        "correlation_median20",
        "correlation_median20_pit_expanding_pct",
        "correlation_median20_pit_3y_pct",
        "correlation_median20_pit_3y_robust_z",
        "correlation_median20_relative_to_all",
        "correlation_median20_relative_view_rank_pct",
        "directional_sync_balance5",
        "directional_sync_balance5_pit_expanding_pct",
        "directional_sync_balance5_pit_3y_pct",
        "directional_sync_balance5_pit_3y_robust_z",
        "directional_sync_balance5_relative_to_all",
        "directional_sync_balance5_relative_view_rank_pct",
        "liquidity_median_amount_ratio10",
        "liquidity_median_amount_ratio20",
        "liquidity_median_amount_ratio60",
        "liquidity_median_amount_ratio20_pit_expanding_pct",
        "liquidity_median_amount_ratio20_pit_3y_pct",
        "liquidity_median_amount_ratio20_pit_3y_robust_z",
        "liquidity_median_amount_ratio20_relative_to_all",
        "liquidity_median_amount_ratio20_relative_view_rank_pct",
        "liquidity_turnover_median",
        "liquidity_turnover_median_pit_3y_pct",
        "liquidity_turnover_median_relative_to_all",
        "liquidity_turnover_median_relative_view_rank_pct",
        "liquidity_amount_share_top10",
        "liquidity_amount_share_top10_pit_3y_pct",
        "liquidity_amount_share_top10_relative_to_all",
        "liquidity_amount_share_top10_relative_view_rank_pct",
    ]
    forbidden = {"liquidity_activity_change3", "liquidity_activity_change5", "liquidity_activity_change10"}
    if forbidden.intersection(clq_columns):
        raise ShockRepresentationError("rejected liquidity-change family reached the adapter")
    vol_columns = [
        *KEYS,
        "view_valid",
        "decision_at",
        "available_at",
        "snapshot_id",
        "realized_volatility_median20",
        "realized_volatility_median20_pit_3y_pct",
        "intraday_range_median_smooth5",
        "intraday_range_median_smooth5_pit_3y_pct",
        "volatility_mass_share_top10",
        "volatility_mass_share_top10_pit_3y_pct",
        "realized_volatility_change5",
        "realized_volatility_change5_pit_3y_pct",
    ]
    clq = pd.read_csv(CLQ_PATH, usecols=clq_columns).rename(
        columns={
            "view_valid": "view_valid_clq",
            "decision_at": "decision_at_clq",
            "available_at": "available_at_clq",
            "snapshot_id": "snapshot_id_clq",
        }
    )
    vol = pd.read_csv(VOL_PATH, usecols=vol_columns).rename(
        columns={
            "view_valid": "view_valid_vol",
            "decision_at": "decision_at_vol",
            "available_at": "available_at_vol",
            "snapshot_id": "snapshot_id_vol",
        }
    )
    for label, frame in (("clq", clq), ("vol", vol)):
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        if frame.duplicated(KEYS).any() or len(frame) != 10696:
            raise ShockRepresentationError(f"{label} key/population changed")
    panel = clq.merge(vol, on=KEYS, validate="one_to_one")
    if len(panel) != 10696:
        raise ShockRepresentationError("frozen panel intersection changed")
    if not (panel.view_valid_clq.astype(bool) & panel.view_valid_vol.astype(bool)).all():
        raise ShockRepresentationError("invalid frozen view row reached shock construction")
    if not panel.snapshot_id_clq.eq(spec["inputs"]["snapshot_id"]).all() or not panel.snapshot_id_vol.eq(
        spec["inputs"]["snapshot_id"]
    ).all():
        raise ShockRepresentationError("snapshot identity changed")
    _validate_completed_close(panel)
    expected_groups = {
        (view, denominator)
        for view in spec["population"]["views"]
        for denominator in spec["population"]["denominators"]
    }
    actual_groups = set(panel.groupby(["market_view", "denominator"]).groups)
    if actual_groups != expected_groups:
        raise ShockRepresentationError("view/denominator population changed")
    sizes = panel.groupby(["market_view", "denominator"]).size()
    if not sizes.eq(1337).all():
        raise ShockRepresentationError("source dates per group changed")
    return panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)


def build_episode(
    score: np.ndarray,
    activity: np.ndarray,
    stress: float,
    reset: float,
    impairment: float,
) -> pd.DataFrame:
    if not (0 <= impairment < reset < stress <= 1):
        raise ShockRepresentationError("invalid state-machine thresholds")
    size = len(score)
    states = np.full(size, "MISSING", dtype=object)
    onset = np.zeros(size, dtype=bool)
    episode_ids = np.full(size, np.nan)
    ages = np.full(size, np.nan)
    peaks = np.full(size, np.nan)
    relief = np.full(size, np.nan)
    impaired = np.zeros(size, dtype=bool)
    active = False
    episode_id = 0
    age = 0
    peak = float("nan")
    for index, (current, current_activity) in enumerate(zip(score, activity, strict=True)):
        if not np.isfinite(current) or not np.isfinite(current_activity):
            active = False
            age = 0
            peak = float("nan")
            continue
        if not active:
            if current >= stress:
                active = True
                episode_id += 1
                age = 1
                peak = float(current)
                states[index] = "ONSET"
                onset[index] = True
                episode_ids[index] = episode_id
                ages[index] = age
                peaks[index] = peak
                relief[index] = 0.0
            else:
                states[index] = "NORMAL"
            continue
        if current < reset:
            states[index] = "NORMAL"
            active = False
            age = 0
            peak = float("nan")
            continue
        age += 1
        peak = max(peak, float(current))
        states[index] = "STRESS" if current >= stress else "RELIEF"
        episode_ids[index] = episode_id
        ages[index] = age
        peaks[index] = peak
        relief[index] = peak - float(current)
        impaired[index] = states[index] == "RELIEF" and current_activity <= impairment
    return pd.DataFrame(
        {
            "state": states,
            "onset": onset,
            "episode_id": episode_ids,
            "episode_age": ages,
            "episode_peak": peaks,
            "stress_relief": relief,
            "activity_impairment": impaired,
        }
    )


def attach_representations(panel: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for _, group in panel.groupby(["market_view", "denominator"], sort=True):
        item = group.sort_values("trade_date").copy().reset_index(drop=True)
        for horizon in (10, 60):
            raw = item[f"liquidity_median_amount_ratio{horizon}"]
            item[f"activity{horizon}_pit_3y_pct"] = causal_rolling_percentile(raw).to_numpy()
        correlation = item.correlation_median20_pit_3y_pct.to_numpy(float)
        synchronization = item.directional_sync_balance5_pit_3y_pct.to_numpy(float)
        activity20 = item.liquidity_median_amount_ratio20_pit_3y_pct.to_numpy(float)
        activity10 = item.activity10_pit_3y_pct.to_numpy(float)
        activity60 = item.activity60_pit_3y_pct.to_numpy(float)
        inputs = np.column_stack([correlation, synchronization, activity20])
        valid = np.isfinite(inputs).all(axis=1)
        item["synchronization_pressure"] = np.where(
            np.isfinite(correlation) & np.isfinite(synchronization),
            np.minimum(correlation, synchronization),
            np.nan,
        )
        item["synchronization_pressure_geometric"] = np.where(
            np.isfinite(correlation) & np.isfinite(synchronization),
            np.sqrt(correlation * synchronization),
            np.nan,
        )
        item["synchronization_pressure_arithmetic"] = np.where(
            np.isfinite(correlation) & np.isfinite(synchronization),
            (correlation + synchronization) / 2.0,
            np.nan,
        )
        item["joint_stress_score"] = np.where(valid, np.min(inputs, axis=1), np.nan)
        item["joint_stress_score_geometric"] = np.where(
            valid, np.cbrt(np.prod(inputs, axis=1)), np.nan
        )
        item["joint_stress_score_arithmetic"] = np.where(
            valid, np.mean(inputs, axis=1), np.nan
        )
        item["joint_stress_score_activity10"] = np.where(
            np.isfinite(correlation) & np.isfinite(synchronization) & np.isfinite(activity10),
            np.minimum(np.minimum(correlation, synchronization), activity10),
            np.nan,
        )
        item["joint_stress_score_activity60"] = np.where(
            np.isfinite(correlation) & np.isfinite(synchronization) & np.isfinite(activity60),
            np.minimum(np.minimum(correlation, synchronization), activity60),
            np.nan,
        )
        score = item.joint_stress_score
        item["joint_stress_score_pit_expanding_pct"] = causal_expanding_percentile(score).to_numpy()
        item["joint_stress_score_pit_3y_pct"] = causal_rolling_percentile(score).to_numpy()
        item["joint_stress_score_pit_3y_robust_z"] = causal_rolling_robust_z(score).to_numpy()
        for name, config in CONFIGS.items():
            episode = build_episode(
                score.to_numpy(float),
                activity20,
                config["stress"],
                config["reset"],
                config["impairment"],
            )
            for column in episode:
                output_name = "shock_onset" if column == "onset" else column
                item[f"{output_name}_{name}"] = episode[column].to_numpy()
        pieces.append(item)
    output = pd.concat(pieces, ignore_index=True)
    output = output.sort_values(KEYS).reset_index(drop=True)
    output["joint_stress_score_relative_to_all"] = np.nan
    output["joint_stress_score_relative_view_rank_pct"] = np.nan
    for (_, _), index in output.groupby(["trade_date", "denominator"], sort=True).groups.items():
        rows = output.loc[index]
        all_a = rows.loc[rows.market_view.eq("ALL_A"), "joint_stress_score"]
        if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
            continue
        output.loc[index, "joint_stress_score_relative_to_all"] = (
            rows.joint_stress_score - float(all_a.iloc[0])
        )
        output.loc[index, "joint_stress_score_relative_view_rank_pct"] = rows.joint_stress_score.rank(
            method="average", pct=True
        )
    return output


def _event_match_ratio(primary: pd.Series, neighbor: pd.Series, tolerance: int = 2) -> float:
    primary_positions = np.flatnonzero(primary.to_numpy(bool))
    neighbor_positions = np.flatnonzero(neighbor.to_numpy(bool))
    if len(primary_positions) == 0:
        return float("nan")
    return float(
        np.mean(
            [
                bool(np.any(np.abs(neighbor_positions - position) <= tolerance))
                for position in primary_positions
            ]
        )
    )


def _components(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    names = list(correlation.columns)
    parent = {name: name for name in names}

    def find(name: str) -> str:
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)

    for index, left in enumerate(names):
        for right in names[index + 1 :]:
            value = correlation.loc[left, right]
            if np.isfinite(value) and abs(float(value)) >= threshold:
                union(left, right)
    grouped: dict[str, list[str]] = {}
    for name in names:
        grouped.setdefault(find(name), []).append(name)
    return sorted((sorted(values) for values in grouped.values()), key=lambda values: values[0])


def representation_diagnostics(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    group_rows: dict[str, Any] = {}
    score_neighbor_values: dict[str, list[float]] = {
        name: [] for name in ("geometric", "arithmetic", "activity10", "activity60")
    }
    sync_neighbor_values: dict[str, list[float]] = {"geometric": [], "arithmetic": []}
    threshold_values: dict[str, dict[str, list[float]]] = {
        neighbor: {
            "onset_match": [],
            "stress_jaccard": [],
            "relief_jaccard": [],
            "relief_rho": [],
            "dwell_rho": [],
            "impairment_jaccard": [],
        }
        for neighbor in ("permissive", "strict")
    }
    for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
        group = group.sort_values("trade_date").reset_index(drop=True)
        label = f"{view}:{denominator}"
        post_warmup = group.within_view_observation.ge(504)
        normalized = group.joint_stress_score.notna()
        onset_count = int(group.shock_onset_primary.sum())
        onset_years = int(group.loc[group.shock_onset_primary, "trade_date"].dt.year.nunique())
        impairment_count = int(group.activity_impairment_primary.sum())
        impairment_years = int(
            group.loc[group.activity_impairment_primary, "trade_date"].dt.year.nunique()
        )
        group_result: dict[str, Any] = {
            "post_warmup_score_coverage": float((normalized & post_warmup).sum() / post_warmup.sum()),
            "normalized_observations": int(normalized.sum()),
            "first_normalized_date": group.loc[normalized, "trade_date"].min().date().isoformat(),
            "primary_onsets": onset_count,
            "primary_onset_years": onset_years,
            "primary_impairment_observations": impairment_count,
            "primary_impairment_years": impairment_years,
            "state_counts": group.state_primary.value_counts().sort_index().to_dict(),
            "neighbors": {},
        }
        for name, column in (
            ("geometric", "joint_stress_score_geometric"),
            ("arithmetic", "joint_stress_score_arithmetic"),
            ("activity10", "joint_stress_score_activity10"),
            ("activity60", "joint_stress_score_activity60"),
        ):
            rho = _spearman(group.joint_stress_score, group[column])
            score_neighbor_values[name].append(rho)
            group_result.setdefault("score_neighbor_rho", {})[name] = rho
        for name, column in (
            ("geometric", "synchronization_pressure_geometric"),
            ("arithmetic", "synchronization_pressure_arithmetic"),
        ):
            rho = _spearman(group.synchronization_pressure, group[column])
            sync_neighbor_values[name].append(rho)
            group_result.setdefault("synchronization_neighbor_rho", {})[name] = rho
        for neighbor in ("permissive", "strict"):
            onset_match = _event_match_ratio(
                group.shock_onset_primary, group[f"shock_onset_{neighbor}"]
            )
            primary_stress = set(np.flatnonzero(group.state_primary.eq("STRESS").to_numpy()))
            neighbor_stress = set(np.flatnonzero(group[f"state_{neighbor}"].eq("STRESS").to_numpy()))
            primary_relief = set(np.flatnonzero(group.state_primary.eq("RELIEF").to_numpy()))
            neighbor_relief = set(np.flatnonzero(group[f"state_{neighbor}"].eq("RELIEF").to_numpy()))
            primary_impairment = set(np.flatnonzero(group.activity_impairment_primary.to_numpy(bool)))
            neighbor_impairment = set(
                np.flatnonzero(group[f"activity_impairment_{neighbor}"].to_numpy(bool))
            )
            metrics = {
                "onset_match_within_two_sessions": onset_match,
                "stress_jaccard": _jaccard(primary_stress, neighbor_stress),
                "relief_jaccard": _jaccard(primary_relief, neighbor_relief),
                "relief_rho": _spearman(
                    group.stress_relief_primary, group[f"stress_relief_{neighbor}"]
                ),
                "dwell_rho": _spearman(
                    group.episode_age_primary, group[f"episode_age_{neighbor}"]
                ),
                "impairment_jaccard": _jaccard(primary_impairment, neighbor_impairment),
            }
            group_result["neighbors"][neighbor] = metrics
            for key, value in metrics.items():
                normalized_key = {
                    "onset_match_within_two_sessions": "onset_match",
                    "stress_jaccard": "stress_jaccard",
                    "relief_jaccard": "relief_jaccard",
                    "relief_rho": "relief_rho",
                    "dwell_rho": "dwell_rho",
                    "impairment_jaccard": "impairment_jaccard",
                }[key]
                threshold_values[neighbor][normalized_key].append(value)
        group_rows[label] = group_result

    score_neighbor_medians = {
        name: float(np.nanmedian(values)) for name, values in score_neighbor_values.items()
    }
    sync_neighbor_medians = {
        name: float(np.nanmedian(values)) for name, values in sync_neighbor_values.items()
    }
    threshold_summary = {
        neighbor: {
            key: _finite_summary(values)
            for key, values in metrics.items()
        }
        for neighbor, metrics in threshold_values.items()
    }

    denominator_rhos: dict[str, float] = {}
    for view, group in panel.groupby("market_view", sort=True):
        wide = group.pivot(index="trade_date", columns="denominator", values="joint_stress_score")
        denominator_rhos[str(view)] = _spearman(wide.ALL_STATUS, wide.NON_ST)
    denominator_median = float(np.nanmedian(list(denominator_rhos.values())))

    year_cells: dict[str, Any] = {}
    year_nondegenerate = True
    for (view, denominator, year), rows in panel.groupby(
        ["market_view", "denominator", panel.trade_date.dt.year], sort=True
    ):
        values = rows.joint_stress_score.dropna()
        if len(values) < int(gates["view_year_minimum_observations"]):
            continue
        valid = bool(np.isfinite(values.std()) and values.std() > 0)
        year_cells[f"{view}:{denominator}:{year}"] = {"n": len(values), "nondegenerate": valid}
        year_nondegenerate &= valid

    coverage_pass = all(
        item["post_warmup_score_coverage"] >= gates["post_warmup_score_coverage"]
        and item["normalized_observations"] >= gates["minimum_normalized_observations_per_group"]
        for item in group_rows.values()
    )
    score_pass = (
        min(score_neighbor_medians.values()) >= gates["joint_score_worst_neighbor_median_spearman"]
        and denominator_median >= gates["all_status_vs_non_st_median_spearman"]
        and year_nondegenerate
        and coverage_pass
    )
    sync_pass = min(sync_neighbor_medians.values()) >= gates[
        "joint_score_worst_neighbor_median_spearman"
    ] and coverage_pass
    onset_sample_pass = all(
        item["primary_onsets"] >= gates["minimum_primary_onsets_per_group"]
        and item["primary_onset_years"] >= gates["minimum_primary_onset_years_per_group"]
        for item in group_rows.values()
    )
    onset_neighbor_pass = all(
        threshold_summary[neighbor]["onset_match"]["minimum"]
        >= gates["onset_match_within_two_sessions"]
        for neighbor in threshold_summary
    )
    state_pass = all(
        threshold_summary[neighbor][state]["minimum"] >= gates[gate]
        for neighbor in threshold_summary
        for state, gate in (
            ("stress_jaccard", "stress_state_jaccard"),
            ("relief_jaccard", "relief_state_jaccard"),
        )
    )
    relief_pass = all(
        threshold_summary[neighbor]["relief_rho"]["median"]
        >= gates["relief_neighbor_median_spearman"]
        for neighbor in threshold_summary
    )
    dwell_pass = all(
        threshold_summary[neighbor]["dwell_rho"]["median"]
        >= gates["dwell_neighbor_median_spearman"]
        for neighbor in threshold_summary
    )
    impairment_sample_pass = all(
        item["primary_impairment_observations"]
        >= gates["minimum_activity_impairment_observations_per_group"]
        and item["primary_impairment_years"]
        >= gates["minimum_activity_impairment_years_per_group"]
        for item in group_rows.values()
    )
    impairment_neighbor_pass = all(
        threshold_summary[neighbor]["impairment_jaccard"]["minimum"]
        >= gates["activity_impairment_jaccard"]
        for neighbor in threshold_summary
    )
    decisions = {
        "synchronization_pressure": sync_pass,
        "joint_stress_score": score_pass,
        "shock_onset": score_pass and onset_sample_pass and onset_neighbor_pass,
        "stress_dwell": score_pass and onset_sample_pass and onset_neighbor_pass and state_pass and dwell_pass,
        "stress_relief": score_pass and onset_sample_pass and onset_neighbor_pass and state_pass and relief_pass,
        "activity_impairment": (
            score_pass
            and onset_sample_pass
            and onset_neighbor_pass
            and state_pass
            and relief_pass
            and impairment_sample_pass
            and impairment_neighbor_pass
        ),
    }

    all_status = panel.loc[panel.denominator.eq("ALL_STATUS")].copy()
    correlation_columns = {
        **ROLE_COLUMNS,
        **VOLATILITY_CONTROLS,
    }
    correlation = pd.DataFrame(
        {
            name: pd.to_numeric(all_status[column], errors="coerce")
            for name, column in correlation_columns.items()
        }
    ).corr(method="spearman", min_periods=100)
    components = _components(correlation, gates["latent_component_edge_absolute_spearman"])
    dispositions: dict[str, str] = {}
    accepted_minimal: list[str] = []
    for role in ROLE_PRIORITY:
        if not decisions[role]:
            dispositions[role] = "representation_gate_failed"
            continue
        redundant_vol = [
            control
            for control in VOLATILITY_CONTROLS
            if np.isfinite(correlation.loc[role, control])
            and abs(float(correlation.loc[role, control]))
            >= gates["volatility_redundancy_edge_absolute_spearman"]
        ]
        if redundant_vol:
            dispositions[role] = f"redundant_with_volatility:{redundant_vol[0]}"
            continue
        redundant_role = [
            accepted
            for accepted in accepted_minimal
            if np.isfinite(correlation.loc[role, accepted])
            and abs(float(correlation.loc[role, accepted]))
            >= gates["latent_component_edge_absolute_spearman"]
        ]
        if redundant_role:
            dispositions[role] = f"redundant_with:{redundant_role[0]}"
            continue
        dispositions[role] = "ACCEPT"
        accepted_minimal.append(role)

    return {
        "groups": group_rows,
        "score_neighbor_median_spearman": score_neighbor_medians,
        "synchronization_neighbor_median_spearman": sync_neighbor_medians,
        "denominator_spearman": denominator_rhos,
        "denominator_median_spearman": denominator_median,
        "view_year_cells": year_cells,
        "threshold_neighbor_summary": threshold_summary,
        "gate_components": {
            "coverage": coverage_pass,
            "score": score_pass,
            "synchronization": sync_pass,
            "onset_sample": onset_sample_pass,
            "onset_neighbor": onset_neighbor_pass,
            "state": state_pass,
            "relief": relief_pass,
            "dwell": dwell_pass,
            "impairment_sample": impairment_sample_pass,
            "impairment_neighbor": impairment_neighbor_pass,
        },
        "role_gate_pass": decisions,
        "role_dispositions": dispositions,
        "minimal_nonredundant_roles": accepted_minimal,
        "correlation_with_volatility": correlation.to_dict(),
        "latent_components_with_volatility": components,
    }


def _format(value: Any) -> str:
    return "NA" if value is None or not math.isfinite(float(value)) else f"{float(value):.3f}"


def _report(result: dict[str, Any]) -> str:
    diagnostics = result["diagnostics"]
    lines = [
        "# MKT-SHOCK-001 direction-neutral shock/relief representation",
        "",
        f"Decision: `{result['decision']}`.",
        "",
        "## Boundary",
        "",
        f"- Output rows: {result['population']['rows']}; normalized rows per group: {result['population']['minimum_normalized_rows_per_group']}..{result['population']['maximum_normalized_rows_per_group']}.",
        "- Strategy fields, future returns, post-decision paths, and CY-011 read: **none**.",
        "- Rejected raw liquidity-activity change3/5/10 columns read: **none**.",
        "- The process is direction-neutral. `RELIEF` is falling synchronization/activity stress, not price recovery; activity dry-up is not proven impairment.",
        "",
        "## Role gates",
        "",
        "| Role | Gate | Minimal disposition |",
        "|---|---|---|",
    ]
    for role in ROLE_PRIORITY:
        lines.append(
            f"| {role} | {'PASS' if diagnostics['role_gate_pass'][role] else 'FAIL'} | {diagnostics['role_dispositions'][role]} |"
        )
    lines += [
        "",
        "## Continuous score stability",
        "",
        "| Neighbor | Median within-group rho |",
        "|---|---:|",
    ]
    for neighbor, rho in diagnostics["score_neighbor_median_spearman"].items():
        lines.append(f"| joint {neighbor} | {rho:.3f} |")
    for neighbor, rho in diagnostics["synchronization_neighbor_median_spearman"].items():
        lines.append(f"| synchronization {neighbor} | {rho:.3f} |")
    lines += [
        "",
        f"ALL_STATUS/NON_ST median joint-score rho: {diagnostics['denominator_median_spearman']:.3f}.",
        "",
        "## Episode robustness",
        "",
        "| Threshold neighbor | Onset match min/median | STRESS Jaccard min/median | RELIEF Jaccard min/median | Dwell rho median | Relief rho median | Impairment Jaccard min/median |",
        "|---|---|---|---|---:|---:|---|",
    ]
    for neighbor, summary in diagnostics["threshold_neighbor_summary"].items():
        lines.append(
            f"| {neighbor} | {_format(summary['onset_match']['minimum'])}/{_format(summary['onset_match']['median'])} | "
            f"{_format(summary['stress_jaccard']['minimum'])}/{_format(summary['stress_jaccard']['median'])} | "
            f"{_format(summary['relief_jaccard']['minimum'])}/{_format(summary['relief_jaccard']['median'])} | "
            f"{_format(summary['dwell_rho']['median'])} | {_format(summary['relief_rho']['median'])} | "
            f"{_format(summary['impairment_jaccard']['minimum'])}/{_format(summary['impairment_jaccard']['median'])} |"
        )
    lines += [
        "",
        "## Group event audit",
        "",
        "| Group | Coverage | Normalized N | Onsets | Onset years | Dry-up observations | Dry-up years |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for group, item in diagnostics["groups"].items():
        lines.append(
            f"| {group} | {item['post_warmup_score_coverage']:.3f} | {item['normalized_observations']} | "
            f"{item['primary_onsets']} | {item['primary_onset_years']} | "
            f"{item['primary_impairment_observations']} | {item['primary_impairment_years']} |"
        )
    lines += [
        "",
        "The exact episode representation fails first on event support: primary onsets range from zero to one per group versus the frozen minimum of eight across three years. Strict-threshold onset matching is zero; STRESS/RELIEF agreement and dwell/relief correlations are absent or below gate. No activity-dry-up observation occurs. These are sparse/unstable exact-state failures, not permission to lower the threshold after seeing the result.",
        "",
        "## Volatility redundancy",
        "",
        f"Outcome-blind absolute-Spearman components at 0.85, including volatility controls: `{diagnostics['latent_components_with_volatility']}`.",
        "",
        f"Minimal nonredundant passing process roles: `{', '.join(diagnostics['minimal_nonredundant_roles']) or 'NONE'}`.",
        "",
        "A same-date correlation with volatility is redundancy evidence only. It is not panic, causality, or forecasting evidence.",
        "",
        "## Interpretation boundary",
        "",
        "A passed continuous score means the joint historical-rank representation is stable across fixed shapes, activity horizons, denominators, and years. Episode roles must pass their own event/state/dwell/relief/dry-up gates and cannot inherit score acceptance.",
        "",
        "No result can be called panic because the representation contains no frozen negative-direction coordinate. No result can be called price recovery because it reads no later price path. Strategy usefulness remains untested.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`.",
        f"- CLQ panel SHA-256: `{result['hashes']['clq_panel_sha256']}`.",
        f"- Volatility panel SHA-256: `{result['hashes']['volatility_panel_sha256']}`.",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`.",
    ]
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ShockRepresentationError("MKT-SHOCK-001 spec hash mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise ShockRepresentationError("MKT-SHOCK-001 spec is not frozen")
    source = load_bound_panels(spec)
    panel = attach_representations(source)
    diagnostics = representation_diagnostics(panel, spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.12g", date_format="%Y-%m-%d")

    passing = diagnostics["role_gate_pass"]
    if passing["shock_onset"] and passing["stress_relief"]:
        decision = "DIRECTION_NEUTRAL_SHOCK_RELIEF_PROCESS_FROZEN"
    elif passing["joint_stress_score"]:
        decision = "CONTINUOUS_STRESS_SCORES_FROZEN_EXACT_EPISODE_REPRESENTATION_FAIL"
    else:
        decision = "NO_STABLE_SHOCK_RECOVERY_REPRESENTATION"
    group_counts = [item["normalized_observations"] for item in diagnostics["groups"].values()]
    result = {
        "experiment_id": "MKT-SHOCK-001",
        "decision": decision,
        "outcome_fields_read": [],
        "future_return_fields_read": [],
        "rejected_liquidity_change_fields_read": [],
        "strategy_rule_authorized": False,
        "panic_claim_authorized": False,
        "price_recovery_claim_authorized": False,
        "population": {
            "rows": len(panel),
            "groups": len(diagnostics["groups"]),
            "first_date": panel.trade_date.min().date().isoformat(),
            "last_date": panel.trade_date.max().date().isoformat(),
            "minimum_normalized_rows_per_group": min(group_counts),
            "maximum_normalized_rows_per_group": max(group_counts),
        },
        "diagnostics": diagnostics,
        "limitations": {
            "direction": "NOT_REPRESENTED",
            "panic": "NOT_ESTABLISHED",
            "stress_relief": "NOT_PRICE_RECOVERY",
            "activity_impairment": "DRY_UP_DESCRIPTOR_NOT_CAUSAL_DAMAGE",
            "future_path": "NOT_READ",
            "economic_usefulness": "NOT_TESTED",
            "pit_grade": "bounded PIT-B",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "clq_panel_sha256": sha256_file(CLQ_PATH),
            "volatility_panel_sha256": sha256_file(VOL_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    RESULT_PATH.write_text(json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    result = run()
    print(
        json.dumps(
            {
                "decision": result["decision"],
                "population": result["population"],
                "role_gate_pass": result["diagnostics"]["role_gate_pass"],
                "role_dispositions": result["diagnostics"]["role_dispositions"],
                "hashes": result["hashes"],
            },
            indent=2,
            sort_keys=True,
        )
    )
