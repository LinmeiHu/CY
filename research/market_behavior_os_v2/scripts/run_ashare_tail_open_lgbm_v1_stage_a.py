#!/usr/bin/env python3
"""Run the outcome-blind Stage-A audit for A-share Tail-to-Open LightGBM V1."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
from pathlib import Path
from typing import Any

import duckdb
import lightgbm
import numpy
import pandas
import pyarrow
import pyarrow.parquet as pq
import sklearn

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_stage_a_spec.json"
FEATURE_PATH = PROGRAM / "experiments/ASHARE-TAIL-OPEN-LGBM-V1_feature_manifest.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-TAIL-OPEN-LGBM-V1_stage_a_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-TAIL-OPEN-LGBM-V1_stage_a_report.md"
EXPECTED_SPEC_SHA256 = "e6010d586231286dcc34066cdaa97a99f7c8252afbd1721338b67658b9a948cc"

DAILY_2018 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
    "daily/partition_year=2018/data_0.parquet"
)
MINUTE_DAILY_2018 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/"
    "daily/partition_year=2018/data_0.parquet"
)
EXECUTION_2018 = Path(
    "/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2/"
    "execution_5m/partition_year=2018/data_0.parquet"
)
RAW_2018 = Path(
    "/Users/linmei/Downloads/workspace/quant/data/lake/"
    "stock_1min_canonical_none_20260813/bars/2018_day_parquet_none.parquet"
)
DAILY_GLOB = (
    "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/"
    "daily/partition_year=*/data_0.parquet"
)
EXTERNAL_VOLUME = Path("/Volumes/quant")


class StageAAuditError(RuntimeError):
    """Fail-closed Stage-A audit error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_feature_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    features = manifest.get("features", [])
    names = [item.get("name") for item in features]
    if manifest.get("status") != "FROZEN_BEFORE_OUTCOME_READ":
        raise StageAAuditError("feature manifest is not frozen")
    if manifest.get("decision_at") != "14:25:00 Asia/Shanghai":
        raise StageAAuditError("feature cutoff changed")
    if not 30 <= len(features) <= 60 or manifest.get("feature_count") != len(features):
        raise StageAAuditError("feature count is outside the frozen compact range")
    if len(set(names)) != len(names) or any(not name for name in names):
        raise StageAAuditError("feature names are missing or duplicated")
    forbidden = ("14:26", "14:55", "15:00", "final-session", "next-day")
    serialized = json.dumps(features, sort_keys=True).lower()
    hits = [token for token in forbidden if token in serialized]
    if hits:
        raise StageAAuditError(f"post-cutoff token in feature dictionary: {hits}")
    required = {"name", "family", "formula", "source", "lookback", "available_at"}
    incomplete = [item.get("name") for item in features if set(item) != required]
    if incomplete:
        raise StageAAuditError(f"incomplete feature records: {incomplete}")
    return {"feature_count": len(features), "unique_names": len(set(names))}


def _schema_names(path: Path) -> set[str]:
    if not path.is_file():
        raise StageAAuditError(f"missing registered input: {path}")
    return set(pq.ParquetFile(path).schema_arrow.names)


def validate_schemas() -> dict[str, Any]:
    required = {
        "daily": {
            "trade_date",
            "decision_at",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "preclose",
            "amount",
            "turnover_fraction",
            "trade_status",
            "is_st",
            "up_limit_price",
            "down_limit_price",
            "sell_blocked_open",
            "industry",
            "source_notice_date",
            "corporate_action_blocking",
            "hard_valid",
            "available_at",
            "snapshot_id",
        },
        "minute_daily": {
            "symbol",
            "trade_date",
            "available_at",
            "session_complete",
            "minute_count",
            "hard_valid",
            "snapshot_id",
            "daily_snapshot_id",
        },
        "execution": {
            "symbol",
            "trade_date",
            "window_index",
            "available_at",
            "trade_status",
            "is_st",
            "up_limit_price",
            "down_limit_price",
            "market_rule_id",
            "hard_valid",
            "snapshot_id",
            "daily_snapshot_id",
        },
        "raw": {
            "symbol",
            "exchange",
            "period",
            "adjust",
            "trade_date",
            "bar_end_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "source",
        },
    }
    paths = {
        "daily": DAILY_2018,
        "minute_daily": MINUTE_DAILY_2018,
        "execution": EXECUTION_2018,
        "raw": RAW_2018,
    }
    result: dict[str, Any] = {}
    for name, path in paths.items():
        columns = _schema_names(path)
        missing = sorted(required[name] - columns)
        if missing:
            raise StageAAuditError(f"{name} schema missing {missing}")
        result[name] = {"path": str(path), "required_columns_present": True}
    return result


