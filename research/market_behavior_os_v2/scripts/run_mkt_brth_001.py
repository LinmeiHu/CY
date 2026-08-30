#!/usr/bin/env python3
"""Build the strategy-independent MKT-BRTH-001 breadth representation panel."""

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

from run_mkt_trnd_001 import (  # noqa: E402
    causal_expanding_percentile,
    causal_rolling_percentile,
    causal_rolling_robust_z,
)


SPEC_PATH = PROGRAM / "experiments/MKT-BRTH-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BRTH-001_breadth_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BRTH-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BRTH-001_breadth_representation_freeze.md"
MANIFEST_SHA = "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2"
SNAPSHOT_ID = f"CY-006:{MANIFEST_SHA}"
MIN_PIT_HISTORY = 504
PIT_WINDOW = 756

ROLE_MAP = {
    "participation": ("breadth_above_ma20", ("breadth_above_ma10", "breadth_above_ma60")),
    "depth": (
        "breadth_median_distance_ma20",
        ("breadth_median_distance_ma10", "breadth_median_distance_ma60"),
    ),
    "new_high_low": (
        "breadth_net_new_high_low60",
        ("breadth_net_new_high_low40", "breadth_net_new_high_low80"),
    ),
    "momentum": (
        "breadth_momentum_balance5",
        ("breadth_momentum_balance3", "breadth_momentum_balance10"),
    ),
    "acceleration": (
        "breadth_participation_acceleration5",
        ("breadth_participation_acceleration3", "breadth_participation_acceleration10"),
    ),
    "industry_diffusion": (
        "industry_diffusion_ma20",
        ("industry_diffusion_ma10", "industry_diffusion_ma60"),
    ),
    "leadership_concentration": (
        "leadership_positive_mass_top10",
        ("leadership_positive_mass_top5", "leadership_positive_mass_top20"),
    ),
    "divergence": (
        "breadth_industry_divergence_ma20",
        ("breadth_industry_divergence_ma10", "breadth_industry_divergence_ma60"),
    ),
    "transition": (
        "breadth_net_crossing_ma20_5",
        ("breadth_net_crossing_ma20_3", "breadth_net_crossing_ma20_10"),
    ),
}
MINIMAL_PRIORITY = (
    "participation",
    "depth",
    "new_high_low",
    "momentum",
    "industry_diffusion",
    "leadership_concentration",
    "divergence",
    "acceleration",
    "transition",
)
VIEW_MINIMUMS = {"ALL_A": 1000, "SH_A": 400, "SZ_A": 400, "CHINEXT_BOARD": 200}
DUCKDB_THREADS = 4


class BreadthFreezeError(RuntimeError):
    """Fail-closed breadth construction error."""


def _load_spec() -> tuple[dict, dict, str]:
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if "inherits_spec_path" not in control:
        own_hash = sha256_file(SPEC_PATH)
        return control, control, own_hash
    parent_path = ROOT / control["inherits_spec_path"]
    parent_hash = sha256_file(parent_path)
    if parent_hash != control["inherits_spec_sha256"]:
        raise BreadthFreezeError("inherited scientific spec identity mismatch")
    merged = json.loads(parent_path.read_text(encoding="utf-8"))
    for key, value in control.items():
        if key not in {"inherits_spec_path", "inherits_spec_sha256"}:
            merged[key] = value
    return merged, control, parent_hash


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def connected_components(correlation: pd.DataFrame, threshold: float = 0.85) -> list[list[str]]:
    remaining = set(str(item) for item in correlation.columns)
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
            neighbors = [
                str(other)
                for other in correlation.columns
                if str(other) not in component
                and np.isfinite(correlation.loc[current, other])
                and abs(float(correlation.loc[current, other])) >= threshold
            ]
            stack.extend(neighbors)
        components.append(sorted(component))
    return sorted(components, key=lambda items: (MINIMAL_PRIORITY.index(items[0]) if items[0] in MINIMAL_PRIORITY else 99, items))


