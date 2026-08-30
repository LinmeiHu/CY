#!/usr/bin/env python3
"""Construct the outcome-blind MKT-LDR-001 leader-deterioration map."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-LDR-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-LDR-001_leader_deterioration_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-LDR-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-LDR-001_leader_failure_representation.md"
MIN_PIT_HISTORY = 504
ROLE_MAP = {
    "concentration_decay": (
        "leadership_concentration_decay5_top10",
        (
            "leadership_concentration_decay5_top5",
            "leadership_concentration_decay5_top20",
            "leadership_concentration_decay3_top10",
            "leadership_concentration_decay10_top10",
        ),
    ),
    "discovery_deterioration": (
        "discovery_deterioration5_h60",
        (
            "discovery_deterioration5_h40",
            "discovery_deterioration5_h80",
            "discovery_deterioration3_h60",
            "discovery_deterioration10_h60",
        ),
    ),
    "leadership_discovery_imbalance": (
        "leadership_discovery_imbalance_top10_h60",
        (
            "leadership_discovery_imbalance_top5_h40",
            "leadership_discovery_imbalance_top20_h80",
        ),
    ),
}


class LeaderRepresentationError(RuntimeError):
    """Fail-closed leader representation error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load() -> tuple[dict, pd.DataFrame]:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise LeaderRepresentationError("spec is not frozen before result")
    panel_path = ROOT / spec["input"]["breadth_panel_path"]
    result_path = ROOT / spec["input"]["breadth_result_path"]
    if sha256_file(panel_path) != spec["input"]["breadth_panel_sha256"]:
        raise LeaderRepresentationError("frozen breadth panel identity mismatch")
    if sha256_file(result_path) != spec["input"]["breadth_result_sha256"]:
        raise LeaderRepresentationError("frozen breadth result identity mismatch")
    permitted = spec["input"]["permitted_columns"]
    frame = pd.read_csv(panel_path, usecols=permitted, parse_dates=["trade_date"])
    if len(frame) != spec["input"]["rows"]:
        raise LeaderRepresentationError("frozen breadth row count changed")
    if frame["trade_date"].min().strftime("%Y-%m-%d") != spec["input"]["first_date"]:
        raise LeaderRepresentationError("breadth start changed")
    if frame["trade_date"].max().strftime("%Y-%m-%d") != spec["input"]["last_date"]:
        raise LeaderRepresentationError("breadth end changed")
    if frame.duplicated(["trade_date", "market_view", "denominator"]).any():
        raise LeaderRepresentationError("duplicate view/date key")
    if not (pd.to_datetime(frame["available_at"], utc=True) <= pd.to_datetime(frame["decision_at"], utc=True)).all():
        raise LeaderRepresentationError("derived breadth time travel")
    return spec, frame


