#!/usr/bin/env python3
"""Falsify same-session market absorption/distribution representations."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-AD-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-AD-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-AD-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-AD-001_representation.md"
EXPECTED_SPEC_SHA256 = "311391c7ae487f3a041a2c31ed9d209cd730dc7de919305dcaeba6de7c0d2506"
KEYS = ["trade_date", "market_view", "denominator"]
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_min_supacc_001.py"
MODULE_SPEC = importlib.util.spec_from_file_location("run_mkt_min_supacc_001_parent", PARENT_RUNNER)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load frozen intraday-mechanism runner")
parent = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(parent)


class IntradayAbsorptionDistributionError(RuntimeError):
    """Fail-closed MKT-MIN-AD-001 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise IntradayAbsorptionDistributionError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_ABSORPTION_DISTRIBUTION_SCORE_CONSTRUCTION"
        or list(spec["hypotheses"]) != spec["compression_priority"]
    ):
        raise IntradayAbsorptionDistributionError("frozen activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise IntradayAbsorptionDistributionError(f"input identity mismatch: {name}")
    minute = json.loads(_resolve(spec["inputs"]["minute_result"]["path"]).read_text())
    required = {
        component
        for definition in spec["hypotheses"].values()
        for side in ("positive", "negative")
        for component in definition[side]
    } | set(spec["external_controls"]["raw_accepted_levels"])
    if (
        not required.issubset(set(minute["minimal_nonredundant_level_roles"]))
        or minute["outcome_fields_read"]
    ):
        raise IntradayAbsorptionDistributionError("minute source activation changed")
    defense = json.loads(_resolve(spec["inputs"]["vwap_defense_result"]["path"]).read_text())
    if (
        defense["compression"]["accepted_mechanisms"] != ["vwap_defense_recovery"]
        or defense["usefulness_claim"] != "NONE"
        or defense["future_state_fields_read"]
        or defense["strategy_or_outcome_fields_read"]
        or defense["raw_minute_rows_read"]
        or defense["cy011_read"]
    ):
        raise IntradayAbsorptionDistributionError("VWAP-defense activation changed")
    return spec


def _core_spec(spec: dict[str, Any]) -> dict[str, Any]:
    core = dict(spec)
    core["mechanisms"] = spec["hypotheses"]
    core["external_controls"] = spec["external_controls"]["raw_accepted_levels"]
    return core


def _load_defense(spec: dict[str, Any]) -> pd.DataFrame:
    fields = spec["external_controls"]["accepted_score"]
    panel = pd.read_csv(
        _resolve(spec["inputs"]["vwap_defense_panel"]["path"]),
        usecols=[*KEYS, fields["pit_field"], fields["relative_rank_field"]],
    )
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    if len(panel) != spec["population"]["expected_rows"] or panel.duplicated(KEYS).any():
        raise IntradayAbsorptionDistributionError("VWAP-defense panel population changed")
    return panel


def construct_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    core = _core_spec(spec)
    source = parent.load_bound_input(core)
    scored = parent.construct_scores(source, core)
    defense = _load_defense(spec)
    scored = scored.merge(defense, on=KEYS, how="left", validate="one_to_one")
    fields = spec["external_controls"]["accepted_score"]
    if scored[[fields["pit_field"], fields["relative_rank_field"]]].isna().all().any():
        raise IntradayAbsorptionDistributionError("VWAP-defense controls unavailable")
    return source, scored


def _external_geometry(
    panel: pd.DataFrame, spec: dict[str, Any], representations: dict[str, Any]
) -> dict[str, Any]:
    gates = spec["gates"]
    eligible = panel.loc[panel["trade_date"].dt.year.isin(gates["eligible_years"])]
    raw_controls = spec["external_controls"]["raw_accepted_levels"]
    accepted = spec["external_controls"]["accepted_score"]
    control_fields = {
        "pit": [
            *[parent._pit_field(control, "median") for control in raw_controls],
            accepted["pit_field"],
        ],
        "relative_rank": [
            *[parent._rank_field(control) for control in raw_controls],
            accepted["relative_rank_field"],
        ],
    }
    control_names = [*raw_controls, accepted["name"]]
    output: dict[str, Any] = {}
    for hypothesis in spec["hypotheses"]:
        if not representations[hypothesis]["representation_gate_pass"]:
            output[hypothesis] = {
                "eligible": False,
                "external_gate_pass": False,
                "reason": "representation_gate_failed",
            }
            continue
        targets = {
            "pit": parent._score_field(hypothesis, "median", "mean"),
            "relative_rank": parent._rank_field(hypothesis),
        }
        pairwise: dict[str, Any] = {"pit": {}, "relative_rank": {}}
        for coordinate in pairwise:
            for name, control in zip(control_names, control_fields[coordinate], strict=True):
                pairwise[coordinate][name] = parent._within_group_spearman(
                    eligible, targets[coordinate], control
                )
        joint: dict[str, Any] = {}
        for coordinate, target in targets.items():
            estimates: dict[str, float] = {}
            support: dict[str, int] = {}
            group_columns = (
                ["market_view", "denominator"] if coordinate == "pit" else ["denominator"]
            )
            for group_key, group in eligible.groupby(group_columns, sort=True):
                adjusted, observations = parent._adjusted_rank_r2(
                    group, target, control_fields[coordinate]
                )
                if observations < 150 or not np.isfinite(adjusted):
                    raise IntradayAbsorptionDistributionError(
                        f"external support failed: {hypothesis}:{coordinate}:"
                        f"{group_key}:{observations}"
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
            "pairwise_distinct": max_pairwise
            < gates["pairwise_external_redundancy_absolute_spearman"],
            "joint_pit_distinct": joint["pit"]["median_adjusted_r2"]
            < gates["joint_rank_reconstruction_median_adjusted_r2_maximum"]
            and joint["pit"]["maximum_adjusted_r2"]
            < gates["joint_rank_reconstruction_maximum_adjusted_r2"],
            "joint_relative_distinct": joint["relative_rank"]["median_adjusted_r2"]
            < gates["joint_rank_reconstruction_median_adjusted_r2_maximum"]
            and joint["relative_rank"]["maximum_adjusted_r2"]
            < gates["joint_rank_reconstruction_maximum_adjusted_r2"],
        }
        output[hypothesis] = {
            "eligible": True,
            "pairwise": pairwise,
            "maximum_pairwise_median_absolute_spearman": float(max_pairwise),
            "joint_reconstruction": joint,
            "checks": checks,
            "external_gate_pass": bool(all(checks.values())),
        }
    return output


def _compress(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    representations: dict[str, Any],
    external: dict[str, Any],
) -> dict[str, Any]:
    eligible = [
        hypothesis
        for hypothesis in spec["compression_priority"]
        if representations[hypothesis]["representation_gate_pass"]
        and external[hypothesis]["external_gate_pass"]
    ]
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    correlations: dict[str, Any] = {}
    threshold = spec["gates"]["hypothesis_pairwise_compression_absolute_spearman"]
    for hypothesis in eligible:
        blockers: list[str] = []
        for prior in accepted:
            pit = parent._within_group_spearman(
                panel,
                parent._score_field(hypothesis, "median", "mean"),
                parent._score_field(prior, "median", "mean"),
            )["median_across_groups"]
            relative = parent._within_group_spearman(
                panel, parent._rank_field(hypothesis), parent._rank_field(prior)
            )["median_across_groups"]
            correlations[f"{prior}|{hypothesis}"] = {
                "pit": pit,
                "relative_rank": relative,
            }
            if max(abs(pit), abs(relative)) >= threshold:
                blockers.append(prior)
        if blockers:
            excluded[hypothesis] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(hypothesis)
    for hypothesis in spec["compression_priority"]:
        if hypothesis not in eligible and hypothesis not in excluded:
            excluded[hypothesis] = (
                "representation_gate_failed"
                if not representations[hypothesis]["representation_gate_pass"]
                else "external_geometry_failed"
            )
    return {
        "eligible_before_internal_compression": eligible,
        "pairwise_correlations": correlations,
        "accepted_hypotheses": accepted,
        "excluded_hypotheses": excluded,
    }


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    accepted = set(result["compression"]["accepted_hypotheses"])
    lines = [
        "# MKT-MIN-AD-001 intraday absorption/distribution falsification",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        "- Source: frozen daily minute descriptors available at 15:30; raw minute "
        "rows were not reopened.",
        "- Labels are OHLCV effort-versus-result hypotheses, not participant intent "
        "or cross-day processes.",
        "- Future values, strategy outcomes, post-2023 data, and CY-011 read: **none**.",
        "",
        "## Fixed gates",
        "",
        "| Hypothesis | Shape | LOO | p40/p60 | Denominator | External rho | PIT R2 | "
        "Relative R2 | Minimal |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for hypothesis in spec["compression_priority"]:
        representation = result["representation_diagnostics"][hypothesis]
        external = result["external_geometry"][hypothesis]
        shape = min(
            item["median_across_groups"] for item in representation["shape_neighbors"].values()
        )
        loo = min(
            item["median_across_groups"]
            for item in representation["leave_one_out_neighbors"].values()
        )
        cross = min(
            item["median_across_groups"]
            for item in representation["cross_section_neighbors"].values()
        )
        if external["eligible"]:
            rho = f"{external['maximum_pairwise_median_absolute_spearman']:.3f}"
            pit_r2 = f"{external['joint_reconstruction']['pit']['median_adjusted_r2']:.3f}"
            relative_r2 = (
                f"{external['joint_reconstruction']['relative_rank']['median_adjusted_r2']:.3f}"
            )
        else:
            rho = pit_r2 = relative_r2 = "NA"
        lines.append(
            f"| {hypothesis} | {shape:.3f} | {loo:.3f} | {cross:.3f} | "
            f"{representation['denominator_stability']['median_across_views']:.3f} | "
            f"{rho} | {pit_r2} | {relative_r2} | "
            f"{'YES' if hypothesis in accepted else 'NO'} |"
        )
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Runner SHA-256: `{result['hashes']['runner_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    core = _core_spec(spec)
    source, panel = construct_panel(spec)
    representations = parent.representation_diagnostics(panel, core)
    external = _external_geometry(panel, spec, representations)
    compression = _compress(panel, spec, representations, external)

    components = parent._component_names(core)
    raw_controls = spec["external_controls"]["raw_accepted_levels"]
    source_names = list(dict.fromkeys([*components, *raw_controls]))
    fields: list[str] = [
        *KEYS,
        "available_at",
        "daily_population_count",
        "descriptor_count",
        "descriptor_coverage",
        "hard_valid",
    ]
    fields.extend(
        parent._raw_field(descriptor, quantile)
        for descriptor in source_names
        for quantile in parent.QUANTILES
    )
    fields.extend(
        parent._pit_field(descriptor, quantile)
        for descriptor in source_names
        for quantile in parent.QUANTILES
    )
    for hypothesis, definition in spec["hypotheses"].items():
        hypothesis_components = [*definition["positive"], *definition["negative"]]
        for quantile in parent.QUANTILES:
            fields.extend(
                parent._score_field(hypothesis, quantile, aggregator)
                for aggregator in ("mean", "median", "geometric_mean")
            )
            fields.extend(
                parent._loo_field(hypothesis, quantile, component)
                for component in hypothesis_components
            )
        fields.extend([parent._relative_field(hypothesis), parent._rank_field(hypothesis)])
    fields.extend(parent._rank_field(control) for control in raw_controls)
    defense = spec["external_controls"]["accepted_score"]
    fields.extend([defense["pit_field"], defense["relative_rank_field"]])
    output = panel[list(dict.fromkeys(fields))].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    accepted = compression["accepted_hypotheses"]
    result = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(accepted)}_OF_2_MINIMAL_REPRESENTATIONS",
        "usefulness_claim": "NONE",
        "participant_accumulation_distribution_claim": "NONE",
        "cross_day_process_claim": "NONE",
        "future_state_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "raw_minute_rows_read": 0,
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "rows": len(source),
            "groups": source.groupby(["market_view", "denominator"]).ngroups,
            "first_date": str(source["trade_date"].min().date()),
            "last_date": str(source["trade_date"].max().date()),
            "minimum_descriptor_coverage": float(source["descriptor_coverage"].min()),
        },
        "representation_diagnostics": representations,
        "external_geometry": external,
        "compression": compression,
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "runner_sha256": sha256_file(Path(__file__)),
            "minute_daily_panel_sha256": spec["inputs"]["minute_daily_panel"]["sha256"],
            "vwap_defense_panel_sha256": spec["inputs"]["vwap_defense_panel"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    cleaned = parent._clean(result)
    RESULT_PATH.write_text(
        json.dumps(cleaned, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(cleaned, spec), encoding="utf-8")
    return cleaned


if __name__ == "__main__":
    final = run()
    print(
        json.dumps(
            {
                "status": final["status"],
                "compression": final["compression"],
                "panel_sha256": final["hashes"]["panel_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
