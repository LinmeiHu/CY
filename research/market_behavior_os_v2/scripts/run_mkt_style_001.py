#!/usr/bin/env python3
"""Construct frozen strategy-independent circulating-size representations."""

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

from run_mkt_style_data_001 import (  # noqa: E402
    _registry_assets,
    _verify_file_inputs,
    _verify_partitions,
)
from run_mkt_trnd_001 import causal_rolling_percentile, causal_rolling_robust_z  # noqa: E402


SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-STYLE-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-001_representation.md"
EXPECTED_SPEC_SHA256 = "a32ca8fcdb6080beb97f4226a891c44270a46e9d0a4818d4132501fdc1a808a3"
SNAPSHOT_ID = "CY-006:de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
GROUP_KEYS = ["market_view", "denominator"]
SIZE_RANK_FRACTION_EXPRESSION = "(row_number() OVER w-0.5)/count(*) OVER p"
DUCKDB_THREADS = 1


class StyleRepresentationError(RuntimeError):
    """Fail-closed MKT-STYLE-001 error."""


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


def _load_spec() -> tuple[dict[str, Any], dict[str, Any]]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StyleRepresentationError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_SIZE_BUCKET_OR_ROLE_CONSTRUCTION":
        raise StyleRepresentationError("spec is not frozen before construction")
    if list(spec["roles"]) != spec["role_priority"]:
        raise StyleRepresentationError("role order mismatch")
    data_spec_path = ROOT / spec["inputs"]["data_contract_spec"]["path"]
    data_result_path = ROOT / spec["inputs"]["data_contract_result"]["path"]
    if sha256_file(data_spec_path) != spec["inputs"]["data_contract_spec"]["sha256"]:
        raise StyleRepresentationError("data-contract spec identity mismatch")
    if sha256_file(data_result_path) != spec["inputs"]["data_contract_result"]["sha256"]:
        raise StyleRepresentationError("data-contract result identity mismatch")
    data_spec = json.loads(data_spec_path.read_text(encoding="utf-8"))
    data_result = json.loads(data_result_path.read_text(encoding="utf-8"))
    if data_result["status"] != "COMPLETE_DATA_CONTRACT_PASS":
        raise StyleRepresentationError("data contract does not pass")
    if data_result["accepted_semantic_label"] != "circulating_market_value_cny":
        raise StyleRepresentationError("data-contract semantic label changed")
    if data_result["representation_claim"] != "NONE" or data_result["usefulness_claim"] != "NONE":
        raise StyleRepresentationError("data-contract claim boundary changed")
    return spec, data_spec


def _verify_bound_source(data_spec: dict[str, Any]) -> tuple[list[Path], dict[str, Any]]:
    hashes = _verify_file_inputs(data_spec)
    _registry_assets(data_spec)
    paths, partitions = _verify_partitions(data_spec)
    return paths, {"inputs": hashes, "partitions": partitions}


def _create_source(connection: duckdb.DuckDBPyConnection, paths: list[Path]) -> None:
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")


