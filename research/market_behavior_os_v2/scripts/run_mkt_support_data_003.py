#!/usr/bin/env python3
"""Execute source-role-correct objective-support coordinate feasibility."""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
PARENT_RUNNER = PROGRAM / "scripts/run_mkt_support_data_002.py"
MODULE_SPEC = importlib.util.spec_from_file_location(
    "run_mkt_support_data_002_parent", PARENT_RUNNER
)
if MODULE_SPEC is None or MODULE_SPEC.loader is None:
    raise RuntimeError("cannot load MKT-SUPPORT-DATA-002 parent")
parent = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(parent)

SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-DATA-003_spec.json"
SAMPLE_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-003_sample.csv"
COORDINATE_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-003_coordinate_audit.csv"
POPULATION_AUDIT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-003_population_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-DATA-003_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-DATA-003_audit.md"
EXPECTED_SPEC_SHA256 = "7a734dd94bd61f2bc52578c6a8706edde637b23d3f5636b4877b7e13ca931b6f"

SupportDataError = parent.SupportDataError
sha256_file = parent.sha256_file
adapter = parent.adapter


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise SupportDataError("MKT-SUPPORT-DATA-003 spec identity mismatch")
    control = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if control["status"] != "FROZEN_BEFORE_RAW_MINUTE_ACCESS":
        raise SupportDataError("003 is not frozen before raw-minute access")
    invalid = control["invalid_parent"]
    parent_spec_path = _resolve(invalid["spec_path"])
    parent_runner_path = _resolve(invalid["runner_path"])
    if sha256_file(parent_spec_path) != invalid["spec_sha256"]:
        raise SupportDataError("002 parent spec identity mismatch")
    if sha256_file(parent_runner_path) != invalid["runner_sha256"]:
        raise SupportDataError("002 parent runner identity mismatch")
    if invalid["outputs_accepted"] is not False:
        raise SupportDataError("002 invalid-output boundary changed")
    roles = control["source_roles"]
    if (
        roles["daily_minute_close_equality_required"] is not False
        or roles["numeric_tolerance"] is not None
        or roles["rounding_or_clipping_of_mapped_prices"] is not False
        or roles["mapped_final_close_forced_to_daily_coordinate_close"] is not False
    ):
        raise SupportDataError("003 source-role correction changed")
    inherited = parent._load_spec()
    inherited["experiment_id"] = control["experiment_id"]
    inherited["status"] = control["status"]
    inherited["outputs"] = control["outputs"]
    inherited["claim_boundary"] = control["claim_boundary"]
    inherited["_control_spec"] = control
    return inherited


def _integer_cents(value: float) -> int:
    if not np.isfinite(value) or value <= 0:
        raise SupportDataError("integer-cent diagnostic received invalid price")
    return int(math.floor(value * 100.0 + 0.5))


def _read_and_validate_cy008(
    year: int,
    targets: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
) -> None:
    coordinate_index = coordinates.set_index(["symbol", "trade_date"])
    cy8 = parent.parent._read_cy008_daily(
        partitions["cy008_daily"][f"daily/partition_year={year}/data_0.parquet"],
        targets,
    )
    target_count = targets[["symbol", "trade_date"]].drop_duplicates().shape[0]
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


