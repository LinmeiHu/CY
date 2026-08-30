#!/usr/bin/env python3
"""Frozen continuous minute-volatility forward-response experiment."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-MIN-VOL-RESP-002_spec.json"
PARENT_SPEC_PATH = PROGRAM / "experiments/MKT-MIN-VOL-RESP-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-RESP-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-MIN-VOL-RESP-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-MIN-VOL-RESP-002_response.md"
EXPECTED_SPEC_SHA256 = "9ef7a0b2aff42a9bded178d63d1f3bca2ae1dad033d8d30378adf490fa51a2d9"
EXPECTED_PARENT_SPEC_SHA256 = "595f2ec5b92150d9cc3533104b3a0ce11a82271938cd3e90716ef640dff863a9"
KEYS = ["trade_date", "market_view", "denominator"]


class MinuteVolatilityResponseError(RuntimeError):
    """Fail-closed temporal-response error."""


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
        raise MinuteVolatilityResponseError("spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if sha256_file(PARENT_SPEC_PATH) != EXPECTED_PARENT_SPEC_SHA256:
        raise MinuteVolatilityResponseError("parent scientific design identity mismatch")
    if control["inherits_scientific_design_sha256"] != EXPECTED_PARENT_SPEC_SHA256:
        raise MinuteVolatilityResponseError("control parent identity mismatch")
    spec = json.loads(PARENT_SPEC_PATH.read_text(encoding="utf-8"))
    spec["experiment_id"] = control["experiment_id"]
    spec["status"] = control["status"]
    spec["outputs"] = control["outputs"]
    spec["response"]["domain_rule"] = control["only_semantic_correction"]["response_domain"]
    spec["controls_domain_rule"] = control["only_semantic_correction"]["current_log_control_domain"]
    if spec["status"] != "FROZEN_BEFORE_FORWARD_RESPONSE_CONSTRUCTION":
        raise MinuteVolatilityResponseError("spec is not frozen before response")
    return spec


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for name in ("geometry_panel", "geometry_result", "daily_minute_panel", "daily_minute_result"):
        entry = spec["inputs"][name]
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise MinuteVolatilityResponseError(f"{name} identity mismatch")
        paths[name] = path
    return paths


def _validate_results(paths: dict[str, Path]) -> None:
    geometry = json.loads(paths["geometry_result"].read_text(encoding="utf-8"))
    if geometry["status"] != "COMPLETE_DISTINCT_PATH_COORDINATE":
        raise MinuteVolatilityResponseError("distinct geometry prerequisite failed")
    minute = json.loads(paths["daily_minute_result"].read_text(encoding="utf-8"))
    expected = sha256_file(paths["daily_minute_panel"])
    if minute["hashes"]["daily_panel_sha256"] != expected:
        raise MinuteVolatilityResponseError("daily minute result/panel lineage mismatch")


def load_bound_inputs(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = _input_paths(spec)
    _validate_results(paths)
    geometry_columns = [
        *KEYS, "geometry_decision_at", "available_at_path", "hard_valid",
        spec["predictor"]["field"], *spec["controls"],
    ]
    daily_columns = [*KEYS, "available_at", "hard_valid", spec["response"]["source_field"]]
    geometry = pd.read_csv(paths["geometry_panel"], usecols=geometry_columns)
    daily = pd.read_csv(paths["daily_minute_panel"], usecols=daily_columns)
    for name, frame in (("geometry", geometry), ("daily", daily)):
        if frame.duplicated(KEYS).any():
            raise MinuteVolatilityResponseError(f"duplicate {name} keys")
        frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    if not geometry["hard_valid"].astype(bool).all() or not daily["hard_valid"].astype(bool).all():
        raise MinuteVolatilityResponseError("invalid row entered response construction")
    if geometry["trade_date"].max() > pd.Timestamp(spec["inputs"]["date_end"]):
        raise MinuteVolatilityResponseError("post-cutoff predictor row")
    decision = pd.to_datetime(geometry["geometry_decision_at"], utc=True, errors="raise").dt.tz_convert(
        "Asia/Shanghai"
    )
    if not (decision.dt.strftime("%H:%M:%S") == "15:30:00").all():
        raise MinuteVolatilityResponseError("predictor decision time is not exact 15:30")
    if len(geometry) != 10696 or geometry.groupby(["market_view", "denominator"]).ngroups != 8:
        raise MinuteVolatilityResponseError("geometry population mismatch")
    return geometry.sort_values(KEYS).reset_index(drop=True), daily.sort_values(KEYS).reset_index(drop=True)


def construct_forward_responses(
    geometry: pd.DataFrame, daily: pd.DataFrame, spec: dict[str, Any]
) -> pd.DataFrame:
    level_field = spec["response"]["source_field"]
    daily = daily.copy()
    daily[level_field] = pd.to_numeric(daily[level_field], errors="coerce")

    current = daily[[*KEYS, level_field]].rename(columns={level_field: "lineage_current_minute_level"})
    panel = geometry.merge(current, on=KEYS, how="left", validate="one_to_one")
    bound_level = pd.to_numeric(panel[spec["controls"][0]], errors="coerce")
    lineage_level = panel["lineage_current_minute_level"]
    lineage_equal = (bound_level == lineage_level) | (bound_level.isna() & lineage_level.isna())
    if not lineage_equal.all():
        raise MinuteVolatilityResponseError("current minute-volatility level lineage mismatch")
    panel["control_log_current_minute_level"] = np.nan
    positive_current = np.isfinite(bound_level) & (bound_level > 0.0)
    panel.loc[positive_current, "control_log_current_minute_level"] = np.log(
        bound_level.loc[positive_current]
    )

    ordered = daily.sort_values(["market_view", "denominator", "trade_date"]).copy()
    grouped = ordered.groupby(["market_view", "denominator"], sort=False)
    for horizon in spec["response"]["horizons_sessions"]:
        ordered[f"response_date_h{horizon}"] = grouped["trade_date"].shift(-horizon)
        ordered[f"future_level_h{horizon}"] = grouped[level_field].shift(-horizon)
        ordered[f"future_log_change_h{horizon}"] = np.nan
        valid_domain = (
            np.isfinite(ordered[level_field])
            & np.isfinite(ordered[f"future_level_h{horizon}"])
            & (ordered[level_field] > 0.0)
            & (ordered[f"future_level_h{horizon}"] > 0.0)
        )
        ordered.loc[valid_domain, f"future_log_change_h{horizon}"] = np.log(
            ordered.loc[valid_domain, f"future_level_h{horizon}"]
            / ordered.loc[valid_domain, level_field]
        )
    response_columns = [*KEYS]
    for horizon in spec["response"]["horizons_sessions"]:
        response_columns.extend([
            f"response_date_h{horizon}", f"future_level_h{horizon}", f"future_log_change_h{horizon}"
        ])
    panel = panel.merge(ordered[response_columns], on=KEYS, how="left", validate="one_to_one")
    for horizon in spec["response"]["horizons_sessions"]:
        date_field = f"response_date_h{horizon}"
        valid = panel[date_field].notna()
        if not (panel.loc[valid, date_field] > panel.loc[valid, "trade_date"]).all():
            raise MinuteVolatilityResponseError(f"nonfuture response at h={horizon}")
        panel[f"response_available_at_h{horizon}"] = panel[date_field].dt.strftime(
            "%Y-%m-%dT15:30:00+08:00"
        )
    return panel.sort_values(KEYS).reset_index(drop=True)


def _spearman(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def partial_rank_correlation(frame: pd.DataFrame, target: str, outcome: str, controls: list[str]) -> float:
    clean = frame[[target, outcome, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(controls) + 3:
        return float("nan")
    ranked = clean.rank(method="average")
    design = np.column_stack([np.ones(len(ranked)), ranked[controls].to_numpy(float)])
    left = ranked[target].to_numpy(float)
    right = ranked[outcome].to_numpy(float)
    left_residual = left - design @ np.linalg.lstsq(design, left, rcond=None)[0]
    right_residual = right - design @ np.linalg.lstsq(design, right, rcond=None)[0]
    if np.std(left_residual) == 0.0 or np.std(right_residual) == 0.0:
        return float("nan")
    return float(np.corrcoef(left_residual, right_residual)[0, 1])


def _block_mask(panel: pd.DataFrame, bounds: list[str]) -> pd.Series:
    return panel["trade_date"].between(pd.Timestamp(bounds[0]), pd.Timestamp(bounds[1]))


def _group_estimates(
    panel: pd.DataFrame,
    spec: dict[str, Any],
    block: str,
    horizon: int,
    nonoverlap: bool,
) -> dict[str, Any]:
    predictor = spec["predictor"]["field"]
    outcome = f"future_log_change_h{horizon}"
    controls = ["control_log_current_minute_level", *spec["controls"][1:]]
    block_panel = panel.loc[_block_mask(panel, spec["temporal_blocks"][block])].copy()
    output: dict[str, Any] = {}
    partials: list[float] = []
    for (view, denominator), group in block_panel.groupby(["market_view", "denominator"], sort=True):
        columns = [predictor, outcome, *controls]
        clean = group.sort_values("trade_date").replace([np.inf, -np.inf], np.nan).dropna(subset=columns)
        if nonoverlap:
            clean = clean.iloc[::horizon].copy()
        raw = _spearman(clean[predictor], clean[outcome])
        partial = partial_rank_correlation(clean, predictor, outcome, controls)
        if not np.isfinite(raw) or not np.isfinite(partial):
            raise MinuteVolatilityResponseError(f"nonfinite estimate: {block} h={horizon}")
        output[f"{view}:{denominator}"] = {
            "n": int(len(clean)),
            "raw_spearman": raw,
            "partial_rank": partial,
        }
        partials.append(partial)
    values = np.asarray(partials, dtype=float)
    median = float(np.median(values))
    sign = int(np.sign(median))
    agreement = int((np.sign(values) == sign).sum()) if sign != 0 else 0
    return {
        "groups": output,
        "median_partial_rank": median,
        "median_absolute_partial_rank": float(np.median(np.abs(values))),
        "median_sign": sign,
        "group_sign_agreement": agreement,
        "minimum_n": min(item["n"] for item in output.values()),
    }


def _analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, bool]]:
    analyses: dict[str, Any] = {"full_sample": {}, "nonoverlap_h5": {}}
    for horizon in spec["response"]["horizons_sessions"]:
        analyses["full_sample"][f"h{horizon}"] = {
            block: _group_estimates(panel, spec, block, horizon, nonoverlap=False)
            for block in ("discovery", "confirmation")
        }
    primary = spec["response"]["primary_horizon_sessions"]
    analyses["nonoverlap_h5"] = {
        block: _group_estimates(panel, spec, block, primary, nonoverlap=True)
        for block in ("discovery", "confirmation")
    }

    gates = spec["gates"]
    coverage = True
    for horizon in spec["response"]["horizons_sessions"]:
        coverage &= analyses["full_sample"][f"h{horizon}"]["discovery"]["minimum_n"] >= gates[
            "full_sample_discovery_minimum_per_group"
        ]
        coverage &= analyses["full_sample"][f"h{horizon}"]["confirmation"]["minimum_n"] >= gates[
            "full_sample_confirmation_minimum_per_group"
        ]
    coverage &= analyses["nonoverlap_h5"]["discovery"]["minimum_n"] >= gates[
        "nonoverlap_discovery_minimum_per_group"
    ]
    coverage &= analyses["nonoverlap_h5"]["confirmation"]["minimum_n"] >= gates[
        "nonoverlap_confirmation_minimum_per_group"
    ]

    primary_discovery = analyses["full_sample"][f"h{primary}"]["discovery"]
    primary_confirmation = analyses["full_sample"][f"h{primary}"]["confirmation"]
    primary_effect = bool(
        primary_discovery["median_absolute_partial_rank"]
        >= gates["primary_block_median_absolute_partial_rho_minimum"]
        and primary_confirmation["median_absolute_partial_rank"]
        >= gates["primary_block_median_absolute_partial_rho_minimum"]
    )
    primary_sign = bool(
        primary_discovery["median_sign"] != 0
        and primary_discovery["median_sign"] == primary_confirmation["median_sign"]
    )
    primary_portability = bool(
        primary_discovery["group_sign_agreement"] >= gates["primary_group_sign_agreement_minimum_of_8"]
        and primary_confirmation["group_sign_agreement"] >= gates["primary_group_sign_agreement_minimum_of_8"]
    )
    accepted_sign = primary_discovery["median_sign"] if primary_sign else 0

    neighbors = True
    for horizon in (1, 3):
        for block in ("discovery", "confirmation"):
            item = analyses["full_sample"][f"h{horizon}"][block]
            neighbors &= item["median_absolute_partial_rank"] >= gates[
                "neighbor_block_median_absolute_partial_rho_minimum"
            ]
            neighbors &= accepted_sign != 0 and item["median_sign"] == accepted_sign

    nonoverlap = True
    for block in ("discovery", "confirmation"):
        item = analyses["nonoverlap_h5"][block]
        nonoverlap &= item["median_absolute_partial_rank"] >= gates[
            "nonoverlap_block_median_absolute_partial_rho_minimum"
        ]
        nonoverlap &= accepted_sign != 0 and item["median_sign"] == accepted_sign
        nonoverlap &= item["group_sign_agreement"] >= gates[
            "nonoverlap_group_sign_agreement_minimum_of_8"
        ]
    result_gates = {
        "coverage": bool(coverage),
        "primary_effect": primary_effect,
        "primary_sign_replication": primary_sign,
        "primary_group_portability": primary_portability,
        "neighbor_horizons": bool(neighbors),
        "nonoverlap_primary": bool(nonoverlap),
    }
    result_gates["all"] = bool(all(result_gates.values()))
    analyses["accepted_sign"] = accepted_sign
    return analyses, result_gates


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-MIN-VOL-RESP-002 continuous future-volatility response",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Predictor rows: {result['population']['rows']:,}; {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Future responses become available only at 15:30 on t+h; they are never predictors at t and create no action.",
        "- Price returns, strategy outcomes, raw minutes, failed path fields, discrete states, and CY-011 read: **none**.",
        "- Association is not causality, return prediction, habitat fitness, or a trading rule.",
        "",
        "## Partial-rank response",
        "",
        "| Horizon | Block | Median partial rho | Median absolute partial rho | Group sign agreement | Minimum n/group |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for horizon in (1, 3, 5):
        for block in ("discovery", "confirmation"):
            item = result["analyses"]["full_sample"][f"h{horizon}"][block]
            lines.append(
                f"| {horizon} | {block} | {item['median_partial_rank']:.3f} | "
                f"{item['median_absolute_partial_rank']:.3f} | {item['group_sign_agreement']}/8 | "
                f"{item['minimum_n']} |"
            )
    lines.extend([
        "",
        "## Fixed phase-zero non-overlapping h=5",
        "",
        "| Block | Median partial rho | Median absolute partial rho | Group sign agreement | Minimum n/group |",
        "|---|---:|---:|---:|---:|",
    ])
    for block in ("discovery", "confirmation"):
        item = result["analyses"]["nonoverlap_h5"][block]
        lines.append(
            f"| {block} | {item['median_partial_rank']:.3f} | {item['median_absolute_partial_rank']:.3f} | "
            f"{item['group_sign_agreement']}/8 | {item['minimum_n']} |"
        )
    lines.extend([
        "",
        "## Gates",
        "",
    ])
    for gate, passed in result["gates"].items():
        if gate != "all":
            lines.append(f"- `{gate}`: {'PASS' if passed else 'FAIL'}")
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    geometry, daily = load_bound_inputs(spec)
    panel = construct_forward_responses(geometry, daily, spec)
    analyses, gates = _analyze(panel, spec)
    status = "COMPLETE_REPLICATING_FUTURE_VOLATILITY_RESPONSE" if gates["all"] else (
        "COMPLETE_NO_REPLICATING_FUTURE_VOLATILITY_RESPONSE"
    )
    output = panel.copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    for horizon in spec["response"]["horizons_sessions"]:
        output[f"response_date_h{horizon}"] = output[f"response_date_h{horizon}"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    accepted_sign = analyses["accepted_sign"]
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "population": {
            "rows": int(len(panel)),
            "groups": int(panel.groupby(["market_view", "denominator"]).ngroups),
            "first_date": str(panel["trade_date"].min().date()),
            "last_date": str(panel["trade_date"].max().date()),
        },
        "analyses": analyses,
        "gates": gates,
        "temporal_interpretation": (
            "CONTINUATION" if gates["all"] and accepted_sign > 0 else
            "REVERSAL" if gates["all"] and accepted_sign < 0 else "NONE"
        ),
        "raw_minute_rows_read": 0,
        "future_market_price_returns_read": [],
        "failed_representation_fields_read": [],
        "discrete_state_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "cy011_read": False,
        "usefulness_claim": "FUTURE_MARKET_MINUTE_VOLATILITY_ASSOCIATION" if gates["all"] else "NONE",
        "strategy_usefulness_claim": "NONE",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "geometry_panel_sha256": spec["inputs"]["geometry_panel"]["sha256"],
            "geometry_result_sha256": spec["inputs"]["geometry_result"]["sha256"],
            "daily_minute_panel_sha256": spec["inputs"]["daily_minute_panel"]["sha256"],
            "daily_minute_result_sha256": spec["inputs"]["daily_minute_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "gates": completed["gates"],
        "temporal_interpretation": completed["temporal_interpretation"],
        "full_sample": completed["analyses"]["full_sample"],
        "nonoverlap_h5": completed["analyses"]["nonoverlap_h5"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
