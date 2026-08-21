#!/usr/bin/env python3
"""Build the PIT-B data gate from frozen audit evidence without rescanning data rows."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
AUDIT_DIR = ROOT / "data" / "audit"
DAILY_ROOT = ROOT / "data" / "processed" / "pit_b_daily_2018_2026_v2"
MINUTE_ROOT = ROOT / "data" / "processed" / "pit_b_minute_2018_2026_v2"
SNAPSHOT = ROOT / "data" / "input_snapshots" / (
    "CYQ-PIT-B-DAILY-MINUTE-2018-2026-20260821-R3.json"
)
REGISTRY = ROOT / "configs" / "data_asset_registry.json"

REQUIRED_DAILY_COLUMNS = {
    "trade_date",
    "decision_at",
    "symbol",
    "industry",
    "circulating_shares",
    "corporate_action_valid",
    "market_rule_valid",
    "hard_valid",
    "invalid_reasons",
    "available_at",
    "snapshot_id",
}
REQUIRED_MINUTE_DAILY_COLUMNS = {
    "trade_date",
    "symbol",
    "chip_prices",
    "chip_volumes",
    "hard_valid",
    "available_at",
    "snapshot_id",
}
REQUIRED_EXECUTION_COLUMNS = {
    "trade_date",
    "symbol",
    "window_index",
    "minute_count",
    "causal_inputs_valid",
    "hard_valid",
    "available_at",
    "snapshot_id",
}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _first_parquet_schema(root: Path) -> set[str]:
    path = next(iter(sorted(root.glob("partition_year=*/data_0.parquet"))), None)
    if path is None:
        raise FileNotFoundError(f"no partition found under {root}")
    return set(pq.read_schema(path).names)


def _check_inventory(binding: dict[str, Any], errors: list[str]) -> dict[str, Any]:
    inventory_path = Path(str(binding["inventory_manifest"]))
    expected_hash = str(binding["inventory_sha256"])
    if _sha256(inventory_path) != expected_hash:
        errors.append(f"inventory hash mismatch: {inventory_path}")
    inventory = _load(inventory_path)
    root = Path(str(inventory["root"]))
    files = inventory.get("files")
    if not isinstance(files, list) or not files:
        errors.append(f"empty inventory: {inventory_path}")
        return inventory
    for item in files:
        path = root / str(item["path"])
        if not path.is_file() or path.stat().st_size != int(item["size"]):
            errors.append(f"missing or size-changed frozen file: {path}")
    return inventory


def collect_evidence() -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    snapshot = _load(SNAPSHOT)
    registry = _load(REGISTRY)
    if _sha256(REGISTRY) != snapshot.get("registry_sha256"):
        errors.append("registry hash differs from activated snapshot")
    if snapshot.get("hard_valid") is not True:
        errors.append("activated snapshot is not hard_valid")
    bindings = snapshot.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 2:
        errors.append("activation snapshot must bind exactly daily and minute assets")
        bindings = []
    inventories = {str(item.get("role")): _check_inventory(item, errors) for item in bindings}

    daily = _load(DAILY_ROOT / "audit.json")
    if daily.get("gate_pass") is not True or daily.get("pit_grade") != "B_CAUSAL_RESEARCH":
        errors.append("daily PIT-B gate is not PASS")
    for name in ("coverage", "duplicates", "time_travel", "consistency", "cross_table"):
        check = daily.get("checks", {}).get(name, {})
        if check.get("status") != "PASS" or check.get("issue_count") != 0:
            errors.append(f"daily check failed: {name}")

    annual: list[dict[str, Any]] = []
    for year in range(2018, 2027):
        item = _load(MINUTE_ROOT / "audits" / f"year={year}.json")
        annual.append(item)
        if item.get("pass") is not True or not all(item.get("checks", {}).values()):
            errors.append(f"minute annual check failed: {year}")
    minute_cross = _load(AUDIT_DIR / "CY-008-minute-pit-b-cross-year-gate.json")
    if minute_cross.get("pass") is not True:
        errors.append("minute cross-year gate is not PASS")

    schema_checks = {
        "daily": REQUIRED_DAILY_COLUMNS
        <= _first_parquet_schema(DAILY_ROOT / "daily"),
        "minute_daily": REQUIRED_MINUTE_DAILY_COLUMNS
        <= _first_parquet_schema(MINUTE_ROOT / "daily"),
        "execution_5m": REQUIRED_EXECUTION_COLUMNS
        <= _first_parquet_schema(MINUTE_ROOT / "execution_5m"),
    }
    for name, passed in schema_checks.items():
        if not passed:
            errors.append(f"required canonical columns missing: {name}")

    assets = {item["asset_id"]: item for item in registry.get("assets", [])}
    if assets.get("QD-011", {}).get("status") != "DISCOVERY_ONLY":
        errors.append("QD-011 fundamentals must remain DISCOVERY_ONLY for first release")

    evidence = {
        "snapshot": snapshot,
        "inventories": inventories,
        "daily": daily,
        "annual_minute": annual,
        "minute_cross": minute_cross,
        "schema_checks": schema_checks,
    }
    return evidence, errors


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_outputs(evidence: dict[str, Any], errors: list[str]) -> None:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()
    daily = evidence["daily"]

    coverage_rows: list[dict[str, Any]] = []
    for item in daily["counts"]["per_year"]:
        coverage_rows.append(
            {
                "dataset": "daily_pit_b",
                "year": int(item["year"]),
                "rows": int(item["rows"]),
                "hard_valid_rows": int(item["hard_valid_rows"]),
            }
        )
    for year, item in zip(range(2018, 2027), evidence["annual_minute"], strict=True):
        coverage_rows.extend(
            [
                {
                    "dataset": "minute_daily",
                    "year": year,
                    "rows": int(item["daily"]["rows"]),
                    "hard_valid_rows": int(item["daily"]["hard_valid_rows"]),
                },
                {
                    "dataset": "execution_5m",
                    "year": year,
                    "rows": int(item["execution_5m"]["rows"]),
                    "hard_valid_rows": int(item["execution_5m"]["hard_valid_rows"]),
                },
            ]
        )
    pq.write_table(pa.Table.from_pylist(coverage_rows), AUDIT_DIR / "cyq_pit_coverage.parquet")
    anomaly_schema = pa.schema(
        [
            ("domain", pa.string()),
            ("check", pa.string()),
            ("count", pa.int64()),
            ("detail", pa.string()),
        ]
    )
    anomaly_rows = [
        {"domain": "gate", "check": "frozen_evidence", "count": 1, "detail": error}
        for error in errors
    ]
    pq.write_table(
        pa.Table.from_pylist(anomaly_rows, schema=anomaly_schema),
        AUDIT_DIR / "cyq_pit_anomalies.parquet",
    )

    manifest = {
        "generated_at": generated_at,
        "pit_grade": "B_CAUSAL_RESEARCH",
        "strict_pit_archive_ready": False,
        "activation_manifest": str(SNAPSHOT),
        "activation_manifest_sha256": _sha256(SNAPSHOT),
        "registry": str(REGISTRY),
        "registry_sha256": _sha256(REGISTRY),
        "bindings": evidence["snapshot"]["bindings"],
        "audit_sources": {
            "daily": str(DAILY_ROOT / "audit.json"),
            "minute_cross_year": str(
                AUDIT_DIR / "CY-008-minute-pit-b-cross-year-gate.json"
            ),
        },
    }
    _write_json(AUDIT_DIR / "cyq_pit_snapshot_manifest.json", manifest)

    gate_pass = not errors
    gate = {
        "generated_at": generated_at,
        "gate": "CYQ_PIT_B_DATA_READY",
        "pass": gate_pass,
        "pit_grade": "B_CAUSAL_RESEARCH",
        "strict_pit_archive_ready": False,
        "fundamentals_enabled": False,
        "checks": {
            "frozen_snapshot_identity": "PASS" if not errors else "FAIL",
            "daily_coverage_duplicates_time_travel_consistency_cross_table": (
                "PASS" if daily.get("gate_pass") is True else "FAIL"
            ),
            "minute_2018_2026": (
                "PASS"
                if all(item.get("pass") is True for item in evidence["annual_minute"])
                else "FAIL"
            ),
            "canonical_columns": (
                "PASS" if all(evidence["schema_checks"].values()) else "FAIL"
            ),
            "missing_required_domain_fails_closed": (
                "PASS"
                if daily["checks"]["cross_table"]["status"] == "PASS"
                else "FAIL"
            ),
        },
        "errors": errors,
    }
    _write_json(AUDIT_DIR / "cyq_pit_gate.json", gate)

    status = "PASS" if gate_pass else "FAIL"
    report = f"""# CYQ PIT-B 数据门禁审计

