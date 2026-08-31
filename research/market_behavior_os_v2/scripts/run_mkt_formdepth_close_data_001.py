#!/usr/bin/env python3
"""Build the frozen accepted/rejected objective-crosser response domain."""

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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-CLOSE-DATA-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-DATA-001_panel.csv"
COUNT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-DATA-001_count_audit.csv"
SCALAR_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-DATA-001_scalar_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-CLOSE-DATA-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-CLOSE-DATA-001_audit.md"
EXPECTED_SPEC_SHA256 = "339783b92c41bae97fa5294926921183ff3480a185bf32d39a44176a8a9c1e2e"


class ClosingDataError(RuntimeError):
    """Fail-closed objective-crosser closing-arm response-domain error."""


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
        raise ClosingDataError(f"cannot load bound module: {path}")
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
        raise ClosingDataError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_CLOSING_ARM_RESPONSE_CONSTRUCTION"
        or spec["outcome_access"]
        != "FUTURE_PRE2024_CROSSER_CLOSING_ARM_RESPONSE_CONSTRUCTION_ONLY"
    ):
        raise ClosingDataError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ClosingDataError(f"input identity mismatch: {name}")
    crossing = json.loads(
        _resolve(spec["inputs"]["crossing_response_result"]["path"]).read_text()
    )
    if crossing["status"] != spec["activation"]["required_crossing_domain_status"]:
        raise ClosingDataError("crossing response domain is not activated")
    propagation = json.loads(
        _resolve(spec["inputs"]["propagation_result"]["path"]).read_text()
    )
    if (
        propagation["classification"]
        != spec["activation"]["required_propagation_classification"]
    ):
        raise ClosingDataError("localized crossing response is not activated")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise ClosingDataError("prohibited boundary changed")
    return spec


def _arm_sql(alias: str) -> str:
    if alias == "accepted":
        return "cross20 AND coordinate_close_t>resistance_high20"
    if alias == "rejected":
        return "cross20 AND coordinate_close_t<resistance_high20"
    return "cross20 AND coordinate_close_t=resistance_high20"


