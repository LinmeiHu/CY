#!/usr/bin/env python3
"""Audit the frozen circulating-market-value size data contract."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import duckdb
import numpy as np


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-STYLE-DATA-001_spec.json"
RESULT_PATH = PROGRAM / "artifacts/MKT-STYLE-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-STYLE-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "506c24bcdd498162b3d44faa3008aa54ddf9a4132606b5da9a890240e224484b"
EXPECTED_REGISTRY_ASSETS = {"QD-009", "CY-006"}


class StyleDataAuditError(RuntimeError):
    """Fail-closed MKT-STYLE-DATA-001 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
        raise StyleDataAuditError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CIRCULATING_MARKET_VALUE_DERIVATION":
        raise StyleDataAuditError("spec is not frozen before size derivation")
    semantics = spec["semantics"]
    if semantics["derived_coordinate"] != (
        "circulating_market_value_cny = close * circulating_shares"
    ):
        raise StyleDataAuditError("derived-coordinate semantics changed")
    return spec


def _verify_file_inputs(spec: dict[str, Any]) -> dict[str, str]:
    observed: dict[str, str] = {}
    for name, entry in spec["inputs"].items():
        path = Path(entry["path"])
        if not path.is_absolute():
            path = ROOT / path
        actual = sha256_file(path)
        if actual != entry["sha256"]:
            raise StyleDataAuditError(f"{name} identity mismatch")
        observed[name] = actual
    return observed


def _registry_assets(spec: dict[str, Any]) -> dict[str, Any]:
    registry_path = ROOT / spec["inputs"]["registry"]["path"]
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assets = {
        item["asset_id"]: item
        for item in registry["assets"]
        if item.get("asset_id") in EXPECTED_REGISTRY_ASSETS
    }
    if set(assets) != EXPECTED_REGISTRY_ASSETS:
        raise StyleDataAuditError("required registry assets missing")
    qd009 = assets["QD-009"]
    cy006 = assets["CY-006"]
    if qd009["status"] != "RESEARCH_CONDITIONAL" or qd009["pit_grade"] != "B":
        raise StyleDataAuditError("QD-009 research/PIT contract changed")
    if cy006["status"] != "RESEARCH_CONDITIONAL" or cy006["pit_grade"] != "B":
        raise StyleDataAuditError("CY-006 research/PIT contract changed")
    if "circulating shares" not in cy006["schema_and_units"].lower():
        raise StyleDataAuditError("CY-006 circulating-share schema missing")
    if "freeFloatCapital" in cy006["schema_and_units"]:
        raise StyleDataAuditError("CY-006 unexpectedly exposes freeFloatCapital")
    if "freeFloatCapital" not in qd009["schema_and_units"]:
        raise StyleDataAuditError("QD-009 source-schema distinction missing")
    if cy006["quality_evidence"]["gate_pass"] is not True:
        raise StyleDataAuditError("CY-006 registered audit no longer passes")
    return assets


