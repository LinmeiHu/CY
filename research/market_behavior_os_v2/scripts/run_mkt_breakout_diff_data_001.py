#!/usr/bin/env python3
"""Audit full-market objective-breakout diffusion representation domains."""

from __future__ import annotations

import hashlib
import json
import platform
import resource
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DIFF-DATA-001_spec.json"
COUNT_AUDIT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DATA-001_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DIFF-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DIFF-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "c659f60d2d38df9c8d02aa0a5f3d780c8cbb1df9104701ea8af47611bf46b58e"


class BreakoutDiffusionDataError(RuntimeError):
    """Fail-closed full-market breakout-diffusion data error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
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
        raise BreakoutDiffusionDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_FULL_MARKET_COORDINATE_OR_CROSSING_COUNTS"
        or spec["outcome_access"] is not False
    ):
        raise BreakoutDiffusionDataError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise BreakoutDiffusionDataError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise BreakoutDiffusionDataError("prohibited-input boundary changed")
    return spec


def _verify_registry_and_partitions(spec: dict[str, Any]) -> tuple[list[Path], dict[str, str]]:
    registry = json.loads(_resolve(spec["inputs"]["registry"]["path"]).read_text())
    assets = {item["asset_id"]: item for item in registry["assets"]}
    asset = assets.get("CY-006")
    inventory_hash = spec["inputs"]["cy006_inventory"]["sha256"]
    if (
        asset is None
        or asset["status"] != "RESEARCH_CONDITIONAL"
        or asset["pit_grade"] != "B"
        or asset["lineage"]["manifest_sha256"] != inventory_hash
    ):
        raise BreakoutDiffusionDataError("CY-006 registry activation changed")

    inventory_path = _resolve(spec["inputs"]["cy006_inventory"]["path"])
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    entries = {item["path"]: item for item in inventory["files"]}
    root = Path(inventory["root"])
    paths: list[Path] = []
    observed: dict[str, str] = {}
    required = spec["required_partitions"]["cy006"]
    if len(required) != 6 or any(str(year) in "|".join(required) for year in (2024, 2025, 2026)):
        raise BreakoutDiffusionDataError("partition boundary changed")
    for relative, expected in required.items():
        item = entries.get(relative)
        path = root / relative
        if item is None or item["sha256"] != expected or not path.is_file():
            raise BreakoutDiffusionDataError(f"inventory partition mismatch: {relative}")
        actual = sha256_file(path)
        if actual != expected:
            raise BreakoutDiffusionDataError(f"partition content mismatch: {relative}")
        paths.append(path)
        observed[relative] = actual
    return paths, observed


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _preflight_resource_guard(spec: dict[str, Any], paths: list[Path]) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(budget["system_memory_headroom_floor_gib"] * 2**30):
        raise BreakoutDiffusionDataError("system memory headroom below frozen floor")
    usage = shutil.disk_usage(ROOT)
    if usage.free / usage.total < float(budget["filesystem_headroom_fraction"]):
        raise BreakoutDiffusionDataError("filesystem headroom below frozen floor")
    source_bytes = sum(path.stat().st_size for path in paths)
    if source_bytes > int(budget["compressed_read_ceiling_gib"] * 2**30):
        raise BreakoutDiffusionDataError("compressed source exceeds frozen ceiling")


def _phase_resource_guard(spec: dict[str, Any], temp_dir: Path, started: float) -> None:
    budget = spec["resource_budget"]
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise BreakoutDiffusionDataError("process peak RSS ceiling breached")
    if _directory_bytes(temp_dir) > int(budget["temporary_spill_ceiling_gib"] * 2**30):
        raise BreakoutDiffusionDataError("temporary spill ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60.0:
        raise BreakoutDiffusionDataError("wall-clock ceiling breached")


def _create_source_and_audit(
    connection: duckdb.DuckDBPyConnection,
    paths: list[Path],
    spec: dict[str, Any],
) -> dict[str, Any]:
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")
    row = connection.execute(
        """
        SELECT count(*) AS rows,
               count(*)-count(DISTINCT (symbol,trade_date)) AS duplicate_keys,
               min(trade_date) AS first_date,max(trade_date) AS last_date,
               count(DISTINCT trade_date) AS exchange_dates,
               sum((available_at>decision_at)::INTEGER) AS time_travel_rows,
               sum((hard_valid AND
                    (high<greatest(open,close,low) OR low>least(open,close,high)))::INTEGER)
                 AS hard_valid_ohlc_failures
        FROM source
        """
    ).fetchone()
    audit = {
        "rows": int(row[0]),
        "duplicate_keys": int(row[1]),
        "first_date": str(row[2]),
        "last_date": str(row[3]),
        "exchange_dates": int(row[4]),
        "time_travel_rows": int(row[5]),
        "hard_valid_ohlc_failures": int(row[6]),
    }
    expected = spec["source_audit"]
    comparisons = {
        "rows": expected["expected_rows"],
        "first_date": expected["expected_first_date"],
        "last_date": expected["expected_last_date"],
        "exchange_dates": expected["expected_exchange_dates"],
        "duplicate_keys": expected["duplicate_keys"],
        "time_travel_rows": expected["time_travel_rows"],
        "hard_valid_ohlc_failures": expected["hard_valid_ohlc_failures"],
    }
    if any(audit[key] != value for key, value in comparisons.items()):
        raise BreakoutDiffusionDataError(f"source audit mismatch: {audit}")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source)
        ORDER BY trade_date
        """
    )
    return audit


