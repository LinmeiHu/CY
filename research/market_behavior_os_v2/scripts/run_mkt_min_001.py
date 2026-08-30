#!/usr/bin/env python3
"""Construct staged full-cross-section MKT-MIN-001 daily minute state."""

from __future__ import annotations

import argparse
import gc
import hashlib
import importlib.util
import json
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
ADAPTER_PATH = PROGRAM / "scripts/vectorized_market_minute_adapter.py"
MODULE_SPEC = importlib.util.spec_from_file_location("vectorized_market_minute_adapter", ADAPTER_PATH)
assert MODULE_SPEC and MODULE_SPEC.loader
adapter = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(adapter)


REPRESENTATIVE_PANEL = PROGRAM / "artifacts/MKT-MIN-001_representative_daily_panel.csv"
REPRESENTATIVE_RESULT = PROGRAM / "artifacts/MKT-MIN-001_representative_result.json"
DAILY_PANEL = PROGRAM / "artifacts/MKT-MIN-001_daily_market_panel.csv"

VIEWS = ("ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD")
DENOMINATORS = ("ALL_STATUS", "NON_ST")
MINIMUM_COUNTS = {"ALL_A": 1000, "SH_A": 400, "SZ_A": 400, "CHINEXT_BOARD": 200}
PERCENTILES = (("p40", 0.4), ("median", 0.5), ("p60", 0.6))
RAM_FLOOR_BYTES = 8 * 1024**3
RSS_CEILING_BYTES = 3 * 1024**3


class MarketMinuteConstructionError(RuntimeError):
    """Raised on a frozen construction, identity, or resource violation."""


def _true(values: pd.Series) -> np.ndarray:
    return values.astype("boolean").fillna(False).to_numpy(dtype=bool)


def _read_calendar(spec: dict[str, Any]) -> pd.DatetimeIndex:
    path = adapter._resolve(spec["inputs"]["calendar"]["path"])
    values = pq.read_table(path, columns=["trade_date"]).to_pandas().trade_date
    values = pd.to_datetime(values, errors="raise").drop_duplicates().sort_values()
    window = spec["construction_window"]
    values = values[(values >= window["start"]) & (values <= window["end"])]
    if len(values) != int(window["exchange_sessions"]):
        raise MarketMinuteConstructionError("calendar session count changed")
    return pd.DatetimeIndex(values)


