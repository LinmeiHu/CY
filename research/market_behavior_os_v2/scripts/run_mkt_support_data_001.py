#!/usr/bin/env python3
"""Audit objective prior-level/current-minute coordinate feasibility."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DATA-001_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-001_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-001_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-001_population_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "3d86cb04a1bfaecbcc43621115edf8a3838d7bd19e717e53c07e9360469e426a"

ADAPTER_PATH = PROGRAM / "scripts/vectorized_market_minute_adapter.py"
MODULE_SPEC = importlib.util.spec_from_file_location("vectorized_market_minute_adapter", ADAPTER_PATH)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load frozen minute adapter")
adapter = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(adapter)


class SupportDataError(RuntimeError):
    """Fail-closed MKT-SUPPORT-DATA-001 error."""


sha256_file = adapter.sha256_file


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


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_NEW_RAW_MINUTE_ACCESS":
        raise SupportDataError("spec is not frozen before raw-minute access")
    if spec["sample"]["expected_cohort_rows"] != 1230:
        raise SupportDataError("sample cohort size changed")
    if spec["support_candidates"] != {
        "primary_previous_sessions": 20,
        "fixed_feasibility_neighbors": [10, 40],
        "price": "minimum action-coordinate daily low through t-1",
        "available_at": "t-1 15:00 Asia/Shanghai",
    }:
        raise SupportDataError("support candidate definitions changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportDataError(f"input identity mismatch: {name}")
    return spec


def _inventory_entries(path: Path) -> tuple[Path, dict[str, dict[str, Any]]]:
    inventory = json.loads(path.read_text(encoding="utf-8"))
    return Path(inventory["root"]), {item["path"]: item for item in inventory["files"]}


def _inventory_paths(
    inventory_path: Path,
    required: Iterable[str],
    verify_content: bool,
) -> dict[str, Path]:
    required_list = list(required)
    try:
        paths = adapter.inventory_files(inventory_path, required_list)
        if verify_content:
            adapter.verify_inventory_hashes(inventory_path, required_list)
        return paths
    except adapter.VectorMinuteAdapterError as exc:
        raise SupportDataError(str(exc)) from exc


def bind_partitions(
    spec: dict[str, Any], verify_content: bool = True
) -> dict[str, dict[str, Path]]:
    qd004_inventory = _resolve(spec["inputs"]["qd004_inventory"]["path"])
    cy006_inventory = _resolve(spec["inputs"]["cy006_inventory"]["path"])
    cy008_inventory = _resolve(spec["inputs"]["cy008_inventory"]["path"])
    output = {
        "qd004": _inventory_paths(
            qd004_inventory, spec["required_partitions"]["qd004"], verify_content
        ),
        "cy006": _inventory_paths(
            cy006_inventory, spec["required_partitions"]["cy006"], verify_content
        ),
        "cy008_daily": _inventory_paths(
            cy008_inventory,
            spec["required_partitions"]["cy008_daily"],
            verify_content,
        ),
    }
    qd010_inventory = _resolve(spec["inputs"]["qd010_inventory"]["path"])
    _, qd010_entries = _inventory_entries(qd010_inventory)
    _inventory_paths(qd010_inventory, qd010_entries, verify_content)
    return output


def _verify_registry_assets(spec: dict[str, Any]) -> None:
    registry = json.loads(
        _resolve(spec["inputs"]["registry"]["path"]).read_text(encoding="utf-8")
    )
    indexed = {item["asset_id"]: item for item in registry["assets"]}
    expected = {
        "QD-004": "767298a88618f30d4cc6d5db8a7f609670f88ba32987de6a32994844ad75746c",
        "CY-006": "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
        "CY-008": "5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f",
        "QD-010": "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
    }
    for asset, manifest_hash in expected.items():
        item = indexed.get(asset)
        if item is None or item["lineage"]["manifest_sha256"] != manifest_hash:
            raise SupportDataError(f"registry asset identity mismatch: {asset}")
        if item["status"] != "RESEARCH_CONDITIONAL" or item["pit_grade"] != "B":
            raise SupportDataError(f"registry activation boundary changed: {asset}")


def _create_daily_coordinate(
    spec: dict[str, Any], cy006_paths: dict[str, Path]
) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.from_parquet(
        [str(path) for path in cy006_paths.values()], union_by_name=True
    ).create_view("source")
    connection.execute(
        """
        CREATE TEMP TABLE calendar AS
        SELECT trade_date,row_number() OVER (ORDER BY trade_date)-1 AS cal_idx
        FROM (SELECT DISTINCT trade_date FROM source)
        ORDER BY trade_date
        """
    )
    calendar_rows = connection.execute("SELECT count(*) FROM calendar").fetchone()[0]
    if int(calendar_rows) != spec["date_range"]["exchange_sessions"]:
        raise SupportDataError("calendar session count mismatch")
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
                AND s.high IS NOT NULL AND isfinite(s.high) AND s.high>=greatest(s.open,s.close,s.low)
                AND s.low IS NOT NULL AND isfinite(s.low) AND s.low<=least(s.open,s.close,s.high)
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
            THEN ln(close/((previous_close-coalesce(cash_per_share,0))/coalesce(share_multiplier,1)))
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
          OVER (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW))
          AS coordinate_close
        FROM chained
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE support_window AS
        SELECT *,coordinate_close*low/close AS coordinate_low,
          count(*) OVER w41 AS history_rows41,
          min(cal_idx) OVER w41 AS min_cal_idx41,
          sum(history_valid::INTEGER) OVER w41 AS history_valid_rows41,
          sum(coordinate_step_valid::INTEGER) OVER w40steps AS valid_steps40,
          min(coordinate_close*low/close) OVER w10 AS support_low10,
          min(coordinate_close*low/close) OVER w20 AS support_low20,
          min(coordinate_close*low/close) OVER w40 AS support_low40
        FROM continuous
        WINDOW
          w41 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND CURRENT ROW),
          w40steps AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 39 PRECEDING AND CURRENT ROW),
          w10 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),
          w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          w40 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 40 PRECEDING AND 1 PRECEDING)
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE coordinate AS
        SELECT *,
          (current_valid AND history_valid AND history_rows41=41
           AND cal_idx-min_cal_idx41=40 AND history_valid_rows41=41
           AND valid_steps40=40
           AND support_low10 IS NOT NULL AND isfinite(support_low10) AND support_low10>0
           AND support_low20 IS NOT NULL AND isfinite(support_low20) AND support_low20>0
           AND support_low40 IS NOT NULL AND isfinite(support_low40) AND support_low40>0
           AND coordinate_close IS NOT NULL AND isfinite(coordinate_close) AND coordinate_close>0)
          AS coordinate_eligible
        FROM support_window
        """
    )
    return connection


