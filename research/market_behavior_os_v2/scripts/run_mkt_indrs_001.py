#!/usr/bin/env python3
"""Construct frozen industry leadership and relative-strength representations."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from run_mkt_brth_001 import (  # noqa: E402
    _create_security_states,
    _create_source_view,
    _verify_inputs,
)
from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-INDRS-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-INDRS-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-INDRS-001_representation.md"
EXPECTED_SPEC_SHA256 = "e49f209806c25cafb1c78c5730fbfe07b0c83690fc14bc1a677c8d303d38836d"
MANIFEST_SHA = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
SNAPSHOT_ID = f"CY-006:{MANIFEST_SHA}"
MIN_PIT_HISTORY = 504

ROLE_MAP: dict[str, tuple[str, tuple[str, str]]] = {
    "industry_positive_participation_1d": (
        "industry_positive_participation_median",
        ("industry_positive_participation_mean", "industry_positive_participation_majority"),
    ),
    "industry_return_depth_1d": (
        "industry_return_depth_median_of_medians",
        ("industry_return_depth_mean_of_medians", "industry_return_depth_median_of_means"),
    ),
    "industry_return_dispersion_1d": (
        "industry_return_dispersion_iqr",
        ("industry_return_dispersion_p90_p10", "industry_return_dispersion_mad"),
    ),
    "industry_market_rs_depth20": (
        "industry_market_rs_depth_median",
        ("industry_market_rs_depth_mean", "industry_market_rs_depth_p60"),
    ),
    "industry_leadership_concentration20": (
        "industry_leadership_positive_mass_top3",
        ("industry_leadership_positive_mass_top5", "industry_leadership_positive_mass_top10"),
    ),
    "winner_industry_diffusion20": (
        "winner_industry_entropy_top10",
        ("winner_industry_entropy_top5", "winner_industry_entropy_top20"),
    ),
    "industry_leadership_persistence20": (
        "industry_leadership_jaccard_top5_lag5",
        ("industry_leadership_jaccard_top3_lag5", "industry_leadership_jaccard_top10_lag5"),
    ),
    "industry_rank_rotation20": (
        "industry_rank_rotation_spearman_lag5",
        ("industry_rank_rotation_kendall_lag5", "industry_rank_rotation_displacement_lag5"),
    ),
    "stock_industry_rs_dispersion20": (
        "stock_industry_rs_dispersion_iqr",
        ("stock_industry_rs_dispersion_p90_p10", "stock_industry_rs_dispersion_mad"),
    ),
    "stock_industry_rs_tail_balance20": (
        "stock_industry_rs_tail_balance_p90_p10",
        ("stock_industry_rs_tail_balance_p80_p20", "stock_industry_rs_tail_balance_p95_p05"),
    ),
    "stock_industry_rs_concentration20": (
        "stock_industry_rs_positive_mass_top10",
        ("stock_industry_rs_positive_mass_top5", "stock_industry_rs_positive_mass_top20"),
    ),
}
PRIORITY = tuple(ROLE_MAP)


class IndustryRelativeStrengthError(RuntimeError):
    """Fail-closed MKT-INDRS-001 error."""


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
        raise IndustryRelativeStrengthError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise IndustryRelativeStrengthError("spec is not frozen before construction")
    return spec


def _audit_source(connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT count(*),count(*)-count(DISTINCT (symbol,trade_date)),
               min(trade_date),max(trade_date),
               sum((available_at>decision_at)::INTEGER),count(DISTINCT snapshot_id),
               sum((hard_valid AND (high<greatest(open,close,low) OR low>least(open,close,high)))::INTEGER),
               sum((hard_valid AND (close IS NULL OR NOT isfinite(close) OR close<=0))::INTEGER)
        FROM source
        """
    ).fetchone()
    result = {
        "rows": int(row[0]),
        "duplicate_keys": int(row[1]),
        "first_date": str(row[2]),
        "last_date": str(row[3]),
        "time_travel_rows": int(row[4]),
        "snapshot_count": int(row[5]),
        "hard_valid_ohlc_failures": int(row[6]),
        "hard_valid_close_failures": int(row[7]),
    }
    expected = spec["input"]
    if result["rows"] != expected["expected_rows"]:
        raise IndustryRelativeStrengthError("source row count mismatch")
    if result["duplicate_keys"] or result["time_travel_rows"]:
        raise IndustryRelativeStrengthError("source key/PIT audit failed")
    if result["first_date"] != expected["source_start"] or result["last_date"] != expected["source_end"]:
        raise IndustryRelativeStrengthError("source date boundary mismatch")
    if result["hard_valid_ohlc_failures"] or result["hard_valid_close_failures"]:
        raise IndustryRelativeStrengthError("hard-valid price audit failed")
    return result


