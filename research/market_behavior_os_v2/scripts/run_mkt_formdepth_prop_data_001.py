#!/usr/bin/env python3
"""Build the frozen crossing/noncrossing formation-depth response domain."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-PROP-DATA-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-001_panel.csv"
COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-001_count_audit.csv"
SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-001_scalar_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PROP-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-PROP-DATA-001_audit.md"
ECON_DATA_RUNNER = PROGRAM / "scripts/run_mkt_breakout_econ_data_001.py"
EXPECTED_SPEC_SHA256 = "3017753a1a25d37946bfb383dc6a8b3f8c0a4219e5b943d6067d4278db326b58"


class PropagationDataError(RuntimeError):
    """Fail-closed membership-resolved response-domain error."""


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
        raise PropagationDataError(f"cannot load bound module: {path}")
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
        raise PropagationDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_MEMBERSHIP_RESOLVED_RESPONSE_CONSTRUCTION"
        or spec["outcome_access"]
        != "FUTURE_PRE2024_MEMBERSHIP_RESOLVED_MARKET_RESPONSE_CONSTRUCTION_ONLY"
    ):
        raise PropagationDataError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise PropagationDataError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise PropagationDataError("prohibited boundary changed")
    broad = json.loads(
        _resolve(spec["inputs"]["broad_response_result"]["path"]).read_text()
    )
    if broad["status"] != spec["broad_domain_audit"]["required_status"]:
        raise PropagationDataError("accepted broad response domain is not activated")
    return spec


def _directory_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _preflight(spec: dict[str, Any], source_paths: list[Path]) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise PropagationDataError("system memory headroom below frozen floor")
    usage = shutil.disk_usage(ROOT)
    if usage.free / usage.total < budget["filesystem_headroom_fraction"]:
        raise PropagationDataError("filesystem headroom below frozen floor")
    if sum(path.stat().st_size for path in source_paths) > int(
        budget["compressed_read_ceiling_gib"] * 2**30
    ):
        raise PropagationDataError("compressed source exceeds frozen ceiling")


def _guard(spec: dict[str, Any], temp_dir: Path, started: float) -> None:
    budget = spec["resource_budget"]
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise PropagationDataError("process peak RSS ceiling breached")
    if _directory_bytes(temp_dir) > int(budget["temporary_spill_ceiling_gib"] * 2**30):
        raise PropagationDataError("temporary spill ceiling breached")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise PropagationDataError("wall-clock ceiling breached")


def _audit_predictor(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    path = _resolve(spec["inputs"]["predictor_panel"]["path"])
    predictor = pd.read_csv(path, parse_dates=["trade_date"])
    expected = spec["predictor_audit"]
    keys = ["trade_date", "market_view", "denominator"]
    audit = {
        "rows": len(predictor),
        "dates": predictor["trade_date"].nunique(),
        "first_date": predictor["trade_date"].min().strftime("%Y-%m-%d"),
        "last_date": predictor["trade_date"].max().strftime("%Y-%m-%d"),
        "views": sorted(predictor["market_view"].unique()),
        "denominators": sorted(predictor["denominator"].unique()),
        "duplicate_keys": int(predictor.duplicated(keys).sum()),
        "snapshot_ids": sorted(predictor["snapshot_id"].unique()),
    }
    required = {
        "rows": expected["expected_rows"],
        "dates": expected["expected_dates"],
        "first_date": expected["expected_first_date"],
        "last_date": expected["expected_last_date"],
        "views": sorted(expected["expected_views"]),
        "denominators": sorted(expected["expected_denominators"]),
        "duplicate_keys": expected["duplicate_keys"],
        "snapshot_ids": [expected["snapshot_id"]],
    }
    if audit != required:
        raise PropagationDataError(f"predictor audit mismatch: {audit}")
    for field in (
        expected["anchor_count"],
        expected["crossing_count"],
        expected["formation_depth"],
        expected["formation_depth_pit"],
    ):
        if field not in predictor:
            raise PropagationDataError(f"predictor field missing: {field}")
    return predictor, audit


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
        raise PropagationDataError(f"no anchor rows for event year {event_year}")
    minimum_cal_idx, maximum_cal_idx = int(bounds[0]), int(bounds[1])
    connection.execute(
        """
        CREATE TEMP TABLE response_path AS
        SELECT trade_date,cal_idx,symbol,is_st,cross20,coordinate_high,
               resistance_high20,coordinate_close AS coordinate_close_t
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
        SELECT count(*) FROM response_security
        WHERE NOT (
          cross20=(coordinate_high>resistance_high20)
          AND isfinite(terminal_log_return_h1)
          AND isfinite(terminal_log_return_h3)
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
    ).fetchone()[0]
    if diagnostic != 0:
        raise PropagationDataError("membership-resolved response conservation failed")


