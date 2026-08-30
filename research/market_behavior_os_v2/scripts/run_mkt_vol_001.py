#!/usr/bin/env python3
"""Build the strategy-independent MKT-VOL-001 volatility panel."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_mkt_brth_001 as breadth  # noqa: E402
from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-VOL-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-VOL-001_volatility_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-VOL-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-VOL-001_volatility_representation.md"
MANIFEST_SHA = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
SNAPSHOT_ID = f"CY-006:{MANIFEST_SHA}"
MIN_PIT_HISTORY = 504
VIEW_MINIMUMS = {"ALL_A": 1000, "SH_A": 400, "SZ_A": 400, "CHINEXT_BOARD": 200}
ROLE_MAP = {
    "realized_volatility": ("realized_volatility_median20", ("realized_volatility_median10", "realized_volatility_median40")),
    "downside_volatility": ("downside_volatility_median20", ("downside_volatility_median10", "downside_volatility_median40")),
    "intraday_range": ("intraday_range_median_smooth5", ("intraday_range_median_smooth3", "intraday_range_median_smooth10")),
    "term_structure": ("volatility_term_structure_10_40", ("volatility_term_structure_10_20", "volatility_term_structure_20_40")),
    "dispersion": ("return_dispersion_smooth5", ("return_dispersion_smooth3", "return_dispersion_smooth10")),
    "downside_mass_share": ("downside_mass_share_smooth5", ("downside_mass_share_smooth3", "downside_mass_share_smooth10")),
    "volatility_concentration": ("volatility_mass_share_top10", ("volatility_mass_share_top5", "volatility_mass_share_top20")),
    "volatility_change": ("realized_volatility_change5", ("realized_volatility_change3", "realized_volatility_change10")),
}
MINIMAL_PRIORITY = tuple(ROLE_MAP)


class VolatilityFreezeError(RuntimeError):
    """Fail-closed volatility construction error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _create_security_volatility(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE volatility_windows AS
        SELECT symbol,trade_date,cal_idx,
               sqrt(252*avg(step_log_return*step_log_return) OVER w10) AS rv10,
               sqrt(252*avg(step_log_return*step_log_return) OVER w20) AS rv20,
               sqrt(252*avg(step_log_return*step_log_return) OVER w40) AS rv40,
               sqrt(252*avg(CASE WHEN step_log_return<0
                                 THEN step_log_return*step_log_return ELSE 0 END) OVER w10) AS downside10,
               sqrt(252*avg(CASE WHEN step_log_return<0
                                 THEN step_log_return*step_log_return ELSE 0 END) OVER w20) AS downside20,
               sqrt(252*avg(CASE WHEN step_log_return<0
                                 THEN step_log_return*step_log_return ELSE 0 END) OVER w40) AS downside40,
               count(step_log_return) OVER w10 AS count10,
               count(step_log_return) OVER w20 AS count20,
               count(step_log_return) OVER w40 AS count40,
               min(cal_idx) OVER w10 AS min_idx10,
               min(cal_idx) OVER w20 AS min_idx20,
               min(cal_idx) OVER w40 AS min_idx40
        FROM stock_lagged
        WINDOW
          w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w40 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE vol_core AS
        SELECT c.trade_date,c.cal_idx,c.symbol,c.is_st,sl.step_log_return,
               v.rv10,v.rv20,v.rv40,v.downside10,v.downside20,v.downside40,
               ln(s.high/s.low) AS intraday_log_range
        FROM core c
        JOIN stock_lagged sl ON c.symbol=sl.symbol AND c.trade_date=sl.trade_date
        JOIN volatility_windows v
          ON c.symbol=v.symbol AND c.trade_date=v.trade_date AND c.cal_idx=v.cal_idx
        JOIN source s ON c.symbol=s.symbol AND c.trade_date=s.trade_date
        WHERE v.count10=10 AND v.count20=20 AND v.count40=40
          AND c.cal_idx-v.min_idx10=9 AND c.cal_idx-v.min_idx20=19
          AND c.cal_idx-v.min_idx40=39
          AND sl.step_log_return IS NOT NULL AND isfinite(sl.step_log_return)
          AND v.rv10 IS NOT NULL AND isfinite(v.rv10) AND v.rv10>=0
          AND v.rv20 IS NOT NULL AND isfinite(v.rv20) AND v.rv20>=0
          AND v.rv40 IS NOT NULL AND isfinite(v.rv40) AND v.rv40>0
          AND v.downside10 IS NOT NULL AND isfinite(v.downside10) AND v.downside10>=0
          AND v.downside20 IS NOT NULL AND isfinite(v.downside20) AND v.downside20>=0
          AND v.downside40 IS NOT NULL AND isfinite(v.downside40) AND v.downside40>=0
          AND s.high IS NOT NULL AND s.low IS NOT NULL AND s.high>=s.low AND s.low>0
        """
    )


def _create_daily(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE view_rows AS
        SELECT 'ALL_A' AS market_view,* FROM vol_core
        UNION ALL SELECT 'SH_A',* FROM vol_core WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM vol_core WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM vol_core
          WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE expanded AS
        SELECT v.*,'ALL_STATUS' AS denominator FROM view_rows v
        UNION ALL SELECT v.*,'NON_ST' FROM view_rows v WHERE is_st IS FALSE
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_context AS
        SELECT market_view,denominator,trade_date,median(step_log_return) AS median_return,
               quantile_cont(step_log_return*step_log_return,0.95) AS q95,
               quantile_cont(step_log_return*step_log_return,0.90) AS q90,
               quantile_cont(step_log_return*step_log_return,0.80) AS q80
        FROM expanded GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_raw AS
        SELECT e.market_view,e.denominator,e.trade_date,max(e.cal_idx) AS cal_idx,
               count(*) AS eligible_count,
               median(e.rv10) AS realized_volatility_median10,
               median(e.rv20) AS realized_volatility_median20,
               median(e.rv40) AS realized_volatility_median40,
               median(e.downside10) AS downside_volatility_median10,
               median(e.downside20) AS downside_volatility_median20,
               median(e.downside40) AS downside_volatility_median40,
               median(e.intraday_log_range) AS intraday_range_median_daily,
               median(e.rv10/e.rv40) AS volatility_term_structure_10_40,
               median(e.rv10/nullif(e.rv20,0)) AS volatility_term_structure_10_20,
               median(e.rv20/e.rv40) AS volatility_term_structure_20_40,
               median(abs(e.step_log_return-c.median_return)) AS return_dispersion_daily,
               sum(CASE WHEN e.step_log_return<0 THEN e.step_log_return*e.step_log_return ELSE 0 END)
                 /nullif(sum(e.step_log_return*e.step_log_return),0) AS downside_mass_share_daily,
               sum(CASE WHEN e.step_log_return*e.step_log_return>=c.q95
                        THEN e.step_log_return*e.step_log_return ELSE 0 END)
                 /nullif(sum(e.step_log_return*e.step_log_return),0) AS volatility_mass_share_top5,
               sum(CASE WHEN e.step_log_return*e.step_log_return>=c.q90
                        THEN e.step_log_return*e.step_log_return ELSE 0 END)
                 /nullif(sum(e.step_log_return*e.step_log_return),0) AS volatility_mass_share_top10,
               sum(CASE WHEN e.step_log_return*e.step_log_return>=c.q80
                        THEN e.step_log_return*e.step_log_return ELSE 0 END)
                 /nullif(sum(e.step_log_return*e.step_log_return),0) AS volatility_mass_share_top20
        FROM expanded e JOIN daily_context c USING(market_view,denominator,trade_date)
        GROUP BY e.market_view,e.denominator,e.trade_date
        """
    )
    return connection.execute(
        """
        SELECT *,
               avg(intraday_range_median_daily) OVER w3 AS intraday_range_median_smooth3,
               avg(intraday_range_median_daily) OVER w5 AS intraday_range_median_smooth5,
               avg(intraday_range_median_daily) OVER w10 AS intraday_range_median_smooth10,
               avg(return_dispersion_daily) OVER w3 AS return_dispersion_smooth3,
               avg(return_dispersion_daily) OVER w5 AS return_dispersion_smooth5,
               avg(return_dispersion_daily) OVER w10 AS return_dispersion_smooth10,
               avg(downside_mass_share_daily) OVER w3 AS downside_mass_share_smooth3,
               avg(downside_mass_share_daily) OVER w5 AS downside_mass_share_smooth5,
               avg(downside_mass_share_daily) OVER w10 AS downside_mass_share_smooth10,
               count(*) OVER w3 AS smooth_count3,count(*) OVER w5 AS smooth_count5,
               count(*) OVER w10 AS smooth_count10,
               min(cal_idx) OVER w3 AS smooth_min_idx3,min(cal_idx) OVER w5 AS smooth_min_idx5,
               min(cal_idx) OVER w10 AS smooth_min_idx10
        FROM daily_raw
        WINDOW
          w3 AS (PARTITION BY market_view,denominator ORDER BY trade_date ROWS BETWEEN 2 PRECEDING AND CURRENT ROW),
          w5 AS (PARTITION BY market_view,denominator ORDER BY trade_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW),
          w10 AS (PARTITION BY market_view,denominator ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW)
        ORDER BY trade_date,denominator,market_view
        """
    ).df()