def build_population_audit(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> pd.DataFrame:
    connection.execute(
        """
        CREATE TEMP TABLE eligible_views AS
        SELECT 'ALL_A' AS market_view,trade_date,symbol,is_st FROM coordinate
          WHERE coordinate_eligible AND (symbol LIKE '%.SH' OR symbol LIKE '%.SZ')
        UNION ALL SELECT 'SH_A',trade_date,symbol,is_st FROM coordinate
          WHERE coordinate_eligible AND symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',trade_date,symbol,is_st FROM coordinate
          WHERE coordinate_eligible AND symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',trade_date,symbol,is_st FROM coordinate
          WHERE coordinate_eligible AND symbol LIKE '%.SZ'
            AND (left(symbol,3)='300' OR left(symbol,3)='301')
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE population_counts AS
        SELECT trade_date,market_view,'ALL_STATUS' AS denominator,count(*) AS eligible_count
        FROM eligible_views GROUP BY 1,2
        UNION ALL
        SELECT trade_date,market_view,'NON_ST',count(*)
        FROM eligible_views WHERE is_st IS FALSE GROUP BY 1,2
        """
    )
    frame = connection.execute(
        """
        WITH dates AS (SELECT trade_date FROM calendar WHERE cal_idx>=40),
        views(market_view) AS (VALUES ('ALL_A'),('SH_A'),('SZ_A'),('CHINEXT_BOARD')),
        denoms(denominator) AS (VALUES ('ALL_STATUS'),('NON_ST'))
        SELECT d.trade_date,v.market_view,n.denominator,coalesce(p.eligible_count,0) AS eligible_count
        FROM dates d CROSS JOIN views v CROSS JOIN denoms n
        LEFT JOIN population_counts p USING(trade_date,market_view,denominator)
        ORDER BY d.trade_date,v.market_view,n.denominator
        """
    ).df()
    minimums = spec["full_daily_population_minimums"]
    frame["minimum_required"] = frame["market_view"].map(minimums).astype(int)
    frame["gate_pass"] = frame["eligible_count"] >= frame["minimum_required"]
    if not frame["gate_pass"].all():
        first = frame.loc[~frame["gate_pass"]].iloc[0]
        raise SupportDataError(
            "population floor failed: "
            f"{first.trade_date}:{first.market_view}:{first.denominator}:"
            f"{first.eligible_count}<{first.minimum_required}"
        )
    return frame


def _hash_order(year: int, symbol: str, trade_date: pd.Timestamp) -> str:
    payload = (
        f"MKT-SUPPORT-DATA-001|{year}|{symbol}|{trade_date.strftime('%Y-%m-%d')}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_sample(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> pd.DataFrame:
    accepted = pd.read_csv(
        _resolve(spec["inputs"]["accepted_minute_sample"]["path"]),
        dtype={"source_symbol": str},
    )
    if len(accepted) != spec["sample"]["accepted_market_sessions"]:
        raise SupportDataError("accepted sample population changed")
    accepted["trade_date"] = pd.to_datetime(accepted["trade_date"], errors="raise")
    accepted_rows = pd.DataFrame(
        {
            "audit_id": "ACCEPTED|" + accepted["trade_id"].astype(str) + "|" + accepted["relative_day"].astype(str),
            "cohort": "ACCEPTED_MARKET_MINUTE_SAMPLE",
            "market_view": accepted["market_view"],
            "symbol": accepted["symbol"],
            "source_symbol": accepted["source_symbol"].str.zfill(6),
            "trade_date": accepted["trade_date"],
            "target_year": accepted["target_year"].astype(int),
            "action_selection_rank": pd.Series([pd.NA] * len(accepted), dtype="Int64"),
        }
    )
    candidates = connection.execute(
        """
        SELECT trade_date,symbol,extract(year FROM trade_date)::INTEGER AS target_year
        FROM coordinate
        WHERE coordinate_eligible AND corporate_action_count>0
          AND corporate_action_available_date IS NOT NULL
          AND corporate_action_available_date<=trade_date
          AND corporate_action_blocking IS FALSE
          AND coalesce(rights_ratio,0)=0 AND coalesce(share_multiplier,1)>0
          AND month(trade_date)>=3
        ORDER BY trade_date,symbol
        """
    ).df()
    action_rows: list[dict[str, Any]] = []
    per_year = int(spec["sample"]["supported_action_sessions_per_year"])
    for year in spec["date_range"]["years"]:
        cell = candidates.loc[candidates["target_year"] == year].copy()
        cell["selection_hash"] = [
            _hash_order(year, str(row.symbol), pd.Timestamp(row.trade_date))
            for row in cell.itertuples(index=False)
        ]
        cell = cell.sort_values(["selection_hash", "symbol", "trade_date"])
        if len(cell) < per_year:
            raise SupportDataError(f"insufficient supported actions: {year}:{len(cell)}")
        for rank, row in enumerate(cell.head(per_year).itertuples(index=False), start=1):
            symbol = str(row.symbol)
            action_rows.append(
                {
                    "audit_id": f"ACTION|{year}|{rank:02d}|{symbol}|{pd.Timestamp(row.trade_date).date()}",
                    "cohort": "SUPPORTED_ACTION_AUDIT",
                    "market_view": "ACTION_AUDIT",
                    "symbol": symbol,
                    "source_symbol": symbol[:6],
                    "trade_date": pd.Timestamp(row.trade_date),
                    "target_year": year,
                    "action_selection_rank": rank,
                }
            )
    action = pd.DataFrame(action_rows)
    sample = pd.concat([accepted_rows, action], ignore_index=True)
    sample["action_selection_rank"] = sample["action_selection_rank"].astype("Int64")
    if len(sample) != spec["sample"]["expected_cohort_rows"]:
        raise SupportDataError("combined sample cohort count mismatch")
    if sample["audit_id"].duplicated().any():
        raise SupportDataError("duplicate audit cohort identity")
    counts = action.groupby("target_year").size()
    if len(counts) != 6 or not (counts == per_year).all():
        raise SupportDataError("action cohort year count mismatch")
    return sample.sort_values(["target_year", "cohort", "audit_id"]).reset_index(drop=True)


def fetch_target_coordinates(
    connection: duckdb.DuckDBPyConnection, sample: pd.DataFrame
) -> pd.DataFrame:
    keys = sample[["symbol", "trade_date"]].drop_duplicates().copy()
    connection.register("target_keys", keys)
    coordinates = connection.execute(
        """
        SELECT c.trade_date,c.symbol,c.coordinate_eligible,c.close AS daily_raw_close,
               c.coordinate_close,c.support_low10,c.support_low20,c.support_low40,
               c.up_limit_price,c.down_limit_price,c.corporate_action_count,
               c.corporate_action_available_date,c.corporate_action_blocking,
               c.share_multiplier,c.cash_per_share,c.rights_ratio,c.snapshot_id,
               c.available_at,c.decision_at
        FROM target_keys t LEFT JOIN coordinate c USING(symbol,trade_date)
        ORDER BY c.trade_date,c.symbol
        """
    ).df()
    if len(coordinates) != len(keys) or coordinates[["trade_date", "symbol"]].isna().any().any():
        raise SupportDataError("target daily coordinate coverage mismatch")
    if not coordinates["coordinate_eligible"].astype(bool).all():
        first = coordinates.loc[~coordinates["coordinate_eligible"].astype(bool)].iloc[0]
        raise SupportDataError(
            f"target coordinate ineligible: {first.symbol}:{first.trade_date}"
        )
    for field in ["daily_raw_close", "coordinate_close", "support_low10", "support_low20", "support_low40"]:
        values = pd.to_numeric(coordinates[field], errors="coerce")
        if not (np.isfinite(values) & (values > 0)).all():
            raise SupportDataError(f"target coordinate field invalid: {field}")
    return coordinates


def _read_cy008_daily(
    path: Path, targets: pd.DataFrame
) -> pd.DataFrame:
    symbols = sorted(targets["symbol"].unique())
    dates = sorted(pd.to_datetime(targets["trade_date"]).dt.date.unique())
    columns = [
        "symbol", "trade_date", "available_at", "minute_count", "distinct_minute_count",
        "source_resolution_minutes", "session_complete", "ohlc_valid", "unit_valid",
        "volume_reconciled", "amount_reconciled", "daily_hard_valid", "hard_valid",
        "daily_snapshot_id",
    ]
    frame = pq.read_table(
        path,
        columns=columns,
        filters=[("symbol", "in", symbols), ("trade_date", "in", dates)],
        use_threads=False,
    ).to_pandas()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="raise")
    frame = frame.merge(
        targets[["symbol", "trade_date"]].drop_duplicates(),
        on=["symbol", "trade_date"],
        validate="one_to_one",
    )
    return frame


def audit_minute_coordinates(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
) -> pd.DataFrame:
    unique_targets = sample[["symbol", "source_symbol", "trade_date", "target_year"]].drop_duplicates()
    coordinate_index = coordinates.set_index(["symbol", "trade_date"])
    session_records: list[dict[str, Any]] = []
    for year, targets in unique_targets.groupby("target_year", sort=True):
        qd_path = partitions["qd004"][f"bars/{year}_day_parquet_none.parquet"]
        try:
            raw_table = adapter.read_raw_table(
                qd_path,
                pd.to_datetime(targets["trade_date"]).dt.date,
                targets["source_symbol"].astype(str),
            )
            adapter.vectorized_session_descriptors(raw_table)
        except adapter.VectorMinuteAdapterError as exc:
            raise SupportDataError(str(exc)) from exc
        raw = raw_table.to_pandas()
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        target_count = targets[["symbol", "trade_date"]].drop_duplicates().shape[0]
        if raw.groupby(["symbol", "trade_date"]).ngroups != target_count:
            raise SupportDataError(f"raw target session coverage mismatch: {year}")
        cy8 = _read_cy008_daily(
            partitions["cy008_daily"][f"daily/partition_year={year}/data_0.parquet"],
            targets,
        )
        if len(cy8) != target_count:
            raise SupportDataError(f"CY-008 target coverage mismatch: {year}")
        for item in cy8.itertuples(index=False):
            key = (str(item.symbol), pd.Timestamp(item.trade_date))
            daily = coordinate_index.loc[key]
            expected_available = pd.Timestamp(item.trade_date) + pd.Timedelta(hours=15, minutes=30)
            checks = (
                pd.Timestamp(item.available_at) == expected_available,
                int(item.minute_count) == 241,
                int(item.distinct_minute_count) == 241,
                int(item.source_resolution_minutes) == 1,
                bool(item.session_complete),
                bool(item.ohlc_valid),
                bool(item.unit_valid),
                bool(item.volume_reconciled),
                bool(item.amount_reconciled),
                bool(item.daily_hard_valid),
                bool(item.hard_valid),
                str(item.daily_snapshot_id) == str(daily.snapshot_id),
            )
            if not all(checks):
                raise SupportDataError(f"CY-008 hard-valid/lineage gate failed: {key}")
        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise SupportDataError(f"minute row count mismatch: {symbol}:{trade_date}")
            daily = coordinate_index.loc[(symbol, pd.Timestamp(trade_date))]
            minute_close = float(rows["close"].iloc[-1])
            daily_close = float(daily.daily_raw_close)
            if minute_close != daily_close:
                raise SupportDataError(
                    f"daily/minute close mismatch: {symbol}:{trade_date}:{minute_close}!={daily_close}"
                )
            scale = float(daily.coordinate_close) / daily_close
            transformed = rows[["open", "high", "low", "close"]].to_numpy(dtype=float) * scale
            if not np.isfinite(transformed).all() or not (transformed > 0).all():
                raise SupportDataError(f"transformed minute coordinate invalid: {symbol}:{trade_date}")
            transformed_close = float(transformed[-1, 3])
            if transformed_close != float(daily.coordinate_close):
                raise SupportDataError(
                    f"transformed close identity failed: {symbol}:{trade_date}"
                )
            support20 = float(daily.support_low20)
            closes = transformed[:, 3]
            lows = transformed[:, 2]
            minute_below = closes < support20
            minimum_position = int(np.argmin(lows))
            recovery_close = float(closes[-1] - lows[minimum_position]) / support20
            session_records.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp(trade_date),
                    "daily_raw_close": daily_close,
                    "minute_raw_close": minute_close,
                    "coordinate_scale": scale,
                    "coordinate_close": float(daily.coordinate_close),
                    "transformed_minute_close": transformed_close,
                    "support_low10": float(daily.support_low10),
                    "support_low20": support20,
                    "support_low40": float(daily.support_low40),
                    "primary_level_tested": bool(np.min(lows) <= support20),
                    "primary_penetration_depth": max(0.0, (support20 - float(np.min(lows))) / support20),
                    "primary_close_below_fraction": float(np.mean(minute_below)),
                    "primary_minimum_bar_index": minimum_position,
                    "primary_close_recovery_from_minimum": recovery_close,
                    "up_limit_contact": bool(np.max(rows["high"].to_numpy(float)) >= float(daily.up_limit_price)),
                    "down_limit_contact": bool(np.min(rows["low"].to_numpy(float)) <= float(daily.down_limit_price)),
                    "corporate_action_count": int(daily.corporate_action_count or 0),
                    "rights_ratio": float(daily.rights_ratio or 0.0),
                    "corporate_action_blocking": bool(daily.corporate_action_blocking),
                    "daily_snapshot_id": str(daily.snapshot_id),
                    "descriptor_available_at": f"{pd.Timestamp(trade_date).date()}T15:30:00+08:00",
                }
            )
    session_audit = pd.DataFrame(session_records)
    if len(session_audit) != unique_targets[["symbol", "trade_date"]].drop_duplicates().shape[0]:
        raise SupportDataError("unique coordinate audit population mismatch")
    output = sample.merge(session_audit, on=["symbol", "trade_date"], validate="many_to_one")
    if len(output) != spec["sample"]["expected_cohort_rows"]:
        raise SupportDataError("cohort coordinate audit population mismatch")
    action = output["cohort"].eq("SUPPORTED_ACTION_AUDIT")
    if not (
        output.loc[action, "corporate_action_count"].gt(0).all()
        and output.loc[action, "rights_ratio"].eq(0).all()
        and ~output.loc[action, "corporate_action_blocking"].all()
    ):
        raise SupportDataError("action cohort semantic gate failed")
    return output.sort_values("audit_id").reset_index(drop=True)


