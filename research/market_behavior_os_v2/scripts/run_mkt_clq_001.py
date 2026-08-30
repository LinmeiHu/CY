#!/usr/bin/env python3
"""Build the outcome-blind MKT-CLQ-001 correlation/liquidity panel."""

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


SPEC_PATH = PROGRAM / "experiments/MKT-CLQ-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-CLQ-001_correlation_liquidity_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-CLQ-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-CLQ-001_correlation_liquidity_representation.md"
MANIFEST_SHA = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
SNAPSHOT_ID = f"CY-006:{MANIFEST_SHA}"
MIN_PIT_HISTORY = 504
VIEW_MINIMUMS = {"ALL_A": 1000, "SH_A": 400, "SZ_A": 400, "CHINEXT_BOARD": 200}

ROLE_MAP = {
    "co_movement": ("correlation_median20", ("correlation_median10", "correlation_median40")),
    "directional_synchronization": (
        "directional_sync_balance5",
        ("directional_sync_balance3", "directional_sync_balance10"),
    ),
    "liquidity_activity": (
        "liquidity_median_amount_ratio20",
        ("liquidity_median_amount_ratio10", "liquidity_median_amount_ratio60"),
    ),
    "liquidity_participation": (
        "liquidity_fraction_amount_ratio20_above1",
        (
            "liquidity_fraction_amount_ratio10_above1",
            "liquidity_fraction_amount_ratio60_above1",
        ),
    ),
    "turnover_level": (
        "liquidity_turnover_median",
        ("liquidity_turnover_q40", "liquidity_turnover_q60"),
    ),
    "liquidity_concentration": (
        "liquidity_amount_share_top10",
        ("liquidity_amount_share_top5", "liquidity_amount_share_top20"),
    ),
    "industry_liquidity_diffusion": (
        "industry_liquidity_diffusion20",
        ("industry_liquidity_diffusion10", "industry_liquidity_diffusion60"),
    ),
    "liquidity_change": (
        "liquidity_activity_change5",
        ("liquidity_activity_change3", "liquidity_activity_change10"),
    ),
}
MINIMAL_PRIORITY = tuple(ROLE_MAP)