def _create_industry_core(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE indrs_core AS
        SELECT trade_date,cal_idx,symbol,is_st,causal_industry,
               exp(step_log_return)-1 AS ret1,
               adjusted_close/lag_close20-1 AS ret20
        FROM stock_lagged
        WHERE current_valid AND history_valid
          AND coordinate_valid_count120=120
          AND history_row_count121=121 AND history_valid_count121=121
          AND cal_idx-history_min_cal_idx121=120
          AND cal_idx-lag_idx20=20
          AND step_log_return IS NOT NULL AND isfinite(step_log_return)
          AND lag_close20 IS NOT NULL AND isfinite(lag_close20) AND lag_close20>0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE view_rows AS
        SELECT 'ALL_A' AS market_view,* FROM indrs_core
        UNION ALL SELECT 'SH_A',* FROM indrs_core WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM indrs_core WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM indrs_core
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


def _create_industry_tables(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE daily_view AS
        SELECT market_view,denominator,trade_date,max(cal_idx) AS cal_idx,
               count(*) AS eligible_count,count(causal_industry) AS industry_mapped_count,
               median(ret20) AS stock_ret20_median,avg(ret20) AS stock_ret20_mean,
               quantile_cont(ret20,0.60) AS stock_ret20_p60,
               quantile_cont(ret20,0.95) AS stock_q95,
               quantile_cont(ret20,0.90) AS stock_q90,
               quantile_cont(ret20,0.80) AS stock_q80
        FROM expanded GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_groups AS
        SELECT market_view,denominator,trade_date,max(cal_idx) AS cal_idx,causal_industry,
               count(*) AS member_count,
               median(ret1) AS industry_ret1_median,avg(ret1) AS industry_ret1_mean,
               avg((ret1>0)::DOUBLE) AS industry_positive_member_fraction,
               median(ret20) AS industry_ret20_median,avg(ret20) AS industry_ret20_mean,
               sum(ret20) AS industry_ret20_sum,
               list_sort(list(ret20)) AS sorted_ret20
        FROM expanded
        WHERE causal_industry IS NOT NULL
        GROUP BY 1,2,3,5 HAVING count(*)>=5
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_ranked AS
        SELECT *,row_number() OVER (
                 PARTITION BY market_view,denominator,trade_date
                 ORDER BY greatest(industry_ret20_median,0) DESC,causal_industry
               ) AS positive_rank
        FROM industry_groups
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_daily_base AS
        SELECT market_view,denominator,trade_date,max(cal_idx) AS cal_idx,
               count(*) AS included_industry_count,
               avg((industry_ret1_median>0)::DOUBLE) AS industry_positive_participation_median,
               avg((industry_ret1_mean>0)::DOUBLE) AS industry_positive_participation_mean,
               avg((industry_positive_member_fraction>0.5)::DOUBLE) AS industry_positive_participation_majority,
               median(industry_ret1_median) AS industry_return_depth_median_of_medians,
               avg(industry_ret1_median) AS industry_return_depth_mean_of_medians,
               median(industry_ret1_mean) AS industry_return_depth_median_of_means,
               quantile_cont(industry_ret1_median,0.75)-quantile_cont(industry_ret1_median,0.25)
                 AS industry_return_dispersion_iqr,
               quantile_cont(industry_ret1_median,0.90)-quantile_cont(industry_ret1_median,0.10)
                 AS industry_return_dispersion_p90_p10,
               median(industry_ret20_median) AS industry_ret20_median_of_medians,
               avg(industry_ret20_mean) AS industry_ret20_mean_of_means,
               quantile_cont(industry_ret20_median,0.60) AS industry_ret20_p60,
               sum(CASE WHEN positive_rank<=3 THEN greatest(industry_ret20_median,0) ELSE 0 END)
                 /nullif(sum(greatest(industry_ret20_median,0)),0)
                 AS industry_leadership_positive_mass_top3,
               sum(CASE WHEN positive_rank<=5 THEN greatest(industry_ret20_median,0) ELSE 0 END)
                 /nullif(sum(greatest(industry_ret20_median,0)),0)
                 AS industry_leadership_positive_mass_top5,
               sum(CASE WHEN positive_rank<=10 THEN greatest(industry_ret20_median,0) ELSE 0 END)
                 /nullif(sum(greatest(industry_ret20_median,0)),0)
                 AS industry_leadership_positive_mass_top10
        FROM industry_ranked GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_mad AS
        SELECT g.market_view,g.denominator,g.trade_date,
               median(abs(g.industry_ret1_median-d.industry_return_depth_median_of_medians))
                 AS industry_return_dispersion_mad
        FROM industry_groups g JOIN industry_daily_base d USING(market_view,denominator,trade_date)
        GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_daily AS
        SELECT i.*,m.industry_return_dispersion_mad,
               i.industry_ret20_median_of_medians-v.stock_ret20_median
                 AS industry_market_rs_depth_median,
               i.industry_ret20_mean_of_means-v.stock_ret20_mean
                 AS industry_market_rs_depth_mean,
               i.industry_ret20_p60-v.stock_ret20_p60
                 AS industry_market_rs_depth_p60,
               v.eligible_count,v.industry_mapped_count,
               v.industry_mapped_count::DOUBLE/v.eligible_count AS industry_mapping_coverage
        FROM industry_daily_base i
        JOIN daily_view v USING(market_view,denominator,trade_date)
        JOIN industry_mad m USING(market_view,denominator,trade_date)
        """
    )


def _create_winner_entropy(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE winner_counts AS
        SELECT e.market_view,e.denominator,e.trade_date,e.causal_industry,'top5' AS threshold,
               count(*) AS winner_count
        FROM expanded e JOIN daily_view d USING(market_view,denominator,trade_date)
        JOIN industry_groups i USING(market_view,denominator,trade_date,causal_industry)
        WHERE e.ret20>=d.stock_q95 GROUP BY 1,2,3,4
        UNION ALL
        SELECT e.market_view,e.denominator,e.trade_date,e.causal_industry,'top10',count(*)
        FROM expanded e JOIN daily_view d USING(market_view,denominator,trade_date)
        JOIN industry_groups i USING(market_view,denominator,trade_date,causal_industry)
        WHERE e.ret20>=d.stock_q90 GROUP BY 1,2,3,4
        UNION ALL
        SELECT e.market_view,e.denominator,e.trade_date,e.causal_industry,'top20',count(*)
        FROM expanded e JOIN daily_view d USING(market_view,denominator,trade_date)
        JOIN industry_groups i USING(market_view,denominator,trade_date,causal_industry)
        WHERE e.ret20>=d.stock_q80 GROUP BY 1,2,3,4
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE winner_totals AS
        SELECT market_view,denominator,trade_date,threshold,sum(winner_count) AS total_winners
        FROM winner_counts GROUP BY 1,2,3,4
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE winner_entropy_long AS
        SELECT w.market_view,w.denominator,w.trade_date,w.threshold,
               -sum((w.winner_count::DOUBLE/t.total_winners)
                    *ln(w.winner_count::DOUBLE/t.total_winners))
                /nullif(ln(i.included_industry_count),0) AS entropy
        FROM winner_counts w
        JOIN winner_totals t USING(market_view,denominator,trade_date,threshold)
        JOIN industry_daily i USING(market_view,denominator,trade_date)
        GROUP BY 1,2,3,4,i.included_industry_count
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE winner_entropy AS
        SELECT market_view,denominator,trade_date,
               max(CASE WHEN threshold='top10' THEN entropy END) AS winner_industry_entropy_top10,
               max(CASE WHEN threshold='top5' THEN entropy END) AS winner_industry_entropy_top5,
               max(CASE WHEN threshold='top20' THEN entropy END) AS winner_industry_entropy_top20
        FROM winner_entropy_long GROUP BY 1,2,3
        """
    )


def _create_leave_one_out_residuals(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE mapped_stocks AS
        SELECT e.*,i.member_count,i.sorted_ret20,
          CASE
            WHEN i.member_count%2=0 AND e.ret20<=list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT)
              THEN list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+1)
            WHEN i.member_count%2=0
              THEN list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT)
            WHEN i.member_count%2=1
                 AND e.ret20<list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+1)
              THEN (list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+1)
                    +list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+2))/2
            WHEN i.member_count%2=1
                 AND e.ret20>list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+1)
              THEN (list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT)
                    +list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+1))/2
            ELSE (list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT)
                  +list_extract(i.sorted_ret20,floor(i.member_count/2)::BIGINT+2))/2
          END AS leave_one_out_industry_median
        FROM expanded e
        JOIN industry_groups i USING(market_view,denominator,trade_date,causal_industry)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_residual AS
        SELECT *,ret20-leave_one_out_industry_median AS stock_industry_residual
        FROM mapped_stocks
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE residual_centers AS
        SELECT market_view,denominator,trade_date,
               median(stock_industry_residual) AS residual_median,
               quantile_cont(stock_industry_residual,0.95) AS residual_q95,
               quantile_cont(stock_industry_residual,0.90) AS residual_q90,
               quantile_cont(stock_industry_residual,0.80) AS residual_q80
        FROM stock_residual GROUP BY 1,2,3
        """
    )


def _create_residual_daily(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE residual_daily AS
        SELECT r.market_view,r.denominator,r.trade_date,
               count(*) AS residual_count,
               quantile_cont(r.stock_industry_residual,0.75)-quantile_cont(r.stock_industry_residual,0.25)
                 AS stock_industry_rs_dispersion_iqr,
               quantile_cont(r.stock_industry_residual,0.90)-quantile_cont(r.stock_industry_residual,0.10)
                 AS stock_industry_rs_dispersion_p90_p10,
               median(abs(r.stock_industry_residual-c.residual_median))
                 AS stock_industry_rs_dispersion_mad,
               quantile_cont(r.stock_industry_residual,0.90)+quantile_cont(r.stock_industry_residual,0.10)
                 AS stock_industry_rs_tail_balance_p90_p10,
               quantile_cont(r.stock_industry_residual,0.80)+quantile_cont(r.stock_industry_residual,0.20)
                 AS stock_industry_rs_tail_balance_p80_p20,
               quantile_cont(r.stock_industry_residual,0.95)+quantile_cont(r.stock_industry_residual,0.05)
                 AS stock_industry_rs_tail_balance_p95_p05,
               sum(CASE WHEN r.stock_industry_residual>=c.residual_q90
                        THEN greatest(r.stock_industry_residual,0) ELSE 0 END)
                 /nullif(sum(greatest(r.stock_industry_residual,0)),0)
                 AS stock_industry_rs_positive_mass_top10,
               sum(CASE WHEN r.stock_industry_residual>=c.residual_q95
                        THEN greatest(r.stock_industry_residual,0) ELSE 0 END)
                 /nullif(sum(greatest(r.stock_industry_residual,0)),0)
                 AS stock_industry_rs_positive_mass_top5,
               sum(CASE WHEN r.stock_industry_residual>=c.residual_q80
                        THEN greatest(r.stock_industry_residual,0) ELSE 0 END)
                 /nullif(sum(greatest(r.stock_industry_residual,0)),0)
                 AS stock_industry_rs_positive_mass_top20
        FROM stock_residual r JOIN residual_centers c USING(market_view,denominator,trade_date)
        GROUP BY 1,2,3
        """
    )