def _create_security_coordinates(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source) ORDER BY trade_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE base AS
        SELECT s.trade_date,c.cal_idx,s.symbol,s.close,s.volume,s.trade_status,
               s.current_day_data_tradable,s.is_st,s.circulating_shares,
               s.corporate_action_count,s.corporate_action_available_date,
               s.corporate_action_blocking,s.share_multiplier,s.cash_per_share,s.rights_ratio,
               s.hard_valid,s.bar_valid,s.trading_state_valid,s.float_valid,
               s.corporate_action_valid,s.market_rule_valid,s.historical_identity_valid,
               s.available_at,s.decision_at,
               s.close*s.circulating_shares AS circulating_market_value_cny,
               (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
                AND s.trading_state_valid IS TRUE AND s.float_valid IS TRUE
                AND s.corporate_action_valid IS TRUE AND s.market_rule_valid IS TRUE
                AND s.historical_identity_valid IS TRUE
                AND s.corporate_action_blocking IS FALSE
                AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
                AND s.close IS NOT NULL AND isfinite(s.close) AND s.close>0
                AND s.circulating_shares IS NOT NULL AND isfinite(s.circulating_shares)
                AND s.circulating_shares>0 AND isfinite(s.close*s.circulating_shares)
                AND s.close*s.circulating_shares>0) AS history_valid,
               (s.hard_valid IS TRUE AND s.trade_status=1
                AND s.current_day_data_tradable IS TRUE
                AND s.volume IS NOT NULL AND isfinite(s.volume) AND s.volume>0) AS current_valid
        FROM source s JOIN calendar c USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_step AS
        SELECT *,lag(close) OVER w AS previous_close,
               lag(history_valid) OVER w AS previous_history_valid,
               lag(cal_idx) OVER w AS previous_cal_idx,
               lag(circulating_market_value_cny) OVER w AS lag_circulating_market_value_cny
        FROM base WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_chain AS
        SELECT *,
          CASE
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN true
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0
             AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date
             AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN true ELSE false END AS coordinate_step_valid,
          CASE
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND corporate_action_count>0
             AND corporate_action_available_date IS NOT NULL
             AND corporate_action_available_date<=trade_date
             AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
             AND (previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)>0
            THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
            ELSE NULL END AS step_log_return
        FROM stock_step
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE size_current_core AS
        SELECT trade_date,cal_idx,symbol,is_st,circulating_market_value_cny
        FROM base WHERE current_valid AND history_valid
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE size_return_core AS
        SELECT trade_date,cal_idx,symbol,is_st,circulating_market_value_cny,
               lag_circulating_market_value_cny,exp(step_log_return)-1 AS ret1
        FROM stock_chain
        WHERE current_valid AND history_valid AND coordinate_step_valid
          AND lag_circulating_market_value_cny IS NOT NULL
          AND isfinite(lag_circulating_market_value_cny)
          AND lag_circulating_market_value_cny>0
          AND step_log_return IS NOT NULL AND isfinite(step_log_return)
        """
    )


def _create_expanded_views(connection: duckdb.DuckDBPyConnection) -> None:
    for source_name, prefix in (("size_current_core", "current"), ("size_return_core", "return")):
        connection.execute(
            f"""
            CREATE TEMP TABLE {prefix}_views AS
            SELECT 'ALL_A' AS market_view,* FROM {source_name}
            UNION ALL SELECT 'SH_A',* FROM {source_name} WHERE symbol LIKE '%.SH'
            UNION ALL SELECT 'SZ_A',* FROM {source_name} WHERE symbol LIKE '%.SZ'
            UNION ALL SELECT 'CHINEXT_BOARD',* FROM {source_name}
              WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
            """
        )
        connection.execute(
            f"""
            CREATE TEMP TABLE {prefix}_expanded AS
            SELECT v.*,'ALL_STATUS' AS denominator FROM {prefix}_views v
            UNION ALL SELECT v.*,'NON_ST' FROM {prefix}_views v WHERE is_st IS FALSE
            """
        )


def _create_daily_components(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE size_enriched AS
        SELECT *,ln(circulating_market_value_cny) AS log_size,
               median(ln(circulating_market_value_cny)) OVER (
                 PARTITION BY market_view,denominator,trade_date
               ) AS group_log_size_median
        FROM current_expanded
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE structure_daily AS
        SELECT market_view,denominator,trade_date,count(*) AS size_structure_count,
               quantile_cont(log_size,0.75)-quantile_cont(log_size,0.25)
                 AS size_log_value_iqr,
               quantile_cont(log_size,0.90)-quantile_cont(log_size,0.10)
                 AS size_log_value_p90_p10,
               median(abs(log_size-group_log_size_median)) AS size_log_value_mad
        FROM size_enriched GROUP BY 1,2,3
        """
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE return_ranked_pre AS
        SELECT *,
          {SIZE_RANK_FRACTION_EXPRESSION} AS size_rank_fraction,
          ntile(3) OVER w AS size_tercile,
          ntile(5) OVER w AS size_quintile,
          quantile_cont(ret1,0.95) OVER p AS return_q95,
          quantile_cont(ret1,0.90) OVER p AS return_q90,
          quantile_cont(ret1,0.80) OVER p AS return_q80
        FROM return_expanded
        WINDOW w AS (
          PARTITION BY market_view,denominator,trade_date
          ORDER BY lag_circulating_market_value_cny,symbol
        ), p AS (PARTITION BY market_view,denominator,trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE return_daily AS
        SELECT market_view,denominator,trade_date,count(*) AS eligible_count,
          sum((size_rank_fraction<=0.20)::INTEGER) AS small20_count,
          sum((size_rank_fraction>=0.80)::INTEGER) AS large20_count,
          sum((size_rank_fraction<=0.30)::INTEGER) AS small30_count,
          sum((size_rank_fraction>=0.70)::INTEGER) AS large30_count,
          sum((size_rank_fraction<=0.40)::INTEGER) AS small40_count,
          sum((size_rank_fraction>=0.60)::INTEGER) AS large40_count,
          avg(ret1) FILTER (size_rank_fraction<=0.20) AS small20_ret,
          avg(ret1) FILTER (size_rank_fraction>=0.80) AS large20_ret,
          avg(ret1) FILTER (size_rank_fraction<=0.30) AS small30_ret,
          avg(ret1) FILTER (size_rank_fraction>=0.70) AS large30_ret,
          avg(ret1) FILTER (size_rank_fraction<=0.40) AS small40_ret,
          avg(ret1) FILTER (size_rank_fraction>=0.60) AS large40_ret,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction<=0.20) AS small20_positive,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction>=0.80) AS large20_positive,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction<=0.30) AS small30_positive,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction>=0.70) AS large30_positive,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction<=0.40) AS small40_positive,
          avg((ret1>0)::DOUBLE) FILTER (size_rank_fraction>=0.60) AS large40_positive,
          sum((size_tercile=1)::INTEGER) AS tercile1_count,
          sum((size_tercile=2)::INTEGER) AS tercile2_count,
          sum((size_tercile=3)::INTEGER) AS tercile3_count,
          sum((ret1>=return_q95 AND size_tercile=1)::INTEGER) AS winner5_t1,
          sum((ret1>=return_q95 AND size_tercile=2)::INTEGER) AS winner5_t2,
          sum((ret1>=return_q95 AND size_tercile=3)::INTEGER) AS winner5_t3,
          sum((ret1>=return_q90 AND size_tercile=1)::INTEGER) AS winner10_t1,
          sum((ret1>=return_q90 AND size_tercile=2)::INTEGER) AS winner10_t2,
          sum((ret1>=return_q90 AND size_tercile=3)::INTEGER) AS winner10_t3,
          sum((ret1>=return_q80 AND size_tercile=1)::INTEGER) AS winner20_t1,
          sum((ret1>=return_q80 AND size_tercile=2)::INTEGER) AS winner20_t2,
          sum((ret1>=return_q80 AND size_tercile=3)::INTEGER) AS winner20_t3,
          sum(greatest(ret1,0)) FILTER (size_tercile=1) AS positive_mass_t1,
          sum(greatest(ret1,0)) FILTER (size_tercile=2) AS positive_mass_t2,
          sum(greatest(ret1,0)) FILTER (size_tercile=3) AS positive_mass_t3,
          sum((size_quintile=1)::INTEGER) AS quintile1_count,
          sum((size_quintile=2)::INTEGER) AS quintile2_count,
          sum((size_quintile=3)::INTEGER) AS quintile3_count,
          sum((size_quintile=4)::INTEGER) AS quintile4_count,
          sum((size_quintile=5)::INTEGER) AS quintile5_count,
          avg(ret1) FILTER (size_quintile=1) AS quintile1_ret,
          avg(ret1) FILTER (size_quintile=2) AS quintile2_ret,
          avg(ret1) FILTER (size_quintile=3) AS quintile3_ret,
          avg(ret1) FILTER (size_quintile=4) AS quintile4_ret,
          avg(ret1) FILTER (size_quintile=5) AS quintile5_ret
        FROM return_ranked_pre GROUP BY 1,2,3
        """
    )


def normalized_entropy(values: list[float]) -> float:
    masses = np.asarray(values, dtype=float)
    if np.any(~np.isfinite(masses)) or np.any(masses < 0) or masses.sum() <= 0:
        return float("nan")
    probabilities = masses[masses > 0] / masses.sum()
    return float(-np.sum(probabilities * np.log(probabilities)) / math.log(len(masses)))


def _daily_frame(connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> pd.DataFrame:
    dates = connection.execute("SELECT trade_date FROM calendar ORDER BY trade_date").df()
    grid = pd.MultiIndex.from_product(
        [
            pd.to_datetime(dates["trade_date"]),
            spec["population"]["views"],
            spec["population"]["denominators"],
        ],
        names=["trade_date", "market_view", "denominator"],
    ).to_frame(index=False)
    structure = connection.execute("SELECT * FROM structure_daily").df()
    returns = connection.execute("SELECT * FROM return_daily").df()
    structure["trade_date"] = pd.to_datetime(structure["trade_date"])
    returns["trade_date"] = pd.to_datetime(returns["trade_date"])
    out = grid.merge(structure, on=["trade_date", *GROUP_KEYS], how="left").merge(
        returns, on=["trade_date", *GROUP_KEYS], how="left"
    )
    view_minimums = spec["population"]["view_minimum_counts"]
    out["view_minimum_count"] = out["market_view"].map(view_minimums).astype(int)
    out["size_structure_valid"] = out["size_structure_count"] >= out["view_minimum_count"]
    out["return_population_valid"] = out["eligible_count"] >= out["view_minimum_count"]
    min_extreme = spec["bucket_definitions"]["minimum_extreme_bucket_members"]
    min_quintile = spec["bucket_definitions"]["minimum_quintile_members"]

    structure_fields = spec["roles"]["size_structure"]
    for field in [structure_fields["primary"], *structure_fields["neighbors"]]:
        out[field] = out[field].where(out["size_structure_valid"])

    for tail in (20, 30, 40):
        valid = (
            out["return_population_valid"]
            & (out[f"small{tail}_count"] >= min_extreme)
            & (out[f"large{tail}_count"] >= min_extreme)
        )
        out[f"size_return_spread1_small{tail}_large{tail}"] = (
            out[f"small{tail}_ret"] - out[f"large{tail}_ret"]
        ).where(valid)
        out[f"size_positive_participation_small{tail}_large{tail}"] = (
            out[f"small{tail}_positive"] - out[f"large{tail}_positive"]
        ).where(valid)

    tercile_valid = out["return_population_valid"] & pd.concat(
        [(out[f"tercile{i}_count"] >= min_extreme) for i in range(1, 4)], axis=1
    ).all(axis=1)
    for percentile in (5, 10, 20):
        fields = [f"winner{percentile}_t{i}" for i in range(1, 4)]
        out[f"size_winner_entropy_top{percentile}"] = [
            normalized_entropy(values) if valid else float("nan")
            for values, valid in zip(out[fields].to_numpy(dtype=float), tercile_valid, strict=True)
        ]
    mass_fields = [f"positive_mass_t{i}" for i in range(1, 4)]
    mass_values = out[mass_fields].to_numpy(dtype=float)
    mass_total = np.nansum(mass_values, axis=1)
    mass_valid = tercile_valid.to_numpy() & np.isfinite(mass_values).all(axis=1) & (mass_total > 0)
    probabilities = np.divide(
        mass_values,
        mass_total[:, None],
        out=np.full_like(mass_values, np.nan),
        where=mass_total[:, None] > 0,
    )
    max_share = np.full(len(out), np.nan, dtype=float)
    max_share[mass_valid] = np.max(probabilities[mass_valid], axis=1)
    out["size_positive_mass_max_share"] = max_share
    out["size_positive_mass_hhi"] = np.where(
        mass_valid, np.nansum(probabilities**2, axis=1), np.nan
    )
    mass_entropy = np.asarray([
        normalized_entropy(values) if valid else float("nan")
        for values, valid in zip(mass_values, mass_valid, strict=True)
    ])
    out["size_positive_mass_one_minus_entropy"] = 1.0 - mass_entropy

    quintile_counts = [f"quintile{i}_count" for i in range(1, 6)]
    quintile_fields = [f"quintile{i}_ret" for i in range(1, 6)]
    quintile_valid = out["return_population_valid"] & pd.concat(
        [(out[field] >= min_quintile) for field in quintile_counts], axis=1
    ).all(axis=1)
    quintile_values = out[quintile_fields].to_numpy(dtype=float)
    curve_valid = quintile_valid.to_numpy() & np.isfinite(quintile_values).all(axis=1)
    out["size_bucket_return_std5"] = np.where(
        curve_valid, np.std(quintile_values, axis=1), np.nan
    )
    out["size_bucket_return_range5"] = np.where(
        curve_valid, np.max(quintile_values, axis=1) - np.min(quintile_values, axis=1), np.nan
    )
    out["size_bucket_return_mean_adjacent_gap5"] = np.where(
        curve_valid, np.mean(np.abs(np.diff(quintile_values, axis=1)), axis=1), np.nan
    )

    out = out.sort_values([*GROUP_KEYS, "trade_date"]).reset_index(drop=True)
    primary_spread_valid = (
        out["small30_ret"].notna() & out["large30_ret"].notna()
        & (out["small30_ret"] > -1.0) & (out["large30_ret"] > -1.0)
    )
    out["daily_size_log_spread30"] = (
        np.log1p(out["small30_ret"]) - np.log1p(out["large30_ret"])
    ).where(primary_spread_valid)
    grouped_spread = out.groupby(GROUP_KEYS, sort=False)["daily_size_log_spread30"]
    for horizon in (10, 20, 40):
        out[f"size_return_spread{horizon}_small30_large30"] = grouped_spread.transform(
            lambda values, h=horizon: values.rolling(h, min_periods=h).sum()
        )
    grouped_leadership = out.groupby(GROUP_KEYS, sort=False)[
        "size_return_spread20_small30_large30"
    ]
    for horizon in (3, 5, 10):
        out[f"size_leadership_transition{horizon}"] = (
            out["size_return_spread20_small30_large30"] - grouped_leadership.shift(horizon)
        )
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def _attach_coordinates(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy().sort_values([*GROUP_KEYS, "trade_date"]).reset_index(drop=True)
    primaries = [spec["roles"][role]["primary"] for role in spec["role_priority"]]
    pieces: list[pd.DataFrame] = []
    for _, group in out.groupby(GROUP_KEYS, sort=True):
        item = group.copy()
        for field in primaries:
            item[f"{field}__pit_3y_pct"] = causal_rolling_percentile(
                item[field], window=756, min_history=504
            )
            item[f"{field}__pit_3y_robust_z"] = causal_rolling_robust_z(
                item[field], window=756, min_history=504
            )
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True)
    for field in primaries:
        all_value = out[field].where(out["market_view"].eq("ALL_A")).groupby(
            [out["trade_date"], out["denominator"]], sort=False
        ).transform("max")
        out[f"{field}__relative_to_all"] = out[field] - all_value
        counts = out.groupby(["trade_date", "denominator"])[field].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[field].rank(method="average", pct=True)
        out[f"{field}__relative_view_rank_pct"] = ranks.where(counts >= 3)
    out["decision_at"] = out["trade_date"].dt.strftime("%Y-%m-%d") + "T15:00:00+08:00"
    out["available_at"] = out["decision_at"]
    out["snapshot_id"] = SNAPSHOT_ID
    return out.sort_values(["trade_date", "denominator", "market_view"]).reset_index(drop=True)


def _compress(
    correlation: pd.DataFrame, passing: list[str], priority: list[str], threshold: float
) -> tuple[list[str], dict[str, str]]:
    accepted: list[str] = []
    excluded: dict[str, str] = {}
    for role in priority:
        if role not in passing:
            excluded[role] = "construction_gate_failed"
            continue
        redundant_with = next(
            (
                kept for kept in accepted
                if abs(float(correlation.loc[role, kept])) >= threshold
            ),
            None,
        )
        if redundant_with is None:
            accepted.append(role)
        else:
            excluded[role] = f"redundant_with:{redundant_with}"
    return accepted, excluded


def _diagnostics(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], pd.DataFrame, list[str], dict[str, str]]:
    gates = spec["gates"]
    diagnostics: dict[str, Any] = {}
    for role in spec["role_priority"]:
        definition = spec["roles"][role]
        primary = definition["primary"]
        coverage = {
            str(view): float(group[primary].notna().mean())
            for view, group in panel.loc[panel["denominator"] == "ALL_STATUS"].groupby(
                "market_view", sort=True
            )
        }
        neighbors: dict[str, Any] = {}
        neighbor_medians: list[float] = []
        for neighbor in definition["neighbors"]:
            by_view = {
                str(view): float(group[[primary, neighbor]].corr(method="spearman").iloc[0, 1])
                for view, group in panel.loc[panel["denominator"] == "ALL_STATUS"].groupby(
                    "market_view", sort=True
                )
            }
            median = float(np.median(list(by_view.values())))
            neighbors[neighbor] = {"by_view": by_view, "median_across_views": median}
            neighbor_medians.append(median)
        denominator_by_view: dict[str, float] = {}
        for view in spec["population"]["views"]:
            wide = panel.loc[panel["market_view"] == view, ["trade_date", "denominator", primary]].pivot(
                index="trade_date", columns="denominator", values=primary
            )
            denominator_by_view[view] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.median(list(denominator_by_view.values())))
        year_support: dict[str, Any] = {}
        year_checks: list[bool] = []
        source = panel.loc[panel["denominator"] == "ALL_STATUS"].assign(
            year=panel.loc[panel["denominator"] == "ALL_STATUS", "trade_date"].dt.year
        )
        for (view, year), cell in source.groupby(["market_view", "year"], sort=True):
            if int(year) not in gates["eligible_years"]:
                continue
            values = cell[primary].dropna()
            nondegenerate = bool(len(values) >= gates["minimum_view_year_observations"] and values.nunique() > 1)
            year_checks.append(nondegenerate)
            year_support[f"{view}:{year}"] = {
                "observations": int(len(values)),
                "nondegenerate": nondegenerate,
            }
        pit_expected: list[bool] = []
        pit_observed: list[bool] = []
        z_observed: list[bool] = []
        for _, group in panel.sort_values([*GROUP_KEYS, "trade_date"]).groupby(GROUP_KEYS, sort=True):
            expected = group[primary].notna().cumsum() >= 504
            expected &= group[primary].notna()
            pit_expected.extend(expected.tolist())
            pit_observed.extend(group[f"{primary}__pit_3y_pct"].notna().tolist())
            z_observed.extend(group[f"{primary}__pit_3y_robust_z"].notna().tolist())
        expected_array = np.asarray(pit_expected, dtype=bool)
        pit_array = np.asarray(pit_observed, dtype=bool)
        z_array = np.asarray(z_observed, dtype=bool)
        pit_coverage = float(pit_array[expected_array].mean()) if expected_array.any() else 0.0
        z_coverage = float(z_array[expected_array].mean()) if expected_array.any() else 0.0
        relative_expected = panel[primary].notna()
        relative_coverage = float(
            panel.loc[relative_expected, f"{primary}__relative_to_all"].notna().mean()
        )
        rank_coverage = float(
            panel.loc[relative_expected, f"{primary}__relative_view_rank_pct"].notna().mean()
        )
        checks = {
            "raw_coverage": min(coverage.values()) >= gates["minimum_raw_coverage_each_view"],
            "neighbor_stability": min(neighbor_medians) >= gates["minimum_neighbor_median_spearman"],
            "denominator_stability": denominator_median >= gates["minimum_denominator_median_spearman"],
            "year_cells": bool(year_checks and all(year_checks)),
            "pit_coverage": pit_coverage >= gates["expected_pit_coverage"],
            "robust_z_coverage": z_coverage >= gates["expected_pit_coverage"],
            "relative_to_all_coverage": relative_coverage >= gates["expected_relative_coverage"],
            "relative_rank_coverage": rank_coverage >= gates["expected_relative_coverage"],
        }
        diagnostics[role] = {
            "primary": primary,
            "coverage_by_view": coverage,
            "neighbors": neighbors,
            "denominator_by_view": denominator_by_view,
            "denominator_median": denominator_median,
            "year_support": year_support,
            "pit_expected_coverage": pit_coverage,
            "robust_z_expected_coverage": z_coverage,
            "relative_to_all_expected_coverage": relative_coverage,
            "relative_rank_expected_coverage": rank_coverage,
            "checks": checks,
            "construction_gate_pass": bool(all(checks.values())),
        }
    role_to_field = {role: spec["roles"][role]["primary"] for role in spec["role_priority"]}
    redundancy = panel.loc[
        (panel["market_view"] == "ALL_A") & (panel["denominator"] == "ALL_STATUS"),
        list(role_to_field.values()),
    ].rename(columns={field: role for role, field in role_to_field.items()}).corr(method="spearman")
    passing = [role for role in spec["role_priority"] if diagnostics[role]["construction_gate_pass"]]
    accepted, excluded = _compress(
        redundancy,
        passing,
        spec["role_priority"],
        gates["role_redundancy_absolute_spearman"],
    )
    return diagnostics, redundancy, accepted, excluded


def _output_columns(spec: dict[str, Any]) -> list[str]:
    roles = [field for role in spec["role_priority"] for field in (
        spec["roles"][role]["primary"], *spec["roles"][role]["neighbors"]
    )]
    coordinate_fields = [field for role in spec["role_priority"] for field in (
        f"{spec['roles'][role]['primary']}__pit_3y_pct",
        f"{spec['roles'][role]['primary']}__pit_3y_robust_z",
        f"{spec['roles'][role]['primary']}__relative_to_all",
        f"{spec['roles'][role]['primary']}__relative_view_rank_pct",
    )]
    return [
        "trade_date", "market_view", "denominator", "decision_at", "available_at",
        "snapshot_id", "size_structure_count", "eligible_count", "view_minimum_count",
        "size_structure_valid", "return_population_valid", *roles, *coordinate_fields,
    ]


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-STYLE-001 circulating-size representation",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        "- Bucket assignment: exact t-1 circulating-market-value rank; no current-close sort.",
        "- Total-cap, true-free-float, growth/value, beta, future, strategy, post-2023, and CY-011 fields read: **none**.",
        "- Any passing role is a representation only, not a small-cap premium, timing signal, habitat, or rule.",
        "",
        "## Role diagnostics",
        "",
        "| Role | Min coverage | Worst neighbor rho | Denominator rho | PIT | Relative | Gate |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for role, item in result["role_diagnostics"].items():
        neighbor_values = [
            value["median_across_views"] for value in item["neighbors"].values()
            if value["median_across_views"] is not None
        ]
        worst_neighbor = min(neighbor_values) if neighbor_values else float("nan")
        relative = min(
            item["relative_to_all_expected_coverage"], item["relative_rank_expected_coverage"]
        )
        lines.append(
            f"| `{role}` | {min(item['coverage_by_view'].values()):.3f} | "
            f"{worst_neighbor:.3f} | {item['denominator_median']:.3f} | "
            f"{item['pit_expected_coverage']:.3f} | {relative:.3f} | "
            f"{'PASS' if item['construction_gate_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Fixed-priority compression",
        "",
        f"- Accepted roles: `{', '.join(result['compression']['accepted_roles']) or 'none'}`",
        f"- Excluded roles: `{json.dumps(result['compression']['excluded_roles'], sort_keys=True)}`",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec, data_spec = _load_spec()
    paths, source_hashes = _verify_bound_source(data_spec)
    with tempfile.TemporaryDirectory(prefix="mkt-style-001-") as temp_dir:
        connection = duckdb.connect()
        connection.execute(f"SET threads={DUCKDB_THREADS}")
        connection.execute(f"SET temp_directory='{temp_dir}'")
        _create_source(connection, paths)
        _create_security_coordinates(connection)
        _create_expanded_views(connection)
        _create_daily_components(connection)
        daily = _daily_frame(connection, spec)
        connection.close()
    panel = _attach_coordinates(daily, spec)
    if len(panel) != spec["population"]["expected_rows"] or panel.duplicated(
        ["trade_date", *GROUP_KEYS]
    ).any():
        raise StyleRepresentationError("output row/key identity mismatch")
    counts = panel.groupby(GROUP_KEYS).size()
    if len(counts) != 8 or not (counts == spec["population"]["expected_rows_per_group"]).all():
        raise StyleRepresentationError("output group population mismatch")
    if str(panel["trade_date"].min().date()) != spec["population"]["date_start"]:
        raise StyleRepresentationError("output start changed")
    if str(panel["trade_date"].max().date()) != spec["population"]["date_end"]:
        raise StyleRepresentationError("output end changed")
    diagnostics, redundancy, accepted, excluded = _diagnostics(panel, spec)

    output = panel[_output_columns(spec)].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(accepted)}_OF_{len(spec['role_priority'])}_MINIMAL_ROLES",
        "usefulness_claim": "NONE",
        "small_cap_premium_claim": "NONE",
        "risk_appetite_claim": "NONE",
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "unregistered_style_fields_read": [],
        "current_close_bucket_assignment_used": False,
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "rows": int(len(panel)),
            "groups": int(panel.groupby(GROUP_KEYS).ngroups),
            "first_date": str(panel["trade_date"].min().date()),
            "last_date": str(panel["trade_date"].max().date()),
        },
        "role_diagnostics": diagnostics,
        "redundancy_spearman": redundancy.to_dict(),
        "compression": {"accepted_roles": accepted, "excluded_roles": excluded},
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "data_contract_spec_sha256": spec["inputs"]["data_contract_spec"]["sha256"],
            "data_contract_result_sha256": spec["inputs"]["data_contract_result"]["sha256"],
            "source": source_hashes,
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "compression": completed["compression"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