def _verify_partitions(spec: dict[str, Any]) -> tuple[list[Path], dict[str, str]]:
    manifest_path = Path(spec["inputs"]["cy006_manifest"]["path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_hashes = {item["path"]: item["sha256"] for item in manifest["files"]}
    paths: list[Path] = []
    observed: dict[str, str] = {}
    source_root = Path(spec["source"]["source_root"])
    selected = spec["source"]["selected_partition_sha256"]
    for relative, expected in sorted(selected.items()):
        if relative not in manifest_hashes or manifest_hashes[relative] != expected:
            raise StyleDataAuditError(f"manifest partition mismatch: {relative}")
        if any(token in relative for token in ("2024", "2025", "2026")):
            raise StyleDataAuditError("post-2023 partition selected")
        path = source_root / relative
        actual = sha256_file(path)
        if actual != expected:
            raise StyleDataAuditError(f"partition identity mismatch: {relative}")
        paths.append(path)
        observed[relative] = actual
    if len(paths) != 6:
        raise StyleDataAuditError("exact six pre-2024 partitions required")
    return paths, observed


def turnover_matches(volume: float, shares: float, turnover: float, tolerance: float) -> bool:
    if not all(np.isfinite(value) for value in (volume, shares, turnover)) or shares <= 0:
        return False
    return bool(abs(turnover - volume / shares) <= tolerance)


def _create_source(connection: duckdb.DuckDBPyConnection, paths: list[Path]) -> None:
    connection.from_parquet([str(path) for path in paths], union_by_name=True).create_view("source")


def _audit_rows(connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> dict[str, Any]:
    tolerance = spec["gates"]["turnover_fraction_absolute_tolerance"]
    row = connection.execute(
        """
        SELECT
          count(*) AS rows,
          count(*)-count(DISTINCT (symbol,trade_date)) AS duplicate_keys,
          min(trade_date) AS first_date,
          max(trade_date) AS last_date,
          sum(CASE WHEN available_at>decision_at THEN 1 ELSE 0 END) AS time_travel_rows,
          sum(CASE WHEN hard_valid AND (
              bar_valid IS DISTINCT FROM TRUE OR float_valid IS DISTINCT FROM TRUE OR
              corporate_action_valid IS DISTINCT FROM TRUE OR
              market_rule_valid IS DISTINCT FROM TRUE OR
              historical_identity_valid IS DISTINCT FROM TRUE
          ) THEN 1 ELSE 0 END) AS hard_valid_component_failures,
          sum(CASE WHEN hard_valid AND (
              available_at IS NULL OR decision_at IS NULL OR available_at>decision_at OR
              CAST(available_at AS DATE)<>trade_date OR CAST(decision_at AS DATE)<>trade_date OR
              float_effective_date IS NULL OR float_effective_date>trade_date OR
              float_announced_date IS NULL OR float_announced_date>trade_date OR
              float_available_date IS NULL OR float_available_date>trade_date
          ) THEN 1 ELSE 0 END) AS hard_valid_lineage_failures,
          sum(CASE WHEN hard_valid AND (
              close IS NULL OR NOT isfinite(close) OR close<=0 OR
              circulating_shares IS NULL OR NOT isfinite(circulating_shares) OR circulating_shares<=0 OR
              NOT isfinite(close*circulating_shares) OR close*circulating_shares<=0
          ) THEN 1 ELSE 0 END) AS hard_valid_size_failures,
          sum(CASE WHEN hard_valid AND volume IS NOT NULL AND isfinite(volume) AND volume>0 AND (
              turnover_fraction IS NULL OR NOT isfinite(turnover_fraction) OR
              abs(turnover_fraction-volume/circulating_shares)>?
          ) THEN 1 ELSE 0 END) AS turnover_unit_failures,
          sum(CASE WHEN hard_valid AND strftime(decision_at,'%H:%M:%S')<>'15:00:00'
              THEN 1 ELSE 0 END) AS decision_time_failures,
          count(DISTINCT snapshot_id) AS snapshot_count,
          min(CASE WHEN hard_valid THEN close*circulating_shares END) AS minimum_circulating_value,
          median(CASE WHEN hard_valid THEN close*circulating_shares END) AS median_circulating_value,
          max(CASE WHEN hard_valid THEN close*circulating_shares END) AS maximum_circulating_value
        FROM source
        """,
        [tolerance],
    ).fetchone()
    names = [item[0] for item in connection.description]
    result = dict(zip(names, row, strict=True))
    for name in (
        "rows", "duplicate_keys", "time_travel_rows", "hard_valid_component_failures",
        "hard_valid_lineage_failures", "hard_valid_size_failures", "turnover_unit_failures",
        "decision_time_failures", "snapshot_count",
    ):
        result[name] = int(result[name])
    result["first_date"] = str(result["first_date"])
    result["last_date"] = str(result["last_date"])
    for name in (
        "minimum_circulating_value", "median_circulating_value", "maximum_circulating_value"
    ):
        result[name] = float(result[name])
    return result


def _audit_population(
    connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]
) -> dict[str, Any]:
    connection.execute(
        """
        CREATE TEMP TABLE size_eligible AS
        SELECT trade_date,symbol,is_st
        FROM source
        WHERE hard_valid IS TRUE AND bar_valid IS TRUE AND float_valid IS TRUE
          AND corporate_action_valid IS TRUE AND market_rule_valid IS TRUE
          AND historical_identity_valid IS TRUE
          AND current_day_data_tradable IS TRUE AND trade_status=1
          AND available_at IS NOT NULL AND available_at<=decision_at
          AND close IS NOT NULL AND isfinite(close) AND close>0
          AND circulating_shares IS NOT NULL AND isfinite(circulating_shares)
          AND circulating_shares>0 AND isfinite(close*circulating_shares)
          AND close*circulating_shares>0
          AND volume IS NOT NULL AND isfinite(volume) AND volume>0
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE size_views AS
        SELECT 'ALL_A' AS market_view,* FROM size_eligible
        UNION ALL SELECT 'SH_A',* FROM size_eligible WHERE symbol LIKE '%.SH'
        UNION ALL SELECT 'SZ_A',* FROM size_eligible WHERE symbol LIKE '%.SZ'
        UNION ALL SELECT 'CHINEXT_BOARD',* FROM size_eligible
          WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE size_expanded AS
        SELECT market_view,trade_date,'ALL_STATUS' AS denominator FROM size_views
        UNION ALL
        SELECT market_view,trade_date,'NON_ST' AS denominator FROM size_views WHERE is_st IS FALSE
        """
    )
    rows = connection.execute(
        """
        SELECT market_view,denominator,trade_date,count(*) AS eligible_count
        FROM size_expanded GROUP BY 1,2,3 ORDER BY 1,2,3
        """
    ).fetchall()
    minimums = spec["population"]["minimum_counts"]
    grouped: dict[str, list[int]] = {}
    for view, denominator, _, count in rows:
        grouped.setdefault(f"{view}:{denominator}", []).append(int(count))
    output: dict[str, Any] = {}
    for group_name, counts in sorted(grouped.items()):
        view = group_name.split(":", 1)[0]
        threshold = int(minimums[view])
        values = np.asarray(counts, dtype=int)
        output[group_name] = {
            "dates": int(len(values)),
            "minimum_eligible_count": int(values.min()),
            "median_eligible_count": float(np.median(values)),
            "maximum_eligible_count": int(values.max()),
            "required_minimum": threshold,
            "eligible_dates": int(np.sum(values >= threshold)),
            "ineligible_dates_fail_closed": int(np.sum(values < threshold)),
            "eligible_fraction": float(np.mean(values >= threshold)),
        }
    if len(output) != 8:
        raise StyleDataAuditError("population group identity mismatch")
    return output


def _evaluate(spec: dict[str, Any], row_audit: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    checks = {
        "row_count": row_audit["rows"] == spec["source"]["expected_rows"],
        "date_start": row_audit["first_date"] == spec["source"]["date_start"],
        "date_end": row_audit["last_date"] == spec["source"]["date_end"],
        "duplicate_keys": row_audit["duplicate_keys"]
        <= gates["duplicate_symbol_date_rows_maximum"],
        "time_travel": row_audit["time_travel_rows"] <= gates["time_travel_rows_maximum"],
        "component_contract": row_audit["hard_valid_component_failures"]
        <= gates["hard_valid_component_or_lineage_failures_maximum"],
        "lineage_contract": row_audit["hard_valid_lineage_failures"]
        <= gates["hard_valid_component_or_lineage_failures_maximum"],
        "size_contract": row_audit["hard_valid_size_failures"]
        <= gates["hard_valid_size_failures_maximum"],
        "turnover_units": row_audit["turnover_unit_failures"]
        <= gates["turnover_unit_failures_maximum"],
        "decision_time": row_audit["decision_time_failures"] == 0,
        "positive_value_summary": row_audit["minimum_circulating_value"] > 0,
    }
    return {"checks": checks, "data_contract_gate_pass": bool(all(checks.values()))}


def _render_report(result: dict[str, Any]) -> str:
    audit = result["row_audit"]
    decision = result["data_contract_decision"]
    lines = [
        "# MKT-STYLE-DATA-001 circulating-size data audit",
        "",
        "## Decision",
        "",
        f"- Status: `{result['status']}`",
        f"- Data-contract gate: `{'PASS' if decision['data_contract_gate_pass'] else 'FAIL'}`",
        "- Accepted semantic label if passing: `circulating_market_value_cny`.",
        "- Total market cap, true free-float cap, enterprise value, growth/value, and beta claim: **none**.",
        "- Future values, strategy outcomes, post-2023 data, and CY-011 read: **none**.",
        "",
        "## Row/PIT audit",
        "",
        f"- Rows: {audit['rows']:,}; dates: {audit['first_date']}..{audit['last_date']}.",
        f"- Duplicate/time-travel rows: {audit['duplicate_keys']}/{audit['time_travel_rows']}.",
        f"- Component/lineage/size failures: {audit['hard_valid_component_failures']}/{audit['hard_valid_lineage_failures']}/{audit['hard_valid_size_failures']}.",
        f"- Turnover-unit/decision-time failures: {audit['turnover_unit_failures']}/{audit['decision_time_failures']}.",
        f"- Circulating value CNY min/median/max: {audit['minimum_circulating_value']:.3f}/{audit['median_circulating_value']:.3f}/{audit['maximum_circulating_value']:.3f}.",
        "",
        "## Population eligibility",
        "",
        "| Group | Dates | Minimum | Required | Fail-closed dates | Eligible fraction |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for group_name, item in result["population_audit"].items():
        lines.append(
            f"| `{group_name}` | {item['dates']} | {item['minimum_eligible_count']} | "
            f"{item['required_minimum']} | {item['ineligible_dates_fail_closed']} | "
            f"{item['eligible_fraction']:.3f} |"
        )
    failed = [name for name, passed in decision["checks"].items() if not passed]
    lines.extend([
        "",
        f"Failed hard gates: `{', '.join(failed) if failed else 'none'}`.",
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- CY-006 manifest SHA-256: `{result['hashes']['cy006_manifest_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    input_hashes = _verify_file_inputs(spec)
    _registry_assets(spec)
    paths, partition_hashes = _verify_partitions(spec)
    with tempfile.TemporaryDirectory(prefix="mkt-style-data-001-") as temp_dir:
        connection = duckdb.connect()
        connection.execute("SET threads=4")
        connection.execute(f"SET temp_directory='{temp_dir}'")
        _create_source(connection, paths)
        row_audit = _audit_rows(connection, spec)
        population_audit = _audit_population(connection, spec)
        connection.close()
    decision = _evaluate(spec, row_audit)
    status = (
        "COMPLETE_DATA_CONTRACT_PASS"
        if decision["data_contract_gate_pass"]
        else "COMPLETE_DATA_CONTRACT_FAIL_CLOSED"
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "representation_claim": "NONE",
        "usefulness_claim": "NONE",
        "accepted_semantic_label": (
            "circulating_market_value_cny"
            if decision["data_contract_gate_pass"]
            else "NONE"
        ),
        "total_market_cap_claim": "NONE",
        "true_free_float_cap_claim": "NONE",
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "row_audit": row_audit,
        "population_audit": population_audit,
        "data_contract_decision": decision,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "registry_sha256": input_hashes["registry"],
            "cy006_manifest_sha256": input_hashes["cy006_manifest"],
            "cy006_audit_sha256": input_hashes["cy006_audit"],
            "qd009_manifest_sha256": input_hashes["qd009_manifest"],
            "partition_sha256": partition_hashes,
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
    print(json.dumps({
        "status": completed["status"],
        "data_contract_gate_pass": completed["data_contract_decision"]["data_contract_gate_pass"],
        "failed_checks": [
            name for name, passed in completed["data_contract_decision"]["checks"].items()
            if not passed
        ],
    }, indent=2, sort_keys=True))