def _topology_frames(
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
    metrics = [
        f"{kind}_h{horizon}"
        for kind in ("terminal_log_return", "adverse_log_excursion")
        for horizon in (1, 3, 5)
    ]
    for view, view_filter in views.items():
        for denominator, denominator_filter in denominators.items():
            where = f"({view_filter}) AND ({denominator_filter})"
            aggregate_parts: list[str] = []
            for arm, flag in (("crossing", "cross20"), ("noncrossing", "NOT cross20")):
                aggregate_parts.append(
                    f"count(*) FILTER (WHERE {flag}) AS {arm}_response_count"
                )
                for metric in metrics:
                    aggregate_parts.extend(
                        [
                            f"sum({metric}) FILTER (WHERE {flag}) AS {arm}_{metric}_sum",
                            f"avg({metric}) FILTER (WHERE {flag}) AS {arm}_{metric}_mean",
                        ]
                    )
            aggregate_sql = ",\n".join(aggregate_parts)
            frame = connection.execute(
                f"""
                WITH anchors AS (
                  SELECT trade_date,count(*) AS anchor_count,
                         count(*) FILTER (WHERE cross20) AS anchor_crossing_count,
                         count(*) FILTER (WHERE NOT cross20) AS anchor_noncrossing_count
                  FROM event_security
                  WHERE ({where}) AND year(trade_date)={event_year}
                  GROUP BY trade_date
                ), responses AS (
                  SELECT trade_date,count(*) AS response_count,
                         {aggregate_sql}
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


def _format_scalar(value: Any) -> str:
    if isinstance(value, (bool, np.bool_)):
        return "true" if value else "false"
    return format(float(value), ".17g")


def _scalar_candidates(
    connection: duckdb.DuckDBPyConnection, event_year: int
) -> pd.DataFrame:
    frame = connection.execute(
        """
        WITH candidates AS (
          SELECT *,CASE WHEN cross20 THEN 'crossing' ELSE 'noncrossing' END AS arm,
            sha256('MKT-FORMDEPTH-PROP-DATA-001|' ||
              CASE WHEN cross20 THEN 'crossing' ELSE 'noncrossing' END || '|' ||
              symbol || '|' || strftime(trade_date,'%Y-%m-%d')) AS selection_hash
          FROM response_security
        ), ranked AS (
          SELECT *,row_number() OVER (PARTITION BY arm ORDER BY selection_hash,symbol,trade_date)
            AS arm_rank
          FROM candidates
        )
        SELECT * FROM ranked WHERE arm_rank<=5 ORDER BY arm,selection_hash,symbol,trade_date
        """
    ).fetchdf()
    frame["event_year"] = event_year
    return frame


def _build_scalar_audit(candidates: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    selected = (
        candidates.sort_values(["arm", "selection_hash", "symbol", "trade_date"])
        .groupby("arm", sort=True)
        .head(spec["scalar_reconstruction"]["cases_per_arm"])
    )
    if selected.groupby("arm").size().to_dict() != {"crossing": 5, "noncrossing": 5}:
        raise PropagationDataError("ten scalar cases are not available")
    rows: list[dict[str, Any]] = []
    for case in selected.itertuples(index=False):
        observed = {
            "cross20": bool(case.coordinate_high > case.resistance_high20),
            "coordinate_close_t": case.coordinate_close_t,
            "coordinate_close_t1": case.coordinate_close_t1,
            "coordinate_close_t3": case.coordinate_close_t3,
            "coordinate_close_t5": case.coordinate_close_t5,
            "mapped_low_t1": case.mapped_low_t1,
            "mapped_low_t2": case.mapped_low_t2,
            "mapped_low_t3": case.mapped_low_t3,
            "mapped_low_t4": case.mapped_low_t4,
            "mapped_low_t5": case.mapped_low_t5,
            "terminal_log_return_h1": np.log(case.coordinate_close_t1 / case.coordinate_close_t),
            "terminal_log_return_h3": np.log(case.coordinate_close_t3 / case.coordinate_close_t),
            "terminal_log_return_h5": np.log(case.coordinate_close_t5 / case.coordinate_close_t),
            "adverse_log_excursion_h1": np.log(case.mapped_low_t1 / case.coordinate_close_t),
            "adverse_log_excursion_h3": min(
                np.log(case.mapped_low_t1 / case.coordinate_close_t),
                np.log(case.mapped_low_t2 / case.coordinate_close_t),
                np.log(case.mapped_low_t3 / case.coordinate_close_t),
            ),
            "adverse_log_excursion_h5": min(
                np.log(case.mapped_low_t1 / case.coordinate_close_t),
                np.log(case.mapped_low_t2 / case.coordinate_close_t),
                np.log(case.mapped_low_t3 / case.coordinate_close_t),
                np.log(case.mapped_low_t4 / case.coordinate_close_t),
                np.log(case.mapped_low_t5 / case.coordinate_close_t),
            ),
        }
        for field in spec["scalar_reconstruction"]["exact_fields"]:
            expected_value = getattr(case, field)
            observed_value = observed[field]
            exact = (
                bool(expected_value) == bool(observed_value)
                if field == "cross20"
                else float(expected_value) == float(observed_value)
            )
            rows.append(
                {
                    "selection_hash": case.selection_hash,
                    "arm": case.arm,
                    "symbol": case.symbol,
                    "trade_date": pd.Timestamp(case.trade_date).strftime("%Y-%m-%d"),
                    "field": field,
                    "expected_value": _format_scalar(expected_value),
                    "observed_value": _format_scalar(observed_value),
                    "exact_match": exact,
                }
            )
    audit = pd.DataFrame(rows).sort_values(
        ["arm", "selection_hash", "symbol", "trade_date", "field"]
    )
    if len(audit) != 10 * len(spec["scalar_reconstruction"]["exact_fields"]):
        raise PropagationDataError("scalar audit field count changed")
    if not audit["exact_match"].all():
        failed = audit.loc[~audit["exact_match"]].iloc[0]
        raise PropagationDataError(
            f"scalar mismatch: {failed['arm']}:{failed['symbol']}:{failed['field']}"
        )
    return audit.reset_index(drop=True)


def _strict_equal(left: pd.Series, right: pd.Series) -> bool:
    if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
        return bool(
            np.array_equal(
                left.to_numpy(dtype=float), right.to_numpy(dtype=float), equal_nan=True
            )
        )
    return left.fillna("<NA>").astype(str).equals(right.fillna("<NA>").astype(str))


def _assemble_and_validate(
    predictor: pd.DataFrame,
    recreated_broad: pd.DataFrame,
    topology: pd.DataFrame,
    spec: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    bound_broad = pd.read_csv(
        _resolve(spec["inputs"]["broad_response_panel"]["path"]),
        parse_dates=["trade_date", "response_date_h1", "response_date_h3", "response_date_h5"],
    )
    expected = spec["broad_domain_audit"]
    if len(bound_broad) != expected["expected_panel_rows"]:
        raise PropagationDataError("bound broad panel row count changed")
    broad_fields = [
        "anchor_count",
        "response_count",
        "response_complete",
        *[
            f"{kind}_mean_log_{suffix}_h{horizon}"
            for kind, suffix in (("terminal", "return"), ("adverse", "excursion"))
            for horizon in (1, 3, 5)
        ],
    ]
    # The adverse field names do not contain an extra `log` token before excursion.
    broad_fields = [
        field.replace("adverse_mean_log_excursion", "adverse_mean_log_excursion")
        for field in broad_fields
    ]
    for field in broad_fields:
        if field not in recreated_broad or field not in bound_broad:
            raise PropagationDataError(f"broad reproduction field missing: {field}")
    left = recreated_broad.sort_values(keys).reset_index(drop=True)
    right = bound_broad.sort_values(keys).reset_index(drop=True)
    strict_broad_float_identity = (
        spec.get("broad_float_reproduction_mode", "STRICT_IN_PROCESS")
        == "STRICT_IN_PROCESS"
    )
    if strict_broad_float_identity and not all(
        _strict_equal(left[field], right[field]) for field in broad_fields
    ):
        failed = next(
            field for field in broad_fields if not _strict_equal(left[field], right[field])
        )
        left_values = left[failed].to_numpy(dtype=float)
        right_values = right[failed].to_numpy(dtype=float)
        mismatch = ~(
            (left_values == right_values)
            | (np.isnan(left_values) & np.isnan(right_values))
        )
        first = int(np.flatnonzero(mismatch)[0])
        key = tuple(str(left.loc[first, column]) for column in keys)
        raise PropagationDataError(
            "exact broad response reproduction failed: "
            f"{failed}:{key}:recreated={left_values[first]!r}:"
            f"bound={right_values[first]!r}:difference="
            f"{left_values[first] - right_values[first]!r}"
        )

    selected_predictor = predictor[
        [
            *keys,
            "eligible_count20",
            "crossing_count20",
            "breakout_formation_depth20",
            "breakout_formation_depth20_pit_3y_pct",
        ]
    ]
    panel = topology.merge(selected_predictor, on=keys, how="left", validate="one_to_one")
    panel = panel.merge(
        right[
            [
                *keys,
                "response_complete",
                "response_date_h1",
                "response_date_h3",
                "response_date_h5",
                "response_available_at_h1",
                "response_available_at_h3",
                "response_available_at_h5",
                "terminal_mean_log_return_h1",
                "terminal_mean_log_return_h3",
                "terminal_mean_log_return_h5",
                "adverse_mean_log_excursion_h1",
                "adverse_mean_log_excursion_h3",
                "adverse_mean_log_excursion_h5",
            ]
        ],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    integer_checks = {
        "anchor": panel["anchor_count"].eq(panel["eligible_count20"]),
        "anchor_crossing": panel["anchor_crossing_count"].eq(panel["crossing_count20"]),
        "anchor_exhaustion": panel["anchor_count"].eq(
            panel["anchor_crossing_count"] + panel["anchor_noncrossing_count"]
        ),
        "response_exhaustion": panel["response_count"].eq(
            panel["crossing_response_count"] + panel["noncrossing_response_count"]
        )
        | panel["response_count"].isna(),
    }
    failed_checks = {name: int((~values).sum()) for name, values in integer_checks.items()}
    if any(failed_checks.values()):
        raise PropagationDataError(f"cohort integer conservation failed: {failed_checks}")
    panel["crossing_response_retention"] = (
        panel["crossing_response_count"] / panel["anchor_crossing_count"]
    )
    crossing_floors = spec["topology_support"]["minimum_crossing_response_count"]
    noncrossing_floors = spec["topology_support"]["minimum_noncrossing_response_count"]
    panel["topology_complete"] = (
        panel["response_complete"].eq(True)
        & panel["crossing_response_retention"].ge(
            spec["topology_support"]["minimum_crossing_retention"]
        )
        & panel["crossing_response_count"].ge(panel["market_view"].map(crossing_floors))
        & panel["noncrossing_response_count"].ge(
            panel["market_view"].map(noncrossing_floors)
        )
    )
    arm_metric_columns = [
        column
        for column in panel
        if (column.startswith("crossing_") or column.startswith("noncrossing_"))
        and (column.endswith("_sum") or column.endswith("_mean"))
    ]
    finite = np.isfinite(
        panel.loc[panel["topology_complete"], arm_metric_columns].to_numpy(dtype=float)
    ).all()
    if not finite:
        raise PropagationDataError("nonfinite topology-complete arm metric")
    panel["event_year"] = panel["trade_date"].dt.year
    count_audit = (
        panel.groupby(["market_view", "denominator", "event_year"], sort=True)
        .agg(
            date_cells=("trade_date", "size"),
            broad_complete_cells=("response_complete", "sum"),
            topology_complete_cells=("topology_complete", "sum"),
            minimum_anchor_crossing_count=("anchor_crossing_count", "min"),
            minimum_crossing_response_count=("crossing_response_count", "min"),
            minimum_crossing_retention=("crossing_response_retention", "min"),
            minimum_noncrossing_response_count=("noncrossing_response_count", "min"),
        )
        .reset_index()
    )
    minimum_dates = int(count_audit["topology_complete_cells"].min())
    gates = {
        "broad_panel_rows": len(panel) == expected["expected_panel_rows"],
        "broad_complete_cells": int(panel["response_complete"].sum())
        == expected["expected_complete_cells"],
        "broad_response_identity": (
            "EXACT_IN_PROCESS_REPRODUCTION"
            if strict_broad_float_identity
            else "IMMUTABLE_BOUND_PANEL_HASH"
        ),
        "anchor_and_response_exhaustion": True,
        "finite_arm_sums_and_means": bool(finite),
        "minimum_topology_dates_per_cell_year": minimum_dates
        >= spec["topology_support"]["minimum_complete_dates_per_view_denominator_year"],
    }
    validation = {
        "gates": gates,
        "all_pass": all(
            value for value in gates.values() if isinstance(value, (bool, np.bool_))
        ),
        "minimum_topology_complete_dates_per_cell_year": minimum_dates,
        "topology_complete_cells": int(panel["topology_complete"].sum()),
        "minimum_crossing_response_retention_complete": float(
            panel.loc[panel["topology_complete"], "crossing_response_retention"].min()
        ),
        "maximum_response_date": str(
            panel.loc[panel["response_complete"], "response_date_h5"].max().date()
        ),
    }
    return panel.sort_values(keys).reset_index(drop=True), count_audit, validation


def _write_report(result: dict[str, Any]) -> None:
    validation = result["response_domain"]
    minimum_dates = validation["minimum_topology_complete_dates_per_cell_year"]
    minimum_retention = validation["minimum_crossing_response_retention_complete"]
    report = f"""# {result['experiment_id']} membership response audit

## Result

- Status: `{result['status']}`
- Broad panel cells: {result['population']['panel_rows']:,}
- Broad complete cells: {result['population']['broad_complete_cells']:,}
- Topology-complete cells: {result['population']['topology_complete_cells']:,}
- Minimum topology-complete dates per view/denominator/year: {minimum_dates}
- Minimum crossing retention among topology-complete cells: {minimum_retention:.6f}
- Broad-response identity: {validation['gates']['broad_response_identity']}
- Exact anchor/response arm exhaustion: {validation['gates']['anchor_and_response_exhaustion']}
- Ten arm-balanced scalar cases exact: {result['scalar_reconstruction']['all_exact']}
- Maximum consumed response date: {validation['maximum_response_date']}

This is an outcome-domain audit only. No formation-depth/arm correlation, partial
response, tail contrast, favorable channel, localization/propagation
classification, strategy outcome, or rule was computed. Post-2023 data and CY-011
were not read.
"""
    REPORT_PATH.write_text(report, encoding="utf-8")


def main(spec_override: dict[str, Any] | None = None) -> None:
    started = time.monotonic()
    spec = _load_spec() if spec_override is None else spec_override
    economic_data = _import(ECON_DATA_RUNNER, "accepted_economic_response_data")
    coordinate = economic_data._load_coordinate_module(spec)
    try:
        source_paths, source_hashes = economic_data._verify_partitions(spec, coordinate)
    except Exception as exc:
        raise PropagationDataError(str(exc)) from exc
    _preflight(spec, source_paths)
    predictor, predictor_audit = _audit_predictor(spec)
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-prop-data-") as temp_raw:
        temp_dir = Path(temp_raw)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped_temp = str(temp_dir).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped_temp}'")
        try:
            try:
                source_audit = coordinate._create_source_and_audit(
                    connection, source_paths, spec
                )
                coordinate._create_event_security(
                    economic_data._PreserveCoordinateWindow(connection)
                )
            except Exception as exc:
                raise PropagationDataError(str(exc)) from exc
            economic_data._create_future_coordinate(connection)
            response_dates = economic_data._calendar_response_dates(connection)
            broad_parts: list[pd.DataFrame] = []
            topology_parts: list[pd.DataFrame] = []
            candidate_parts: list[pd.DataFrame] = []
            for event_year in (2018, 2019, 2020, 2021, 2022, 2023):
                # Preserve the immutable broad aggregation's physical table layout.
                # Adding membership columns changes binary floating summation order.
                economic_data._create_response_security(connection, event_year)
                broad_parts.append(economic_data._group_frames(connection, event_year))
                connection.execute("DROP TABLE response_security")
                _create_response_security(connection, event_year)
                topology_parts.append(_topology_frames(connection, event_year))
                candidate_parts.append(_scalar_candidates(connection, event_year))
                connection.execute("DROP TABLE response_security")
                _guard(spec, temp_dir, started)
        finally:
            connection.close()
        _guard(spec, temp_dir, started)
    grouped_broad = pd.concat(broad_parts, ignore_index=True)
    recreated_broad = economic_data._assemble_panel(predictor, grouped_broad, response_dates)
    topology = pd.concat(topology_parts, ignore_index=True)
    panel, count_audit, validation = _assemble_and_validate(
        predictor, recreated_broad, topology, spec
    )
    scalar_audit = _build_scalar_audit(pd.concat(candidate_parts, ignore_index=True), spec)
    validation["gates"]["ten_scalar_cases_exact"] = bool(scalar_audit["exact_match"].all())
    validation["all_pass"] = all(
        value
        for value in validation["gates"].values()
        if isinstance(value, (bool, np.bool_))
    )
    status = (
        "COMPLETE_MEMBERSHIP_RESPONSE_DOMAIN_ADEQUACY"
        if validation["all_pass"]
        else "COMPLETE_MEMBERSHIP_RESPONSE_DOMAIN_INADEQUATE_FAIL_CLOSED"
    )
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    count_audit.to_csv(COUNT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    scalar_audit.to_csv(SCALAR_PATH, index=False, lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "source_audit": source_audit,
        "predictor_audit": predictor_audit,
        "response_domain": validation,
        "population": {
            "panel_rows": len(panel),
            "broad_complete_cells": int(panel["response_complete"].sum()),
            "topology_complete_cells": int(panel["topology_complete"].sum()),
            "count_audit_rows": len(count_audit),
        },
        "scalar_reconstruction": {
            "cases": scalar_audit["selection_hash"].nunique(),
            "cases_per_arm": scalar_audit.groupby("arm")["selection_hash"].nunique().to_dict(),
            "fields": scalar_audit["field"].nunique(),
            "all_exact": bool(scalar_audit["exact_match"].all()),
        },
        "source_partitions": source_hashes,
        "state_outcome_estimates_computed": False,
        "topology_classification_computed": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "resource_contract": spec["resource_budget"],
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "runner_sha256": sha256_file(Path(__file__)),
        "panel_sha256": sha256_file(PANEL_PATH),
        "count_audit_sha256": sha256_file(COUNT_PATH),
        "scalar_audit_sha256": sha256_file(SCALAR_PATH),
    }
    if "entry_runner_path" in spec:
        result["hashes"]["entry_runner_sha256"] = sha256_file(
            _resolve(spec["entry_runner_path"])
        )
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_report(result)
    durable = sum(
        path.stat().st_size
        for path in (PANEL_PATH, COUNT_PATH, SCALAR_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise PropagationDataError("durable output ceiling breached")
    if not validation["all_pass"]:
        raise PropagationDataError(f"response-domain gate failed: {validation['gates']}")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
