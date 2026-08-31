#!/usr/bin/env python3
"""Reproduce the exploratory dispersion-to-opportunity association."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-ECON-001_spec.json"
AUDIT_PATH = PROGRAM / "artifacts/MKT-DISP-ECON-001_cell_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-ECON-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-ECON-001_dispersion_opportunity.md"
EXPECTED_SPEC_SHA256 = "cb369d1edf7e8574cdbe6f9c95b37b91e2c546bae27f38e366c93f84beb6b543"

KEYS = ["trade_date", "market_view", "denominator"]
PRIMARY_RAW = "industry_return_dispersion_iqr"
PRIMARY_PIT = "industry_return_dispersion_iqr_pit_3y_pct"
NEIGHBORS = ["industry_return_dispersion_p90_p10", "industry_return_dispersion_mad"]
CONTROLS = [
    "realized_volatility_median20_pit_3y_pct",
    "correlation_median20_pit_3y_pct",
    "median_signed_limit_utilization_pit_3y_pct",
    "breadth_net_new_high_low60_pit_3y_pct",
]


class DispersionExploreError(RuntimeError):
    """Fail-closed exploratory dispersion error."""


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
    if pd.isna(value):
        return None
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionExploreError("exploratory reproduction spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("experiment_id") != "MKT-DISP-ECON-001"
        or spec.get("research_level") != "EXPLORE"
        or spec.get("status") != "POST_DISCOVERY_REPRODUCTION_CONTRACT"
    ):
        raise DispersionExploreError("exploratory honesty boundary changed")
    if "inspected before" not in spec.get("honesty_boundary", ""):
        raise DispersionExploreError("post-discovery disclosure is absent")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionExploreError(f"bound input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    for phrase in ("same-bar execution", "post-2023", "CY-011"):
        if phrase not in forbidden:
            raise DispersionExploreError(f"missing prohibited boundary: {phrase}")
    return spec


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    industry_result = json.loads(
        _resolve(spec["inputs"]["industry_result"]["path"]).read_text(encoding="utf-8")
    )
    geometry_result = json.loads(
        _resolve(spec["inputs"]["geometry_result"]["path"]).read_text(encoding="utf-8")
    )
    response_result = json.loads(
        _resolve(spec["inputs"]["response_result"]["path"]).read_text(encoding="utf-8")
    )
    if industry_result.get("status") != "COMPLETE_8_OF_11_ROLES_PASS_7_MINIMAL":
        raise DispersionExploreError("industry representation is not activated")
    if "industry_return_dispersion_1d" not in geometry_result.get("compression", {}).get(
        "distinct_engine_coordinates", []
    ):
        raise DispersionExploreError("industry dispersion is not a distinct engine coordinate")
    if response_result.get("status") != "COMPLETE_RESPONSE_DOMAIN_ADEQUACY":
        raise DispersionExploreError("future response domain is not activated")

    industry = pd.read_csv(
        _resolve(spec["inputs"]["industry_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    industry_columns = [
        *KEYS,
        "decision_at",
        "available_at",
        PRIMARY_RAW,
        PRIMARY_PIT,
        *NEIGHBORS,
    ]
    geometry = pd.read_csv(
        _resolve(spec["inputs"]["geometry_panel"]["path"]),
        parse_dates=["trade_date"],
    )[[*KEYS, "geometry_decision_at", *CONTROLS]]
    response = pd.read_csv(
        _resolve(spec["inputs"]["response_panel"]["path"]),
        parse_dates=["trade_date", "response_date_h1", "response_date_h3", "response_date_h5"],
    )
    panel = industry[industry_columns].merge(
        geometry, on=KEYS, how="inner", validate="one_to_one"
    ).merge(response, on=KEYS, how="inner", validate="one_to_one", suffixes=("_state", "_response"))
    panel = panel.loc[
        panel["response_complete"] & panel.trade_date.le(pd.Timestamp("2023-12-29"))
    ].copy()
    population = spec["population"]
    if len(panel) != population["expected_complete_rows"]:
        raise DispersionExploreError("complete response row count changed")
    if panel.trade_date.nunique() != population["expected_complete_dates"]:
        raise DispersionExploreError("complete response date count changed")
    if panel.trade_date.min().strftime("%Y-%m-%d") != population["expected_first_date"]:
        raise DispersionExploreError("first response date changed")
    if panel.trade_date.max().strftime("%Y-%m-%d") != population["expected_last_complete_date"]:
        raise DispersionExploreError("last complete response date changed")
    observed_cells = set(map(tuple, panel[["market_view", "denominator"]].drop_duplicates().to_numpy()))
    expected_cells = {
        (view, denominator)
        for view in population["views"]
        for denominator in population["denominators"]
    }
    if observed_cells != expected_cells:
        raise DispersionExploreError("governed cell population changed")

    for horizon in (1, 3, 5):
        if not panel[f"response_date_h{horizon}"].gt(panel.trade_date).all():
            raise DispersionExploreError(f"future response h{horizon} is not strictly after t")
        panel[f"opportunity_spread_h{horizon}"] = (
            panel[f"terminal_p90_log_return_h{horizon}"]
            - panel[f"terminal_p10_log_return_h{horizon}"]
        )
        if not panel[f"opportunity_spread_h{horizon}"].ge(0).all():
            raise DispersionExploreError(f"negative response spread at h{horizon}")
    if panel.trade_date.dt.year.max() > 2023:
        raise DispersionExploreError("post-2023 row reached exploratory analysis")
    pit = panel.dropna(subset=[PRIMARY_PIT, *CONTROLS])
    if len(pit) != population["expected_pit_rows"]:
        raise DispersionExploreError("PIT complete row count changed")
    if pit.trade_date.min().strftime("%Y-%m-%d") != population["expected_first_pit_date"]:
        raise DispersionExploreError("first causal PIT date changed")
    cell_support = pit.groupby(KEYS[1:]).size()
    if (
        cell_support.min() != population["minimum_expected_pit_rows_per_cell"]
        or cell_support.max() != population["maximum_expected_pit_rows_per_cell"]
    ):
        raise DispersionExploreError("PIT per-cell support changed")
    for column in [PRIMARY_RAW, PRIMARY_PIT, *NEIGHBORS, *CONTROLS]:
        if not np.isfinite(pit[column].to_numpy(dtype=float)).all():
            raise DispersionExploreError(f"nonfinite required state field: {column}")
    panel["calendar_year"] = panel.trade_date.dt.year
    panel["session_ordinal"] = panel.groupby(KEYS[1:], sort=False).cumcount()
    support = {
        "complete_rows": len(panel),
        "complete_dates": int(panel.trade_date.nunique()),
        "pit_rows": len(pit),
        "minimum_pit_rows_per_cell": int(cell_support.min()),
        "maximum_pit_rows_per_cell": int(cell_support.max()),
        "first_date": panel.trade_date.min().strftime("%Y-%m-%d"),
        "last_complete_date": panel.trade_date.max().strftime("%Y-%m-%d"),
        "first_pit_date": pit.trade_date.min().strftime("%Y-%m-%d"),
        "cells": len(observed_cells),
    }
    return panel.sort_values(KEYS).reset_index(drop=True), support


def _spearman(frame: pd.DataFrame, predictor: str, response: str) -> tuple[float, int]:
    data = frame[[predictor, response]].dropna().to_numpy(dtype=float)
    if len(data) < 20:
        return float("nan"), len(data)
    return float(spearmanr(data[:, 0], data[:, 1]).statistic), len(data)


def _partial(frame: pd.DataFrame, predictor: str, response: str) -> tuple[float, int]:
    data = frame[[predictor, response, *CONTROLS]].dropna().to_numpy(dtype=float)
    if len(data) < 20:
        return float("nan"), len(data)
    ranked = np.column_stack([rankdata(data[:, index]) for index in range(data.shape[1])])
    design = np.column_stack([np.ones(len(ranked)), ranked[:, 2:]])
    x_residual = ranked[:, 0] - design @ np.linalg.lstsq(design, ranked[:, 0], rcond=None)[0]
    y_residual = ranked[:, 1] - design @ np.linalg.lstsq(design, ranked[:, 1], rcond=None)[0]
    return float(np.corrcoef(x_residual, y_residual)[0, 1]), len(data)


def _cell_rows(
    frame: pd.DataFrame,
    scope: str,
    predictor: str,
    response: str,
    estimator: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    function = _partial if estimator == "partial_spearman" else _spearman
    for (view, denominator), cell in frame.groupby(KEYS[1:], sort=True):
        estimate, count = function(cell, predictor, response)
        rows.append(
            {
                "scope": scope,
                "market_view": view,
                "denominator": denominator,
                "predictor": predictor,
                "response": response,
                "estimator": estimator,
                "estimate": estimate,
                "observations": count,
            }
        )
    return rows


def _median_estimate(rows: list[dict[str, Any]]) -> float:
    return float(np.nanmedian([row["estimate"] for row in rows]))


def _analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit_rows: list[dict[str, Any]] = []
    primary: dict[str, Any] = {"horizons": {}}
    for horizon in (1, 3, 5):
        response = f"opportunity_spread_h{horizon}"
        raw_rows = _cell_rows(panel, f"h{horizon}", PRIMARY_RAW, response, "spearman")
        pit_rows = _cell_rows(panel, f"h{horizon}", PRIMARY_PIT, response, "spearman")
        partial_rows = _cell_rows(panel, f"h{horizon}", PRIMARY_PIT, response, "partial_spearman")
        audit_rows.extend(raw_rows + pit_rows + partial_rows)
        primary["horizons"][str(horizon)] = {
            "median_cell_raw_rho": _median_estimate(raw_rows),
            "median_cell_pit_rho": _median_estimate(pit_rows),
            "median_cell_partial_rho": _median_estimate(partial_rows),
            "positive_partial_cells": sum(row["estimate"] > 0 for row in partial_rows),
            "cell_partial_rhos": [row["estimate"] for row in partial_rows],
        }

    neighbor_summary: dict[str, Any] = {}
    for predictor in NEIGHBORS:
        rows = _cell_rows(panel, "h3_neighbor", predictor, "opportunity_spread_h3", "spearman")
        audit_rows.extend(rows)
        neighbor_summary[predictor] = {
            "median_cell_raw_rho": _median_estimate(rows),
            "positive_cells": sum(row["estimate"] > 0 for row in rows),
        }

    pit_panel = panel.dropna(subset=[PRIMARY_PIT, *CONTROLS]).copy()
    raw_years: dict[str, Any] = {}
    for year, annual in panel.groupby("calendar_year", sort=True):
        rows = _cell_rows(annual, f"raw_year_{year}", PRIMARY_RAW, "opportunity_spread_h3", "spearman")
        audit_rows.extend(rows)
        raw_years[str(year)] = _median_estimate(rows)
    pit_years: dict[str, Any] = {}
    for year, annual in pit_panel.groupby("calendar_year", sort=True):
        rows = _cell_rows(
            annual, f"pit_year_{year}", PRIMARY_PIT, "opportunity_spread_h3", "partial_spearman"
        )
        audit_rows.extend(rows)
        pit_years[str(year)] = _median_estimate(rows)
    leave_one_year_out: dict[str, Any] = {}
    for year in sorted(pit_panel.calendar_year.unique()):
        rows = _cell_rows(
            pit_panel.loc[pit_panel.calendar_year.ne(year)],
            f"loyo_{year}",
            PRIMARY_PIT,
            "opportunity_spread_h3",
            "partial_spearman",
        )
        audit_rows.extend(rows)
        leave_one_year_out[str(year)] = _median_estimate(rows)

    phases: dict[str, Any] = {}
    for horizon in (3, 5):
        response = f"opportunity_spread_h{horizon}"
        phase_values: dict[str, float] = {}
        for phase in range(horizon):
            subset = pit_panel.loc[pit_panel.session_ordinal.mod(horizon).eq(phase)]
            rows = _cell_rows(
                subset,
                f"h{horizon}_phase_{phase}",
                PRIMARY_PIT,
                response,
                "partial_spearman",
            )
            audit_rows.extend(rows)
            phase_values[str(phase)] = _median_estimate(rows)
        phases[str(horizon)] = phase_values

    diagnostics: dict[str, Any] = {}
    diagnostic_responses = [
        "terminal_p90_log_return_h3",
        "terminal_p10_log_return_h3",
        "terminal_mean_log_return_h3",
        "terminal_positive_fraction_h3",
        "adverse_mean_log_excursion_h3",
    ]
    for response in diagnostic_responses:
        pit_rows = _cell_rows(panel, "h3_diagnostic", PRIMARY_PIT, response, "spearman")
        partial_rows = _cell_rows(
            panel, "h3_diagnostic", PRIMARY_PIT, response, "partial_spearman"
        )
        audit_rows.extend(pit_rows + partial_rows)
        diagnostics[response] = {
            "median_cell_pit_rho": _median_estimate(pit_rows),
            "median_cell_partial_rho": _median_estimate(partial_rows),
        }

    tail_gaps: list[float] = []
    for _, cell in pit_panel.groupby(KEYS[1:], sort=True):
        high = cell.loc[cell[PRIMARY_PIT].ge(0.8), "opportunity_spread_h3"]
        low = cell.loc[cell[PRIMARY_PIT].le(0.2), "opportunity_spread_h3"]
        if len(high) < 20 or len(low) < 20:
            raise DispersionExploreError("insufficient fixed-tail support")
        tail_gaps.append(float(high.mean() - low.mean()))

    screen = spec["exploratory_candidate_screen"]
    checks = {
        "all_primary_cells_positive": primary["horizons"]["3"]["positive_partial_cells"]
        >= screen["minimum_positive_primary_cells"],
        "primary_partial_magnitude": primary["horizons"]["3"]["median_cell_partial_rho"]
        >= screen["minimum_median_primary_partial_rho"],
        "all_pit_years_positive": all(value > 0 for value in pit_years.values()),
        "neighbor_horizons_positive": all(
            primary["horizons"][str(horizon)]["median_cell_partial_rho"] > 0
            for horizon in (1, 5)
        ),
        "neighbor_definitions_positive": all(
            value["median_cell_raw_rho"] > 0 for value in neighbor_summary.values()
        ),
        "h3_nonoverlap_phases_positive": all(value > 0 for value in phases["3"].values()),
    }
    candidate = all(checks.values())
    result = {
        "experiment_id": "MKT-DISP-ECON-001",
        "research_level": "EXPLORE",
        "classification": (
            "EXPLORE_CANDIDATE_DISPERSION_OPPORTUNITY_PERSISTENCE"
            if candidate
            else "EXPLORE_NO_DISPERSION_OPPORTUNITY_CANDIDATE"
        ),
        "candidate_screen": {"pass": candidate, "checks": checks},
        "primary": primary,
        "neighbor_definitions": neighbor_summary,
        "raw_year_median_cell_rhos": raw_years,
        "pit_year_median_cell_partial_rhos": pit_years,
        "leave_one_pit_year_out_median_cell_partial_rhos": leave_one_year_out,
        "nonoverlap_phase_median_cell_partial_rhos": phases,
        "h3_tail_contrast": {
            "median_cell_high80_minus_low20_opportunity_spread": float(np.median(tail_gaps)),
            "cell_gaps": tail_gaps,
        },
        "tail_and_direction_decomposition": diagnostics,
        "interpretation": {
            "mechanism_candidate": "current cross-industry disagreement precedes a wider security-level opportunity distribution",
            "directional_market_timing_supported": False,
            "realizable_long_short_return_estimated": False,
            "strategy_archetype_candidate": "cross-sectional dispersion / relative-value opportunity harvesting",
            "strategy_authorized": False,
            "required_next_level": "separately frozen PROMOTE test with fixed construction, execution, costs, capacity, and untouched time",
        },
        "honesty_boundary": spec["honesty_boundary"],
        "future_response_used_as_predictor": False,
        "same_bar_fill_assumed": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
    }
    audit = pd.DataFrame(audit_rows).sort_values(
        ["scope", "predictor", "response", "estimator", "market_view", "denominator"]
    )
    return audit.reset_index(drop=True), result


def _render_report(result: dict[str, Any], support: dict[str, Any]) -> str:
    primary = result["primary"]["horizons"]
    diagnostic = result["tail_and_direction_decomposition"]
    return f"""# MKT-DISP-ECON-001 exploratory dispersion opportunity result