def _attach_coordinates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out = out.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    out["view_valid"] = out["eligible_count"] >= out["market_view"].map(VIEW_MINIMUMS)
    smooth_stems = ("intraday_range_median_smooth", "return_dispersion_smooth", "downside_mass_share_smooth")
    for horizon in (3, 5, 10):
        valid = (out[f"smooth_count{horizon}"] == horizon) & (
            out["cal_idx"] - out[f"smooth_min_idx{horizon}"] == horizon - 1
        )
        for stem in smooth_stems:
            out.loc[~valid, f"{stem}{horizon}"] = np.nan
        grouped = out.groupby(["market_view", "denominator"], sort=False)
        lag_value = grouped["realized_volatility_median20"].shift(horizon)
        lag_idx = grouped["cal_idx"].shift(horizon)
        out[f"realized_volatility_change{horizon}"] = (
            out["realized_volatility_median20"] - lag_value
        ).where(out["cal_idx"] - lag_idx == horizon)
    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    out.loc[~out["view_valid"], raw_columns] = np.nan
    out["within_view_observation"] = out.groupby(
        ["market_view", "denominator"], sort=False
    ).cumcount() + 1
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for column in primary_columns:
            item[f"{column}_pit_expanding_pct"] = causal_expanding_percentile(item[column])
            item[f"{column}_pit_3y_pct"] = causal_rolling_percentile(item[column])
            item[f"{column}_pit_3y_robust_z"] = causal_rolling_robust_z(item[column])
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(["trade_date", "denominator", "market_view"])
    for column in primary_columns:
        all_values = out.loc[out["market_view"] == "ALL_A", ["trade_date", "denominator", column]].rename(columns={column: "_all"})
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left")
        out[f"{column}_relative_to_all"] = out[column] - out["_all"]
        counts = out.groupby(["trade_date", "denominator"])[column].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[column].rank(method="average", pct=True)
        out[f"{column}_relative_view_rank_pct"] = ranks.where(counts >= 3)
        out = out.drop(columns="_all")
    out["decision_at"] = out["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    out["available_at"] = out["decision_at"]
    out["snapshot_id"] = SNAPSHOT_ID
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def connected_components(correlation: pd.DataFrame, threshold: float = 0.85) -> list[list[str]]:
    remaining = set(str(item) for item in correlation.columns)
    components: list[list[str]] = []
    while remaining:
        stack = [sorted(remaining)[0]]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            stack.extend(
                str(other) for other in correlation.columns
                if str(other) not in component and np.isfinite(correlation.loc[current, other])
                and abs(float(correlation.loc[current, other])) >= threshold
            )
        components.append(sorted(component))
    return sorted(components, key=lambda items: min(MINIMAL_PRIORITY.index(item) for item in items))


def _diagnostics(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[list[str]], list[str], dict[str, str]]:
    primary = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    diagnostics: dict[str, dict] = {}
    for role, (column, neighbors) in ROLE_MAP.items():
        coverage = {
            str(view): float(group.loc[group["view_valid"] & (group["within_view_observation"] >= 60), column].notna().mean())
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
            wide = panel.loc[panel["market_view"] == view, ["trade_date", "denominator", column]].pivot(index="trade_date", columns="denominator", values=column)
            denominator_by_view[str(view)] = float(wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1])
        denominator_median = float(np.median(list(denominator_by_view.values())))
        eligible_cells = 0
        cell_checks: list[bool] = []
        year_support: dict[str, dict] = {}
        for (view, year), cell in primary.assign(year=primary["trade_date"].dt.year).groupby(["market_view", "year"], sort=True):
            values = cell[column].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                std = float(values.std(ddof=0))
                cell_checks.append(bool(np.isfinite(std) and std > 0))
                year_support[f"{view}:{year}"] = {"n": int(len(values)), "p10": float(values.quantile(0.1)), "median": float(values.median()), "p90": float(values.quantile(0.9))}
        nondegenerate = bool(eligible_cells and all(cell_checks))
        pit_expected = primary[column].notna().groupby([primary["market_view"], primary["denominator"]]).cumsum() >= MIN_PIT_HISTORY
        pit_coverage = float(primary.loc[pit_expected, f"{column}_pit_3y_pct"].notna().mean()) if pit_expected.any() else float("nan")
        relative_expected = (primary["market_view"] != "ALL_A") & primary[column].notna()
        relative_coverage = float(primary.loc[relative_expected, f"{column}_relative_to_all"].notna().mean())
        passed = bool(min(coverage.values()) >= 0.95 and min(neighbor_medians) >= 0.70 and denominator_median >= 0.90 and nondegenerate)
        diagnostics[role] = {
            "primary": column, "coverage_by_view": coverage,
            "minimum_raw_coverage": min(coverage.values()), "neighbors": neighbor_stats,
            "all_status_vs_non_st_by_view": denominator_by_view,
            "all_status_vs_non_st_median": denominator_median,
            "eligible_view_year_cells": eligible_cells,
            "all_eligible_cells_nondegenerate": nondegenerate, "year_support": year_support,
            "pit_3y_percentile_expected_coverage": pit_coverage,
            "relative_to_all_expected_coverage": relative_coverage,
            "construction_gate_pass": passed,
        }
    columns = {role: definition[0] for role, definition in ROLE_MAP.items()}
    correlation = primary.loc[primary["market_view"] == "ALL_A", list(columns.values())].rename(columns={value: key for key, value in columns.items()}).corr(method="spearman")
    components = connected_components(correlation)
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in MINIMAL_PRIORITY:
        if not diagnostics[role]["construction_gate_pass"]:
            excluded[role] = "construction_gate_failed"
            continue
        blockers = [other for other in accepted if abs(float(correlation.loc[role, other])) > 0.85]
        if blockers:
            excluded[role] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    return diagnostics, correlation, components, accepted, excluded


def _render_report(result: dict) -> str:
    lines = [
        "# MKT-VOL-001 volatility representation freeze", "", "## Boundary", "",
        f"- Status: `{result['status']}`", f"- Output: {result['population']['rows']:,} daily view/denominator rows.",
        "- Strategy membership, outcomes, future paths, and CY-011 read: **none**.",
        "- This establishes representation quality only, not panic, contraction/expansion usefulness, a habitat, or a strategy.",
        f"- Minimal nonredundant roles: `{', '.join(result['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "", "## Representation gates", "",
        "| Concept | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Gate | Minimal panel |",
        "|---|---:|---:|---:|---:|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in MINIMAL_PRIORITY:
        item = result["role_diagnostics"][role]
        worst = min(value["median_across_views"] for value in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(f"| {role} | {item['minimum_raw_coverage']:.3f} | {worst:.3f} | {item['all_status_vs_non_st_median']:.3f} | {item['pit_3y_percentile_expected_coverage']:.3f} | {'PASS' if item['construction_gate_pass'] else 'FAIL'} | {disposition} |")
    lines.extend([
        "", f"Outcome-blind components at absolute Spearman 0.85: `{result['latent_components']}`.",
        "", "Failed fixed representations leave their broader families open.",
        "", "## Reproducibility", "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise VolatilityFreezeError("spec is not frozen before result")
    paths, source_hashes = breadth._verify_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="mkt_vol_001_") as temporary:
        connection = duckdb.connect(str(Path(temporary) / "vol.duckdb"))
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='6GB'")
        connection.execute(f"SET temp_directory='{temporary}'")
        try:
            breadth._create_source_view(connection, paths)
            input_audit = breadth._audit_source(connection, spec)
            breadth._create_security_states(connection)
            _create_security_volatility(connection)
            daily = _create_daily(connection)
        finally:
            connection.close()
    panel = _attach_coordinates(daily)
    diagnostics, correlation, components, accepted, excluded = _diagnostics(panel)
    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    coordinate_columns = [column for primary in primary_columns for column in (
        f"{primary}_pit_expanding_pct", f"{primary}_pit_3y_pct", f"{primary}_pit_3y_robust_z",
        f"{primary}_relative_to_all", f"{primary}_relative_view_rank_pct",
    )]
    output = panel[["trade_date", "market_view", "denominator", "eligible_count", "view_valid", "within_view_observation", "decision_at", "available_at", "snapshot_id", *raw_columns, *coordinate_columns]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"], "status": "COMPLETE_STRATEGY_INDEPENDENT_VOLATILITY_REPRESENTATION_FREEZE",
        "usefulness_claim": "NONE", "strategy_or_future_fields_read": [],
        "input_audit": input_audit,
        "population": {"rows": int(len(output)), "first_date": str(output["trade_date"].min()), "last_date": str(output["trade_date"].max()), "views": int(output["market_view"].nunique())},
        "role_diagnostics": diagnostics,
        "primary_role_spearman_all_a": {str(row): {str(column): float(correlation.loc[row, column]) for column in correlation.columns} for row in correlation.index},
        "latent_components": components,
        "minimal_panel": {"accepted_roles": accepted, "excluded_roles": excluded},
        "limitations": {"panic": "NOT_ESTABLISHED", "usefulness": "NOT_TESTED", "pit_grade": "bounded PIT-B"},
        "hashes": {"spec_sha256": sha256_file(SPEC_PATH), "manifest_sha256": MANIFEST_SHA, "source_partitions": source_hashes, "panel_sha256": sha256_file(PANEL_PATH)},
    }
    RESULT_PATH.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    final = run()
    print(json.dumps({"status": final["status"], "accepted_roles": final["minimal_panel"]["accepted_roles"], "excluded_roles": final["minimal_panel"]["excluded_roles"], "latent_components": final["latent_components"], "panel_sha256": final["hashes"]["panel_sha256"]}, indent=2, sort_keys=True))