def _verify_inputs(spec: dict) -> tuple[list[Path], dict[str, str]]:
    manifest_path = Path(spec["input"]["manifest_path"])
    if sha256_file(manifest_path) != MANIFEST_SHA:
        raise BreadthFreezeError("CY-006 manifest identity mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hashes = {item["path"]: item["sha256"] for item in manifest["files"]}
    source_root = Path(spec["input"]["source_root"])
    paths: list[Path] = []
    observed: dict[str, str] = {}
    for relative, expected in sorted(spec["input"]["selected_partition_sha256"].items()):
        if relative not in manifest_hashes or manifest_hashes[relative] != expected:
            raise BreadthFreezeError(f"manifest partition mismatch: {relative}")
        path = source_root / relative
        actual = sha256_file(path)
        if actual != expected:
            raise BreadthFreezeError(f"source partition hash mismatch: {relative}")
        if any(token in relative for token in ("2024", "2025", "2026")):
            raise BreadthFreezeError("post-2023 partition entered selected inputs")
        paths.append(path)
        observed[relative] = actual
    if len(paths) != 6:
        raise BreadthFreezeError("exact six pre-2024 partitions required")
    return paths, observed


def _create_source_view(connection: duckdb.DuckDBPyConnection, paths: list[Path]) -> None:
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")


def _audit_source(connection: duckdb.DuckDBPyConnection, spec: dict) -> dict:
    summary = connection.execute(
        """
        SELECT count(*) AS rows,
               count(*)-count(DISTINCT (symbol,trade_date)) AS duplicate_keys,
               min(trade_date) AS first_date,max(trade_date) AS last_date,
               sum((available_at>decision_at)::INTEGER) AS time_travel_rows,
               count(DISTINCT snapshot_id) AS snapshot_count,
               sum((hard_valid AND
                    (high<greatest(open,close,low) OR low>least(open,close,high)))::INTEGER)
                 AS hard_valid_ohlc_failures,
               sum((hard_valid AND
                    (close IS NULL OR NOT isfinite(close) OR close<=0))::INTEGER)
                 AS hard_valid_close_failures
        FROM source
        """
    ).fetchone()
    result = {
        "rows": int(summary[0]),
        "duplicate_keys": int(summary[1]),
        "first_date": str(summary[2]),
        "last_date": str(summary[3]),
        "time_travel_rows": int(summary[4]),
        "snapshot_count": int(summary[5]),
        "hard_valid_ohlc_failures": int(summary[6]),
        "hard_valid_close_failures": int(summary[7]),
    }
    expected = spec["input"]
    if result["rows"] != expected["outcome_blind_audit_rows"]:
        raise BreadthFreezeError("source row count changed")
    if result["duplicate_keys"] != 0 or result["time_travel_rows"] != 0:
        raise BreadthFreezeError("source key/PIT audit failed")
    if result["last_date"] > "2023-12-31" or result["first_date"] != "2018-01-02":
        raise BreadthFreezeError("source date boundary failed")
    if result["hard_valid_ohlc_failures"] or result["hard_valid_close_failures"]:
        raise BreadthFreezeError("hard-valid source price audit failed")
    return result


def _create_security_states(connection: duckdb.DuckDBPyConnection) -> None:
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
        SELECT s.trade_date,c.cal_idx,s.symbol,s.open,s.high,s.low,s.close,s.volume,s.amount,
               s.trade_status,s.current_day_data_tradable,s.is_st,s.industry,s.industry_valid,
               s.source_notice_date,s.corporate_action_count,s.corporate_action_available_date,
               s.corporate_action_blocking,s.share_multiplier,s.cash_per_share,s.rights_ratio,
               s.hard_valid,s.bar_valid,s.trading_state_valid,s.corporate_action_valid,
               s.market_rule_valid,s.historical_identity_valid,s.available_at,s.decision_at,
               (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
                AND s.trading_state_valid IS TRUE AND s.corporate_action_valid IS TRUE
                AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
                AND s.corporate_action_blocking IS FALSE
                AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
                AND s.close IS NOT NULL AND isfinite(s.close) AND s.close>0
                AND s.open IS NOT NULL AND isfinite(s.open) AND s.open>0
                AND s.high IS NOT NULL AND isfinite(s.high) AND s.high>=greatest(s.open,s.close,s.low)
                AND s.low IS NOT NULL AND isfinite(s.low) AND s.low<=least(s.open,s.close,s.high)
                AND s.volume IS NOT NULL AND isfinite(s.volume) AND s.volume>=0
                AND s.amount IS NOT NULL AND isfinite(s.amount) AND s.amount>=0) AS history_valid,
               (s.hard_valid IS TRUE AND s.trade_status=1
                AND s.current_day_data_tradable IS TRUE
                AND s.volume IS NOT NULL AND isfinite(s.volume) AND s.volume>0) AS current_valid,
               CASE WHEN s.industry_valid IS TRUE AND s.industry IS NOT NULL
                          AND trim(s.industry)<>'' AND s.source_notice_date IS NOT NULL
                          AND s.source_notice_date<=s.trade_date
                    THEN s.industry ELSE NULL END AS causal_industry
        FROM source s JOIN calendar c USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_step AS
        SELECT *,lag(close) OVER w AS previous_close,
               lag(history_valid) OVER w AS previous_history_valid,
               lag(cal_idx) OVER w AS previous_cal_idx
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
        CREATE TEMP TABLE stock_adjusted AS
        SELECT *,exp(sum(coalesce(step_log_return,0.0)) OVER (
                 PARTITION BY symbol ORDER BY trade_date
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS adjusted_close
        FROM stock_chain
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_windows AS
        SELECT *,adjusted_close*high/close AS adjusted_high,
               adjusted_close*low/close AS adjusted_low,
               sum(coordinate_step_valid::INTEGER) OVER w120 AS coordinate_valid_count120,
               count(*) OVER w121 AS history_row_count121,
               min(cal_idx) OVER w121 AS history_min_cal_idx121,
               sum(history_valid::INTEGER) OVER w121 AS history_valid_count121,
               avg(adjusted_close) OVER w10 AS ma10,
               avg(adjusted_close) OVER w20 AS ma20,
               avg(adjusted_close) OVER w60 AS ma60,
               max(adjusted_close*high/close) OVER w40 AS high40,
               min(adjusted_close*low/close) OVER w40 AS low40,
               max(adjusted_close*high/close) OVER w60 AS high60,
               min(adjusted_close*low/close) OVER w60 AS low60,
               max(adjusted_close*high/close) OVER w80 AS high80,
               min(adjusted_close*low/close) OVER w80 AS low80,
               lag(adjusted_close,3) OVER w AS lag_close3,
               lag(adjusted_close,5) OVER w AS lag_close5,
               lag(adjusted_close,10) OVER w AS lag_close10,
               lag(adjusted_close,20) OVER w AS lag_close20,
               lag(cal_idx,3) OVER w AS lag_idx3,
               lag(cal_idx,5) OVER w AS lag_idx5,
               lag(cal_idx,10) OVER w AS lag_idx10,
               lag(cal_idx,20) OVER w AS lag_idx20
        FROM stock_adjusted
        WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
          w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 9 PRECEDING AND CURRENT ROW),
          w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW),
          w40 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW),
          w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 59 PRECEDING AND CURRENT ROW),
          w80 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 79 PRECEDING AND CURRENT ROW),
          w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW),
          w121 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND CURRENT ROW)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_prestate AS
        SELECT *,adjusted_close>ma10 AS above_ma10,
               adjusted_close>ma20 AS above_ma20,adjusted_close>ma60 AS above_ma60
        FROM stock_windows
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stock_lagged AS
        SELECT *,lag(above_ma20,3) OVER w AS lag_above_ma20_3,
               lag(above_ma20,5) OVER w AS lag_above_ma20_5,
               lag(above_ma20,10) OVER w AS lag_above_ma20_10
        FROM stock_prestate WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE core AS
        SELECT trade_date,cal_idx,symbol,is_st,causal_industry,
               above_ma10,above_ma20,above_ma60,
               adjusted_close/ma10-1 AS distance_ma10,
               adjusted_close/ma20-1 AS distance_ma20,
               adjusted_close/ma60-1 AS distance_ma60,
               adjusted_close>=high40 AS new_high40,adjusted_close<=low40 AS new_low40,
               adjusted_close>=high60 AS new_high60,adjusted_close<=low60 AS new_low60,
               adjusted_close>=high80 AS new_high80,adjusted_close<=low80 AS new_low80,
               adjusted_close/lag_close3-1 AS ret3,
               adjusted_close/lag_close5-1 AS ret5,
               adjusted_close/lag_close10-1 AS ret10,
               adjusted_close/lag_close20-1 AS ret20,
               CASE WHEN above_ma20 AND NOT lag_above_ma20_3 THEN 1
                    WHEN NOT above_ma20 AND lag_above_ma20_3 THEN -1 ELSE 0 END AS crossing3,
               CASE WHEN above_ma20 AND NOT lag_above_ma20_5 THEN 1
                    WHEN NOT above_ma20 AND lag_above_ma20_5 THEN -1 ELSE 0 END AS crossing5,
               CASE WHEN above_ma20 AND NOT lag_above_ma20_10 THEN 1
                    WHEN NOT above_ma20 AND lag_above_ma20_10 THEN -1 ELSE 0 END AS crossing10
        FROM stock_lagged
        WHERE current_valid AND history_valid
          AND coordinate_valid_count120=120
          AND history_row_count121=121 AND history_valid_count121=121
          AND cal_idx-history_min_cal_idx121=120
          AND cal_idx-lag_idx3=3 AND cal_idx-lag_idx5=5
          AND cal_idx-lag_idx10=10 AND cal_idx-lag_idx20=20
          AND lag_above_ma20_3 IS NOT NULL AND lag_above_ma20_5 IS NOT NULL
          AND lag_above_ma20_10 IS NOT NULL
        """
    )


def _create_daily_breadth(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE view_rows AS
        SELECT 'ALL_A' AS market_view,* FROM core
        UNION ALL SELECT 'SH_A',* FROM core WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM core WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM core
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
        CREATE TEMP TABLE thresholds AS
        SELECT market_view,denominator,trade_date,
               quantile_cont(ret20,0.95) AS q95,quantile_cont(ret20,0.90) AS q90,
               quantile_cont(ret20,0.80) AS q80
        FROM expanded GROUP BY 1,2,3
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE daily_security AS
        SELECT e.market_view,e.denominator,e.trade_date,max(e.cal_idx) AS cal_idx,
               count(*) AS eligible_count,count(e.causal_industry) AS industry_mapped_count,
               avg(e.above_ma10::DOUBLE) AS breadth_above_ma10,
               avg(e.above_ma20::DOUBLE) AS breadth_above_ma20,
               avg(e.above_ma60::DOUBLE) AS breadth_above_ma60,
               median(e.distance_ma10) AS breadth_median_distance_ma10,
               median(e.distance_ma20) AS breadth_median_distance_ma20,
               median(e.distance_ma60) AS breadth_median_distance_ma60,
               avg(e.new_high40::DOUBLE)-avg(e.new_low40::DOUBLE) AS breadth_net_new_high_low40,
               avg(e.new_high60::DOUBLE)-avg(e.new_low60::DOUBLE) AS breadth_net_new_high_low60,
               avg(e.new_high80::DOUBLE)-avg(e.new_low80::DOUBLE) AS breadth_net_new_high_low80,
               avg(sign(e.ret3)) AS breadth_momentum_balance3,
               avg(sign(e.ret5)) AS breadth_momentum_balance5,
               avg(sign(e.ret10)) AS breadth_momentum_balance10,
               avg(e.crossing3) AS breadth_net_crossing_ma20_3,
               avg(e.crossing5) AS breadth_net_crossing_ma20_5,
               avg(e.crossing10) AS breadth_net_crossing_ma20_10,
               sum(CASE WHEN e.ret20>0 AND e.ret20>=t.q95 THEN e.ret20 ELSE 0 END)
                 /nullif(sum(greatest(e.ret20,0)),0) AS leadership_positive_mass_top5,
               sum(CASE WHEN e.ret20>0 AND e.ret20>=t.q90 THEN e.ret20 ELSE 0 END)
                 /nullif(sum(greatest(e.ret20,0)),0) AS leadership_positive_mass_top10,
               sum(CASE WHEN e.ret20>0 AND e.ret20>=t.q80 THEN e.ret20 ELSE 0 END)
                 /nullif(sum(greatest(e.ret20,0)),0) AS leadership_positive_mass_top20
        FROM expanded e JOIN thresholds t USING(market_view,denominator,trade_date)
        GROUP BY e.market_view,e.denominator,e.trade_date
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_groups AS
        SELECT market_view,denominator,trade_date,causal_industry,count(*) AS member_count,
               avg(above_ma10::DOUBLE) AS above_ma10,
               avg(above_ma20::DOUBLE) AS above_ma20,
               avg(above_ma60::DOUBLE) AS above_ma60
        FROM expanded WHERE causal_industry IS NOT NULL
        GROUP BY 1,2,3,4 HAVING count(*)>=5
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE industry_daily AS
        SELECT market_view,denominator,trade_date,count(*) AS included_industry_count,
               avg((above_ma10>0.5)::DOUBLE) AS industry_diffusion_ma10,
               avg((above_ma20>0.5)::DOUBLE) AS industry_diffusion_ma20,
               avg((above_ma60>0.5)::DOUBLE) AS industry_diffusion_ma60
        FROM industry_groups GROUP BY 1,2,3
        """
    )
    return connection.execute(
        """
        SELECT s.*,s.industry_mapped_count::DOUBLE/s.eligible_count AS industry_mapping_coverage,
               i.included_industry_count,i.industry_diffusion_ma10,
               i.industry_diffusion_ma20,i.industry_diffusion_ma60
        FROM daily_security s LEFT JOIN industry_daily i
          USING(market_view,denominator,trade_date)
        ORDER BY trade_date,denominator,market_view
        """
    ).df()


