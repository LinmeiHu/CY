#!/usr/bin/env python3
"""Construct frozen MKT-DSTRESS-001 directional synchronization processes."""

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

from run_mkt_shock_001 import (  # noqa: E402
    _event_match_ratio,
    _finite_summary,
    _jaccard,
    _spearman,
)
from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-DSTRESS-001_spec.json"
SHOCK_PATH = PROGRAM / "artifacts/MKT-SHOCK-001_shock_recovery_panel.csv"
RISK_PATH = PROGRAM / "artifacts/MKT-RISK-001_risk_appetite_panel.csv"
PANEL_PATH = PROGRAM / "artifacts/MKT-DSTRESS-001_directional_process_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DSTRESS-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DSTRESS-001_directional_process.md"
EXPECTED_SPEC_SHA256 = "63093a0abdd8a44374b9b0c1a066130774131df7c17e7b85cb55cb697ca305d2"
KEYS = ["trade_date", "market_view", "denominator"]
SIDES = ("downside", "upside")
CONFIGS = {
    "permissive": {"entry": 0.70, "reset": 0.40, "high_activity": 0.70},
    "primary": {"entry": 0.80, "reset": 0.50, "high_activity": 0.80},
    "strict": {"entry": 0.90, "reset": 0.60, "high_activity": 0.90},
}
VOLATILITY_CONTROLS = (
    "realized_volatility_median20",
    "intraday_range_median_smooth5",
    "volatility_mass_share_top10",
    "realized_volatility_change5",
)


class DirectionalStressError(RuntimeError):
    """Fail-closed MKT-DSTRESS-001 construction error."""


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


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DirectionalStressError("frozen spec identity changed")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise DirectionalStressError("scientific spec is not frozen")
    return spec