def calendar_metadata() -> dict[str, Any]:
    connection = duckdb.connect()
    rows = connection.execute(
        """SELECT year(trade_date) AS year,min(trade_date),max(trade_date),
        count(DISTINCT trade_date) FROM read_parquet(?) GROUP BY 1 ORDER BY 1""",
        [DAILY_GLOB],
    ).fetchall()
    first_eligible = connection.execute(
        """SELECT trade_date FROM (SELECT DISTINCT trade_date FROM read_parquet(?)
        WHERE year(trade_date)=2018 ORDER BY trade_date) LIMIT 1 OFFSET 59""",
        [DAILY_GLOB],
    ).fetchone()
    connection.close()
    if not first_eligible or str(first_eligible[0]) != "2018-04-02":
        raise StageAAuditError("60-session warm-up boundary changed")
    expected = {
        2018: ("2018-01-02", "2018-12-28", 243),
        2019: ("2019-01-02", "2019-12-31", 244),
        2020: ("2020-01-02", "2020-12-31", 243),
        2021: ("2021-01-04", "2021-12-31", 243),
        2022: ("2022-01-04", "2022-12-30", 242),
        2023: ("2023-01-03", "2023-12-29", 242),
        2024: ("2024-01-02", "2024-12-31", 242),
        2025: ("2025-01-02", "2025-12-31", 243),
        2026: ("2026-01-05", "2026-08-12", 147),
    }
    observed = {int(year): (str(first), str(last), int(count)) for year, first, last, count in rows}
    if observed != expected:
        raise StageAAuditError(f"calendar metadata changed: {observed}")
    return {
        "years": {
            str(year): {"first": first, "last": last, "sessions": count}
            for year, (first, last, count) in observed.items()
        },
        "first_signal_after_60_session_warmup": str(first_eligible[0]),
        "security_columns_read_post_2023": False,
    }


def run() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StageAAuditError("Stage-A spec hash changed")
    spec = _load_json(SPEC_PATH)
    feature_manifest = _load_json(FEATURE_PATH)
    for contract in spec["input_contracts"].values():
        if "path" in contract:
            contract_path = Path(contract["path"])
            path = contract_path if contract_path.is_absolute() else ROOT / contract_path
        elif "manifest" in contract:
            path = Path(contract["manifest"])
        else:
            raise StageAAuditError(f"unknown input contract record: {contract}")
        if sha256_file(path) != contract["sha256"]:
            raise StageAAuditError(f"input identity changed: {path}")
    disk = shutil.disk_usage(EXTERNAL_VOLUME)
    if disk.free < 500 * (1 << 30):
        raise StageAAuditError("external volume has less than 500 GiB free")
    free_gib_floor_hundreds = int(disk.free / (100 * (1 << 30))) * 100
    result = {
        "experiment_id": spec["experiment_id"],
        "stage": "A",
        "status": "STAGE_A_COMPLETE_OUTCOME_BLIND",
        "environment_valid": True,
        "feature_audit": validate_feature_manifest(feature_manifest),
        "schema_audit": validate_schemas(),
        "calendar_audit": calendar_metadata(),
        "resource_audit": {
            "external_volume": str(EXTERNAL_VOLUME),
            "external_free_gib_floor_hundreds": free_gib_floor_hundreds,
            "external_free_gib_minimum_required": 500,
            "external_root_created": False,
            "lightgbm_available": True,
        },
        "versions": {
            "python": platform.python_version(),
            "lightgbm": lightgbm.__version__,
            "sklearn": sklearn.__version__,
            "duckdb": duckdb.__version__,
            "pyarrow": pyarrow.__version__,
            "pandas": pandas.__version__,
            "numpy": numpy.__version__,
        },
        "chronology": spec["chronology"],
        "execution_contract": spec["clock"] | spec["label"],
        "boundaries": spec["stage_a_boundaries"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "feature_manifest_sha256": sha256_file(FEATURE_PATH),
        },
    }
    return result


def render(result: dict[str, Any]) -> str:
    chronology = result["chronology"]
    return "\n".join(
        [
            "# A-share Tail-to-Open LightGBM V1 — Stage A",
            "",
            "## CONCLUSION",
            "",
            "`STAGE_A_COMPLETE_OUTCOME_BLIND`",
            "",
            "The fixed lane uses 59 features available no later than 14:25, a single raw",
            "one-minute entry bar ending 14:56, and the first later legal open. No forward",
            "return, model fit, portfolio result, or post-2023 security row was read.",
            "",
            "## CHRONOLOGY",
            "",
            "- Development: "
            f"`{chronology['development'][0]}` through `{chronology['development'][1]}`.",
            "- Validation: "
            f"`{chronology['validation'][0]}` through `{chronology['validation'][1]}`.",
            "- Final locked OOS: "
            f"`{chronology['final_locked_oos'][0]}` through "
            f"`{chronology['final_locked_oos'][1]}`.",
            "- Final OOS remains `LOCKED_UNREAD`; only calendar/schema metadata was inspected.",
            "",
            "## EXECUTION",
            "",
            "The signal is formed after the completed 14:25 bar. The order is represented",
            "by the VWAP of the bar ending 14:56 and is unfilled when pinned at the upper",
            "limit. Exit is the first later legal open under T+1, suspension, limit, lot,",
            "and frozen QD-010 corporate-action handling. Canonical cost is 20 bps per side.",
            "",
            "## MODELS AND DECISION",
            "",
            "Ridge and exactly three preregistered LightGBM profiles are allowed. Top-10 is",
            "fixed. Development walk-forward must pass before validation is opened; final",
            "OOS requires every validation continuation gate and a separate committed freeze.",
            "",
            "## RESOURCES",
            "",
            "The mounted external volume has at least "
            f"{result['resource_audit']['external_free_gib_floor_hundreds']} GiB free.",
            "Stage B may scan and materialize only 2018-2023 yearly shards. No 2024-2026",
            "feature or label shard may be created before Stage C authorization.",
            "",
        ]
    )


def main() -> None:
    result = run()
    _atomic_write(RESULT_PATH, json.dumps(result, sort_keys=True, indent=2) + "\n")
    _atomic_write(REPORT_PATH, render(result))


if __name__ == "__main__":
    main()
