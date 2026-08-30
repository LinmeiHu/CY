#!/usr/bin/env python3
"""Audit the frozen larger sample for objective-recovery temporal research."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import gc
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DYN-DATA-001_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-001_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-001_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-001_population_audit.csv"
SUPPORT_COUNT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-001_support_count_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DYN-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DYN-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "cb6559ee585eef7fc147c1036bbd0cc81d4a8634b8d2aca339cfa10358a9b02d"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


data003 = _load_module(
    "run_mkt_support_data_003_parent_dyn",
    PROGRAM / "scripts/run_mkt_support_data_003.py",
)
support001 = _load_module(
    "run_mkt_support_001_parent_dyn", PROGRAM / "scripts/run_mkt_support_001.py"
)
adapter = data003.adapter
sha256_file = data003.sha256_file
SupportDataError = data003.SupportDataError


class SupportTemporalSampleError(RuntimeError):
    """Fail-closed MKT-SUPPORT-DYN-DATA-001 error."""


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
        raise SupportTemporalSampleError("temporal-sample spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_NEW_RAW_MINUTE_ACCESS"
        or spec["outcome_access"] is not False
    ):
        raise SupportTemporalSampleError("temporal-sample activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportTemporalSampleError(f"input identity mismatch: {name}")
    if spec["sample"] != {
        "market_views": ["ALL_A", "SH_A", "SZ_A", "CHINEXT_BOARD"],
        "sequences_per_block_view": 10,
        "selection_order": "SHA256(MKT-SUPPORT-DYN-DATA-001|MARKET|year|block_id|market_view|symbol)",
        "selection_source": "registered calendar and CY-006 coordinate eligibility only",
        "expected_sequences": 1920,
        "expected_cohort_rows": 9600,
        "expected_unique_security_sessions": 9575,
        "minimum_complete_candidates_any_block_view": 625,
        "expected_selected_supported_action_unique_sessions": 38,
        "minimum_selected_supported_action_sessions_each_year": 3,
        "cohort_identity_preserved_on_duplicate_security_date": True,
    }:
        raise SupportTemporalSampleError("frozen sample identity changed")
    base = data003._load_spec()
    data_result = json.loads(_resolve(spec["inputs"]["data003_result"]["path"]).read_text())
    support_result = json.loads(_resolve(spec["inputs"]["support_result"]["path"]).read_text())
    geometry_result = json.loads(_resolve(spec["inputs"]["geometry_result"]["path"]).read_text())
    if data_result["status"] != "COMPLETE_DATA_CONTRACT_PASS" or data_result["cy011_read"]:
        raise SupportTemporalSampleError("003 data-contract activation changed")
    if support_result["accepted_session_roles"] != [
        "signed_test_geometry",
        "recovery_speed",
        "recovery_amplitude",
        "recovery_volume_intensity",
    ]:
        raise SupportTemporalSampleError("support representation activation changed")
    if geometry_result["direct_roles"] != ["recovery_speed", "recovery_volume_intensity"]:
        raise SupportTemporalSampleError("support geometry activation changed")
    spec["_base_data_spec"] = base
    return spec


def _endpoint_positions(n: int) -> list[int]:
    if n < 16:
        raise SupportTemporalSampleError("calendar window too short")
    return [((2 * index + 1) * n) // 16 for index in range(8)]


def construct_calendar_blocks(spec: dict[str, Any]) -> pd.DataFrame:
    calendar = pd.read_parquet(
        _resolve(spec["inputs"]["calendar"]["path"]), columns=["trade_date"]
    )
    calendar["trade_date"] = pd.to_datetime(calendar["trade_date"], errors="raise")
    start = pd.Timestamp(spec["date_range"]["start"])
    end = pd.Timestamp(spec["date_range"]["end"])
    dates = sorted(
        calendar.loc[calendar["trade_date"].between(start, end), "trade_date"].drop_duplicates()
    )
    if (
        len(dates) != spec["date_range"]["exchange_sessions"]
        or dates[0] != start
        or dates[-1] != end
    ):
        raise SupportTemporalSampleError("calendar identity changed")
    date_to_position = {date: position for position, date in enumerate(dates)}
    records: list[dict[str, Any]] = []
    used: set[pd.Timestamp] = set()
    config = spec["calendar_blocks"]
    for year in spec["date_range"]["years"]:
        window_start = pd.Timestamp(f"{year}-{config['window_start_month_day']}")
        window_end = pd.Timestamp(f"{year}-{config['window_end_month_day']}")
        window = [date for date in dates if window_start <= date <= window_end]
        endpoints = [window[position] for position in _endpoint_positions(len(window))]
        expected = [pd.Timestamp(value) for value in config["endpoint_dates"][str(year)]]
        if endpoints != expected:
            raise SupportTemporalSampleError(f"calendar endpoint mismatch: {year}")
        for block_id, endpoint in enumerate(endpoints, start=1):
            endpoint_position = date_to_position[endpoint]
            block = dates[endpoint_position - 4 : endpoint_position + 1]
            if len(block) != 5 or len(set(block)) != 5 or used.intersection(block):
                raise SupportTemporalSampleError(f"calendar block overlap: {year}:{block_id}")
            used.update(block)
            for relative_day, trade_date in zip(range(-5, 0), block, strict=True):
                records.append(
                    {
                        "target_year": year,
                        "block_id": block_id,
                        "relative_day": relative_day,
                        "trade_date": trade_date,
                    }
                )
    output = pd.DataFrame(records)
    if len(output) != 240:
        raise SupportTemporalSampleError("calendar block row count changed")
    return output


def _selection_hash(year: int, block_id: int, market_view: str, symbol: str) -> str:
    payload = (
        f"MKT-SUPPORT-DYN-DATA-001|MARKET|{year}|{block_id:02d}|"
        f"{market_view}|{symbol}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _view_mask(symbols: pd.Series, market_view: str) -> pd.Series:
    symbols = symbols.astype(str)
    if market_view == "ALL_A":
        return symbols.str.endswith((".SH", ".SZ"))
    if market_view == "SH_A":
        return symbols.str.endswith(".SH")
    if market_view == "SZ_A":
        return symbols.str.endswith(".SZ")
    if market_view == "CHINEXT_BOARD":
        return symbols.str.endswith(".SZ") & symbols.str[:3].isin(["300", "301"])
    raise SupportTemporalSampleError(f"unknown market view: {market_view}")


def build_sample(
    connection: Any, spec: dict[str, Any], blocks: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, Any]]:
    connection.register("temporal_block_dates", blocks[["trade_date"]].drop_duplicates())
    eligible = connection.execute(
        """
        SELECT c.trade_date,c.symbol
        FROM coordinate c JOIN temporal_block_dates d USING(trade_date)
        WHERE c.coordinate_eligible
        ORDER BY c.trade_date,c.symbol
        """
    ).df()
    eligible["trade_date"] = pd.to_datetime(eligible["trade_date"], errors="raise")
    count = int(spec["sample"]["sequences_per_block_view"])
    records: list[dict[str, Any]] = []
    candidate_counts: list[int] = []
    for (year, block_id), block in blocks.groupby(["target_year", "block_id"], sort=True):
        dates = block.sort_values("relative_day")["trade_date"].tolist()
        cell = eligible.loc[eligible["trade_date"].isin(dates)]
        counts = cell.groupby("symbol", sort=False)["trade_date"].nunique()
        complete = pd.Series(counts.loc[counts == 5].index.astype(str), dtype=str)
        for market_view in spec["sample"]["market_views"]:
            candidates = complete.loc[_view_mask(complete, market_view)].tolist()
            candidate_counts.append(len(candidates))
            ordered = sorted(
                candidates,
                key=lambda symbol: (
                    _selection_hash(int(year), int(block_id), market_view, symbol),
                    symbol,
                ),
            )
            if len(ordered) < count:
                raise SupportTemporalSampleError(
                    f"insufficient complete candidates: {year}:{block_id}:{market_view}"
                )
            for rank, symbol in enumerate(ordered[:count], start=1):
                sequence_id = f"{year}|{int(block_id):02d}|{market_view}|{rank:02d}|{symbol}"
                for item in block.sort_values("relative_day").itertuples(index=False):
                    records.append(
                        {
                            "audit_id": f"MARKET|{sequence_id}|{pd.Timestamp(item.trade_date).date()}",
                            "sequence_id": sequence_id,
                            "cohort": "CALENDAR_DISTRIBUTED_MARKET_SEQUENCE",
                            "market_view": market_view,
                            "symbol": symbol,
                            "source_symbol": symbol[:6],
                            "trade_date": pd.Timestamp(item.trade_date),
                            "target_year": int(year),
                            "block_id": int(block_id),
                            "market_sequence_rank": rank,
                            "relative_day": int(item.relative_day),
                        }
                    )
    sample = pd.DataFrame(records).sort_values("audit_id").reset_index(drop=True)
    if len(sample) != spec["sample"]["expected_cohort_rows"]:
        raise SupportTemporalSampleError("sample cohort row count changed")
    if sample["sequence_id"].nunique() != spec["sample"]["expected_sequences"]:
        raise SupportTemporalSampleError("sample sequence count changed")
    unique_count = len(sample[["symbol", "trade_date"]].drop_duplicates())
    if unique_count != spec["sample"]["expected_unique_security_sessions"]:
        raise SupportTemporalSampleError("sample unique-session identity changed")
    if sample["audit_id"].duplicated().any():
        raise SupportTemporalSampleError("sample audit identity duplicated")
    minimum_candidates = min(candidate_counts)
    if minimum_candidates != spec["sample"]["minimum_complete_candidates_any_block_view"]:
        raise SupportTemporalSampleError("sample candidate margin changed")
    return sample, {
        "sequences": int(sample["sequence_id"].nunique()),
        "cohort_rows": len(sample),
        "unique_security_sessions": unique_count,
        "minimum_complete_candidates_any_block_view": minimum_candidates,
    }


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < budget["system_memory_headroom_floor_gib"] * 2**30:
        raise SupportTemporalSampleError("system memory headroom floor breached")
    if adapter._max_rss_bytes() > budget["peak_rss_ceiling_gib"] * 2**30:
        raise SupportTemporalSampleError("process RSS ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise SupportTemporalSampleError("wall-clock ceiling breached")


def audit_minutes_and_recovery(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
    started: float,
) -> pd.DataFrame:
    unique_targets = sample[
        ["symbol", "source_symbol", "trade_date", "target_year"]
    ].drop_duplicates()
    coordinate_index = coordinates.set_index(["symbol", "trade_date"])
    records: list[dict[str, Any]] = []
    for raw_year, targets in unique_targets.groupby("target_year", sort=True):
        _resource_guard(spec, started)
        year = int(raw_year)
        try:
            table = adapter.read_raw_table(
                partitions["qd004"][f"bars/{year}_day_parquet_none.parquet"],
                pd.to_datetime(targets["trade_date"]).dt.date,
                targets["source_symbol"].astype(str),
            )
            adapter.vectorized_session_descriptors(table)
        except adapter.VectorMinuteAdapterError as exc:
            raise SupportTemporalSampleError(str(exc)) from exc
        raw = table.to_pandas()
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        target_count = targets[["symbol", "trade_date"]].drop_duplicates().shape[0]
        if raw.groupby(["symbol", "trade_date"]).ngroups != target_count:
            raise SupportTemporalSampleError(f"raw target coverage changed: {year}")
        data003._read_and_validate_cy008(year, targets, coordinates, partitions)
        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise SupportTemporalSampleError(f"minute grid changed: {symbol}:{trade_date}")
            daily = coordinate_index.loc[(symbol, pd.Timestamp(trade_date))]
            raw_ohlc = rows[["open", "high", "low", "close"]].to_numpy(dtype=float)
            if not np.isfinite(raw_ohlc).all() or not (raw_ohlc > 0).all():
                raise SupportTemporalSampleError(f"raw minute OHLC invalid: {symbol}:{trade_date}")
            daily_close = float(daily.daily_raw_close)
            coordinate_close = float(daily.coordinate_close)
            scale = coordinate_close / daily_close
            if not np.isfinite(scale) or scale <= 0:
                raise SupportTemporalSampleError(f"coordinate scale invalid: {symbol}:{trade_date}")
            mapped = raw_ohlc * scale
            if not np.isfinite(mapped).all() or not (mapped > 0).all():
                raise SupportTemporalSampleError(f"mapped minute OHLC invalid: {symbol}:{trade_date}")
            minute_close = float(raw_ohlc[-1, 3])
            mapped_rows = rows.copy()
            mapped_rows["mapped_low"] = mapped[:, 2]
            mapped_rows["mapped_close"] = mapped[:, 3]
            descriptor = support001._session_descriptor(
                mapped_rows, float(daily.support_low20), include_auction=False
            )
            action_count = (
                int(daily.corporate_action_count)
                if pd.notna(daily.corporate_action_count)
                else 0
            )
            rights_ratio = float(daily.rights_ratio) if pd.notna(daily.rights_ratio) else 0.0
            records.append(
                {
                    "symbol": str(symbol),
                    "trade_date": pd.Timestamp(trade_date),
                    "daily_raw_close": daily_close,
                    "minute_raw_close": minute_close,
                    "binary_close_equal": bool(minute_close == daily_close),
                    "daily_close_integer_cents": data003._integer_cents(daily_close),
                    "minute_close_integer_cents": data003._integer_cents(minute_close),
                    "integer_cent_difference": data003._integer_cents(minute_close)
                    - data003._integer_cents(daily_close),
                    "raw_close_signed_difference": minute_close - daily_close,
                    "raw_close_absolute_difference": abs(minute_close - daily_close),
                    "coordinate_scale": scale,
                    "coordinate_close": coordinate_close,
                    "mapped_minute_close": float(mapped[-1, 3]),
                    "support_low10": float(daily.support_low10),
                    "support_low20": float(daily.support_low20),
                    "support_low40": float(daily.support_low40),
                    "primary_level_tested": bool(descriptor["tested"]),
                    "primary_recovery_completion": descriptor["recovery_completion"],
                    "primary_recovery_speed": descriptor["recovery_speed"],
                    "primary_recovery_volume_intensity": descriptor[
                        "recovery_volume_intensity"
                    ],
                    "corporate_action_count": action_count,
                    "rights_ratio": rights_ratio,
                    "corporate_action_blocking": bool(daily.corporate_action_blocking),
                    "daily_snapshot_id": str(daily.snapshot_id),
                    "descriptor_available_at": (
                        f"{pd.Timestamp(trade_date).date()}T15:30:00+08:00"
                    ),
                }
            )
        _resource_guard(spec, started)
    unique = pd.DataFrame(records)
    if len(unique) != spec["sample"]["expected_unique_security_sessions"]:
        raise SupportTemporalSampleError("unique minute-audit population changed")
    if (
        unique["corporate_action_blocking"].any()
        or unique["rights_ratio"].ne(0).any()
        or unique[["support_low10", "support_low20", "support_low40"]].isna().any().any()
    ):
        raise SupportTemporalSampleError("action/level coordinate gate failed")
    output = sample.merge(unique, on=["symbol", "trade_date"], validate="many_to_one")
    if len(output) != spec["sample"]["expected_cohort_rows"]:
        raise SupportTemporalSampleError("cohort minute-audit population changed")
    return output.sort_values("audit_id").reset_index(drop=True)


def build_support_count_audit(coordinate_audit: pd.DataFrame) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    group_fields = [
        "sequence_id",
        "target_year",
        "block_id",
        "market_view",
        "market_sequence_rank",
        "symbol",
    ]
    for key, rows in coordinate_audit.groupby(group_fields, sort=True):
        rows = rows.sort_values("relative_day")
        if len(rows) != 5 or rows["relative_day"].tolist() != [-5, -4, -3, -2, -1]:
            raise SupportTemporalSampleError(f"sequence conservation changed: {key[0]}")
        tested = rows["primary_level_tested"].astype(bool)
        recovered = (
            tested
            & rows["primary_recovery_completion"].fillna(False).astype(bool)
            & rows["primary_recovery_speed"].notna()
            & rows["primary_recovery_volume_intensity"].notna()
        )
        record = dict(zip(group_fields, key, strict=True))
        record.update(
            {
                "tested_day_count": int(tested.sum()),
                "recovered_tested_day_count": int(recovered.sum()),
                "repeated_test_sequence": bool(tested.sum() >= 2),
                "recovered_sequence": bool(recovered.sum() >= 2),
            }
        )
        records.append(record)
    output = pd.DataFrame(records).sort_values("sequence_id").reset_index(drop=True)
    if len(output) != 1920 or not output["sequence_id"].is_unique:
        raise SupportTemporalSampleError("support-count sequence population changed")
    return output


def evaluate_sample_adequacy(
    spec: dict[str, Any], support_counts: pd.DataFrame
) -> dict[str, Any]:
    gates = spec["sample_adequacy_gates"]
    repeated = support_counts["repeated_test_sequence"].astype(bool)
    recovered = support_counts["recovered_sequence"].astype(bool)
    repeated_year = support_counts.loc[repeated].groupby("target_year").size()
    recovered_year = support_counts.loc[recovered].groupby("target_year").size()
    block_masks = {
        name: support_counts["target_year"].isin(years)
        for name, years in gates["temporal_blocks"].items()
    }
    repeated_blocks = {
        name: int((repeated & mask).sum()) for name, mask in block_masks.items()
    }
    recovered_blocks = {
        name: int((recovered & mask).sum()) for name, mask in block_masks.items()
    }
    checks = {
        "repeated_total": int(repeated.sum()) >= gates["minimum_repeated_test_sequences"],
        "repeated_blocks": all(
            value >= gates["minimum_repeated_test_sequences_each_temporal_block"]
            for value in repeated_blocks.values()
        ),
        "repeated_years": all(
            int(repeated_year.get(year, 0)) >= gates["minimum_repeated_test_sequences_each_year"]
            for year in spec["date_range"]["years"]
        ),
        "recovered_total": int(recovered.sum()) >= gates["minimum_recovered_sequences"],
        "recovered_blocks": all(
            value >= gates["minimum_recovered_sequences_each_temporal_block"]
            for value in recovered_blocks.values()
        ),
    }
    return {
        "pass": all(checks.values()),
        "checks": checks,
        "repeated_test_sequences": int(repeated.sum()),
        "repeated_test_sequences_by_year": {
            str(year): int(repeated_year.get(year, 0)) for year in spec["date_range"]["years"]
        },
        "repeated_test_sequences_by_temporal_block": repeated_blocks,
        "recovered_sequences": int(recovered.sum()),
        "recovered_sequences_by_year": {
            str(year): int(recovered_year.get(year, 0)) for year in spec["date_range"]["years"]
        },
        "recovered_sequences_by_temporal_block": recovered_blocks,
        "process_estimates_constructed": False,
    }


def _render_report(result: dict[str, Any]) -> str:
    adequacy = result["sample_adequacy"]
    return "\n".join(
        [
            "# MKT-SUPPORT-DYN-DATA-001 temporal-sample audit",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Sequences/cohort rows/unique sessions: {result['sample_audit']['sequences']:,}/{result['sample_audit']['cohort_rows']:,}/{result['sample_audit']['unique_security_sessions']:,}.",
            f"- Repeated-tested sequences: {adequacy['repeated_test_sequences']}; recovered sequences: {adequacy['recovered_sequences']}.",
            f"- Repeated by block: {adequacy['repeated_test_sequences_by_temporal_block']}; recovered by block: {adequacy['recovered_sequences_by_temporal_block']}.",
            "- Counts alone determine whether a later temporal map may be frozen. No progression, recurrence direction, payoff, or strategy estimate was constructed.",
            "- CY-006 supplies causal scale; QD-004 supplies observed minute OHLC. Descriptor availability remains 15:30.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Sample SHA-256: `{result['hashes']['sample_sha256']}`",
            f"- Coordinate audit SHA-256: `{result['hashes']['coordinate_audit_sha256']}`",
            f"- Support-count audit SHA-256: `{result['hashes']['support_count_audit_sha256']}`",
        ]
    ) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    started = time.monotonic()
    spec = _load_spec()
    base = spec["_base_data_spec"]
    data003.parent.parent._verify_registry_assets(base)
    partitions = data003.parent.parent.bind_partitions(
        base, verify_content=verify_partition_content
    )
    _resource_guard(spec, started)
    connection = data003.parent.parent._create_daily_coordinate(base, partitions["cy006"])
    try:
        population = data003.parent.parent.build_population_audit(connection, base)
        blocks = construct_calendar_blocks(spec)
        sample, sample_audit = build_sample(connection, spec, blocks)
        coordinates = data003.parent.fetch_target_coordinates(connection, sample)
    finally:
        connection.close()
    del connection
    gc.collect()
    _resource_guard(spec, started)
    coordinate_audit = audit_minutes_and_recovery(
        spec, sample, coordinates, partitions, started
    )
    _resource_guard(spec, started)

    support_counts = build_support_count_audit(coordinate_audit)
    adequacy = evaluate_sample_adequacy(spec, support_counts)
    unique_audit = coordinate_audit.drop_duplicates(["symbol", "trade_date"])
    selected_actions = unique_audit["corporate_action_count"].gt(0)
    actions_by_year = (
        unique_audit.loc[selected_actions].groupby("target_year").size().astype(int)
    )
    if int(selected_actions.sum()) != spec["sample"]["expected_selected_supported_action_unique_sessions"]:
        raise SupportTemporalSampleError("selected supported-action identity changed")
    if any(
        int(actions_by_year.get(year, 0))
        < spec["sample"]["minimum_selected_supported_action_sessions_each_year"]
        for year in spec["date_range"]["years"]
    ):
        raise SupportTemporalSampleError("selected action year floor failed")
    sample_audit["selected_supported_action_unique_sessions"] = int(selected_actions.sum())
    sample_audit["selected_supported_action_unique_sessions_by_year"] = {
        str(year): int(actions_by_year.get(year, 0)) for year in spec["date_range"]["years"]
    }

    sample_out = sample.copy()
    sample_out["trade_date"] = sample_out["trade_date"].dt.strftime("%Y-%m-%d")
    sample_out.to_csv(SAMPLE_PATH, index=False, lineterminator="\n")
    coordinate_out = coordinate_audit.copy()
    coordinate_out["trade_date"] = coordinate_out["trade_date"].dt.strftime("%Y-%m-%d")
    coordinate_out.to_csv(
        COORDINATE_AUDIT_PATH,
        index=False,
        float_format="%.17g",
        lineterminator="\n",
    )
    population_out = population.copy()
    population_out["trade_date"] = pd.to_datetime(population_out["trade_date"]).dt.strftime(
        "%Y-%m-%d"
    )
    population_out.to_csv(POPULATION_AUDIT_PATH, index=False, lineterminator="\n")
    support_counts.to_csv(SUPPORT_COUNT_PATH, index=False, lineterminator="\n")

    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-DYN-DATA-001",
        "status": (
            "COMPLETE_SAMPLE_ADEQUACY_PASS"
            if adequacy["pass"]
            else "COMPLETE_SAMPLE_INADEQUATE"
        ),
        "sample_audit": sample_audit,
        "sample_adequacy": adequacy,
        "coordinate_audit": {
            "cohort_rows": len(coordinate_audit),
            "unique_sessions": len(unique_audit),
            "binary_close_mismatch_sessions": int((~unique_audit["binary_close_equal"]).sum()),
            "integer_cent_mismatch_sessions": int(
                unique_audit["integer_cent_difference"].ne(0).sum()
            ),
            "maximum_absolute_raw_close_difference": float(
                unique_audit["raw_close_absolute_difference"].max()
            ),
            "mapped_or_raw_nonfinite_rows": 0,
            "rights_or_blocking_action_rows": 0,
        },
        "population_audit": {
            "cells": len(population),
            "passing_cells": int(population["gate_pass"].sum()),
            "minimum_margin": int(
                (population["eligible_count"] - population["minimum_required"]).min()
            ),
        },
        "resource_checks": {
            "planned_raw_minute_rows": spec["resource_budget"]["planned_raw_minute_rows"],
            "peak_rss_below_ceiling": True,
            "memory_headroom_above_floor": True,
            "wall_clock_below_ceiling": True,
        },
        "representation_claim": "NONE",
        "support_defense_claim": "NONE",
        "temporal_process_claim": "NONE",
        "prediction_or_usefulness_claim": "NONE",
        "process_estimates_constructed": False,
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "sample_sha256": sha256_file(SAMPLE_PATH),
            "coordinate_audit_sha256": sha256_file(COORDINATE_AUDIT_PATH),
            "population_audit_sha256": sha256_file(POPULATION_AUDIT_PATH),
            "support_count_audit_sha256": sha256_file(SUPPORT_COUNT_PATH),
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
    durable_bytes = sum(
        path.stat().st_size
        for path in [
            SAMPLE_PATH,
            COORDINATE_AUDIT_PATH,
            POPULATION_AUDIT_PATH,
            SUPPORT_COUNT_PATH,
            RESULT_PATH,
            REPORT_PATH,
        ]
    )
    if durable_bytes > spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20:
        raise SupportTemporalSampleError("durable output ceiling breached")
    _resource_guard(spec, started)
    return result


if __name__ == "__main__":
    completed = run()
    print(
        json.dumps(
            {
                "status": completed["status"],
                "sample_adequacy": completed["sample_adequacy"],
            },
            indent=2,
            sort_keys=True,
        )
    )