def audit_minute_coordinates(
    spec: dict[str, Any],
    sample: pd.DataFrame,
    coordinates: pd.DataFrame,
    partitions: dict[str, dict[str, Path]],
) -> pd.DataFrame:
    unique_targets = sample[
        ["symbol", "source_symbol", "trade_date", "target_year"]
    ].drop_duplicates()
    coordinate_index = coordinates.set_index(["symbol", "trade_date"])
    records: list[dict[str, Any]] = []
    for raw_year, targets in unique_targets.groupby("target_year", sort=True):
        year = int(raw_year)
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
        raw["symbol"] = (
            raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        )
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        target_count = targets[["symbol", "trade_date"]].drop_duplicates().shape[0]
        if raw.groupby(["symbol", "trade_date"]).ngroups != target_count:
            raise SupportDataError(f"raw target session coverage mismatch: {year}")
        _read_and_validate_cy008(year, targets, coordinates, partitions)

        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            if len(rows) != 241:
                raise SupportDataError(f"minute row count mismatch: {symbol}:{trade_date}")
            daily = coordinate_index.loc[(symbol, pd.Timestamp(trade_date))]
            raw_ohlc = rows[["open", "high", "low", "close"]].to_numpy(dtype=float)
            if not np.isfinite(raw_ohlc).all() or not (raw_ohlc > 0).all():
                raise SupportDataError(f"raw minute OHLC invalid: {symbol}:{trade_date}")
            daily_close = float(daily.daily_raw_close)
            coordinate_close = float(daily.coordinate_close)
            scale = coordinate_close / daily_close
            if not np.isfinite(scale) or scale <= 0:
                raise SupportDataError(f"coordinate scale invalid: {symbol}:{trade_date}")
            mapped = raw_ohlc * scale
            if not np.isfinite(mapped).all() or not (mapped > 0).all():
                raise SupportDataError(f"mapped minute coordinate invalid: {symbol}:{trade_date}")
            minute_close = float(raw_ohlc[-1, 3])
            mapped_close = float(mapped[-1, 3])
            expected_mapped_close = minute_close * scale
            if mapped_close != expected_mapped_close:
                raise SupportDataError(f"mapped-close multiplication identity failed: {symbol}:{trade_date}")

            daily_cents = _integer_cents(daily_close)
            minute_cents = _integer_cents(minute_close)
            raw_difference = minute_close - daily_close
            support20 = float(daily.support_low20)
            closes = mapped[:, 3]
            lows = mapped[:, 2]
            minimum_position = int(np.argmin(lows))
            action_count = (
                int(daily.corporate_action_count)
                if pd.notna(daily.corporate_action_count)
                else 0
            )
            rights_ratio = float(daily.rights_ratio) if pd.notna(daily.rights_ratio) else 0.0
            records.append(
                {
                    "symbol": symbol,
                    "trade_date": pd.Timestamp(trade_date),
                    "daily_raw_close": daily_close,
                    "minute_raw_close": minute_close,
                    "binary_close_equal": bool(minute_close == daily_close),
                    "daily_close_integer_cents": daily_cents,
                    "minute_close_integer_cents": minute_cents,
                    "integer_cent_difference": minute_cents - daily_cents,
                    "raw_close_signed_difference": raw_difference,
                    "raw_close_absolute_difference": abs(raw_difference),
                    "coordinate_scale": scale,
                    "coordinate_close": coordinate_close,
                    "mapped_minute_close": mapped_close,
                    "support_low10": float(daily.support_low10),
                    "support_low20": support20,
                    "support_low40": float(daily.support_low40),
                    "primary_level_tested": bool(np.min(lows) <= support20),
                    "primary_penetration_depth": max(
                        0.0, (support20 - float(np.min(lows))) / support20
                    ),
                    "primary_close_below_fraction": float(np.mean(closes < support20)),
                    "primary_minimum_bar_index": minimum_position,
                    "primary_close_recovery_from_minimum": (
                        float(closes[-1] - lows[minimum_position]) / support20
                    ),
                    "up_limit_contact": bool(
                        np.max(raw_ohlc[:, 1]) >= float(daily.up_limit_price)
                    ),
                    "down_limit_contact": bool(
                        np.min(raw_ohlc[:, 2]) <= float(daily.down_limit_price)
                    ),
                    "corporate_action_count": action_count,
                    "rights_ratio": rights_ratio,
                    "corporate_action_blocking": bool(daily.corporate_action_blocking),
                    "daily_snapshot_id": str(daily.snapshot_id),
                    "descriptor_available_at": (
                        f"{pd.Timestamp(trade_date).date()}T15:30:00+08:00"
                    ),
                }
            )
    session_audit = pd.DataFrame(records)
    expected_unique = unique_targets[["symbol", "trade_date"]].drop_duplicates().shape[0]
    if len(session_audit) != expected_unique:
        raise SupportDataError("unique 003 coordinate audit population mismatch")
    output = sample.merge(session_audit, on=["symbol", "trade_date"], validate="many_to_one")
    if len(output) != spec["sample"]["expected_cohort_rows"]:
        raise SupportDataError("003 cohort coordinate audit population mismatch")
    action = output["cohort"].eq("SUPPORTED_ACTION_AUDIT")
    if not (
        output.loc[action, "corporate_action_count"].gt(0).all()
        and output.loc[action, "rights_ratio"].eq(0).all()
        and ~output.loc[action, "corporate_action_blocking"].all()
    ):
        raise SupportDataError("003 action cohort semantic gate failed")
    required_diagnostics = spec["_control_spec"]["diagnostics"]["per_session_fields"]
    if any(field not in output.columns for field in required_diagnostics):
        raise SupportDataError("003 source-disagreement diagnostic missing")
    if output[required_diagnostics].isna().any().any():
        raise SupportDataError("003 source-disagreement diagnostic null")
    return output.sort_values("audit_id").reset_index(drop=True)


