#!/usr/bin/env python3
"""Reproduce exploratory CHINEXT habitat archaeology for industry dispersion."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata, spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-DISP-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-DISP-001_result.json"
AUDIT_PATH = PROGRAM / "artifacts/HAB-CHX-DISP-001_endpoint_audit.csv"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-DISP-001_archaeology.md"
EXPECTED_SPEC_SHA256 = "5852bd752b68fdc4ff8f4ba80b8cd638ca73cb52120581b7a2ad44c3685d4cb7"

STATE = "industry_return_dispersion_iqr_pit_3y_pct"
CONTROLS = [
    "A_trend_pit_3y_pct",
    "B_breadth_pit_3y_pct",
    "realized_volatility_median20_pit_3y_pct",
    "correlation_median20_pit_3y_pct",
]


class HabitatDispersionError(RuntimeError):
    """Fail-closed exploratory habitat error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise HabitatDispersionError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("research_level") != "EXPLORE"
        or spec.get("status") != "POST_DISCOVERY_REPRODUCTION_CONTRACT"
        or "inspected before" not in spec.get("honesty_boundary", "")
    ):
        raise HabitatDispersionError("exploratory honesty boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise HabitatDispersionError(f"input identity mismatch: {name}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("CHINEXT V1 rule", "post-2023", "CY-011"):
        if phrase not in prohibited:
            raise HabitatDispersionError(f"missing prohibition: {phrase}")
    return spec


def _load_panel(spec: dict[str, Any]) -> pd.DataFrame:
    habitat_result = json.loads(
        _resolve(spec["inputs"]["habitat_result"]["path"]).read_text(encoding="utf-8")
    )
    geometry_result = json.loads(
        _resolve(spec["inputs"]["geometry_result"]["path"]).read_text(encoding="utf-8")
    )
    if (
        habitat_result.get("decision")
        != "EXPLORATORY_OPPORTUNITY_AND_PAYOFF_HABITAT_ASSOCIATION"
        or habitat_result.get("strategy_rule_authorized") is not False
    ):
        raise HabitatDispersionError("consumed habitat panel is not activated")
    if "industry_return_dispersion_1d" not in geometry_result.get("compression", {}).get(
        "distinct_engine_coordinates", []
    ):
        raise HabitatDispersionError("dispersion state is not activated")
    habitat = pd.read_csv(
        _resolve(spec["inputs"]["habitat_panel"]["path"]), parse_dates=["trade_date"]
    )
    geometry = pd.read_csv(
        _resolve(spec["inputs"]["geometry_panel"]["path"]), parse_dates=["trade_date"]
    )
    geometry = geometry.loc[
        geometry.market_view.eq("CHINEXT_BOARD") & geometry.denominator.eq("ALL_STATUS"),
        ["trade_date", STATE, *CONTROLS[-2:]],
    ]
    if geometry.trade_date.duplicated().any():
        raise HabitatDispersionError("duplicate CHINEXT state date")
    panel = habitat.merge(geometry, on="trade_date", how="left", validate="many_to_one")
    if panel.trade_date.dt.year.max() > 2023:
        raise HabitatDispersionError("post-2023 row reached archaeology")
    endpoint_columns = [item for values in spec["endpoints"].values() for item in values]
    for column in endpoint_columns:
        panel[column] = pd.to_numeric(panel[column], errors="coerce")
    panel["calendar_year"] = panel.trade_date.dt.year
    for sample_type, expected in spec["expected_complete_rows"].items():
        endpoints = next(
            values
            for name, values in spec["endpoints"].items()
            if {"DAILY_PROCESS": "daily_setup", "EVALUATED_EVENT": "event_conversion", "COMPLETED_CYCLE": "cycle"}[sample_type]
            == name
        )
        complete = panel.loc[panel.sample_type.eq(sample_type)].dropna(
            subset=[STATE, *CONTROLS, *endpoints]
        )
        if len(complete) != expected:
            raise HabitatDispersionError(f"complete support changed: {sample_type}")
    return panel


def _spearman(frame: pd.DataFrame, endpoint: str) -> float:
    clean = frame[[STATE, endpoint]].dropna()
    if len(clean) < 20:
        return float("nan")
    return float(spearmanr(clean[STATE], clean[endpoint]).statistic)


def _partial(frame: pd.DataFrame, endpoint: str) -> tuple[float, int]:
    values = frame[[STATE, endpoint, *CONTROLS]].dropna().to_numpy(dtype=float)
    if len(values) < 20:
        return float("nan"), len(values)
    ranked = np.column_stack([rankdata(values[:, index]) for index in range(values.shape[1])])
    design = np.column_stack([np.ones(len(ranked)), ranked[:, 2:]])
    state_residual = ranked[:, 0] - design @ np.linalg.lstsq(
        design, ranked[:, 0], rcond=None
    )[0]
    endpoint_residual = ranked[:, 1] - design @ np.linalg.lstsq(
        design, ranked[:, 1], rcond=None
    )[0]
    return float(np.corrcoef(state_residual, endpoint_residual)[0, 1]), len(values)


def _cluster_bootstrap_return(
    cycles: pd.DataFrame, spec: dict[str, Any]
) -> tuple[float, float, float]:
    dates = np.asarray(sorted(cycles.trade_date.dropna().unique()))
    grouped = {date: cycles.loc[cycles.trade_date.eq(date)] for date in dates}
    rng = np.random.default_rng(spec["descriptive_boundaries"]["cluster_bootstrap_seed"])
    estimates: list[float] = []
    for _ in range(spec["descriptive_boundaries"]["cluster_bootstrap_draws"]):
        selected = rng.choice(dates, size=len(dates), replace=True)
        sample = pd.concat([grouped[date] for date in selected], ignore_index=True)
        estimate, _ = _partial(sample, "round_trip_return")
        estimates.append(estimate)
    low, high = np.nanquantile(estimates, [0.025, 0.975])
    return float(low), float(high), float(np.mean(np.asarray(estimates) < 0))


def _analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    endpoint_results: dict[str, Any] = {}
    sample_map = {
        "daily_setup": "DAILY_PROCESS",
        "event_conversion": "EVALUATED_EVENT",
        "cycle": "COMPLETED_CYCLE",
    }
    for family, endpoints in spec["endpoints"].items():
        sample_type = sample_map[family]
        sample = panel.loc[panel.sample_type.eq(sample_type)].copy()
        endpoint_results[family] = {}
        for endpoint in endpoints:
            raw = _spearman(sample, endpoint)
            partial, observations = _partial(sample, endpoint)
            years: dict[str, float | None] = {}
            for year, annual in sample.groupby("calendar_year", sort=True):
                estimate, count = _partial(annual, endpoint)
                if count >= 20:
                    years[str(year)] = estimate
            endpoint_results[family][endpoint] = {
                "raw_rho": raw,
                "partial_rho": partial,
                "observations": observations,
                "annual_partial_rhos": years,
            }
            rows.append(
                {
                    "family": family,
                    "sample_type": sample_type,
                    "endpoint": endpoint,
                    "raw_rho": raw,
                    "partial_rho": partial,
                    "observations": observations,
                    "annual_partial_rhos": json.dumps(_clean(years), sort_keys=True),
                }
            )
    cycles = panel.loc[panel.sample_type.eq("COMPLETED_CYCLE")].copy()
    bootstrap_low, bootstrap_high, probability_negative = _cluster_bootstrap_return(cycles, spec)
    setup_bound = spec["descriptive_boundaries"]["setup_transfer_minimum_absolute_partial_rho"]
    setup_transfer = any(
        abs(values["partial_rho"]) >= setup_bound
        for values in endpoint_results["daily_setup"].values()
    )
    payoff = endpoint_results["cycle"]["round_trip_return"]["partial_rho"]
    payoff_hint = payoff <= -spec["descriptive_boundaries"]["payoff_hint_minimum_absolute_partial_rho"]
    payoff_supported = payoff_hint and bootstrap_high < 0
    if setup_transfer:
        classification = "CHINEXT_DISPERSION_SETUP_HABITAT_CANDIDATE"
    elif payoff_supported:
        classification = "NO_CHINEXT_SETUP_TRANSFER_ADVERSE_PAYOFF_EXPLORE_ASSOCIATION"
    else:
        classification = "NO_CHINEXT_SETUP_TRANSFER_ADVERSE_PAYOFF_HINT_ONLY"
    result = {
        "experiment_id": "HAB-CHX-DISP-001",
        "research_level": "EXPLORE",
        "classification": classification,
        "endpoint_results": endpoint_results,
        "round_trip_return_cluster_bootstrap": {
            "lower_95": bootstrap_low,
            "upper_95": bootstrap_high,
            "probability_negative": probability_negative,
        },
        "interpretation": {
            "setup_transfer": setup_transfer,
            "adverse_payoff_hint": payoff_hint,
            "adverse_payoff_supported": payoff_supported,
            "chinext_rule_change": False,
            "dispersion_relative_value_candidate_changed": False,
        },
        "honesty_boundary": spec["honesty_boundary"],
        "strategy_outcomes_newly_consumed": False,
        "post_2023_read": False,
        "cy011_read": False,
    }
    return pd.DataFrame(rows), result


def _report(result: dict[str, Any]) -> str:
    daily = result["endpoint_results"]["daily_setup"]
    cycles = result["endpoint_results"]["cycle"]
    bootstrap = result["round_trip_return_cluster_bootstrap"]
    return f"""# HAB-CHX-DISP-001 exploratory archaeology

`{result['classification']}`. After fixed trend, breadth, volatility, and
co-movement controls, dispersion partial rhos for evaluated/candidate/selected
counts are {daily['evaluated_count']['partial_rho']:.4f},
{daily['candidate_count']['partial_rho']:.4f}, and
{daily['selected_count']['partial_rho']:.4f}. There is no CHINEXT setup-density
transfer.

Completed-cycle return has exploratory partial rho
{cycles['round_trip_return']['partial_rho']:.4f}, but the date-clustered 95%
interval is [{bootstrap['lower_95']:.4f}, {bootstrap['upper_95']:.4f}]. Preserve
it as a post-discovery exploratory adverse association. It does not support a veto, exposure change,
or rule. No new outcome, post-2023 row, or CY-011 field was consumed.
"""


def main() -> None:
    spec = _load_spec()
    panel = _load_panel(spec)
    audit, result = _analyze(panel, spec)
    _atomic_write(AUDIT_PATH, audit.to_csv(index=False, float_format="%.12g", lineterminator="\n"))
    result["hashes"] = {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "endpoint_audit_sha256": sha256_file(AUDIT_PATH),
        "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _report(result))


if __name__ == "__main__":
    main()