def _render_report(result: dict[str, Any]) -> str:
    audit = result["coordinate_audit"]
    lines = [
        "# MKT-SUPPORT-DATA-001 objective support coordinate audit",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Cohort rows: {audit['cohort_rows']:,}; unique security-sessions: {audit['unique_sessions']:,}.",
        f"- Supported action cohort rows: {audit['supported_action_rows']}.",
        f"- Primary 20-session prior-low tests observed: {audit['primary_level_tests']} (feasibility diagnostic only).",
        f"- Full daily population cells passing: {result['population_audit']['passing_cells']}/{result['population_audit']['cells']}.",
        "- Descriptor availability is completed session 15:30; no intraday or same-session action is permitted.",
        "- This is coordinate feasibility, not evidence of support, defense, recovery, accumulation, prediction, or a strategy.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Sample SHA-256: `{result['hashes']['sample_sha256']}`",
        f"- Coordinate audit SHA-256: `{result['hashes']['coordinate_audit_sha256']}`",
        f"- Population audit SHA-256: `{result['hashes']['population_audit_sha256']}`",
    ]
    return "\n".join(lines) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    _verify_registry_assets(spec)
    partitions = bind_partitions(spec, verify_content=verify_partition_content)
    connection = _create_daily_coordinate(spec, partitions["cy006"])
    try:
        population = build_population_audit(connection, spec)
        sample = build_sample(connection, spec)
        coordinates = fetch_target_coordinates(connection, sample)
        coordinate_audit = audit_minute_coordinates(
            spec, sample, coordinates, partitions
        )
    finally:
        connection.close()
    sample_out = sample.copy()
    sample_out["trade_date"] = sample_out["trade_date"].dt.strftime("%Y-%m-%d")
    sample_out.to_csv(SAMPLE_PATH, index=False, lineterminator="\n")
    coordinate_out = coordinate_audit.copy()
    coordinate_out["trade_date"] = coordinate_out["trade_date"].dt.strftime("%Y-%m-%d")
    coordinate_out.to_csv(
        COORDINATE_AUDIT_PATH, index=False, float_format="%.12g", lineterminator="\n"
    )
    population_out = population.copy()
    population_out["trade_date"] = pd.to_datetime(population_out["trade_date"]).dt.strftime("%Y-%m-%d")
    population_out.to_csv(POPULATION_AUDIT_PATH, index=False, lineterminator="\n")
    action = coordinate_audit["cohort"].eq("SUPPORTED_ACTION_AUDIT")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_DATA_CONTRACT_PASS",
        "representation_claim": "NONE",
        "support_defense_claim": "NONE",
        "recovery_claim": "NONE",
        "accumulation_claim": "NONE",
        "usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "future_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "coordinate_audit": {
            "cohort_rows": int(len(coordinate_audit)),
            "unique_sessions": int(
                coordinate_audit[["symbol", "trade_date"]].drop_duplicates().shape[0]
            ),
            "supported_action_rows": int(action.sum()),
            "supported_action_rows_by_year": {
                str(year): int(count)
                for year, count in coordinate_audit.loc[action].groupby("target_year").size().items()
            },
            "daily_minute_close_mismatches": 0,
            "transformed_close_identity_failures": 0,
            "rights_or_blocking_action_rows": 0,
            "primary_level_tests": int(coordinate_audit["primary_level_tested"].sum()),
            "up_limit_contact_rows": int(coordinate_audit["up_limit_contact"].sum()),
            "down_limit_contact_rows": int(coordinate_audit["down_limit_contact"].sum()),
        },
        "population_audit": {
            "cells": int(len(population)),
            "passing_cells": int(population["gate_pass"].sum()),
            "first_date": str(pd.Timestamp(population["trade_date"].min()).date()),
            "last_date": str(pd.Timestamp(population["trade_date"].max()).date()),
            "minimum_margin": int(
                (population["eligible_count"] - population["minimum_required"]).min()
            ),
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "sample_sha256": sha256_file(SAMPLE_PATH),
            "coordinate_audit_sha256": sha256_file(COORDINATE_AUDIT_PATH),
            "population_audit_sha256": sha256_file(POPULATION_AUDIT_PATH),
            "bound_inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
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
    print(
        json.dumps(
            {
                "status": completed["status"],
                "coordinate_audit": completed["coordinate_audit"],
                "population_audit": completed["population_audit"],
            },
            indent=2,
            sort_keys=True,
        )
    )
