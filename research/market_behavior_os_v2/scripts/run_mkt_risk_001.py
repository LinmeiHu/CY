#!/usr/bin/env python3
"""Construct the outcome-blind MKT-RISK-001 directional-tail panel."""

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

from run_mkt_brth_001 import (  # noqa: E402
    _audit_source,
    _create_security_states,
    _create_source_view,
    _verify_inputs,
    sha256_file,
)
from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-RISK-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-RISK-001_risk_appetite_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-RISK-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-RISK-001_risk_appetite_representation.md"
MANIFEST_SHA = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
SNAPSHOT_ID = f"CY-006:{MANIFEST_SHA}"
MIN_PIT_HISTORY = 504
VIEW_MINIMUMS = {"ALL_A": 1000, "SH_A": 400, "SZ_A": 400, "CHINEXT_BOARD": 200}

ROLE_MAP = {
    "central_direction": (
        "median_signed_limit_utilization",
        ("q40_signed_limit_utilization", "q60_signed_limit_utilization"),
    ),
    "upside_participation": (
        "upside_participation_gt0",
        ("upside_participation_gt05", "upside_participation_gt10"),
    ),
    "downside_participation": (
        "downside_participation_lt0",
        ("downside_participation_lt05", "downside_participation_lt10"),
    ),
    "upside_tail_depth": (
        "upside_tail_depth_q90",
        ("upside_tail_depth_q80", "upside_tail_depth_q95"),
    ),
    "downside_tail_depth": (
        "downside_tail_depth_q10",
        ("downside_tail_depth_q20", "downside_tail_depth_q05"),
    ),
    "upside_extreme_participation": (
        "upside_extreme_participation_70",
        ("upside_extreme_participation_50", "upside_extreme_participation_90"),
    ),
    "downside_extreme_participation": (
        "downside_extreme_participation_70",
        ("downside_extreme_participation_50", "downside_extreme_participation_90"),
    ),
    "upside_leadership_concentration": (
        "upside_mass_share_top10",
        ("upside_mass_share_top05", "upside_mass_share_top20"),
    ),
    "downside_pressure_concentration": (
        "downside_mass_share_worst10",
        ("downside_mass_share_worst05", "downside_mass_share_worst20"),
    ),
    "directional_industry_diffusion": (
        "industry_positive_median_fraction",
        ("industry_positive_mean_fraction", "industry_positive_participation_fraction"),
    ),
    "tail_risk_appetite_balance": (
        "tail_risk_appetite_balance_70",
        ("tail_risk_appetite_balance_50", "tail_risk_appetite_balance_90"),
    ),
}
MINIMAL_PRIORITY = tuple(ROLE_MAP)
SIGNED_COUNTERPARTS = {
    frozenset(("upside_participation", "downside_participation")),
    frozenset(("upside_tail_depth", "downside_tail_depth")),
    frozenset(("upside_extreme_participation", "downside_extreme_participation")),
    frozenset(("upside_leadership_concentration", "downside_pressure_concentration")),
}


class RiskRepresentationError(RuntimeError):
    """Fail-closed MKT-RISK-001 construction error."""


def _load_spec() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise RiskRepresentationError("scientific spec is not frozen")
    if spec["input"]["manifest_sha256"] != MANIFEST_SHA:
        raise RiskRepresentationError("manifest identity in spec changed")
    return spec


def signed_limit_utilization(frame: pd.DataFrame) -> pd.Series:
    """Return the exact signed registered-limit coordinate; invalid rows are missing."""
    required = ["close", "preclose", "up_limit_price", "down_limit_price", "limit_pct"]
    values = frame[required].astype(float)
    finite = np.isfinite(values).all(axis=1)
    valid = (
        finite
        & (values["close"] > 0)
        & (values["preclose"] > 0)
        & (values["up_limit_price"] > values["preclose"])
        & (values["preclose"] > values["down_limit_price"])
        & values["limit_pct"].isin((0.05, 0.10, 0.20))
        & (values["close"] <= values["up_limit_price"])
        & (values["close"] >= values["down_limit_price"])
    )
    result = pd.Series(np.nan, index=frame.index, dtype=float)
    positive = valid & (values["close"] >= values["preclose"])
    negative = valid & (values["close"] < values["preclose"])
    result.loc[positive] = (
        (values.loc[positive, "close"] - values.loc[positive, "preclose"])
        / (values.loc[positive, "up_limit_price"] - values.loc[positive, "preclose"])
    )
    result.loc[negative] = -(
        (values.loc[negative, "preclose"] - values.loc[negative, "close"])
        / (values.loc[negative, "preclose"] - values.loc[negative, "down_limit_price"])
    )
    if ((result.dropna() < -1.0) | (result.dropna() > 1.0)).any():
        raise RiskRepresentationError("signed limit utilization escaped exact bounds")
    return result