## Outcome

`{result['classification']}`. This is a post-discovery `EXPLORE` result, not a
preregistered promotion or confirmation. The disclosure is durable: the primary
association was inspected before the reproduction contract was written.

Current one-session cross-industry return dispersion precedes a wider future
security-return distribution. Median eight-cell causal-PIT Spearman at h=3 is
{primary['3']['median_cell_pit_rho']:.6f}; after fixed realized-volatility,
co-movement, central-direction, and discovery-breadth controls it is
{primary['3']['median_cell_partial_rho']:.6f}. All eight cells are positive.
The controlled neighboring h=1/h=5 estimates are
{primary['1']['median_cell_partial_rho']:.6f}/{primary['5']['median_cell_partial_rho']:.6f}.

The h=3 high-PIT-versus-low-PIT opportunity-width gap is
{result['h3_tail_contrast']['median_cell_high80_minus_low20_opportunity_spread']:.6f}
log-return units. Both neighboring absolute dispersion definitions are positive.
Every supported PIT year, leave-one-year-out view, and h=3 non-overlap phase is
positive.

## Mechanism boundary

The distribution widens on both sides: the controlled h=3 upper-tail/lower-tail
associations are {diagnostic['terminal_p90_log_return_h3']['median_cell_partial_rho']:.6f}
and {diagnostic['terminal_p10_log_return_h3']['median_cell_partial_rho']:.6f}.
The controlled market-mean association is
{diagnostic['terminal_mean_log_return_h3']['median_cell_partial_rho']:.6f}, so
the result is opportunity-set widening rather than directional market timing.
The adverse-excursion diagnostic is
{diagnostic['adverse_mean_log_excursion_h3']['median_cell_partial_rho']:.6f};
dispersion expansion includes additional downside risk.

## Contract and limits

The analysis contains {support['complete_rows']:,} complete rows across
{support['cells']} governed cells and {support['pit_rows']:,} causal-PIT rows.
State is available at t 15:00; every response begins strictly after t. No
security ranking, portfolio, PnL, transaction cost, capacity, strategy outcome,
post-2023 row, or CY-011 field was read. Opportunity width is not a realizable
long-short payoff. A cross-sectional dispersion/relative-value archetype becomes
a candidate for separately frozen research only; no strategy is authorized.
"""


def main() -> None:
    spec = _load_spec()
    panel, support = _load_panel(spec)
    audit, result = _analyze(panel, spec)
    audit_text = audit.to_csv(index=False, float_format="%.12g", lineterminator="\n")
    _atomic_write(AUDIT_PATH, audit_text)
    result["support"] = support
    result["hashes"] = {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "input_sha256": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        "cell_audit_sha256": sha256_file(AUDIT_PATH),
    }
    result_text = json.dumps(_clean(result), indent=2, sort_keys=True) + "\n"
    _atomic_write(RESULT_PATH, result_text)
    _atomic_write(REPORT_PATH, _render_report(result, support))


if __name__ == "__main__":
    main()
