#!/usr/bin/env python3
"""Explore exact-crosser event-day and recent five-session minute structure."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import resource
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import psutil
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-MINX-001_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-MINX-001_sample_audit.csv"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-MINX-001_date_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-MINX-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-MINX-001_cross_scale.md"
EXPECTED_SPEC_SHA256 = "b808e43e7f34eb3112a4e801a3a277130af820e9494cf06563bcf964fbaa2b94"

CONTROL_COLUMNS = [
    "action_coordinate_close_return",
    "intraday_log_range",
    "close_location",
    "turnover_fraction",
    "log_traded_value",
]
EVENT_DESCRIPTOR_MAP = {
    "event_high_time": "high_time_fraction",
    "event_final30_return": "final30_log_return",
    "event_late_vwap_acceptance": "late_vwap_acceptance_fraction",
    "event_time_above_vwap": "time_above_vwap_fraction",
    "event_directional_efficiency": "signed_directional_efficiency",
    "event_vwap_crossing": "vwap_crossing_fraction",
    "event_new_high_fraction": "new_intraday_high_fraction",
    "event_volume_concentration": "minute_volume_concentration",
    "event_closing_volume": "closing30_volume_share",
}
TRAJECTORY_BASES = [
    "time_above_vwap_fraction",
    "late_vwap_acceptance_fraction",
    "down_minute_volume_share",
    "minute_realized_volatility",
]
RAW_DESCRIPTOR_COLUMNS = sorted(
    {
        *EVENT_DESCRIPTOR_MAP.values(),
        *TRAJECTORY_BASES,
        "up_minute_volume_share",
        "down_minute_volume_share",
    }
)


class MinuteCrossScaleError(RuntimeError):
    """Fail-closed sampled minute cross-scale error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _import(path: Path, name: str) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise MinuteCrossScaleError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise MinuteCrossScaleError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["research_level"] != "EXPLORE"
        or spec["status"] != "FROZEN_BEFORE_SAMPLED_MINUTE_VALUE_ACCESS"
        or spec["outcome_access"] is not False
    ):
        raise MinuteCrossScaleError("exploration activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MinuteCrossScaleError(f"input identity mismatch: {name}")
    specificity = json.loads(
        _resolve(spec["inputs"]["accepted_specificity_result"]["path"]).read_text()
    )
    minute = json.loads(
        _resolve(spec["inputs"]["accepted_minute_result"]["path"]).read_text()
    )
    if (
        specificity["classification"]
        != spec["activation"]["required_specificity_classification"]
        or minute["decision"] != spec["activation"]["required_minute_decision"]
    ):
        raise MinuteCrossScaleError("accepted scientific activation changed")
    if list(spec["fixed_same_day_controls"]) != CONTROL_COLUMNS:
        raise MinuteCrossScaleError("fixed control identity changed")
    if spec["fixed_event_day_roles"] != {
        **EVENT_DESCRIPTOR_MAP,
        "event_volume_asymmetry": (
            "up_minute_volume_share minus down_minute_volume_share"
        ),
    }:
        raise MinuteCrossScaleError("fixed event-day role identity changed")
    if list(spec["fixed_trajectory_bases"]) != TRAJECTORY_BASES:
        raise MinuteCrossScaleError("fixed trajectory identity changed")
    forbidden = "|".join(spec["prohibited_computations"])
    for token in ("future response", "strategy membership", "post-2023", "CY-011"):
        if token not in forbidden:
            raise MinuteCrossScaleError(f"prohibited boundary missing: {token}")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if sys.platform == "darwin" else value * 1024


def _guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    gc.collect()
    pa.default_memory_pool().release_unused()
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise MinuteCrossScaleError("process peak RSS ceiling breached")
    available = psutil.virtual_memory().available
    floor = int(budget["system_memory_headroom_floor_gib"] * 2**30)
    if available < floor:
        current_rss = psutil.Process().memory_info().rss
        raise MinuteCrossScaleError(
            "system memory headroom below frozen floor: "
            f"available={available}, current_rss={current_rss}, "
            f"peak_rss={_peak_rss_bytes()}"
        )
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise MinuteCrossScaleError("wall-clock ceiling breached")


def _sample_query(spec: dict[str, Any]) -> str:
    views = ",".join(f"'{item}'" for item in spec["activation"]["market_views"])
    denominator = spec["activation"]["denominator"]
    maximum = spec["activation"]["maximum_hash_sample_each_date_view"]
    seed = spec["activation"]["selection_seed"]
    return f"""
        WITH candidates AS (
          SELECT a.trade_date AS event_date,a.market_view,a.denominator,a.symbol,
                 a.anchor_crossing_count,a.own_depth,e.cal_idx,
                 sha256('{seed}' || '|' || strftime(a.trade_date,'%Y-%m-%d') ||
                        '|' || a.market_view || '|' || a.symbol) AS selection_hash
          FROM anchor_strata a
          JOIN event_security e USING(symbol,trade_date)
          WHERE a.market_view IN ({views}) AND a.denominator='{denominator}'
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY event_date,market_view
            ORDER BY selection_hash,symbol) AS selection_rank
          FROM candidates
        )
        SELECT r.*,
               CASE WHEN e.coordinate_close>0 AND p.coordinate_close>0
                          AND isfinite(e.coordinate_close)
                          AND isfinite(p.coordinate_close)
                          AND s.high>s.low AND s.low>0
                          AND isfinite(s.high) AND isfinite(s.low)
                          AND s.close>=s.low AND s.close<=s.high
                          AND s.turnover_fraction>0
                          AND isfinite(s.turnover_fraction)
                          AND s.amount>0 AND isfinite(s.amount)
                    THEN ln(e.coordinate_close/p.coordinate_close) END
                 AS action_coordinate_close_return,
               CASE WHEN s.high>s.low AND s.low>0
                    THEN ln(s.high/s.low) END AS intraday_log_range,
               CASE WHEN s.high>s.low
                    THEN (s.close-s.low)/(s.high-s.low) END AS close_location,
               CASE WHEN s.turnover_fraction>0 AND isfinite(s.turnover_fraction)
                    THEN s.turnover_fraction END AS turnover_fraction,
               CASE WHEN s.amount>0 AND isfinite(s.amount)
                    THEN ln(s.amount) END AS log_traded_value
        FROM ranked r
        LEFT JOIN event_security e
          ON e.symbol=r.symbol AND e.trade_date=r.event_date
        LEFT JOIN event_security p
          ON p.symbol=e.symbol AND p.cal_idx=e.cal_idx-1
        LEFT JOIN source s
          ON s.symbol=r.symbol AND s.trade_date=r.event_date
        WHERE r.selection_rank<={maximum}
        ORDER BY r.event_date,r.market_view,r.selection_rank,r.symbol
    """


def _build_sample(
    spec: dict[str, Any], started: float
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    data_runner = _import(
        _resolve(spec["inputs"]["accepted_own_data_runner"]["path"]),
        "minx_accepted_own_data_runner",
    )
    data_spec = data_runner._load_spec()
    path_runner = data_runner._import(
        data_runner._resolve(data_spec["inputs"]["inherited_path_data_runner"]["path"]),
        "minx_path_runner",
    )
    path_spec = path_runner._load_spec()
    base = path_runner._import(
        data_runner._resolve(path_spec["inputs"]["inherited_data_runner"]["path"]),
        "minx_base_data",
    )
    inherited = base._load_spec()
    economic_data = base._import(base.ECON_DATA_RUNNER, "minx_economic_data")
    coordinate = economic_data._load_coordinate_module(inherited)
    source_paths, source_hashes = economic_data._verify_partitions(inherited, coordinate)
    base._preflight(inherited, source_paths)
    sample_frames: list[pd.DataFrame] = []
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-minx-") as temp_raw:
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped = str(Path(temp_raw)).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped}'")
        try:
            source_audit = coordinate._create_source_and_audit(
                connection, source_paths, inherited
            )
            coordinate._create_event_security(
                economic_data._PreserveCoordinateWindow(connection)
            )
            for event_year in spec["activation"]["years"]:
                data_runner._create_anchor_strata(
                    connection,
                    event_year,
                    spec["activation"]["minimum_anchor_crossers"],
                )
                sample_frames.append(connection.execute(_sample_query(spec)).fetchdf())
                _guard(spec, started)
            sample = pd.concat(sample_frames, ignore_index=True)
            connection.register("sample_events_df", sample)
            targets = connection.execute(
                """
                SELECT s.event_date,s.market_view,s.symbol,d.trade_date AS session_date,
                       d.cal_idx-s.cal_idx AS event_offset
                FROM sample_events_df s
                JOIN event_security d
                  ON d.symbol=s.symbol AND d.cal_idx BETWEEN s.cal_idx-4 AND s.cal_idx
                ORDER BY s.event_date,s.market_view,s.symbol,d.cal_idx
                """
            ).fetchdf()
        finally:
            connection.close()
    keys = ["event_date", "market_view", "symbol"]
    if sample.duplicated(keys).any():
        raise MinuteCrossScaleError("sample event key is not unique")
    expected = np.minimum(
        sample["anchor_crossing_count"].to_numpy(int),
        spec["activation"]["maximum_hash_sample_each_date_view"],
    )
    group_sizes = sample.groupby(["event_date", "market_view"], sort=True).size()
    group_expected = sample.groupby(["event_date", "market_view"], sort=True).apply(
        lambda group: int(
            min(
                group["anchor_crossing_count"].iloc[0],
                spec["activation"]["maximum_hash_sample_each_date_view"],
            )
        ),
        include_groups=False,
    )
    if not group_sizes.equals(group_expected) or not np.all(
        sample["selection_rank"].to_numpy(int) <= expected
    ):
        raise MinuteCrossScaleError("deterministic sample count mismatch")
    numeric = ["own_depth", *CONTROL_COLUMNS]
    sample["daily_control_complete"] = np.isfinite(
        sample[numeric].to_numpy(float)
    ).all(axis=1)
    construction = {
        "selected_events": len(sample),
        "selected_event_date_views": len(group_sizes),
        "target_event_session_links": len(targets),
        "source_audit": source_audit,
        "source_partitions": source_hashes,
    }
    return sample, targets, construction


def _true(values: pd.Series) -> np.ndarray:
    return values.astype("boolean").fillna(False).to_numpy(dtype=bool)


def _load_target_context(
    cy6_path: Path, cy8_path: Path, targets: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    keys = ["symbol", "trade_date"]
    target_keys = targets[["symbol", "source_symbol", "session_date"]].copy()
    target_keys = target_keys.rename(columns={"session_date": "trade_date"})
    target_keys["trade_date"] = pd.to_datetime(target_keys["trade_date"])
    target_keys = target_keys.drop_duplicates(keys)
    dates = sorted(target_keys["trade_date"].dt.date.unique())
    symbols = sorted(target_keys["symbol"].astype(str).unique())
    filters = [("trade_date", "in", dates), ("symbol", "in", symbols)]
    cy6_columns = [
        *keys,
        "hard_valid",
        "bar_valid",
        "trading_state_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "corporate_action_blocking",
        "available_at",
        "decision_at",
        "close",
        "volume",
        "trade_status",
        "current_day_data_tradable",
        "snapshot_id",
    ]
    cy8_columns = [
        *keys,
        "available_at",
        "minute_count",
        "distinct_minute_count",
        "source_resolution_minutes",
        "session_complete",
        "ohlc_valid",
        "unit_valid",
        "volume_reconciled",
        "amount_reconciled",
        "daily_hard_valid",
        "hard_valid",
        "daily_snapshot_id",
    ]
    cy6 = pq.read_table(
        cy6_path, columns=cy6_columns, filters=filters, use_threads=False
    ).to_pandas()
    cy6["trade_date"] = pd.to_datetime(cy6["trade_date"], errors="raise")
    cy6 = cy6.loc[cy6.set_index(keys).index.isin(target_keys.set_index(keys).index)]
    if cy6.duplicated(keys).any():
        raise MinuteCrossScaleError("duplicate target CY-006 context key")
    cy6 = cy6.rename(
        columns={
            "available_at": "cy6_available_at",
            "snapshot_id": "cy6_snapshot_id",
            "hard_valid": "cy6_hard_valid",
        }
    )
    cy6["daily_eligible"] = (
        _true(cy6["cy6_hard_valid"])
        & _true(cy6["bar_valid"])
        & _true(cy6["trading_state_valid"])
        & _true(cy6["corporate_action_valid"])
        & _true(cy6["market_rule_valid"])
        & _true(cy6["historical_identity_valid"])
        & ~_true(cy6["corporate_action_blocking"])
        & (
            pd.to_datetime(cy6["cy6_available_at"], utc=True)
            <= pd.to_datetime(cy6["decision_at"], utc=True)
        )
        & pd.to_numeric(cy6["close"], errors="coerce").gt(0)
        & pd.to_numeric(cy6["volume"], errors="coerce").gt(0)
        & pd.to_numeric(cy6["trade_status"], errors="coerce").eq(1)
        & _true(cy6["current_day_data_tradable"])
    )
    cy6 = cy6[[*keys, "cy6_snapshot_id", "daily_eligible"]].copy()

    cy8 = pq.read_table(
        cy8_path, columns=cy8_columns, filters=filters, use_threads=False
    ).to_pandas()
    cy8["trade_date"] = pd.to_datetime(cy8["trade_date"], errors="raise")
    cy8 = cy8.loc[cy8.set_index(keys).index.isin(target_keys.set_index(keys).index)]
    if cy8.duplicated(keys).any():
        raise MinuteCrossScaleError("duplicate target CY-008 context key")
    cy8 = cy8.rename(
        columns={"available_at": "cy8_available_at", "hard_valid": "cy8_hard_valid"}
    )
    expected_available = cy8["trade_date"] + pd.Timedelta(hours=15, minutes=30)
    cy8["minute_base_eligible"] = (
        pd.to_datetime(cy8["cy8_available_at"]).eq(expected_available)
        & pd.to_numeric(cy8["minute_count"], errors="coerce").eq(241)
        & pd.to_numeric(cy8["distinct_minute_count"], errors="coerce").eq(241)
        & pd.to_numeric(cy8["source_resolution_minutes"], errors="coerce").eq(1)
        & _true(cy8["session_complete"])
        & _true(cy8["ohlc_valid"])
        & _true(cy8["unit_valid"])
        & _true(cy8["volume_reconciled"])
        & _true(cy8["amount_reconciled"])
        & _true(cy8["daily_hard_valid"])
        & _true(cy8["cy8_hard_valid"])
    )
    cy8 = cy8[[*keys, "daily_snapshot_id", "minute_base_eligible"]].copy()
    context = target_keys.merge(cy6, on=keys, how="left", validate="one_to_one")
    context = context.merge(cy8, on=keys, how="left", validate="one_to_one")
    snapshot_match = context["daily_snapshot_id"].eq(context["cy6_snapshot_id"])
    both_present = context["cy6_snapshot_id"].notna() & context[
        "daily_snapshot_id"
    ].notna()
    if not snapshot_match.loc[both_present].all():
        raise MinuteCrossScaleError("target CY-006/CY-008 snapshot binding failed")
    context["minute_eligible"] = (
        context["minute_base_eligible"].fillna(False).astype(bool)
        & snapshot_match.fillna(False)
    )
    context = context.rename(columns={"trade_date": "session_date"})
    audit = {
        "target_keys": len(target_keys),
        "cy006_rows_read": len(cy6),
        "cy008_rows_read": len(cy8),
        "daily_eligible_targets": int(context["daily_eligible"].fillna(False).sum()),
        "minute_eligible_targets": int(context["minute_eligible"].sum()),
    }
    return context, audit


def _validate_missing_descriptors(raw: Any, missing: pd.DataFrame, adapter: Any) -> None:
    raw_keys = raw.select(
        [
            "symbol",
            "exchange",
            "trade_date",
            "bar_end_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
        ]
    ).to_pandas()
    raw_keys["symbol"] = (
        raw_keys["symbol"].astype(str).str.zfill(6)
        + "."
        + raw_keys["exchange"].astype(str)
    )
    raw_keys["trade_date"] = pd.to_datetime(raw_keys["trade_date"])
    missing_keys = set(missing.itertuples(index=False, name=None))
    for missing_key in missing_keys:
        rows = raw_keys.loc[
            raw_keys["symbol"].eq(missing_key[0])
            & raw_keys["trade_date"].eq(missing_key[1])
        ].sort_values("bar_end_time")
        minute = (
            pd.to_datetime(rows["bar_end_time"]).dt.hour.to_numpy() * 60
            + pd.to_datetime(rows["bar_end_time"]).dt.minute.to_numpy()
        )
        numeric = rows[
            ["open", "high", "low", "close", "volume", "amount"]
        ].to_numpy(float)
        valid_raw = (
            len(rows) == 241
            and np.array_equal(minute, adapter.EXPECTED_MINUTES)
            and np.isfinite(numeric).all()
            and (numeric[:, :4] > 0).all()
            and (numeric[:, 4:] >= 0).all()
            and (
                numeric[:, 1] >= np.maximum(numeric[:, 0], numeric[:, 3])
            ).all()
            and (
                numeric[:, 2] <= np.minimum(numeric[:, 0], numeric[:, 3])
            ).all()
        )
        if not valid_raw:
            raise MinuteCrossScaleError(
                f"CY-008-valid target lacks valid raw session: {missing_key}"
            )


def _minute_descriptors(
    spec: dict[str, Any], targets: pd.DataFrame, started: float
) -> tuple[pd.DataFrame, dict[str, Any]]:
    adapter = _import(
        _resolve(spec["inputs"]["accepted_minute_adapter"]["path"]),
        "minx_minute_adapter",
    )
    minute_spec = adapter.load_frozen_spec()
    required_adapter_columns = set(RAW_DESCRIPTOR_COLUMNS)
    if not required_adapter_columns.issubset(set(adapter.DESCRIPTOR_COLUMNS)):
        raise MinuteCrossScaleError("accepted adapter descriptor identity changed")
    unique_targets = targets[["symbol", "session_date"]].drop_duplicates().copy()
    unique_targets["session_date"] = pd.to_datetime(unique_targets["session_date"])
    unique_targets["source_symbol"] = unique_targets["symbol"].str.split(".").str[0]
    unique_targets["session_year"] = unique_targets["session_date"].dt.year
    years = sorted(unique_targets["session_year"].unique().astype(int).tolist())
    if not set(years).issubset(set(spec["activation"]["years"])):
        raise MinuteCrossScaleError("target minute session outside frozen years")
    qd_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy6_required = [f"partition_year={year}/data_0.parquet" for year in years]
    cy8_required = [f"daily/partition_year={year}/data_0.parquet" for year in years]
    qd_inventory = adapter._resolve(minute_spec["inputs"]["qd004_inventory"]["path"])
    cy6_inventory = adapter._resolve(minute_spec["inputs"]["cy006_inventory"]["path"])
    cy8_inventory = adapter._resolve(minute_spec["inputs"]["cy008_inventory"]["path"])
    qd = adapter.inventory_files(qd_inventory, qd_required)
    cy6 = adapter.inventory_files(cy6_inventory, cy6_required)
    cy8 = adapter.inventory_files(cy8_inventory, cy8_required)
    adapter.verify_inventory_hashes(qd_inventory, qd_required)
    adapter.verify_inventory_hashes(cy6_inventory, cy6_required)
    adapter.verify_inventory_hashes(cy8_inventory, cy8_required)
    descriptor_frames: list[pd.DataFrame] = []
    context_audits: list[dict[str, Any]] = []
    raw_rows = 0
    raw_sessions = 0
    context_valid_targets = 0
    descriptor_incomplete_targets = 0
    for year in years:
        year_targets = unique_targets.loc[unique_targets["session_year"].eq(year)].copy()
        qd_path = qd[f"bars/{year}_day_parquet_none.parquet"]
        year_targets["session_month"] = year_targets["session_date"].dt.to_period("M")
        date_index = 0
        for session_month, month_targets in year_targets.groupby(
            "session_month", sort=True
        ):
            target_context, context_audit = _load_target_context(
                cy6[f"partition_year={year}/data_0.parquet"],
                cy8[f"daily/partition_year={year}/data_0.parquet"],
                month_targets,
            )
            context_audits.append(
                {"year": year, "month": str(session_month), **context_audit}
            )
            valid = (
                target_context["daily_eligible"].fillna(False).astype(bool)
                & target_context["minute_eligible"].fillna(False).astype(bool)
            )
            valid_targets = target_context.loc[
                valid, ["symbol", "source_symbol", "session_date"]
            ].copy()
            context_valid_targets += len(valid_targets)
            for session_date, date_targets in valid_targets.groupby(
                "session_date", sort=True
            ):
                date_index += 1
                try:
                    raw = adapter.read_raw_table(
                        qd_path,
                        [pd.Timestamp(session_date).date()],
                        date_targets["source_symbol"].astype(str),
                    )
                    descriptors, _, raw_audit = (
                        adapter.vectorized_session_descriptors(raw)
                    )
                except adapter.VectorMinuteAdapterError as exc:
                    raise MinuteCrossScaleError(str(exc)) from exc
                wanted = date_targets[["symbol", "session_date"]].rename(
                    columns={"session_date": "trade_date"}
                )
                selected = wanted.merge(
                    descriptors[["symbol", "trade_date", *RAW_DESCRIPTOR_COLUMNS]],
                    on=["symbol", "trade_date"],
                    how="left",
                    validate="one_to_one",
                    indicator=True,
                )
                missing = selected.loc[
                    selected["_merge"].ne("both"), ["symbol", "trade_date"]
                ]
                if len(missing):
                    _validate_missing_descriptors(raw, missing, adapter)
                    descriptor_incomplete_targets += len(missing)
                selected = selected.loc[selected["_merge"].eq("both")].drop(
                    columns="_merge"
                )
                if len(selected):
                    descriptor_frames.append(selected)
                raw_rows += int(raw_audit["raw_rows"])
                raw_sessions += int(raw_audit["raw_sessions"])
                del raw, descriptors, selected
                if date_index % 25 == 0:
                    gc.collect()
                    _guard(spec, started)
            del target_context, valid_targets
            gc.collect()
            _guard(spec, started)
        gc.collect()
        _guard(spec, started)
    descriptors = pd.concat(descriptor_frames, ignore_index=True)
    if descriptors.duplicated(["symbol", "trade_date"]).any():
        raise MinuteCrossScaleError("sampled minute descriptor key is not unique")
    if not np.isfinite(descriptors[RAW_DESCRIPTOR_COLUMNS].to_numpy(float)).all():
        raise MinuteCrossScaleError("sampled minute descriptor contains nonfinite values")
    audit = {
        "unique_target_sessions": len(unique_targets),
        "context_valid_target_sessions": context_valid_targets,
        "descriptor_sessions": len(descriptors),
        "descriptor_incomplete_target_sessions": descriptor_incomplete_targets,
        "raw_rows_read": raw_rows,
        "raw_sessions_read": raw_sessions,
        "context_audits": context_audits,
    }
    return descriptors, audit


def _pre_slope(values: np.ndarray) -> np.ndarray:
    centered = np.array([-1.5, -0.5, 0.5, 1.5])
    return values[:, :4] @ centered / float(np.square(centered).sum())


def _feature_frame(
    sample: pd.DataFrame,
    targets: pd.DataFrame,
    descriptors: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = ["event_date", "market_view", "symbol"]
    long = targets.merge(
        descriptors,
        left_on=["symbol", "session_date"],
        right_on=["symbol", "trade_date"],
        how="left",
        validate="many_to_one",
    )
    counts = long.groupby(keys, sort=True)[RAW_DESCRIPTOR_COLUMNS[0]].count().rename(
        "minute_descriptor_count"
    )
    sample_audit = sample.merge(counts, on=keys, how="left", validate="one_to_one")
    sample_audit["minute_descriptor_count"] = (
        sample_audit["minute_descriptor_count"].fillna(0).astype(int)
    )
    sample_audit["trajectory_complete"] = (
        sample_audit["daily_control_complete"]
        & sample_audit["minute_descriptor_count"].eq(5)
    )
    complete_keys = sample_audit.loc[sample_audit["trajectory_complete"], keys]
    complete_long = long.merge(complete_keys, on=keys, validate="many_to_one")
    wide = complete_long.pivot(
        index=keys, columns="event_offset", values=RAW_DESCRIPTOR_COLUMNS
    )
    expected_columns = pd.MultiIndex.from_product(
        [RAW_DESCRIPTOR_COLUMNS, [-4, -3, -2, -1, 0]]
    )
    if not expected_columns.isin(wide.columns).all():
        raise MinuteCrossScaleError("complete trajectory offset schema changed")
    wide = wide[expected_columns]
    wide.columns = [f"{descriptor}__{offset}" for descriptor, offset in wide.columns]
    wide = wide.reset_index()
    metadata = sample_audit.loc[sample_audit["trajectory_complete"]].drop(
        columns=["minute_descriptor_count", "trajectory_complete"]
    )
    frame = metadata.merge(wide, on=keys, validate="one_to_one")
    feature_values: dict[str, np.ndarray] = {}
    for feature, descriptor in EVENT_DESCRIPTOR_MAP.items():
        feature_values[feature] = frame[f"{descriptor}__0"].to_numpy(float)
    feature_values["event_volume_asymmetry"] = (
        frame["up_minute_volume_share__0"].to_numpy(float)
        - frame["down_minute_volume_share__0"].to_numpy(float)
    )
    for descriptor in TRAJECTORY_BASES:
        columns = [f"{descriptor}__{offset}" for offset in (-4, -3, -2, -1, 0)]
        values = frame[columns].to_numpy(float)
        feature_values[f"pre_slope4_{descriptor}"] = _pre_slope(values)
        feature_values[f"event_jump_{descriptor}"] = values[:, 4] - values[:, :4].mean(
            axis=1
        )
    clean = frame[[*keys, "own_depth", "anchor_crossing_count", *CONTROL_COLUMNS]].copy()
    for name, values in feature_values.items():
        clean[name] = values
    complete_values = clean[
        ["own_depth", *CONTROL_COLUMNS, *feature_values]
    ].to_numpy(float)
    if not np.isfinite(complete_values).all():
        raise MinuteCrossScaleError("complete feature frame contains nonfinite values")
    return clean, sample_audit


def _rank(frame: pd.DataFrame) -> np.ndarray:
    return frame.rank(method="average").to_numpy(dtype=float)


def _residual(values: np.ndarray, controls: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(values)), controls])
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    return values - design @ coefficients


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def _date_audit(
    frame: pd.DataFrame, sample_audit: pd.DataFrame, spec: dict[str, Any]
) -> pd.DataFrame:
    keys = ["event_date", "market_view"]
    features = [
        column
        for column in frame.columns
        if column != "event_date"
        and column.startswith(("event_", "pre_slope4_"))
    ]
    selected_counts = sample_audit.groupby(keys, sort=True).size()
    rows: list[dict[str, Any]] = []
    minimum = spec["estimation"]["minimum_complete_rows_each_date_view"]
    minimum_retention = spec["estimation"][
        "minimum_complete_retention_each_date_view"
    ]
    for key, group in frame.groupby(keys, sort=True):
        selected_n = int(selected_counts.loc[key])
        retention = len(group) / selected_n
        supported = len(group) >= minimum and retention >= minimum_retention
        ranked_controls = _rank(group[CONTROL_COLUMNS]) if supported else None
        target_rank = (
            group[["own_depth"]].rank(method="average").to_numpy(float).ravel()
            if supported
            else None
        )
        target_residual = (
            _residual(target_rank, ranked_controls)
            if target_rank is not None and ranked_controls is not None
            else None
        )
        for feature in features:
            if supported and target_rank is not None and target_residual is not None:
                feature_rank = (
                    group[[feature]].rank(method="average").to_numpy(float).ravel()
                )
                raw_rho = _corr(target_rank, feature_rank)
                partial_rho = _corr(
                    target_residual, _residual(feature_rank, ranked_controls)
                )
            else:
                raw_rho = float("nan")
                partial_rho = float("nan")
            rows.append(
                {
                    "event_date": key[0],
                    "event_year": pd.Timestamp(key[0]).year,
                    "block": (
                        "A" if pd.Timestamp(key[0]).year <= 2020 else "B"
                    ),
                    "market_view": key[1],
                    "feature": feature,
                    "selected_count": selected_n,
                    "complete_count": len(group),
                    "retention": retention,
                    "supported": supported,
                    "raw_rho": raw_rho,
                    "partial_rho": partial_rho,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["event_date", "market_view", "feature"]
    ).reset_index(drop=True)


def _median(values: Any) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _same_sign(values: dict[str, float], sign: int) -> bool:
    return all(np.isfinite(value) and int(np.sign(value)) == sign for value in values.values())


def _summarize_feature(
    feature_audit: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    supported = feature_audit.loc[
        feature_audit["supported"]
        & feature_audit["raw_rho"].notna()
        & feature_audit["partial_rho"].notna()
    ]
    raw = _median(supported["raw_rho"])
    partial = _median(supported["partial_rho"])
    raw_sign = int(np.sign(raw)) if np.isfinite(raw) and raw != 0 else 0
    partial_sign = int(np.sign(partial)) if np.isfinite(partial) and partial != 0 else 0
    raw_blocks = {
        block: _median(supported.loc[supported["block"].eq(block), "raw_rho"])
        for block in spec["estimation"]["blocks"]
    }
    raw_views = {
        view: _median(
            supported.loc[supported["market_view"].eq(view), "raw_rho"]
        )
        for view in spec["activation"]["market_views"]
    }
    raw_years = {
        str(year): _median(
            supported.loc[supported["event_year"].eq(year), "raw_rho"]
        )
        for year in spec["activation"]["years"]
    }
    partial_blocks = {
        block: _median(supported.loc[supported["block"].eq(block), "partial_rho"])
        for block in spec["estimation"]["blocks"]
    }
    partial_views = {
        view: _median(
            supported.loc[supported["market_view"].eq(view), "partial_rho"]
        )
        for view in spec["activation"]["market_views"]
    }
    partial_years = {
        str(year): _median(
            supported.loc[supported["event_year"].eq(year), "partial_rho"]
        )
        for year in spec["activation"]["years"]
    }
    minimum_dates = spec["estimation"]["minimum_supported_dates_each_view_year"]
    support_counts = supported.groupby(["market_view", "event_year"], sort=True).size()
    support_pass = (
        len(support_counts)
        == len(spec["activation"]["market_views"])
        * len(spec["activation"]["years"])
        and int(support_counts.min()) >= minimum_dates
    )
    minimum_years = spec["estimation"]["minimum_same_sign_years"]
    raw_portable = (
        raw_sign != 0
        and _same_sign(raw_blocks, raw_sign)
        and _same_sign(raw_views, raw_sign)
        and sum(int(np.sign(value)) == raw_sign for value in raw_years.values())
        >= minimum_years
    )
    partial_portable = (
        partial_sign != 0
        and _same_sign(partial_blocks, partial_sign)
        and _same_sign(partial_views, partial_sign)
        and sum(int(np.sign(value)) == partial_sign for value in partial_years.values())
        >= minimum_years
    )
    return {
        "support_pass": support_pass,
        "supported_date_views": len(supported),
        "minimum_supported_dates_each_view_year": (
            int(support_counts.min()) if len(support_counts) else 0
        ),
        "median_raw_rho": raw,
        "median_partial_rho": partial,
        "raw_block_medians": raw_blocks,
        "raw_view_medians": raw_views,
        "raw_year_medians": raw_years,
        "partial_block_medians": partial_blocks,
        "partial_view_medians": partial_views,
        "partial_year_medians": partial_years,
        "raw_portable_sign": raw_portable,
        "partial_portable_sign": partial_portable,
        "raw_exploratory_effect": (
            support_pass
            and raw_portable
            and abs(raw) >= spec["estimation"]["exploratory_role_effect_floor"]
        ),
        "partial_exploratory_effect": (
            support_pass
            and partial_portable
            and abs(partial)
            >= spec["estimation"]["exploratory_partial_effect_floor"]
        ),
    }


def _evaluate(audit: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    summaries = {
        feature: _summarize_feature(group, spec)
        for feature, group in audit.groupby("feature", sort=True)
    }
    support_pass = all(item["support_pass"] for item in summaries.values())
    mechanism_consistency: dict[str, Any] = {}
    for mechanism, roles in spec["mechanism_sign_map"].items():
        matched: list[str] = []
        contradicted: list[str] = []
        unresolved: list[str] = []
        for role, expected_sign in roles.items():
            item = summaries[role]
            if not item["raw_exploratory_effect"]:
                unresolved.append(role)
            elif int(np.sign(item["median_raw_rho"])) == int(expected_sign):
                matched.append(role)
            else:
                contradicted.append(role)
        mechanism_consistency[mechanism] = {
            "expected_roles": len(roles),
            "matched_roles": matched,
            "contradicted_roles": contradicted,
            "unresolved_roles": unresolved,
            "matched_fraction": len(matched) / len(roles),
        }
    return {
        "support_pass": support_pass,
        "decision": (
            "EXPLORATORY_MINUTE_PATTERN_MAPPED"
            if support_pass
            else "SAMPLED_MINUTE_MECHANISM_NOT_ESTIMABLE"
        ),
        "features": summaries,
        "mechanism_consistency": mechanism_consistency,
    }


def _report(result: dict[str, Any]) -> str:
    evaluation = result["evaluation"]
    ordered = sorted(
        evaluation["features"].items(),
        key=lambda item: abs(item[1]["median_raw_rho"]),
        reverse=True,
    )
    rows = [
        "| Coordinate | Raw rho | Partial rho | Raw effect | Partial effect |",
        "|---|---:|---:|---|---|",
    ]
    for name, item in ordered:
        rows.append(
            f"| `{name}` | {item['median_raw_rho']:.4f} | "
            f"{item['median_partial_rho']:.4f} | "
            f"{'YES' if item['raw_exploratory_effect'] else 'no'} | "
            f"{'YES' if item['partial_exploratory_effect'] else 'no'} |"
        )
    mechanisms = []
    for name, item in evaluation["mechanism_consistency"].items():
        mechanisms.append(
            f"- `{name}`: {len(item['matched_roles'])}/{item['expected_roles']} "
            f"expected roles match; contradicted={item['contradicted_roles']}; "
            f"unresolved={item['unresolved_roles']}."
        )
    return "\n".join(
        [
            "# MKT-FORMDEPTH-MINX-001 cross-scale exploration",
            "",
            "## Decision",
            "",
            f"`{evaluation['decision']}`",
            "",
            *rows,
            "",
            "## Mechanism consistency",
            "",
            *mechanisms,
            "",
            "The raw column asks which minute paths accompany deeper own overshoot. The",
            "partial column asks what remains after the same five fixed daily-geometry",
            "rank controls. This is consumed pre-2024 sampled exploration, not causal",
            "price impact, participant intent, prediction, payoff, habitat, or strategy.",
            "",
        ]
    )


def _write_stage(
    stage_dir: Path,
    sample: pd.DataFrame,
    targets: pd.DataFrame,
    construction: dict[str, Any],
    started: float,
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=False)
    sample_path = stage_dir / "sample.parquet"
    targets_path = stage_dir / "targets.parquet"
    manifest_path = stage_dir / "manifest.json"
    sample.to_parquet(sample_path, index=False)
    targets.to_parquet(targets_path, index=False)
    manifest = {
        "experiment_id": "MKT-FORMDEPTH-MINX-001",
        "spec_sha256": sha256_file(SPEC_PATH),
        "sample_sha256": sha256_file(sample_path),
        "targets_sha256": sha256_file(targets_path),
        "sample_rows": len(sample),
        "target_rows": len(targets),
        "construction": construction,
        "sample_stage_elapsed_seconds": time.monotonic() - started,
        "sample_stage_peak_rss_bytes": _peak_rss_bytes(),
        "future_values_read": False,
        "minute_values_read": False,
    }
    manifest_path.write_text(
        json.dumps(_clean(manifest), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _read_stage(stage_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    sample_path = stage_dir / "sample.parquet"
    targets_path = stage_dir / "targets.parquet"
    manifest_path = stage_dir / "manifest.json"
    if not all(path.is_file() for path in (sample_path, targets_path, manifest_path)):
        raise MinuteCrossScaleError("serial stage handoff is incomplete")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    checks = (
        manifest["experiment_id"] == "MKT-FORMDEPTH-MINX-001",
        manifest["spec_sha256"] == sha256_file(SPEC_PATH),
        manifest["sample_sha256"] == sha256_file(sample_path),
        manifest["targets_sha256"] == sha256_file(targets_path),
        manifest["future_values_read"] is False,
        manifest["minute_values_read"] is False,
    )
    if not all(checks):
        raise MinuteCrossScaleError("serial stage handoff identity mismatch")
    sample = pd.read_parquet(sample_path)
    targets = pd.read_parquet(targets_path)
    if len(sample) != manifest["sample_rows"] or len(targets) != manifest["target_rows"]:
        raise MinuteCrossScaleError("serial stage handoff row count mismatch")
    return sample, targets, manifest


def _analyze(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    targets: pd.DataFrame,
    construction: dict[str, Any],
    started: float,
    sample_stage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _load_spec()
    descriptors, minute_audit = _minute_descriptors(spec, targets, started)
    feature_frame, sample_audit = _feature_frame(sample, targets, descriptors)
    audit = _date_audit(feature_frame, sample_audit, spec)
    evaluation = _evaluate(audit, spec)
    SAMPLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    sample_output = sample_audit[
        [
            "event_date",
            "market_view",
            "denominator",
            "symbol",
            "selection_hash",
            "selection_rank",
            "anchor_crossing_count",
            "own_depth",
            "daily_control_complete",
            "minute_descriptor_count",
            "trajectory_complete",
        ]
    ].copy()
    sample_output.to_csv(
        SAMPLE_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "claim": spec["claim_boundary"],
        "construction": {
            **construction,
            "minute_audit": minute_audit,
            "complete_event_trajectories": len(feature_frame),
            "peak_rss_bytes": max(
                _peak_rss_bytes(),
                int((sample_stage or {}).get("sample_stage_peak_rss_bytes", 0)),
            ),
            "elapsed_seconds": time.monotonic() - started,
            "serial_stage_handoff": (
                {
                    "sample_sha256": sample_stage["sample_sha256"],
                    "targets_sha256": sample_stage["targets_sha256"],
                    "sample_stage_elapsed_seconds": sample_stage[
                        "sample_stage_elapsed_seconds"
                    ],
                }
                if sample_stage is not None
                else None
            ),
        },
        "evaluation": evaluation,
        "minute_cache_published": False,
        "durable_security_minute_descriptors": False,
        "future_values_read": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "sample_audit_sha256": sha256_file(SAMPLE_PATH),
            "date_audit_sha256": sha256_file(AUDIT_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    durable = sum(
        path.stat().st_size for path in (SAMPLE_PATH, AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise MinuteCrossScaleError("durable output ceiling breached")
    _guard(spec, started)
    print(json.dumps(_clean(result), indent=2, sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=("all", "sample", "analyze"), default="all")
    parser.add_argument("--stage-dir", type=Path)
    args = parser.parse_args()
    spec = _load_spec()
    if args.stage == "sample":
        if args.stage_dir is None:
            raise MinuteCrossScaleError("sample stage requires --stage-dir")
        started = time.monotonic()
        sample, targets, construction = _build_sample(spec, started)
        manifest = _write_stage(
            args.stage_dir, sample, targets, construction, started
        )
        _guard(spec, started)
        print(json.dumps(_clean(manifest), indent=2, sort_keys=True))
        return
    if args.stage == "analyze":
        if args.stage_dir is None:
            raise MinuteCrossScaleError("analyze stage requires --stage-dir")
        sample, targets, manifest = _read_stage(args.stage_dir)
        started = time.monotonic() - float(manifest["sample_stage_elapsed_seconds"])
        _analyze(
            spec,
            sample,
            targets,
            manifest["construction"],
            started,
            sample_stage=manifest,
        )
        return
    started = time.monotonic()
    sample, targets, construction = _build_sample(spec, started)
    _analyze(spec, sample, targets, construction, started)


if __name__ == "__main__":
    main()