def _closing_frames(
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
    metrics = [
        f"{kind}_h{horizon}"
        for kind in ("terminal_log_return", "adverse_log_excursion")
        for horizon in (1, 3, 5)
    ]
    frames: list[pd.DataFrame] = []
    for view, view_filter in views.items():
        for denominator, denominator_filter in denominators.items():
            where = f"({view_filter}) AND ({denominator_filter})"
            aggregate_parts: list[str] = []
            for arm in ("accepted", "rejected", "equal"):
                flag = _arm_sql(arm)
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
                  SELECT trade_date,
                    count(*) FILTER (WHERE cross20) AS anchor_crossing_count,
                    count(*) FILTER (WHERE cross20 AND coordinate_close>resistance_high20)
                      AS anchor_accepted_count,
                    count(*) FILTER (WHERE cross20 AND coordinate_close<resistance_high20)
                      AS anchor_rejected_count,
                    count(*) FILTER (WHERE cross20 AND coordinate_close=resistance_high20)
                      AS anchor_equal_count
                  FROM event_security
                  WHERE ({where}) AND year(trade_date)={event_year}
                  GROUP BY trade_date
                ), responses AS (
                  SELECT trade_date,count(*) FILTER (WHERE cross20) AS crossing_response_count,
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
          SELECT *,sha256('MKT-FORMDEPTH-CLOSE-DATA-001|' || closing_arm || '|' ||
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
    selected = (
        candidates.sort_values(["closing_arm", "selection_hash", "symbol", "trade_date"])
        .groupby("closing_arm", sort=True)
        .head(spec["scalar_reconstruction"]["cases_per_arm"])
    )
    expected_counts = {arm: 5 for arm in spec["scalar_reconstruction"]["arms"]}
    if selected.groupby("closing_arm").size().to_dict() != expected_counts:
        raise ClosingDataError("arm-balanced scalar cases unavailable")
    rows: list[dict[str, Any]] = []
    for case in selected.itertuples(index=False):
        closing_arm = (
            "accepted"
            if case.coordinate_close_t > case.resistance_high20
            else "rejected"
            if case.coordinate_close_t < case.resistance_high20
            else "equal"
        )
        observed = {
            "closing_arm": closing_arm,
            "coordinate_close_t": case.coordinate_close_t,
            "resistance_high20": case.resistance_high20,
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
        raise ClosingDataError(f"scalar mismatch: {failed.to_dict()}")
    return audit.reset_index(drop=True)


def _assemble(
    closing: pd.DataFrame, predictor: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    keys = ["trade_date", "market_view", "denominator"]
    crossing = pd.read_csv(
        _resolve(spec["inputs"]["crossing_response_panel"]["path"]),
        parse_dates=["trade_date", "response_date_h1", "response_date_h3", "response_date_h5"],
    )
    if len(crossing) != spec["activation"]["expected_crossing_panel_rows"]:
        raise ClosingDataError("crossing panel row count changed")
    predictor_columns = [
        *keys,
        "crossing_count20",
        "close_above_count20",
        "close_below_count20",
        "close_equal_count20",
    ]
    panel = closing.merge(
        predictor[predictor_columns], on=keys, how="left", validate="one_to_one"
    ).merge(
        crossing[
            [
                *keys,
                "crossing_response_count",
                "topology_complete",
                "response_date_h1",
                "response_date_h3",
                "response_date_h5",
                "response_available_at_h1",
                "response_available_at_h3",
                "response_available_at_h5",
                "breakout_formation_depth20",
                "breakout_formation_depth20_pit_3y_pct",
            ]
        ],
        on=keys,
        how="left",
        validate="one_to_one",
        suffixes=("", "_bound"),
    )
    checks = {
        "anchor_crossing": panel["anchor_crossing_count"].eq(panel["crossing_count20"]),
        "anchor_accepted": panel["anchor_accepted_count"].eq(panel["close_above_count20"]),
        "anchor_rejected": panel["anchor_rejected_count"].eq(panel["close_below_count20"]),
        "anchor_equal": panel["anchor_equal_count"].eq(panel["close_equal_count20"]),
        "anchor_exhaustion": panel["anchor_crossing_count"].eq(
            panel["anchor_accepted_count"]
            + panel["anchor_rejected_count"]
            + panel["anchor_equal_count"]
        ),
        "response_crossing": panel["crossing_response_count"].eq(
            panel["crossing_response_count_bound"]
        )
        | panel["crossing_response_count"].isna(),
        "response_exhaustion": panel["crossing_response_count"].eq(
            panel["accepted_response_count"]
            + panel["rejected_response_count"]
            + panel["equal_response_count"]
        )
        | panel["crossing_response_count"].isna(),
    }
    failures = {name: int((~value).sum()) for name, value in checks.items()}
    if any(failures.values()):
        raise ClosingDataError(f"closing-arm integer conservation failed: {failures}")
    panel["accepted_response_retention"] = (
        panel["accepted_response_count"] / panel["anchor_accepted_count"]
    )
    panel["rejected_response_retention"] = (
        panel["rejected_response_count"] / panel["anchor_rejected_count"]
    )
    accepted_floor = panel["market_view"].map(
        spec["support"]["minimum_accepted_response_count"]
    )
    rejected_floor = panel["market_view"].map(
        spec["support"]["minimum_rejected_response_count"]
    )
    panel["closing_topology_complete"] = (
        panel["topology_complete"].eq(True)
        & panel["accepted_response_retention"].ge(spec["support"]["minimum_arm_retention"])
        & panel["rejected_response_retention"].ge(spec["support"]["minimum_arm_retention"])
        & panel["accepted_response_count"].ge(accepted_floor)
        & panel["rejected_response_count"].ge(rejected_floor)
    )
    arm_metrics = [
        column
        for column in panel
        if column.startswith(("accepted_", "rejected_"))
        and column.endswith(("_sum", "_mean"))
    ]
    if not np.isfinite(
        panel.loc[panel["closing_topology_complete"], arm_metrics].to_numpy(dtype=float)
    ).all():
        raise ClosingDataError("nonfinite primary closing-arm metric")
    panel["event_year"] = panel["trade_date"].dt.year
    count = (
        panel.groupby(["market_view", "denominator", "event_year"], sort=True)
        .agg(
            date_cells=("trade_date", "size"),
            crossing_complete_cells=("topology_complete", "sum"),
            closing_complete_cells=("closing_topology_complete", "sum"),
            minimum_accepted_anchor=("anchor_accepted_count", "min"),
            minimum_rejected_anchor=("anchor_rejected_count", "min"),
            minimum_accepted_response=("accepted_response_count", "min"),
            minimum_rejected_response=("rejected_response_count", "min"),
            minimum_accepted_retention=("accepted_response_retention", "min"),
            minimum_rejected_retention=("rejected_response_retention", "min"),
        )
        .reset_index()
    )
    minimum_dates = int(count["closing_complete_cells"].min())
    validation = {
        "exact_anchor_and_response_conservation": True,
        "closing_topology_complete_cells": int(panel["closing_topology_complete"].sum()),
        "minimum_closing_complete_dates_per_cell_year": minimum_dates,
        "minimum_dates_gate": minimum_dates
        >= spec["support"]["minimum_complete_dates_per_view_denominator_year"],
        "minimum_accepted_retention_complete": float(
            panel.loc[panel["closing_topology_complete"], "accepted_response_retention"].min()
        ),
        "minimum_rejected_retention_complete": float(
            panel.loc[panel["closing_topology_complete"], "rejected_response_retention"].min()
        ),
    }
    if not validation["minimum_dates_gate"]:
        raise ClosingDataError(f"closing topology support failed: {validation}")
    return panel.sort_values(keys).reset_index(drop=True), count, validation


def _report(result: dict[str, Any]) -> str:
    validation = result["response_domain"]
    complete = validation["closing_topology_complete_cells"]
    minimum_dates = validation["minimum_closing_complete_dates_per_cell_year"]
    accepted_retention = validation["minimum_accepted_retention_complete"]
    rejected_retention = validation["minimum_rejected_retention_complete"]
    conservation = validation["exact_anchor_and_response_conservation"]
    scalar_cases = result["scalar_reconstruction"]["cases"]
    scalar_fields = result["scalar_reconstruction"]["fields"]
    return f"""# MKT-FORMDEPTH-CLOSE-DATA-001 closing-arm response audit

- Status: `{result['status']}`
- Closing-topology-complete cells: {complete:,}
- Minimum complete dates per view/denominator/year: {minimum_dates}
- Minimum accepted/rejected retention: {accepted_retention:.6f}/{rejected_retention:.6f}
- Exact anchor/response arm conservation: {conservation}
- Scalar cases/fields exact: {scalar_cases}/{scalar_fields}

This is response-domain adequacy only. No formation-depth/closing-arm association,
paired effect, favorable arm, reversal classification, strategy outcome, or rule
was computed. Post-2023 data and CY-011 were not read.
"""


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    base = _import(
        _resolve(spec["inputs"]["inherited_data_runner"]["path"]),
        "inherited_prop_data",
    )
    inherited = base._load_spec()
    economic_data = base._import(base.ECON_DATA_RUNNER, "accepted_economic_data_close")
    coordinate = economic_data._load_coordinate_module(inherited)
    source_paths, source_hashes = economic_data._verify_partitions(inherited, coordinate)
    base._preflight(inherited, source_paths)
    predictor, predictor_audit = base._audit_predictor(inherited)
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-close-data-") as temp_raw:
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
            economic_data._create_future_coordinate(connection)
            frames: list[pd.DataFrame] = []
            candidates: list[pd.DataFrame] = []
            for event_year in (2018, 2019, 2020, 2021, 2022, 2023):
                base._create_response_security(connection, event_year)
                frames.append(_closing_frames(connection, event_year))
                candidates.append(_scalar_candidates(connection))
                connection.execute("DROP TABLE response_security")
                base._guard(inherited, temp_dir, started)
        finally:
            connection.close()
        base._guard(inherited, temp_dir, started)
    panel, count, validation = _assemble(
        pd.concat(frames, ignore_index=True), predictor, spec
    )
    scalar = _scalar_audit(pd.concat(candidates, ignore_index=True), spec, base)
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    count.to_csv(COUNT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    scalar.to_csv(SCALAR_PATH, index=False, lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "status": "COMPLETE_CLOSING_ARM_RESPONSE_DOMAIN_ADEQUACY",
        "claim": spec["claim_boundary"],
        "outcome_access": spec["outcome_access"],
        "source_audit": source_audit,
        "predictor_audit": predictor_audit,
        "response_domain": validation,
        "population": {"panel_rows": len(panel), "count_audit_rows": len(count)},
        "scalar_reconstruction": {
            "cases": scalar["selection_hash"].nunique(),
            "cases_per_arm": scalar.groupby("closing_arm")["selection_hash"].nunique().to_dict(),
            "fields": scalar["field"].nunique(),
            "all_exact": bool(scalar["exact_match"].all()),
        },
        "source_partitions": source_hashes,
        "state_outcome_estimates_computed": False,
        "closing_classification_computed": False,
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
        raise ClosingDataError("durable output ceiling breached")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
