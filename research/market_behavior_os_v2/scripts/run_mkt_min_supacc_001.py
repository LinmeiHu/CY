#!/usr/bin/env python3
"""Construct frozen same-session market intraday mechanism representations."""

from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-SUPACC-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-SUPACC-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-SUPACC-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-SUPACC-001_representation.md"
EXPECTED_SPEC_SHA256 = "fcdc9d359a153ba473543ee7ccfabb6f7ed68a4c37fca34a5a2b3e4f60be9435"
KEYS = ["trade_date", "market_view", "denominator"]
QUANTILES = ("median", "p40", "p60")


class IntradayMechanismError(RuntimeError):
    """Fail-closed MKT-MIN-SUPACC-001 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
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
        raise IntradayMechanismError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_MECHANISM_SCORE_CONSTRUCTION":
        raise IntradayMechanismError("spec is not frozen before score construction")
    if list(spec["mechanisms"]) != spec["compression_priority"]:
        raise IntradayMechanismError("mechanism identity/order mismatch")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise IntradayMechanismError(f"{name} identity mismatch")
        output[name] = path
    return output


def _component_names(spec: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        component
        for mechanism in spec["mechanisms"].values()
        for side in ("positive", "negative")
        for component in mechanism[side]
    ))


def _source_names(spec: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys([*_component_names(spec), *spec["external_controls"]]))


def _raw_field(descriptor: str, quantile: str) -> str:
    return f"{descriptor}__{quantile}"


def _pit_field(descriptor: str, quantile: str) -> str:
    return f"{descriptor}__{quantile}__pit_3y_pct"


def _score_field(mechanism: str, quantile: str, aggregator: str = "mean") -> str:
    return f"{mechanism}__{quantile}__aligned_{aggregator}"


def _loo_field(mechanism: str, quantile: str, omitted: str) -> str:
    return f"{mechanism}__{quantile}__loo_{omitted}"


def _relative_field(mechanism: str) -> str:
    return f"{mechanism}__relative_to_all"


def _rank_field(name: str) -> str:
    return f"{name}__relative_view_rank_pct"


def causal_rolling_percentile(
    values: pd.Series, window: int = 756, min_history: int = 504
) -> pd.Series:
    output = np.full(len(values), np.nan, dtype=float)
    ordered: list[float] = []
    raw = values.to_numpy(dtype=float)
    for position, value in enumerate(raw):
        if np.isfinite(value):
            bisect.insort(ordered, float(value))
        expired_position = position - window
        if expired_position >= 0 and np.isfinite(raw[expired_position]):
            expired = float(raw[expired_position])
            removal = bisect.bisect_left(ordered, expired)
            if removal >= len(ordered) or ordered[removal] != expired:
                raise IntradayMechanismError("rolling percentile state lost exact value")
            ordered.pop(removal)
        if np.isfinite(value) and len(ordered) >= min_history:
            left = bisect.bisect_left(ordered, float(value))
            right = bisect.bisect_right(ordered, float(value))
            output[position] = (left + right + 1.0) / (2.0 * len(ordered))
    return pd.Series(output, index=values.index, dtype=float)


def load_bound_input(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    result = json.loads(paths["minute_result"].read_text(encoding="utf-8"))
    accepted = set(result["minimal_nonredundant_level_roles"])
    required = set(_source_names(spec))
    if not required.issubset(accepted):
        raise IntradayMechanismError("a fixed component/control is not an accepted level role")
    if result["decision"] != "COMPLETE_LEVEL_REPRESENTATIONS_FROZEN_FIVE_DAY_TRAJECTORY_PRIMARIES_FAIL":
        raise IntradayMechanismError("minute source decision changed")
    if result["outcome_fields_read"]:
        raise IntradayMechanismError("minute source outcome boundary changed")
    if result["hashes"]["daily_panel_sha256"] != spec["inputs"]["minute_daily_panel"][
        "sha256"
    ]:
        raise IntradayMechanismError("minute result/panel identity mismatch")

    raw_fields = [
        _raw_field(descriptor, quantile)
        for descriptor in _source_names(spec)
        for quantile in QUANTILES
    ]
    panel = pd.read_csv(
        paths["minute_daily_panel"],
        usecols=[
            *KEYS,
            "available_at",
            "daily_population_count",
            "descriptor_count",
            "descriptor_coverage",
            "hard_valid",
            *raw_fields,
        ],
    )
    population = spec["population"]
    if len(panel) != population["expected_rows"] or panel.duplicated(KEYS).any():
        raise IntradayMechanismError("source row/key identity mismatch")
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    if str(panel["trade_date"].min().date()) != population["date_start"]:
        raise IntradayMechanismError("source start changed")
    if str(panel["trade_date"].max().date()) != population["date_end"]:
        raise IntradayMechanismError("source end changed")
    available = pd.to_datetime(panel["available_at"], errors="raise")
    if not (available.dt.strftime("%H:%M:%S") == "15:30:00").all():
        raise IntradayMechanismError("derived availability is not exact 15:30")
    if not (available.dt.date == panel["trade_date"].dt.date).all():
        raise IntradayMechanismError("derived availability date mismatch")
    if not panel["hard_valid"].all():
        raise IntradayMechanismError("source includes non-hard-valid market rows")
    counts = panel.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not (counts == population["expected_rows_per_group"]).all():
        raise IntradayMechanismError("source group population mismatch")
    if set(panel["market_view"]) != set(population["views"]):
        raise IntradayMechanismError("source view identity mismatch")
    if set(panel["denominator"]) != set(population["denominators"]):
        raise IntradayMechanismError("source denominator identity mismatch")
    return panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)


def construct_scores(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.copy()
    normalization = spec["causal_normalization"]
    raw_names = _source_names(spec)
    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for descriptor in raw_names:
            for quantile in QUANTILES:
                item[_pit_field(descriptor, quantile)] = causal_rolling_percentile(
                    item[_raw_field(descriptor, quantile)],
                    window=int(normalization["window_sessions"]),
                    min_history=int(normalization["minimum_valid_observations"]),
                )
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(
        ["trade_date", "denominator", "market_view"]
    )
    for mechanism, definition in spec["mechanisms"].items():
        signs = {component: 1.0 for component in definition["positive"]}
        signs.update({component: -1.0 for component in definition["negative"]})
        if len(signs) != 4:
            raise IntradayMechanismError(f"mechanism does not have four unique components: {mechanism}")
        for quantile in QUANTILES:
            aligned: dict[str, pd.Series] = {}
            for component, sign in signs.items():
                values = out[_pit_field(component, quantile)]
                aligned[component] = values if sign > 0 else 1.0 - values
            matrix = pd.DataFrame(aligned, index=out.index)
            out[_score_field(mechanism, quantile, "mean")] = matrix.mean(axis=1, skipna=False)
            out[_score_field(mechanism, quantile, "median")] = matrix.median(axis=1, skipna=False)
            out[_score_field(mechanism, quantile, "geometric_mean")] = np.power(
                matrix.prod(axis=1, skipna=False), 1.0 / 4.0
            )
            for omitted in signs:
                out[_loo_field(mechanism, quantile, omitted)] = matrix.drop(
                    columns=omitted
                ).mean(axis=1, skipna=False)
        primary = _score_field(mechanism, "median", "mean")
        all_values = out.loc[
            out["market_view"] == "ALL_A", ["trade_date", "denominator", primary]
        ].rename(columns={primary: "_all_score"})
        out = out.merge(
            all_values, on=["trade_date", "denominator"], how="left", validate="many_to_one"
        )
        out[_relative_field(mechanism)] = out[primary] - out["_all_score"]
        counts = out.groupby(["trade_date", "denominator"])[primary].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[primary].rank(
            method="average", pct=True
        )
        out[_rank_field(mechanism)] = ranks.where(counts == 4)
        out = out.drop(columns="_all_score")
    for control in spec["external_controls"]:
        primary = _pit_field(control, "median")
        counts = out.groupby(["trade_date", "denominator"])[primary].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[primary].rank(
            method="average", pct=True
        )
        out[_rank_field(control)] = ranks.where(counts == 4)
    return out.sort_values(KEYS).reset_index(drop=True)


def _spearman(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def _within_group_spearman(panel: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    by_group: dict[str, float] = {}
    for (view, denominator), group in panel.groupby(
        ["market_view", "denominator"], sort=True
    ):
        value = _spearman(group[left], group[right])
        if not np.isfinite(value):
            raise IntradayMechanismError(f"undefined stability correlation: {left}:{right}")
        by_group[f"{view}:{denominator}"] = value
    return {
        "by_group": by_group,
        "median_across_groups": float(np.median(np.asarray(list(by_group.values())))),
        "minimum_across_groups": float(np.min(np.asarray(list(by_group.values())))),
    }


def _denominator_stability(panel: pd.DataFrame, field: str) -> dict[str, Any]:
    by_view: dict[str, float] = {}
    for view, group in panel.groupby("market_view", sort=True):
        pivot = group.pivot(index="trade_date", columns="denominator", values=field)
        value = _spearman(pivot["ALL_STATUS"], pivot["NON_ST"])
        if not np.isfinite(value):
            raise IntradayMechanismError(f"undefined denominator stability: {field}:{view}")
        by_view[str(view)] = value
    return {
        "by_view": by_view,
        "median_across_views": float(np.median(np.asarray(list(by_view.values())))),
    }


def _year_cells(panel: pd.DataFrame, field: str, spec: dict[str, Any]) -> dict[str, Any]:
    eligible = panel.loc[panel["trade_date"].dt.year.isin(spec["gates"]["eligible_years"])].copy()
    eligible["year"] = eligible["trade_date"].dt.year
    cells: dict[str, Any] = {}
    all_pass = True
    for (view, denominator, year), group in eligible.groupby(
        ["market_view", "denominator", "year"], sort=True
    ):
        clean = group[field].replace([np.inf, -np.inf], np.nan).dropna()
        passed = (
            len(clean) >= spec["gates"]["minimum_group_year_observations"]
            and clean.nunique() > 1
        )
        cells[f"{view}:{denominator}:{year}"] = {
            "n": int(len(clean)),
            "nondegenerate": bool(clean.nunique() > 1),
            "pass": bool(passed),
        }
        all_pass = all_pass and passed
    if len(cells) != 24:
        raise IntradayMechanismError("eligible mechanism cell count changed")
    return {"cells": cells, "all_cells_pass": bool(all_pass)}


def representation_diagnostics(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    gates = spec["gates"]
    for mechanism, definition in spec["mechanisms"].items():
        components = [*definition["positive"], *definition["negative"]]
        raw_coverages = {
            component: float(
                panel[_raw_field(component, "median")].replace([np.inf, -np.inf], np.nan).notna().mean()
            )
            for component in components
        }
        primary = _score_field(mechanism, "median", "mean")
        shape_neighbors = {
            aggregator: _within_group_spearman(
                panel, primary, _score_field(mechanism, "median", aggregator)
            )
            for aggregator in ("median", "geometric_mean")
        }
        loo_neighbors = {
            component: _within_group_spearman(
                panel, primary, _loo_field(mechanism, "median", component)
            )
            for component in components
        }
        cross_section_neighbors = {
            quantile: _within_group_spearman(
                panel, primary, _score_field(mechanism, quantile, "mean")
            )
            for quantile in ("p40", "p60")
        }
        denominator = _denominator_stability(panel, primary)
        cells = _year_cells(panel, primary, spec)
        primary_valid = panel[primary].notna()
        relative_expected = primary_valid & (panel["market_view"] != "ALL_A")
        relative_coverage = float(
            panel.loc[relative_expected, _relative_field(mechanism)].notna().mean()
        )
        rank_coverage = float(panel.loc[primary_valid, _rank_field(mechanism)].notna().mean())
        checks = {
            "source_coverage": min(raw_coverages.values()) >= gates["minimum_source_raw_coverage"],
            "shape_stability": min(
                item["median_across_groups"] for item in shape_neighbors.values()
            ) >= gates["minimum_shape_neighbor_median_spearman"],
            "leave_one_out_stability": min(
                item["median_across_groups"] for item in loo_neighbors.values()
            ) >= gates["minimum_leave_one_component_out_median_spearman"],
            "cross_section_stability": min(
                item["median_across_groups"] for item in cross_section_neighbors.values()
            ) >= gates["minimum_cross_section_neighbor_median_spearman"],
            "denominator_stability": denominator["median_across_views"] >= gates[
                "minimum_denominator_median_spearman"
            ],
            "year_cells": cells["all_cells_pass"],
            "relative_coverage": relative_coverage >= 0.95,
            "rank_coverage": rank_coverage >= 0.95,
        }
        output[mechanism] = {
            "raw_coverage_by_component": raw_coverages,
            "shape_neighbors": shape_neighbors,
            "leave_one_out_neighbors": loo_neighbors,
            "cross_section_neighbors": cross_section_neighbors,
            "denominator_stability": denominator,
            "year_cells": cells,
            "relative_coverage": relative_coverage,
            "relative_rank_coverage": rank_coverage,
            "checks": checks,
            "representation_gate_pass": bool(all(checks.values())),
        }
    return output


def _adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> tuple[float, int]:
    clean = frame[[target, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    observations = len(clean)
    parameters = len(controls)
    if observations <= parameters + 2:
        return float("nan"), observations
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    design = np.column_stack([np.ones(observations), ranked[:, 1:]])
    fitted = design @ np.linalg.lstsq(design, ranked[:, 0], rcond=None)[0]
    residual = float(np.square(ranked[:, 0] - fitted).sum())
    total = float(np.square(ranked[:, 0] - ranked[:, 0].mean()).sum())
    if total == 0.0:
        return float("nan"), observations
    r2 = 1.0 - residual / total
    adjusted = 1.0 - (1.0 - r2) * (observations - 1.0) / (observations - parameters - 1.0)
    return float(adjusted), observations


def external_geometry(
    panel: pd.DataFrame, spec: dict[str, Any], representations: dict[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    gates = spec["gates"]
    eligible = panel.loc[panel["trade_date"].dt.year.isin(gates["eligible_years"])].copy()
    for mechanism in spec["mechanisms"]:
        if not representations[mechanism]["representation_gate_pass"]:
            output[mechanism] = {
                "eligible": False,
                "external_gate_pass": False,
                "reason": "representation_gate_failed",
            }
            continue
        target_pit = _score_field(mechanism, "median", "mean")
        target_rank = _rank_field(mechanism)
        pairwise: dict[str, Any] = {"pit": {}, "relative_rank": {}}
        for control in spec["external_controls"]:
            pit = _within_group_spearman(eligible, target_pit, _pit_field(control, "median"))
            relative = _within_group_spearman(eligible, target_rank, _rank_field(control))
            pairwise["pit"][control] = pit
            pairwise["relative_rank"][control] = relative
        joint: dict[str, Any] = {}
        for coordinate, target, controls in (
            (
                "pit",
                target_pit,
                [_pit_field(control, "median") for control in spec["external_controls"]],
            ),
            (
                "relative_rank",
                target_rank,
                [_rank_field(control) for control in spec["external_controls"]],
            ),
        ):
            estimates: dict[str, float] = {}
            support: dict[str, int] = {}
            group_columns = ["market_view", "denominator"] if coordinate == "pit" else ["denominator"]
            for group_key, group in eligible.groupby(group_columns, sort=True):
                adjusted, observations = _adjusted_rank_r2(group, target, controls)
                if observations < 150 or not np.isfinite(adjusted):
                    raise IntradayMechanismError(
                        f"external joint support failed: {mechanism}:{coordinate}:{group_key}:{observations}"
                    )
                name = ":".join(group_key) if isinstance(group_key, tuple) else str(group_key)
                estimates[name] = adjusted
                support[name] = observations
            values = np.asarray(list(estimates.values()), dtype=float)
            joint[coordinate] = {
                "by_group": estimates,
                "support_by_group": support,
                "median_adjusted_r2": float(np.median(values)),
                "maximum_adjusted_r2": float(np.max(values)),
            }
        max_pairwise = max(
            abs(item["median_across_groups"])
            for coordinate in pairwise.values()
            for item in coordinate.values()
        )
        checks = {
            "pairwise_distinct": max_pairwise < gates[
                "pairwise_external_redundancy_absolute_spearman"
            ],
            "joint_pit_distinct": joint["pit"]["median_adjusted_r2"] < gates[
                "joint_rank_reconstruction_median_adjusted_r2_maximum"
            ] and joint["pit"]["maximum_adjusted_r2"] < gates[
                "joint_rank_reconstruction_maximum_adjusted_r2"
            ],
            "joint_relative_distinct": joint["relative_rank"]["median_adjusted_r2"] < gates[
                "joint_rank_reconstruction_median_adjusted_r2_maximum"
            ] and joint["relative_rank"]["maximum_adjusted_r2"] < gates[
                "joint_rank_reconstruction_maximum_adjusted_r2"
            ],
        }
        output[mechanism] = {
            "eligible": True,
            "pairwise": pairwise,
            "maximum_pairwise_median_absolute_spearman": float(max_pairwise),
            "joint_reconstruction": joint,
            "checks": checks,
            "external_gate_pass": bool(all(checks.values())),
        }
    return output


def compress_mechanisms(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    representations: dict[str, Any],
    external: dict[str, Any],
) -> dict[str, Any]:
    eligible = [
        mechanism
        for mechanism in spec["compression_priority"]
        if representations[mechanism]["representation_gate_pass"]
        and external[mechanism]["external_gate_pass"]
    ]
    correlations: dict[str, Any] = {}
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    threshold = spec["gates"]["mechanism_pairwise_compression_absolute_spearman"]
    for mechanism in eligible:
        blockers: list[str] = []
        for prior in accepted:
            pit = _within_group_spearman(
                panel,
                _score_field(mechanism, "median", "mean"),
                _score_field(prior, "median", "mean"),
            )["median_across_groups"]
            relative = _within_group_spearman(
                panel, _rank_field(mechanism), _rank_field(prior)
            )["median_across_groups"]
            pair = f"{prior}|{mechanism}"
            correlations[pair] = {"pit": pit, "relative_rank": relative}
            if max(abs(pit), abs(relative)) >= threshold:
                blockers.append(prior)
        if blockers:
            excluded[mechanism] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(mechanism)
    for mechanism in spec["compression_priority"]:
        if mechanism not in eligible and mechanism not in excluded:
            if not representations[mechanism]["representation_gate_pass"]:
                excluded[mechanism] = "representation_gate_failed"
            else:
                excluded[mechanism] = "external_geometry_failed"
    return {
        "eligible_before_internal_compression": eligible,
        "pairwise_correlations": correlations,
        "accepted_mechanisms": accepted,
        "excluded_mechanisms": excluded,
    }


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-MIN-SUPACC-001 same-session intraday mechanisms",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        "- Source: frozen required-scale daily minute panel; no raw minute rescan.",
        "- Availability: 15:30 Asia/Shanghai after the completed 15:00 bar.",
        "- Future values, strategy outcomes, failed paths, post-2023 data, and CY-011 read: **none**.",
        "- Scores are OHLCV-derived state representations, not cross-day support, participant accumulation, prediction, or rules.",
        "",
        "## Mechanism gates",
        "",
        "| Mechanism | Shape worst | LOO worst | p40/p60 worst | Denominator rho | External max rho | Representation | External | Minimal |",
        "|---|---:|---:|---:|---:|---:|---|---|---|",
    ]
    accepted = set(result["compression"]["accepted_mechanisms"])
    for mechanism in spec["compression_priority"]:
        representation = result["representation_diagnostics"][mechanism]
        external = result["external_geometry"][mechanism]
        shape = min(item["median_across_groups"] for item in representation["shape_neighbors"].values())
        loo = min(item["median_across_groups"] for item in representation["leave_one_out_neighbors"].values())
        cross = min(item["median_across_groups"] for item in representation["cross_section_neighbors"].values())
        external_rho = external.get("maximum_pairwise_median_absolute_spearman")
        external_text = "NA" if external_rho is None else f"{external_rho:.3f}"
        lines.append(
            f"| `{mechanism}` | {shape:.3f} | {loo:.3f} | {cross:.3f} | "
            f"{representation['denominator_stability']['median_across_views']:.3f} | "
            f"{external_text} | {'PASS' if representation['representation_gate_pass'] else 'FAIL'} | "
            f"{'PASS' if external['external_gate_pass'] else 'FAIL'} | "
            f"{'YES' if mechanism in accepted else 'NO'} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    source = load_bound_input(spec)
    panel = construct_scores(source, spec)
    representations = representation_diagnostics(panel, spec)
    external = external_geometry(panel, spec, representations)
    compression = compress_mechanisms(panel, spec, representations, external)

    source_fields = [
        _raw_field(descriptor, quantile)
        for descriptor in _source_names(spec)
        for quantile in QUANTILES
    ]
    pit_fields = [
        _pit_field(descriptor, quantile)
        for descriptor in _source_names(spec)
        for quantile in QUANTILES
    ]
    score_fields: list[str] = []
    for mechanism, definition in spec["mechanisms"].items():
        components = [*definition["positive"], *definition["negative"]]
        for quantile in QUANTILES:
            score_fields.extend(
                _score_field(mechanism, quantile, aggregator)
                for aggregator in ("mean", "median", "geometric_mean")
            )
            score_fields.extend(_loo_field(mechanism, quantile, item) for item in components)
        score_fields.extend([_relative_field(mechanism), _rank_field(mechanism)])
    control_rank_fields = [_rank_field(control) for control in spec["external_controls"]]
    output = panel[[
        *KEYS,
        "available_at",
        "daily_population_count",
        "descriptor_count",
        "descriptor_coverage",
        "hard_valid",
        *source_fields,
        *pit_fields,
        *score_fields,
        *control_rank_fields,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    accepted = compression["accepted_mechanisms"]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(accepted)}_OF_{len(spec['mechanisms'])}_MINIMAL_MECHANISMS",
        "usefulness_claim": "NONE",
        "cross_day_support_claim": "NONE",
        "participant_accumulation_claim": "NONE",
        "future_state_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_level_roles_read": [],
        "failed_path_roles_read": [],
        "raw_minute_rows_read": False,
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "rows": int(len(source)),
            "groups": int(source.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(source["trade_date"].min().date()),
            "last_date": str(source["trade_date"].max().date()),
            "minimum_descriptor_coverage": float(source["descriptor_coverage"].min()),
        },
        "representation_diagnostics": representations,
        "external_geometry": external,
        "compression": compression,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "minute_daily_panel_sha256": spec["inputs"]["minute_daily_panel"]["sha256"],
            "minute_result_sha256": spec["inputs"]["minute_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result, spec), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "compression": completed["compression"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
