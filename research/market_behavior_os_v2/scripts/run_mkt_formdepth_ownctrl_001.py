#!/usr/bin/env python3
"""Test objective-specific own overshoot beyond fixed same-day security geometry."""

from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import resource
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
SPEC_PATH = PROGRAM / "experiments/MKT-FORMDEPTH-OWNCTRL-001_spec.json"
AUDIT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWNCTRL-001_date_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-FORMDEPTH-OWNCTRL-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-FORMDEPTH-OWNCTRL-001_specificity.md"
EXPECTED_SPEC_SHA256 = "b2254dee1169c044f16ff2b977e53fd7ef3135b7b083a407aad2f61ead7406f3"


class OwnControlError(RuntimeError):
    """Fail-closed objective-specificity error."""


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
        raise OwnControlError(f"cannot load bound module: {path}")
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
        raise OwnControlError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"]
        != "FROZEN_BEFORE_SECURITY_LEVEL_OBJECTIVE_SPECIFICITY_ESTIMATES"
        or spec["research_level"] != "PROMOTE"
        or spec["outcome_access"]
        != "EXISTING_PRE2024_EXACT_CROSSER_H1_H3_H5_ADVERSE_RESPONSE_ONLY"
    ):
        raise OwnControlError("activation boundary changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise OwnControlError(f"input identity mismatch: {name}")
    own_result = json.loads(
        _resolve(spec["inputs"]["accepted_own_result"]["path"]).read_text()
    )
    data_result = json.loads(
        _resolve(spec["inputs"]["accepted_data_result"]["path"]).read_text()
    )
    if own_result["classification"] != spec["activation"]["required_own_classification"]:
        raise OwnControlError("accepted own-channel activation changed")
    if data_result["status"] != spec["activation"]["required_data_status"]:
        raise OwnControlError("accepted response-domain activation changed")
    forbidden = "|".join(spec["prohibited_computations"])
    for token in ("terminal return", "minute data", "strategy outcome", "CY-011"):
        if token not in forbidden:
            raise OwnControlError(f"prohibited boundary missing: {token}")
    return spec


def _peak_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)


def _guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise OwnControlError("process peak RSS ceiling breached")
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise OwnControlError("system memory headroom below frozen floor")
    if time.monotonic() - started > budget["wall_clock_ceiling_minutes"] * 60:
        raise OwnControlError("wall-clock ceiling breached")


def _rank(frame: pd.DataFrame) -> np.ndarray:
    return frame.rank(method="average").to_numpy(dtype=float)


def _residual(values: np.ndarray, controls: np.ndarray) -> np.ndarray:
    design = np.column_stack([np.ones(len(values)), controls])
    coefficients = np.linalg.lstsq(design, values, rcond=None)[0]
    return values - design @ coefficients


def _corr(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])


def _date_statistics(group: pd.DataFrame, horizon: int) -> dict[str, Any]:
    target = "own_depth"
    response = f"adverse_log_excursion_h{horizon}"
    controls = [
        "action_coordinate_close_return",
        "intraday_log_range",
        "close_location",
        "turnover_fraction",
        "log_traded_value",
    ]
    ranked = _rank(group[[target, response, *controls]])
    target_rank = ranked[:, 0]
    response_rank = ranked[:, 1]
    control_ranks = ranked[:, 2:]
    target_residual = _residual(target_rank, control_ranks)
    response_residual = _residual(response_rank, control_ranks)
    raw_rho = _corr(target_rank, response_rank)
    partial_rho = _corr(target_residual, response_residual)
    total = float(np.sum((target_rank - target_rank.mean()) ** 2))
    target_r2 = (
        float(1 - np.sum(target_residual**2) / total) if total > 0 else float("nan")
    )
    target_pct = (pd.Series(target_rank).rank(method="average").to_numpy() - 0.5) / len(
        group
    )
    raw_response_residual = _residual(
        group[response].to_numpy(dtype=float), control_ranks
    )
    low = raw_response_residual[target_pct <= 0.20]
    high = raw_response_residual[target_pct >= 0.80]
    gap = float(np.mean(high) - np.mean(low)) if len(low) and len(high) else float("nan")
    return {
        "raw_rho": raw_rho,
        "partial_rho": partial_rho,
        "target_rank_r2": target_r2,
        "low_n": len(low),
        "high_n": len(high),
        "controlled_tail_gap": gap,
    }