def _create_risk_core(connection: duckdb.DuckDBPyConnection) -> dict:
    connection.execute(
        """
        CREATE TEMP TABLE risk_core_raw AS
        SELECT c.trade_date,c.cal_idx,c.symbol,c.is_st,c.causal_industry,
               s.close,s.preclose,s.limit_pct,s.up_limit_price,s.down_limit_price,
               (s.close IS NOT NULL AND isfinite(s.close) AND s.close>0
                AND s.preclose IS NOT NULL AND isfinite(s.preclose) AND s.preclose>0
                AND s.up_limit_price IS NOT NULL AND isfinite(s.up_limit_price)
                AND s.down_limit_price IS NOT NULL AND isfinite(s.down_limit_price)
                AND s.up_limit_price>s.preclose AND s.preclose>s.down_limit_price
                AND s.limit_pct IN (0.05,0.10,0.20)
                AND s.close<=s.up_limit_price AND s.close>=s.down_limit_price) AS coordinate_valid
        FROM core c JOIN source s USING(trade_date,symbol)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_core AS
        SELECT *,CASE
          WHEN NOT coordinate_valid THEN NULL
          WHEN close>=preclose THEN (close-preclose)/(up_limit_price-preclose)
          ELSE -(preclose-close)/(preclose-down_limit_price)
        END AS signed_limit_utilization
        FROM risk_core_raw
        """
    )
    row = connection.execute(
        """
        SELECT count(*) AS core_rows,sum(coordinate_valid::INTEGER) AS valid_rows,
               sum((preclose IS NULL OR NOT isfinite(preclose) OR preclose<=0)::INTEGER) AS invalid_preclose,
               sum((up_limit_price IS NULL OR down_limit_price IS NULL
                    OR NOT isfinite(up_limit_price) OR NOT isfinite(down_limit_price)
                    OR NOT(up_limit_price>preclose AND preclose>down_limit_price))::INTEGER) AS invalid_limits,
               sum((limit_pct IS NULL OR limit_pct NOT IN (0.05,0.10,0.20))::INTEGER) AS invalid_regime,
               sum((close>up_limit_price)::INTEGER) AS close_above_limit,
               sum((close<down_limit_price)::INTEGER) AS close_below_limit,
               min(signed_limit_utilization),max(signed_limit_utilization)
        FROM risk_core
        """
    ).fetchone()
    result = {
        "core_rows": int(row[0]),
        "coordinate_valid_rows": int(row[1]),
        "coordinate_valid_fraction": float(row[1] / row[0]),
        "invalid_preclose_rows": int(row[2]),
        "invalid_limit_geometry_rows": int(row[3]),
        "invalid_registered_regime_rows": int(row[4]),
        "close_above_registered_limit_rows": int(row[5]),
        "close_below_registered_limit_rows": int(row[6]),
        "minimum_signed_limit_utilization": float(row[7]),
        "maximum_signed_limit_utilization": float(row[8]),
    }
    if result["minimum_signed_limit_utilization"] < -1.0 or result["maximum_signed_limit_utilization"] > 1.0:
        raise RiskRepresentationError("constructed coordinate escaped exact registered limits")
    return result