def _construct(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    grouped = out.groupby(["market_view", "denominator"], sort=False)
    concentration = {5: "leadership_positive_mass_top5", 10: "leadership_positive_mass_top10", 20: "leadership_positive_mass_top20"}
    discovery = {40: "breadth_net_new_high_low40", 60: "breadth_net_new_high_low60", 80: "breadth_net_new_high_low80"}
    for top, column in concentration.items():
        out[f"leadership_concentration_decay5_top{top}"] = -(out[column] - grouped[column].shift(5))
    for horizon in (3, 10):
        column = concentration[10]
        out[f"leadership_concentration_decay{horizon}_top10"] = -(
            out[column] - grouped[column].shift(horizon)
        )
    for price_horizon, column in discovery.items():
        out[f"discovery_deterioration5_h{price_horizon}"] = -(
            out[column] - grouped[column].shift(5)
        )
    for horizon in (3, 10):
        column = discovery[60]
        out[f"discovery_deterioration{horizon}_h60"] = -(
            out[column] - grouped[column].shift(horizon)
        )

    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for top, price_horizon in ((5, 40), (10, 60), (20, 80)):
            concentration_pct = causal_rolling_percentile(item[concentration[top]])
            discovery_pct = causal_rolling_percentile(item[discovery[price_horizon]])
            item[f"leadership_discovery_imbalance_top{top}_h{price_horizon}"] = (
                concentration_pct - discovery_pct
            )
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(
        ["market_view", "denominator", "trade_date"]
    )
    out["within_view_observation"] = out.groupby(
        ["market_view", "denominator"], sort=False
    ).cumcount() + 1
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    pieces = []
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for column in primary_columns:
            item[f"{column}_pit_expanding_pct"] = causal_expanding_percentile(item[column])
            item[f"{column}_pit_3y_pct"] = causal_rolling_percentile(item[column])
            item[f"{column}_pit_3y_robust_z"] = causal_rolling_robust_z(item[column])
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(
        ["trade_date", "denominator", "market_view"]
    )
    for column in primary_columns:
        all_values = out.loc[
            out["market_view"] == "ALL_A", ["trade_date", "denominator", column]
        ].rename(columns={column: "_all_value"})
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left")
        out[f"{column}_relative_to_all"] = out[column] - out["_all_value"]
        counts = out.groupby(["trade_date", "denominator"])[column].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[column].rank(method="average", pct=True)
        out[f"{column}_relative_view_rank_pct"] = ranks.where(counts >= 3)
        out = out.drop(columns="_all_value")
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def _diagnostics(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[str], dict[str, str]]:
    primary = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    diagnostics: dict[str, dict] = {}
    for role, (column, neighbors) in ROLE_MAP.items():
        warmup = MIN_PIT_HISTORY if role == "leadership_discovery_imbalance" else 20
        coverage = {
            str(view): float(group.loc[group["within_view_observation"] >= warmup, column].notna().mean())
            for view, group in primary.groupby("market_view", sort=True)
        }
        neighbor_stats: dict[str, dict] = {}
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_view = {
                str(view): float(group[[column, neighbor]].corr(method="spearman").iloc[0, 1])
                for view, group in primary.groupby("market_view", sort=True)
            }
            median_rho = float(np.median(list(by_view.values())))
            neighbor_medians.append(median_rho)
            neighbor_stats[neighbor] = {"median_across_views": median_rho, "by_view": by_view}
        denominator_by_view: dict[str, float] = {}
        for view in sorted(panel["market_view"].unique()):
            wide = panel.loc[
                panel["market_view"] == view, ["trade_date", "denominator", column]
            ].pivot(index="trade_date", columns="denominator", values=column)
            denominator_by_view[str(view)] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.median(list(denominator_by_view.values())))
        eligible_cells = 0
        nondegenerate_cells: list[bool] = []
        year_support: dict[str, dict] = {}
        for (view, year), cell in primary.assign(year=primary["trade_date"].dt.year).groupby(
            ["market_view", "year"], sort=True
        ):
            values = cell[column].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                std = float(values.std(ddof=0))
                nondegenerate_cells.append(bool(np.isfinite(std) and std > 0))
                year_support[f"{view}:{year}"] = {
                    "n": int(len(values)), "p10": float(values.quantile(0.1)),
                    "median": float(values.median()), "p90": float(values.quantile(0.9)),
                }
        nondegenerate = bool(eligible_cells and all(nondegenerate_cells))
        pit_expected = primary[column].notna().groupby(
            [primary["market_view"], primary["denominator"]]
        ).cumsum() >= MIN_PIT_HISTORY
        pit_coverage = (
            float(primary.loc[pit_expected, f"{column}_pit_3y_pct"].notna().mean())
            if pit_expected.any() else float("nan")
        )
        relative_expected = (primary["market_view"] != "ALL_A") & primary[column].notna()
        relative_coverage = float(
            primary.loc[relative_expected, f"{column}_relative_to_all"].notna().mean()
        )
        passed = bool(
            min(coverage.values()) >= 0.95
            and min(neighbor_medians) >= 0.70
            and denominator_median >= 0.90
            and nondegenerate
        )
        diagnostics[role] = {
            "primary": column,
            "minimum_raw_coverage": min(coverage.values()),
            "coverage_by_view": coverage,
            "neighbors": neighbor_stats,
            "all_status_vs_non_st_by_view": denominator_by_view,
            "all_status_vs_non_st_median": denominator_median,
            "eligible_view_year_cells": eligible_cells,
            "all_eligible_cells_nondegenerate": nondegenerate,
            "year_support": year_support,
            "pit_3y_percentile_expected_coverage": pit_coverage,
            "relative_to_all_expected_coverage": relative_coverage,
            "construction_gate_pass": passed,
        }
    role_columns = {role: definition[0] for role, definition in ROLE_MAP.items()}
    correlation = primary.loc[primary["market_view"] == "ALL_A", list(role_columns.values())].rename(
        columns={value: key for key, value in role_columns.items()}
    ).corr(method="spearman")
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in ROLE_MAP:
        if not diagnostics[role]["construction_gate_pass"]:
            excluded[role] = "construction_gate_failed"
            continue
        blockers = [other for other in accepted if abs(float(correlation.loc[role, other])) > 0.85]
        if blockers:
            excluded[role] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    return diagnostics, correlation, accepted, excluded