def _create_event_security(connection: duckdb.DuckDBPyConnection) -> None:
    # Keep these stage boundaries byte-semantically identical to the accepted
    # MKT-SUPPORT-DATA-003/MKT-BREAKOUT-DATA-001 coordinate builder. DuckDB's
    # fused CTE window plan changes the cumulative floating result by one ULP on
    # the first protected disagreement, 000020.SZ on 2019-08-29.
    connection.execute(
        """
        CREATE TEMP TABLE base AS
        SELECT s.trade_date,c.cal_idx,s.symbol,s.open,s.high,s.low,s.close,
               s.volume,s.amount,s.is_st,s.trade_status,s.current_day_data_tradable,
               s.preclose,s.limit_pct,s.up_limit_price,s.down_limit_price,
               s.corporate_action_count,s.corporate_action_available_date,
               s.corporate_action_blocking,s.share_multiplier,s.cash_per_share,
               s.rights_ratio,s.rights_price,s.hard_valid,s.bar_valid,
               s.trading_state_valid,s.corporate_action_valid,s.market_rule_valid,
               s.historical_identity_valid,s.available_at,s.decision_at,s.snapshot_id,
               (s.hard_valid IS TRUE AND s.bar_valid IS TRUE
                AND s.trading_state_valid IS TRUE AND s.corporate_action_valid IS TRUE
                AND s.market_rule_valid IS TRUE AND s.historical_identity_valid IS TRUE
                AND s.corporate_action_blocking IS FALSE
                AND s.available_at IS NOT NULL AND s.available_at<=s.decision_at
                AND s.open IS NOT NULL AND isfinite(s.open) AND s.open>0
                AND s.high IS NOT NULL AND isfinite(s.high)
                AND s.high>=greatest(s.open,s.close,s.low)
                AND s.low IS NOT NULL AND isfinite(s.low)
                AND s.low<=least(s.open,s.close,s.high)
                AND s.close IS NOT NULL AND isfinite(s.close) AND s.close>0) AS history_valid,
               (s.hard_valid IS TRUE AND s.trade_status=1
                AND s.current_day_data_tradable IS TRUE
                AND s.volume IS NOT NULL AND isfinite(s.volume) AND s.volume>0) AS current_valid
        FROM source s JOIN calendar c USING(trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE stepped AS
        SELECT *,lag(close) OVER w AS previous_close,
               lag(history_valid) OVER w AS previous_history_valid,
               lag(cal_idx) OVER w AS previous_cal_idx
        FROM base WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE chained AS
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
            THEN ln(close/((previous_close-coalesce(cash_per_share,0))
                     /coalesce(share_multiplier,1)))
            WHEN history_valid AND previous_history_valid AND cal_idx-previous_cal_idx=1
             AND coalesce(corporate_action_count,0)=0 THEN ln(close/previous_close)
            ELSE NULL END AS step_log_return
        FROM stepped
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE continuous AS
        SELECT *,exp(sum(CASE WHEN coordinate_step_valid THEN step_log_return ELSE 0.0 END)
          OVER (PARTITION BY symbol ORDER BY trade_date
                ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)) AS coordinate_close
        FROM chained
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE coordinate_window AS
        SELECT *,coordinate_close*high/close AS coordinate_high,
               count(*) OVER w41 AS history_rows41,
               min(cal_idx) OVER w41 AS min_cal_idx41,
               sum(history_valid::INTEGER) OVER w41 AS history_valid_rows41,
               sum(coordinate_step_valid::INTEGER) OVER w40steps AS valid_steps40,
               max(coordinate_close*high/close) OVER w10 AS resistance_high10,
               max(coordinate_close*high/close) OVER w20 AS resistance_high20,
               max(coordinate_close*high/close) OVER w40 AS resistance_high40
        FROM continuous
        WINDOW
          w41 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 40 PRECEDING AND CURRENT ROW),
          w40steps AS (PARTITION BY symbol ORDER BY trade_date
                       ROWS BETWEEN 39 PRECEDING AND CURRENT ROW),
          w10 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
          w20 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          w40 AS (PARTITION BY symbol ORDER BY trade_date
                  ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING)
        """
    )
    for table in ("base", "stepped", "chained", "continuous"):
        connection.execute(f"DROP TABLE {table}")
    connection.execute(
        """
        CREATE TEMP TABLE event_security AS
        SELECT c.trade_date,c.cal_idx,c.symbol,c.is_st,
               CASE WHEN s.industry_valid IS TRUE AND s.industry IS NOT NULL
                          AND trim(s.industry)<>'' AND s.source_notice_date IS NOT NULL
                          AND s.source_notice_date<=s.trade_date
                    THEN s.industry ELSE NULL END AS causal_industry,
               c.snapshot_id,c.close AS daily_raw_close,c.high AS daily_raw_high,
               c.coordinate_close,c.coordinate_high,c.resistance_high10,
               c.resistance_high20,c.resistance_high40,
               coordinate_high>resistance_high10 AS cross10,
               coordinate_high>resistance_high20 AS cross20,
               coordinate_high>resistance_high40 AS cross40,
               coordinate_high>resistance_high10 AND coordinate_close>resistance_high10 AS above10,
               coordinate_high>resistance_high20 AND coordinate_close>resistance_high20 AS above20,
               coordinate_high>resistance_high40 AND coordinate_close>resistance_high40 AS above40,
               coordinate_high>resistance_high10 AND coordinate_close=resistance_high10 AS equal10,
               coordinate_high>resistance_high20 AND coordinate_close=resistance_high20 AS equal20,
               coordinate_high>resistance_high40 AND coordinate_close=resistance_high40 AS equal40,
               coordinate_high>resistance_high10 AND coordinate_close<resistance_high10 AS below10,
               coordinate_high>resistance_high20 AND coordinate_close<resistance_high20 AS below20,
               coordinate_high>resistance_high40 AND coordinate_close<resistance_high40 AS below40,
               CASE WHEN coordinate_high>resistance_high10
                    THEN coordinate_high/resistance_high10-1 ELSE NULL END AS formation_depth10,
               CASE WHEN coordinate_high>resistance_high20
                    THEN coordinate_high/resistance_high20-1 ELSE NULL END AS formation_depth20,
               CASE WHEN coordinate_high>resistance_high40
                    THEN coordinate_high/resistance_high40-1 ELSE NULL END AS formation_depth40,
               CASE WHEN coordinate_high>resistance_high10
                    THEN greatest(resistance_high10/coordinate_close-1,0) ELSE NULL END
                    AS rejection_depth10,
               CASE WHEN coordinate_high>resistance_high20
                    THEN greatest(resistance_high20/coordinate_close-1,0) ELSE NULL END
                    AS rejection_depth20,
               CASE WHEN coordinate_high>resistance_high40
                    THEN greatest(resistance_high40/coordinate_close-1,0) ELSE NULL END
                    AS rejection_depth40
        FROM coordinate_window c JOIN source s USING(symbol,trade_date)
        WHERE c.current_valid AND c.history_valid AND c.history_rows41=41
          AND c.cal_idx-c.min_cal_idx41=40 AND c.history_valid_rows41=41
          AND c.valid_steps40=40
          AND c.resistance_high10 IS NOT NULL AND isfinite(c.resistance_high10)
          AND c.resistance_high10>0
          AND c.resistance_high20 IS NOT NULL AND isfinite(c.resistance_high20)
          AND c.resistance_high20>0
          AND c.resistance_high40 IS NOT NULL AND isfinite(c.resistance_high40)
          AND c.resistance_high40>0
          AND c.coordinate_close IS NOT NULL AND isfinite(c.coordinate_close)
          AND c.coordinate_close>0 AND c.coordinate_high IS NOT NULL
          AND isfinite(c.coordinate_high) AND c.coordinate_high>0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE scalar_candidates AS
        SELECT symbol,trade_date,cal_idx,daily_raw_close,daily_raw_high,
               coordinate_close,coordinate_high,resistance_high10,resistance_high20,
               resistance_high40,cross20,above20,equal20,below20,formation_depth20,
               rejection_depth20,
               sha256('MKT-BREAKOUT-DIFF-DATA-001|' || symbol || '|' ||
                      strftime(trade_date,'%Y-%m-%d')) AS selection_hash
        FROM event_security WHERE cross20
        ORDER BY selection_hash,symbol,trade_date LIMIT 5
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE scalar_coordinate_history AS
        SELECT k.symbol,k.trade_date AS target_date,k.cal_idx AS target_cal_idx,
               c.trade_date,c.cal_idx,c.high,c.close,c.coordinate_close,
               c.coordinate_high,c.history_valid,c.coordinate_step_valid
        FROM scalar_candidates k JOIN coordinate_window c ON c.symbol=k.symbol
          AND c.cal_idx BETWEEN k.cal_idx-40 AND k.cal_idx
        ORDER BY k.symbol,k.trade_date,c.cal_idx
        """
    )
    connection.execute("DROP TABLE coordinate_window")
    invalid = connection.execute(
        """
        SELECT count(*) FROM event_security
        WHERE NOT (isfinite(coordinate_close) AND coordinate_close>0
                   AND isfinite(coordinate_high) AND coordinate_high>0
                   AND cross10=(above10 OR equal10 OR below10)
                   AND cross20=(above20 OR equal20 OR below20)
                   AND cross40=(above40 OR equal40 OR below40))
        """
    ).fetchone()[0]
    if int(invalid) != 0:
        raise BreakoutDiffusionDataError("security event-state conservation failed")