def _load_year_context(
    cy006_path: Path, cy008_daily_path: Path
) -> tuple[pd.DataFrame, dict[str, int]]:
    key_columns = ["symbol", "trade_date"]
    cy6_columns = [
        *key_columns,
        "hard_valid",
        "bar_valid",
        "trading_state_valid",
        "corporate_action_valid",
        "market_rule_valid",
        "historical_identity_valid",
        "corporate_action_blocking",
        "corporate_action_count",
        "available_at",
        "decision_at",
        "close",
        "volume",
        "trade_status",
        "current_day_data_tradable",
        "is_st",
        "snapshot_id",
    ]
    cy8_columns = [
        *key_columns,
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
        "snapshot_id",
        "daily_snapshot_id",
    ]
    cy6 = pq.read_table(cy006_path, columns=cy6_columns, use_threads=False).to_pandas()
    cy8 = pq.read_table(cy008_daily_path, columns=cy8_columns, use_threads=False).to_pandas()
    cy6["trade_date"] = pd.to_datetime(cy6.trade_date, errors="raise")
    cy8["trade_date"] = pd.to_datetime(cy8.trade_date, errors="raise")
    if cy6.duplicated(key_columns).any() or cy8.duplicated(key_columns).any():
        raise MarketMinuteConstructionError("duplicate daily causal context key")

    cy6 = cy6.rename(
        columns={
            "available_at": "cy6_available_at",
            "snapshot_id": "cy6_snapshot_id",
            "hard_valid": "cy6_hard_valid",
        }
    )
    cy8 = cy8.rename(
        columns={
            "available_at": "cy8_available_at",
            "snapshot_id": "cy8_snapshot_id",
            "hard_valid": "cy8_hard_valid",
        }
    )
    context = cy6.merge(
        cy8, on=key_columns, how="left", validate="one_to_one", indicator=True
    )
    matched = context._merge.eq("both")
    snapshot_match = context.daily_snapshot_id.eq(context.cy6_snapshot_id)
    if not snapshot_match.loc[matched].all():
        raise MarketMinuteConstructionError("CY-006/CY-008 snapshot binding failed")

    context["daily_eligible"] = (
        _true(context.cy6_hard_valid)
        & _true(context.bar_valid)
        & _true(context.trading_state_valid)
        & _true(context.corporate_action_valid)
        & _true(context.market_rule_valid)
        & _true(context.historical_identity_valid)
        & ~_true(context.corporate_action_blocking)
        & (
            pd.to_datetime(context.cy6_available_at, utc=True)
            <= pd.to_datetime(context.decision_at, utc=True)
        )
        & pd.to_numeric(context.close, errors="coerce").gt(0)
        & pd.to_numeric(context.volume, errors="coerce").gt(0)
        & pd.to_numeric(context.trade_status, errors="coerce").eq(1)
        & _true(context.current_day_data_tradable)
    )
    expected_available = context.trade_date + pd.Timedelta(hours=15, minutes=30)
    context["minute_eligible"] = (
        matched
        & pd.to_datetime(context.cy8_available_at).eq(expected_available)
        & pd.to_numeric(context.minute_count, errors="coerce").eq(241)
        & pd.to_numeric(context.distinct_minute_count, errors="coerce").eq(241)
        & pd.to_numeric(context.source_resolution_minutes, errors="coerce").eq(1)
        & _true(context.session_complete)
        & _true(context.ohlc_valid)
        & _true(context.unit_valid)
        & _true(context.volume_reconciled)
        & _true(context.amount_reconciled)
        & _true(context.daily_hard_valid)
        & _true(context.cy8_hard_valid)
        & snapshot_match.fillna(False)
    )
    context = context.drop(columns=["_merge"])
    context = context.sort_values(key_columns).reset_index(drop=True)
    audit = {
        "cy006_rows": int(len(cy6)),
        "cy008_rows": int(len(cy8)),
        "matched_rows": int(matched.sum()),
        "daily_eligible_rows": int(context.daily_eligible.sum()),
        "minute_eligible_rows": int(context.minute_eligible.sum()),
    }
    return context, audit


def _view_masks(symbols: pd.Series) -> dict[str, np.ndarray]:
    text = symbols.astype(str)
    sh = text.str.endswith(".SH").to_numpy()
    sz = text.str.endswith(".SZ").to_numpy()
    chinext = (sz & text.str[:3].isin(["300", "301"]).to_numpy())
    return {"ALL_A": sh | sz, "SH_A": sh, "SZ_A": sz, "CHINEXT_BOARD": chinext}