def _validate_hash(path: Path, expected: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise DirectionalStressError(f"bound panel identity changed: {path.name}")


def load_bound_panels(spec: dict[str, Any]) -> pd.DataFrame:
    shock_item = spec["inputs"]["shock_panel"]
    risk_item = spec["inputs"]["risk_panel"]
    _validate_hash(SHOCK_PATH, shock_item["sha256"])
    _validate_hash(RISK_PATH, risk_item["sha256"])
    forbidden_tokens = (
        "state_primary", "shock_onset", "episode_id", "episode_age",
        "episode_peak", "stress_relief", "activity_impairment",
    )
    if any(
        token in column
        for column in shock_item["allowed_columns"]
        for token in forbidden_tokens
    ):
        raise DirectionalStressError("failed shock-episode field entered whitelist")
    shock = pd.read_csv(SHOCK_PATH, usecols=shock_item["allowed_columns"])
    risk = pd.read_csv(RISK_PATH, usecols=risk_item["allowed_columns"])
    for label, frame in (("shock", shock), ("risk", risk)):
        frame["trade_date"] = pd.to_datetime(frame.trade_date)
        if frame.duplicated(KEYS).any() or len(frame) != 10696:
            raise DirectionalStressError(f"{label} key/population changed")
        if frame.trade_date.max() > pd.Timestamp("2023-12-31"):
            raise DirectionalStressError(f"post-2023 {label} row entered")
    panel = shock.merge(risk, on=KEYS, validate="one_to_one", suffixes=("_shock", "_risk"))
    if len(panel) != 10696:
        raise DirectionalStressError("bound panel intersection changed")
    if not panel.groupby(["market_view", "denominator"]).size().eq(1337).all():
        raise DirectionalStressError("group population changed")
    shock_decision = pd.to_datetime(panel.decision_at_clq, utc=True)
    shock_available = pd.to_datetime(panel.available_at_clq, utc=True)
    risk_decision = pd.to_datetime(panel.decision_at, utc=True)
    risk_available = pd.to_datetime(panel.available_at, utc=True)
    if not (
        shock_decision.eq(shock_available)
        & shock_decision.eq(risk_decision)
        & shock_decision.eq(risk_available)
    ).all():
        raise DirectionalStressError("completed-close timestamp mismatch")
    local = shock_decision.dt.tz_convert("Asia/Shanghai")
    if not (local.dt.hour.eq(15) & local.dt.minute.eq(0)).all():
        raise DirectionalStressError("decision timestamp is not completed close")
    if not panel.snapshot_id_clq.eq(panel.snapshot_id).all():
        raise DirectionalStressError("snapshot identity mismatch")
    invalid_risk = ~panel.view_valid.astype(bool)
    risk_absolute = [
        f"{side}_extreme_participation_{threshold}"
        for side in ("upside", "downside")
        for threshold in (50, 70, 90)
    ]
    panel.loc[invalid_risk, risk_absolute] = np.nan
    return panel.sort_values(KEYS).reset_index(drop=True)


def build_directional_episode(
    score: np.ndarray,
    activity: np.ndarray,
    entry: float,
    reset: float,
    high_activity: float,
) -> pd.DataFrame:
    """Causal elevated-process state machine; missing values break state."""
    if not (0 <= reset < entry <= 1 and 0 <= high_activity <= 1):
        raise DirectionalStressError("invalid process thresholds")
    size = len(score)
    state = np.full(size, "MISSING", dtype=object)
    onset = np.zeros(size, dtype=bool)
    episode_id_values = np.full(size, np.nan)
    age_values = np.full(size, np.nan)
    peak_values = np.full(size, np.nan)
    relief_values = np.full(size, np.nan)
    high_activity_values = np.zeros(size, dtype=bool)
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
            if current < entry:
                state[index] = "NORMAL"
                continue
            active = True
            episode_id += 1
            age = 1
            peak = float(current)
            state[index] = "ONSET"
            onset[index] = True
        elif current < reset:
            active = False
            age = 0
            peak = float("nan")
            state[index] = "NORMAL"
            continue
        else:
            age += 1
            peak = max(peak, float(current))
            state[index] = "ELEVATED" if current >= entry else "RELIEF"
        episode_id_values[index] = episode_id
        age_values[index] = age
        peak_values[index] = peak
        relief_values[index] = peak - float(current)
        high_activity_values[index] = current_activity >= high_activity
    return pd.DataFrame({
        "state": state,
        "onset": onset,
        "episode_id": episode_id_values,
        "episode_age": age_values,
        "episode_peak": peak_values,
        "process_relief": relief_values,
        "high_activity": high_activity_values,
    })


def attach_representations(panel: pd.DataFrame) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    for _, group in panel.groupby(["market_view", "denominator"], sort=True):
        item = group.sort_values("trade_date").copy().reset_index(drop=True)
        for side in SIDES:
            for threshold in (50, 70, 90):
                raw = item[f"{side}_extreme_participation_{threshold}"]
                item[f"{side}_extreme_{threshold}_pit_3y_pct"] = causal_rolling_percentile(raw)
            synchronization = item.synchronization_pressure.to_numpy(float)
            side50 = item[f"{side}_extreme_50_pit_3y_pct"].to_numpy(float)
            side70 = item[f"{side}_extreme_70_pit_3y_pct"].to_numpy(float)
            side90 = item[f"{side}_extreme_90_pit_3y_pct"].to_numpy(float)
            valid = np.isfinite(synchronization) & np.isfinite(side70)
            item[f"{side}_directional_sync_score"] = np.where(
                valid, np.minimum(synchronization, side70), np.nan
            )
            item[f"{side}_directional_sync_geometric"] = np.where(
                valid, np.sqrt(synchronization * side70), np.nan
            )
            item[f"{side}_directional_sync_arithmetic"] = np.where(
                valid, (synchronization + side70) / 2.0, np.nan
            )
            item[f"{side}_directional_sync_threshold50"] = np.where(
                np.isfinite(synchronization) & np.isfinite(side50),
                np.minimum(synchronization, side50), np.nan,
            )
            item[f"{side}_directional_sync_threshold90"] = np.where(
                np.isfinite(synchronization) & np.isfinite(side90),
                np.minimum(synchronization, side90), np.nan,
            )
            score = item[f"{side}_directional_sync_score"]
            item[f"{side}_directional_sync_score_pit_expanding_pct"] = causal_expanding_percentile(score)
            item[f"{side}_directional_sync_score_pit_3y_pct"] = causal_rolling_percentile(score)
            item[f"{side}_directional_sync_score_pit_3y_robust_z"] = causal_rolling_robust_z(score)
            for name, config in CONFIGS.items():
                episode = build_directional_episode(
                    score.to_numpy(float),
                    item.liquidity_median_amount_ratio20_pit_3y_pct.to_numpy(float),
                    config["entry"], config["reset"], config["high_activity"],
                )
                for column in episode:
                    item[f"{side}_{column}_{name}"] = episode[column].to_numpy()
        item["directional_sync_balance"] = (
            item.upside_directional_sync_score - item.downside_directional_sync_score
        )
        item["directional_sync_balance_geometric"] = (
            item.upside_directional_sync_geometric - item.downside_directional_sync_geometric
        )
        item["directional_sync_balance_arithmetic"] = (
            item.upside_directional_sync_arithmetic - item.downside_directional_sync_arithmetic
        )
        item["directional_sync_balance_threshold50"] = (
            item.upside_directional_sync_threshold50 - item.downside_directional_sync_threshold50
        )
        item["directional_sync_balance_threshold90"] = (
            item.upside_directional_sync_threshold90 - item.downside_directional_sync_threshold90
        )
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(KEYS).reset_index(drop=True)
    for side in SIDES:
        primary = f"{side}_directional_sync_score"
        out[f"{primary}_relative_to_all"] = np.nan
        out[f"{primary}_relative_view_rank_pct"] = np.nan
        for (_, _), index in out.groupby(["trade_date", "denominator"], sort=True).groups.items():
            rows = out.loc[index]
            all_a = rows.loc[rows.market_view.eq("ALL_A"), primary]
            if len(all_a) != 1 or not np.isfinite(float(all_a.iloc[0])):
                continue
            out.loc[index, f"{primary}_relative_to_all"] = rows[primary] - float(all_a.iloc[0])
            if rows[primary].notna().sum() >= 3:
                out.loc[index, f"{primary}_relative_view_rank_pct"] = rows[primary].rank(
                    method="average", pct=True
                )
    return out


def _state_set(group: pd.DataFrame, side: str, config: str, label: str) -> set[int]:
    state = group[f"{side}_state_{config}"]
    if label == "ELEVATED":
        mask = state.isin(["ONSET", "ELEVATED"])
    else:
        mask = state.eq(label)
    return set(np.flatnonzero(mask.to_numpy()))


def diagnostics(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    result: dict[str, Any] = {"sides": {}}
    for side in SIDES:
        primary = f"{side}_directional_sync_score"
        neighbor_names = {
            "geometric": f"{side}_directional_sync_geometric",
            "arithmetic": f"{side}_directional_sync_arithmetic",
            "threshold50": f"{side}_directional_sync_threshold50",
            "threshold90": f"{side}_directional_sync_threshold90",
        }
        groups: dict[str, Any] = {}
        neighbor_rhos: dict[str, list[float]] = {name: [] for name in neighbor_names}
        config_metrics: dict[str, dict[str, list[float]]] = {
            config: {key: [] for key in (
                "onset_match", "elevated_jaccard", "relief_jaccard",
                "dwell_rho", "relief_rho", "high_activity_jaccard",
            )}
            for config in ("permissive", "strict")
        }
        for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True):
            group = group.sort_values("trade_date").reset_index(drop=True)
            label = f"{view}:{denominator}"
            valid = group[primary].notna()
            post_warmup = group.groupby(["market_view", "denominator"]).cumcount().ge(503)
            group_item: dict[str, Any] = {
                "normalized_observations": int(valid.sum()),
                "post_warmup_coverage": float((valid & post_warmup).sum() / post_warmup.sum()),
                "first_normalized_date": group.loc[valid, "trade_date"].min().date().isoformat(),
                "neighbors": {},
            }
            for name, column in neighbor_names.items():
                rho = _spearman(group[primary], group[column])
                neighbor_rhos[name].append(rho)
                group_item["neighbors"][name] = rho
            primary_onset = group[f"{side}_onset_primary"]
            group_item["primary_onsets"] = int(primary_onset.sum())
            group_item["primary_onset_years"] = int(
                group.loc[primary_onset, "trade_date"].dt.year.nunique()
            )
            primary_high = group[f"{side}_high_activity_primary"]
            group_item["primary_high_activity_observations"] = int(primary_high.sum())
            group_item["primary_high_activity_years"] = int(
                group.loc[primary_high, "trade_date"].dt.year.nunique()
            )
            group_item["primary_state_counts"] = (
                group[f"{side}_state_primary"].value_counts().sort_index().to_dict()
            )
            group_item["configurations"] = {}
            for config in ("permissive", "strict"):
                metrics = {
                    "onset_match": _event_match_ratio(
                        primary_onset, group[f"{side}_onset_{config}"], tolerance=2
                    ),
                    "elevated_jaccard": _jaccard(
                        _state_set(group, side, "primary", "ELEVATED"),
                        _state_set(group, side, config, "ELEVATED"),
                    ),
                    "relief_jaccard": _jaccard(
                        _state_set(group, side, "primary", "RELIEF"),
                        _state_set(group, side, config, "RELIEF"),
                    ),
                    "dwell_rho": _spearman(
                        group[f"{side}_episode_age_primary"],
                        group[f"{side}_episode_age_{config}"],
                    ),
                    "relief_rho": _spearman(
                        group[f"{side}_process_relief_primary"],
                        group[f"{side}_process_relief_{config}"],
                    ),
                    "high_activity_jaccard": _jaccard(
                        set(np.flatnonzero(primary_high.to_numpy(bool))),
                        set(np.flatnonzero(group[f"{side}_high_activity_{config}"].to_numpy(bool))),
                    ),
                }
                group_item["configurations"][config] = metrics
                for key, value in metrics.items():
                    config_metrics[config][key].append(value)
            groups[label] = group_item

        neighbor_medians = {
            name: float(np.nanmedian(values)) for name, values in neighbor_rhos.items()
        }
        denominator_rhos: dict[str, float] = {}
        for view, group in panel.groupby("market_view", sort=True):
            wide = group.pivot(index="trade_date", columns="denominator", values=primary)
            denominator_rhos[str(view)] = _spearman(wide.ALL_STATUS, wide.NON_ST)
        denominator_median = float(np.nanmedian(list(denominator_rhos.values())))
        year_cells: dict[str, Any] = {}
        year_nondegenerate = True
        for (view, denominator, year), group in panel.groupby(
            ["market_view", "denominator", panel.trade_date.dt.year], sort=True
        ):
            values = group[primary].dropna()
            if len(values) < gates["view_year_minimum_observations"]:
                continue
            passed = bool(np.isfinite(values.std()) and values.std() > 0)
            year_cells[f"{view}:{denominator}:{year}"] = {"n": int(len(values)), "nondegenerate": passed}
            year_nondegenerate &= passed

        external_controls = {
            "synchronization_pressure": "synchronization_pressure",
            f"{side}_signed_primitive": f"{side}_extreme_70_pit_3y_pct",
            "joint_activity_stress": "joint_stress_score",
            **{name: name for name in VOLATILITY_CONTROLS},
        }
        external: dict[str, Any] = {}
        for control_name, column in external_controls.items():
            by_group = {
                f"{view}:{denominator}": _spearman(group[primary], group[column])
                for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True)
            }
            external[control_name] = {
                "by_group": by_group,
                "median_absolute_spearman": float(np.nanmedian(np.abs(list(by_group.values())))),
            }
        external_max = max(item["median_absolute_spearman"] for item in external.values())
        config_summary = {
            config: {key: _finite_summary(values) for key, values in metrics.items()}
            for config, metrics in config_metrics.items()
        }
        coverage_pass = all(
            item["post_warmup_coverage"] >= gates["common_post_warmup_coverage"]
            and item["normalized_observations"] >= gates["minimum_group_observations"]
            for item in groups.values()
        )
        continuous_pass = bool(
            coverage_pass
            and min(neighbor_medians.values()) >= gates["worst_median_score_neighbor_spearman"]
            and denominator_median >= gates["all_status_vs_non_st_median_spearman"]
            and year_nondegenerate
            and external_max < gates["single_input_or_volatility_redundancy_median_absolute_spearman"]
        )
        onset_sample = all(
            item["primary_onsets"] >= gates["minimum_onsets_each_group"]
            and item["primary_onset_years"] >= gates["minimum_onset_years_each_group"]
            for item in groups.values()
        )
        onset_neighbor = all(
            config_summary[config]["onset_match"]["minimum"] >= gates["minimum_onset_match_each_neighbor"]
            for config in config_summary
        )
        state_pass = all(
            config_summary[config][key]["minimum"]
            >= gates["minimum_elevated_and_relief_state_jaccard_each_neighbor"]
            for config in config_summary for key in ("elevated_jaccard", "relief_jaccard")
        )
        dwell_relief_pass = all(
            config_summary[config][key]["median"]
            >= gates["minimum_dwell_and_relief_median_spearman_each_neighbor"]
            for config in config_summary for key in ("dwell_rho", "relief_rho")
        )
        high_activity_sample = all(
            item["primary_high_activity_observations"]
            >= gates["minimum_high_activity_observations_each_group"]
            and item["primary_high_activity_years"]
            >= gates["minimum_high_activity_years_each_group"]
            for item in groups.values()
        )
        high_activity_neighbor = all(
            config_summary[config]["high_activity_jaccard"]["minimum"]
            >= gates["minimum_high_activity_jaccard_each_neighbor"]
            for config in config_summary
        )
        process_pass = bool(
            continuous_pass and onset_sample and onset_neighbor and state_pass and dwell_relief_pass
        )
        activity_modifier_pass = bool(process_pass and high_activity_sample and high_activity_neighbor)
        result["sides"][side] = {
            "groups": groups,
            "neighbor_median_spearman": neighbor_medians,
            "denominator_spearman": denominator_rhos,
            "denominator_median_spearman": denominator_median,
            "view_year_cells": year_cells,
            "external_redundancy": external,
            "maximum_external_median_absolute_spearman": external_max,
            "configuration_summary": config_summary,
            "gate_components": {
                "coverage": coverage_pass,
                "neighbors": min(neighbor_medians.values()) >= gates["worst_median_score_neighbor_spearman"],
                "denominator": denominator_median >= gates["all_status_vs_non_st_median_spearman"],
                "year_nondegenerate": year_nondegenerate,
                "single_input_and_volatility_nonredundancy": external_max < gates["single_input_or_volatility_redundancy_median_absolute_spearman"],
                "onset_sample": onset_sample,
                "onset_neighbor": onset_neighbor,
                "state": state_pass,
                "dwell_and_relief": dwell_relief_pass,
                "high_activity_sample": high_activity_sample,
                "high_activity_neighbor": high_activity_neighbor,
            },
            "continuous_score_pass": continuous_pass,
            "recurring_process_pass": process_pass,
            "activity_modifier_pass": activity_modifier_pass,
        }
    result["directional_balance"] = {
        "status": "DETERMINISTIC_SUMMARY_NOT_INDEPENDENT_MECHANISM",
        "formula": "upside_directional_sync_score - downside_directional_sync_score",
        "side_score_spearman": _spearman(
            panel.upside_directional_sync_score, panel.downside_directional_sync_score
        ),
    }
    return result


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-DSTRESS-001 directional synchronization/stress process",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Common panel: {result['population']['rows']:,} rows, {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Failed MKT-SHOCK episode fields, future returns, strategy outcomes, and CY-011 read: **none**.",
        "- `ELEVATED` is a process label, not panic, speculation, recovery, or usefulness.",
        "",
        "## Side-specific gates",
        "",
        "| Side | Observations/group | Worst score-neighbor rho | ST rho | Max single-input/vol rho | Continuous | Recurring process | Activity modifier |",
        "|---|---:|---:|---:|---:|---|---|---|",
    ]
    for side in SIDES:
        item = result["diagnostics"]["sides"][side]
        minimum_observations = min(group["normalized_observations"] for group in item["groups"].values())
        lines.append(
            f"| {side} | {minimum_observations} | {min(item['neighbor_median_spearman'].values()):.3f} | "
            f"{item['denominator_median_spearman']:.3f} | {item['maximum_external_median_absolute_spearman']:.3f} | "
            f"{'PASS' if item['continuous_score_pass'] else 'FAIL'} | "
            f"{'PASS' if item['recurring_process_pass'] else 'FAIL'} | "
            f"{'PASS' if item['activity_modifier_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Process interpretation",
        "",
    ])
    for side in SIDES:
        item = result["diagnostics"]["sides"][side]
        onsets = [group["primary_onsets"] for group in item["groups"].values()]
        years = [group["primary_onset_years"] for group in item["groups"].values()]
        lines.append(
            f"- {side}: primary onsets/group {min(onsets)}..{max(onsets)}, years/group {min(years)}..{max(years)}; "
            f"gate components `{item['gate_components']}`."
        )
    lines.extend([
        "- Directional balance is retained only as the exact difference of the two side scores; it is not a third mechanism.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Shock panel SHA-256: `{result['hashes']['shock_panel_sha256']}`",
        f"- Risk panel SHA-256: `{result['hashes']['risk_panel_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    bound = load_bound_panels(spec)
    panel = attach_representations(bound)
    diag = diagnostics(panel, spec)
    keep_source = [
        *KEYS, "decision_at", "available_at", "snapshot_id", "view_valid",
        "synchronization_pressure", "joint_stress_score",
        "liquidity_median_amount_ratio20_pit_3y_pct", "activity10_pit_3y_pct",
        "activity60_pit_3y_pct", "median_signed_limit_utilization_pit_expanding_pct",
        "median_signed_limit_utilization_pit_3y_pct",
        "median_signed_limit_utilization_pit_3y_robust_z", *VOLATILITY_CONTROLS,
    ]
    derived = [
        column for column in panel.columns
        if column.startswith(("downside_", "upside_", "directional_sync_balance"))
    ]
    output = panel[[*keep_source, *derived]].copy()
    output["trade_date"] = output.trade_date.dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    status_parts = []
    for side in SIDES:
        item = diag["sides"][side]
        if item["activity_modifier_pass"]:
            status_parts.append(f"{side.upper()}_PROCESS_AND_ACTIVITY_PASS")
        elif item["recurring_process_pass"]:
            status_parts.append(f"{side.upper()}_PROCESS_PASS_ACTIVITY_FAIL")
        elif item["continuous_score_pass"]:
            status_parts.append(f"{side.upper()}_CONTINUOUS_PASS_PROCESS_FAIL")
        else:
            status_parts.append(f"{side.upper()}_CONTINUOUS_FAIL")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_" + "_".join(status_parts),
        "usefulness_claim": "NONE",
        "panic_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "failed_shock_episode_fields_read": [],
        "population": {
            "rows": int(len(output)),
            "first_date": str(output.trade_date.min()),
            "last_date": str(output.trade_date.max()),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
        },
        "diagnostics": diag,
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "shock_panel_sha256": sha256_file(SHOCK_PATH),
            "risk_panel_sha256": sha256_file(RISK_PATH),
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    cleaned = _clean(result)
    RESULT_PATH.write_text(json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return cleaned


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "status": final["status"],
        "population": final["population"],
        "side_decisions": {
            side: {
                "continuous": final["diagnostics"]["sides"][side]["continuous_score_pass"],
                "process": final["diagnostics"]["sides"][side]["recurring_process_pass"],
                "activity": final["diagnostics"]["sides"][side]["activity_modifier_pass"],
                "gate_components": final["diagnostics"]["sides"][side]["gate_components"],
            }
            for side in SIDES
        },
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