def _render_report(result: dict) -> str:
    lines = [
        "# MKT-LDR-001 leader-failure representation freeze", "",
        "## Boundary", "",
        f"- Status: `{result['status']}`",
        "- Input is the immutable MKT-BRTH-002 representation panel only.",
        "- Strategy membership, outcomes, future returns, paths, and CY-011 read: **none**.",
        "- Concentration level is not leader failure; this experiment establishes no reversal, continuation, short, veto, or strategy claim.",
        f"- Joint deterioration geometry: `{result['joint_deterioration_geometry']}`.",
        "", "## Representation gates", "",
        "| Concept | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Gate |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for role in ROLE_MAP:
        item = result["role_diagnostics"][role]
        worst = min(value["median_across_views"] for value in item["neighbors"].values())
        lines.append(
            f"| {role} | {item['minimum_raw_coverage']:.3f} | {worst:.3f} | "
            f"{item['all_status_vs_non_st_median']:.3f} | "
            f"{item['pit_3y_percentile_expected_coverage']:.3f} | "
            f"{'PASS' if item['construction_gate_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "", "Failed exact representations leave the broader leader-failure family open; no favorable neighbor may replace a failed primary.",
        "", "## Reproducibility", "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Input panel SHA-256: `{result['hashes']['input_panel_sha256']}`",
        f"- Output panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec, source = _load()
    panel = _construct(source)
    diagnostics, correlation, accepted, excluded = _diagnostics(panel)
    joint = (
        "PERMITTED_DESCRIPTIVE_ONLY"
        if diagnostics["concentration_decay"]["construction_gate_pass"]
        and diagnostics["discovery_deterioration"]["construction_gate_pass"]
        else "NOT_CONSTRUCTED_TRANSITION_GATE_FAILED"
    )
    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    base_columns = [
        "breadth_net_new_high_low40", "breadth_net_new_high_low60", "breadth_net_new_high_low80",
        "leadership_positive_mass_top5", "leadership_positive_mass_top10", "leadership_positive_mass_top20",
    ]
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    coordinate_columns = [
        column for primary in primary_columns for column in (
            f"{primary}_pit_expanding_pct", f"{primary}_pit_3y_pct",
            f"{primary}_pit_3y_robust_z", f"{primary}_relative_to_all",
            f"{primary}_relative_view_rank_pct",
        )
    ]
    output = panel[[
        "trade_date", "market_view", "denominator", "within_view_observation",
        "decision_at", "available_at", "snapshot_id", *base_columns, *raw_columns,
        *coordinate_columns,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_OUTCOME_BLIND_LEADER_REPRESENTATION_FREEZE",
        "usefulness_claim": "NONE",
        "strategy_or_future_fields_read": [],
        "population": {
            "rows": int(len(output)), "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "views": int(output["market_view"].nunique()),
        },
        "role_diagnostics": diagnostics,
        "primary_role_spearman_all_a": {
            str(row): {str(column): float(correlation.loc[row, column]) for column in correlation.columns}
            for row in correlation.index
        },
        "minimal_panel": {"accepted_roles": accepted, "excluded_roles": excluded},
        "joint_deterioration_geometry": joint,
        "limitations": {
            "leader_failure": "NOT_ESTABLISHED", "future_path": "NOT_READ",
            "strategy_usefulness": "NOT_TESTED",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "input_panel_sha256": spec["input"]["breadth_panel_sha256"],
            "input_result_sha256": spec["input"]["breadth_result_sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "status": final["status"], "accepted_roles": final["minimal_panel"]["accepted_roles"],
        "excluded_roles": final["minimal_panel"]["excluded_roles"],
        "joint_deterioration_geometry": final["joint_deterioration_geometry"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