def _attach_time_coordinates(frame: pd.DataFrame) -> pd.DataFrame:
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
    nonindustry = [
        column
        for role, (primary, neighbors) in ROLE_MAP.items()
        if role not in {"acceleration", "industry_diffusion", "divergence"}
        for column in (primary, *neighbors)
    ]
    out.loc[~out["view_valid"], nonindustry] = np.nan
    for column in ("industry_diffusion_ma10", "industry_diffusion_ma20", "industry_diffusion_ma60"):
        out.loc[~out["industry_valid"], column] = np.nan
    for horizon in (3, 5, 10):
        grouped = out.groupby(["market_view", "denominator"], sort=False)["breadth_above_ma20"]
        out[f"breadth_participation_acceleration{horizon}"] = (
            out["breadth_above_ma20"] - 2.0 * grouped.shift(horizon) + grouped.shift(2 * horizon)
        )
    for horizon in (10, 20, 60):
        out[f"breadth_industry_divergence_ma{horizon}"] = (
            out[f"breadth_above_ma{horizon}"] - out[f"industry_diffusion_ma{horizon}"]
        )
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
        all_values = (
            out.loc[out["market_view"] == "ALL_A", ["trade_date", "denominator", column]]
            .rename(columns={column: "_all_value"})
        )
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


