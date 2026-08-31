#!/usr/bin/env python3
"""Run fixed cheap incremental robustness for market-state screen survivors."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import rankdata

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-STATE-ROBUST-001_spec.json"
AUDIT_PATH = PROGRAM / "artifacts/MKT-STATE-ROBUST-001_partial_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STATE-ROBUST-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STATE-ROBUST-001_incremental_robustness.md"
EXPECTED_SPEC_SHA256 = "65f1014b2ce6ca4dcff49e5f6618dc378b05cf1f03f9ca652a1c59e2ca974f0e"

KEYS = ["trade_date", "market_view", "denominator"]


class MarketStateRobustnessError(RuntimeError):
    """Fail-closed incremental robustness error."""


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
        raise MarketStateRobustnessError("robustness spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("research_level") != "EXPLORE_ROBUSTNESS"
        or spec.get("status") != "FROZEN_BEFORE_INCREMENTAL_ESTIMATION"
    ):
        raise MarketStateRobustnessError("robustness contract changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MarketStateRobustnessError(f"bound input identity mismatch: {name}")
    screen = json.loads(_resolve(spec["inputs"]["screen_result"]["path"]).read_text())
    if screen.get("status") != "COMPLETE_DISCLOSED_CHEAP_MARKET_STATE_ECONOMIC_SCREEN":
        raise MarketStateRobustnessError("cheap screen is not activated")
    selected = {item["candidate_id"] for item in spec["fixed_candidates"]}
    if selected != set(screen.get("passing_candidate_ids", [])):
        raise MarketStateRobustnessError("robustness candidates differ from screen survivors")
    prohibited = "|".join(spec["prohibited_computations"])
    for phrase in ("same-bar execution", "post-2023", "CY-011"):
        if phrase not in prohibited:
            raise MarketStateRobustnessError(f"missing prohibited boundary: {phrase}")
    return spec


def _load_panel(spec: dict[str, Any]) -> pd.DataFrame:
    population = spec["population"]
    response = pd.read_csv(
        _resolve(spec["inputs"]["response_panel"]["path"]),
        usecols=[
            *KEYS,
            "response_complete",
            "response_date_h3",
            "response_date_h5",
            "terminal_mean_log_return_h5",
            "terminal_p10_log_return_h3",
            "terminal_p90_log_return_h3",
            "adverse_mean_log_excursion_h3",
        ],
        parse_dates=["trade_date", "response_date_h3", "response_date_h5"],
    )
    response = response.loc[
        response.response_complete
        & response.trade_date.between(
            pd.Timestamp(population["expected_first_date"]),
            pd.Timestamp(population["expected_last_complete_date"]),
        )
    ].copy()
    response["opportunity_spread_h3"] = (
        response.terminal_p90_log_return_h3 - response.terminal_p10_log_return_h3
    )
    if len(response) != population["expected_complete_rows"]:
        raise MarketStateRobustnessError("response population changed")
    for horizon in (3, 5):
        if not response[f"response_date_h{horizon}"].gt(response.trade_date).all():
            raise MarketStateRobustnessError(f"h{horizon} response is not future-only")

    required = {
        field
        for candidate in spec["fixed_candidates"]
        for field in [candidate["predictor"], *candidate["controls"]]
    }
    liquidity = {
        "liquidity_turnover_median_pit_3y_pct",
        "liquidity_median_amount_ratio20_pit_3y_pct",
    }
    geometry_columns = sorted(required - liquidity)
    geometry = pd.read_csv(
        _resolve(spec["inputs"]["geometry_panel"]["path"]),
        usecols=[*KEYS, "geometry_decision_at", *geometry_columns],
        parse_dates=["trade_date"],
    )
    correlation_liquidity = pd.read_csv(
        _resolve(spec["inputs"]["correlation_liquidity_panel"]["path"]),
        usecols=[*KEYS, "decision_at", "available_at", *sorted(required & liquidity)],
        parse_dates=["trade_date"],
    )
    if geometry.duplicated(KEYS).any() or correlation_liquidity.duplicated(KEYS).any():
        raise MarketStateRobustnessError("duplicate state key")
    if not geometry.geometry_decision_at.str.contains("T15:00:00+08:00", regex=False).all():
        raise MarketStateRobustnessError("geometry decision timestamp changed")
    if not correlation_liquidity.available_at.eq(correlation_liquidity.decision_at).all():
        raise MarketStateRobustnessError("liquidity state availability changed")
    panel = response.merge(geometry, on=KEYS, validate="one_to_one").merge(
        correlation_liquidity, on=KEYS, validate="one_to_one"
    )
    if len(panel) != population["expected_complete_rows"]:
        raise MarketStateRobustnessError("state/response merge coverage changed")
    if panel.trade_date.dt.year.max() > 2023:
        raise MarketStateRobustnessError("post-2023 row reached robustness analysis")
    panel["calendar_year"] = panel.trade_date.dt.year
    panel["session_ordinal"] = panel.groupby(KEYS[1:], sort=False).cumcount()
    complete = panel.dropna(subset=sorted(required))
    if len(complete) != population["expected_pit_rows"]:
        raise MarketStateRobustnessError("complete PIT row count changed")
    if complete.trade_date.min().strftime("%Y-%m-%d") != population["expected_first_pit_date"]:
        raise MarketStateRobustnessError("first PIT date changed")
    support = complete.groupby(KEYS[1:]).size()
    if support.min() < population["minimum_pit_rows_per_cell"] or len(support) != 8:
        raise MarketStateRobustnessError("PIT cell support changed")
    return panel.sort_values(KEYS).reset_index(drop=True)


def _partial(
    frame: pd.DataFrame, predictor: str, response: str, controls: list[str]
) -> tuple[float, int]:
    columns = [predictor, response, *controls]
    data = frame[columns].dropna().to_numpy(dtype=float)
    if len(data) < 20:
        return float("nan"), len(data)
    if not np.isfinite(data).all():
        raise MarketStateRobustnessError(f"nonfinite partial input: {predictor}/{response}")
    ranked = np.column_stack([rankdata(data[:, index]) for index in range(data.shape[1])])
    design = np.column_stack([np.ones(len(ranked)), ranked[:, 2:]])
    x_residual = ranked[:, 0] - design @ np.linalg.lstsq(design, ranked[:, 0], rcond=None)[0]
    y_residual = ranked[:, 1] - design @ np.linalg.lstsq(design, ranked[:, 1], rcond=None)[0]
    return float(np.corrcoef(x_residual, y_residual)[0, 1]), len(data)


def _cell_rows(
    frame: pd.DataFrame,
    candidate: dict[str, Any],
    scope: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (view, denominator), cell in frame.groupby(KEYS[1:], sort=True):
        estimate, observations = _partial(
            cell, candidate["predictor"], candidate["response"], candidate["controls"]
        )
        rows.append(
            {
                "candidate_id": candidate["candidate_id"],
                "scope": scope,
                "market_view": view,
                "denominator": denominator,
                "estimate": estimate,
                "observations": observations,
            }
        )
    return rows


def _median(rows: list[dict[str, Any]]) -> float:
    return float(np.nanmedian([row["estimate"] for row in rows]))


def _same_sign(value: float, expected_sign: int) -> bool:
    return math.isfinite(value) and value * expected_sign > 0


def _analyze(spec: dict[str, Any], panel: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    audit: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    gate = spec["survival_gate"]
    blocks = spec["estimator"]["temporal_blocks"]
    for candidate in spec["fixed_candidates"]:
        expected_sign = int(candidate["expected_sign"])
        full_rows = _cell_rows(panel, candidate, "full")
        audit.extend(full_rows)
        full_rho = _median(full_rows)
        same_sign_cells = sum(
            _same_sign(float(row["estimate"]), expected_sign) for row in full_rows
        )
        block_values: dict[str, float] = {}
        for name, years in blocks.items():
            rows = _cell_rows(
                panel.loc[panel.calendar_year.isin(years)], candidate, f"block_{name}"
            )
            audit.extend(rows)
            block_values[name] = _median(rows)
        phase_values: dict[str, float] = {}
        horizon = int(candidate["horizon"])
        for phase in range(horizon):
            rows = _cell_rows(
                panel.loc[panel.session_ordinal.mod(horizon).eq(phase)],
                candidate,
                f"phase_{phase}",
            )
            audit.extend(rows)
            phase_values[str(phase)] = _median(rows)
        required_phases = gate[f"minimum_same_sign_nonoverlap_phases_h{horizon}"]
        checks = {
            "partial_magnitude": abs(full_rho)
            >= gate["minimum_absolute_median_cell_partial_rho"],
            "cell_sign": same_sign_cells >= gate["minimum_same_sign_cells"],
            "both_blocks_same_sign": all(
                _same_sign(value, expected_sign) for value in block_values.values()
            ),
            "nonoverlap_phase_sign": sum(
                _same_sign(value, expected_sign) for value in phase_values.values()
            )
            >= required_phases,
        }
        results.append(
            {
                "candidate_id": candidate["candidate_id"],
                "predictor": candidate["predictor"],
                "response": candidate["response"],
                "controls": candidate["controls"],
                "median_cell_partial_rho": full_rho,
                "same_sign_cells": same_sign_cells,
                "block_partial_rhos": block_values,
                "nonoverlap_phase_partial_rhos": phase_values,
                "checks": checks,
                "survives_incremental_robustness": all(checks.values()),
            }
        )
    results.sort(key=lambda item: abs(item["median_cell_partial_rho"]), reverse=True)
    for rank, item in enumerate(results, 1):
        item["rank_by_absolute_partial_rho"] = rank
        item["funnel_status"] = (
            "ROBUSTNESS" if item["survives_incremental_robustness"] else "PARKED"
        )
    survivors = [item for item in results if item["survives_incremental_robustness"]]
    return pd.DataFrame(audit), {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_CHEAP_INCREMENTAL_ROBUSTNESS",
        "classification": (
            "SURVIVORS_REQUIRE_EXECUTABLE_TRANSLATION_OR_DISTINCTNESS_TEST"
            if survivors
            else "NO_CHEAP_SCREEN_CANDIDATE_SURVIVES_INCREMENTAL_CONTROLS"
        ),
        "selection_boundary": spec["selection_boundary"],
        "support": {
            "complete_rows": spec["population"]["expected_complete_rows"],
            "pit_rows": spec["population"]["expected_pit_rows"],
            "cells": 8,
            "first_pit_date": spec["population"]["expected_first_pit_date"],
            "last_complete_date": spec["population"]["expected_last_complete_date"],
        },
        "ranked_candidates": results,
        "survivor_ids": [item["candidate_id"] for item in survivors],
        "next_stage": (
            "For directional survivors, freeze the simplest t+1 executable broad-market translation. "
            "For opportunity-habitat survivors, test distinctness from current dispersion before "
            "resource-gated security ranking."
        ),
        "claim_boundary": {
            "independent_confirmation": False,
            "strategy_supported": False,
            "pnl_estimated": False,
            "same_bar_fill_assumed": False,
            "future_response_used_as_predictor": False,
            "post_2023_read": False,
            "cy011_read": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {name: value["sha256"] for name, value in spec["inputs"].items()},
        },
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-STATE-ROBUST-001 — cheap incremental robustness",
        "",
        "## Outcome",
        "",
        "| Rank | Candidate | Partial rho | Cells | Early | Late | Status |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for item in result["ranked_candidates"]:
        blocks = item["block_partial_rhos"]
        lines.append(
            f"| {item['rank_by_absolute_partial_rho']} | {item['candidate_id']} | "
            f"{item['median_cell_partial_rho']:.6f} | {item['same_sign_cells']}/8 | "
            f"{blocks['early']:.6f} | {blocks['late']:.6f} | {item['funnel_status']} |"
        )
    lines.extend(
        [
            "",
            "This is sequential exploratory robustness. It does not authorize a signal, fill, "
            "portfolio, P&L claim, or strategy change.",
            "",
            "## Next decision",
            "",
            result["next_stage"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    spec = _load_spec()
    panel = _load_panel(spec)
    audit, result = _analyze(spec, panel)
    audit = audit.sort_values(
        ["candidate_id", "scope", "market_view", "denominator"]
    ).reset_index(drop=True)
    _atomic_write(AUDIT_PATH, audit.to_csv(index=False, lineterminator="\n", float_format="%.12g"))
    result["hashes"]["partial_audit_sha256"] = sha256_file(AUDIT_PATH)
    _atomic_write(REPORT_PATH, _render_report(result))
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