class CorrelationLiquidityFreezeError(RuntimeError):
    """Fail-closed correlation/liquidity construction error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_spec() -> dict:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise CorrelationLiquidityFreezeError("spec is not frozen before construction")
    return spec


def _liquidity_audit(connection: duckdb.DuckDBPyConnection, spec: dict) -> dict:
    row = connection.execute(
        """
        SELECT count(*) AS eligible_rows,
               sum((s.amount IS NOT NULL AND isfinite(s.amount) AND s.amount>0)::INTEGER)
                 AS positive_amount_rows,
               sum((s.turnover_fraction IS NOT NULL AND isfinite(s.turnover_fraction)
                    AND s.turnover_fraction>=0 AND s.turnover_pct IS NOT NULL
                    AND isfinite(s.turnover_pct) AND s.turnover_pct>=0)::INTEGER)
                 AS valid_turnover_rows,
               max(abs(s.turnover_fraction-s.turnover_pct/100.0)) AS max_unit_difference,
               sum((s.amount<>round(s.amount,3))::INTEGER) AS amount_scale_failures,
               count(DISTINCT s.snapshot_id) AS snapshot_count
        FROM base b JOIN source s USING(symbol,trade_date)
        WHERE b.history_valid AND b.current_valid
        """
    ).fetchone()
    audit = {
        "eligible_rows": int(row[0]),
        "positive_amount_rows": int(row[1]),
        "valid_turnover_rows": int(row[2]),
        "maximum_turnover_unit_difference": float(row[3]),
        "amount_scale_failures_above_3_decimals": int(row[4]),
        "snapshot_count": int(row[5]),
    }
    frozen = spec["input"]
    if audit["eligible_rows"] != frozen["eligible_liquidity_audit_rows"]:
        raise CorrelationLiquidityFreezeError("eligible liquidity population changed")
    if audit["positive_amount_rows"] != audit["eligible_rows"]:
        raise CorrelationLiquidityFreezeError("eligible amount is not finite and positive")
    if audit["valid_turnover_rows"] != audit["eligible_rows"]:
        raise CorrelationLiquidityFreezeError("eligible turnover is not finite and nonnegative")
    if audit["maximum_turnover_unit_difference"] > 1e-12:
        raise CorrelationLiquidityFreezeError("turnover unit contract failed")
    if audit["amount_scale_failures_above_3_decimals"] != 0:
        raise CorrelationLiquidityFreezeError("registered amount exceeds exact frozen scale")
    return audit


def _create_clq_security(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE amount_windows AS
        SELECT symbol,trade_date,cal_idx,
               avg(amount) OVER w10 AS prior_amount_mean10,
               avg(amount) OVER w20 AS prior_amount_mean20,
               avg(amount) OVER w60 AS prior_amount_mean60,
               count(amount) OVER w10 AS prior_amount_count10,
               count(amount) OVER w20 AS prior_amount_count20,
               count(amount) OVER w60 AS prior_amount_count60,
               lag(cal_idx,10) OVER w AS prior_idx10,
               lag(cal_idx,20) OVER w AS prior_idx20,
               lag(cal_idx,60) OVER w AS prior_idx60
        FROM stock_lagged
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
          w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
          w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE clq_core AS
        SELECT c.trade_date,c.cal_idx,c.symbol,c.is_st,c.causal_industry,
               sl.step_log_return,sl.amount,s.turnover_fraction,
               sl.amount/w.prior_amount_mean10 AS amount_ratio10,
               sl.amount/w.prior_amount_mean20 AS amount_ratio20,
               sl.amount/w.prior_amount_mean60 AS amount_ratio60
        FROM core c
        JOIN stock_lagged sl
          ON c.symbol=sl.symbol AND c.trade_date=sl.trade_date
        JOIN amount_windows w
          ON c.symbol=w.symbol AND c.trade_date=w.trade_date AND c.cal_idx=w.cal_idx
        JOIN source s
          ON c.symbol=s.symbol AND c.trade_date=s.trade_date
        WHERE sl.step_log_return IS NOT NULL AND isfinite(sl.step_log_return)
          AND sl.amount IS NOT NULL AND isfinite(sl.amount) AND sl.amount>0
          AND s.turnover_fraction IS NOT NULL AND isfinite(s.turnover_fraction)
          AND s.turnover_fraction>=0
          AND w.prior_amount_count10=10 AND w.prior_amount_count20=20
          AND w.prior_amount_count60=60
          AND c.cal_idx-w.prior_idx10=10 AND c.cal_idx-w.prior_idx20=20
          AND c.cal_idx-w.prior_idx60=60
          AND w.prior_amount_mean10>0 AND w.prior_amount_mean20>0
          AND w.prior_amount_mean60>0
        """
    )
    bad = connection.execute(
        """
        SELECT count(*) FROM clq_core
        WHERE NOT isfinite(amount_ratio10) OR NOT isfinite(amount_ratio20)
           OR NOT isfinite(amount_ratio60) OR amount_ratio10<0
           OR amount_ratio20<0 OR amount_ratio60<0
        """
    ).fetchone()[0]
    if bad:
        raise CorrelationLiquidityFreezeError("nonfinite activity ratio entered core")