def _expanded_view(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP VIEW governed AS
        SELECT 'ALL_A' AS market_view,* FROM event_security
          WHERE symbol LIKE '%.SH' OR symbol LIKE '%.SZ'
        UNION ALL SELECT 'SH_A',* FROM event_security WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM event_security WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM event_security
          WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
        """
    )
    connection.execute(
        """
        CREATE TEMP VIEW expanded AS
        SELECT g.*,'ALL_STATUS' AS denominator FROM governed g
        UNION ALL SELECT g.*,'NON_ST' FROM governed g WHERE is_st IS FALSE
        """
    )


def _daily_counts(connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for lookback in spec["coordinate"]["lookbacks"]:
        h = int(lookback)
        frame = connection.execute(
            f"""
            WITH overall AS (
              SELECT market_view,denominator,trade_date,
                     count(*) AS eligible_count,
                     count(causal_industry) AS industry_mapped_count,
                     sum(cross{h}::INTEGER) AS crossing_count,
                     sum(above{h}::INTEGER) AS close_above_count,
                     sum(equal{h}::INTEGER) AS close_equal_count,
                     sum(below{h}::INTEGER) AS close_below_count
              FROM expanded GROUP BY 1,2,3
            ), industries AS (
              SELECT market_view,denominator,trade_date,causal_industry,
                     count(*) AS industry_eligible_count,
                     sum(cross{h}::INTEGER) AS industry_crossing_count,
                     sum(above{h}::INTEGER) AS industry_accepted_count
              FROM expanded WHERE causal_industry IS NOT NULL
              GROUP BY 1,2,3,4 HAVING count(*)>=5
            ), industry_daily AS (
              SELECT market_view,denominator,trade_date,
                     count(*) AS included_industry_count,
                     sum(industry_eligible_count) AS included_eligible_count,
                     sum(industry_crossing_count) AS included_crossing_count,
                     sum(industry_accepted_count) AS included_accepted_count,
                     sum((industry_crossing_count>0)::INTEGER) AS event_industry_count,
                     sum((industry_accepted_count>0)::INTEGER) AS accepted_event_industry_count
              FROM industries GROUP BY 1,2,3
            )
            SELECT o.*,coalesce(i.included_industry_count,0) AS included_industry_count,
                   coalesce(i.included_eligible_count,0) AS included_eligible_count,
                   coalesce(i.included_crossing_count,0) AS included_crossing_count,
                   coalesce(i.included_accepted_count,0) AS included_accepted_count,
                   coalesce(i.event_industry_count,0) AS event_industry_count,
                   coalesce(i.accepted_event_industry_count,0) AS accepted_event_industry_count
            FROM overall o LEFT JOIN industry_daily i
              USING(market_view,denominator,trade_date)
            ORDER BY trade_date,denominator,market_view
            """
        ).df()
        frame["lookback"] = h
        frames.append(frame)
    output = pd.concat(frames, ignore_index=True)
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="raise")
    output["year"] = output["trade_date"].dt.year.astype(int)
    minimums = spec["population"]["minimum_counts"]
    output["view_valid"] = output["eligible_count"] >= output["market_view"].map(minimums)
    output["nonindustry_defined"] = output["view_valid"] & output["crossing_count"].gt(0)
    output["industry_mapping_coverage"] = output["industry_mapped_count"] / output["eligible_count"]
    pop = spec["population"]
    output["industry_valid"] = (
        output["view_valid"]
        & output["industry_mapping_coverage"].ge(pop["industry_mapping_minimum"])
        & output["included_industry_count"].ge(pop["industry_count_minimum"])
    )
    output["formation_domain"] = output["industry_valid"] & output["event_industry_count"].ge(
        pop["formation_event_industry_minimum"]
    )
    output["acceptance_domain"] = output["formation_domain"] & output[
        "accepted_event_industry_count"
    ].ge(pop["acceptance_event_industry_minimum"])
    expected_rows = int(pop["expected_date_view_denominator_cells"]) * len(frames)
    if len(output) != expected_rows:
        raise BreakoutDiffusionDataError(
            f"daily count cell conservation failed: {len(output)} != {expected_rows}"
        )
    if output["trade_date"].nunique() != pop["expected_post_warmup_dates"]:
        raise BreakoutDiffusionDataError("post-warmup date conservation failed")
    states = output["close_above_count"] + output["close_equal_count"] + output["close_below_count"]
    if not np.array_equal(states.to_numpy(), output["crossing_count"].to_numpy()):
        raise BreakoutDiffusionDataError("daily closing-state conservation failed")
    if (
        (output["included_eligible_count"] > output["eligible_count"]).any()
        or (output["included_crossing_count"] > output["crossing_count"]).any()
        or (output["included_accepted_count"] > output["close_above_count"]).any()
    ):
        raise BreakoutDiffusionDataError("industry mass conservation failed")
    return output.sort_values(["lookback", "trade_date", "denominator", "market_view"]).reset_index(
        drop=True
    )


def verify_view_and_denominator_nesting(daily: pd.DataFrame) -> dict[str, bool]:
    metrics = [
        "eligible_count",
        "crossing_count",
        "close_above_count",
        "close_equal_count",
        "close_below_count",
    ]
    exchange_partition = True
    board_subset = True
    denominator_subset = True
    for metric in metrics:
        for (_lookback, _denominator), group in daily.groupby(
            ["lookback", "denominator"], sort=False
        ):
            wide = group.pivot(index="trade_date", columns="market_view", values=metric)
            exchange_partition &= bool(
                np.array_equal(
                    wide["ALL_A"].to_numpy(),
                    (wide["SH_A"] + wide["SZ_A"]).to_numpy(),
                )
            )
            board_subset &= bool((wide["CHINEXT_BOARD"] <= wide["SZ_A"]).all())
        for (_lookback, _view), group in daily.groupby(["lookback", "market_view"], sort=False):
            wide = group.pivot(index="trade_date", columns="denominator", values=metric)
            denominator_subset &= bool((wide["NON_ST"] <= wide["ALL_STATUS"]).all())
    result = {
        "all_a_equals_sh_plus_sz": exchange_partition,
        "chinext_subset_sz": board_subset,
        "non_st_subset_all_status": denominator_subset,
    }
    if not all(result.values()):
        raise BreakoutDiffusionDataError(f"view/denominator nesting failed: {result}")
    return result


def _protected_coordinate_replication(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> dict[str, Any]:
    path = _resolve(spec["inputs"]["protected_breakout_coordinate_audit"]["path"])
    parent = pd.read_csv(path, float_precision="round_trip")
    parent["trade_date"] = pd.to_datetime(parent["trade_date"], errors="raise")
    parent = parent.drop_duplicates(["symbol", "trade_date"]).copy()
    expected = spec["protected_coordinate_replication"]["expected_unique_targets"]
    if len(parent) != expected:
        raise BreakoutDiffusionDataError("protected target population changed")
    connection.register("protected_targets", parent[["symbol", "trade_date"]])
    current = connection.execute(
        """
        SELECT e.symbol,e.trade_date,e.daily_raw_close,e.coordinate_close,
               e.coordinate_close/e.daily_raw_close AS coordinate_scale,
               e.resistance_high10,e.resistance_high20,e.resistance_high40,
               e.snapshot_id AS daily_snapshot_id
        FROM event_security e JOIN protected_targets p USING(symbol,trade_date)
        ORDER BY e.symbol,e.trade_date
        """
    ).df()
    if len(current) != expected:
        raise BreakoutDiffusionDataError("protected coordinate coverage changed")
    joined = current.merge(
        parent,
        on=["symbol", "trade_date"],
        suffixes=("_new", "_parent"),
        validate="one_to_one",
    )
    for field in spec["protected_coordinate_replication"]["exact_float_fields"]:
        left = joined[f"{field}_new"].to_numpy(dtype=float)
        right = joined[f"{field}_parent"].to_numpy(dtype=float)
        if not np.array_equal(left, right):
            index = int(np.flatnonzero(left != right)[0])
            row = joined.iloc[index]
            raise BreakoutDiffusionDataError(
                f"protected coordinate disagreement: {row.symbol}:{row.trade_date}:{field}:"
                f"{left[index]} != {right[index]}"
            )
    for field in spec["protected_coordinate_replication"]["exact_identity_fields"]:
        if not joined[f"{field}_new"].astype(str).equals(joined[f"{field}_parent"].astype(str)):
            raise BreakoutDiffusionDataError(f"protected identity disagreement: {field}")
    return {"targets": expected, "exact_fields": 7, "exact_match": True}


def _scalar_cases(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> list[dict[str, Any]]:
    candidates = connection.execute(
        "SELECT * FROM scalar_candidates ORDER BY selection_hash,symbol,trade_date"
    ).df()
    if len(candidates) != int(spec["scalar_reconstruction"]["cases"]):
        raise BreakoutDiffusionDataError("insufficient scalar reconstruction cases")
    scalar = connection.execute(
        "SELECT * FROM scalar_coordinate_history ORDER BY symbol,target_date,cal_idx"
    ).df()
    scalar["trade_date"] = pd.to_datetime(scalar["trade_date"], errors="raise")
    scalar["target_date"] = pd.to_datetime(scalar["target_date"], errors="raise")
    output: list[dict[str, Any]] = []
    for case in candidates.itertuples(index=False):
        expected_hash = hashlib.sha256(
            f"MKT-BREAKOUT-DIFF-DATA-001|{case.symbol}|{pd.Timestamp(case.trade_date).date()}".encode()
        ).hexdigest()
        if expected_hash != case.selection_hash:
            raise BreakoutDiffusionDataError("scalar selection hash disagreement")
        rows = scalar.loc[
            scalar["symbol"].eq(case.symbol)
            & scalar["target_date"].eq(pd.Timestamp(case.trade_date))
        ].copy()
        target = rows.loc[rows["cal_idx"].eq(int(case.cal_idx))]
        if len(target) != 1:
            raise BreakoutDiffusionDataError("scalar target coverage mismatch")
        target_row = target.iloc[0]
        prior = rows.loc[
            rows["cal_idx"].between(int(case.cal_idx) - 40, int(case.cal_idx) - 1)
        ].sort_values("cal_idx")
        if (
            len(prior) != 40
            or not prior["history_valid"].astype(bool).all()
            or not prior["coordinate_step_valid"].astype(bool).all()
        ):
            raise BreakoutDiffusionDataError("scalar prior-coordinate core invalid")
        highs = (
            prior["coordinate_close"].to_numpy(float)
            * prior["high"].to_numpy(float)
            / prior["close"].to_numpy(float)
        )
        levels = {h: float(np.max(highs[-h:])) for h in (10, 20, 40)}
        current_coordinate = float(target_row.coordinate_close)
        mapped_high = current_coordinate * float(target_row.high) / float(target_row.close)
        mapped_close = current_coordinate
        crossing = mapped_high > levels[20]
        state = (
            "CROSS_CLOSE_ABOVE"
            if mapped_close > levels[20]
            else "CROSS_CLOSE_BELOW"
            if mapped_close < levels[20]
            else "CROSS_CLOSE_EQUAL"
        )
        formation_depth = mapped_high / levels[20] - 1.0
        rejection_depth = max(levels[20] / mapped_close - 1.0, 0.0)
        exact_values = (
            levels[10] == float(case.resistance_high10),
            levels[20] == float(case.resistance_high20),
            levels[40] == float(case.resistance_high40),
            mapped_high == float(case.coordinate_high),
            mapped_close == float(case.coordinate_close),
            crossing == bool(case.cross20),
            formation_depth == float(case.formation_depth20),
            rejection_depth == float(case.rejection_depth20),
            state
            == (
                "CROSS_CLOSE_ABOVE"
                if bool(case.above20)
                else "CROSS_CLOSE_EQUAL"
                if bool(case.equal20)
                else "CROSS_CLOSE_BELOW"
            ),
        )
        if not all(exact_values):
            raise BreakoutDiffusionDataError(
                f"scalar reconstruction disagreement: {case.symbol}:{case.trade_date}:"
                f"{exact_values}"
            )
        output.append(
            {
                "selection_hash": expected_hash,
                "symbol": str(case.symbol),
                "trade_date": str(pd.Timestamp(case.trade_date).date()),
                "resistance_high10": levels[10],
                "resistance_high20": levels[20],
                "resistance_high40": levels[40],
                "mapped_current_high": mapped_high,
                "mapped_current_close": mapped_close,
                "closing_state": state,
                "exact_match": True,
            }
        )
    return output


def evaluate_count_gates(daily: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    gates = spec["count_gates"]
    coverage: dict[str, dict[str, Any]] = {}
    coverage_pass = True
    for (lookback, market_view, denominator), group in daily.groupby(
        ["lookback", "market_view", "denominator"], sort=True
    ):
        valid = group["view_valid"]
        valid_count = int(valid.sum())
        if valid_count == 0:
            raise BreakoutDiffusionDataError("zero valid cells in count-gate domain")
        item = {
            "valid_date_coverage": float(valid.mean()),
            "nonindustry_defined_coverage": float(group.loc[valid, "nonindustry_defined"].mean()),
            "industry_mapping_coverage": float(group.loc[valid, "industry_valid"].mean()),
            "formation_distribution_coverage": float(group.loc[valid, "formation_domain"].mean()),
            "acceptance_distribution_coverage": float(group.loc[valid, "acceptance_domain"].mean()),
        }
        item["pass"] = bool(
            item["valid_date_coverage"]
            >= gates["valid_date_coverage_each_horizon_view_denominator"]
            and item["nonindustry_defined_coverage"]
            >= gates["nonindustry_role_date_coverage_each_horizon_view_denominator"]
            and item["industry_mapping_coverage"]
            >= gates["industry_mapping_date_coverage_each_view_denominator"]
            and item["formation_distribution_coverage"]
            >= gates["formation_distribution_date_coverage_each_horizon_view_denominator"]
            and item["acceptance_distribution_coverage"]
            >= gates["acceptance_distribution_date_coverage_each_horizon_view_denominator"]
        )
        coverage_pass &= item["pass"]
        coverage[f"L{lookback}:{market_view}:{denominator}"] = item

    annual: dict[str, dict[str, Any]] = {}
    annual_pass = True
    primary = daily.loc[daily["lookback"].eq(spec["coordinate"]["primary_lookback"])]
    for (market_view, denominator, year), group in primary.groupby(
        ["market_view", "denominator", "year"], sort=True
    ):
        item = {
            "valid_cells": int(group["view_valid"].sum()),
            "crossings": int(group["crossing_count"].sum()),
            "close_above": int(group["close_above_count"].sum()),
            "close_below": int(group["close_below_count"].sum()),
            "defined_acceptance_industry_cells": int(group["acceptance_domain"].sum()),
        }
        item["pass"] = bool(
            item["valid_cells"] >= gates["view_year_minimum_valid_cells"]
            and item["crossings"] >= gates["l20_view_year_minimum_crossings"]
            and item["close_above"] >= gates["l20_view_year_minimum_close_above"]
            and item["close_below"] >= gates["l20_view_year_minimum_close_below"]
            and item["defined_acceptance_industry_cells"]
            >= gates["view_year_minimum_defined_industry_role_observations"]
        )
        annual_pass &= item["pass"]
        annual[f"{market_view}:{denominator}:{year}"] = item
    result = {
        "coverage": coverage,
        "annual_primary": annual,
        "coverage_pass": bool(coverage_pass),
        "annual_primary_pass": bool(annual_pass),
        "all_count_gates_pass": bool(coverage_pass and annual_pass),
    }
    return result


def _build_count_audit(daily: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for (lookback, market_view, denominator), group in daily.groupby(
        ["lookback", "market_view", "denominator"], sort=True
    ):
        for group_type, group_value, rows in [
            ("ALL_YEARS", "ALL", group),
            *[("YEAR", str(year), cell) for year, cell in group.groupby("year", sort=True)],
        ]:
            records.append(
                {
                    "lookback": int(lookback),
                    "market_view": str(market_view),
                    "denominator": str(denominator),
                    "group_type": group_type,
                    "group_value": group_value,
                    "date_cells": len(rows),
                    "valid_date_cells": int(rows["view_valid"].sum()),
                    "eligible_security_rows": int(rows["eligible_count"].sum()),
                    "crossing_security_events": int(rows["crossing_count"].sum()),
                    "close_above_events": int(rows["close_above_count"].sum()),
                    "close_equal_events": int(rows["close_equal_count"].sum()),
                    "close_below_events": int(rows["close_below_count"].sum()),
                    "nonindustry_defined_cells": int(rows["nonindustry_defined"].sum()),
                    "industry_valid_cells": int(rows["industry_valid"].sum()),
                    "formation_distribution_cells": int(rows["formation_domain"].sum()),
                    "acceptance_distribution_cells": int(rows["acceptance_domain"].sum()),
                    "minimum_eligible_count": int(rows["eligible_count"].min()),
                    "minimum_included_industries": int(rows["included_industry_count"].min()),
                    "minimum_event_industries": int(rows["event_industry_count"].min()),
                    "minimum_accepted_event_industries": int(
                        rows["accepted_event_industry_count"].min()
                    ),
                }
            )
    return (
        pd.DataFrame(records)
        .sort_values(["lookback", "market_view", "denominator", "group_type", "group_value"])
        .reset_index(drop=True)
    )


def _render_report(result: dict[str, Any]) -> str:
    primary = result["primary_support"]
    gates = result["gate_evaluation"]
    population = result["population"]
    protected = result["protected_coordinate_replication"]
    return (
        "\n".join(
            [
                "# MKT-BREAKOUT-DIFF-DATA-001 full-market domain audit",
                "",
                "## Result",
                "",
                f"- Status: `{result['status']}`",
                "- Eligible full-market security-dates: "
                f"{population['eligible_all_a_all_status']:,} across "
                f"{population['post_warmup_dates']:,} completed dates.",
                "- L20 ALL_A/ALL_STATUS crossing events above/equal/below: "
                f"{primary['crossings']:,}/{primary['close_above']:,}/"
                f"{primary['close_equal']:,}/{primary['close_below']:,}.",
                "- Count-domain coverage/annual gates: "
                f"{gates['coverage_pass']}/{gates['annual_primary_pass']}.",
                f"- Protected coordinate replication: {protected['targets']:,} targets, exact.",
                "- Five hash-selected daily events independently reproduce all prior-high, "
                "mapped-price, closing-state, and depth fields exactly.",
                "- This experiment computes no daily representation correlations, causal "
                "percentiles, relative ranks, transitions, outcomes, or strategy evidence.",
                "- QD-004, CY-008, post-2023 data, strategy fields, and CY-011 were not read.",
                "",
                "## Reproducibility",
                "",
                f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
                f"- Runner SHA-256: `{result['hashes']['runner_sha256']}`",
                f"- Count audit SHA-256: `{result['hashes']['count_audit_sha256']}`",
            ]
        )
        + "\n"
    )


def run() -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    paths, source_hashes = _verify_registry_and_partitions(spec)
    _preflight_resource_guard(spec, paths)
    temp_peak = 0
    with tempfile.TemporaryDirectory(prefix="mkt_breakout_diff_data_001_") as temporary:
        temp_dir = Path(temporary)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1.5GB'")
        connection.execute("SET temp_directory=?", [str(temp_dir / "spill")])
        try:
            input_audit = _create_source_and_audit(connection, paths, spec)
            _create_event_security(connection)
            temp_peak = max(temp_peak, _directory_bytes(temp_dir))
            _phase_resource_guard(spec, temp_dir, started)
            event_rows = int(
                connection.execute("SELECT count(*) FROM event_security").fetchone()[0]
            )
            _expanded_view(connection)
            daily = _daily_counts(connection, spec)
            nesting = verify_view_and_denominator_nesting(daily)
            protected = _protected_coordinate_replication(connection, spec)
            scalar_cases = _scalar_cases(connection, spec)
            temp_peak = max(temp_peak, _directory_bytes(temp_dir))
            _phase_resource_guard(spec, temp_dir, started)
        finally:
            connection.close()

    gate_evaluation = evaluate_count_gates(daily, spec)
    count_audit = _build_count_audit(daily)
    COUNT_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    count_audit.to_csv(COUNT_AUDIT_PATH, index=False, lineterminator="\n")

    primary = daily.loc[
        daily["lookback"].eq(spec["coordinate"]["primary_lookback"])
        & daily["market_view"].eq("ALL_A")
        & daily["denominator"].eq("ALL_STATUS")
    ]
    status = (
        "COMPLETE_FULL_MARKET_DOMAIN_PASS"
        if gate_evaluation["all_count_gates_pass"]
        else "COMPLETE_FULL_MARKET_DOMAIN_ADEQUACY_FAIL"
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": "COUNT_LINEAGE_AND_DOMAIN_FEASIBILITY_ONLY",
        "outcome_or_strategy_fields_read": [],
        "qd004_read": False,
        "cy008_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "input_audit": input_audit,
        "population": {
            "eligible_security_dates_all_symbols": event_rows,
            "eligible_all_a_all_status": int(primary["eligible_count"].sum()),
            "post_warmup_dates": int(daily["trade_date"].nunique()),
            "daily_cells_all_horizons": len(daily),
            "count_audit_rows": len(count_audit),
        },
        "primary_support": {
            "crossings": int(primary["crossing_count"].sum()),
            "close_above": int(primary["close_above_count"].sum()),
            "close_equal": int(primary["close_equal_count"].sum()),
            "close_below": int(primary["close_below_count"].sum()),
            "industry_valid_cells": int(primary["industry_valid"].sum()),
            "formation_distribution_cells": int(primary["formation_domain"].sum()),
            "acceptance_distribution_cells": int(primary["acceptance_domain"].sum()),
        },
        "gate_evaluation": gate_evaluation,
        "view_and_denominator_nesting": nesting,
        "protected_coordinate_replication": protected,
        "scalar_reconstruction": scalar_cases,
        "resource_contract": {
            "status": "PASS",
            "single_process": True,
            "duckdb_threads": 1,
            "memory_limit_gib": 1.5,
            "temporary_spill_ceiling_gib": 10,
            "peak_rss_ceiling_gib": 3,
            "headroom_floor_gib": 8,
            "wall_clock_ceiling_minutes": 10,
            "dynamic_measurements_serialized": False,
        },
        "next_if_pass": "FREEZE_SEPARATE_MKT_BREAKOUT_DIFF_001_REPRESENTATION_EXPERIMENT",
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "source_partitions": source_hashes,
            "count_audit_sha256": sha256_file(COUNT_AUDIT_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable_bytes = sum(
        path.stat().st_size for path in (COUNT_AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable_bytes > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise BreakoutDiffusionDataError("durable output ceiling breached")
    wall_ceiling = float(spec["resource_budget"]["wall_clock_ceiling_minutes"]) * 60
    if time.monotonic() - started > wall_ceiling:
        raise BreakoutDiffusionDataError("wall-clock ceiling breached after serialization")
    print(
        json.dumps(
            {
                "status": status,
                "peak_rss_bytes": _peak_rss_bytes(),
                "temporary_peak_bytes": temp_peak,
                "durable_output_bytes": durable_bytes,
                "elapsed_seconds": time.monotonic() - started,
                "count_audit_sha256": result["hashes"]["count_audit_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return result


if __name__ == "__main__":
    run()
