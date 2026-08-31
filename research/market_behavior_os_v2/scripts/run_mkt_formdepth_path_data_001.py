#!/usr/bin/env python3
"""Build the frozen formation-depth adverse-path component domain."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import time
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-PATH-DATA-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-DATA-001_panel.csv"
COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-DATA-001_count_audit.csv"
SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-DATA-001_scalar_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-PATH-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-PATH-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "8c222329448443ce2079df9a8b7fe25016fcf321abd61e8354adfb8f199e2854"


class PathDataError(RuntimeError):
    """Fail-closed adverse-path component data error."""


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
        raise PathDataError(f"cannot load bound module: {path}")
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
        raise PathDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_ADVERSE_PATH_COMPONENT_CONSTRUCTION"
        or spec["outcome_access"]
        != "FUTURE_PRE2024_CROSSER_OPEN_LOW_CLOSE_COMPONENT_CONSTRUCTION_ONLY"
    ):
        raise PathDataError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise PathDataError(f"input identity mismatch: {name}")
    closing = json.loads(_resolve(spec["inputs"]["closing_result"]["path"]).read_text())
    crossing = json.loads(
        _resolve(spec["inputs"]["crossing_result"]["path"]).read_text()
    )
    topology = json.loads(
        _resolve(spec["inputs"]["closing_topology_result"]["path"]).read_text()
    )
    activation = spec["activation"]
    if closing["status"] != activation["required_closing_domain_status"]:
        raise PathDataError("closing response domain is not activated")
    if crossing["status"] != activation["required_crossing_domain_status"]:
        raise PathDataError("crossing response domain is not activated")
    if topology["classification"] != activation["required_closing_classification"]:
        raise PathDataError("closing-state topology is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise PathDataError("prohibited boundary changed")
    return spec


def _create_future_coordinate(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """
        CREATE TEMP TABLE future_coordinate AS
        SELECT symbol,cal_idx,history_valid,coordinate_step_valid,coordinate_close,
               open AS raw_open,low AS raw_low,close AS raw_close,
               coordinate_close*(open/close) AS mapped_open,
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
        raise PathDataError(f"no anchor rows for event year {event_year}")
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
                   f.mapped_open AS mapped_open_t{offset},
                   f.mapped_low AS mapped_low_t{offset}
            FROM response_path p JOIN future_coordinate f
              ON f.symbol=p.symbol AND f.cal_idx=p.cal_idx+{offset}
            WHERE f.cal_idx BETWEEN {minimum_cal_idx + 1} AND {maximum_cal_idx + 5}
              AND f.history_valid AND f.coordinate_step_valid
              AND isfinite(f.coordinate_close) AND f.coordinate_close>0
              AND isfinite(f.mapped_open) AND f.mapped_open>0
              AND isfinite(f.mapped_low) AND f.mapped_low>0
            """
        )
        connection.execute("DROP TABLE response_path")
        connection.execute("ALTER TABLE response_path_next RENAME TO response_path")
    connection.execute(
        """
        CREATE TEMP TABLE response_security AS
        WITH base AS (
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
                  ln(mapped_low_t5/coordinate_close_t)) AS adverse_log_excursion_h5,
            1 AS trough_offset_h1,
            CASE
              WHEN mapped_low_t1=least(mapped_low_t1,mapped_low_t2,mapped_low_t3)
                THEN 1
              WHEN mapped_low_t2=least(mapped_low_t1,mapped_low_t2,mapped_low_t3)
                THEN 2
              ELSE 3 END AS trough_offset_h3,
            CASE
              WHEN mapped_low_t1=least(mapped_low_t1,mapped_low_t2,mapped_low_t3,
                                        mapped_low_t4,mapped_low_t5) THEN 1
              WHEN mapped_low_t2=least(mapped_low_t1,mapped_low_t2,mapped_low_t3,
                                        mapped_low_t4,mapped_low_t5) THEN 2
              WHEN mapped_low_t3=least(mapped_low_t1,mapped_low_t2,mapped_low_t3,
                                        mapped_low_t4,mapped_low_t5) THEN 3
              WHEN mapped_low_t4=least(mapped_low_t1,mapped_low_t2,mapped_low_t3,
                                        mapped_low_t4,mapped_low_t5) THEN 4
              ELSE 5 END AS trough_offset_h5
          FROM response_path
        ), selected AS (
          SELECT *,mapped_open_t1 AS trough_open_h1,
            CASE trough_offset_h3 WHEN 1 THEN mapped_open_t1
              WHEN 2 THEN mapped_open_t2 ELSE mapped_open_t3 END AS trough_open_h3,
            CASE trough_offset_h5 WHEN 1 THEN mapped_open_t1
              WHEN 2 THEN mapped_open_t2 WHEN 3 THEN mapped_open_t3
              WHEN 4 THEN mapped_open_t4 ELSE mapped_open_t5 END AS trough_open_h5
          FROM base
        ), preopen AS (
          SELECT *,ln(trough_open_h1/coordinate_close_t) AS preopen_path_to_trough_h1,
            ln(trough_open_h3/coordinate_close_t) AS preopen_path_to_trough_h3,
            ln(trough_open_h5/coordinate_close_t) AS preopen_path_to_trough_h5
          FROM selected
        )
        SELECT *,
          adverse_log_excursion_h1-preopen_path_to_trough_h1
            AS trough_session_intraday_h1,
          adverse_log_excursion_h3-preopen_path_to_trough_h3
            AS trough_session_intraday_h3,
          adverse_log_excursion_h5-preopen_path_to_trough_h5
            AS trough_session_intraday_h5,
          terminal_log_return_h1-adverse_log_excursion_h1
            AS post_trough_recovery_h1,
          terminal_log_return_h3-adverse_log_excursion_h3
            AS post_trough_recovery_h3,
          terminal_log_return_h5-adverse_log_excursion_h5
            AS post_trough_recovery_h5
        FROM preopen
        """
    )
    connection.execute("DROP TABLE response_path")
    component_fields = [
        f"{component}_h{horizon}"
        for component in (
            "preopen_path_to_trough",
            "trough_session_intraday",
            "post_trough_recovery",
        )
        for horizon in (1, 3, 5)
    ]
    invalid = connection.execute(
        f"""
        SELECT count(*) FROM response_security
        WHERE NOT (
          cross20=(coordinate_high>resistance_high20)
          AND trough_offset_h1=1 AND trough_offset_h3 BETWEEN 1 AND 3
          AND trough_offset_h5 BETWEEN 1 AND 5
          AND {' AND '.join(f'isfinite({field})' for field in component_fields)}
          AND post_trough_recovery_h1>=0
          AND post_trough_recovery_h3>=0
          AND post_trough_recovery_h5>=0)
        """
    ).fetchone()[0]
    if invalid != 0:
        raise PathDataError("adverse-path coordinate conservation failed")


def _arm_sql(arm: str) -> str:
    if arm == "crossing":
        return "cross20"
    if arm == "accepted":
        return "cross20 AND coordinate_close_t>resistance_high20"
    return "cross20 AND coordinate_close_t<resistance_high20"


def _path_frames(
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
    components = (
        "preopen_path_to_trough",
        "trough_session_intraday",
        "post_trough_recovery",
    )
    frames: list[pd.DataFrame] = []
    for view, view_filter in views.items():
        for denominator, denominator_filter in denominators.items():
            where = f"({view_filter}) AND ({denominator_filter})"
            aggregates: list[str] = []
            for arm in ("crossing", "accepted", "rejected"):
                flag = _arm_sql(arm)
                aggregates.append(
                    f"count(*) FILTER (WHERE {flag}) AS {arm}_response_count"
                )
                for component in components:
                    for horizon in (1, 3, 5):
                        field = f"{component}_h{horizon}"
                        aggregates.extend(
                            [
                                f"sum({field}) FILTER (WHERE {flag}) AS {arm}_{field}_sum",
                                f"avg({field}) FILTER (WHERE {flag}) AS {arm}_{field}_mean",
                            ]
                        )
                for horizon in (1, 3, 5):
                    for offset in range(1, horizon + 1):
                        aggregates.append(
                            f"count(*) FILTER (WHERE {flag} AND "
                            f"trough_offset_h{horizon}={offset}) AS "
                            f"{arm}_trough_h{horizon}_offset{offset}_count"
                        )
            aggregates.append(
                "count(*) FILTER (WHERE cross20 AND "
                "coordinate_close_t=resistance_high20) AS equal_response_count"
            )
            aggregate_sql = ",\n".join(aggregates)
            frame = connection.execute(
                f"""
                WITH anchors AS (
                  SELECT DISTINCT trade_date FROM event_security
                  WHERE ({where}) AND year(trade_date)={event_year}
                ), responses AS (
                  SELECT trade_date,{aggregate_sql}
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


def _scalar_candidates(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return connection.execute(
        """
        WITH candidates AS (
          SELECT *,CASE
            WHEN cross20 AND coordinate_close_t>resistance_high20 THEN 'accepted'
            WHEN cross20 AND coordinate_close_t<resistance_high20 THEN 'rejected'
            WHEN cross20 AND coordinate_close_t=resistance_high20 THEN 'equal'
            ELSE NULL END AS closing_arm
          FROM response_security WHERE cross20
        ), hashed AS (
          SELECT *,sha256('MKT-FORMDEPTH-PATH-DATA-001|' || closing_arm || '|' ||
            symbol || '|' || strftime(trade_date,'%Y-%m-%d')) AS selection_hash
          FROM candidates
        ), ranked AS (
          SELECT *,row_number() OVER (
            PARTITION BY closing_arm ORDER BY selection_hash,symbol,trade_date
          ) AS arm_rank FROM hashed
        )
        SELECT * FROM ranked WHERE arm_rank<=5
        ORDER BY closing_arm,selection_hash,symbol,trade_date
        """
    ).fetchdf()


def _scalar_audit(candidates: pd.DataFrame, spec: dict[str, Any], base: Any) -> pd.DataFrame:
    candidates = (
        candidates.sort_values(
            ["closing_arm", "selection_hash", "symbol", "trade_date"]
        )
        .groupby("closing_arm", sort=True)
        .head(spec["scalar_reconstruction"]["cases_per_arm"])
    )
    expected_counts = {arm: 5 for arm in spec["scalar_reconstruction"]["arms"]}
    if candidates.groupby("closing_arm").size().to_dict() != expected_counts:
        raise PathDataError("arm-balanced scalar cases unavailable")
    rows: list[dict[str, Any]] = []
    for case in candidates.itertuples(index=False):
        closing_arm = (
            "accepted"
            if case.coordinate_close_t > case.resistance_high20
            else "rejected"
            if case.coordinate_close_t < case.resistance_high20
            else "equal"
        )
        opens = [getattr(case, f"mapped_open_t{offset}") for offset in range(1, 6)]
        lows = [getattr(case, f"mapped_low_t{offset}") for offset in range(1, 6)]
        observed: dict[str, Any] = {
            "closing_arm": closing_arm,
            "coordinate_close_t": case.coordinate_close_t,
            "resistance_high20": case.resistance_high20,
        }
        for offset in range(1, 6):
            observed[f"mapped_open_t{offset}"] = opens[offset - 1]
            observed[f"mapped_low_t{offset}"] = lows[offset - 1]
        for horizon in (1, 3, 5):
            terminal = np.log(
                getattr(case, f"coordinate_close_t{horizon}") / case.coordinate_close_t
            )
            logs = [np.log(value / case.coordinate_close_t) for value in lows[:horizon]]
            trough_offset = min(range(horizon), key=lambda index: lows[index]) + 1
            trough_open = opens[trough_offset - 1]
            adverse = min(logs)
            preopen = np.log(trough_open / case.coordinate_close_t)
            observed[f"coordinate_close_t{horizon}"] = getattr(
                case, f"coordinate_close_t{horizon}"
            )
            observed[f"trough_offset_h{horizon}"] = trough_offset
            observed[f"trough_open_h{horizon}"] = trough_open
            observed[f"adverse_log_excursion_h{horizon}"] = adverse
            observed[f"terminal_log_return_h{horizon}"] = terminal
            observed[f"preopen_path_to_trough_h{horizon}"] = preopen
            observed[f"trough_session_intraday_h{horizon}"] = adverse - preopen
            observed[f"post_trough_recovery_h{horizon}"] = terminal - adverse
        for field in spec["scalar_reconstruction"]["exact_fields"]:
            expected_value = getattr(case, field)
            observed_value = observed[field]
            exact = (
                str(expected_value) == str(observed_value)
                if field == "closing_arm"
                else float(expected_value) == float(observed_value)
            )
            rows.append(
                {
                    "selection_hash": case.selection_hash,
                    "closing_arm": case.closing_arm,
                    "symbol": case.symbol,
                    "trade_date": pd.Timestamp(case.trade_date).strftime("%Y-%m-%d"),
                    "field": field,
                    "expected_value": (
                        str(expected_value)
                        if field == "closing_arm"
                        else base._format_scalar(expected_value)
                    ),
                    "observed_value": (
                        str(observed_value)
                        if field == "closing_arm"
                        else base._format_scalar(observed_value)
                    ),
                    "exact_match": exact,
                }
            )
    audit = pd.DataFrame(rows).sort_values(
        ["closing_arm", "selection_hash", "symbol", "trade_date", "field"]
    )
    if not audit["exact_match"].all():
        failed = audit.loc[~audit["exact_match"]].iloc[0]
        raise PathDataError(f"scalar mismatch: {failed.to_dict()}")
    return audit.reset_index(drop=True)


def _assemble(
    timing: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    closing = pd.read_csv(
        _resolve(spec["inputs"]["closing_panel"]["path"]),
        parse_dates=["trade_date", "response_date_h1", "response_date_h3", "response_date_h5"],
    )
    crossing = pd.read_csv(
        _resolve(spec["inputs"]["crossing_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    if len(closing) != spec["activation"]["expected_panel_rows"]:
        raise PathDataError("closing panel row count changed")
    bound_columns = [
        *keys,
        "closing_topology_complete",
        "crossing_response_count",
        "accepted_response_count",
        "rejected_response_count",
        "equal_response_count",
        "response_date_h1",
        "response_date_h3",
        "response_date_h5",
        "response_available_at_h1",
        "response_available_at_h3",
        "response_available_at_h5",
        "breakout_formation_depth20",
        "breakout_formation_depth20_pit_3y_pct",
    ]
    crossing_columns = [
        *keys,
        *[
            f"crossing_{kind}_h{horizon}_mean"
            for kind in ("terminal_log_return", "adverse_log_excursion")
            for horizon in (1, 3, 5)
        ],
    ]
    panel = timing.merge(
        closing[bound_columns],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_bound"),
    ).merge(crossing[crossing_columns], on=keys, how="left", validate="one_to_one")
    checks = {
        "crossing_count": panel["crossing_response_count"].eq(
            panel["crossing_response_count_bound"]
        )
        | panel["crossing_response_count"].isna(),
        "accepted_count": panel["accepted_response_count"].eq(
            panel["accepted_response_count_bound"]
        )
        | panel["accepted_response_count"].isna(),
        "rejected_count": panel["rejected_response_count"].eq(
            panel["rejected_response_count_bound"]
        )
        | panel["rejected_response_count"].isna(),
        "equal_count": panel["equal_response_count"].eq(
            panel["equal_response_count_bound"]
        )
        | panel["equal_response_count"].isna(),
        "arm_exhaustion": panel["crossing_response_count"].eq(
            panel["accepted_response_count"]
            + panel["rejected_response_count"]
            + panel["equal_response_count"]
        )
        | panel["crossing_response_count"].isna(),
    }
    failures = {name: int((~value).sum()) for name, value in checks.items()}
    if any(failures.values()):
        raise PathDataError(f"bound response count mismatch: {failures}")
    component_columns = [
        column
        for column in panel
        if column.startswith(("crossing_", "accepted_", "rejected_"))
        and column.endswith(("_sum", "_mean"))
    ]
    panel["path_topology_complete"] = panel["closing_topology_complete"].eq(True)
    complete = panel["path_topology_complete"]
    if not np.isfinite(panel.loc[complete, component_columns].to_numpy(dtype=float)).all():
        raise PathDataError("nonfinite path component in complete domain")
    if int(complete.sum()) != spec["activation"]["expected_closing_complete_rows"]:
        raise PathDataError("path-topology-complete row count changed")
    panel["event_year"] = panel["trade_date"].dt.year
    count = (
        panel.groupby(["market_view", "denominator", "event_year"], sort=True)
        .agg(
            date_cells=("trade_date", "size"),
            closing_complete_cells=("closing_topology_complete", "sum"),
            path_complete_cells=("path_topology_complete", "sum"),
            minimum_crossing_response=("crossing_response_count", "min"),
            minimum_accepted_response=("accepted_response_count", "min"),
            minimum_rejected_response=("rejected_response_count", "min"),
        )
        .reset_index()
    )
    minimum_dates = int(count["path_complete_cells"].min())
    minimum_gate = minimum_dates >= spec["support"][
        "minimum_closing_complete_dates_per_view_denominator_year"
    ]
    validation = {
        "exact_bound_arm_counts_and_exhaustion": True,
        "path_topology_complete_cells": int(complete.sum()),
        "minimum_path_complete_dates_per_cell_year": minimum_dates,
        "minimum_dates_gate": minimum_gate,
        "component_fields_finite": True,
    }
    if not minimum_gate:
        raise PathDataError(f"path component support failed: {validation}")
    return panel.sort_values(keys).reset_index(drop=True), count, validation


def _report(result: dict[str, Any]) -> str:
    domain = result["response_domain"]
    scalar = result["scalar_reconstruction"]
    return f"""# MKT-FORMDEPTH-PATH-DATA-001 response-component audit

- Status: `{result['status']}`
- Path-topology-complete cells: {domain['path_topology_complete_cells']:,}
- Minimum complete dates per cell/year: {domain['minimum_path_complete_dates_per_cell_year']}
- Exact bound arm counts/exhaustion: {domain['exact_bound_arm_counts_and_exhaustion']}
- Scalar cases/fields exact: {scalar['cases']}/{scalar['fields']}

This is response-component adequacy only. No formation-depth association, timing
classification, recovery interpretation, execution, habitat, payoff, or strategy
was computed. Future path fields are post-decision attribution only. Post-2023
data and CY-011 were not read.
"""


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    base = _import(
        _resolve(spec["inputs"]["inherited_data_runner"]["path"]),
        "inherited_path_data",
    )
    inherited = base._load_spec()
    economic_data = base._import(base.ECON_DATA_RUNNER, "accepted_economic_data_path")
    coordinate = economic_data._load_coordinate_module(inherited)
    source_paths, source_hashes = economic_data._verify_partitions(inherited, coordinate)
    base._preflight(inherited, source_paths)
    _, predictor_audit = base._audit_predictor(inherited)
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-path-data-") as temp_raw:
        temp_dir = Path(temp_raw)
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped_temp = str(temp_dir).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped_temp}'")
        try:
            source_audit = coordinate._create_source_and_audit(
                connection, source_paths, inherited
            )
            coordinate._create_event_security(
                economic_data._PreserveCoordinateWindow(connection)
            )
            _create_future_coordinate(connection)
            frames: list[pd.DataFrame] = []
            candidates: list[pd.DataFrame] = []
            for event_year in (2018, 2019, 2020, 2021, 2022, 2023):
                _create_response_security(connection, event_year)
                frames.append(_path_frames(connection, event_year))
                candidates.append(_scalar_candidates(connection))
                connection.execute("DROP TABLE response_security")
                base._guard(inherited, temp_dir, started)
        finally:
            connection.close()
        base._guard(inherited, temp_dir, started)
    panel, count, validation = _assemble(pd.concat(frames, ignore_index=True), spec)
    scalar = _scalar_audit(pd.concat(candidates, ignore_index=True), spec, base)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    count.to_csv(COUNT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    scalar.to_csv(SCALAR_PATH, index=False, lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_ADVERSE_PATH_COMPONENT_DOMAIN_ADEQUACY",
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "source_audit": source_audit,
        "predictor_audit": predictor_audit,
        "response_domain": validation,
        "population": {"panel_rows": len(panel), "count_audit_rows": len(count)},
        "scalar_reconstruction": {
            "cases": scalar["selection_hash"].nunique(),
            "cases_per_arm": scalar.groupby("closing_arm")["selection_hash"]
            .nunique()
            .to_dict(),
            "fields": scalar["field"].nunique(),
            "all_exact": bool(scalar["exact_match"].all()),
        },
        "source_partitions": source_hashes,
        "component_association_computed": False,
        "timing_classification_computed": False,
        "future_components_used_as_predictors": False,
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
    durable = sum(
        path.stat().st_size
        for path in (PANEL_PATH, COUNT_PATH, SCALAR_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise PathDataError("durable output ceiling breached")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