def _diagnostics(panel: pd.DataFrame) -> tuple[dict, pd.DataFrame, list[list[str]], list[str], dict[str, str]]:
    diagnostics: dict[str, dict] = {}
    primary_columns = {role: definition[0] for role, definition in ROLE_MAP.items()}
    primary_panel = panel.loc[panel["denominator"] == "ALL_STATUS"].copy()
    for role, (primary, neighbors) in ROLE_MAP.items():
        coverage_by_view: dict[str, float] = {}
        neighbor_stats: dict[str, dict] = {}
        for market_view, group in primary_panel.groupby("market_view", sort=True):
            eligible = group.loc[(group["view_valid"]) & (group["within_view_observation"] >= 20)]
            coverage_by_view[str(market_view)] = float(eligible[primary].notna().mean())
        neighbor_medians: list[float] = []
        for neighbor in neighbors:
            by_view: dict[str, float] = {}
            for market_view, group in primary_panel.groupby("market_view", sort=True):
                rho = group[[primary, neighbor]].corr(method="spearman").iloc[0, 1]
                by_view[str(market_view)] = float(rho)
            median_rho = float(np.median(list(by_view.values())))
            neighbor_medians.append(median_rho)
            neighbor_stats[neighbor] = {"median_across_views": median_rho, "by_view": by_view}

        denominator_by_view: dict[str, float] = {}
        for market_view in sorted(panel["market_view"].unique()):
            wide = panel.loc[panel["market_view"] == market_view, ["trade_date", "denominator", primary]].pivot(
                index="trade_date", columns="denominator", values=primary
            )
            denominator_by_view[str(market_view)] = float(
                wide[["ALL_STATUS", "NON_ST"]].corr(method="spearman").iloc[0, 1]
            )
        denominator_median = float(np.median(list(denominator_by_view.values())))

        cell_checks: list[bool] = []
        eligible_cells = 0
        year_support: dict[str, dict] = {}
        with_year = primary_panel.assign(year=primary_panel["trade_date"].dt.year)
        for (market_view, year), cell in with_year.groupby(["market_view", "year"], sort=True):
            values = cell[primary].dropna()
            if len(values) >= 150:
                eligible_cells += 1
                std = float(values.std(ddof=0))
                cell_checks.append(bool(np.isfinite(std) and std > 0.0))
                year_support[f"{market_view}:{year}"] = {
                    "n": int(len(values)),
                    "p10": float(values.quantile(0.10)),
                    "median": float(values.median()),
                    "p90": float(values.quantile(0.90)),
                }
        nondegenerate = bool(eligible_cells > 0 and all(cell_checks))
        pit_expected = primary_panel[primary].notna().groupby(
            [primary_panel["market_view"], primary_panel["denominator"]]
        ).cumsum() >= MIN_PIT_HISTORY
        pit_coverage = float(
            primary_panel.loc[pit_expected, f"{primary}_pit_3y_pct"].notna().mean()
        ) if pit_expected.any() else float("nan")
        relative_expected = primary_panel["market_view"] != "ALL_A"
        relative_coverage = float(
            primary_panel.loc[relative_expected & primary_panel[primary].notna(), f"{primary}_relative_to_all"].notna().mean()
        )
        passed = bool(
            min(coverage_by_view.values()) >= 0.95
            and min(neighbor_medians) >= 0.70
            and denominator_median >= 0.90
            and nondegenerate
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

    redundancy_source = primary_panel.loc[primary_panel["market_view"] == "ALL_A", [
        primary_columns[role] for role in MINIMAL_PRIORITY
    ]].rename(columns={primary_columns[role]: role for role in MINIMAL_PRIORITY})
    correlation = redundancy_source.corr(method="spearman")
    components = connected_components(correlation, threshold=0.85)
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
        f"# {result['experiment_id']} strategy-independent breadth representation freeze",
        "",
        "## Construction boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Source: {result['input_audit']['rows']:,} CY-006 rows, {result['input_audit']['first_date']}..{result['input_audit']['last_date']}.",
        f"- Output: {result['population']['rows']:,} daily view/denominator rows across {result['population']['market_views']} governed views.",
        "- CHINEXT membership, strategy outcomes, trades, future returns, and CY-011 read: **none**.",
        "- This is representation-quality evidence, not economic usefulness or a habitat/strategy claim.",
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
        worst_neighbor = min(value["median_across_views"] for value in item["neighbors"].values())
        disposition = "ACCEPT" if role in accepted else result["minimal_panel"]["excluded_roles"].get(role, "EXCLUDE")
        lines.append(
            f"| {role} | `{item['primary']}` | {item['minimum_raw_coverage']:.3f} | "
            f"{worst_neighbor:.3f} | {item['all_status_vs_non_st_median']:.3f} | "
            f"{item['pit_3y_percentile_expected_coverage']:.3f} | {item['relative_to_all_expected_coverage']:.3f} | "
            f"{'PASS' if item['construction_gate_pass'] else 'FAIL'} | {disposition} |"
        )
    lines.extend(
        [
            "",
            "## Outcome-blind latent components",
            "",
            f"Absolute-Spearman connected components at 0.85: `{result['latent_components']}`.",
            "",
            "These components diagnose redundant manifestations; they do not prove a causal latent factor. Exact constituent-index breadth remains unavailable because historical constituent membership is not registered. SH/SZ/ChiNext-board views are portability diagnostics, not index-constituent breadth.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Scientific design SHA-256: `{result['hashes']['scientific_spec_sha256']}`",
            f"- CY-006 manifest SHA-256: `{result['hashes']['manifest_sha256']}`",
            f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run() -> dict:
    spec, _control, scientific_spec_hash = _load_spec()
    if spec["status"] != "FROZEN_BEFORE_CONSTRUCTION_RESULT":
        raise BreadthFreezeError("spec is not frozen before construction")
    paths, source_hashes = _verify_inputs(spec)
    with tempfile.TemporaryDirectory(prefix="mkt_brth_001_") as temporary:
        database_path = Path(temporary) / "breadth.duckdb"
        connection = duckdb.connect(str(database_path))
        connection.execute(f"SET threads={DUCKDB_THREADS}")
        connection.execute("SET memory_limit='6GB'")
        connection.execute(f"SET temp_directory='{temporary}'")
        try:
            _create_source_view(connection, paths)
            input_audit = _audit_source(connection, spec)
            _create_security_states(connection)
            daily = _create_daily_breadth(connection)
        finally:
            connection.close()

    panel = _attach_time_coordinates(daily)
    if panel["trade_date"].max() > pd.Timestamp("2023-12-31"):
        raise BreadthFreezeError("post-2023 row entered output")
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
    output_columns = [
        "trade_date", "market_view", "denominator", "eligible_count",
        "industry_mapped_count", "industry_mapping_coverage", "included_industry_count",
        "view_valid", "industry_valid", "within_view_observation", "decision_at",
        "available_at", "snapshot_id", *raw_columns, *coordinate_columns,
    ]
    output = panel[output_columns].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_STRATEGY_INDEPENDENT_BREADTH_REPRESENTATION_FREEZE",
        "usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "input_audit": input_audit,
        "population": {
            "rows": int(len(output)),
            "first_date": str(output["trade_date"].min()),
            "last_date": str(output["trade_date"].max()),
            "market_views": int(output["market_view"].nunique()),
            "denominators": sorted(str(item) for item in output["denominator"].unique()),
            "rows_by_view_denominator": {
                f"{view}:{denominator}": int(count)
                for (view, denominator), count in output.groupby(["market_view", "denominator"]).size().items()
            },
            "eligible_count_support": {
                f"{view}:{denominator}": {
                    "min": int(group["eligible_count"].min()),
                    "median": float(group["eligible_count"].median()),
                    "max": int(group["eligible_count"].max()),
                }
                for (view, denominator), group in panel.groupby(["market_view", "denominator"], sort=True)
            },
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
            "constituent_index_breadth": "UNAVAILABLE_NO_REGISTERED_HISTORICAL_MEMBERSHIP",
            "portability_views": ["ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"],
            "trend_breadth_interaction": "NOT_TESTED",
            "economic_usefulness": "NOT_TESTED",
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "scientific_spec_sha256": scientific_spec_hash,
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
