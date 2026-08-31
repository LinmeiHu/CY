#!/usr/bin/env python3
"""Run the disclosed cheap economic screen of frozen market-state roles."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-STATE-ECON-SCREEN-001_spec.json"
AUDIT_PATH = PROGRAM / "artifacts/MKT-STATE-ECON-SCREEN-001_candidate_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STATE-ECON-SCREEN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STATE-ECON-SCREEN-001_market_state_screen.md"
EXPECTED_SPEC_SHA256 = "667ce3dee02af1f04ac7e1a1cb4c2ec10ba9f602e1c4a9c50dbef8d378fc0203"

KEYS = ["trade_date", "market_view", "denominator"]
COORDINATE_SUFFIXES = {
    "absolute": "",
    "pit_expanding": "_pit_expanding_pct",
    "pit_3y": "_pit_3y_pct",
}
ACTIVATED_STATUSES = {
    "risk_result": "COMPLETE_STRATEGY_INDEPENDENT_DIRECTIONAL_TAIL_REPRESENTATION",
    "correlation_liquidity_result": (
        "COMPLETE_STRATEGY_INDEPENDENT_CORRELATION_LIQUIDITY_REPRESENTATION_FREEZE"
    ),
    "breadth_result": "COMPLETE_STRATEGY_INDEPENDENT_BREADTH_REPRESENTATION_FREEZE",
    "response_result": "COMPLETE_RESPONSE_DOMAIN_ADEQUACY",
}


class MarketStateScreenError(RuntimeError):
    """Fail-closed market-state screen error."""


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
        raise MarketStateScreenError("screen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("experiment_id") != "MKT-STATE-ECON-SCREEN-001"
        or spec.get("research_level") != "EXPLORE"
        or spec.get("status") != "POST_DISCOVERY_FIXED_CHEAP_SCREEN"
    ):
        raise MarketStateScreenError("screen honesty contract changed")
    if "inspected" not in spec.get("honesty_boundary", ""):
        raise MarketStateScreenError("post-inspection disclosure is missing")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MarketStateScreenError(f"bound input identity mismatch: {name}")
        if name in ACTIVATED_STATUSES:
            result = json.loads(path.read_text(encoding="utf-8"))
            if result.get("status") != ACTIVATED_STATUSES[name]:
                raise MarketStateScreenError(f"bound input is not activated: {name}")
    prohibited = "|".join(spec["prohibited_computations"])
    for phrase in ("same-bar execution", "post-2023", "CY-011"):
        if phrase not in prohibited:
            raise MarketStateScreenError(f"missing prohibited boundary: {phrase}")
    return spec


def _load_response(spec: dict[str, Any]) -> pd.DataFrame:
    path = _resolve(spec["inputs"]["response_panel"]["path"])
    columns = [
        *KEYS,
        "response_complete",
        "response_date_h3",
        "response_date_h5",
        "terminal_mean_log_return_h5",
        "terminal_p10_log_return_h3",
        "terminal_p90_log_return_h3",
        "adverse_mean_log_excursion_h3",
    ]
    response = pd.read_csv(
        path,
        usecols=columns,
        parse_dates=["trade_date", "response_date_h3", "response_date_h5"],
    )
    response = response.loc[response.response_complete].copy()
    population = spec["population"]
    response = response.loc[
        response.trade_date.between(
            pd.Timestamp(population["expected_first_date"]),
            pd.Timestamp(population["expected_last_complete_date"]),
        )
    ].copy()
    if len(response) != population["expected_complete_rows"]:
        raise MarketStateScreenError("complete response row count changed")
    if response.trade_date.nunique() != population["expected_complete_dates"]:
        raise MarketStateScreenError("complete response date count changed")
    if response.trade_date.min().strftime("%Y-%m-%d") != population["expected_first_date"]:
        raise MarketStateScreenError("first response date changed")
    if response.trade_date.max().strftime("%Y-%m-%d") != population["expected_last_complete_date"]:
        raise MarketStateScreenError("last response date changed")
    if response.trade_date.dt.year.max() > 2023:
        raise MarketStateScreenError("post-2023 response reached screen")
    for horizon in (3, 5):
        if not response[f"response_date_h{horizon}"].gt(response.trade_date).all():
            raise MarketStateScreenError(f"h{horizon} response is not strictly after state date")
    response["opportunity_spread_h3"] = (
        response["terminal_p90_log_return_h3"]
        - response["terminal_p10_log_return_h3"]
    )
    if not response.opportunity_spread_h3.ge(0).all():
        raise MarketStateScreenError("negative opportunity spread")
    expected_cells = {
        (view, denominator)
        for view in population["views"]
        for denominator in population["denominators"]
    }
    observed_cells = set(map(tuple, response[KEYS[1:]].drop_duplicates().to_numpy()))
    if observed_cells != expected_cells:
        raise MarketStateScreenError("governed response cells changed")
    return response


def _source_columns(spec: dict[str, Any], source: str) -> list[str]:
    columns: set[str] = set()
    for candidate in spec["fixed_candidates"]:
        if candidate["source"] != source:
            continue
        primary = candidate["primary"]
        columns.update(primary + suffix for suffix in COORDINATE_SUFFIXES.values())
        columns.update(candidate["neighbors"])
    return sorted(columns)


def _load_state_source(spec: dict[str, Any], source: str) -> pd.DataFrame:
    columns = _source_columns(spec, source)
    state = pd.read_csv(
        _resolve(spec["inputs"][source]["path"]),
        usecols=[*KEYS, "decision_at", "available_at", "snapshot_id", *columns],
        parse_dates=["trade_date"],
    )
    if state.duplicated(KEYS).any():
        raise MarketStateScreenError(f"duplicate state keys: {source}")
    if not state["decision_at"].str.contains("T15:00:00+08:00", regex=False).all():
        raise MarketStateScreenError(f"decision timestamp changed: {source}")
    if not state["available_at"].eq(state["decision_at"]).all():
        raise MarketStateScreenError(f"state availability exceeds decision time: {source}")
    if state.trade_date.dt.year.max() > 2023:
        raise MarketStateScreenError(f"post-2023 state reached screen: {source}")
    return state


def _rho(frame: pd.DataFrame, predictor: str, response: str) -> tuple[float, int]:
    data = frame[[predictor, response]].dropna().to_numpy(dtype=float)
    if len(data) < 20:
        return float("nan"), len(data)
    if not np.isfinite(data).all():
        raise MarketStateScreenError(f"nonfinite estimator input: {predictor}/{response}")
    return float(spearmanr(data[:, 0], data[:, 1]).statistic), len(data)


def _cell_estimates(
    frame: pd.DataFrame,
    predictor: str,
    response: str,
    scope: str,
    candidate_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (view, denominator), cell in frame.groupby(KEYS[1:], sort=True):
        estimate, observations = _rho(cell, predictor, response)
        rows.append(
            {
                "candidate_id": candidate_id,
                "scope": scope,
                "market_view": view,
                "denominator": denominator,
                "predictor": predictor,
                "response": response,
                "estimate": estimate,
                "observations": observations,
            }
        )
    return rows


def _median(rows: list[dict[str, Any]]) -> float:
    return float(np.nanmedian([row["estimate"] for row in rows]))


def _same_sign(value: float, expected_sign: int) -> bool:
    return math.isfinite(value) and value * expected_sign > 0


def _analyze_candidate(
    panel: pd.DataFrame,
    candidate: dict[str, Any],
    screen: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidate_id = candidate["candidate_id"]
    primary = candidate["primary"]
    response = candidate["response"]
    expected_sign = int(candidate["expected_sign"])
    audit: list[dict[str, Any]] = []
    coordinate_summary: dict[str, Any] = {}
    for coordinate, suffix in COORDINATE_SUFFIXES.items():
        predictor = primary + suffix
        rows = _cell_estimates(panel, predictor, response, f"coordinate_{coordinate}", candidate_id)
        audit.extend(rows)
        coordinate_summary[coordinate] = {
            "predictor": predictor,
            "median_cell_rho": _median(rows),
            "same_sign_cells": sum(
                _same_sign(float(row["estimate"]), expected_sign) for row in rows
            ),
            "cell_rhos": [row["estimate"] for row in rows],
        }

    neighbor_summary: dict[str, Any] = {}
    for predictor in candidate["neighbors"]:
        rows = _cell_estimates(panel, predictor, response, "neighbor_definition", candidate_id)
        audit.extend(rows)
        neighbor_summary[predictor] = {
            "median_cell_rho": _median(rows),
            "same_sign_cells": sum(
                _same_sign(float(row["estimate"]), expected_sign) for row in rows
            ),
        }

    pit_predictor = primary + "_pit_3y_pct"
    pit_panel = panel.dropna(subset=[pit_predictor, response]).copy()
    support = pit_panel.groupby(KEYS[1:]).size()
    if len(support) != 8 or support.min() < screen.get("minimum_rows_per_cell", 0):
        raise MarketStateScreenError(f"insufficient PIT support: {candidate_id}")
    annual_summary: dict[str, Any] = {}
    for year, annual in pit_panel.groupby(pit_panel.trade_date.dt.year, sort=True):
        rows = _cell_estimates(
            annual, pit_predictor, response, f"pit_year_{year}", candidate_id
        )
        audit.extend(rows)
        annual_summary[str(year)] = {
            "median_cell_rho": _median(rows),
            "same_sign_cells": sum(
                _same_sign(float(row["estimate"]), expected_sign) for row in rows
            ),
        }

    tail_gaps: list[float] = []
    tail_counts: list[dict[str, Any]] = []
    for (view, denominator), cell in pit_panel.groupby(KEYS[1:], sort=True):
        high = cell.loc[cell[pit_predictor].ge(0.8), response]
        low = cell.loc[cell[pit_predictor].le(0.2), response]
        if len(high) < 20 or len(low) < 20:
            raise MarketStateScreenError(f"insufficient fixed-tail support: {candidate_id}")
        gap = float(high.mean() - low.mean())
        tail_gaps.append(gap)
        tail_counts.append(
            {
                "market_view": view,
                "denominator": denominator,
                "high_count": len(high),
                "low_count": len(low),
                "gap": gap,
            }
        )

    pit = coordinate_summary["pit_3y"]
    checks = {
        "pit_magnitude": abs(pit["median_cell_rho"])
        >= screen["minimum_absolute_median_cell_pit_rho"],
        "all_cells_same_sign": pit["same_sign_cells"]
        >= screen["required_same_sign_cells"],
        "pit_years_same_sign": sum(
            _same_sign(value["median_cell_rho"], expected_sign)
            for value in annual_summary.values()
        )
        >= screen["minimum_same_sign_pit_years"],
        "coordinate_views_same_sign": sum(
            _same_sign(value["median_cell_rho"], expected_sign)
            for value in coordinate_summary.values()
        )
        >= screen["required_same_sign_coordinate_views"],
        "neighbor_definitions_same_sign": sum(
            _same_sign(value["median_cell_rho"], expected_sign)
            for value in neighbor_summary.values()
        )
        >= screen["required_same_sign_neighbor_definitions"],
        "economic_tail_gap_same_sign": _same_sign(float(np.median(tail_gaps)), expected_sign),
    }
    return audit, {
        "candidate_id": candidate_id,
        "family": candidate["family"],
        "economic_role": candidate["economic_role"],
        "response": response,
        "expected_sign": expected_sign,
        "pit_rows": len(pit_panel),
        "minimum_pit_rows_per_cell": int(support.min()),
        "maximum_pit_rows_per_cell": int(support.max()),
        "coordinate_summary": coordinate_summary,
        "neighbor_summary": neighbor_summary,
        "pit_years": annual_summary,
        "median_fixed_tail_gap": float(np.median(tail_gaps)),
        "fixed_tail_cells": tail_counts,
        "checks": checks,
        "cheap_screen_pass": all(checks.values()),
    }


def _analyze(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    response = _load_response(spec)
    sources = {
        source: _load_state_source(spec, source)
        for source in sorted({item["source"] for item in spec["fixed_candidates"]})
    }
    candidates: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    screen = dict(spec["cheap_screen"])
    screen["minimum_rows_per_cell"] = spec["population"]["minimum_pit_rows_per_cell"]
    for candidate in spec["fixed_candidates"]:
        state = sources[candidate["source"]]
        panel = response.merge(state, on=KEYS, how="inner", validate="one_to_one")
        if len(panel) != len(response):
            raise MarketStateScreenError(f"state/response coverage changed: {candidate['candidate_id']}")
        rows, result = _analyze_candidate(panel, candidate, screen)
        audit_rows.extend(rows)
        candidates.append(result)

    candidates.sort(
        key=lambda item: abs(item["coordinate_summary"]["pit_3y"]["median_cell_rho"]),
        reverse=True,
    )
    for rank, candidate in enumerate(candidates, 1):
        candidate["rank_by_absolute_pit_rho"] = rank
        candidate["funnel_status"] = "PROMISING" if candidate["cheap_screen_pass"] else "PARKED"
    passing = [item for item in candidates if item["cheap_screen_pass"]]
    return pd.DataFrame(audit_rows), {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "status": "COMPLETE_DISCLOSED_CHEAP_MARKET_STATE_ECONOMIC_SCREEN",
        "classification": (
            "MULTIPLE_PROMISING_LEADS_REQUIRE_CHEAP_INCREMENTAL_ROBUSTNESS"
            if passing
            else "NO_MARKET_STATE_ROLE_PASSES_CHEAP_SCREEN"
        ),
        "honesty_boundary": spec["honesty_boundary"],
        "support": {
            "complete_rows": len(response),
            "complete_dates": int(response.trade_date.nunique()),
            "cells": int(response.groupby(KEYS[1:]).ngroups),
            "first_date": response.trade_date.min().strftime("%Y-%m-%d"),
            "last_date": response.trade_date.max().strftime("%Y-%m-%d"),
        },
        "ranked_candidates": candidates,
        "passing_candidate_ids": [item["candidate_id"] for item in passing],
        "next_stage": (
            "Test the top distinct channels against obvious same-family and current-state controls; "
            "translate only surviving directional channels to t+1 executable rules."
        ),
        "claim_boundary": {
            "confirmation": False,
            "causality": False,
            "strategy_supported": False,
            "pnl_estimated": False,
            "cost_capacity_estimated": False,
            "future_response_used_as_predictor": False,
            "same_bar_fill_assumed": False,
            "strategy_fields_read": False,
            "post_2023_read": False,
            "cy011_read": False,
        },
        "hashes": {
            "spec_sha256": EXPECTED_SPEC_SHA256,
            "inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
        },
    }


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-STATE-ECON-SCREEN-001 — cheap market-state economic screen",
        "",
        "## Outcome",
        "",
        "This is a disclosed post-inspection EXPLORE screen. It ranks frozen market-state roles; "
        "it does not validate a signal or strategy.",
        "",
        "| Rank | Candidate | Role | PIT rho | Fixed 80/20 gap | Status |",
        "|---:|---|---|---:|---:|---|",
    ]
    for item in result["ranked_candidates"]:
        rho = item["coordinate_summary"]["pit_3y"]["median_cell_rho"]
        lines.append(
            f"| {item['rank_by_absolute_pit_rho']} | {item['candidate_id']} | "
            f"{item['economic_role']} | {rho:.6f} | {item['median_fixed_tail_gap']:.6f} | "
            f"{item['funnel_status']} |"
        )
    lines.extend(
        [
            "",
            "All responses begin after the completed t close. No fill, portfolio, P&L, cost, "
            "capacity, strategy outcome, post-2023 field, or CY-011 field was constructed or read.",
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
    audit, result = _analyze(spec)
    audit = audit.sort_values(
        ["candidate_id", "scope", "market_view", "denominator"]
    ).reset_index(drop=True)
    audit_csv = audit.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    _atomic_write(AUDIT_PATH, audit_csv)
    result["hashes"]["candidate_audit_sha256"] = sha256_file(AUDIT_PATH)
    report = _render_report(result)
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(_clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