def _lineage_hash(values: pd.Series) -> str:
    payload = "\n".join(sorted(values.dropna().astype(str))).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def aggregate_market_date(
    trade_date: pd.Timestamp,
    descriptors: pd.DataFrame,
    context: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    if context.empty:
        raise MarketMinuteConstructionError(f"missing daily context: {trade_date.date()}")
    descriptor_columns = list(adapter.DESCRIPTOR_COLUMNS)
    descriptor_frame = descriptors[["symbol", *descriptor_columns]].copy()
    if descriptor_frame.duplicated("symbol").any():
        raise MarketMinuteConstructionError("duplicate vector descriptor symbol/date")
    merged = context.merge(descriptor_frame, on="symbol", how="left", validate="one_to_one")
    descriptor_finite = np.isfinite(
        merged[descriptor_columns].to_numpy(dtype=float, na_value=np.nan)
    ).all(axis=1)
    merged["descriptor_eligible"] = (
        merged.daily_eligible.to_numpy(bool)
        & merged.minute_eligible.to_numpy(bool)
        & descriptor_finite
    )
    masks = _view_masks(merged.symbol)
    rows: list[dict[str, Any]] = []
    eligible_key_frames: list[pd.DataFrame] = []
    for view in VIEWS:
        view_mask = masks[view]
        for denominator in DENOMINATORS:
            denominator_mask = view_mask.copy()
            if denominator == "NON_ST":
                denominator_mask &= ~merged.is_st.astype("boolean").fillna(True).to_numpy(dtype=bool)
            population_mask = denominator_mask & merged.daily_eligible.to_numpy(bool)
            final_mask = denominator_mask & merged.descriptor_eligible.to_numpy(bool)
            population_count = int(population_mask.sum())
            descriptor_count = int(final_mask.sum())
            coverage = descriptor_count / population_count if population_count else 0.0
            hard_valid = (
                population_count >= MINIMUM_COUNTS[view]
                and descriptor_count >= MINIMUM_COUNTS[view]
                and coverage >= 0.95
            )
            row: dict[str, Any] = {
                "trade_date": trade_date.strftime("%Y-%m-%d"),
                "available_at": (trade_date + pd.Timedelta(hours=15, minutes=30)).isoformat(),
                "market_view": view,
                "denominator": denominator,
                "daily_population_count": population_count,
                "descriptor_count": descriptor_count,
                "descriptor_coverage": coverage,
                "hard_valid": hard_valid,
                "cy6_snapshot_sha256": _lineage_hash(
                    merged.loc[final_mask, "cy6_snapshot_id"]
                ),
                "cy8_snapshot_sha256": _lineage_hash(
                    merged.loc[final_mask, "cy8_snapshot_id"]
                ),
            }
            if hard_valid:
                values = merged.loc[final_mask, descriptor_columns].to_numpy(float)
                quantiles = np.quantile(
                    values, [value for _, value in PERCENTILES], axis=0, method="linear"
                )
                for percentile_index, (label, _) in enumerate(PERCENTILES):
                    for descriptor_index, name in enumerate(descriptor_columns):
                        row[f"{name}__{label}"] = float(
                            quantiles[percentile_index, descriptor_index]
                        )
                keys = merged.loc[final_mask, ["symbol"]].copy()
                keys["trade_date"] = trade_date
                eligible_key_frames.append(keys)
            else:
                for label, _ in PERCENTILES:
                    for name in descriptor_columns:
                        row[f"{name}__{label}"] = np.nan
            rows.append(row)
    eligible_keys = (
        pd.concat(eligible_key_frames, ignore_index=True)
        .drop_duplicates(["symbol", "trade_date"])
        if eligible_key_frames
        else pd.DataFrame(columns=["symbol", "trade_date"])
    )
    audit = {
        "context_rows": int(len(context)),
        "raw_descriptor_rows": int(len(descriptors)),
        "daily_eligible_rows": int(merged.daily_eligible.sum()),
        "final_descriptor_rows": int(merged.descriptor_eligible.sum()),
    }
    return pd.DataFrame(rows), eligible_keys, audit


def _compare_opening(
    actual_frames: list[pd.DataFrame],
    eligible_keys: pd.DataFrame,
    execution_path: Path,
) -> dict[str, Any]:
    actual = pd.concat(actual_frames, ignore_index=True).merge(
        eligible_keys.drop_duplicates(), on=["symbol", "trade_date"], validate="many_to_one"
    )
    expected = adapter._opening_reference(execution_path, eligible_keys)
    key_columns = ["symbol", "trade_date", "window_index"]
    actual = actual.sort_values(key_columns).reset_index(drop=True)
    expected = expected.sort_values(key_columns).reset_index(drop=True)
    actual_keys = actual[key_columns].copy()
    expected_keys = expected[key_columns].copy()
    actual_keys["window_index"] = actual_keys.window_index.astype(int)
    expected_keys["window_index"] = expected_keys.window_index.astype(int)
    if not actual_keys.equals(expected_keys):
        raise MarketMinuteConstructionError("representative opening keys disagree")
    numeric = list(adapter.FLOAT_COLUMNS)
    observed = actual[numeric].to_numpy(float)
    reference = expected[numeric].to_numpy(float)
    relative = np.abs(observed - reference) / np.maximum(1.0, np.abs(reference))
    if np.any(relative > 1e-12):
        row, column = np.argwhere(relative > 1e-12)[0]
        raise MarketMinuteConstructionError(
            f"representative opening mismatch: {numeric[column]} relative={relative[row, column]!r}"
        )
    return {
        "opening_rows": int(len(actual)),
        "opening_sessions": int(actual[["symbol", "trade_date"]].drop_duplicates().shape[0]),
        "maximum_relative_opening_difference": float(relative.max()),
        "opening_sha256": adapter.stable_frame_sha256(
            actual, [*key_columns, *numeric]
        ),
    }


def _check_resources() -> None:
    available = psutil.virtual_memory().available
    if available < RAM_FLOOR_BYTES:
        raise MarketMinuteConstructionError(
            f"system RAM headroom below frozen floor: {available}"
        )
    rss = adapter._max_rss_bytes()
    if rss > RSS_CEILING_BYTES:
        raise MarketMinuteConstructionError(f"process RSS exceeded frozen ceiling: {rss}")


def run(stage: str) -> dict[str, Any]:
    if stage not in {"representative", "required"}:
        raise MarketMinuteConstructionError(f"unsupported construction stage: {stage}")
    spec = adapter.load_frozen_spec()
    calendar = _read_calendar(spec)
    if stage == "representative":
        selected_dates = pd.DatetimeIndex(pd.to_datetime(spec["validation_ladder"]["representative"]))
    else:
        selected_dates = calendar
    if not selected_dates.isin(calendar).all():
        raise MarketMinuteConstructionError("selected date is outside the frozen calendar")
    years = sorted(selected_dates.year.unique().astype(int).tolist())
    qd_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy6_required = [f"partition_year={year}/data_0.parquet" for year in years]
    cy8_daily_required = [f"daily/partition_year={year}/data_0.parquet" for year in years]
    cy8_required = list(cy8_daily_required)
    if stage == "representative":
        cy8_required += [f"execution_5m/partition_year={year}/data_0.parquet" for year in years]
    qd_inventory = adapter._resolve(spec["inputs"]["qd004_inventory"]["path"])
    cy6_inventory = adapter._resolve(spec["inputs"]["cy006_inventory"]["path"])
    cy8_inventory = adapter._resolve(spec["inputs"]["cy008_inventory"]["path"])
    qd = adapter.inventory_files(qd_inventory, qd_required)
    cy6 = adapter.inventory_files(cy6_inventory, cy6_required)
    cy8 = adapter.inventory_files(cy8_inventory, cy8_required)
    adapter.verify_inventory_hashes(qd_inventory, qd_required)
    adapter.verify_inventory_hashes(cy6_inventory, cy6_required)
    adapter.verify_inventory_hashes(cy8_inventory, cy8_required)

    started = time.perf_counter()
    panel_frames: list[pd.DataFrame] = []
    opening_frames: list[pd.DataFrame] = []
    eligible_key_frames: list[pd.DataFrame] = []
    raw_audits: list[dict[str, Any]] = []
    market_audits: list[dict[str, int]] = []
    context_audits: list[dict[str, int]] = []
    by_date_seconds: dict[str, float] = {}
    for year in years:
        _check_resources()
        context, context_audit = _load_year_context(
            cy6[f"partition_year={year}/data_0.parquet"],
            cy8[f"daily/partition_year={year}/data_0.parquet"],
        )
        context_audits.append(context_audit)
        year_dates = selected_dates[selected_dates.year == year]
        for trade_date in year_dates:
            _check_resources()
            date_started = time.perf_counter()
            raw = adapter.read_raw_table(
                qd[f"bars/{year}_day_parquet_none.parquet"], [trade_date.date()]
            )
            descriptors, opening, raw_audit = adapter.vectorized_session_descriptors(raw)
            day_context = context.loc[context.trade_date.eq(trade_date)].copy()
            day_panel, eligible_keys, market_audit = aggregate_market_date(
                trade_date, descriptors, day_context
            )
            if not day_panel.hard_valid.all():
                invalid = day_panel.loc[~day_panel.hard_valid, ["market_view", "denominator"]]
                raise MarketMinuteConstructionError(
                    f"daily market representation failed: {trade_date.date()}: {invalid.to_dict('records')}"
                )
            panel_frames.append(day_panel)
            if stage == "representative":
                opening_frames.append(opening)
                eligible_key_frames.append(eligible_keys)
            raw_audits.append(raw_audit)
            market_audits.append(market_audit)
            by_date_seconds[trade_date.strftime("%Y-%m-%d")] = time.perf_counter() - date_started
            del raw, descriptors, opening, day_context, day_panel, eligible_keys
            gc.collect()
        del context
        gc.collect()

    panel = pd.concat(panel_frames, ignore_index=True).sort_values(
        ["trade_date", "market_view", "denominator"]
    ).reset_index(drop=True)
    expected_rows = len(selected_dates) * len(VIEWS) * len(DENOMINATORS)
    if len(panel) != expected_rows or panel.duplicated(
        ["trade_date", "market_view", "denominator"]
    ).any():
        raise MarketMinuteConstructionError("daily market panel population changed")
    output_path = REPRESENTATIVE_PANEL if stage == "representative" else DAILY_PANEL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(output_path, index=False, float_format="%.12g", lineterminator="\n")
    panel_sha256 = adapter.sha256_file(output_path)

    opening_audit: dict[str, Any] | None = None
    if stage == "representative":
        if len(years) != 1:
            raise MarketMinuteConstructionError("representative opening audit expects one year")
        opening_audit = _compare_opening(
            opening_frames,
            pd.concat(eligible_key_frames, ignore_index=True).drop_duplicates(),
            cy8[f"execution_5m/partition_year={years[0]}/data_0.parquet"],
        )

    wall_seconds = time.perf_counter() - started
    raw_rows = int(sum(item["raw_rows"] for item in raw_audits))
    result: dict[str, Any] = {
        "experiment_id": "MKT-MIN-001",
        "stage": stage,
        "decision": "PASS_REPRESENTATIVE_SCALE" if stage == "representative" else "PASS_REQUIRED_DAILY_SCALE",
        "dates": int(len(selected_dates)),
        "first_date": selected_dates.min().strftime("%Y-%m-%d"),
        "last_date": selected_dates.max().strftime("%Y-%m-%d"),
        "daily_panel_rows": int(len(panel)),
        "raw_rows": raw_rows,
        "raw_descriptor_sessions": int(sum(item["descriptor_sessions"] for item in raw_audits)),
        "daily_eligible_rows": int(sum(item["daily_eligible_rows"] for item in market_audits)),
        "final_descriptor_rows": int(sum(item["final_descriptor_rows"] for item in market_audits)),
        "maximum_five_minute_volume_conservation_difference": float(max(item["maximum_five_minute_volume_conservation_difference"] for item in raw_audits)),
        "maximum_five_minute_amount_conservation_difference": float(max(item["maximum_five_minute_amount_conservation_difference"] for item in raw_audits)),
        "opening_audit": opening_audit,
        "panel_sha256": panel_sha256,
        "wall_seconds": wall_seconds,
        "rows_per_second": raw_rows / wall_seconds,
        "median_date_seconds": float(np.median(list(by_date_seconds.values()))),
        "maximum_date_seconds": float(np.max(list(by_date_seconds.values()))),
        "peak_rss_bytes": adapter._max_rss_bytes(),
        "minimum_observed_descriptor_coverage": float(panel.descriptor_coverage.min()),
        "minimum_observed_cross_section": int(panel.descriptor_count.min()),
        "context_audits": context_audits,
        "spec_sha256": adapter.sha256_file(adapter.SPEC_PATH),
        "adapter_sha256": adapter.sha256_file(ADAPTER_PATH),
    }
    if result["peak_rss_bytes"] > RSS_CEILING_BYTES:
        raise MarketMinuteConstructionError("completed stage exceeded frozen RSS ceiling")
    if stage == "representative":
        REPRESENTATIVE_RESULT.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["representative", "required"], required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.stage), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