def _create_daily_clq(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE view_rows AS
        SELECT 'ALL_A' AS market_view,* FROM clq_core
        UNION ALL SELECT 'SH_A',* FROM clq_core WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM clq_core WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM clq_core
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
        CREATE TEMP TABLE market_steps AS
        SELECT market_view,denominator,trade_date,count(*) AS security_count,
               sum(step_log_return) AS return_sum
        FROM expanded GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE security_market AS
        SELECT e.*,(m.return_sum-e.step_log_return)/(m.security_count-1)
                 AS leave_one_out_view_return
        FROM expanded e JOIN market_steps m USING(market_view,denominator,trade_date)
        WHERE m.security_count>=2
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE security_correlations AS
        SELECT *,corr(step_log_return,leave_one_out_view_return) OVER w10 AS corr10,
               corr(step_log_return,leave_one_out_view_return) OVER w20 AS corr20,
               corr(step_log_return,leave_one_out_view_return) OVER w40 AS corr40,
               count(*) OVER w10 AS corr_count10,count(*) OVER w20 AS corr_count20,
               count(*) OVER w40 AS corr_count40,
               min(cal_idx) OVER w10 AS corr_min_idx10,
               min(cal_idx) OVER w20 AS corr_min_idx20,
               min(cal_idx) OVER w40 AS corr_min_idx40
        FROM security_market
        WINDOW
          w10 AS (PARTITION BY market_view,denominator,symbol ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY market_view,denominator,symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w40 AS (PARTITION BY market_view,denominator,symbol ORDER BY trade_date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE amount_thresholds AS
        SELECT market_view,denominator,trade_date,
               quantile_cont(amount,0.95) AS q95,quantile_cont(amount,0.90) AS q90,
               quantile_cont(amount,0.80) AS q80
        FROM security_correlations GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_security AS
        SELECT e.market_view,e.denominator,e.trade_date,max(e.cal_idx) AS cal_idx,
               count(*) AS eligible_count,count(e.causal_industry) AS industry_mapped_count,
               median(e.corr10) FILTER (
                 WHERE e.corr_count10=10 AND e.cal_idx-e.corr_min_idx10=9
                   AND isfinite(e.corr10)) AS correlation_median10,
               median(e.corr20) FILTER (
                 WHERE e.corr_count20=20 AND e.cal_idx-e.corr_min_idx20=19
                   AND isfinite(e.corr20)) AS correlation_median20,
               median(e.corr40) FILTER (
                 WHERE e.corr_count40=40 AND e.cal_idx-e.corr_min_idx40=39
                   AND isfinite(e.corr40)) AS correlation_median40,
               avg(sign(e.step_log_return)*sign(e.leave_one_out_view_return))
                 AS directional_sync_balance_daily,
               median(e.amount_ratio10) AS liquidity_median_amount_ratio10,
               median(e.amount_ratio20) AS liquidity_median_amount_ratio20,
               median(e.amount_ratio60) AS liquidity_median_amount_ratio60,
               avg((e.amount_ratio10>1)::DOUBLE)
                 AS liquidity_fraction_amount_ratio10_above1,
               avg((e.amount_ratio20>1)::DOUBLE)
                 AS liquidity_fraction_amount_ratio20_above1,
               avg((e.amount_ratio60>1)::DOUBLE)
                 AS liquidity_fraction_amount_ratio60_above1,
               quantile_cont(e.turnover_fraction,0.40) AS liquidity_turnover_q40,
               median(e.turnover_fraction) AS liquidity_turnover_median,
               quantile_cont(e.turnover_fraction,0.60) AS liquidity_turnover_q60,
               CAST(sum(CASE WHEN e.amount>=t.q95
                             THEN CAST(e.amount AS DECIMAL(38,3))
                             ELSE CAST(0 AS DECIMAL(38,3)) END) AS DOUBLE)
                 /CAST(sum(CAST(e.amount AS DECIMAL(38,3))) AS DOUBLE)
                 AS liquidity_amount_share_top5,
               CAST(sum(CASE WHEN e.amount>=t.q90
                             THEN CAST(e.amount AS DECIMAL(38,3))
                             ELSE CAST(0 AS DECIMAL(38,3)) END) AS DOUBLE)
                 /CAST(sum(CAST(e.amount AS DECIMAL(38,3))) AS DOUBLE)
                 AS liquidity_amount_share_top10,
               CAST(sum(CASE WHEN e.amount>=t.q80
                             THEN CAST(e.amount AS DECIMAL(38,3))
                             ELSE CAST(0 AS DECIMAL(38,3)) END) AS DOUBLE)
                 /CAST(sum(CAST(e.amount AS DECIMAL(38,3))) AS DOUBLE)
                 AS liquidity_amount_share_top20,
               sum(CAST(e.amount AS DECIMAL(38,3))) AS amount_total_exact,
               sum(CASE WHEN e.amount<t.q90 THEN CAST(e.amount AS DECIMAL(38,3))
                        ELSE CAST(0 AS DECIMAL(38,3)) END)
                 +sum(CASE WHEN e.amount>=t.q90 THEN CAST(e.amount AS DECIMAL(38,3))
                           ELSE CAST(0 AS DECIMAL(38,3)) END)
                 AS amount_partition_total_exact
        FROM security_correlations e JOIN amount_thresholds t
          USING(market_view,denominator,trade_date)
        GROUP BY e.market_view,e.denominator,e.trade_date
        """
    )
    first_conservation_failure = connection.execute(
        """
        SELECT market_view,denominator,trade_date,amount_total_exact,
               amount_partition_total_exact,
               amount_total_exact-amount_partition_total_exact AS difference
        FROM daily_security
        WHERE amount_total_exact<>amount_partition_total_exact
           OR amount_total_exact IS NULL OR amount_total_exact<=0
        ORDER BY trade_date,denominator,market_view LIMIT 1
        """
    ).fetchone()
    if first_conservation_failure:
        raise CorrelationLiquidityFreezeError(
            "daily liquidity amount did not conserve exactly; first_difference="
            + repr(first_conservation_failure)
        )
    connection.execute(
        """
        CREATE TEMP TABLE industry_groups AS
        SELECT market_view,denominator,trade_date,causal_industry,count(*) AS member_count,
               avg((amount_ratio10>1)::DOUBLE) AS active10,
               avg((amount_ratio20>1)::DOUBLE) AS active20,
               avg((amount_ratio60>1)::DOUBLE) AS active60
        FROM security_correlations WHERE causal_industry IS NOT NULL
        GROUP BY 1,2,3,4 HAVING count(*)>=5
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_daily AS
        SELECT market_view,denominator,trade_date,count(*) AS included_industry_count,
               avg((active10>0.5)::DOUBLE) AS industry_liquidity_diffusion10,
               avg((active20>0.5)::DOUBLE) AS industry_liquidity_diffusion20,
               avg((active60>0.5)::DOUBLE) AS industry_liquidity_diffusion60
        FROM industry_groups GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_joined AS
        SELECT s.* EXCLUDE(amount_total_exact,amount_partition_total_exact),
               cast(s.amount_total_exact AS VARCHAR) AS amount_total_exact,
               cast(s.amount_partition_total_exact AS VARCHAR) AS amount_partition_total_exact,
               s.industry_mapped_count::DOUBLE/s.eligible_count
                 AS industry_mapping_coverage,
               i.included_industry_count,i.industry_liquidity_diffusion10,
               i.industry_liquidity_diffusion20,i.industry_liquidity_diffusion60
        FROM daily_security s LEFT JOIN industry_daily i
          USING(market_view,denominator,trade_date)
        """
    )
    return connection.execute(
        """
        SELECT *,
               avg(directional_sync_balance_daily) OVER w3 AS directional_sync_balance3,
               avg(directional_sync_balance_daily) OVER w5 AS directional_sync_balance5,
               avg(directional_sync_balance_daily) OVER w10 AS directional_sync_balance10,
               count(*) OVER w3 AS sync_count3,count(*) OVER w5 AS sync_count5,
               count(*) OVER w10 AS sync_count10,
               min(cal_idx) OVER w3 AS sync_min_idx3,min(cal_idx) OVER w5 AS sync_min_idx5,
               min(cal_idx) OVER w10 AS sync_min_idx10
        FROM daily_joined
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
    out["view_minimum_count"] = out["market_view"].map(VIEW_MINIMUMS).astype(int)
    out["view_valid"] = out["eligible_count"] >= out["view_minimum_count"]
    out["industry_valid"] = (
        out["view_valid"]
        & (out["industry_mapping_coverage"] >= 0.80)
        & (out["included_industry_count"] >= 10)
    )
    for horizon in (3, 5, 10):
        valid = (out[f"sync_count{horizon}"] == horizon) & (
            out["cal_idx"] - out[f"sync_min_idx{horizon}"] == horizon - 1
        )
        out.loc[~valid, f"directional_sync_balance{horizon}"] = np.nan
        grouped = out.groupby(["market_view", "denominator"], sort=False)
        lag_value = grouped["liquidity_median_amount_ratio20"].shift(horizon)
        lag_idx = grouped["cal_idx"].shift(horizon)
        out[f"liquidity_activity_change{horizon}"] = (
            out["liquidity_median_amount_ratio20"] - lag_value
        ).where(out["cal_idx"] - lag_idx == horizon)

    industry_columns = [
        "industry_liquidity_diffusion10",
        "industry_liquidity_diffusion20",
        "industry_liquidity_diffusion60",
    ]
    all_raw = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    nonindustry = [column for column in all_raw if column not in industry_columns]
    out.loc[~out["view_valid"], nonindustry] = np.nan
    out.loc[~out["industry_valid"], industry_columns] = np.nan
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
        ranks = out.groupby(["trade_date", "denominator"])[column].rank(
            method="average", pct=True
        )
        out[f"{column}_relative_view_rank_pct"] = ranks.where(counts >= 3)
        out = out.drop(columns="_all_value")
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
                str(other)
                for other in correlation.columns
                if str(other) not in component
                and np.isfinite(correlation.loc[current, other])
                and abs(float(correlation.loc[current, other])) >= threshold
            )
        components.append(sorted(component))
    return sorted(components, key=lambda items: min(MINIMAL_PRIORITY.index(item) for item in items))


def _diagnostics(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[list[str]], list[str], dict[str, str]]:
    diagnostics: dict[str, dict] = {}
    primary = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    for role, (column, neighbors) in ROLE_MAP.items():
        coverage_by_view: dict[str, float] = {}
        for market_view, group in primary.groupby("market_view", sort=True):
            eligible = group.loc[group["view_valid"] & (group["within_view_observation"] >= 60)]
            if role == "industry_liquidity_diffusion":
                eligible = eligible.loc[eligible["industry_valid"]]
            coverage_by_view[str(market_view)] = float(eligible[column].notna().mean())
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
        for market_view in sorted(panel["market_view"].unique()):
            wide = panel.loc[
                panel["market_view"] == market_view, ["trade_date", "denominator", column]
            ].pivot(index="trade_date", columns="denominator", values=column)
            denominator_by_view[str(market_view)] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.median(list(denominator_by_view.values())))
        cell_checks: list[bool] = []
        eligible_cells = 0
        year_support: dict[str, dict] = {}
        for (view, year), cell in primary.assign(year=primary["trade_date"].dt.year).groupby(
            ["market_view", "year"], sort=True
        ):
            values = cell[column].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                std = float(values.std(ddof=0))
                cell_checks.append(bool(np.isfinite(std) and std > 0))
                year_support[f"{view}:{year}"] = {
                    "n": int(len(values)),
                    "p10": float(values.quantile(0.10)),
                    "median": float(values.median()),
                    "p90": float(values.quantile(0.90)),
                }
        nondegenerate = bool(eligible_cells and all(cell_checks))
        pit_expected = primary[column].notna().groupby(
            [primary["market_view"], primary["denominator"]]
        ).cumsum() >= MIN_PIT_HISTORY
        pit_coverage = (
            float(primary.loc[pit_expected, f"{column}_pit_3y_pct"].notna().mean())
            if pit_expected.any()
            else float("nan")
        )
        relative_expected = (primary["market_view"] != "ALL_A") & primary[column].notna()
        relative_coverage = float(
            primary.loc[relative_expected, f"{column}_relative_to_all"].notna().mean()
        )
        passed = bool(
            min(coverage_by_view.values()) >= 0.95
            and min(neighbor_medians) >= 0.70
            and denominator_median >= 0.90
            and nondegenerate
        )
        diagnostics[role] = {
            "primary": column,
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

    redundancy = primary.loc[primary["market_view"] == "ALL_A", [
        ROLE_MAP[role][0] for role in MINIMAL_PRIORITY
    ]].rename(columns={ROLE_MAP[role][0]: role for role in MINIMAL_PRIORITY})
    correlation = redundancy.corr(method="spearman")
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


def _correlation_dict(correlation: pd.DataFrame) -> dict[str, dict[str, float]]:
    return {
        str(row): {str(column): float(correlation.loc[row, column]) for column in correlation.columns}
        for row in correlation.index
    }


def _render_report(result: dict) -> str:
    lines = [
        f"# {result['experiment_id']} correlation/liquidity representation freeze",
        "",
        "## Construction boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Source: {result['input_audit']['rows']:,} CY-006 rows; eligible liquidity audit: {result['liquidity_audit']['eligible_rows']:,} rows.",
        f"- Output: {result['population']['rows']:,} daily view/denominator rows.",
        "- Strategy membership, outcomes, trades, future returns, and CY-011 read: **none**.",
        "- This is representation-quality evidence, not a panic, recovery, impairment, habitat, or strategy claim.",
        f"- Minimal nonredundant roles: `{', '.join(result['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "",
        "## Representation gates",
        "",
        "| Concept | Primary | Min coverage | Worst neighbor median rho | ST sensitivity rho | PIT coverage | Relative coverage | Gate | Minimal panel |",
        "|---|---|---:|---:|---:|---:|---:|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in MINIMAL_PRIORITY:
        item = result["role_diagnostics"][role]
        worst = min(value["median_across_views"] for value in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(
            f"| {role} | `{item['primary']}` | {item['minimum_raw_coverage']:.3f} | "
            f"{worst:.3f} | {item['all_status_vs_non_st_median']:.3f} | "
            f"{item['pit_3y_percentile_expected_coverage']:.3f} | "
            f"{item['relative_to_all_expected_coverage']:.3f} | "
            f"{'PASS' if item['construction_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend([
        "",
        "## Outcome-blind latent components",
        "",
        f"Absolute-Spearman connected components at 0.85: `{result['latent_components']}`.",
        "",
        "Components diagnose redundancy only. A stable role is not a panic mechanism or a useful trading state. Failed fixed representations leave their broader economic families open.",
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
    paths, source_hashes = breadth._verify_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="mkt_clq_001_") as temporary:
        connection = duckdb.connect(str(Path(temporary) / "clq.duckdb"))
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='6GB'")
        connection.execute(f"SET temp_directory='{temporary}'")
        try:
            breadth._create_source_view(connection, paths)
            input_audit = breadth._audit_source(connection, spec)
            breadth._create_security_states(connection)
            liquidity_audit = _liquidity_audit(connection, spec)
            _create_clq_security(connection)
            daily = _create_daily_clq(connection)
        finally:
            connection.close()

    panel = _attach_coordinates(daily)
    diagnostics, correlation, components, accepted, excluded = _diagnostics(panel)
    raw_columns = [column for definition in ROLE_MAP.values() for column in (definition[0], *definition[1])]
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    coordinate_columns = [
        column
        for primary in primary_columns
        for column in (
            f"{primary}_pit_expanding_pct",
            f"{primary}_pit_3y_pct",
            f"{primary}_pit_3y_robust_z",
            f"{primary}_relative_to_all",
            f"{primary}_relative_view_rank_pct",
        )
    ]
    output = panel[[
        "trade_date", "market_view", "denominator", "eligible_count",
        "industry_mapped_count", "industry_mapping_coverage", "included_industry_count",
        "amount_total_exact", "amount_partition_total_exact", "view_valid", "industry_valid",
        "within_view_observation", "decision_at", "available_at", "snapshot_id",
        *raw_columns, *coordinate_columns,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    if output["trade_date"].max() > "2023-12-31":
        raise CorrelationLiquidityFreezeError("post-2023 row entered output")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_STRATEGY_INDEPENDENT_CORRELATION_LIQUIDITY_REPRESENTATION_FREEZE",
        "usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "input_audit": input_audit,
        "liquidity_audit": liquidity_audit,
        "population": {
            "rows": int(len(output)),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "market_views": int(output["market_view"].nunique()),
            "denominators": sorted(str(item) for item in output["denominator"].unique()),
        },
        "role_diagnostics": diagnostics,
        "primary_role_spearman_all_a": _correlation_dict(correlation),
        "latent_components": components,
        "minimal_panel": {
            "priority": list(MINIMAL_PRIORITY),
            "accepted_roles": accepted,
            "excluded_roles": excluded,
        },
        "limitations": {
            "pit_grade": "bounded PIT-B",
            "panic_state": "NOT_ESTABLISHED",
            "recovery_or_impairment": "NOT_TESTED",
            "economic_usefulness": "NOT_TESTED",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "manifest_sha256": MANIFEST_SHA,
            "source_partitions": source_hashes,
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
        "accepted_roles": final["minimal_panel"]["accepted_roles"],
        "excluded_roles": final["minimal_panel"]["excluded_roles"],
        "latent_components": final["latent_components"],
        "panel_sha256": final["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