def _render_report(result: dict[str, Any]) -> str:
    audit = result["coordinate_audit"]
    return "\n".join(
        [
            "# MKT-SUPPORT-DATA-003 objective support coordinate audit",
            "",
            "## Result",
            "",
            f"- Status: `{result['status']}`",
            f"- Cohort rows: {audit['cohort_rows']:,}; unique security-sessions: {audit['unique_sessions']:,}.",
            f"- Binary daily/minute close mismatches: {audit['binary_close_mismatch_sessions']:,}.",
            f"- Integer-cent close mismatches: {audit['integer_cent_mismatch_sessions']:,}; maximum absolute raw difference: {audit['maximum_absolute_raw_close_difference']:.12g} CNY.",
            f"- Supported action rows: {audit['supported_action_rows']}; primary 20-session level tests observed: {audit['primary_level_tests']}.",
            f"- Full daily population cells passing: {result['population_audit']['passing_cells']}/{result['population_audit']['cells']}.",
            "- CY-006 supplies only the causal scale; QD-004 supplies observed minute OHLC. No close was substituted or forced equal.",
            "- Availability is 15:30. This is coordinate feasibility, not support, defense, recovery, accumulation, prediction, or a strategy.",
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Sample SHA-256: `{result['hashes']['sample_sha256']}`",
            f"- Coordinate audit SHA-256: `{result['hashes']['coordinate_audit_sha256']}`",
            f"- Population audit SHA-256: `{result['hashes']['population_audit_sha256']}`",
        ]
    ) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    parent.parent._verify_registry_assets(spec)
    partitions = parent.parent.bind_partitions(spec, verify_content=verify_partition_content)
    connection = parent.parent._create_daily_coordinate(spec, partitions["cy006"])
    try:
        population = parent.parent.build_population_audit(connection, spec)
        sample = parent.build_sample(connection, spec)
        coordinates = parent.fetch_target_coordinates(connection, sample)
        coordinate_audit = audit_minute_coordinates(spec, sample, coordinates, partitions)
    finally:
        connection.close()

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

    action = coordinate_audit["cohort"].eq("SUPPORTED_ACTION_AUDIT")
    unique_audit = coordinate_audit.drop_duplicates(["symbol", "trade_date"])
    binary_mismatch = ~unique_audit["binary_close_equal"]
    cent_mismatch = unique_audit["integer_cent_difference"].ne(0)
    cent_by_year = (
        unique_audit.loc[cent_mismatch]
        .groupby("target_year")
        .size()
        .astype(int)
        .to_dict()
    )
    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-DATA-003",
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
        "source_roles": spec["_control_spec"]["source_roles"],
        "coordinate_audit": {
            "cohort_rows": int(len(coordinate_audit)),
            "unique_sessions": int(len(unique_audit)),
            "supported_action_rows": int(action.sum()),
            "supported_action_rows_by_year": {
                str(year): int(count)
                for year, count in coordinate_audit.loc[action]
                .groupby("target_year")
                .size()
                .items()
            },
            "binary_close_match_sessions": int((~binary_mismatch).sum()),
            "binary_close_mismatch_sessions": int(binary_mismatch.sum()),
            "integer_cent_match_sessions": int((~cent_mismatch).sum()),
            "integer_cent_mismatch_sessions": int(cent_mismatch.sum()),
            "integer_cent_mismatch_sessions_by_year": {
                str(year): count for year, count in cent_by_year.items()
            },
            "maximum_absolute_integer_cent_difference": int(
                unique_audit["integer_cent_difference"].abs().max()
            ),
            "maximum_absolute_raw_close_difference": float(
                unique_audit["raw_close_absolute_difference"].max()
            ),
            "mapped_close_multiplication_identity_failures": 0,
            "mapped_or_raw_nonfinite_rows": 0,
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
            "parent_spec_sha256": spec["_control_spec"]["invalid_parent"]["spec_sha256"],
            "parent_runner_sha256": spec["_control_spec"]["invalid_parent"]["runner_sha256"],
            "sample_sha256": sha256_file(SAMPLE_PATH),
            "coordinate_audit_sha256": sha256_file(COORDINATE_AUDIT_PATH),
            "population_audit_sha256": sha256_file(POPULATION_AUDIT_PATH),
            "bound_inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
        },
    }
    result = parent.parent._clean(result)
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
