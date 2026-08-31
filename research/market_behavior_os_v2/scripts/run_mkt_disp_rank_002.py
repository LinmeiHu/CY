#!/usr/bin/env python3
"""Exact year-batched engineering retry of MKT-DISP-RANK-001."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-RANK-002_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-002_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-002_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-RANK-002_industry_rank.md"
EXPECTED_SPEC_SHA256 = "b3fe4a343dbd1f438852a033d78621f1290ec74b6e4dce31e6e5305c75571480"


class DispersionRankBatchError(RuntimeError):
    """Fail-closed exact batched rank response error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def _import_runner(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise DispersionRankBatchError(f"cannot import {path.name}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _load_spec() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Any, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionRankBatchError("batch retry spec identity mismatch")
    retry = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        retry.get("status") != "FROZEN_EXACT_YEAR_BATCHED_ENGINEERING_RETRY"
        or retry.get("scientific_changes") != "NONE"
    ):
        raise DispersionRankBatchError("batch retry engineering boundary changed")
    inherited_path = _resolve(retry["inherits_scientific_spec"]["path"])
    if sha256_file(inherited_path) != retry["inherits_scientific_spec"]["sha256"]:
        raise DispersionRankBatchError("inherited scientific spec identity mismatch")
    rank001 = _import_runner(
        "mkt_disp_rank_001_for_batch", PROGRAM / "scripts/run_mkt_disp_rank_001.py"
    )
    scientific, industry_spec, industry_runner = rank001._load_spec()
    if scientific.get("experiment_id") != "MKT-DISP-RANK-001":
        raise DispersionRankBatchError("wrong inherited experiment")
    expected_context = {
        int(year): [int(value) for value in values]
        for year, values in retry["engineering_change"]["year_context"].items()
    }
    if expected_context != {
        2018: [2018, 2019],
        2019: [2018, 2019, 2020],
        2020: [2019, 2020, 2021],
        2021: [2020, 2021, 2022],
        2022: [2021, 2022, 2023],
        2023: [2022, 2023],
    }:
        raise DispersionRankBatchError("year context changed")
    return retry, scientific, industry_spec, industry_runner, rank001


def _create_rank_security_for_year(
    connection: duckdb.DuckDBPyConnection, anchor_year: int
) -> None:
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
        GROUP BY ALL
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
        raise DispersionRankBatchError("invalid future rank response")
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


def _configure(
    connection: duckdb.DuckDBPyConnection,
    scientific: dict[str, Any],
    temp_dir: Path,
) -> None:
    resource = scientific["resource"]
    connection.execute(f"SET threads={resource['duckdb_threads']}")
    connection.execute(f"SET memory_limit='{resource['duckdb_memory_limit_mb']}MB'")
    connection.execute("SET preserve_insertion_order=false")
    escaped = str(temp_dir).replace("'", "''")
    connection.execute(f"SET temp_directory='{escaped}'")


def _source_year(path: Path) -> int:
    for part in path.parts:
        if part.startswith("partition_year="):
            return int(part.split("=", 1)[1])
    raise DispersionRankBatchError(f"cannot identify partition year: {path}")


def _build_daily_batched(
    retry: dict[str, Any],
    scientific: dict[str, Any],
    industry_spec: dict[str, Any],
    industry_runner: Any,
    rank001: Any,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.monotonic()
    rank001._guard(scientific, None, started, prelaunch=True)
    paths, observed_hashes = industry_runner._verify_inputs(industry_spec)
    path_by_year = {_source_year(path): path for path in paths}
    if set(path_by_year) != set(scientific["source"]["years"]):
        raise DispersionRankBatchError("exact source year set changed")

    with tempfile.TemporaryDirectory(prefix="mkt-disp-rank-002-audit-") as raw_temp:
        temp_dir = Path(raw_temp)
        connection = duckdb.connect()
        _configure(connection, scientific, temp_dir)
        try:
            industry_runner._create_source_view(connection, paths)
            source_audit = industry_runner._audit_source(connection, industry_spec)
        finally:
            connection.close()
        rank001._guard(scientific, temp_dir, started)

    contexts = {
        int(year): [int(value) for value in values]
        for year, values in retry["engineering_change"]["year_context"].items()
    }
    views = {
        "ALL_A": "symbol LIKE '%.SH' OR symbol LIKE '%.SZ'",
        "SH_A": "symbol LIKE '%.SH'",
        "SZ_A": "symbol LIKE '%.SZ'",
        "CHINEXT_BOARD": (
            "symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')"
        ),
    }
    denominators = {"ALL_STATUS": "TRUE", "NON_ST": "is_st IS FALSE"}
    pieces: list[pd.DataFrame] = []
    batch_rows: dict[str, int] = {}
    batch_spill_bytes: dict[str, int] = {}
    for anchor_year, context_years in contexts.items():
        rank001._guard(scientific, None, started)
        selected = [path_by_year[year] for year in context_years]
        with tempfile.TemporaryDirectory(prefix=f"mkt-disp-rank-002-{anchor_year}-") as raw_temp:
            temp_dir = Path(raw_temp)
            connection = duckdb.connect()
            _configure(connection, scientific, temp_dir)
            year_pieces: list[pd.DataFrame] = []
            try:
                industry_runner._create_source_view(connection, selected)
                industry_runner._create_security_states(connection)
                rank001._guard(scientific, temp_dir, started)
                _create_rank_security_for_year(connection, anchor_year)
                rank001._guard(scientific, temp_dir, started)
                for view, view_filter in views.items():
                    for denominator, denominator_filter in denominators.items():
                        item = connection.execute(
                            rank001._cell_query(view_filter, denominator_filter)
                        ).fetchdf()
                        item["market_view"] = view
                        item["denominator"] = denominator
                        year_pieces.append(item)
                        rank001._guard(scientific, temp_dir, started)
            finally:
                connection.close()
            batch_spill_bytes[str(anchor_year)] = rank001._directory_bytes(temp_dir)
        batch = pd.concat(year_pieces, ignore_index=True)
        batch["trade_date"] = pd.to_datetime(batch.trade_date)
        if not batch.trade_date.dt.year.eq(anchor_year).all():
            raise DispersionRankBatchError(f"anchor-year leakage: {anchor_year}")
        batch_rows[str(anchor_year)] = len(batch)
        pieces.append(batch)
    daily = pd.concat(pieces, ignore_index=True).sort_values(rank001.KEYS).reset_index(drop=True)
    if daily.duplicated(rank001.KEYS).any():
        raise DispersionRankBatchError("cross-batch duplicate daily key")
    telemetry = {
        "source_audit": source_audit,
        "source_partition_sha256": observed_hashes,
        "batch_rows": batch_rows,
        "batch_spill_bytes": batch_spill_bytes,
        "peak_rss_bytes": rank001._peak_rss_bytes(),
        "wall_seconds": time.monotonic() - started,
    }
    return daily, telemetry


def main() -> None:
    retry, scientific, industry_spec, industry_runner, rank001 = _load_spec()
    daily, telemetry = _build_daily_batched(
        retry, scientific, industry_spec, industry_runner, rank001
    )
    panel, result = rank001._analyze(daily, scientific)
    result["experiment_id"] = retry["experiment_id"]
    result["research_level"] = retry["research_level"]
    result["status"] = "COMPLETE_EXACT_YEAR_BATCHED_ENGINEERING_RETRY"
    result["supersedes_execution"] = retry["supersedes_execution"]
    result["scientific_changes"] = "NONE"
    result["engineering"] = telemetry
    result["hashes"] = {
        "retry_spec_sha256": EXPECTED_SPEC_SHA256,
        "inherited_scientific_spec_sha256": retry["inherits_scientific_spec"]["sha256"],
    }
    panel_csv = panel.to_csv(index=False, lineterminator="\n", float_format="%.12g")
    _atomic_write(PANEL_PATH, panel_csv)
    result["hashes"]["panel_sha256"] = sha256_file(PANEL_PATH)
    report = rank001._report(result).replace("MKT-DISP-RANK-001", "MKT-DISP-RANK-002")
    report += (
        "\nExecution used the frozen exact year-batched engineering retry; scientific "
        "definitions and resource floors were unchanged.\n"
    )
    _atomic_write(REPORT_PATH, report)
    result["hashes"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(
        RESULT_PATH,
        json.dumps(rank001._clean(result), indent=2, sort_keys=True, allow_nan=False) + "\n",
    )
    print(json.dumps(rank001._clean(result), indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
