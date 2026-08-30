#!/usr/bin/env python3
"""Audit PIT prior-high coordinates and objective crossing event support."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-DATA-001_spec.json"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_data_003.py"
PARENT_SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_sample.csv"
PARENT_COORDINATE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-004_coordinate_audit.csv"
COORDINATE_EVENT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DATA-001_coordinate_event_audit.csv"
COUNT_AUDIT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DATA-001_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "db3d0cfa1ea7c6d8ca89fe553c0b4803ac36080b02a57160c41e9391b5040b79"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


data003 = _load_module("run_mkt_support_data_003_for_breakout", PARENT_RUNNER)
base = data003.parent.parent
adapter = data003.adapter
sha256_file = data003.sha256_file


class BreakoutDataError(RuntimeError):
    """Fail-closed MKT-BREAKOUT-DATA-001 error."""


DEFINITIONS = {
    "L10_CONTINUOUS": ("resistance_high10", False),
    "L20_CONTINUOUS": ("resistance_high20", False),
    "L40_CONTINUOUS": ("resistance_high40", False),
    "L20_AUCTION": ("resistance_high20", True),
}


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


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
        raise BreakoutDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_PRIOR_HIGH_COORDINATE_OR_NEW_RAW_MINUTE_ACCESS"
        or spec["outcome_access"] is not False
    ):
        raise BreakoutDataError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise BreakoutDataError(f"input identity mismatch: {name}")
    if spec["coordinate"]["lookbacks"] != [10, 20, 40]:
        raise BreakoutDataError("prior-high lookbacks changed")
    if spec["event"]["equality_is_crossing"] is not False:
        raise BreakoutDataError("strict crossing contract changed")
    if spec["event"]["remaining_bar_horizons"] != [5, 15, 30, 60]:
        raise BreakoutDataError("censoring horizons changed")
    return spec


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < budget["system_memory_headroom_floor_gib"] * 2**30:
        raise BreakoutDataError("system memory headroom floor breached")
    if adapter._max_rss_bytes() > budget["peak_rss_ceiling_gib"] * 2**30:
        raise BreakoutDataError("process RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise BreakoutDataError("wall-clock ceiling breached")


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _load_parent_sample(spec: dict[str, Any]) -> pd.DataFrame:
    sample = pd.read_csv(PARENT_SAMPLE_PATH, dtype={"source_symbol": str})
    sample["trade_date"] = pd.to_datetime(sample["trade_date"], errors="raise")
    population = spec["population"]
    if (
        len(sample) != population["expected_cohort_rows"]
        or sample["sequence_id"].nunique() != population["expected_sequences"]
        or len(sample[["symbol", "trade_date"]].drop_duplicates())
        != population["expected_unique_sessions"]
    ):
        raise BreakoutDataError("parent sample population changed")
    for sequence_id, rows in sample.groupby("sequence_id", sort=False):
        if sorted(rows["relative_day"].astype(int).tolist()) != [-5, -4, -3, -2, -1]:
            raise BreakoutDataError(f"sequence day conservation changed: {sequence_id}")
    return sample.sort_values("audit_id").reset_index(drop=True)


def _create_capped_daily_coordinate(
    spec: dict[str, Any], cy006_paths: dict[str, Path], temp_dir: Path
) -> Any:
    duckdb_module = base.duckdb
    original_connect = duckdb_module.connect

    def capped_connect(*args: Any, **kwargs: Any) -> Any:
        connection = original_connect(*args, **kwargs)
        connection.execute("SET memory_limit='1.5GB'")
        connection.execute("SET temp_directory=?", [str(temp_dir)])
        return connection

    duckdb_module.connect = capped_connect
    try:
        connection = base._create_daily_coordinate(
            {"date_range": {"exchange_sessions": 1457}}, cy006_paths
        )
    finally:
        duckdb_module.connect = original_connect
    spill = _directory_bytes(temp_dir)
    if spill > spec["resource_budget"]["temporary_spill_ceiling_gib"] * 2**30:
        connection.close()
        raise BreakoutDataError("daily-coordinate disposable spill ceiling breached")
    return connection


def _target_coordinates_and_history(
    connection: Any, sample: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    keys = sample[["symbol", "trade_date"]].drop_duplicates().copy()
    connection.register("breakout_target_keys", keys)
    coordinates = connection.execute(
        """
        SELECT c.symbol,c.trade_date,c.cal_idx,c.coordinate_eligible,
               c.close AS daily_raw_close,c.coordinate_close,
               c.coordinate_close/c.close AS coordinate_scale,
               c.support_low10,c.support_low20,c.support_low40,
               c.up_limit_price,c.down_limit_price,c.corporate_action_count,
               c.corporate_action_blocking,c.rights_ratio,c.snapshot_id
        FROM coordinate c JOIN breakout_target_keys t USING(symbol,trade_date)
        ORDER BY c.symbol,c.trade_date
        """
    ).df()
    history = connection.execute(
        """
        SELECT t.symbol,t.trade_date AS target_date,h.trade_date AS history_date,
               t.cal_idx-h.cal_idx AS lag,h.coordinate_close,h.high,h.close,
               h.coordinate_close*h.high/h.close AS coordinate_high,
               h.history_valid,h.coordinate_step_valid
        FROM (
          SELECT c.symbol,c.trade_date,c.cal_idx
          FROM coordinate c JOIN breakout_target_keys k USING(symbol,trade_date)
        ) t
        JOIN coordinate h ON h.symbol=t.symbol
          AND h.cal_idx BETWEEN t.cal_idx-40 AND t.cal_idx-1
        ORDER BY t.symbol,t.trade_date,t.cal_idx-h.cal_idx
        """
    ).df()
    if len(coordinates) != len(keys) or not coordinates["coordinate_eligible"].astype(bool).all():
        raise BreakoutDataError("target coordinate coverage or eligibility changed")
    if len(history) != 40 * len(keys):
        raise BreakoutDataError("prior-40 history row conservation changed")
    group_fields = ["symbol", "target_date"]
    lag_sets = history.groupby(group_fields)["lag"].agg(lambda values: tuple(sorted(values)))
    if any(value != tuple(range(1, 41)) for value in lag_sets):
        raise BreakoutDataError("prior-40 consecutive lag set changed")
    if not history["history_valid"].astype(bool).all():
        raise BreakoutDataError("invalid row entered prior-high history")
    numeric = history[["coordinate_close", "high", "close", "coordinate_high"]].to_numpy(float)
    if not np.isfinite(numeric).all() or not (numeric > 0).all():
        raise BreakoutDataError("prior-high history contains invalid numeric value")

    level_records: list[dict[str, Any]] = []
    for (symbol, target_date), rows in history.groupby(group_fields, sort=True):
        record: dict[str, Any] = {"symbol": symbol, "trade_date": target_date}
        for lookback in (10, 20, 40):
            values = rows.loc[rows["lag"].le(lookback), "coordinate_high"].to_numpy(float)
            if len(values) != lookback:
                raise BreakoutDataError("prior-high lookback count changed")
            record[f"resistance_high{lookback}"] = float(np.max(values))
        level_records.append(record)
    levels = pd.DataFrame(level_records)
    coordinates = coordinates.merge(levels, on=["symbol", "trade_date"], validate="one_to_one")
    return coordinates, history


def _verify_parent_coordinate_equivalence(
    spec: dict[str, Any], coordinates: pd.DataFrame
) -> dict[str, int]:
    parent = pd.read_csv(
        PARENT_COORDINATE_PATH,
        dtype={"source_symbol": str},
        float_precision="round_trip",
    )
    parent["trade_date"] = pd.to_datetime(parent["trade_date"], errors="raise")
    unique_parent = parent.drop_duplicates(["symbol", "trade_date"]).copy()
    if len(unique_parent) != spec["population"]["expected_unique_sessions"]:
        raise BreakoutDataError("parent coordinate unique population changed")
    joined = coordinates.merge(
        unique_parent,
        on=["symbol", "trade_date"],
        suffixes=("_new", "_parent"),
        validate="one_to_one",
    )
    exact_fields = [
        "daily_raw_close",
        "coordinate_close",
        "coordinate_scale",
        "support_low10",
        "support_low20",
        "support_low40",
    ]
    for field in exact_fields:
        left = joined[f"{field}_new"].to_numpy(float)
        right = joined[f"{field}_parent"].to_numpy(float)
        if not np.array_equal(left, right):
            index = int(np.flatnonzero(left != right)[0])
            row = joined.iloc[index]
            raise BreakoutDataError(
                f"parent coordinate disagreement: {row.symbol}:{row.trade_date}:{field}:"
                f"{left[index]!r}!={right[index]!r}"
            )
    if not (
        joined["snapshot_id"].astype(str).to_numpy()
        == joined["daily_snapshot_id"].astype(str).to_numpy()
    ).all():
        raise BreakoutDataError("parent snapshot identity disagreement")
    if joined["corporate_action_blocking_new"].astype(bool).any():
        raise BreakoutDataError("blocking action entered target coordinate")
    if joined["rights_ratio_new"].fillna(0.0).astype(float).ne(0.0).any():
        raise BreakoutDataError("rights action entered target coordinate")
    return {"unique_sessions": len(joined), "exact_numeric_fields": len(exact_fields)}


def event_summary(
    mapped_high: np.ndarray,
    mapped_close: np.ndarray,
    level: float,
    *,
    include_auction: bool,
) -> dict[str, Any]:
    """Count-only strict-crossing state; no post-cross magnitude is computed."""
    start = 0 if include_auction else 1
    highs = np.asarray(mapped_high, dtype=float)[start:]
    closes = np.asarray(mapped_close, dtype=float)[start:]
    crossed = np.flatnonzero(highs > level)
    if len(crossed) == 0:
        return {
            "cross": False,
            "first_cross_index": None,
            "remaining_bars": None,
            "closing_state": "NO_CROSS",
            "close_loss": False,
            "reacquired": False,
        }
    first = int(crossed[0])
    final = float(closes[-1])
    if final > level:
        state = "CROSS_CLOSE_ABOVE"
    elif final < level:
        state = "CROSS_CLOSE_BELOW"
    else:
        state = "CROSS_CLOSE_EQUAL"
    post = closes[first:]
    losses = np.flatnonzero(post < level)
    close_loss = len(losses) > 0
    reacquired = False
    if close_loss:
        reacquired = bool(np.any(post[int(losses[0]) + 1 :] > level))
    return {
        "cross": True,
        "first_cross_index": first,
        "remaining_bars": int(len(highs) - first - 1),
        "closing_state": state,
        "close_loss": close_loss,
        "reacquired": reacquired,
    }


def _event_columns(name: str, summary: dict[str, Any]) -> dict[str, Any]:
    prefix = name.lower()
    return {
        f"{prefix}_cross": summary["cross"],
        f"{prefix}_first_cross_index": summary["first_cross_index"],
        f"{prefix}_remaining_bars": summary["remaining_bars"],
        f"{prefix}_closing_state": summary["closing_state"],
        f"{prefix}_close_loss": summary["close_loss"],
        f"{prefix}_reacquired": summary["reacquired"],
    }


def _case_hash(symbol: str, trade_date: pd.Timestamp) -> str:
    payload = f"MKT-BREAKOUT-DATA-001|{symbol}|{trade_date.date()}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _audit_minute_events(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
    started: float,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    coordinate_index = coordinates.set_index(["symbol", "trade_date"])
    unique_targets = sample[
        ["symbol", "source_symbol", "trade_date", "target_year", "block_id"]
    ].drop_duplicates()
    records: list[dict[str, Any]] = []
    scalar_candidates: list[dict[str, Any]] = []
    raw_rows_read = 0
    for (raw_year, raw_block), targets in unique_targets.groupby(
        ["target_year", "block_id"], sort=True
    ):
        _resource_guard(spec, started)
        year = int(raw_year)
        qd_path = partitions["qd004"][f"bars/{year}_day_parquet_none.parquet"]
        try:
            table = adapter.read_raw_table(
                qd_path,
                pd.to_datetime(targets["trade_date"]).dt.date,
                targets["source_symbol"].astype(str),
            )
            descriptors, opening, vector_audit = adapter.vectorized_session_descriptors(table)
        except adapter.VectorMinuteAdapterError as exc:
            raise BreakoutDataError(str(exc)) from exc
        del descriptors, opening
        raw_rows_read += int(vector_audit["raw_rows"])
        raw = table.to_pandas()
        del table
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        block_coordinates = coordinates.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="one_to_one",
        )
        try:
            data003._read_and_validate_cy008(year, targets, block_coordinates, partitions)
        except data003.SupportDataError as exc:
            raise BreakoutDataError(str(exc)) from exc
        if raw.groupby(["symbol", "trade_date"]).ngroups != len(block_coordinates):
            raise BreakoutDataError(f"raw session coverage changed: {year}:{raw_block}")

        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise BreakoutDataError(f"minute grid changed: {symbol}:{trade_date}")
            daily = coordinate_index.loc[(symbol, pd.Timestamp(trade_date))]
            raw_ohlc = rows[["open", "high", "low", "close"]].to_numpy(float)
            if not np.isfinite(raw_ohlc).all() or not (raw_ohlc > 0).all():
                raise BreakoutDataError(f"invalid raw minute OHLC: {symbol}:{trade_date}")
            scale = float(daily.coordinate_scale)
            mapped = raw_ohlc * scale
            if not np.isfinite(mapped).all() or not (mapped > 0).all():
                raise BreakoutDataError(f"invalid mapped minute OHLC: {symbol}:{trade_date}")
            record: dict[str, Any] = {
                "symbol": symbol,
                "trade_date": pd.Timestamp(trade_date),
                "daily_raw_close": float(daily.daily_raw_close),
                "minute_raw_close": float(raw_ohlc[-1, 3]),
                "coordinate_scale": scale,
                "coordinate_close": float(daily.coordinate_close),
                "resistance_high10": float(daily.resistance_high10),
                "resistance_high20": float(daily.resistance_high20),
                "resistance_high40": float(daily.resistance_high40),
                "up_limit_contact": bool(np.max(raw_ohlc[:, 1]) >= float(daily.up_limit_price)),
                "down_limit_contact": bool(np.min(raw_ohlc[:, 2]) <= float(daily.down_limit_price)),
                "corporate_action_count": int(daily.corporate_action_count or 0),
                "rights_ratio": float(daily.rights_ratio or 0.0),
                "corporate_action_blocking": bool(daily.corporate_action_blocking),
                "daily_snapshot_id": str(daily.snapshot_id),
                "descriptor_available_at": (f"{pd.Timestamp(trade_date).date()}T15:30:00+08:00"),
            }
            summaries: dict[str, dict[str, Any]] = {}
            for name, (level_field, include_auction) in DEFINITIONS.items():
                summary = event_summary(
                    mapped[:, 1],
                    mapped[:, 3],
                    float(daily[level_field]),
                    include_auction=include_auction,
                )
                summaries[name] = summary
                record.update(_event_columns(name, summary))
            record["l20_auction_only_cross"] = bool(
                summaries["L20_AUCTION"]["cross"] and not summaries["L20_CONTINUOUS"]["cross"]
            )
            records.append(record)

            primary = summaries["L20_CONTINUOUS"]
            if primary["cross"]:
                scalar_candidates.append(
                    {
                        "selection_hash": _case_hash(symbol, pd.Timestamp(trade_date)),
                        "symbol": symbol,
                        "trade_date": pd.Timestamp(trade_date),
                        "mapped_high": mapped[:, 1].copy(),
                        "mapped_close": mapped[:, 3].copy(),
                        "vector_level": float(daily.resistance_high20),
                        "vector_first_cross_index": int(primary["first_cross_index"]),
                        "vector_closing_state": str(primary["closing_state"]),
                        "vector_remaining_bars": int(primary["remaining_bars"]),
                    }
                )
                scalar_candidates.sort(key=lambda item: item["selection_hash"])
                del scalar_candidates[5:]
        del raw, block_coordinates
        gc.collect()
        _resource_guard(spec, started)
    expected_raw = spec["resource_budget"]["planned_raw_minute_rows"]
    if raw_rows_read != expected_raw:
        raise BreakoutDataError(f"raw row conservation changed: {raw_rows_read}!={expected_raw}")
    unique = pd.DataFrame(records).sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    if len(unique) != spec["population"]["expected_unique_sessions"]:
        raise BreakoutDataError("unique event-audit population changed")
    output = sample.merge(unique, on=["symbol", "trade_date"], validate="many_to_one")
    if len(output) != spec["population"]["expected_cohort_rows"]:
        raise BreakoutDataError("cohort event-audit population changed")
    return output.sort_values("audit_id").reset_index(drop=True), scalar_candidates


def _definition_stats(frame: pd.DataFrame, name: str, spec: dict[str, Any]) -> dict[str, Any]:
    prefix = name.lower()
    cross = frame[f"{prefix}_cross"].astype(bool)
    state = frame[f"{prefix}_closing_state"].astype(str)
    reacquired = frame[f"{prefix}_reacquired"].astype(bool) & cross
    remaining = pd.to_numeric(frame[f"{prefix}_remaining_bars"], errors="coerce")
    years = spec["population"]["years"]
    blocks = spec["population"]["temporal_blocks"]

    def counts(mask: pd.Series, group: str) -> dict[str, int]:
        return {
            str(key): int(value) for key, value in frame.loc[mask].groupby(group).size().items()
        }

    result: dict[str, Any] = {
        "crossings_total": int(cross.sum()),
        "crossings_unique_sessions": int(
            frame.loc[cross, ["symbol", "trade_date"]].drop_duplicates().shape[0]
        ),
        "crossings_by_year": {
            str(year): int((cross & frame["target_year"].eq(year)).sum()) for year in years
        },
        "crossings_by_block": {
            label: int((cross & frame["target_year"].isin(block_years)).sum())
            for label, block_years in blocks.items()
        },
        "crossings_by_view": counts(cross, "market_view"),
        "crossings_by_view_year": {
            f"{view}|{year}": int(
                (cross & frame["market_view"].eq(view) & frame["target_year"].eq(year)).sum()
            )
            for view in spec["population"]["market_views"]
            for year in years
        },
        "closing_states": {
            label: int((cross & state.eq(label)).sum())
            for label in [
                "CROSS_CLOSE_ABOVE",
                "CROSS_CLOSE_EQUAL",
                "CROSS_CLOSE_BELOW",
            ]
        },
        "closing_states_by_year": {
            label: {
                str(year): int((cross & state.eq(label) & frame["target_year"].eq(year)).sum())
                for year in years
            }
            for label in ["CROSS_CLOSE_ABOVE", "CROSS_CLOSE_EQUAL", "CROSS_CLOSE_BELOW"]
        },
        "closing_states_by_block": {
            label: {
                block: int((cross & state.eq(label) & frame["target_year"].isin(block_years)).sum())
                for block, block_years in blocks.items()
            }
            for label in ["CROSS_CLOSE_ABOVE", "CROSS_CLOSE_EQUAL", "CROSS_CLOSE_BELOW"]
        },
        "remaining_horizon_counts": {
            str(horizon): int((cross & remaining.ge(horizon)).sum())
            for horizon in spec["event"]["remaining_bar_horizons"]
        },
        "remaining60_by_year": {
            str(year): int((cross & remaining.ge(60) & frame["target_year"].eq(year)).sum())
            for year in years
        },
        "remaining60_by_block": {
            block: int((cross & remaining.ge(60) & frame["target_year"].isin(block_years)).sum())
            for block, block_years in blocks.items()
        },
        "close_loss_total": int((cross & frame[f"{prefix}_close_loss"].astype(bool)).sum()),
        "reacquired_total": int(reacquired.sum()),
        "reacquired_by_year": {
            str(year): int((reacquired & frame["target_year"].eq(year)).sum()) for year in years
        },
        "reacquired_by_block": {
            block: int((reacquired & frame["target_year"].isin(block_years)).sum())
            for block, block_years in blocks.items()
        },
    }
    first = pd.to_numeric(frame.loc[cross, f"{prefix}_first_cross_index"], errors="raise")
    rem = remaining.loc[cross]
    result["first_cross_index_distribution"] = {
        "minimum": int(first.min()) if len(first) else None,
        "median": float(first.median()) if len(first) else None,
        "maximum": int(first.max()) if len(first) else None,
    }
    result["remaining_bars_distribution"] = {
        "minimum": int(rem.min()) if len(rem) else None,
        "median": float(rem.median()) if len(rem) else None,
        "maximum": int(rem.max()) if len(rem) else None,
    }
    return result


def evaluate_count_gates(stats: dict[str, dict[str, Any]], spec: dict[str, Any]) -> dict[str, Any]:
    primary = stats["L20_CONTINUOUS"]
    gate = spec["count_gates"]["primary"]
    above = "CROSS_CLOSE_ABOVE"
    below = "CROSS_CLOSE_BELOW"
    primary_checks = {
        "crossings_total": primary["crossings_total"] >= gate["crossings_total"],
        "crossings_blocks": min(primary["crossings_by_block"].values())
        >= gate["crossings_each_block"],
        "crossings_years": min(primary["crossings_by_year"].values())
        >= gate["crossings_each_year"],
        "close_above_total": primary["closing_states"][above] >= gate["close_above_total"],
        "close_below_total": primary["closing_states"][below] >= gate["close_below_total"],
        "close_arms_blocks": min(
            *primary["closing_states_by_block"][above].values(),
            *primary["closing_states_by_block"][below].values(),
        )
        >= gate["each_close_arm_each_block"],
        "close_arms_years": min(
            *primary["closing_states_by_year"][above].values(),
            *primary["closing_states_by_year"][below].values(),
        )
        >= gate["each_close_arm_each_year"],
        "remaining60_total": primary["remaining_horizon_counts"]["60"] >= gate["remaining60_total"],
        "remaining60_blocks": min(primary["remaining60_by_block"].values())
        >= gate["remaining60_each_block"],
        "remaining60_years": min(primary["remaining60_by_year"].values())
        >= gate["remaining60_each_year"],
        "views_total": min(primary["crossings_by_view"].values()) >= gate["each_view_total"],
        "view_years": min(primary["crossings_by_view_year"].values())
        >= gate["each_view_each_year"],
    }
    neighbor_gate = spec["count_gates"]["each_neighbor_or_auction"]
    neighbor_checks: dict[str, dict[str, bool]] = {}
    for name in ["L10_CONTINUOUS", "L40_CONTINUOUS", "L20_AUCTION"]:
        item = stats[name]
        neighbor_checks[name] = {
            "crossings_total": item["crossings_total"] >= neighbor_gate["crossings_total"],
            "crossings_blocks": min(item["crossings_by_block"].values())
            >= neighbor_gate["crossings_each_block"],
            "crossings_years": min(item["crossings_by_year"].values())
            >= neighbor_gate["crossings_each_year"],
            "close_above_total": item["closing_states"][above]
            >= neighbor_gate["close_above_total"],
            "close_below_total": item["closing_states"][below]
            >= neighbor_gate["close_below_total"],
        }
    reacq_gate = spec["count_gates"]["conditional_reacquisition"]
    reacquisition_checks = {
        "total": primary["reacquired_total"] >= reacq_gate["total"],
        "blocks": min(primary["reacquired_by_block"].values()) >= reacq_gate["each_block"],
        "years": min(primary["reacquired_by_year"].values()) >= reacq_gate["each_year"],
    }
    primary_pass = all(primary_checks.values())
    neighbor_pass = all(all(item.values()) for item in neighbor_checks.values())
    reacquisition_pass = all(reacquisition_checks.values())
    return {
        "primary_checks": primary_checks,
        "neighbor_checks": neighbor_checks,
        "conditional_reacquisition_checks": reacquisition_checks,
        "primary_pass": primary_pass,
        "neighbors_pass": neighbor_pass,
        "session_representation_domain_pass": primary_pass and neighbor_pass,
        "reacquisition_domain_pass": reacquisition_pass,
    }


def _build_count_audit(
    frame: pd.DataFrame, stats: dict[str, dict[str, Any]], spec: dict[str, Any]
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    for definition, item in stats.items():
        records.append(
            {
                "definition": definition,
                "group_type": "OVERALL",
                "group_value": "ALL",
                "crossings": item["crossings_total"],
                "close_above": item["closing_states"]["CROSS_CLOSE_ABOVE"],
                "close_equal": item["closing_states"]["CROSS_CLOSE_EQUAL"],
                "close_below": item["closing_states"]["CROSS_CLOSE_BELOW"],
                "remaining60": item["remaining_horizon_counts"]["60"],
                "reacquired": item["reacquired_total"],
            }
        )
        for group_type, field in [
            ("YEAR", "crossings_by_year"),
            ("BLOCK", "crossings_by_block"),
            ("VIEW", "crossings_by_view"),
            ("VIEW_YEAR", "crossings_by_view_year"),
        ]:
            for value, count in item[field].items():
                records.append(
                    {
                        "definition": definition,
                        "group_type": group_type,
                        "group_value": value,
                        "crossings": count,
                        "close_above": None,
                        "close_equal": None,
                        "close_below": None,
                        "remaining60": None,
                        "reacquired": None,
                    }
                )
    primary_cross = frame["l20_continuous_cross"].astype(bool)
    sequence_counts = frame.assign(_cross=primary_cross).groupby("sequence_id")["_cross"].sum()
    sequence_bins = {
        "ZERO": int(sequence_counts.eq(0).sum()),
        "ONE": int(sequence_counts.eq(1).sum()),
        "TWO_OR_MORE": int(sequence_counts.ge(2).sum()),
    }
    for value, count in sequence_bins.items():
        records.append(
            {
                "definition": "L20_CONTINUOUS",
                "group_type": "SEQUENCE_CROSS_DAYS",
                "group_value": value,
                "crossings": count,
                "close_above": None,
                "close_equal": None,
                "close_below": None,
                "remaining60": None,
                "reacquired": None,
            }
        )
    output = pd.DataFrame(records)
    return output.sort_values(["definition", "group_type", "group_value"]).reset_index(drop=True)


def _scalar_reconstruction(
    candidates: list[dict[str, Any]], history: pd.DataFrame
) -> list[dict[str, Any]]:
    if len(candidates) != 5:
        raise BreakoutDataError("insufficient scalar reconstruction cases")
    results: list[dict[str, Any]] = []
    for case in candidates:
        rows = history.loc[
            history["symbol"].eq(case["symbol"])
            & history["target_date"].eq(case["trade_date"])
            & history["lag"].le(20)
        ].sort_values("lag")
        if len(rows) != 20:
            raise BreakoutDataError("scalar prior-20 row count changed")
        scalar_highs: list[float] = []
        for row in rows.itertuples(index=False):
            scalar_highs.append(float(row.coordinate_close) * float(row.high) / float(row.close))
        level = max(scalar_highs)
        if level != case["vector_level"]:
            raise BreakoutDataError("scalar prior-high coordinate disagreement")
        mapped_high = case["mapped_high"]
        mapped_close = case["mapped_close"]
        first: int | None = None
        for index in range(1, len(mapped_high)):
            if float(mapped_high[index]) > level:
                first = index - 1
                break
        if first is None:
            raise BreakoutDataError("scalar selected case did not cross")
        final_close = float(mapped_close[-1])
        state = (
            "CROSS_CLOSE_ABOVE"
            if final_close > level
            else "CROSS_CLOSE_BELOW"
            if final_close < level
            else "CROSS_CLOSE_EQUAL"
        )
        remaining = 240 - first - 1
        if (
            first != case["vector_first_cross_index"]
            or state != case["vector_closing_state"]
            or remaining != case["vector_remaining_bars"]
        ):
            raise BreakoutDataError("scalar event reconstruction disagreement")
        results.append(
            {
                "selection_hash": case["selection_hash"],
                "symbol": case["symbol"],
                "trade_date": str(case["trade_date"].date()),
                "resistance_high20": level,
                "first_cross_index": first,
                "closing_state": state,
                "remaining_bars": remaining,
                "exact_match": True,
            }
        )
    return results


def _render_report(result: dict[str, Any]) -> str:
    primary = result["event_support"]["L20_CONTINUOUS"]
    gates = result["gate_evaluation"]
    population = result["population"]
    states = primary["closing_states"]
    diagnostics = result["diagnostics"]
    hashes = result["hashes"]
    return (
        "\n".join(
            [
                "# MKT-BREAKOUT-DATA-001 prior-high event-support audit",
                "",
                "## Result",
                "",
                f"- Status: `{result['status']}`",
                "- Immutable sequences/cohort rows/unique sessions: "
                f"{population['sequences']:,}/{population['cohort_rows']:,}/"
                f"{population['unique_sessions']:,}.",
                f"- Primary L20 continuous crossings: {primary['crossings_total']:,}; "
                f"unique physical sessions: {primary['crossings_unique_sessions']:,}.",
                "- Closing states above/equal/below: "
                f"{states['CROSS_CLOSE_ABOVE']:,}/{states['CROSS_CLOSE_EQUAL']:,}/"
                f"{states['CROSS_CLOSE_BELOW']:,}.",
                "- Crossings with 60 remaining bars: "
                f"{primary['remaining_horizon_counts']['60']:,}; "
                f"loss-and-reacquisition sessions: {primary['reacquired_total']:,}.",
                "- Session-domain primary/neighbor pass: "
                f"{gates['primary_pass']}/{gates['neighbors_pass']}; conditional "
                f"reacquisition pass: {gates['reacquisition_domain_pass']}.",
                f"- Auction-only L20 crossings: {diagnostics['auction_only_crossings']:,}; "
                "up/down-limit contacts: "
                f"{diagnostics['up_limit_contacts']:,}/"
                f"{diagnostics['down_limit_contacts']:,}.",
                "- Five independently selected scalar cases reproduce the exact "
                "prior-high, first crossing, closing state, and censoring count.",
                "- This count-only experiment computes no continuation, depth, dwell, "
                "VWAP, trajectory, outcome, prediction, habitat, or strategy estimate.",
                "",
                "## Reproducibility",
                "",
                f"- Spec SHA-256: `{hashes['spec_sha256']}`",
                f"- Runner SHA-256: `{hashes['runner_sha256']}`",
                f"- Coordinate/event audit SHA-256: `{hashes['coordinate_event_audit_sha256']}`",
                f"- Count audit SHA-256: `{hashes['count_audit_sha256']}`",
            ]
        )
        + "\n"
    )


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    disk = psutil.disk_usage(ROOT)
    if disk.free / disk.total < spec["resource_budget"]["filesystem_headroom_fraction"]:
        raise BreakoutDataError("filesystem headroom floor breached")
    _resource_guard(spec, started)
    base._verify_registry_assets(spec)
    partitions = base.bind_partitions(spec, verify_content=verify_partition_content)
    sample = _load_parent_sample(spec)

    with tempfile.TemporaryDirectory(prefix="mkt-breakout-data-001-") as temp_name:
        temp_dir = Path(temp_name)
        connection = _create_capped_daily_coordinate(spec, partitions["cy006"], temp_dir)
        try:
            coordinates, history = _target_coordinates_and_history(connection, sample)
            equivalence = _verify_parent_coordinate_equivalence(spec, coordinates)
            if (
                _directory_bytes(temp_dir)
                > spec["resource_budget"]["temporary_spill_ceiling_gib"] * 2**30
            ):
                raise BreakoutDataError("post-query disposable spill ceiling breached")
        finally:
            connection.close()
    gc.collect()
    _resource_guard(spec, started)

    event_audit, scalar_candidates = _audit_minute_events(
        spec, sample, coordinates, partitions, started
    )
    scalar_cases = _scalar_reconstruction(scalar_candidates, history)
    del history
    gc.collect()

    stats = {name: _definition_stats(event_audit, name, spec) for name in DEFINITIONS}
    gate_evaluation = evaluate_count_gates(stats, spec)
    count_audit = _build_count_audit(event_audit, stats, spec)
    sequence_cross_counts = (
        event_audit.assign(_cross=event_audit["l20_continuous_cross"].astype(bool))
        .groupby("sequence_id")["_cross"]
        .sum()
    )

    coordinate_out = event_audit.copy()
    coordinate_out["trade_date"] = coordinate_out["trade_date"].dt.strftime("%Y-%m-%d")
    coordinate_out.to_csv(
        COORDINATE_EVENT_PATH,
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )
    count_audit.to_csv(COUNT_AUDIT_PATH, index=False, lineterminator="\n")

    domain_pass = gate_evaluation["session_representation_domain_pass"]
    reacquisition_pass = gate_evaluation["reacquisition_domain_pass"]
    if not domain_pass:
        status = "COMPLETE_EVENT_SAMPLE_INADEQUATE"
    elif reacquisition_pass:
        status = "COMPLETE_EVENT_SUPPORT_PASS"
    else:
        status = "COMPLETE_EVENT_SUPPORT_PASS_REACQUISITION_DEFERRED"
    unique = event_audit.drop_duplicates(["symbol", "trade_date"])
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "population": {
            "sequences": int(event_audit["sequence_id"].nunique()),
            "cohort_rows": len(event_audit),
            "unique_sessions": len(unique),
            "raw_minute_rows_read": spec["resource_budget"]["planned_raw_minute_rows"],
        },
        "parent_coordinate_equivalence": equivalence,
        "event_support": stats,
        "gate_evaluation": gate_evaluation,
        "diagnostics": {
            "auction_only_crossings": int(event_audit["l20_auction_only_cross"].sum()),
            "up_limit_contacts": int(event_audit["up_limit_contact"].sum()),
            "down_limit_contacts": int(event_audit["down_limit_contact"].sum()),
            "supported_action_unique_sessions": int(unique["corporate_action_count"].gt(0).sum()),
            "sequence_cross_day_counts": {
                "zero": int(sequence_cross_counts.eq(0).sum()),
                "one": int(sequence_cross_counts.eq(1).sum()),
                "two_or_more": int(sequence_cross_counts.ge(2).sum()),
            },
        },
        "scalar_reconstruction": scalar_cases,
        "resource_checks": {
            "daily_memory_limit_gib": 1.5,
            "disposable_spill_below_ceiling": True,
            "raw_rows_exact": True,
            "peak_rss_below_ceiling": True,
            "memory_headroom_above_floor": True,
            "wall_clock_below_ceiling": True,
            "filesystem_headroom_preserved": True,
        },
        "representation_claim": "NONE",
        "process_estimates_constructed": False,
        "post_cross_magnitudes_constructed": False,
        "prediction_or_usefulness_claim": "NONE",
        "strategy_or_outcome_fields_read": [],
        "future_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "coordinate_event_audit_sha256": sha256_file(COORDINATE_EVENT_PATH),
            "count_audit_sha256": sha256_file(COUNT_AUDIT_PATH),
            "bound_inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable_bytes = sum(
        path.stat().st_size
        for path in [COORDINATE_EVENT_PATH, COUNT_AUDIT_PATH, RESULT_PATH, REPORT_PATH]
    )
    if durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise BreakoutDataError("durable output ceiling breached")
    _resource_guard(spec, started)
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "primary": completed["event_support"]["L20_CONTINUOUS"],
                "gates": completed["gate_evaluation"],
            },
            indent=2,
            sort_keys=True,
        )
    )