def _security_frame(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    return connection.execute(
        """
        SELECT a.trade_date,a.market_view,a.denominator,a.symbol,
               a.anchor_crossing_count,e.cal_idx,a.own_depth,
               ln(e.coordinate_close/p.coordinate_close)
                 AS action_coordinate_close_return,
               ln(s.high/s.low) AS intraday_log_range,
               (s.close-s.low)/(s.high-s.low) AS close_location,
               s.turnover_fraction,ln(s.amount) AS log_traded_value,
               r.adverse_log_excursion_h1,r.adverse_log_excursion_h3,
               r.adverse_log_excursion_h5
        FROM anchor_strata a
        JOIN response_security r USING(symbol,trade_date)
        JOIN event_security e USING(symbol,trade_date)
        JOIN event_security p ON p.symbol=e.symbol AND p.cal_idx=e.cal_idx-1
        JOIN source s USING(symbol,trade_date)
        WHERE s.high>s.low AND s.low>0 AND isfinite(s.high) AND isfinite(s.low)
          AND s.close>=s.low AND s.close<=s.high
          AND s.turnover_fraction>0 AND isfinite(s.turnover_fraction)
          AND s.amount>0 AND isfinite(s.amount)
          AND e.coordinate_close>0 AND p.coordinate_close>0
          AND isfinite(e.coordinate_close) AND isfinite(p.coordinate_close)
        ORDER BY a.trade_date,a.denominator,a.market_view,a.symbol
        """
    ).fetchdf()


def _build_date_audit(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    started = time.monotonic()
    data_runner = _import(
        _resolve(spec["inputs"]["accepted_data_runner"]["path"]),
        "ownctrl_accepted_data_runner",
    )
    data_spec = data_runner._load_spec()
    path_runner = data_runner._import(
        data_runner._resolve(data_spec["inputs"]["inherited_path_data_runner"]["path"]),
        "ownctrl_path_runner",
    )
    path_spec = path_runner._load_spec()
    base = path_runner._import(
        data_runner._resolve(path_spec["inputs"]["inherited_data_runner"]["path"]),
        "ownctrl_base_data",
    )
    inherited = base._load_spec()
    economic_data = base._import(base.ECON_DATA_RUNNER, "ownctrl_economic_data")
    coordinate = economic_data._load_coordinate_module(inherited)
    source_paths, source_hashes = economic_data._verify_partitions(inherited, coordinate)
    base._preflight(inherited, source_paths)
    audit_frames: list[pd.DataFrame] = []
    security_rows = 0
    numeric = [
        "own_depth",
        "action_coordinate_close_return",
        "intraday_log_range",
        "close_location",
        "turnover_fraction",
        "log_traded_value",
        "adverse_log_excursion_h1",
        "adverse_log_excursion_h3",
        "adverse_log_excursion_h5",
    ]
    with tempfile.TemporaryDirectory(prefix="mkt-formdepth-ownctrl-") as temp_raw:
        connection = duckdb.connect()
        connection.execute("SET threads=1")
        connection.execute("SET memory_limit='1536MB'")
        connection.execute("SET preserve_insertion_order=false")
        escaped = str(Path(temp_raw)).replace("'", "''")
        connection.execute(f"SET temp_directory='{escaped}'")
        try:
            source_audit = coordinate._create_source_and_audit(
                connection, source_paths, inherited
            )
            coordinate._create_event_security(
                economic_data._PreserveCoordinateWindow(connection)
            )
            path_runner._create_future_coordinate(connection)
            for event_year in spec["years"]:
                data_runner._create_anchor_strata(
                    connection,
                    event_year,
                    spec["activation"]["minimum_anchor_crossers_each_date_cell"],
                )
                path_runner._create_response_security(connection, event_year)
                frame = _security_frame(connection)
                if not np.isfinite(frame[numeric].to_numpy(float)).all():
                    raise OwnControlError(
                        "security analysis frame contains nonfinite values"
                    )
                if frame[
                    ["trade_date", "market_view", "denominator", "symbol"]
                ].duplicated().any():
                    raise OwnControlError("security analysis key is not unique")
                security_rows += len(frame)
                audit_frames.append(_date_audit(frame, spec))
                connection.execute("DROP TABLE response_security")
                del frame
                gc.collect()
                _guard(spec, started)
        finally:
            connection.close()
    _guard(spec, started)
    support = {
        "security_rows": security_rows,
        "source_audit": source_audit,
        "source_partitions": source_hashes,
        "peak_rss_bytes": _peak_rss_bytes(),
        "elapsed_seconds": time.monotonic() - started,
    }
    return pd.concat(audit_frames, ignore_index=True), support


def _date_audit(frame: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    keys = ["trade_date", "market_view", "denominator"]
    rows: list[dict[str, Any]] = []
    minimum_n = spec["activation"]["minimum_complete_security_rows_each_date_cell"]
    minimum_retention = spec["activation"][
        "minimum_complete_security_retention_each_date_cell"
    ]
    for key, group in frame.groupby(keys, sort=True):
        anchor_count = int(group["anchor_crossing_count"].iloc[0])
        n = len(group)
        retention = n / anchor_count
        supported = n >= minimum_n and retention >= minimum_retention
        for horizon in (1, 3, 5):
            stats = (
                _date_statistics(group, horizon)
                if supported
                else {
                    "raw_rho": np.nan,
                    "partial_rho": np.nan,
                    "target_rank_r2": np.nan,
                    "low_n": 0,
                    "high_n": 0,
                    "controlled_tail_gap": np.nan,
                }
            )
            rows.append(
                {
                    "trade_date": key[0],
                    "market_view": key[1],
                    "denominator": key[2],
                    "event_year": pd.Timestamp(key[0]).year,
                    "cal_idx": int(group["cal_idx"].iloc[0]),
                    "horizon": horizon,
                    "anchor_count": anchor_count,
                    "analysis_count": n,
                    "retention": retention,
                    "supported": supported,
                    **stats,
                }
            )
    return pd.DataFrame(rows).sort_values(
        ["trade_date", "denominator", "market_view", "horizon"]
    ).reset_index(drop=True)


def _median(values: Any) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _evaluate(audit: pd.DataFrame, spec: dict[str, Any]) -> tuple[dict[str, Any], str]:
    supported = audit[audit["supported"] & audit["partial_rho"].notna()].copy()
    primary = supported[supported["horizon"].eq(3)]
    cell_year = primary.groupby(
        ["market_view", "denominator", "event_year"], sort=True
    ).size()
    support_pass = (
        len(cell_year) == spec["activation"]["cells"] * len(spec["years"])
        and int(cell_year.min())
        >= spec["activation"]["minimum_supported_dates_each_cell_year"]
    )
    cell_medians = primary.groupby(["market_view", "denominator"], sort=True)[
        "partial_rho"
    ].median()
    block_medians = {
        block: _median(primary.loc[primary["event_year"].isin(years), "partial_rho"])
        for block, years in spec["blocks"].items()
    }
    year_medians = {
        str(year): _median(primary.loc[primary["event_year"].eq(year), "partial_rho"])
        for year in spec["years"]
    }
    loo_medians = {
        str(year): _median(
            primary.loc[primary["event_year"].ne(year), "partial_rho"]
        )
        for year in spec["years"]
    }
    neighbor_medians = {
        str(horizon): _median(
            supported.loc[supported["horizon"].eq(horizon), "partial_rho"]
        )
        for horizon in (1, 5)
    }
    phase_signs = {
        str(horizon): [
            int(
                np.sign(
                    _median(
                        supported.loc[
                            supported["horizon"].eq(horizon)
                            & supported["cal_idx"].mod(horizon).eq(phase),
                            "partial_rho",
                        ]
                    )
                )
            )
            for phase in range(horizon)
        ]
        for horizon in (3, 5)
    }
    median_h3 = _median(primary["partial_rho"])
    tail_gap = _median(primary["controlled_tail_gap"])
    gate = spec["gates"]
    checks = {
        "support": support_pass,
        "primary": median_h3 <= gate["maximum_median_h3_within_date_partial_rho"],
        "cells": int((cell_medians < 0).sum()) >= gate["minimum_negative_cell_medians"],
        "blocks": all(
            value <= gate["maximum_each_block_median_h3_partial_rho"]
            for value in block_medians.values()
        ),
        "years": all(value < 0 for value in year_medians.values()),
        "leave_one_year_out": all(value < 0 for value in loo_medians.values()),
        "neighbors": all(value < 0 for value in neighbor_medians.values()),
        "h3_phases": sum(value < 0 for value in phase_signs["3"])
        >= gate["minimum_negative_h3_phases"],
        "h5_phases": sum(value < 0 for value in phase_signs["5"])
        >= gate["minimum_negative_h5_phases"],
        "controlled_tail_gap": tail_gap
        <= gate["maximum_median_h3_controlled_tail_gap"],
    }
    if not support_pass:
        classification = spec["classification"]["support_fail"]
    elif all(checks.values()):
        classification = spec["classification"]["pass"]
    else:
        classification = spec["classification"]["fail"]
    evaluation = {
        "pass": all(checks.values()),
        "checks": checks,
        "supported_h3_date_cells": len(primary),
        "minimum_supported_dates_each_cell_year": int(cell_year.min()),
        "minimum_retention": float(primary["retention"].min()),
        "median_h3_raw_rho": _median(primary["raw_rho"]),
        "median_h3_partial_rho": median_h3,
        "median_h3_target_rank_r2_from_controls": _median(primary["target_rank_r2"]),
        "negative_cell_medians": int((cell_medians < 0).sum()),
        "cell_median_h3_partial_rho": {
            f"{view}:{denominator}": float(value)
            for (view, denominator), value in cell_medians.items()
        },
        "block_median_h3_partial_rho": block_medians,
        "year_median_h3_partial_rho": year_medians,
        "leave_one_year_out_median_h3_partial_rho": loo_medians,
        "neighbor_median_partial_rho": neighbor_medians,
        "phase_signs": phase_signs,
        "median_h3_controlled_tail_gap": tail_gap,
    }
    return evaluation, classification


def _report(result: dict[str, Any]) -> str:
    item = result["evaluation"]
    checks = "\n".join(
        f"- `{name}`: {'PASS' if passed else 'FAIL'}"
        for name, passed in item["checks"].items()
    )
    return f"""# MKT-FORMDEPTH-OWNCTRL-001 objective specificity

## Decision

`{result['classification']}`

- Median h3 raw within-date rho: {item['median_h3_raw_rho']:.6f}
- Median h3 partial rho after five fixed t-day controls: {item['median_h3_partial_rho']:.6f}
- Median target rank R2 from controls: {item['median_h3_target_rank_r2_from_controls']:.6f}
- Median controlled h3 top-minus-bottom depth-tail gap: {item['median_h3_controlled_tail_gap']:.6f}
- Negative cell medians: {item['negative_cell_medians']}/8

{checks}

The controls are action-coordinate close return, intraday range, close location,
turnover fraction, and log traded-value scale. Traded value is not claimed to be
true liquidity. This is pre-2024 within-date association specificity only—not
causal supply, prediction, execution, payoff, habitat, or strategy.
"""


def main() -> None:
    spec = _load_spec()
    audit, construction = _build_date_audit(spec)
    evaluation, classification = _evaluate(audit, spec)
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    audit.to_csv(AUDIT_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result = {
        "experiment_id": spec["experiment_id"],
        "research_level": spec["research_level"],
        "classification": classification,
        "claim": spec["claim_boundary"],
        "construction": construction,
        "evaluation": evaluation,
        "security_level_durable_output": False,
        "future_response_used_as_predictor": False,
        "terminal_return_read": False,
        "minute_data_read": False,
        "strategy_fields_read": False,
        "post_2023_read": False,
        "cy011_read": False,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "runner_sha256": sha256_file(Path(__file__)),
            "date_audit_sha256": sha256_file(AUDIT_PATH),
        },
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_report(result), encoding="utf-8")
    print(json.dumps(_clean(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
