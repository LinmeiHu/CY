#!/usr/bin/env python3
"""Build the frozen own-overshoot/shared-date stratum response domain."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import platform
import resource
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWN-DATA-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-001_panel.csv"
COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-001_count_audit.csv"
SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-001_scalar_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-001_result.json"
TELEMETRY_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWN-DATA-001_resource_telemetry.csv"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWN-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "ec153f32588ad6a1be034da074575981e30614aca05c0c16a3cf2293ab841854"


class OwnSharedDataError(RuntimeError):
    """Fail-closed own/shared stratum data error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _import(path: Path, name: str) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise OwnSharedDataError(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise OwnSharedDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_OWN_SHARED_STRATUM_RESPONSE_CONSTRUCTION"
        or spec["outcome_access"]
        != "FUTURE_PRE2024_CROSSER_STRATUM_RESPONSE_CONSTRUCTION_ONLY"
    ):
        raise OwnSharedDataError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OwnSharedDataError(f"input identity mismatch: {name}")
    path_result = json.loads(
        _resolve(spec["inputs"]["path_result"]["path"]).read_text(encoding="utf-8")
    )
    attr_result = json.loads(
        _resolve(spec["inputs"]["attribution_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    immed_result = json.loads(
        _resolve(spec["inputs"]["immediacy_result"]["path"]).read_text(
            encoding="utf-8"
        )
    )
    activation = spec["activation"]
    if path_result["status"] != activation["required_path_data_status"]:
        raise OwnSharedDataError("path response domain is not activated")
    if attr_result["classification"] != activation["required_attribution_classification"]:
        raise OwnSharedDataError("formation-depth attribution is not activated")
    if immed_result["classification"] != activation["required_immediacy_classification"]:
        raise OwnSharedDataError("trough-immediacy synthesis boundary changed")
    forbidden = "|".join(spec["prohibited_computations"])
    for token in ("CY-011", "post-2023", "raw QD-004/CY-008", "own/shared association"):
        if token not in forbidden:
            raise OwnSharedDataError(f"prohibited boundary missing: {token}")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _telemetry(progress: str) -> dict[str, Any]:
    memory = psutil.virtual_memory()
    swap = psutil.swap_memory()
    disk = psutil.disk_usage(str(ROOT))
    return {
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "worker_id": "DIRECTOR-LANE-A",
        "pid": os.getpid(),
        "progress": progress,
        "process_peak_rss_bytes": _peak_rss_bytes(),
        "system_available_bytes": int(memory.available),
        "system_percent_used": float(memory.percent),
        "swap_used_bytes": int(swap.used),
        "swap_free_bytes": int(swap.free),
        "disk_free_bytes": int(disk.free),
    }


def _guard(spec: dict[str, Any], started: float, temp_dir: Path) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise OwnSharedDataError("system memory headroom below frozen floor")
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise OwnSharedDataError("process peak RSS ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60:
        raise OwnSharedDataError("wall-clock ceiling breached")
    spill = sum(path.stat().st_size for path in temp_dir.rglob("*") if path.is_file())
    if spill > int(budget["temporary_spill_ceiling_gib"] * 2**30):
        raise OwnSharedDataError("temporary spill ceiling breached")
    disk = psutil.disk_usage(str(ROOT))
    if disk.free / disk.total < float(budget["filesystem_headroom_fraction"]):
        raise OwnSharedDataError("filesystem headroom below frozen fraction")


def _create_anchor_strata(
    connection: duckdb.DuckDBPyConnection, event_year: int, minimum: int
) -> None:
    for table in ("anchor_expanded", "anchor_strata"):
        connection.execute(f"DROP TABLE IF EXISTS {table}")
    connection.execute(
        """
        CREATE TEMP TABLE anchor_expanded AS
        WITH base AS (
          SELECT trade_date,symbol,is_st,coordinate_high,resistance_high20,
                 coordinate_close AS coordinate_close_t,
                 coordinate_high/resistance_high20-1.0 AS own_depth
          FROM event_security
          WHERE year(trade_date)=? AND cross20
        ), governed AS (
          SELECT 'ALL_A' AS market_view,* FROM base
            WHERE symbol LIKE '%.SH' OR symbol LIKE '%.SZ'
          UNION ALL SELECT 'SH_A',* FROM base WHERE symbol LIKE '%.SH'
          UNION ALL SELECT 'SZ_A',* FROM base WHERE symbol LIKE '%.SZ'
          UNION ALL SELECT 'CHINEXT_BOARD',* FROM base
            WHERE symbol LIKE '%.SZ' AND (left(symbol,3)='300' OR left(symbol,3)='301')
        )
        SELECT g.*,'ALL_STATUS' AS denominator FROM governed g
        UNION ALL SELECT g.*,'NON_ST' FROM governed g WHERE is_st IS FALSE
        """,
        [event_year],
    )
    connection.execute(
        f"""
        CREATE TEMP TABLE anchor_strata AS
        WITH ranked AS (
          SELECT *,count(*) OVER w AS anchor_crossing_count,
                 row_number() OVER w_order AS depth_row_number,
                 ntile(5) OVER w_order AS stratum
          FROM anchor_expanded
          WINDOW
            w AS (PARTITION BY trade_date,market_view,denominator),
            w_order AS (PARTITION BY trade_date,market_view,denominator
                        ORDER BY own_depth,symbol)
        )
        SELECT * FROM ranked WHERE anchor_crossing_count>={minimum}
        """
    )
    invalid = connection.execute(
        """
        SELECT count(*) FROM anchor_strata
        WHERE NOT (own_depth>0 AND isfinite(own_depth)
                   AND stratum BETWEEN 1 AND 5
                   AND depth_row_number BETWEEN 1 AND anchor_crossing_count)
        """
    ).fetchone()[0]
    if int(invalid) != 0:
        raise OwnSharedDataError("anchor stratum semantic failure")


def _stratum_frame(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    response_fields = [
        f"{kind}_h{horizon}"
        for kind in ("adverse_log_excursion", "terminal_log_return")
        for horizon in (1, 3, 5)
    ]
    response_sql: list[str] = []
    for field in response_fields:
        response_sql.extend(
            [
                f"sum(r.{field}) AS stratum_{field}_sum",
                f"avg(r.{field}) AS stratum_{field}_mean",
            ]
        )
    aggregates = ",\n".join(response_sql)
    return connection.execute(
        f"""
        WITH anchor_groups AS (
          SELECT trade_date,market_view,denominator,stratum,
                 max(anchor_crossing_count) AS anchor_crossing_count,
                 count(*) AS stratum_anchor_count,
                 sum(own_depth) AS stratum_own_depth_sum,
                 avg(own_depth) AS stratum_own_depth_mean,
                 sha256(string_agg(symbol || ':' || printf('%.17g',own_depth),
                                   '|' ORDER BY own_depth,symbol)) AS stratum_ledger_sha256
          FROM anchor_strata GROUP BY 1,2,3,4
        ), group_ledgers AS (
          SELECT trade_date,market_view,denominator,
                 sha256(string_agg(symbol || ':' || printf('%.17g',own_depth),
                                   '|' ORDER BY own_depth,symbol)) AS anchor_ledger_sha256
          FROM anchor_strata GROUP BY 1,2,3
        ), response_groups AS (
          SELECT a.trade_date,a.market_view,a.denominator,a.stratum,
                 count(*) AS stratum_response_count,{aggregates}
          FROM anchor_strata a JOIN response_security r
            ON a.symbol=r.symbol AND a.trade_date=r.trade_date
          GROUP BY 1,2,3,4
        )
        SELECT a.*,g.anchor_ledger_sha256,
               coalesce(r.stratum_response_count,0) AS stratum_response_count,
               r.* EXCLUDE(trade_date,market_view,denominator,stratum,stratum_response_count)
        FROM anchor_groups a
        JOIN group_ledgers g USING(trade_date,market_view,denominator)
        LEFT JOIN response_groups r USING(trade_date,market_view,denominator,stratum)
        ORDER BY trade_date,denominator,market_view,stratum
        """
    ).fetchdf()


def _scalar_candidates(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return connection.execute(
        """
        WITH candidates AS (
          SELECT a.trade_date,a.market_view,a.denominator,a.symbol,a.stratum,
                 a.depth_row_number,a.anchor_crossing_count,a.own_depth,
                 a.coordinate_high,a.resistance_high20,a.coordinate_close_t,
                 r.mapped_low_t1,r.mapped_low_t2,r.mapped_low_t3,
                 r.mapped_low_t4,r.mapped_low_t5,
                 r.coordinate_close_t1,r.coordinate_close_t3,r.coordinate_close_t5,
                 r.adverse_log_excursion_h1,r.adverse_log_excursion_h3,
                 r.adverse_log_excursion_h5,r.terminal_log_return_h1,
                 r.terminal_log_return_h3,r.terminal_log_return_h5,
                 sha256('MKT-FORMDEPTH-OWN-DATA-001|' || a.stratum || '|' ||
                        a.symbol || '|' || strftime(a.trade_date,'%Y-%m-%d') || '|' ||
                        a.market_view || '|' || a.denominator) AS selection_hash
          FROM anchor_strata a JOIN response_security r
            ON a.symbol=r.symbol AND a.trade_date=r.trade_date
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY stratum ORDER BY selection_hash,symbol,trade_date,
            market_view,denominator) AS selection_rank
          FROM candidates
        )
        SELECT * FROM ranked WHERE selection_rank<=5
        ORDER BY stratum,selection_hash,symbol,trade_date,market_view,denominator
        """
    ).fetchdf()


def _expected_ntile(row_number: int, count: int, buckets: int = 5) -> int:
    small = count // buckets
    large = small + 1
    large_buckets = count % buckets
    cutoff = large * large_buckets
    if row_number <= cutoff:
        return (row_number - 1) // large + 1
    return large_buckets + (row_number - cutoff - 1) // small + 1


def _scalar_audit(candidates: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    candidates = (
        candidates.sort_values(
            ["stratum", "selection_hash", "symbol", "trade_date", "market_view", "denominator"]
        )
        .groupby("stratum", sort=True)
        .head(spec["scalar_reconstruction"]["cases_per_stratum"])
    )
    expected_cases = spec["scalar_reconstruction"]["cases_per_stratum"]
    if candidates.groupby("stratum").size().to_dict() != {
        index: expected_cases for index in range(1, 6)
    }:
        raise OwnSharedDataError("balanced scalar cases unavailable")
    rows: list[dict[str, Any]] = []
    for case in candidates.itertuples(index=False):
        observed = {
            "stratum": _expected_ntile(
                int(case.depth_row_number), int(case.anchor_crossing_count)
            ),
            "own_depth": case.coordinate_high / case.resistance_high20 - 1.0,
            "coordinate_high": case.coordinate_high,
            "resistance_high20": case.resistance_high20,
        }
        lows = [getattr(case, f"mapped_low_t{offset}") for offset in range(1, 6)]
        for horizon in (1, 3, 5):
            observed[f"adverse_log_excursion_h{horizon}"] = min(
                np.log(value / case.coordinate_close_t) for value in lows[:horizon]
            )
            observed[f"terminal_log_return_h{horizon}"] = np.log(
                getattr(case, f"coordinate_close_t{horizon}") / case.coordinate_close_t
            )
        for field in spec["scalar_reconstruction"]["exact_fields"]:
            expected = getattr(case, field)
            actual = observed[field]
            exact = (
                int(expected) == int(actual)
                if field == "stratum"
                else float(expected) == float(actual)
            )
            rows.append(
                {
                    "selection_hash": case.selection_hash,
                    "stratum": int(case.stratum),
                    "symbol": case.symbol,
                    "trade_date": pd.Timestamp(case.trade_date).strftime("%Y-%m-%d"),
                    "market_view": case.market_view,
                    "denominator": case.denominator,
                    "field": field,
                    "expected_value": (
                        str(expected)
                        if field == "stratum"
                        else format(float(expected), ".17g")
                    ),
                    "observed_value": (
                        str(actual)
                        if field == "stratum"
                        else format(float(actual), ".17g")
                    ),
                    "exact_match": exact,
                }
            )
    audit = pd.DataFrame(rows).sort_values(
        [
            "stratum",
            "selection_hash",
            "symbol",
            "trade_date",
            "market_view",
            "denominator",
            "field",
        ]
    )
    if not audit["exact_match"].all():
        failed = audit.loc[~audit["exact_match"]].iloc[0]
        raise OwnSharedDataError(f"scalar reconstruction failed: {failed.to_dict()}")
    return audit.reset_index(drop=True)


def _attach_pit(panel: pd.DataFrame, causal: Any) -> pd.DataFrame:
    pieces: list[pd.DataFrame] = []
    keys = ["market_view", "denominator", "stratum"]
    for _, group in panel.groupby(keys, sort=True):
        item = group.sort_values("trade_date").copy()
        item["stratum_own_depth_pit_3y_pct"] = causal.causal_rolling_percentile(
            item["stratum_own_depth_mean"], window=756, min_history=504
        )
        item["other_strata_depth_pit_3y_pct"] = causal.causal_rolling_percentile(
            item["other_strata_depth_mean"], window=756, min_history=504
        )
        pieces.append(item)
    return pd.concat(pieces, ignore_index=True).sort_values(
        ["trade_date", "denominator", "market_view", "stratum"]
    ).reset_index(drop=True)


def _bind_path_domain(
    panel: pd.DataFrame,
    path: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["trade_date", "market_view", "denominator"]
    if path[keys].duplicated().any():
        raise OwnSharedDataError("bound path panel key is not unique")
    membership = panel.merge(
        path[keys], on=keys, how="left", validate="many_to_one", indicator=True
    )
    unbound = membership.loc[membership["_merge"].eq("left_only")].copy()
    if not unbound.empty:
        raise OwnSharedDataError("anchor stratum key is absent from bound path domain")
    return panel.merge(path, on=keys, how="left", validate="many_to_one")


def _assemble(
    frames: pd.DataFrame, spec: dict[str, Any], causal: Any
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    panel = frames.copy()
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    path = pd.read_csv(
        _resolve(spec["inputs"]["path_panel"]["path"]),
        usecols=[
            *keys,
            "crossing_response_count",
            "breakout_formation_depth20",
            "path_topology_complete",
            "response_date_h1",
            "response_date_h3",
            "response_date_h5",
            "response_available_at_h1",
            "response_available_at_h3",
            "response_available_at_h5",
        ],
        parse_dates=[
            "trade_date",
            "response_date_h1",
            "response_date_h3",
            "response_date_h5",
        ],
    )
    if len(path) != spec["activation"]["expected_bound_panel_rows"]:
        raise OwnSharedDataError("bound path panel row count changed")
    panel = _bind_path_domain(panel, path)
    if panel[[*keys, "stratum"]].duplicated().any():
        raise OwnSharedDataError("stratum output key is not unique")
    if not panel["stratum"].between(1, 5).all():
        raise OwnSharedDataError("stratum domain changed")
    group = panel.groupby(keys, sort=False)
    panel["deterministic_total_depth_sum"] = group["stratum_own_depth_sum"].transform("sum")
    panel["deterministic_total_anchor_count"] = group["stratum_anchor_count"].transform("sum")
    panel["deterministic_total_depth_mean"] = (
        panel["deterministic_total_depth_sum"] / panel["deterministic_total_anchor_count"]
    )
    panel["other_strata_anchor_count"] = (
        panel["deterministic_total_anchor_count"] - panel["stratum_anchor_count"]
    )
    panel["other_strata_depth_sum"] = (
        panel["deterministic_total_depth_sum"] - panel["stratum_own_depth_sum"]
    )
    panel["other_strata_depth_mean"] = (
        panel["other_strata_depth_sum"] / panel["other_strata_anchor_count"]
    )
    panel["relative_depth_mean"] = (
        panel["stratum_own_depth_mean"] - panel["other_strata_depth_mean"]
    )
    panel["bound_depth_binary_equal"] = panel["deterministic_total_depth_mean"].eq(
        panel["breakout_formation_depth20"]
    )
    panel["bound_depth_binary_difference"] = (
        panel["deterministic_total_depth_mean"] - panel["breakout_formation_depth20"]
    )
    panel["stratum_response_retention"] = (
        panel["stratum_response_count"] / panel["stratum_anchor_count"]
    )
    panel["stratum_complete"] = (
        panel["path_topology_complete"].eq(True)
        & panel["stratum_response_retention"].ge(
            spec["support"]["minimum_response_retention_each_stratum_cell"]
        )
    )
    count_exhaustion = group["stratum_anchor_count"].sum().eq(
        group["anchor_crossing_count"].first()
    )
    response_sum = group["stratum_response_count"].sum()
    bound_response = group["crossing_response_count"].first()
    structurally_right_censored = bound_response.isna() & response_sum.eq(0)
    response_exhaustion = response_sum.eq(bound_response) | structurally_right_censored
    expected_right_censored = spec.get("_right_censor_retry_control", {}).get(
        "diagnosed_domain", {}
    ).get("structurally_right_censored_date_cells")
    if (
        expected_right_censored is not None
        and int(structurally_right_censored.sum()) != expected_right_censored
    ):
        raise OwnSharedDataError("structurally right-censored cell count changed")
    five_strata = group["stratum"].nunique().eq(5)
    if not count_exhaustion.all() or not response_exhaustion.all() or not five_strata.all():
        raise OwnSharedDataError("stratum count/response exhaustion failed")
    if (
        panel["stratum_anchor_count"]
        < spec["membership"]["minimum_anchor_per_stratum"]
    ).any():
        raise OwnSharedDataError("stratum anchor floor failed")
    if not (
        panel["other_strata_anchor_count"]
        == panel["deterministic_total_anchor_count"] - panel["stratum_anchor_count"]
    ).all():
        raise OwnSharedDataError("other-strata count identity failed")
    response_mean_columns = [
        f"stratum_{kind}_h{horizon}_mean"
        for kind in ("adverse_log_excursion", "terminal_log_return")
        for horizon in (1, 3, 5)
    ]
    if not np.isfinite(
        panel.loc[panel["stratum_complete"], response_mean_columns].to_numpy(float)
    ).all():
        raise OwnSharedDataError("complete stratum response is nonfinite")
    panel = _attach_pit(panel, causal)
    controls = [
        "breadth_net_new_high_low60_pit_3y_pct",
        "realized_volatility_median20_pit_3y_pct",
        "median_signed_limit_utilization",
        "open_close_log_return__median",
        "intraday_log_range__median",
    ]
    attr = pd.read_csv(
        _resolve(spec["inputs"]["attribution_panel"]["path"]),
        usecols=[*keys, "available_at", *controls],
        parse_dates=["trade_date"],
    ).rename(columns={"available_at": "control_available_at"})
    if attr[keys].duplicated().any():
        raise OwnSharedDataError("attribution controls are not uniquely keyed")
    panel = panel.merge(attr, on=keys, how="left", validate="many_to_one")
    clock = pd.to_datetime(panel["control_available_at"], errors="coerce")
    complete_clock = clock.loc[panel["stratum_complete"]]
    if complete_clock.isna().any() or not (
        (complete_clock.dt.hour == 15) & (complete_clock.dt.minute == 30)
    ).all():
        raise OwnSharedDataError("joint control clock is not exactly 15:30")
    missing_clock = clock.isna()
    if (missing_clock & panel["stratum_complete"]).any():
        raise OwnSharedDataError("complete stratum is missing joint control clock")
    expected_missing_cells = spec.get("_control_clock_retry_control", {}).get(
        "diagnosed_domain", {}
    ).get("right_censored_cells_without_control_clock")
    if expected_missing_cells is not None and int(missing_clock.sum()) != (
        expected_missing_cells * spec["membership"]["strata"]
    ):
        raise OwnSharedDataError("right-censored missing-control count changed")
    own_clock = panel["trade_date"].dt.strftime("%Y-%m-%dT15:30:00")
    panel["available_at"] = clock.dt.strftime("%Y-%m-%dT%H:%M:%S").fillna(
        own_clock
    )
    panel["event_year"] = panel["trade_date"].dt.year.astype(int)
    later_columns = [
        "stratum_own_depth_pit_3y_pct",
        "other_strata_depth_pit_3y_pct",
        "stratum_adverse_log_excursion_h3_mean",
        *controls,
    ]
    later = panel[panel["stratum_complete"]].dropna(subset=later_columns)
    per_stratum_later = later.groupby("stratum", sort=True).size()
    support = spec["support"]
    if len(later) < support["expected_later_complete_rows_all_strata"]:
        raise OwnSharedDataError("later six-control support below total floor")
    if (
        per_stratum_later.reindex(range(1, 6), fill_value=0)
        < support["minimum_later_complete_rows_each_stratum"]
    ).any():
        raise OwnSharedDataError("later six-control support below stratum floor")
    count = (
        panel.groupby(["market_view", "denominator", "event_year", "stratum"], sort=True)
        .agg(
            eligible_dates=("trade_date", "size"),
            complete_dates=("stratum_complete", "sum"),
            minimum_anchor_count=("stratum_anchor_count", "min"),
            minimum_response_count=("stratum_response_count", "min"),
            minimum_response_retention=("stratum_response_retention", "min"),
            pit_complete_rows=("other_strata_depth_pit_3y_pct", "count"),
        )
        .reset_index()
    )
    minimum_complete = int(count["complete_dates"].min())
    if minimum_complete < support["minimum_complete_dates_each_view_denominator_year"]:
        raise OwnSharedDataError("complete date/cell/year support below frozen floor")
    if int(panel["stratum_complete"].sum()) < support["minimum_complete_stratum_rows"]:
        raise OwnSharedDataError("complete stratum rows below frozen floor")
    validation = {
        "stratum_count_exhaustion": True,
        "stratum_response_exhaustion": True,
        "structurally_right_censored_date_cells": int(
            structurally_right_censored.sum()
        ),
        "five_strata_each_eligible_cell": True,
        "minimum_complete_dates_per_cell_year_stratum": minimum_complete,
        "complete_stratum_rows": int(panel["stratum_complete"].sum()),
        "later_six_control_rows": len(later),
        "later_rows_per_stratum": {
            str(int(key)): int(value) for key, value in per_stratum_later.items()
        },
        "bound_depth_binary_equal_rows": int(panel["bound_depth_binary_equal"].sum()),
        "bound_depth_binary_unequal_rows": int((~panel["bound_depth_binary_equal"]).sum()),
        "maximum_absolute_bound_depth_binary_difference": float(
            panel["bound_depth_binary_difference"].abs().max()
        ),
        "binary_difference_used_as_pass_tolerance": False,
        "right_censored_rows_without_control_clock": int(missing_clock.sum()),
    }
    return (
        panel.sort_values([*keys, "stratum"]).reset_index(drop=True),
        count,
        validation,
    )


def _report(result: dict[str, Any]) -> str:
    domain = result["response_domain"]
    count_ok = domain["stratum_count_exhaustion"]
    response_ok = domain["stratum_response_exhaustion"]
    binary_difference = domain["maximum_absolute_bound_depth_binary_difference"]
    scalar_cases = result["scalar_reconstruction"]["cases"]
    scalar_fields = result["scalar_reconstruction"]["fields"]
    return f"""# MKT-FORMDEPTH-OWN-DATA-001 own/shared response-domain audit

- Status: `{result['status']}`
- Complete stratum rows: {domain['complete_stratum_rows']:,}
- Minimum complete dates/cell/year/stratum: {domain['minimum_complete_dates_per_cell_year_stratum']}
- Later PIT + six-control rows: {domain['later_six_control_rows']:,}
- Exact anchor/response stratum exhaustion: {count_ok}/{response_ok}
- Bound unordered-mean unequal rows: {domain['bound_depth_binary_unequal_rows']:,}
- Maximum absolute unordered-mean binary difference: {binary_difference:.17g}
- Scalar cases/fields exact: {scalar_cases}/{scalar_fields}

The floating aggregation diagnostic is not a tolerance gate. Exact membership,
counts, deterministic ledgers, response conservation, and scalar formulas pass.
This experiment computes no own/shared association, gradient, channel direction,
classification, subgroup result, strategy field, post-2023 row, or CY-011 access.
Future responses remain attribution only.
"""


def main() -> None:
    started = time.monotonic()
    telemetry = [_telemetry("start")]
    spec = _load_spec()
    path_runner = _import(
        _resolve(spec["inputs"]["inherited_path_data_runner"]["path"]),
        "own_shared_path_data",
    )
    path_spec = path_runner._load_spec()
    base = path_runner._import(
        _resolve(path_spec["inputs"]["inherited_data_runner"]["path"]),
        "own_shared_inherited_data",
    )
    inherited = base._load_spec()
    economic_data = base._import(base.ECON_DATA_RUNNER, "own_shared_economic_data")
    coordinate = economic_data._load_coordinate_module(inherited)
    source_paths, source_hashes = economic_data._verify_partitions(inherited, coordinate)
    base._preflight(inherited, source_paths)
    causal = _import(
        _resolve(spec["inputs"]["causal_pit_runner"]["path"]),
        "own_shared_causal_pit",
    )
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-own-data-") as temp_raw:
        temp_dir = Path(temp_raw)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped_temp = str(temp_dir).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped_temp}'")
        frames: list[pd.DataFrame] = []
        candidates: list[pd.DataFrame] = []
        try:
            source_audit = coordinate._create_source_and_audit(
                connection, source_paths, inherited
            )
            coordinate._create_event_security(
                economic_data._PreserveCoordinateWindow(connection)
            )
            path_runner._create_future_coordinate(connection)
            for event_year in (2018, 2019, 2020, 2021, 2022, 2023):
                _create_anchor_strata(
                    connection,
                    event_year,
                    int(spec["membership"]["minimum_anchor_crossers"]),
                )
                path_runner._create_response_security(connection, event_year)
                frames.append(_stratum_frame(connection))
                candidates.append(_scalar_candidates(connection))
                connection.execute("DROP TABLE response_security")
                telemetry.append(_telemetry(f"year_{event_year}_complete"))
                _guard(spec, started, temp_dir)
        finally:
            connection.close()
        _guard(spec, started, temp_dir)
    panel, count, validation = _assemble(pd.concat(frames, ignore_index=True), spec, causal)
    scalar = _scalar_audit(pd.concat(candidates, ignore_index=True), spec)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    count.to_csv(COUNT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    scalar.to_csv(SCALAR_PATH, index=False, lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_OWN_SHARED_STRATUM_RESPONSE_DOMAIN_ADEQUACY",
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "source_audit": source_audit,
        "source_partitions": source_hashes,
        "response_domain": validation,
        "population": {"panel_rows": len(panel), "count_audit_rows": len(count)},
        "scalar_reconstruction": {
            "cases": scalar["selection_hash"].nunique(),
            "cases_per_stratum": {
                str(int(key)): int(value)
                for key, value in scalar.groupby("stratum")["selection_hash"].nunique().items()
            },
            "fields": scalar["field"].nunique(),
            "all_exact": bool(scalar["exact_match"].all()),
        },
        "own_shared_association_computed": False,
        "channel_classification_computed": False,
        "future_response_used_as_predictor": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "resource_contract": spec["resource_budget"],
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "panel_sha256": sha256_file(PANEL_PATH),
            "count_audit_sha256": sha256_file(COUNT_PATH),
            "scalar_audit_sha256": sha256_file(SCALAR_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    telemetry.append(_telemetry("complete"))
    pd.DataFrame(telemetry).to_csv(TELEMETRY_PATH, index=False, lineterminator="\n")
    durable = sum(
        path.stat().st_size
        for path in (PANEL_PATH, COUNT_PATH, SCALAR_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise OwnSharedDataError("durable output ceiling breached")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
