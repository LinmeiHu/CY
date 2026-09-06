#!/usr/bin/env python3
"""Run frozen dispersion-rank science under a machine-sized external contract."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-RANK-003_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-003_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-003_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-RANK-003_industry_rank.md"
BASE_PATH = PROGRAM / "scripts/run_mkt_disp_rank_002.py"
EXPECTED_SPEC_SHA256 = "7758ffc29b03aa344858d2a25f993d2e1071dc26c6207efd63032b8fe3c3de75"


class DispersionRankResourceError(RuntimeError):
    """Fail-closed materially different dispersion-rank retry error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise DispersionRankResourceError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


BASE = _load_module("mkt_disp_rank_002_for_003", BASE_PATH)


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionRankResourceError("resource-retry spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec.get("status") != "FROZEN_MATERIALLY_DIFFERENT_RESOURCE_CONTRACT_RETRY"
        or spec.get("scientific_changes") != "NONE"
    ):
        raise DispersionRankResourceError("frozen resource/science boundary changed")
    for section in ("inherits_scientific_spec", "inherits_year_batched_engineering"):
        binding = spec[section]
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionRankResourceError(f"bound input changed: {section}")
    for name, binding in spec["bound_runners"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionRankResourceError(f"bound runner changed: {name}")
    return spec


def _effective_scientific(
    scientific: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    effective = copy.deepcopy(scientific)
    contract = spec["resource_contract"]
    effective["resource"] = {
        "duckdb_threads": contract["duckdb_threads"],
        "duckdb_memory_limit_mb": int(contract["duckdb_memory_limit_gib"] * 1024),
        "prelaunch_available_memory_floor_gib": contract[
            "prelaunch_available_memory_floor_gib"
        ],
        "in_run_available_memory_floor_gib": contract["in_run_available_memory_floor_gib"],
        "peak_rss_ceiling_gib": contract["peak_rss_ceiling_gib"],
        "temporary_spill_ceiling_gib": contract["temporary_spill_ceiling_gib"],
        "wall_clock_ceiling_minutes": contract["wall_clock_ceiling_minutes"],
    }
    return effective


def _resource_preflight(spec: dict[str, Any]) -> dict[str, Any]:
    contract = spec["resource_contract"]
    scratch = Path(contract["scratch_root"])
    if not Path("/Volumes/quant").is_mount():
        raise DispersionRankResourceError("verified external volume is not mounted")
    scratch.mkdir(parents=True, exist_ok=True)
    if not os.access(scratch, os.W_OK):
        raise DispersionRankResourceError("external scratch root is not writable")
    usage = shutil.disk_usage(scratch)
    free_gib = usage.free / 2**30
    if free_gib < contract["minimum_scratch_free_gib"]:
        raise DispersionRankResourceError("external scratch free-space floor failed")
    if any(PANEL_PATH.parent.glob("MKT-DISP-RANK-003_*.tmp")):
        raise DispersionRankResourceError("unexpected prior partial durable output")
    return {
        "scratch_root": str(scratch),
        "scratch_free_gib": free_gib,
        "scratch_total_gib": usage.total / 2**30,
        "scratch_used_gib": usage.used / 2**30,
    }


def _create_rank_security_for_year_explicit_group(
    connection: Any, anchor_year: int
) -> None:
    """Preserve 002 semantics while avoiding DuckDB GROUP BY ALL binding drift."""
    connection.execute(
        f"""
        CREATE TEMP TABLE rank_anchor AS
        SELECT trade_date,cal_idx,symbol,is_st,causal_industry,
               exp(step_log_return)-1 AS current_return1,adjusted_close AS coordinate_close_t
        FROM stock_lagged
        WHERE year(trade_date)={anchor_year}
          AND current_valid AND history_valid
          AND coordinate_valid_count120=120
          AND history_row_count121=121 AND history_valid_count121=121
          AND cal_idx-history_min_cal_idx121=120
          AND cal_idx-lag_idx20=20
          AND step_log_return IS NOT NULL AND isfinite(step_log_return)
          AND lag_close20 IS NOT NULL AND isfinite(lag_close20) AND lag_close20>0
          AND causal_industry IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE TEMP TABLE rank_security AS
        SELECT a.trade_date,a.cal_idx,a.symbol,a.is_st,a.causal_industry,
               a.current_return1,a.coordinate_close_t,
               ln(max(CASE WHEN f.cal_idx=a.cal_idx+1 THEN f.adjusted_close END)
                  /a.coordinate_close_t) AS future_return_h1,
               ln(max(CASE WHEN f.cal_idx=a.cal_idx+3 THEN f.adjusted_close END)
                  /a.coordinate_close_t) AS future_return_h3,
               ln(max(CASE WHEN f.cal_idx=a.cal_idx+5 THEN f.adjusted_close END)
                  /a.coordinate_close_t) AS future_return_h5
        FROM rank_anchor a JOIN stock_lagged f
          ON f.symbol=a.symbol AND f.cal_idx BETWEEN a.cal_idx+1 AND a.cal_idx+5
        GROUP BY a.trade_date,a.cal_idx,a.symbol,a.is_st,a.causal_industry,
                 a.current_return1,a.coordinate_close_t
        HAVING count(*)=5
           AND sum((f.history_valid AND f.coordinate_step_valid)::INTEGER)=5
           AND count(CASE WHEN f.adjusted_close IS NOT NULL AND isfinite(f.adjusted_close)
                               AND f.adjusted_close>0 THEN 1 END)=5
        """
    )
    invalid = connection.execute(
        """SELECT count(*) FROM rank_security WHERE NOT (
             isfinite(future_return_h1) AND isfinite(future_return_h3)
             AND isfinite(future_return_h5))"""
    ).fetchone()[0]
    if int(invalid):
        raise DispersionRankResourceError("invalid future rank response")
    for table in (
        "base",
        "stock_step",
        "stock_chain",
        "stock_adjusted",
        "stock_windows",
        "stock_prestate",
        "stock_lagged",
    ):
        connection.execute(f"DROP TABLE IF EXISTS {table}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def main() -> None:
    spec = _load_spec()
    preflight = _resource_preflight(spec)
    retry, scientific, industry_spec, industry_runner, rank001 = BASE._load_spec()
    effective = _effective_scientific(scientific, spec)
    scratch = Path(spec["resource_contract"]["scratch_root"])
    previous_tempdir = tempfile.tempdir
    previous_builder = BASE._create_rank_security_for_year
    tempfile.tempdir = str(scratch)
    BASE._create_rank_security_for_year = _create_rank_security_for_year_explicit_group
    try:
        daily, telemetry = BASE._build_daily_batched(
            retry, effective, industry_spec, industry_runner, rank001
        )
    finally:
        tempfile.tempdir = previous_tempdir
        BASE._create_rank_security_for_year = previous_builder
    panel, result = rank001._analyze(daily, effective)
    result["experiment_id"] = spec["experiment_id"]
    result["research_level"] = spec["research_level"]
    result["status"] = "COMPLETE_MATERIALLY_DIFFERENT_RESOURCE_CONTRACT_RETRY"
    result["scientific_changes"] = "NONE"
    result["resource_preflight"] = preflight
    result["resource_contract"] = spec["resource_contract"]
    result["engineering"] = telemetry
    result["post_2023_read"] = "NO"
    result["cy011_read"] = "NO"
    result["strategy_change"] = "NONE_DIRECTION_SCIENCE_ONLY"
    panel_csv = panel.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    durable_estimate = len(panel_csv.encode("utf-8"))
    if durable_estimate > int(spec["resource_contract"]["durable_output_ceiling_mib"] * 2**20):
        raise DispersionRankResourceError("durable output ceiling breached")
    _atomic_write(PANEL_PATH, panel_csv)
    result["hashes"] = {
        "resource_spec_sha256": EXPECTED_SPEC_SHA256,
        "inherited_scientific_spec_sha256": spec["inherits_scientific_spec"]["sha256"],
        "inherited_year_batch_spec_sha256": spec[
            "inherits_year_batched_engineering"
        ]["sha256"],
        "panel_sha256": sha256_file(PANEL_PATH),
    }
    report = rank001._report(result).replace("MKT-DISP-RANK-001", "MKT-DISP-RANK-003")
    report += (
        "\nExecution retained the exact frozen science and exact year batching. "
        "Only the predeclared machine-sized resource contract and verified external "
        "scratch filesystem differ from failed attempts 001/002. No portfolio rule "
        "was evaluated.\n"
    )
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(rank001._clean(result), indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )
    print(
        json.dumps(rank001._clean(result), indent=2, sort_keys=True, allow_nan=False)
    )


if __name__ == "__main__":
    main()
