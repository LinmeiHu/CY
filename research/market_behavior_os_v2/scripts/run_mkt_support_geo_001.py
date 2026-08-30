#!/usr/bin/env python3
"""Test objective-support roles against fixed daily/minute alternatives."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-SUPPORT-GEO-001_spec.json"
SESSION_PATH = PROGRAM / "artifacts/MKT-SUPPORT-GEO-001_session_panel.csv"
TRAJECTORY_PATH = PROGRAM / "artifacts/MKT-SUPPORT-GEO-001_trajectory_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-SUPPORT-GEO-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-SUPPORT-GEO-001_geometry.md"
EXPECTED_SPEC_SHA256 = "c828ed0e73a652ff6979067712fbd293e43f553e4dd3683e358db06504552ba1"


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


support001 = _load_module(
    "run_mkt_support_001_parent", PROGRAM / "scripts/run_mkt_support_001.py"
)
data003 = _load_module(
    "run_mkt_support_data_003_parent_geo", PROGRAM / "scripts/run_mkt_support_data_003.py"
)
adapter = support001.adapter
sha256_file = support001.sha256_file


class SupportGeometryError(RuntimeError):
    """Fail-closed MKT-SUPPORT-GEO-001 error."""


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


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
        raise SupportGeometryError("MKT-SUPPORT-GEO-001 spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_CONTROL_CONSTRUCTION" or spec["outcome_access"] is not False:
        raise SupportGeometryError("external geometry is not frozen outcome-blind")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise SupportGeometryError(f"input identity mismatch: {name}")
    support_result = json.loads(
        _resolve(spec["inputs"]["support_result"]["path"]).read_text(encoding="utf-8")
    )
    if (
        support_result["status"] != "COMPLETE_REPRESENTATIONS_FROZEN"
        or support_result["accepted_session_roles"]
        != [
            "signed_test_geometry",
            "recovery_speed",
            "recovery_amplitude",
            "recovery_volume_intensity",
        ]
        or support_result["accepted_trajectory_roles"]
        != ["signed_test_geometry", "closing_level_state"]
        or support_result["cy011_read"] is not False
    ):
        raise SupportGeometryError("support representation activation changed")
    return spec


def _inventory_paths(
    inventory: Path, required: list[str], verify_content: bool
) -> dict[str, Path]:
    try:
        paths = adapter.inventory_files(inventory, required)
        if verify_content:
            adapter.verify_inventory_hashes(inventory, required)
        return paths
    except adapter.VectorMinuteAdapterError as exc:
        raise SupportGeometryError(str(exc)) from exc


def _rank_pct(series: pd.Series) -> pd.Series:
    valid = series.notna()
    output = pd.Series(np.nan, index=series.index, dtype=float)
    n = int(valid.sum())
    if n:
        output.loc[valid] = (series.loc[valid].rank(method="average") - 0.5) / n
    return output


def _spearman(left: Iterable[float], right: Iterable[float]) -> float:
    frame = pd.DataFrame({"left": left, "right": right}).dropna()
    if len(frame) < 3 or frame["left"].nunique() < 2 or frame["right"].nunique() < 2:
        return np.nan
    return float(frame["left"].rank(method="average").corr(frame["right"].rank(method="average")))


def _adjusted_rank_r2(frame: pd.DataFrame, target: str, controls: list[str]) -> float:
    complete = frame[[target, *controls]].dropna()
    n = len(complete)
    p = len(controls)
    if n <= p + 1 or complete[target].nunique() < 2:
        return np.nan
    ranked = complete.rank(method="average").to_numpy(dtype=float)
    y = ranked[:, 0]
    x = np.column_stack([np.ones(n), ranked[:, 1:]])
    if np.linalg.matrix_rank(x) < p + 1:
        return np.nan
    fitted = x @ np.linalg.lstsq(x, y, rcond=None)[0]
    total = float(np.sum((y - y.mean()) ** 2))
    if total <= 0:
        return np.nan
    r2 = 1.0 - float(np.sum((y - fitted) ** 2)) / total
    return float(1.0 - (1.0 - r2) * (n - 1) / (n - p - 1))


def _minute_controls(rows: pd.DataFrame) -> dict[str, float]:
    continuous = rows.iloc[1:].reset_index(drop=True)
    if len(continuous) != 240:
        raise SupportGeometryError("continuous path length changed")
    open_ = continuous["open"].to_numpy(dtype=float)
    high = continuous["high"].to_numpy(dtype=float)
    low = continuous["low"].to_numpy(dtype=float)
    close = continuous["close"].to_numpy(dtype=float)
    volume = continuous["volume"].to_numpy(dtype=float)
    if (
        not np.isfinite(np.column_stack([open_, high, low, close, volume])).all()
        or not (open_ > 0).all()
        or not (high > 0).all()
        or not (low > 0).all()
        or not (close > 0).all()
        or (volume < 0).any()
        or float(volume.sum()) <= 0
    ):
        raise SupportGeometryError("invalid generic minute control input")
    minimum = float(low.min())
    maximum = float(high.max())
    width = maximum - minimum
    shares = volume / volume.sum()
    return {
        "minute_open_to_close_return": float(close[-1] / open_[0] - 1.0),
        "minute_intraday_range": float(width / open_[0]),
        "minute_close_location": float((close[-1] - minimum) / width) if width > 0 else np.nan,
        "minute_time_of_low": float(int(np.argmin(low)) / 239.0),
        "minute_realized_volatility": float(
            np.sqrt(np.sum(np.diff(np.log(close)) ** 2))
        ),
        "minute_volume_herfindahl": float(np.sum(shares**2)),
        "minute_opening30_volume_share": float(volume[:30].sum() / volume.sum()),
        "minute_closing30_volume_share": float(volume[-30:].sum() / volume.sum()),
    }


def _load_base_panels(spec: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame]:
    session = pd.read_csv(_resolve(spec["inputs"]["session_panel"]["path"]))
    trajectory = pd.read_csv(_resolve(spec["inputs"]["trajectory_panel"]["path"]))
    session["trade_date"] = pd.to_datetime(session["trade_date"], errors="raise")
    market = session.loc[session["cohort"].eq("COORDINATE_ELIGIBLE_MARKET_SEQUENCE")].copy()
    if len(market) != 1200 or len(trajectory) != 240:
        raise SupportGeometryError("support panel population changed")
    if not market["audit_id"].is_unique or not trajectory["sequence_id"].is_unique:
        raise SupportGeometryError("support panel key changed")
    return market, trajectory


def construct_controls(
    spec: dict[str, Any], verify_partition_content: bool
) -> tuple[pd.DataFrame, pd.DataFrame]:
    session, trajectory = _load_base_panels(spec)
    years = [2018, 2019, 2020, 2021, 2022, 2023]
    qd_required = [f"bars/{year}_day_parquet_none.parquet" for year in years]
    cy_required = [f"partition_year={year}/data_0.parquet" for year in years]
    qd_paths = _inventory_paths(
        _resolve(spec["inputs"]["qd004_inventory"]["path"]),
        qd_required,
        verify_partition_content,
    )
    cy_paths = _inventory_paths(
        _resolve(spec["inputs"]["cy006_inventory"]["path"]),
        cy_required,
        verify_partition_content,
    )

    data_spec = data003._load_spec()
    data003.parent.parent._verify_registry_assets(data_spec)
    connection = data003.parent.parent._create_daily_coordinate(data_spec, cy_paths)
    try:
        keys = session[["symbol", "trade_date"]].drop_duplicates()
        connection.register("geometry_keys", keys)
        daily = connection.execute(
            """
            SELECT c.trade_date,c.symbol,c.coordinate_eligible,c.open,c.high,c.low,c.close,
                   c.coordinate_close,c.coordinate_low,c.support_low20
            FROM geometry_keys k JOIN coordinate c USING(symbol,trade_date)
            ORDER BY c.trade_date,c.symbol
            """
        ).df()
    finally:
        connection.close()
    if len(daily) != session[["symbol", "trade_date"]].drop_duplicates().shape[0]:
        raise SupportGeometryError("daily control coverage mismatch")
    if not daily["coordinate_eligible"].astype(bool).all():
        raise SupportGeometryError("daily control coordinate ineligible")
    daily["trade_date"] = pd.to_datetime(daily["trade_date"], errors="raise")
    for column in ["open", "high", "low", "close", "coordinate_close", "coordinate_low", "support_low20"]:
        values = pd.to_numeric(daily[column], errors="coerce")
        if not (np.isfinite(values) & (values > 0)).all():
            raise SupportGeometryError(f"daily control invalid: {column}")
    daily["daily_low_level_distance"] = daily["coordinate_low"] / daily["support_low20"] - 1.0
    daily["daily_close_level_distance"] = daily["coordinate_close"] / daily["support_low20"] - 1.0
    daily["daily_range"] = (daily["high"] - daily["low"]) / daily["close"]
    daily_controls = daily[
        ["symbol", "trade_date", "daily_low_level_distance", "daily_close_level_distance", "daily_range"]
    ]

    unique = session[["symbol", "source_symbol", "trade_date", "target_year"]].drop_duplicates()
    minute_records: list[dict[str, Any]] = []
    for raw_year, targets in unique.groupby("target_year", sort=True):
        year = int(raw_year)
        try:
            table = adapter.read_raw_table(
                qd_paths[f"bars/{year}_day_parquet_none.parquet"],
                pd.to_datetime(targets["trade_date"]).dt.date,
                targets["source_symbol"].astype(str).str.zfill(6),
            )
            adapter.vectorized_session_descriptors(table)
        except adapter.VectorMinuteAdapterError as exc:
            raise SupportGeometryError(str(exc)) from exc
        raw = table.to_pandas()
        raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="raise")
        raw["symbol"] = raw["symbol"].astype(str).str.zfill(6) + "." + raw["exchange"].astype(str)
        raw = raw.merge(
            targets[["symbol", "trade_date"]].drop_duplicates(),
            on=["symbol", "trade_date"],
            validate="many_to_one",
        )
        for (symbol, trade_date), rows in raw.groupby(["symbol", "trade_date"], sort=True):
            rows = rows.sort_values("bar_end_time").reset_index(drop=True)
            controls = _minute_controls(rows)
            minute_records.append({"symbol": symbol, "trade_date": pd.Timestamp(trade_date), **controls})
    minute = pd.DataFrame(minute_records)
    if len(minute) != len(unique):
        raise SupportGeometryError("minute control coverage mismatch")

    panel = session.merge(daily_controls, on=["symbol", "trade_date"], validate="many_to_one")
    panel = panel.merge(minute, on=["symbol", "trade_date"], validate="many_to_one")
    if len(panel) != 1200:
        raise SupportGeometryError("session geometry merge changed population")
    session_control_columns = sorted(
        set(
            control
            for role in spec["roles"].values()
            if role["domain"] != "all_market_sequences"
            for control in role["controls"]
        )
    )
    target_columns = [
        role["target"]
        for role in spec["roles"].values()
        if role["domain"] != "all_market_sequences"
    ]
    for column in [*session_control_columns, *target_columns]:
        panel[f"relative_rank__{column}"] = panel.groupby(
            ["target_year", "market_view", "trade_date"], sort=False
        )[column].transform(_rank_pct)

    sequence_fields = ["target_year", "market_view", "market_sequence_rank", "symbol"]
    trajectory_controls: list[dict[str, Any]] = []
    for key, rows in panel.groupby(sequence_fields, sort=True):
        rows = rows.sort_values("relative_day")
        if len(rows) != 5 or rows["relative_day"].tolist() != [-5, -4, -3, -2, -1]:
            raise SupportGeometryError(f"geometry sequence changed: {key}")
        record = dict(zip(sequence_fields, key, strict=True))
        record["sequence_id"] = "|".join(str(value) for value in key)
        for column in [
            "daily_low_level_distance",
            "daily_close_level_distance",
            "minute_intraday_range",
            "minute_open_to_close_return",
        ]:
            slope, _, _ = support001._trajectory_values(rows[column].to_numpy(dtype=float))
            record[f"{column}__slope5"] = slope
        trajectory_controls.append(record)
    control_panel = pd.DataFrame(trajectory_controls)
    trajectory_panel = trajectory.merge(
        control_panel, on=sequence_fields + ["sequence_id"], validate="one_to_one"
    )
    if len(trajectory_panel) != 240:
        raise SupportGeometryError("trajectory geometry merge changed population")
    trajectory_control_columns = sorted(
        set(
            control
            for role in spec["roles"].values()
            if role["domain"] == "all_market_sequences"
            for control in role["controls"]
        )
    )
    trajectory_targets = [
        role["target"]
        for role in spec["roles"].values()
        if role["domain"] == "all_market_sequences"
    ]
    for column in [*trajectory_control_columns, *trajectory_targets]:
        trajectory_panel[f"relative_rank__{column}"] = trajectory_panel.groupby(
            ["target_year", "market_view"], sort=False
        )[column].transform(_rank_pct)
    return panel.sort_values("audit_id").reset_index(drop=True), trajectory_panel.sort_values(
        "sequence_id"
    ).reset_index(drop=True)


def _evaluate_unconditional(
    frame: pd.DataFrame,
    target: str,
    controls: list[str],
    coordinate: str,
    cell_fields: list[str],
    expected_cell_rows: int,
    gates: dict[str, Any],
) -> dict[str, Any]:
    if coordinate == "relative_rank":
        used_target = f"relative_rank__{target}"
        used_controls = [f"relative_rank__{control}" for control in controls]
    else:
        used_target = target
        used_controls = controls
    required = [used_target, *used_controls]
    if frame[required].isna().any().any():
        raise SupportGeometryError(f"unconditional field missing: {target}:{coordinate}")
    pairwise: dict[str, Any] = {}
    pair_pass = True
    for raw_control, control in zip(controls, used_controls, strict=True):
        global_rho = _spearman(frame[used_target], frame[control])
        cells = []
        for _, cell in frame.groupby(cell_fields, sort=True):
            if len(cell) != expected_cell_rows:
                raise SupportGeometryError(f"unconditional cell support changed: {target}")
            rho = _spearman(cell[used_target], cell[control])
            if not np.isfinite(rho):
                raise SupportGeometryError(f"unconditional cell degeneracy: {target}:{raw_control}")
            cells.append(abs(rho))
        median_abs = float(np.median(cells))
        passed = (
            abs(global_rho) < gates["pairwise_absolute_spearman_strictly_below"]
            and median_abs
            < gates["unconditional_pairwise_median_cell_absolute_spearman_strictly_below"]
        )
        pair_pass = pair_pass and passed
        pairwise[raw_control] = {
            "global_spearman": global_rho,
            "median_cell_absolute_spearman": median_abs,
            "pass": passed,
        }
    full_r2 = _adjusted_rank_r2(frame, used_target, used_controls)
    cell_r2 = []
    for _, cell in frame.groupby(cell_fields, sort=True):
        value = _adjusted_rank_r2(cell, used_target, used_controls)
        if not np.isfinite(value):
            raise SupportGeometryError(f"unconditional joint cell degeneracy: {target}")
        cell_r2.append(value)
    max_cell = float(max(cell_r2))
    joint_pass = (
        full_r2 < gates["joint_adjusted_rank_r2_full_strictly_below"]
        and max_cell < gates["joint_adjusted_rank_r2_max_cell_or_block_strictly_below"]
    )
    return {
        "rows": len(frame),
        "coordinate": coordinate,
        "pairwise": pairwise,
        "joint_adjusted_rank_r2_full": full_r2,
        "joint_adjusted_rank_r2_max_cell": max_cell,
        "pairwise_pass": pair_pass,
        "joint_pass": joint_pass,
        "pass": bool(pair_pass and joint_pass),
    }


def _evaluate_conditional(
    frame: pd.DataFrame,
    target: str,
    controls: list[str],
    spec: dict[str, Any],
) -> dict[str, Any]:
    complete = frame[["target_year", target, *controls]].dropna().copy()
    blocks = spec["support_gates"]["conditional_blocks"]
    gates = spec["distinctness_gates"]
    block_frames = {
        name: complete.loc[complete["target_year"].isin(years)] for name, years in blocks.items()
    }
    for name, block in block_frames.items():
        if len(block) < spec["support_gates"]["conditional_block_minimum_rows"]:
            raise SupportGeometryError(f"conditional block support failed: {target}:{name}:{len(block)}")
        for column in [target, *controls]:
            if block[column].nunique() < 2:
                raise SupportGeometryError(f"conditional block degeneracy: {target}:{name}:{column}")
    pairwise: dict[str, Any] = {}
    pair_pass = True
    for control in controls:
        values = {"full": _spearman(complete[target], complete[control])}
        values.update(
            {
                name: _spearman(block[target], block[control])
                for name, block in block_frames.items()
            }
        )
        passed = all(
            np.isfinite(value)
            and abs(value) < gates["pairwise_absolute_spearman_strictly_below"]
            for value in values.values()
        )
        pair_pass = pair_pass and passed
        pairwise[control] = {**values, "pass": passed}
    full_r2 = _adjusted_rank_r2(complete, target, controls)
    block_r2 = {
        name: _adjusted_rank_r2(block, target, controls) for name, block in block_frames.items()
    }
    joint_pass = (
        np.isfinite(full_r2)
        and full_r2 < gates["joint_adjusted_rank_r2_full_strictly_below"]
        and all(
            np.isfinite(value)
            and value < gates["joint_adjusted_rank_r2_max_cell_or_block_strictly_below"]
            for value in block_r2.values()
        )
    )
    return {
        "rows": len(complete),
        "block_rows": {name: len(block) for name, block in block_frames.items()},
        "coordinate": "raw",
        "pairwise": pairwise,
        "joint_adjusted_rank_r2_full": full_r2,
        "joint_adjusted_rank_r2_blocks": block_r2,
        "pairwise_pass": pair_pass,
        "joint_pass": joint_pass,
        "pass": bool(pair_pass and joint_pass),
    }


def evaluate_roles(
    spec: dict[str, Any], session: pd.DataFrame, trajectory: pd.DataFrame
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    gates = spec["distinctness_gates"]
    for role_name, role in spec["roles"].items():
        domain = role["domain"]
        target = role["target"]
        controls = role["controls"]
        coordinates: dict[str, Any] = {}
        if domain == "all_market_sessions":
            for coordinate in role["coordinates"]:
                coordinates[coordinate] = _evaluate_unconditional(
                    session,
                    target,
                    controls,
                    coordinate,
                    ["target_year", "market_view"],
                    spec["support_gates"]["unconditional_year_view_cell_rows"],
                    gates,
                )
        elif domain == "all_market_sequences":
            for coordinate in role["coordinates"]:
                coordinates[coordinate] = _evaluate_unconditional(
                    trajectory,
                    target,
                    controls,
                    coordinate,
                    ["target_year", "market_view"],
                    spec["support_gates"]["trajectory_year_view_cell_rows"],
                    gates,
                )
        else:
            coordinates["raw"] = _evaluate_conditional(session, target, controls, spec)
        output[role_name] = {
            "domain": domain,
            "target": target,
            "controls": controls,
            "coordinates": coordinates,
            "pass": all(detail["pass"] for detail in coordinates.values()),
        }
    return output


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-SUPPORT-GEO-001 external geometry",
        "",
        "## Result",
        "",
        f"- Status: `{result['status']}`",
        f"- Direct support-specific coordinates: {', '.join(result['direct_roles']) or 'none'}.",
        "- Daily/minute source roles remain distinct; no close substitution or sparse conditional rank was used.",
        "- This is external representation geometry only, not support defense, temporal recurrence, prediction, payoff, habitat, timing, or strategy evidence.",
        "",
        "| Role | Domain | Result |",
        "|---|---|---|",
    ]
    for role, detail in result["roles"].items():
        lines.append(f"| `{role}` | `{detail['domain']}` | {'PASS' if detail['pass'] else 'REDUNDANT'} |")
    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
            f"- Session panel SHA-256: `{result['hashes']['session_panel_sha256']}`",
            f"- Trajectory panel SHA-256: `{result['hashes']['trajectory_panel_sha256']}`",
        ]
    )
    return "\n".join(lines) + "\n"


def run(*, verify_partition_content: bool = True) -> dict[str, Any]:
    spec = _load_spec()
    session, trajectory = construct_controls(spec, verify_partition_content)
    roles = evaluate_roles(spec, session, trajectory)
    direct = [name for name, detail in roles.items() if detail["pass"]]

    session_out = session.copy()
    session_out["trade_date"] = pd.to_datetime(session_out["trade_date"]).dt.strftime("%Y-%m-%d")
    session_out.to_csv(SESSION_PATH, index=False, float_format="%.17g", lineterminator="\n")
    trajectory.to_csv(TRAJECTORY_PATH, index=False, float_format="%.17g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": "MKT-SUPPORT-GEO-001",
        "status": "COMPLETE_EXTERNAL_GEOMETRY",
        "direct_roles": direct,
        "roles": roles,
        "external_distinctness_claim": "FIXED_CONTROL_GEOMETRY_ONLY",
        "support_defense_claim": "NONE",
        "temporal_claim": "NONE",
        "usefulness_claim": "NONE",
        "pit_historical_coordinate": "UNAVAILABLE_NOT_FABRICATED",
        "future_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "partition_content_hashes_verified": verify_partition_content,
        "sample_counts": {
            "session_rows": len(session),
            "trajectory_rows": len(trajectory),
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "session_panel_sha256": sha256_file(SESSION_PATH),
            "trajectory_panel_sha256": sha256_file(TRAJECTORY_PATH),
            "bound_inputs": {
                name: binding["sha256"] for name, binding in spec["inputs"].items()
            },
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
    print(
        json.dumps(
            {"status": completed["status"], "direct_roles": completed["direct_roles"]},
            indent=2,
            sort_keys=True,
        )
    )
