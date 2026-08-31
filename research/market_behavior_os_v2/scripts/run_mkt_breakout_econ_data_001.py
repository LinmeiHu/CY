#!/usr/bin/env python3
"""Build the frozen objective-crossing future market-response domain."""

from __future__ import annotations

import hashlib
import importlib.util
import json
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

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-ECON-DATA-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-DATA-001_panel.csv"
COUNT_AUDIT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-DATA-001_count_audit.csv"
SCALAR_AUDIT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-DATA-001_scalar_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-ECON-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "251c9e3a386857ce61d7720e2d7f51554f916a3cf8dec782c9624f413ec6dbf0"


class EconomicResponseDataError(RuntimeError):
    """Fail-closed objective-crossing market-response data error."""


class _PreserveCoordinateWindow:
    """Retain the accepted helper's coordinate table for frozen future mapping."""

    def __init__(self, connection: duckdb.DuckDBPyConnection) -> None:
        self.connection = connection

    def execute(self, query: str, *args: Any, **kwargs: Any) -> Any:
        if query.strip().upper() == "DROP TABLE COORDINATE_WINDOW":
            return self.connection
        return self.connection.execute(query, *args, **kwargs)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
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
        raise EconomicResponseDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_FUTURE_RETURN_OR_DOWNSIDE_CONSTRUCTION"
        or spec["outcome_access"]
        != "FUTURE_PRE2024_MARKET_RETURN_AND_DOWNSIDE_CONSTRUCTION_ONLY"
    ):
        raise EconomicResponseDataError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise EconomicResponseDataError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise EconomicResponseDataError("prohibited-input boundary changed")
    return spec


def _load_coordinate_module(spec: dict[str, Any]) -> Any:
    binding = spec["inputs"]["accepted_coordinate_runner"]
    path = _resolve(binding["path"])
    module_spec = importlib.util.spec_from_file_location("accepted_breakout_coordinate", path)
    if module_spec is None or module_spec.loader is None:
        raise EconomicResponseDataError("accepted coordinate runner cannot be loaded")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _preflight_resource_guard(spec: dict[str, Any], paths: list[Path]) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise EconomicResponseDataError("system memory headroom below frozen floor")
    usage = shutil.disk_usage(ROOT)
    if usage.free / usage.total < float(budget["filesystem_headroom_fraction"]):
        raise EconomicResponseDataError("filesystem headroom below frozen floor")
    if sum(path.stat().st_size for path in paths) > int(
        budget["compressed_read_ceiling_gib"] * 2**30
    ):
        raise EconomicResponseDataError("compressed source exceeds frozen ceiling")