def leave_one_out_median(values: list[float], position: int) -> float:
    remaining = [value for index, value in enumerate(values) if index != position]
    return float(np.median(np.asarray(remaining, dtype=float)))


def _audit_leave_one_out(connection: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    sample = connection.execute(
        """
        SELECT market_view,denominator,trade_date,causal_industry,symbol,ret20,
               leave_one_out_industry_median
        FROM mapped_stocks
        WHERE market_view='ALL_A' AND denominator='ALL_STATUS'
        ORDER BY trade_date,causal_industry,symbol LIMIT 2000
        """
    ).df()
    checked = 0
    maximum_difference = 0.0
    for _, group in sample.groupby(["trade_date", "causal_industry"], sort=True):
        if len(group) < 2:
            continue
        values = group["ret20"].astype(float).tolist()
        # Only groups fully contained in the bounded sample can be recomputed.
        source_count = connection.execute(
            """SELECT count(*) FROM mapped_stocks
               WHERE market_view='ALL_A' AND denominator='ALL_STATUS'
                 AND trade_date=? AND causal_industry=?""",
            [group["trade_date"].iloc[0], group["causal_industry"].iloc[0]],
        ).fetchone()[0]
        if int(source_count) != len(group):
            continue
        for position, observed in enumerate(group["leave_one_out_industry_median"].astype(float)):
            expected = leave_one_out_median(values, position)
            difference = abs(expected - observed)
            maximum_difference = max(maximum_difference, difference)
            if difference != 0.0:
                raise IndustryRelativeStrengthError("leave-one-out median exact audit failed")
            checked += 1
    if checked < 100:
        raise IndustryRelativeStrengthError("insufficient exact leave-one-out audit support")
    return {"rows_checked": checked, "maximum_absolute_difference": maximum_difference}


def _fetch_daily_and_industries(
    connection: duckdb.DuckDBPyConnection,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = connection.execute(
        """
        SELECT i.*,w.winner_industry_entropy_top10,w.winner_industry_entropy_top5,
               w.winner_industry_entropy_top20,r.* EXCLUDE(market_view,denominator,trade_date)
        FROM industry_daily i
        LEFT JOIN winner_entropy w USING(market_view,denominator,trade_date)
        LEFT JOIN residual_daily r USING(market_view,denominator,trade_date)
        ORDER BY trade_date,denominator,market_view
        """
    ).df()
    industries = connection.execute(
        """
        SELECT market_view,denominator,trade_date,cal_idx,causal_industry,
               member_count,industry_ret20_median
        FROM industry_groups
        ORDER BY market_view,denominator,cal_idx,causal_industry
        """
    ).df()
    return daily, industries


def _jaccard(left: set[str], right: set[str]) -> float:
    union = left | right
    return float(len(left & right) / len(union)) if union else float("nan")


def _rotation_panel(industries: pd.DataFrame, minimum_common: int) -> pd.DataFrame:
    industries = industries.copy()
    industries["trade_date"] = pd.to_datetime(industries["trade_date"])
    rows: list[dict[str, Any]] = []
    for (view, denominator), group in industries.groupby(["market_view", "denominator"], sort=True):
        by_index = {int(index): item for index, item in group.groupby("cal_idx", sort=True)}
        for cal_idx in sorted(by_index):
            if cal_idx - 5 not in by_index:
                continue
            current = by_index[cal_idx][["causal_industry", "industry_ret20_median"]].copy()
            lagged = by_index[cal_idx - 5][["causal_industry", "industry_ret20_median"]].copy()
            current = current.sort_values(["industry_ret20_median", "causal_industry"], ascending=[False, True])
            lagged = lagged.sort_values(["industry_ret20_median", "causal_industry"], ascending=[False, True])
            merged = current.merge(lagged, on="causal_industry", suffixes=("_current", "_lag"))
            record: dict[str, Any] = {
                "market_view": view,
                "denominator": denominator,
                "trade_date": by_index[cal_idx]["trade_date"].iloc[0],
                "common_industry_count_lag5": int(len(merged)),
                "industry_label_union_lag5": int(len(set(current.causal_industry) | set(lagged.causal_industry))),
            }
            for top in (3, 5, 10):
                record[f"industry_leadership_jaccard_top{top}_lag5"] = _jaccard(
                    set(current.head(top).causal_industry), set(lagged.head(top).causal_industry)
                )
            if len(merged) >= minimum_common:
                spearman = float(merged[["industry_ret20_median_current", "industry_ret20_median_lag"]].corr(
                    method="spearman"
                ).iloc[0, 1])
                kendall = float(merged[["industry_ret20_median_current", "industry_ret20_median_lag"]].corr(
                    method="kendall"
                ).iloc[0, 1])
                current_rank = merged["industry_ret20_median_current"].rank(method="average", pct=True)
                lag_rank = merged["industry_ret20_median_lag"].rank(method="average", pct=True)
                displacement = float((current_rank - lag_rank).abs().mean())
                record["industry_rank_rotation_spearman_lag5"] = (1.0 - spearman) / 2.0
                record["industry_rank_rotation_kendall_lag5"] = (1.0 - kendall) / 2.0
                record["industry_rank_rotation_displacement_lag5"] = displacement
            else:
                record["industry_rank_rotation_spearman_lag5"] = np.nan
                record["industry_rank_rotation_kendall_lag5"] = np.nan
                record["industry_rank_rotation_displacement_lag5"] = np.nan
            rows.append(record)
    return pd.DataFrame(rows)


def _attach_coordinates(daily: pd.DataFrame, rotation: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = daily.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    rotation["trade_date"] = pd.to_datetime(rotation["trade_date"])
    out = out.merge(rotation, on=["market_view", "denominator", "trade_date"], how="left", validate="one_to_one")
    out["view_minimum_count"] = out["market_view"].map(spec["universe"]["minimum_view_counts"]).astype(int)
    out["view_valid"] = out["eligible_count"] >= out["view_minimum_count"]
    out["industry_valid"] = (
        out["view_valid"]
        & (out["industry_mapping_coverage"] >= spec["universe"]["industry_mapping_minimum"])
        & (out["included_industry_count"] >= spec["universe"]["industry_count_minimum"])
    )
    raw_columns = [column for primary, neighbors in ROLE_MAP.values() for column in (primary, *neighbors)]
    out.loc[~out["industry_valid"], raw_columns] = np.nan
    out = out.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    out["within_view_observation"] = out.groupby(["market_view", "denominator"], sort=False).cumcount() + 1
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
        all_values = out.loc[out["market_view"] == "ALL_A", ["trade_date", "denominator", column]].rename(
            columns={column: "_all_value"}
        )
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left")
        out[f"{column}_relative_to_all"] = out[column] - out["_all_value"]
        counts = out.groupby(["trade_date", "denominator"])[column].transform("count")
        out[f"{column}_relative_view_rank_pct"] = out.groupby(["trade_date", "denominator"])[column].rank(
            method="average", pct=True
        ).where(counts >= 3)
        out = out.drop(columns="_all_value")
    out["decision_at"] = out["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    out["available_at"] = out["decision_at"]
    out["snapshot_id"] = SNAPSHOT_ID
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def _spearman(left: pd.Series, right: pd.Series) -> float:
    clean = pd.concat([left, right], axis=1).replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) < 3 or clean.iloc[:, 0].nunique() < 2 or clean.iloc[:, 1].nunique() < 2:
        return float("nan")
    return float(clean.corr(method="spearman").iloc[0, 1])


def _connected_components(correlation: pd.DataFrame, threshold: float) -> list[list[str]]:
    remaining = set(correlation.columns.astype(str))
    components: list[list[str]] = []
    while remaining:
        seed = sorted(remaining)[0]
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            for other in correlation.columns.astype(str):
                value = correlation.loc[current, other]
                if other not in component and np.isfinite(value) and abs(float(value)) >= threshold:
                    stack.append(other)
        components.append(sorted(component))
    return sorted(components)


def _diagnostics(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame, list[list[str]], list[str], dict[str, str], dict[str, Any]]:
    primary = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    diagnostics: dict[str, Any] = {}
    for role, (field, neighbors) in ROLE_MAP.items():
        coverage: dict[str, float] = {}
        neighbor_results: dict[str, Any] = {}
        for view, group in primary.groupby("market_view", sort=True):
            eligible = group.loc[group["industry_valid"] & (group["within_view_observation"] >= 20)]
            coverage[str(view)] = float(eligible[field].notna().mean())
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_view = {
                str(view): _spearman(group[field], group[neighbor])
                for view, group in primary.groupby("market_view", sort=True)
            }
            median = float(np.median(list(by_view.values())))
            neighbor_medians.append(median)
            neighbor_results[neighbor] = {"by_view": by_view, "median_across_views": median}
        denominator_by_view: dict[str, float] = {}
        for view in sorted(panel["market_view"].unique()):
            wide = panel.loc[panel["market_view"] == view, ["trade_date", "denominator", field]].pivot(
                index="trade_date", columns="denominator", values=field
            )
            denominator_by_view[str(view)] = _spearman(wide["ALL_STATUS"], wide["NON_ST"])
        denominator_median = float(np.median(list(denominator_by_view.values())))
        year_support: dict[str, Any] = {}
        cell_pass = True
        eligible_cells = 0
        work = primary.assign(year=primary["trade_date"].dt.year)
        for (view, year), group in work.groupby(["market_view", "year"], sort=True):
            if int(year) not in (2019, 2020, 2021, 2022, 2023):
                continue
            values = group[field].replace([np.inf, -np.inf], np.nan).dropna()
            year_support[f"{view}:{year}"] = {"n": int(len(values)), "nunique": int(values.nunique())}
            eligible_cells += 1
            cell_pass &= len(values) >= spec["gates"]["view_year_minimum_observations"] and values.nunique() >= 2
        expected_pit = primary.groupby(["market_view", "denominator"])[field].transform(
            lambda values: values.notna().cumsum()
        ) >= MIN_PIT_HISTORY
        pit_coverage = float(primary.loc[expected_pit, f"{field}_pit_3y_pct"].notna().mean())
        relative_expected = (primary["market_view"] != "ALL_A") & primary[field].notna()
        relative_coverage = float(primary.loc[relative_expected, f"{field}_relative_to_all"].notna().mean())
        passed = bool(
            min(coverage.values()) >= spec["gates"]["raw_coverage"]
            and min(neighbor_medians) >= spec["gates"]["worst_median_neighbor_spearman"]
            and denominator_median >= spec["gates"]["all_status_vs_non_st_median_spearman"]
            and cell_pass and eligible_cells == 20
            and pit_coverage >= spec["gates"]["pit_and_relative_expected_coverage"]
            and relative_coverage >= spec["gates"]["pit_and_relative_expected_coverage"]
        )
        diagnostics[role] = {
            "primary": field,
            "minimum_raw_coverage": min(coverage.values()),
            "coverage_by_view": coverage,
            "neighbors": neighbor_results,
            "all_status_vs_non_st_by_view": denominator_by_view,
            "all_status_vs_non_st_median": denominator_median,
            "eligible_view_year_cells": eligible_cells,
            "all_eligible_cells_nondegenerate": bool(cell_pass and eligible_cells == 20),
            "year_support": year_support,
            "pit_expected_coverage": pit_coverage,
            "relative_expected_coverage": relative_coverage,
            "representation_gate_pass": passed,
        }

    all_a = primary.loc[primary["market_view"] == "ALL_A", [ROLE_MAP[role][0] for role in PRIORITY]].rename(
        columns={ROLE_MAP[role][0]: role for role in PRIORITY}
    )
    correlation = all_a.corr(method="spearman")
    components = _connected_components(correlation, spec["gates"]["latent_component_edge_absolute_spearman"])

    external_path = ROOT / spec["external_controls"]["breadth_panel"]["path"]
    if sha256_file(external_path) != spec["external_controls"]["breadth_panel"]["sha256"]:
        raise IndustryRelativeStrengthError("external breadth panel identity mismatch")
    external_fields = spec["external_controls"]["breadth_panel"]["fields"]
    external = pd.read_csv(external_path, usecols=["trade_date", "market_view", "denominator", *external_fields])
    external["trade_date"] = pd.to_datetime(external["trade_date"])
    external = external.loc[external["denominator"] == "ALL_STATUS"].copy()
    external_diagnostics: dict[str, Any] = {}
    for role in PRIORITY:
        field = ROLE_MAP[role][0]
        medians: dict[str, float] = {}
        for control in external_fields:
            values = []
            for view in sorted(primary["market_view"].unique()):
                joined = primary.loc[primary["market_view"] == view, ["trade_date", field]].merge(
                    external.loc[external["market_view"] == view, ["trade_date", control]], on="trade_date"
                )
                values.append(abs(_spearman(joined[field], joined[control])))
            medians[control] = float(np.median(values))
        external_diagnostics[role] = {
            "median_absolute_spearman": medians,
            "maximum_median_absolute_spearman": max(medians.values()),
            "nonredundant": max(medians.values()) < spec["gates"]["external_redundancy_absolute_spearman"],
        }

    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in PRIORITY:
        if not diagnostics[role]["representation_gate_pass"]:
            excluded[role] = "representation_gate_failed"
            continue
        if not external_diagnostics[role]["nonredundant"]:
            excluded[role] = "externally_redundant"
            continue
        blockers = [
            prior for prior in accepted
            if abs(float(correlation.loc[role, prior])) >= spec["gates"]["latent_component_edge_absolute_spearman"]
        ]
        if blockers:
            excluded[role] = "redundant_with:" + ",".join(blockers)
        else:
            accepted.append(role)
    return diagnostics, correlation, components, accepted, excluded, external_diagnostics


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-INDRS-001 industry leadership and relative-strength representation",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Source: {result['input_audit']['rows']:,} CY-006 rows; output {result['population']['rows']:,} group/date rows.",
        "- PIT industry labels, exact leave-one-out medians, and serial construction only.",
        "- Failed MA diffusion fields, future returns, strategy outcomes, and CY-011 read: **none**.",
        "- Representation stability is not future persistence, selection alpha, sector-rotation usefulness, or a strategy rule.",
        f"- Minimal roles: `{', '.join(result['minimal_panel']['accepted_roles']) or 'NONE'}`.",
        "",
        "## Role gates",
        "",
        "| Role | Coverage | Worst neighbor rho | Denominator rho | Gate | Minimal disposition |",
        "|---|---:|---:|---:|---|---|",
    ]
    accepted = set(result["minimal_panel"]["accepted_roles"])
    for role in PRIORITY:
        item = result["role_diagnostics"][role]
        worst = min(value["median_across_views"] for value in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(
            f"| `{role}` | {item['minimum_raw_coverage']:.3f} | {worst:.3f} | "
            f"{item['all_status_vs_non_st_median']:.3f} | "
            f"{'PASS' if item['representation_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        f"- Leave-one-out audit rows: {result['leave_one_out_audit']['rows_checked']:,}; maximum exact difference {result['leave_one_out_audit']['maximum_absolute_difference']}.",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    paths, source_hashes = _verify_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="mkt_indrs_001_") as temporary:
        connection = duckdb.connect(str(Path(temporary) / "industry.duckdb"))
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='6GB'")
        connection.execute(f"SET temp_directory='{temporary}'")
        try:
            _create_source_view(connection, paths)
            input_audit = _audit_source(connection, spec)
            _create_security_states(connection)
            _create_industry_core(connection)
            _create_industry_tables(connection)
            _create_winner_entropy(connection)
            _create_leave_one_out_residuals(connection)
            _create_residual_daily(connection)
            loo_audit = _audit_leave_one_out(connection)
            daily, industries = _fetch_daily_and_industries(connection)
        finally:
            connection.close()
    rotation = _rotation_panel(industries, spec["universe"]["common_industries_for_rotation_minimum"])
    panel = _attach_coordinates(daily, rotation, spec)
    diagnostics, correlation, components, accepted, excluded, external = _diagnostics(panel, spec)

    raw_columns = [column for primary, neighbors in ROLE_MAP.values() for column in (primary, *neighbors)]
    primary_columns = [definition[0] for definition in ROLE_MAP.values()]
    coordinate_columns = [
        column for primary in primary_columns for column in (
            f"{primary}_pit_expanding_pct", f"{primary}_pit_3y_pct", f"{primary}_pit_3y_robust_z",
            f"{primary}_relative_to_all", f"{primary}_relative_view_rank_pct",
        )
    ]
    metadata = [
        "trade_date", "market_view", "denominator", "eligible_count", "industry_mapped_count",
        "industry_mapping_coverage", "included_industry_count", "residual_count",
        "common_industry_count_lag5", "industry_label_union_lag5", "view_valid", "industry_valid",
        "within_view_observation", "decision_at", "available_at", "snapshot_id",
    ]
    output = panel[[*metadata, *raw_columns, *coordinate_columns]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    passed_count = sum(item["representation_gate_pass"] for item in diagnostics.values())
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{passed_count}_OF_{len(PRIORITY)}_ROLES_PASS_{len(accepted)}_MINIMAL",
        "usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "failed_ma_industry_fields_read": [],
        "cy011_read": False,
        "input_audit": input_audit,
        "leave_one_out_audit": loo_audit,
        "population": {
            "rows": int(len(output)),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "groups": int(output.groupby(["market_view", "denominator"]).ngroups),
            "minimum_industry_mapping_coverage": float(panel.loc[panel["view_valid"], "industry_mapping_coverage"].min()),
            "minimum_included_industries": int(panel.loc[panel["industry_valid"], "included_industry_count"].min()),
        },
        "role_diagnostics": diagnostics,
        "external_redundancy": external,
        "primary_role_spearman_all_a": {
            str(row): {str(column): float(correlation.loc[row, column]) for column in correlation.columns}
            for row in correlation.index
        },
        "latent_components": components,
        "minimal_panel": {
            "priority": list(PRIORITY),
            "accepted_roles": accepted,
            "excluded_roles": excluded,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "manifest_sha256": MANIFEST_SHA,
            "source_partitions": source_hashes,
            "external_breadth_panel_sha256": spec["external_controls"]["breadth_panel"]["sha256"],
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
        "accepted_roles": completed["minimal_panel"]["accepted_roles"],
        "excluded_roles": completed["minimal_panel"]["excluded_roles"],
        "latent_components": completed["latent_components"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