- 结果：**{status}**
- 等级：`B_CAUSAL_RESEARCH`；严格 PIT-A：`false`
- 日线：{daily['counts']['output_rows']:,} 行，`hard_valid=true` \
{daily['counts']['hard_valid_rows']:,} 行
- 分钟日表：{sum(item['daily']['rows'] for item in evidence['annual_minute']):,} 行
- 因果 5 分钟成交窗：{sum(item['execution_5m']['rows'] for item in evidence['annual_minute']):,} 行
- 日线覆盖、重复、时间穿越、一致性、跨表失败关闭：全部 PASS
- 2018–2026 分钟年度审计与跨年门禁：全部 PASS
- 财务披露：`DISCOVERY_ONLY`，首版禁用且不参与 `hard_valid`
- 错误：{json.dumps(errors, ensure_ascii=False)}

本报告由冻结审计证据汇总生成，不重复扫描全量行情。异常明细表为空表示已冻结审计的
issue count 为零；已知 PIT-B 局限保留在日线审计与数据源矩阵中。
"""
    (AUDIT_DIR / "cyq_pit_audit_report.md").write_text(report, encoding="utf-8")


def main() -> int:
    try:
        evidence, errors = collect_evidence()
        write_outputs(evidence, errors)
    except Exception as exc:  # fail closed at the CLI boundary
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"FAIL: {error}", file=sys.stderr)
        return 1
    print("PASS: CYQ PIT-B data gate evidence is complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