def _phase_resource_guard(spec: dict[str, Any], temp_dir: Path, started: float) -> None:
    budget = spec["resource_budget"]
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise EconomicResponseDataError("process peak RSS ceiling breached")
    if _directory_bytes(temp_dir) > int(budget["temporary_spill_ceiling_gib"] * 2**30):
        raise EconomicResponseDataError("temporary spill ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60.0:
        raise EconomicResponseDataError("wall-clock ceiling breached")


def _verify_partitions(
    spec: dict[str, Any], coordinate_module: Any
) -> tuple[list[Path], dict[str, str]]:
    try:
        return coordinate_module._verify_registry_and_partitions(spec)
    except Exception as exc:
        raise EconomicResponseDataError(str(exc)) from exc


def _audit_predictor(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = _resolve(spec["inputs"]["predictor_panel"]["path"])
    predictor = pd.read_csv(path, parse_dates=["trade_date"])
    expected = spec["predictor_audit"]
    keys = ["trade_date", "market_view", "denominator"]
    audit = {
        "rows": int(len(predictor)),
        "dates": int(predictor["trade_date"].nunique()),
        "first_date": predictor["trade_date"].min().strftime("%Y-%m-%d"),
        "last_date": predictor["trade_date"].max().strftime("%Y-%m-%d"),
        "views": sorted(predictor["market_view"].unique().tolist()),
        "denominators": sorted(predictor["denominator"].unique().tolist()),
        "duplicate_keys": int(predictor.duplicated(keys).sum()),
        "snapshot_ids": sorted(predictor["snapshot_id"].unique().tolist()),
        "available_after_decision": int(
            (
                pd.to_datetime(predictor["available_at"], utc=True)
                > pd.to_datetime(predictor["decision_at"], utc=True)
            ).sum()
        ),
    }
    comparisons = {
        "rows": expected["expected_rows"],
        "dates": expected["expected_dates"],
        "first_date": expected["expected_first_date"],
        "last_date": expected["expected_last_date"],
        "views": sorted(expected["expected_views"]),
        "denominators": sorted(expected["expected_denominators"]),
        "duplicate_keys": expected["duplicate_keys"],
        "snapshot_ids": [expected["snapshot_id"]],
        "available_after_decision": 0,
    }
    if any(audit[key] != value for key, value in comparisons.items()):
        raise EconomicResponseDataError(f"predictor audit mismatch: {audit}")
    result = json.loads(_resolve(spec["inputs"]["predictor_result"]["path"]).read_text())
    if result["minimal_panel"]["accepted_roles"] != list(spec["roles"]):
        raise EconomicResponseDataError("seven-role predictor activation changed")
    required = set(spec["roles"].values()) | {
        f"{field}_pit_3y_pct" for field in spec["roles"].values()
    }
    if not required.issubset(predictor.columns):
        raise EconomicResponseDataError("required predictor coordinate missing")
    return predictor, audit


def _create_future_coordinate(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE future_coordinate AS
        SELECT symbol,cal_idx,history_valid,coordinate_step_valid,coordinate_close,
               low AS raw_low,close AS raw_close,
               coordinate_close*(low/close) AS mapped_low
        FROM coordinate_window
        """
    )
    connection.execute("DROP TABLE coordinate_window")


def _create_response_security(
    connection: duckdb.DuckDBPyConnection, event_year: int
) -> None:
    for table in ("response_security", "response_path_next", "response_path"):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    bounds = connection.execute(
        "SELECT min(cal_idx),max(cal_idx) FROM event_security WHERE year(trade_date)=?",
        [event_year],
    ).fetchone()
    if bounds[0] is None:
        raise EconomicResponseDataError(f"no anchor rows for event year {event_year}")
    minimum_cal_idx, maximum_cal_idx = int(bounds[0]), int(bounds[1])
    connection.execute(
        """
        CREATE TEMP TABLE response_path AS
        SELECT trade_date,cal_idx,symbol,is_st,
               coordinate_close AS coordinate_close_t
        FROM event_security WHERE year(trade_date)=?
        """,
        [event_year],
    )
    for offset in range(1, 6):
        connection.execute(
            f"""
            CREATE TEMP TABLE response_path_next AS
            SELECT p.*,f.coordinate_close AS coordinate_close_t{offset},
                   f.mapped_low AS mapped_low_t{offset}
            FROM response_path p JOIN future_coordinate f
              ON f.symbol=p.symbol AND f.cal_idx=p.cal_idx+{offset}
            WHERE f.cal_idx BETWEEN {minimum_cal_idx + 1} AND {maximum_cal_idx + 5}
              AND f.history_valid AND f.coordinate_step_valid
              AND isfinite(f.coordinate_close) AND f.coordinate_close>0
              AND isfinite(f.mapped_low) AND f.mapped_low>0
            """
        )
        connection.execute("DROP TABLE response_path")
        connection.execute("ALTER TABLE response_path_next RENAME TO response_path")
    connection.execute(
        """
        CREATE TEMP TABLE response_security AS
        SELECT *,
               ln(coordinate_close_t1/coordinate_close_t) AS terminal_log_return_h1,
               ln(coordinate_close_t3/coordinate_close_t) AS terminal_log_return_h3,
               ln(coordinate_close_t5/coordinate_close_t) AS terminal_log_return_h5,
               ln(mapped_low_t1/coordinate_close_t) AS adverse_log_excursion_h1,
               least(ln(mapped_low_t1/coordinate_close_t),
                     ln(mapped_low_t2/coordinate_close_t),
                     ln(mapped_low_t3/coordinate_close_t)) AS adverse_log_excursion_h3,
               least(ln(mapped_low_t1/coordinate_close_t),
                     ln(mapped_low_t2/coordinate_close_t),
                     ln(mapped_low_t3/coordinate_close_t),
                     ln(mapped_low_t4/coordinate_close_t),
                     ln(mapped_low_t5/coordinate_close_t)) AS adverse_log_excursion_h5
        FROM response_path
        """
    )
    connection.execute("DROP TABLE response_path")
    diagnostic = connection.execute(
        """
        SELECT count(*) AS invalid_rows,
          sum((NOT isfinite(terminal_log_return_h1))::INTEGER) AS bad_return_h1,
          sum((NOT isfinite(terminal_log_return_h3))::INTEGER) AS bad_return_h3,
          sum((NOT isfinite(terminal_log_return_h5))::INTEGER) AS bad_return_h5,
          sum((NOT isfinite(adverse_log_excursion_h1))::INTEGER) AS bad_adverse_h1,
          sum((NOT isfinite(adverse_log_excursion_h3))::INTEGER) AS bad_adverse_h3,
          sum((NOT isfinite(adverse_log_excursion_h5))::INTEGER) AS bad_adverse_h5,
          sum((adverse_log_excursion_h1>terminal_log_return_h1)::INTEGER)
            AS adverse_above_terminal_h1,
          sum((adverse_log_excursion_h3>terminal_log_return_h3)::INTEGER)
            AS adverse_above_terminal_h3,
          sum((adverse_log_excursion_h5>terminal_log_return_h5)::INTEGER)
            AS adverse_above_terminal_h5,
          sum((adverse_log_excursion_h3>adverse_log_excursion_h1)::INTEGER)
            AS adverse_order_h3,
          sum((adverse_log_excursion_h5>adverse_log_excursion_h3)::INTEGER)
            AS adverse_order_h5,
          max(adverse_log_excursion_h1-terminal_log_return_h1)
            FILTER (adverse_log_excursion_h1>terminal_log_return_h1) AS max_gap_h1,
          max(adverse_log_excursion_h3-terminal_log_return_h3)
            FILTER (adverse_log_excursion_h3>terminal_log_return_h3) AS max_gap_h3,
          max(adverse_log_excursion_h5-terminal_log_return_h5)
            FILTER (adverse_log_excursion_h5>terminal_log_return_h5) AS max_gap_h5
        FROM response_security
        WHERE NOT (
          isfinite(terminal_log_return_h1) AND isfinite(terminal_log_return_h3)
          AND isfinite(terminal_log_return_h5)
          AND isfinite(adverse_log_excursion_h1)
          AND isfinite(adverse_log_excursion_h3)
          AND isfinite(adverse_log_excursion_h5)
          AND adverse_log_excursion_h1<=terminal_log_return_h1
          AND adverse_log_excursion_h3<=terminal_log_return_h3
          AND adverse_log_excursion_h5<=terminal_log_return_h5
          AND adverse_log_excursion_h3<=adverse_log_excursion_h1
          AND adverse_log_excursion_h5<=adverse_log_excursion_h3)
        """
    ).fetchone()
    if int(diagnostic[0]) != 0:
        raise EconomicResponseDataError(
            f"future response coordinate conservation failed: {tuple(diagnostic)}"
        )


def _group_frames(
    connection: duckdb.DuckDBPyConnection, event_year: int
) -> pd.DataFrame:
    views = {
        "ALL_A": "(symbol LIKE '%.SH' OR symbol LIKE '%.SZ')",
        "SH_A": "symbol LIKE '%.SH'",
        "SZ_A": "symbol LIKE '%.SZ'",
        "CHINEXT_BOARD": (
            "symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')"
        ),
    }
    denominators = {"ALL_STATUS": "TRUE", "NON_ST": "is_st IS FALSE"}
    frames: list[pd.DataFrame] = []
    for view, view_filter in views.items():
        for denominator, denominator_filter in denominators.items():
            where = f"({view_filter}) AND ({denominator_filter})"
            anchor_where = f"({where}) AND year(trade_date)={event_year}"
            frame = connection.execute(
                f"""
                WITH anchors AS (
                  SELECT trade_date,count(*) AS anchor_count
                  FROM event_security WHERE {anchor_where} GROUP BY trade_date
                ), responses AS (
                  SELECT trade_date,count(*) AS response_count,
                    avg(terminal_log_return_h1) AS terminal_mean_log_return_h1,
                    avg(terminal_log_return_h3) AS terminal_mean_log_return_h3,
                    avg(terminal_log_return_h5) AS terminal_mean_log_return_h5,
                    median(terminal_log_return_h1) AS terminal_median_log_return_h1,
                    median(terminal_log_return_h3) AS terminal_median_log_return_h3,
                    median(terminal_log_return_h5) AS terminal_median_log_return_h5,
                    avg((terminal_log_return_h1>0)::INTEGER) AS terminal_positive_fraction_h1,
                    avg((terminal_log_return_h3>0)::INTEGER) AS terminal_positive_fraction_h3,
                    avg((terminal_log_return_h5>0)::INTEGER) AS terminal_positive_fraction_h5,
                    quantile_cont(terminal_log_return_h1,0.1) AS terminal_p10_log_return_h1,
                    quantile_cont(terminal_log_return_h3,0.1) AS terminal_p10_log_return_h3,
                    quantile_cont(terminal_log_return_h5,0.1) AS terminal_p10_log_return_h5,
                    quantile_cont(terminal_log_return_h1,0.9) AS terminal_p90_log_return_h1,
                    quantile_cont(terminal_log_return_h3,0.9) AS terminal_p90_log_return_h3,
                    quantile_cont(terminal_log_return_h5,0.9) AS terminal_p90_log_return_h5,
                    avg(adverse_log_excursion_h1) AS adverse_mean_log_excursion_h1,
                    avg(adverse_log_excursion_h3) AS adverse_mean_log_excursion_h3,
                    avg(adverse_log_excursion_h5) AS adverse_mean_log_excursion_h5,
                    median(adverse_log_excursion_h1) AS adverse_median_log_excursion_h1,
                    median(adverse_log_excursion_h3) AS adverse_median_log_excursion_h3,
                    median(adverse_log_excursion_h5) AS adverse_median_log_excursion_h5,
                    quantile_cont(adverse_log_excursion_h1,0.1) AS adverse_p10_log_excursion_h1,
                    quantile_cont(adverse_log_excursion_h3,0.1) AS adverse_p10_log_excursion_h3,
                    quantile_cont(adverse_log_excursion_h5,0.1) AS adverse_p10_log_excursion_h5
                  FROM response_security WHERE {where} GROUP BY trade_date
                )
                SELECT a.*,r.* EXCLUDE(trade_date)
                FROM anchors a LEFT JOIN responses r USING(trade_date)
                ORDER BY a.trade_date
                """
            ).fetchdf()
            frame["market_view"] = view
            frame["denominator"] = denominator
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _calendar_response_dates(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return connection.execute(
        """
        SELECT c0.trade_date,
               c1.trade_date AS response_date_h1,
               c3.trade_date AS response_date_h3,
               c5.trade_date AS response_date_h5
        FROM calendar c0
        LEFT JOIN calendar c1 ON c1.cal_idx=c0.cal_idx+1
        LEFT JOIN calendar c3 ON c3.cal_idx=c0.cal_idx+3
        LEFT JOIN calendar c5 ON c5.cal_idx=c0.cal_idx+5
        ORDER BY c0.trade_date
        """
    ).fetchdf()


def _scalar_audit(connection: duckdb.DuckDBPyConnection, spec: dict[str, Any]) -> pd.DataFrame:
    connection.execute("DROP TABLE IF EXISTS scalar_response_cases")
    connection.execute(
        """
        CREATE TEMP TABLE scalar_response_cases AS
        SELECT symbol,trade_date,cal_idx,
               sha256('MKT-BREAKOUT-ECON-DATA-001|' || symbol || '|' ||
                      strftime(trade_date,'%Y-%m-%d')) AS selection_hash
        FROM response_security
        ORDER BY selection_hash,symbol,trade_date
        LIMIT 5
        """
    )
    fields = spec["scalar_reconstruction"]["exact_fields"]
    aggregate = connection.execute(
        f"""
        SELECT c.symbol,c.trade_date,c.selection_hash,
               {','.join('r.' + field for field in fields)}
        FROM scalar_response_cases c JOIN response_security r USING(symbol,trade_date,cal_idx)
        ORDER BY c.selection_hash,c.symbol,c.trade_date
        """
    ).fetchdf()
    scalar_rows: list[pd.DataFrame] = []
    candidates = connection.execute(
        """
        SELECT symbol,trade_date,cal_idx,selection_hash
        FROM scalar_response_cases ORDER BY selection_hash,symbol,trade_date
        """
    ).fetchdf()
    for candidate in candidates.itertuples(index=False):
        scalar_rows.append(
            connection.execute(
                """
                WITH anchor AS (
                  SELECT symbol,trade_date,cal_idx,coordinate_close AS coordinate_close_t
                  FROM event_security WHERE symbol=? AND trade_date=? AND cal_idx=?
                ), path AS (
                  SELECT a.symbol,a.trade_date,a.coordinate_close_t,
                    max(CASE WHEN f.cal_idx=a.cal_idx+1 THEN f.coordinate_close END)
                      AS coordinate_close_t1,
                    max(CASE WHEN f.cal_idx=a.cal_idx+3 THEN f.coordinate_close END)
                      AS coordinate_close_t3,
                    max(CASE WHEN f.cal_idx=a.cal_idx+5 THEN f.coordinate_close END)
                      AS coordinate_close_t5,
                    max(CASE WHEN f.cal_idx=a.cal_idx+1
                             THEN f.coordinate_close*(f.raw_low/f.raw_close) END)
                      AS mapped_low_t1,
                    max(CASE WHEN f.cal_idx=a.cal_idx+2
                             THEN f.coordinate_close*(f.raw_low/f.raw_close) END)
                      AS mapped_low_t2,
                    max(CASE WHEN f.cal_idx=a.cal_idx+3
                             THEN f.coordinate_close*(f.raw_low/f.raw_close) END)
                      AS mapped_low_t3,
                    max(CASE WHEN f.cal_idx=a.cal_idx+4
                             THEN f.coordinate_close*(f.raw_low/f.raw_close) END)
                      AS mapped_low_t4,
                    max(CASE WHEN f.cal_idx=a.cal_idx+5
                             THEN f.coordinate_close*(f.raw_low/f.raw_close) END)
                      AS mapped_low_t5
                  FROM anchor a JOIN future_coordinate f ON f.symbol=a.symbol
                    AND f.cal_idx BETWEEN a.cal_idx+1 AND a.cal_idx+5
                  GROUP BY a.symbol,a.trade_date,a.coordinate_close_t
                )
                SELECT ? AS selection_hash,path.*,
                       ln(coordinate_close_t1/coordinate_close_t)
                         AS terminal_log_return_h1,
                       ln(coordinate_close_t3/coordinate_close_t)
                         AS terminal_log_return_h3,
                       ln(coordinate_close_t5/coordinate_close_t)
                         AS terminal_log_return_h5,
                       ln(mapped_low_t1/coordinate_close_t)
                         AS adverse_log_excursion_h1,
                       least(ln(mapped_low_t1/coordinate_close_t),
                             ln(mapped_low_t2/coordinate_close_t),
                             ln(mapped_low_t3/coordinate_close_t))
                         AS adverse_log_excursion_h3,
                       least(ln(mapped_low_t1/coordinate_close_t),
                             ln(mapped_low_t2/coordinate_close_t),
                             ln(mapped_low_t3/coordinate_close_t),
                             ln(mapped_low_t4/coordinate_close_t),
                             ln(mapped_low_t5/coordinate_close_t))
                         AS adverse_log_excursion_h5
                FROM path
                """,
                [
                    candidate.symbol,
                    candidate.trade_date,
                    int(candidate.cal_idx),
                    candidate.selection_hash,
                ],
            ).fetchdf()
        )
    scalar = pd.concat(scalar_rows, ignore_index=True).sort_values(
        ["selection_hash", "symbol", "trade_date"]
    ).reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    for idx in range(len(aggregate)):
        for field in fields:
            left = float(aggregate.loc[idx, field])
            right = float(scalar.loc[idx, field])
            rows.append(
                {
                    "symbol": aggregate.loc[idx, "symbol"],
                    "trade_date": aggregate.loc[idx, "trade_date"],
                    "selection_hash": aggregate.loc[idx, "selection_hash"],
                    "field": field,
                    "exact_match": bool(left == right),
                    "aggregate_hex": left.hex(),
                    "scalar_hex": right.hex(),
                }
            )
    output = pd.DataFrame(rows)
    if len(output) != len(fields) * 5 or not output["exact_match"].all():
        raise EconomicResponseDataError("five scalar response reconstructions failed")
    return output


def _assemble_panel(
    predictor: pd.DataFrame,
    grouped: pd.DataFrame,
    response_dates: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["trade_date", "market_view", "denominator"]
    lineage = predictor[
        keys
        + [
            "eligible_count20",
            "decision_at",
            "available_at",
            "snapshot_id",
        ]
    ].copy()
    grouped["trade_date"] = pd.to_datetime(grouped["trade_date"])
    response_dates["trade_date"] = pd.to_datetime(response_dates["trade_date"])
    output = lineage.merge(grouped, on=keys, how="left", validate="one_to_one")
    output = output.merge(response_dates, on="trade_date", how="left", validate="many_to_one")
    if not output["anchor_count"].eq(output["eligible_count20"]).all():
        raise EconomicResponseDataError("anchor population differs from predictor population")
    output["response_complete"] = output["response_count"].notna()
    output["response_retention"] = output["response_count"] / output["anchor_count"]
    for horizon in (1, 3, 5):
        date_col = f"response_date_h{horizon}"
        output[f"response_available_at_h{horizon}"] = np.where(
            output["response_complete"],
            pd.to_datetime(output[date_col]).dt.strftime("%Y-%m-%dT15:00:00+08:00"),
            None,
        )
        output[date_col] = pd.to_datetime(output[date_col]).dt.strftime("%Y-%m-%d")
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output["response_count"] = output["response_count"].astype("Int64")
    first = keys + [
        "decision_at",
        "available_at",
        "snapshot_id",
        "anchor_count",
        "response_count",
        "response_retention",
        "response_complete",
    ]
    timing: list[str] = []
    for horizon in (1, 3, 5):
        timing.extend([f"response_date_h{horizon}", f"response_available_at_h{horizon}"])
    metric_columns = [
        column
        for column in output.columns
        if column not in set(first + timing + ["eligible_count20"])
    ]
    return output[first + timing + metric_columns].sort_values(keys).reset_index(drop=True)


def _validate_panel(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    complete = panel[panel["response_complete"]].copy()
    incomplete = panel[~panel["response_complete"]].copy()
    minimum_retention = float(complete["response_retention"].min())
    floors = spec["population"]["minimum_anchor_counts"]
    floor_pass = bool(
        complete["response_count"].ge(complete["market_view"].map(floors)).all()
    )
    incomplete_dates = sorted(incomplete["trade_date"].unique().tolist())
    expected_incomplete = int(spec["population"]["expected_ineligible_terminal_dates"])
    year_counts = (
        complete.assign(event_year=complete["trade_date"].str[:4].astype(int))
        .groupby(["market_view", "denominator", "event_year"], sort=True)
        .size()
    )
    metrics = [column for column in panel if "_h" in column and panel[column].dtype.kind == "f"]
    finite = bool(np.isfinite(complete[metrics].to_numpy(float)).all())
    quantile_order = True
    for horizon in (1, 3, 5):
        quantile_order &= bool(
            (
                complete[f"terminal_p10_log_return_h{horizon}"]
                <= complete[f"terminal_median_log_return_h{horizon}"]
            ).all()
            and (
                complete[f"terminal_median_log_return_h{horizon}"]
                <= complete[f"terminal_p90_log_return_h{horizon}"]
            ).all()
            and (
                complete[f"adverse_p10_log_excursion_h{horizon}"]
                <= complete[f"adverse_median_log_excursion_h{horizon}"]
            ).all()
            and complete[f"adverse_mean_log_excursion_h{horizon}"].le(
                complete[f"terminal_mean_log_return_h{horizon}"]
            ).all()
        )
    max_consumed = complete["response_date_h5"].max()
    gates = {
        "minimum_response_retention": minimum_retention
        >= spec["population"]["minimum_complete_response_retention"],
        "minimum_view_population": floor_pass,
        "minimum_dates_each_view_denominator_year": int(year_counts.min())
        >= spec["population"]["minimum_response_dates_per_view_denominator_year"],
        "exact_five_ineligible_terminal_dates": len(incomplete_dates) == expected_incomplete,
        "only_terminal_dates_incomplete": len(incomplete) == expected_incomplete * 8,
        "finite_response_metrics": finite,
        "ordered_quantiles_and_downside": quantile_order,
        "no_post_2023_consumption": max_consumed == spec["coordinate"]["last_consumed_date"],
    }
    return {
        "gates": gates,
        "all_pass": all(gates.values()),
        "minimum_retention": minimum_retention,
        "minimum_response_dates_per_cell_year": int(year_counts.min()),
        "ineligible_terminal_dates": incomplete_dates,
        "max_consumed_date": max_consumed,
    }


def _count_audit(panel: pd.DataFrame) -> pd.DataFrame:
    complete = panel[panel["response_complete"]].copy()
    complete["event_year"] = complete["trade_date"].str[:4].astype(int)
    annual = (
        complete.groupby(["market_view", "denominator", "event_year"], sort=True)
        .agg(
            response_dates=("trade_date", "size"),
            anchor_security_rows=("anchor_count", "sum"),
            response_security_rows=("response_count", "sum"),
            minimum_response_retention=("response_retention", "min"),
            minimum_response_count=("response_count", "min"),
        )
        .reset_index()
    )
    return annual


def _render_report(result: dict[str, Any]) -> str:
    validation = result["response_domain"]
    gates = validation["gates"]
    return "\n".join(
        [
            "# MKT-BREAKOUT-ECON-DATA-001 response-domain audit",
            "",
            f"Status: **{result['status']}**.",
            "",
            "The frozen CY-006 supported-action coordinate produced a complete fixed-cohort "
            "1/3/5-session terminal-return and adverse-excursion domain without estimating "
            "any state/outcome relationship.",
            "",
            f"- Response panel rows: {result['population']['panel_rows']:,}.",
            f"- Complete response cells: {result['population']['complete_response_cells']:,}.",
            f"- Minimum complete-cohort retention: {validation['minimum_retention']:.6f}.",
            f"- Minimum dates per view/denominator/year: "
            f"{validation['minimum_response_dates_per_cell_year']}.",
            f"- Ineligible terminal event dates: "
            f"{', '.join(validation['ineligible_terminal_dates'])}.",
            f"- Maximum consumed response date: {validation['max_consumed_date']}.",
            f"- Scalar action-coordinate response cases exact: "
            f"{result['scalar_reconstruction']['all_exact']}.",
            f"- All frozen domain gates pass: {all(gates.values())}.",
            "",
            "No state/outcome correlation, high/low contrast, crossing episode, favorable "
            "direction, control, placebo, economic classification, strategy field, post-2023 "
            "row, or CY-011 field was read or estimated.",
            "",
            "Passing establishes response-domain feasibility only, not economic meaning, "
            "prediction, habitat, execution, or strategy usefulness.",
            "",
        ]
    )


def _write_outputs(
    panel: pd.DataFrame,
    count_audit: pd.DataFrame,
    scalar_audit: pd.DataFrame,
    result_without_hashes: dict[str, Any],
) -> None:
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    count_audit.to_csv(
        COUNT_AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    scalar_audit.to_csv(SCALAR_AUDIT_PATH, index=False, lineterminator="\n")
    result = dict(result_without_hashes)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "runner_sha256": sha256_file(Path(__file__)),
        "panel_sha256": sha256_file(PANEL_PATH),
        "count_audit_sha256": sha256_file(COUNT_AUDIT_PATH),
        "scalar_audit_sha256": sha256_file(SCALAR_AUDIT_PATH),
        "source_partitions": result_without_hashes["source_partitions"],
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable = sum(
        path.stat().st_size
        for path in (PANEL_PATH, COUNT_AUDIT_PATH, SCALAR_AUDIT_PATH, RESULT_PATH, REPORT_PATH)
    )
    spec = json.loads(SPEC_PATH.read_text())
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise EconomicResponseDataError("durable output ceiling breached")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    coordinate_module = _load_coordinate_module(spec)
    paths, observed_partitions = _verify_partitions(spec, coordinate_module)
    _preflight_resource_guard(spec, paths)
    predictor, predictor_audit = _audit_predictor(spec)

    with tempfile.TemporaryDirectory(prefix="mkt-breakout-econ-data-") as temp_raw:
        temp_dir = Path(temp_raw)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped_temp = str(temp_dir).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped_temp}'")
        try:
            try:
                source_audit = coordinate_module._create_source_and_audit(
                    connection, paths, spec
                )
                coordinate_module._create_event_security(
                    _PreserveCoordinateWindow(connection)
                )
            except Exception as exc:
                raise EconomicResponseDataError(str(exc)) from exc
            _phase_resource_guard(spec, temp_dir, started)
            _create_future_coordinate(connection)
            response_dates = _calendar_response_dates(connection)
            grouped_parts: list[pd.DataFrame] = []
            scalar_parts: list[pd.DataFrame] = []
            for event_year in spec["population"]["event_years"]:
                _create_response_security(connection, int(event_year))
                grouped_parts.append(_group_frames(connection, int(event_year)))
                scalar_parts.append(_scalar_audit(connection, spec))
                connection.execute("DROP TABLE response_security")
                _phase_resource_guard(spec, temp_dir, started)
            grouped = pd.concat(grouped_parts, ignore_index=True)
            scalar_candidates = pd.concat(scalar_parts, ignore_index=True)
            selected_hashes = sorted(scalar_candidates["selection_hash"].unique())[:5]
            scalar_audit = scalar_candidates[
                scalar_candidates["selection_hash"].isin(selected_hashes)
            ].copy()
            if (
                scalar_audit["selection_hash"].nunique() != 5
                or len(scalar_audit)
                != 5 * len(spec["scalar_reconstruction"]["exact_fields"])
            ):
                raise EconomicResponseDataError("global scalar response selection failed")
        finally:
            connection.close()
        _phase_resource_guard(spec, temp_dir, started)

    panel = _assemble_panel(predictor, grouped, response_dates)
    validation = _validate_panel(panel, spec)
    count_audit = _count_audit(panel)
    status = (
        "COMPLETE_RESPONSE_DOMAIN_ADEQUACY"
        if validation["all_pass"]
        else "COMPLETE_RESPONSE_DOMAIN_INADEQUATE_FAIL_CLOSED"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": "RESPONSE_DOMAIN_ONLY",
        "source_audit": source_audit,
        "predictor_audit": predictor_audit,
        "response_domain": validation,
        "population": {
            "panel_rows": int(len(panel)),
            "complete_response_cells": int(panel["response_complete"].sum()),
            "response_security_rows_all_a_all_status": int(
                count_audit.loc[
                    count_audit["market_view"].eq("ALL_A")
                    & count_audit["denominator"].eq("ALL_STATUS"),
                    "response_security_rows",
                ].sum()
            ),
        },
        "scalar_reconstruction": {
            "cases": int(scalar_audit["selection_hash"].nunique()),
            "fields": int(scalar_audit["field"].nunique()),
            "all_exact": bool(scalar_audit["exact_match"].all()),
        },
        "source_partitions": observed_partitions,
        "state_outcome_estimates_computed": False,
        "crossing_or_episode_estimates_computed": False,
        "strategy_fields_read": [],
        "post_2023_read": False,
        "cy011_read": False,
        "resource_contract": {
            "status": "PASS",
            "memory_limit_gib": spec["resource_budget"]["daily_memory_limit_gib"],
            "peak_rss_ceiling_gib": spec["resource_budget"]["peak_rss_ceiling_gib"],
            "temporary_spill_ceiling_gib": spec["resource_budget"][
                "temporary_spill_ceiling_gib"
            ],
            "wall_clock_ceiling_minutes": spec["resource_budget"][
                "wall_clock_ceiling_minutes"
            ],
            "dynamic_measurements_serialized": False,
        },
    }
    _write_outputs(panel, count_audit, scalar_audit, result)
    if not validation["all_pass"]:
        raise EconomicResponseDataError(f"response-domain gate failed: {validation['gates']}")


if __name__ == "__main__":
    main()
