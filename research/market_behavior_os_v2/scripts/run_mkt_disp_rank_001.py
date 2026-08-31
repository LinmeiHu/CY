#!/usr/bin/env python3
"""Test frozen continuation versus reversal inside the dispersion candidate."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import platform
import resource
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import psutil
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-DISP-RANK-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-DISP-RANK-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-DISP-RANK-001_industry_rank.md"
EXPECTED_SPEC_SHA256 = "502d5db1779fad76f73b45a4f6587c79398fb198a7a19f6404a6e2f7e92ac57c"
STATE = "industry_return_dispersion_iqr_pit_3y_pct"
KEYS = ["trade_date", "market_view", "denominator"]


class DispersionRankError(RuntimeError):
    """Fail-closed industry-rank response error."""


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


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _guard(spec: dict[str, Any], temp_dir: Path | None, started: float, prelaunch: bool = False) -> None:
    budget = spec["resource"]
    floor = budget[
        "prelaunch_available_memory_floor_gib" if prelaunch else "in_run_available_memory_floor_gib"
    ]
    available = psutil.virtual_memory().available
    if available < int(floor * 2**30):
        raise DispersionRankError(
            f"system memory below frozen floor: available={available}, floor_gib={floor}"
        )
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise DispersionRankError("process peak RSS ceiling breached")
    if temp_dir is not None and _directory_bytes(temp_dir) > int(
        budget["temporary_spill_ceiling_gib"] * 2**30
    ):
        raise DispersionRankError("temporary spill ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise DispersionRankError("wall-clock ceiling breached")


def _load_spec() -> tuple[dict[str, Any], dict[str, Any], Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise DispersionRankError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_INDUSTRY_RANK_RESPONSE":
        raise DispersionRankError("rank response is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise DispersionRankError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited"])
    for phrase in ("same-bar fill", "post-2023", "CY-011"):
        if phrase not in forbidden:
            raise DispersionRankError(f"missing prohibition: {phrase}")
    parent = json.loads(_resolve(spec["inputs"]["industry_spec"]["path"]).read_text())
    path = PROGRAM / "scripts/run_mkt_indrs_001.py"
    module_spec = importlib.util.spec_from_file_location("accepted_industry_rank_source", path)
    if module_spec is None or module_spec.loader is None:
        raise DispersionRankError("cannot load accepted industry construction")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return spec, parent, module


def _create_rank_security(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE rank_anchor AS
        SELECT trade_date,cal_idx,symbol,is_st,causal_industry,
               exp(step_log_return)-1 AS current_return1,adjusted_close AS coordinate_close_t
        FROM stock_lagged
        WHERE current_valid AND history_valid
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
    bad = connection.execute(
        """SELECT count(*) FROM rank_security WHERE NOT (
             isfinite(future_return_h1) AND isfinite(future_return_h3)
             AND isfinite(future_return_h5))"""
    ).fetchone()[0]
    if int(bad):
        raise DispersionRankError("invalid future rank response")
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


def _cell_query(view_filter: str, denominator_filter: str) -> str:
    return f"""
        WITH anchors AS (
          SELECT trade_date,causal_industry,count(*) AS anchor_count,
                 median(current_return1) AS current_industry_return
          FROM rank_anchor WHERE ({view_filter}) AND ({denominator_filter})
          GROUP BY 1,2 HAVING count(*)>=5
        ), responses AS (
          SELECT trade_date,causal_industry,count(*) AS response_count,
                 median(future_return_h1) AS future_industry_h1,
                 median(future_return_h3) AS future_industry_h3,
                 median(future_return_h5) AS future_industry_h5
          FROM rank_security WHERE ({view_filter}) AND ({denominator_filter})
          GROUP BY 1,2
        ), valid AS (
          SELECT a.*,r.response_count,r.future_industry_h1,r.future_industry_h3,
                 r.future_industry_h5
          FROM anchors a JOIN responses r USING(trade_date,causal_industry)
          WHERE r.response_count>=5 AND r.response_count::DOUBLE/a.anchor_count>=0.8
        ), ranked0 AS (
          SELECT *,ntile(5) OVER (PARTITION BY trade_date ORDER BY current_industry_return)
                   AS current_quintile,
                 rank() OVER (PARTITION BY trade_date ORDER BY current_industry_return)
                  +(count(*) OVER (PARTITION BY trade_date,current_industry_return)-1)/2.0
                   AS current_rank,
                 rank() OVER (PARTITION BY trade_date ORDER BY future_industry_h1)
                  +(count(*) OVER (PARTITION BY trade_date,future_industry_h1)-1)/2.0
                   AS future_rank_h1,
                 rank() OVER (PARTITION BY trade_date ORDER BY future_industry_h3)
                  +(count(*) OVER (PARTITION BY trade_date,future_industry_h3)-1)/2.0
                   AS future_rank_h3,
                 rank() OVER (PARTITION BY trade_date ORDER BY future_industry_h5)
                  +(count(*) OVER (PARTITION BY trade_date,future_industry_h5)-1)/2.0
                   AS future_rank_h5
          FROM valid
        )
        SELECT trade_date,count(*) AS industry_count,
               min(response_count::DOUBLE/anchor_count) AS minimum_industry_retention,
               corr(current_rank,future_rank_h1) AS rank_ic_h1,
               corr(current_rank,future_rank_h3) AS rank_ic_h3,
               corr(current_rank,future_rank_h5) AS rank_ic_h5,
               avg(future_industry_h1) FILTER(current_quintile=5)
                 -avg(future_industry_h1) FILTER(current_quintile=1) AS top_bottom_h1,
               avg(future_industry_h3) FILTER(current_quintile=5)
                 -avg(future_industry_h3) FILTER(current_quintile=1) AS top_bottom_h3,
               avg(future_industry_h5) FILTER(current_quintile=5)
                 -avg(future_industry_h5) FILTER(current_quintile=1) AS top_bottom_h5
        FROM ranked0 GROUP BY trade_date HAVING count(*)>=10 ORDER BY trade_date
    """


def _build_daily(spec: dict[str, Any], parent: dict[str, Any], module: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.monotonic()
    _guard(spec, None, started, prelaunch=True)
    paths, observed_hashes = module._verify_inputs(parent)
    with tempfile.TemporaryDirectory(prefix="mkt-disp-rank-") as raw_temp:
        temp_dir = Path(raw_temp)
        connection = duckdb.connect()
        connection.execute(f"SET threads={spec['resource']['duckdb_threads']}")
        connection.execute(f"SET memory_limit='{spec['resource']['duckdb_memory_limit_mb']}MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped = str(temp_dir).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped}'")
        try:
            module._create_source_view(connection, paths)
            source_audit = module._audit_source(connection, parent)
            if source_audit["rows"] != spec["source"]["expected_rows"]:
                raise DispersionRankError("source rows changed")
            _guard(spec, temp_dir, started)
            module._create_security_states(connection)
            _guard(spec, temp_dir, started)
            _create_rank_security(connection)
            _guard(spec, temp_dir, started)
            views = {
                "ALL_A": "symbol LIKE '%.SH' OR symbol LIKE '%.SZ'",
                "SH_A": "symbol LIKE '%.SH'",
                "SZ_A": "symbol LIKE '%.SZ'",
                "CHINEXT_BOARD": "symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')",
            }
            denominators = {"ALL_STATUS": "TRUE", "NON_ST": "is_st IS FALSE"}
            pieces: list[pd.DataFrame] = []
            for view, view_filter in views.items():
                for denominator, denominator_filter in denominators.items():
                    item = connection.execute(_cell_query(view_filter, denominator_filter)).fetchdf()
                    item["market_view"] = view
                    item["denominator"] = denominator
                    pieces.append(item)
                    _guard(spec, temp_dir, started)
            daily = pd.concat(pieces, ignore_index=True)
        finally:
            connection.close()
        spill_bytes = _directory_bytes(temp_dir)
    telemetry = {
        "source_audit": source_audit,
        "source_partition_sha256": observed_hashes,
        "peak_rss_bytes": _peak_rss_bytes(),
        "spill_bytes_at_close": spill_bytes,
        "wall_seconds": time.monotonic() - started,
    }
    return daily, telemetry


def _median_by_cell(frame: pd.DataFrame, column: str) -> tuple[float, list[float]]:
    values = [float(group[column].median()) for _, group in frame.groupby(KEYS[1:], sort=True)]
    return float(np.median(values)), values


def _analyze(daily: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    state = pd.read_csv(
        _resolve(spec["inputs"]["industry_panel"]["path"]), parse_dates=["trade_date"]
    )[[*KEYS, STATE]]
    daily["trade_date"] = pd.to_datetime(daily["trade_date"])
    panel = daily.merge(state, on=KEYS, how="left", validate="one_to_one")
    panel = panel.sort_values(KEYS).reset_index(drop=True)
    panel["calendar_year"] = panel.trade_date.dt.year
    panel["session_ordinal"] = panel.groupby(KEYS[1:], sort=False).cumcount()
    support = spec["support"]
    cell_counts = panel.groupby(KEYS[1:]).size()
    pit = panel.dropna(subset=[STATE]).copy()
    pit_counts = pit.groupby(KEYS[1:]).size()
    high = pit.loc[pit[STATE].ge(0.8)].copy()
    low = pit.loc[pit[STATE].le(0.2)].copy()
    high_counts = high.groupby(KEYS[1:]).size()
    low_counts = low.groupby(KEYS[1:]).size()
    if (
        len(cell_counts) != 8
        or cell_counts.min() < support["minimum_daily_rows_per_cell"]
        or pit_counts.min() < support["minimum_pit_rows_per_cell"]
        or high_counts.min() < support["minimum_high_state_rows_per_cell"]
        or low_counts.min() < support["minimum_low_state_rows_per_cell"]
    ):
        raise DispersionRankError("daily/PIT/tail support gate failed")
    annual_high = high.groupby(["calendar_year", *KEYS[1:]]).size()
    supported_annual = annual_high.loc[annual_high.index.get_level_values(0).isin([2020, 2021, 2022, 2023])]
    if supported_annual.min() < support["minimum_high_state_rows_per_cell_year"]:
        raise DispersionRankError("annual high-state support gate failed")

    high_summary: dict[str, Any] = {}
    low_summary: dict[str, Any] = {}
    for horizon in (1, 3, 5):
        high_median, high_cells = _median_by_cell(high, f"rank_ic_h{horizon}")
        low_median, low_cells = _median_by_cell(low, f"rank_ic_h{horizon}")
        high_spread, high_spread_cells = _median_by_cell(high, f"top_bottom_h{horizon}")
        high_summary[str(horizon)] = {
            "median_cell_rank_ic": high_median,
            "cell_rank_ics": high_cells,
            "median_cell_top_bottom_attribution": high_spread,
            "cell_top_bottom_attributions": high_spread_cells,
        }
        low_summary[str(horizon)] = {
            "median_cell_rank_ic": low_median,
            "cell_rank_ics": low_cells,
        }
    annual: dict[str, float] = {}
    for year, annual_frame in high.groupby("calendar_year", sort=True):
        if int(year) in (2020, 2021, 2022, 2023):
            annual[str(year)] = _median_by_cell(annual_frame, "rank_ic_h3")[0]
    phases: dict[str, float] = {}
    for phase in range(3):
        phases[str(phase)] = _median_by_cell(
            high.loc[high.session_ordinal.mod(3).eq(phase)], "rank_ic_h3"
        )[0]
    state_ic_cells: list[float] = []
    for _, cell in pit.groupby(KEYS[1:], sort=True):
        state_ic_cells.append(float(spearmanr(cell[STATE], cell["rank_ic_h3"]).statistic))
    boundary = spec["classification"]
    h3 = high_summary["3"]["median_cell_rank_ic"]
    continuation = (
        h3 >= boundary["continuation_minimum_absolute_median_high_state_ic"]
        and all(value > 0 for value in high_summary["3"]["cell_rank_ics"])
        and all(value > 0 for value in annual.values())
        and high_summary["1"]["median_cell_rank_ic"] >= 0
        and high_summary["5"]["median_cell_rank_ic"] >= 0
        and all(value > 0 for value in phases.values())
    )
    reversal = (
        h3 <= boundary["reversal_maximum_median_high_state_ic"]
        and all(value < 0 for value in high_summary["3"]["cell_rank_ics"])
        and all(value < 0 for value in annual.values())
        and high_summary["1"]["median_cell_rank_ic"] <= 0
        and high_summary["5"]["median_cell_rank_ic"] <= 0
        and all(value < 0 for value in phases.values())
    )
    classification = (
        "HIGH_DISPERSION_INDUSTRY_RANK_CONTINUATION"
        if continuation
        else "HIGH_DISPERSION_INDUSTRY_RANK_REVERSAL"
        if reversal
        else "HIGH_DISPERSION_DIRECTIONLESS_OR_UNSTABLE_RANKING"
    )
    result = {
        "experiment_id": "MKT-DISP-RANK-001",
        "research_level": "EXPLORE",
        "classification": classification,
        "high_dispersion": high_summary,
        "low_dispersion": low_summary,
        "high_dispersion_annual_h3_median_cell_rank_ic": annual,
        "high_dispersion_h3_nonoverlap_phase_median_cell_rank_ic": phases,
        "dispersion_state_to_h3_rank_ic": {
            "median_cell_spearman": float(np.median(state_ic_cells)),
            "cell_spearmans": state_ic_cells,
        },
        "support": {
            "panel_rows": len(panel),
            "minimum_daily_rows_per_cell": int(cell_counts.min()),
            "minimum_pit_rows_per_cell": int(pit_counts.min()),
            "minimum_high_rows_per_cell": int(high_counts.min()),
            "minimum_low_rows_per_cell": int(low_counts.min()),
            "minimum_high_rows_per_supported_cell_year": int(supported_annual.min()),
            "minimum_industries_per_date_cell": int(panel.industry_count.min()),
            "minimum_industry_response_retention": float(panel.minimum_industry_retention.min()),
        },
        "interpretation": {
            "industry_rank_direction_established": continuation or reversal,
            "security_selection_estimated": False,
            "portfolio_pnl_estimated": False,
            "strategy_authorized": False,
        },
        "same_bar_fill_assumed": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
    }
    return panel, result


def _report(result: dict[str, Any]) -> str:
    high = result["high_dispersion"]
    return f"""# MKT-DISP-RANK-001 industry rank discriminator

`{result['classification']}`. In the fixed high-dispersion state, median cell
industry rank IC at h=1/3/5 is {high['1']['median_cell_rank_ic']:.5f},
{high['3']['median_cell_rank_ic']:.5f}, and
{high['5']['median_cell_rank_ic']:.5f}. The h=3 top-minus-bottom industry
attribution is {high['3']['median_cell_top_bottom_attribution']:.5f}.

These are future industry-response attributions using t membership, not
realizable portfolio returns. No same-bar fill, security selection, PnL, cost,
capacity, strategy outcome, post-2023 row, or CY-011 field is used.
"""


def main() -> None:
    spec, parent, module = _load_spec()
    daily, telemetry = _build_daily(spec, parent, module)
    panel, result = _analyze(daily, spec)
    _atomic_write(PANEL_PATH, panel.to_csv(index=False, float_format="%.12g", lineterminator="\n"))
    result["resource_telemetry"] = telemetry
    result["hashes"] = {
        "spec_sha256": EXPECTED_SPEC_SHA256,
        "panel_sha256": sha256_file(PANEL_PATH),
        "inputs": {name: binding["sha256"] for name, binding in spec["inputs"].items()},
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _report(result))


if __name__ == "__main__":
    main()