def _create_daily_risk(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE risk_view_rows AS
        SELECT 'ALL_A' AS market_view,* FROM risk_core
        UNION ALL SELECT 'SH_A',* FROM risk_core WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM risk_core WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM risk_core
          WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_expanded AS
        SELECT v.*,'ALL_STATUS' AS denominator FROM risk_view_rows v
        UNION ALL SELECT v.*,'NON_ST' FROM risk_view_rows v WHERE is_st IS FALSE
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_quantiles AS
        SELECT market_view,denominator,trade_date,
               quantile_cont(signed_limit_utilization,0.05) FILTER (WHERE coordinate_valid) AS q05,
               quantile_cont(signed_limit_utilization,0.10) FILTER (WHERE coordinate_valid) AS q10,
               quantile_cont(signed_limit_utilization,0.20) FILTER (WHERE coordinate_valid) AS q20,
               quantile_cont(signed_limit_utilization,0.40) FILTER (WHERE coordinate_valid) AS q40,
               quantile_cont(signed_limit_utilization,0.50) FILTER (WHERE coordinate_valid) AS q50,
               quantile_cont(signed_limit_utilization,0.60) FILTER (WHERE coordinate_valid) AS q60,
               quantile_cont(signed_limit_utilization,0.80) FILTER (WHERE coordinate_valid) AS q80,
               quantile_cont(signed_limit_utilization,0.90) FILTER (WHERE coordinate_valid) AS q90,
               quantile_cont(signed_limit_utilization,0.95) FILTER (WHERE coordinate_valid) AS q95
        FROM risk_expanded GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_daily_security AS
        SELECT e.market_view,e.denominator,e.trade_date,max(e.cal_idx) AS cal_idx,
               count(*) AS core_count,sum(e.coordinate_valid::INTEGER) AS eligible_count,
               count(e.causal_industry) FILTER (WHERE e.coordinate_valid) AS industry_mapped_count,
               q.q50 AS median_signed_limit_utilization,
               q.q40 AS q40_signed_limit_utilization,q.q60 AS q60_signed_limit_utilization,
               avg((e.signed_limit_utilization>0)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_participation_gt0,
               avg((e.signed_limit_utilization>0.05)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_participation_gt05,
               avg((e.signed_limit_utilization>0.10)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_participation_gt10,
               avg((e.signed_limit_utilization<0)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_participation_lt0,
               avg((e.signed_limit_utilization< -0.05)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_participation_lt05,
               avg((e.signed_limit_utilization< -0.10)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_participation_lt10,
               q.q90 AS upside_tail_depth_q90,q.q80 AS upside_tail_depth_q80,q.q95 AS upside_tail_depth_q95,
               -q.q10 AS downside_tail_depth_q10,-q.q20 AS downside_tail_depth_q20,-q.q05 AS downside_tail_depth_q05,
               avg((e.signed_limit_utilization>=0.70)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_extreme_participation_70,
               avg((e.signed_limit_utilization>=0.50)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_extreme_participation_50,
               avg((e.signed_limit_utilization>=0.90)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS upside_extreme_participation_90,
               avg((e.signed_limit_utilization<= -0.70)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_extreme_participation_70,
               avg((e.signed_limit_utilization<= -0.50)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_extreme_participation_50,
               avg((e.signed_limit_utilization<= -0.90)::DOUBLE) FILTER (WHERE e.coordinate_valid) AS downside_extreme_participation_90,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization>0
                              AND e.signed_limit_utilization>=q.q90 THEN e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(e.signed_limit_utilization,0) ELSE 0 END),0) AS upside_mass_share_top10,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization>0
                              AND e.signed_limit_utilization>=q.q95 THEN e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(e.signed_limit_utilization,0) ELSE 0 END),0) AS upside_mass_share_top05,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization>0
                              AND e.signed_limit_utilization>=q.q80 THEN e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(e.signed_limit_utilization,0) ELSE 0 END),0) AS upside_mass_share_top20,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization<0
                              AND e.signed_limit_utilization<=q.q10 THEN -e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(-e.signed_limit_utilization,0) ELSE 0 END),0) AS downside_mass_share_worst10,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization<0
                              AND e.signed_limit_utilization<=q.q05 THEN -e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(-e.signed_limit_utilization,0) ELSE 0 END),0) AS downside_mass_share_worst05,
               sum(CASE WHEN e.coordinate_valid AND e.signed_limit_utilization<0
                              AND e.signed_limit_utilization<=q.q20 THEN -e.signed_limit_utilization ELSE 0 END)
                 /nullif(sum(CASE WHEN e.coordinate_valid THEN greatest(-e.signed_limit_utilization,0) ELSE 0 END),0) AS downside_mass_share_worst20
        FROM risk_expanded e JOIN risk_quantiles q USING(market_view,denominator,trade_date)
        GROUP BY e.market_view,e.denominator,e.trade_date,q.q05,q.q10,q.q20,q.q40,q.q50,q.q60,q.q80,q.q90,q.q95
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_industry_groups AS
        SELECT market_view,denominator,trade_date,causal_industry,count(*) AS member_count,
               median(signed_limit_utilization) AS median_u,avg(signed_limit_utilization) AS mean_u,
               avg((signed_limit_utilization>0)::DOUBLE) AS positive_fraction,
               avg((signed_limit_utilization<0)::DOUBLE) AS negative_fraction
        FROM risk_expanded
        WHERE coordinate_valid AND causal_industry IS NOT NULL
        GROUP BY 1,2,3,4 HAVING count(*)>=5
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE risk_industry_daily AS
        SELECT market_view,denominator,trade_date,count(*) AS included_industry_count,
               avg((median_u>0)::DOUBLE) AS industry_positive_median_fraction,
               avg((mean_u>0)::DOUBLE) AS industry_positive_mean_fraction,
               avg((positive_fraction>negative_fraction)::DOUBLE) AS industry_positive_participation_fraction
        FROM risk_industry_groups GROUP BY 1,2,3
        """
    )
    return connection.execute(
        """
        SELECT s.*,s.eligible_count::DOUBLE/s.core_count AS limit_eligible_fraction,
               s.industry_mapped_count::DOUBLE/s.eligible_count AS industry_mapping_coverage,
               i.included_industry_count,i.industry_positive_median_fraction,
               i.industry_positive_mean_fraction,i.industry_positive_participation_fraction,
               s.upside_extreme_participation_70-s.downside_extreme_participation_70 AS tail_risk_appetite_balance_70,
               s.upside_extreme_participation_50-s.downside_extreme_participation_50 AS tail_risk_appetite_balance_50,
               s.upside_extreme_participation_90-s.downside_extreme_participation_90 AS tail_risk_appetite_balance_90
        FROM risk_daily_security s LEFT JOIN risk_industry_daily i
          USING(market_view,denominator,trade_date)
        ORDER BY trade_date,denominator,market_view
        """
    ).df()


def _attach_coordinates(frame: pd.DataFrame, spec: dict) -> pd.DataFrame:
    out = frame.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out = out.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    out["view_minimum_count"] = out["market_view"].map(VIEW_MINIMUMS).astype(int)
    out["view_valid"] = (
        (out["core_count"] >= out["view_minimum_count"])
        & (out["limit_eligible_fraction"] >= spec["gates"]["daily_limit_eligible_fraction"])
    )
    out["industry_valid"] = (
        out["view_valid"]
        & (out["industry_mapping_coverage"] >= spec["universe"]["industry_mapping_minimum"])
        & (out["included_industry_count"] >= spec["universe"]["industry_count_minimum"])
    )
    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    industry_columns = set(ROLE_MAP["directional_industry_diffusion"])
    out.loc[~out["view_valid"], [c for c in raw_columns if c not in industry_columns]] = np.nan
    out.loc[~out["industry_valid"], list(industry_columns)] = np.nan
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
        all_values = out.loc[
            out["market_view"] == "ALL_A", ["trade_date", "denominator", column]
        ].rename(columns={column: "_all_value"})
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left")
        out[f"{column}_relative_to_all"] = out[column] - out["_all_value"]
        counts = out.groupby(["trade_date", "denominator"])[column].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[column].rank(method="average", pct=True)
        out[f"{column}_relative_view_rank_pct"] = ranks.where(counts >= 3)
        out = out.drop(columns="_all_value")
    out["decision_at"] = out["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    out["available_at"] = out["decision_at"]
    out["snapshot_id"] = SNAPSHOT_ID
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def _load_external_controls(spec: dict) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    keys = ["trade_date", "market_view", "denominator"]
    for item in spec["frozen_external_controls"].values():
        if not isinstance(item, dict):
            continue
        path = ROOT / item["path"]
        if sha256_file(path) != item["sha256"]:
            raise RiskRepresentationError(f"frozen external panel hash changed: {path.name}")
        frame = pd.read_csv(path, usecols=[*keys, *item["columns"]])
        frame["trade_date"] = pd.to_datetime(frame["trade_date"])
        if frame["trade_date"].max() > pd.Timestamp("2023-12-31"):
            raise RiskRepresentationError("post-2023 external control entered construction")
        pieces.append(frame)
    merged = pieces[0]
    for piece in pieces[1:]:
        merged = merged.merge(piece, on=keys, how="inner", validate="one_to_one")
    return merged


def _connected_components(correlation: pd.DataFrame) -> list[list[str]]:
    remaining = set(str(item) for item in correlation.columns)
    components: list[list[str]] = []
    while remaining:
        seed = min(remaining, key=MINIMAL_PRIORITY.index)
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            for other in correlation.columns:
                other = str(other)
                if other in component:
                    continue
                value = correlation.loc[current, other]
                if np.isfinite(value) and abs(float(value)) >= 0.85:
                    stack.append(other)
        components.append(sorted(component, key=MINIMAL_PRIORITY.index))
    return sorted(components, key=lambda items: MINIMAL_PRIORITY.index(items[0]))


def _diagnostics(panel: pd.DataFrame, controls: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[list[str]], dict, list[str], dict[str, str]]:
    diagnostics: dict[str, dict] = {}
    primary_columns = {role: definition[0] for role, definition in ROLE_MAP.items()}
    primary_panel = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    for role, (primary, neighbors) in ROLE_MAP.items():
        coverage_by_view: dict[str, float] = {}
        for market_view, group in primary_panel.groupby("market_view", sort=True):
            expected = group["industry_valid"] if role == "directional_industry_diffusion" else group["view_valid"]
            coverage_by_view[str(market_view)] = float(group.loc[expected, primary].notna().mean())
        neighbor_stats: dict[str, dict] = {}
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_view = {
                str(market_view): float(group[[primary, neighbor]].corr(method="spearman").iloc[0, 1])
                for market_view, group in primary_panel.groupby("market_view", sort=True)
            }
            median_rho = float(np.nanmedian(list(by_view.values())))
            neighbor_medians.append(median_rho)
            neighbor_stats[neighbor] = {"by_view": by_view, "median_across_views": median_rho}

        denominator_by_view: dict[str, float] = {}
        for market_view in sorted(panel["market_view"].unique()):
            wide = panel.loc[panel["market_view"] == market_view, ["trade_date", "denominator", primary]].pivot(
                index="trade_date", columns="denominator", values=primary
            )
            denominator_by_view[str(market_view)] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.nanmedian(list(denominator_by_view.values())))

        cell_checks: list[bool] = []
        eligible_cells = 0
        year_support: dict[str, dict] = {}
        with_year = primary_panel.assign(year=primary_panel["trade_date"].dt.year)
        for (market_view, year), cell in with_year.groupby(["market_view", "year"], sort=True):
            values = cell[primary].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                std = float(values.std(ddof=0))
                cell_checks.append(bool(np.isfinite(std) and std > 0))
                year_support[f"{market_view}:{year}"] = {
                    "n": int(len(values)),
                    "p10": float(values.quantile(0.10)),
                    "median": float(values.median()),
                    "p90": float(values.quantile(0.90)),
                }
        nondegenerate = bool(eligible_cells > 0 and all(cell_checks))
        pit_expected = primary_panel[primary].notna().groupby(primary_panel["market_view"]).cumsum() >= MIN_PIT_HISTORY
        pit_coverage = float(
            primary_panel.loc[pit_expected, f"{primary}_pit_3y_pct"].notna().mean()
        ) if pit_expected.any() else float("nan")
        relative_expected = (primary_panel["market_view"] != "ALL_A") & primary_panel[primary].notna()
        relative_coverage = float(
            primary_panel.loc[relative_expected, f"{primary}_relative_to_all"].notna().mean()
        )
        passed = bool(
            min(coverage_by_view.values()) >= 0.95
            and min(neighbor_medians) >= 0.70
            and denominator_median >= 0.90
            and nondegenerate
            and pit_coverage >= 0.95
            and relative_coverage >= 0.95
        )
        diagnostics[role] = {
            "primary": primary,
            "coverage_by_view": coverage_by_view,
            "minimum_raw_coverage": min(coverage_by_view.values()),
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

    all_a = primary_panel.loc[primary_panel["market_view"] == "ALL_A", [
        primary_columns[role] for role in MINIMAL_PRIORITY
    ]].rename(columns={primary_columns[role]: role for role in MINIMAL_PRIORITY})
    correlation = all_a.corr(method="spearman")
    components = _connected_components(correlation)

    keys = ["trade_date", "market_view", "denominator"]
    joined = panel[keys + list(primary_columns.values())].merge(
        controls, on=keys, how="inner", validate="one_to_one"
    )
    control_columns = [column for column in controls.columns if column not in keys]
    external: dict[str, dict] = {}
    externally_redundant: dict[str, str] = {}
    for role, primary in primary_columns.items():
        external[role] = {}
        for control in control_columns:
            by_group: dict[str, float] = {}
            for (view, denominator), group in joined.groupby(["market_view", "denominator"], sort=True):
                by_group[f"{view}:{denominator}"] = float(
                    group[[primary, control]].corr(method="spearman").iloc[0, 1]
                )
            median_absolute = float(np.nanmedian(np.abs(list(by_group.values()))))
            external[role][control] = {
                "by_group": by_group,
                "median_absolute_spearman": median_absolute,
            }
            if median_absolute >= 0.85 and role not in externally_redundant:
                externally_redundant[role] = control

    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in MINIMAL_PRIORITY:
        if not diagnostics[role]["construction_gate_pass"]:
            excluded[role] = "construction_gate_failed"
            continue
        if role in externally_redundant:
            excluded[role] = "externally_redundant_with:" + externally_redundant[role]
            continue
        if role == "tail_risk_appetite_balance" and {
            "upside_extreme_participation", "downside_extreme_participation"
        }.issubset(accepted):
            excluded[role] = (
                "deterministic_composite_of:upside_extreme_participation,"
                "downside_extreme_participation"
            )
            continue
        blockers: list[str] = []
        for other in accepted:
            rho = float(correlation.loc[role, other])
            signed_exception = frozenset((role, other)) in SIGNED_COUNTERPARTS and rho < 0
            if abs(rho) >= 0.85 and not signed_exception:
                blockers.append(other)
        if blockers:
            excluded[role] = "internally_redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    return diagnostics, correlation, components, external, accepted, excluded


def _matrix_dict(frame: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        str(row): {str(column): float(frame.loc[row, column]) for column in frame.columns}
        for row in frame.index
    }


def _render_report(result: dict) -> str:
    lines = [
        "# MKT-RISK-001 directional-tail and risk-appetite representation",
        "",
        "## Construction boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Source: {result['input_audit']['rows']:,} CY-006 rows, {result['input_audit']['first_date']}..{result['input_audit']['last_date']}.",
        f"- Causal core: {result['limit_coordinate_audit']['core_rows']:,} security-dates; exact valid limit coordinate on {result['limit_coordinate_audit']['coordinate_valid_fraction']:.6f}.",
        f"- Coordinate support: [{result['limit_coordinate_audit']['minimum_signed_limit_utilization']:.6f}, {result['limit_coordinate_audit']['maximum_signed_limit_utilization']:.6f}].",
        f"- Group/dates invalidated below the unchanged 99% limit-coordinate gate: {result['limit_coordinate_audit']['invalidated_group_dates_below_frozen_gate']}.",
        "- Strategy fields, future returns, MKT-SHOCK-001 score, and CY-011 read: **none**.",
        "- Representation stability is not panic, forecast, habitat, or strategy usefulness.",
        "",
        "## Frozen representation gates",
        "",
        "| Role | Min coverage | Worst neighbor rho | ST rho | PIT | Relative | Gate | Novel minimal panel |",
        "|---|---:|---:|---:|---:|---:|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in MINIMAL_PRIORITY:
        item = result["role_diagnostics"][role]
        worst = min(value["median_across_views"] for value in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(
            f"| {role} | {item['minimum_raw_coverage']:.3f} | {worst:.3f} | "
            f"{item['all_status_vs_non_st_median']:.3f} | {item['pit_3y_percentile_expected_coverage']:.3f} | "
            f"{item['relative_to_all_expected_coverage']:.3f} | {'PASS' if item['construction_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend([
        "",
        "## Outcome-blind compression",
        "",
        f"- Absolute-Spearman 0.85 components: `{result['latent_components']}`.",
        f"- Novel minimal roles: `{', '.join(result['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "- Upside/downside counterparts remain separately diagnosed; high negative correlation alone does not merge their semantics.",
        "- External controls are frozen discovery/leadership and accepted volatility roles only. External redundancy is descriptive and outcome-blind.",
        "",
        "| Role | Largest external median absolute rho | Control |",
        "|---|---:|---|",
    ])
    for role in MINIMAL_PRIORITY:
        best_control, best_item = max(
            result["external_redundancy"][role].items(),
            key=lambda pair: pair[1]["median_absolute_spearman"],
        )
        lines.append(
            f"| {role} | {best_item['median_absolute_spearman']:.3f} | `{best_control}` |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- CY-006 manifest SHA-256: `{result['hashes']['manifest_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec = _load_spec()
    paths, source_hashes = _verify_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="mkt_risk_001_") as temporary:
        connection = duckdb.connect(str(Path(temporary) / "risk.duckdb"))
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='6GB'")
        connection.execute(f"SET temp_directory='{temporary}'")
        try:
            _create_source_view(connection, paths)
            input_audit = _audit_source(connection, spec)
            _create_security_states(connection)
            limit_audit = _create_risk_core(connection)
            daily = _create_daily_risk(connection)
        finally:
            connection.close()

    panel = _attach_coordinates(daily, spec)
    if panel["trade_date"].max() > pd.Timestamp("2023-12-31"):
        raise RiskRepresentationError("post-2023 row entered output")
    eligible_days = panel.loc[panel["core_count"] >= panel["view_minimum_count"]]
    minimum_daily_limit_fraction = float(eligible_days["limit_eligible_fraction"].min())
    failed_limit_cells = eligible_days.loc[
        eligible_days["limit_eligible_fraction"] < spec["gates"]["daily_limit_eligible_fraction"],
        ["trade_date", "market_view", "denominator", "core_count", "eligible_count", "limit_eligible_fraction"],
    ].copy()
    controls = _load_external_controls(spec)
    diagnostics, correlation, components, external, accepted, excluded = _diagnostics(panel, controls)

    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    coordinate_columns = [
        column
        for primary in primary_columns
        for column in (
            f"{primary}_pit_expanding_pct", f"{primary}_pit_3y_pct",
            f"{primary}_pit_3y_robust_z", f"{primary}_relative_to_all",
            f"{primary}_relative_view_rank_pct",
        )
    ]
    output_columns = [
        "trade_date", "market_view", "denominator", "core_count", "eligible_count",
        "limit_eligible_fraction", "industry_mapped_count", "industry_mapping_coverage",
        "included_industry_count", "view_valid", "industry_valid", "within_view_observation",
        "decision_at", "available_at", "snapshot_id", *raw_columns, *coordinate_columns,
    ]
    output = panel[output_columns].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_STRATEGY_INDEPENDENT_DIRECTIONAL_TAIL_REPRESENTATION",
        "usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "shock_score_read": False,
        "input_audit": input_audit,
        "limit_coordinate_audit": {
            **limit_audit,
            "minimum_daily_group_eligible_fraction": minimum_daily_limit_fraction,
            "invalidated_group_dates_below_frozen_gate": int(len(failed_limit_cells)),
            "first_invalidated_group_dates": [
                {
                    "trade_date": item.trade_date.strftime("%Y-%m-%d"),
                    "market_view": str(item.market_view),
                    "denominator": str(item.denominator),
                    "core_count": int(item.core_count),
                    "eligible_count": int(item.eligible_count),
                    "limit_eligible_fraction": float(item.limit_eligible_fraction),
                }
                for item in failed_limit_cells.sort_values(
                    ["trade_date", "denominator", "market_view"]
                ).itertuples(index=False)
            ][:25],
        },
        "population": {
            "rows": int(len(output)),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "market_views": int(output["market_view"].nunique()),
            "denominators": sorted(str(item) for item in output["denominator"].unique()),
        },
        "role_diagnostics": diagnostics,
        "primary_role_spearman_all_a": _matrix_dict(correlation),
        "latent_components": components,
        "external_redundancy": external,
        "minimal_panel": {
            "priority": list(MINIMAL_PRIORITY),
            "accepted_roles": accepted,
            "excluded_roles": excluded,
            "signed_pair_rule_applied": True,
        },
        "limitations": {
            "pit_grade": "bounded PIT-B",
            "listing_day_limit_semantics": "UNKNOWN_ROWS_FAIL_CLOSED_AND_120_SESSION_CORE_REQUIRED",
            "constituent_index_state": "UNAVAILABLE_NO_REGISTERED_HISTORICAL_MEMBERSHIP",
            "stress_interaction": "NOT_TESTED",
            "economic_usefulness": "NOT_TESTED",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "manifest_sha256": MANIFEST_SHA,
            "source_partitions": source_hashes,
            "breadth_control_sha256": spec["frozen_external_controls"]["breadth_panel"]["sha256"],
            "volatility_control_sha256": spec["frozen_external_controls"]["volatility_panel"]["sha256"],
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
        "rows": final["population"]["rows"],
        "limit_coordinate_audit": final["limit_coordinate_audit"],
        "accepted_roles": final["minimal_panel"]["accepted_roles"],
        "excluded_roles": final["minimal_panel"]["excluded_roles"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
