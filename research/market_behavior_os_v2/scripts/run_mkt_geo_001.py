#!/usr/bin/env python3
"""Outcome-blind continuous/state geometry for frozen trend and breadth roles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-GEO-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-GEO-001_geometry_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-GEO-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-GEO-001_trend_breadth_geometry.md"


class GeometryError(RuntimeError):
    """Fail-closed state-geometry error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def partial_rank_correlation(frame: pd.DataFrame, left: str, right: str, control: str) -> float:
    clean = frame[[left, right, control]].dropna().rank(method="average")
    if len(clean) < 3:
        return float("nan")
    design = np.column_stack([np.ones(len(clean)), clean[control].to_numpy(float)])
    left_residual = clean[left].to_numpy(float) - design @ np.linalg.lstsq(
        design, clean[left].to_numpy(float), rcond=None
    )[0]
    right_residual = clean[right].to_numpy(float) - design @ np.linalg.lstsq(
        design, clean[right].to_numpy(float), rcond=None
    )[0]
    return float(np.corrcoef(left_residual, right_residual)[0, 1])


def direction_state(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value > 0.0:
        return "POSITIVE"
    if value < 0.0:
        return "NEGATIVE"
    return "NEUTRAL"


def discovery_state(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value > 0.0:
        return "EXPANSION"
    if value < 0.0:
        return "BREAKDOWN"
    return "BALANCED"


def concentration_state(value: float) -> str:
    if not np.isfinite(value):
        return "MISSING"
    if value >= 0.80:
        return "CONCENTRATED"
    if value <= 0.20:
        return "DIFFUSE"
    return "MIDDLE"


def _run_lengths(states: pd.Series) -> list[tuple[str, int]]:
    output: list[tuple[str, int]] = []
    previous: str | None = None
    length = 0
    for state in states.astype(str):
        if state == previous:
            length += 1
        else:
            if previous is not None:
                output.append((previous, length))
            previous = state
            length = 1
    if previous is not None:
        output.append((previous, length))
    return output


def _load(spec: dict) -> pd.DataFrame:
    trend_path = ROOT / spec["inputs"]["trend_panel"]["path"]
    breadth_path = ROOT / spec["inputs"]["breadth_panel"]["path"]
    if sha256_file(trend_path) != spec["inputs"]["trend_panel"]["sha256"]:
        raise GeometryError("trend panel identity mismatch")
    if sha256_file(breadth_path) != spec["inputs"]["breadth_panel"]["sha256"]:
        raise GeometryError("breadth panel identity mismatch")
    trend_columns = [
        "trade_date", "index_symbol", "decision_at", "available_at",
        "direction_return_60", "direction_return_60_pit_3y_pct",
    ]
    breadth_columns = [
        "trade_date", "market_view", "denominator", "decision_at", "available_at",
        "breadth_net_new_high_low60", "breadth_net_new_high_low60_pit_3y_pct",
        "leadership_positive_mass_top10", "leadership_positive_mass_top10_pit_3y_pct",
    ]
    trend = pd.read_csv(trend_path, usecols=trend_columns)
    breadth = pd.read_csv(breadth_path, usecols=breadth_columns)
    breadth = breadth.loc[breadth["denominator"] == "ALL_STATUS"].copy()
    if trend.duplicated(["trade_date", "index_symbol"]).any():
        raise GeometryError("duplicate trend key")
    if breadth.duplicated(["trade_date", "market_view"]).any():
        raise GeometryError("duplicate breadth key")
    if trend["index_symbol"].nunique() != 6 or breadth["market_view"].nunique() != 4:
        raise GeometryError("exact 6 x 4 geometry contract failed")
    merged = trend.merge(breadth, on="trade_date", how="inner", suffixes=("_trend", "_breadth"))
    if len(merged) == 0 or len(merged.groupby(["index_symbol", "market_view"])) != 24:
        raise GeometryError("geometry join coverage failed")
    if (merged["decision_at_trend"] != merged["decision_at_breadth"]).any():
        raise GeometryError("decision timestamp mismatch")
    if (merged["available_at_trend"] > merged["decision_at_trend"]).any():
        raise GeometryError("trend time travel")
    if (merged["available_at_breadth"] > merged["decision_at_breadth"]).any():
        raise GeometryError("breadth time travel")
    merged["trade_date"] = pd.to_datetime(merged["trade_date"])
    if merged["trade_date"].max() > pd.Timestamp(spec["inputs"]["date_end"]):
        raise GeometryError("post-cutoff geometry row")
    return merged.sort_values(["index_symbol", "market_view", "trade_date"]).reset_index(drop=True)


def _analyze(panel: pd.DataFrame) -> dict:
    pairs: dict[str, dict] = {}
    direction_discovery: list[float] = []
    direction_concentration: list[float] = []
    conditional_breadth: list[float] = []
    for (index_symbol, market_view), group in panel.groupby(["index_symbol", "market_view"], sort=True):
        rho_discovery = float(group[["direction_return_60", "breadth_net_new_high_low60"]].corr(method="spearman").iloc[0, 1])
        rho_concentration = float(group[["direction_return_60", "leadership_positive_mass_top10"]].corr(method="spearman").iloc[0, 1])
        partial = partial_rank_correlation(
            group, "breadth_net_new_high_low60", "leadership_positive_mass_top10", "direction_return_60"
        )
        key = f"{index_symbol}:{market_view}"
        pairs[key] = {
            "n": int(len(group)),
            "direction_vs_discovery_spearman": rho_discovery,
            "direction_vs_concentration_spearman": rho_concentration,
            "discovery_vs_concentration_partial_rank_after_direction": partial,
        }
        direction_discovery.append(rho_discovery)
        direction_concentration.append(rho_concentration)
        conditional_breadth.append(partial)

    geometry = panel.copy()
    geometry["direction_state"] = geometry["direction_return_60"].map(direction_state)
    geometry["discovery_state"] = geometry["breadth_net_new_high_low60"].map(discovery_state)
    geometry["concentration_state"] = geometry["leadership_positive_mass_top10_pit_3y_pct"].map(concentration_state)
    geometry["direction_discovery_state"] = geometry["direction_state"] + "__" + geometry["discovery_state"]
    geometry["full_state"] = geometry["direction_discovery_state"] + "__" + geometry["concentration_state"]

    occupancy = {
        str(key): int(value)
        for key, value in geometry.groupby("direction_discovery_state").size().sort_index().items()
    }
    occupancy_by_year = {
        f"{year}:{state}": int(value)
        for (year, state), value in geometry.assign(year=geometry["trade_date"].dt.year)
        .groupby(["year", "direction_discovery_state"]).size().sort_index().items()
    }
    dwell_rows: list[dict] = []
    transitions: dict[str, int] = {}
    for (index_symbol, market_view), group in geometry.groupby(["index_symbol", "market_view"], sort=True):
        ordered = group.sort_values("trade_date")
        for state, length in _run_lengths(ordered["direction_discovery_state"]):
            dwell_rows.append({"state": state, "length": length})
        states = ordered["direction_discovery_state"].astype(str).to_numpy()
        for left, right in zip(states[:-1], states[1:]):
            key = f"{left}->{right}"
            transitions[key] = transitions.get(key, 0) + 1
    dwell_frame = pd.DataFrame(dwell_rows)
    dwell = {
        str(state): {
            "runs": int(len(group)),
            "median_sessions": float(group["length"].median()),
            "p90_sessions": float(group["length"].quantile(0.90)),
            "max_sessions": int(group["length"].max()),
        }
        for state, group in dwell_frame.groupby("state", sort=True)
    }
    return {
        "pair_diagnostics": pairs,
        "summary": {
            "direction_vs_discovery_median_spearman": float(np.median(direction_discovery)),
            "direction_vs_discovery_max_absolute_spearman": float(np.max(np.abs(direction_discovery))),
            "direction_vs_concentration_median_spearman": float(np.median(direction_concentration)),
            "direction_vs_concentration_max_absolute_spearman": float(np.max(np.abs(direction_concentration))),
            "conditional_discovery_vs_concentration_median_partial_rank": float(np.median(conditional_breadth)),
            "conditional_discovery_vs_concentration_max_absolute_partial_rank": float(np.max(np.abs(conditional_breadth))),
        },
        "state_occupancy": occupancy,
        "state_occupancy_by_year": occupancy_by_year,
        "dwell": dwell,
        "transition_counts": dict(sorted(transitions.items())),
        "geometry_panel": geometry,
    }


def _render_report(result: dict) -> str:
    summary = result["continuous_geometry"]
    lines = [
        "# MKT-GEO-001 outcome-blind Trend × Breadth state geometry",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Geometry rows: {result['population']['rows']:,}; 6 indices × 4 market views; {result['population']['first_date']}..{result['population']['last_date']}.",
        "- Strategy outcomes, future returns, trading rules, and CY-011 read: **none**.",
        "- This describes contemporaneous redundancy, occupancy, dwell, and transitions. It does not establish usefulness, prediction, habitat fitness, or causality.",
        "",
        "## Continuous geometry",
        "",
        "| Relationship | Median | Maximum absolute across 24 pairs | Nonredundancy gate |",
        "|---|---:|---:|---|",
        f"| direction vs new-high/new-low discovery | {summary['direction_vs_discovery_median_spearman']:.3f} | {summary['direction_vs_discovery_max_absolute_spearman']:.3f} | {'PASS' if result['gates']['direction_discovery_nonredundant'] else 'FAIL'} |",
        f"| direction vs leadership concentration | {summary['direction_vs_concentration_median_spearman']:.3f} | {summary['direction_vs_concentration_max_absolute_spearman']:.3f} | {'PASS' if result['gates']['direction_concentration_nonredundant'] else 'FAIL'} |",
        f"| discovery vs concentration, controlling direction | {summary['conditional_discovery_vs_concentration_median_partial_rank']:.3f} | {summary['conditional_discovery_vs_concentration_max_absolute_partial_rank']:.3f} | {'PASS' if result['gates']['breadth_roles_conditionally_distinct'] else 'FAIL'} |",
        "",
        "## Absolute-sign state occupancy",
        "",
        "| State | Observations |",
        "|---|---:|",
    ]
    for state, count in result["state_occupancy"].items():
        lines.append(f"| {state} | {count:,} |")
    lines.extend(
        [
            "",
            "State counts repeat dates across the 24 index/view geometry pairs and are not independent samples. Sparse states remain visible; no state boundary was optimized or merged.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Geometry panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_GEOMETRY_RESULT":
        raise GeometryError("geometry spec is not frozen")
    panel = _load(spec)
    analysis = _analyze(panel)
    geometry = analysis.pop("geometry_panel")
    output_columns = [
        "trade_date", "index_symbol", "market_view", "direction_return_60",
        "direction_return_60_pit_3y_pct", "breadth_net_new_high_low60",
        "breadth_net_new_high_low60_pit_3y_pct", "leadership_positive_mass_top10",
        "leadership_positive_mass_top10_pit_3y_pct", "direction_state",
        "discovery_state", "concentration_state", "direction_discovery_state", "full_state",
        "decision_at_trend", "decision_at_breadth",
    ]
    output = geometry[output_columns].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    summary = analysis["summary"]
    result = {
        "experiment_id": "MKT-GEO-001",
        "status": "COMPLETE_OUTCOME_BLIND_STATE_GEOMETRY",
        "usefulness_claim": "NONE",
        "strategy_or_future_return_fields_read": [],
        "population": {
            "rows": int(len(output)),
            "index_view_pairs": int(len(analysis["pair_diagnostics"])),
            "indices": int(output["index_symbol"].nunique()),
            "market_views": int(output["market_view"].nunique()),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
        },
        "continuous_geometry": summary,
        "pair_diagnostics": analysis["pair_diagnostics"],
        "gates": {
            "direction_discovery_nonredundant": summary["direction_vs_discovery_max_absolute_spearman"] < 0.85,
            "direction_concentration_nonredundant": summary["direction_vs_concentration_max_absolute_spearman"] < 0.85,
            "breadth_roles_conditionally_distinct": summary["conditional_discovery_vs_concentration_max_absolute_partial_rank"] < 0.85,
        },
        "state_occupancy": analysis["state_occupancy"],
        "state_occupancy_by_year": analysis["state_occupancy_by_year"],
        "dwell": analysis["dwell"],
        "transition_counts": analysis["transition_counts"],
        "limitations": {
            "overlapping_pairs": "24 index/view descriptions are not independent observations",
            "next_session_transitions": "descriptive state evolution only, not forecast",
            "economic_usefulness": "NOT_TESTED",
            "strategy_habitat": "NOT_TESTED",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "trend_panel_sha256": spec["inputs"]["trend_panel"]["sha256"],
            "breadth_panel_sha256": spec["inputs"]["breadth_panel"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(json.dumps({
        "status": final["status"],
        "population": final["population"],
        "continuous_geometry": final["continuous_geometry"],
        "gates": final["gates"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
