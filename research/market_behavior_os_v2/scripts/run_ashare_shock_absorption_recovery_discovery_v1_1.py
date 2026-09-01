#!/usr/bin/env python3
"""Run frozen A-share Shock Absorption / Recovery Discovery V1.1."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1-1_spec.json"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1-1_result.json"
SURFACE_PATH = PROGRAM / "artifacts/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1-1_surface.csv"
REPORT_PATH = PROGRAM / "reports/ASHARE-SHOCK-ABSORPTION-RECOVERY-DISCOVERY-V1-1_report.md"
EXTERNAL_ROOT = Path("/Volumes/quant/CY_quant_research/shock_absorption_recovery_discovery_v1_1")
PANEL_PATH = EXTERNAL_ROOT / "evaluation_panel.parquet"
TEMP_PATH = EXTERNAL_ROOT / "duckdb_tmp"
V1_PATH = PROGRAM / "scripts/run_ashare_shock_absorption_recovery_discovery_v1.py"
EXPECTED_SPEC_SHA256 = "b6318619dcf9c483c32be8fcd8a2e0df9897ba5338ca2dc23bdd9ecda6c1bc87"
HORIZONS = (1, 3, 5, 10, 20)
PRIMARY_HORIZONS = (5, 10, 20)
ABS_LEVELS = (-0.04, -0.06, -0.08)
REL_LEVELS = (-0.02, -0.04)
WINDOWS = (2, 3, 5)
ANCHOR = "ABS_m06_REL_m04_W3"
SEVERE = -0.10


class ShockNeighborhoodError(RuntimeError):
    """Fail-closed error for the frozen V1.1 experiment."""


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise ShockNeighborhoodError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


V1 = _load_module("shock_absorption_v1_for_v1_1", V1_PATH)
EXECUTION = V1.EXECUTION


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
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
    if isinstance(value, (date, pd.Timestamp)):
        return value.isoformat()
    if value is None or pd.isna(value):
        return None
    return value


def validate_outcome_boundary(evaluation: pd.DataFrame) -> date:
    if evaluation.empty or pd.to_datetime(evaluation.signal_date).dt.year.max() > 2023:
        raise ShockNeighborhoodError("empty or post-2023 signal evaluation")
    outcome_dates = pd.concat(
        [pd.to_datetime(evaluation[f"outcome_date_h{horizon}"]) for horizon in HORIZONS]
    ).dropna()
    if outcome_dates.empty:
        raise ShockNeighborhoodError("no completed outcome")
    maximum = outcome_dates.max().date()
    if maximum > pd.Timestamp("2023-12-31").date():
        raise ShockNeighborhoodError("post-2023 outcome detected")
    return maximum


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise ShockNeighborhoodError("frozen specification identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_V1_1_GRID_OUTCOME_ACCESS_AFTER_V1_RESULT_KNOWN":
        raise ShockNeighborhoodError("invalid freeze provenance")
    if spec["parameter_grid"]["total_cells"] != 18:
        raise ShockNeighborhoodError("grid is not the frozen 18 cells")
    for role, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise ShockNeighborhoodError(f"bound input changed: {role}")
    prohibited = "|".join(spec["prohibited"])
    for phrase in ("post-2023", "CY-011", "sign-inversion", "machine-learning"):
        if phrase not in prohibited:
            raise ShockNeighborhoodError(f"missing prohibition: {phrase}")
    return spec


def _configure() -> duckdb.DuckDBPyConnection:
    EXTERNAL_ROOT.mkdir(parents=True, exist_ok=True)
    TEMP_PATH.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect()
    connection.execute("SET threads=1")
    connection.execute("SET memory_limit='12GB'")
    connection.execute("SET preserve_insertion_order=false")
    connection.execute(f"SET temp_directory='{TEMP_PATH.as_posix()}'")
    return connection


def cell_id(absolute_threshold: float, relative_threshold: float, window: int) -> str:
    absolute = round(abs(absolute_threshold) * 100)
    relative = round(abs(relative_threshold) * 100)
    return f"ABS_m{absolute:02d}_REL_m{relative:02d}_W{window}"


def grid_cells() -> list[dict[str, Any]]:
    return [
        {
            "cell_id": cell_id(absolute, relative, window),
            "absolute_threshold": absolute,
            "relative_threshold": relative,
            "window": window,
            "coordinate": (ai, ri, wi),
        }
        for ai, absolute in enumerate(ABS_LEVELS)
        for ri, relative in enumerate(REL_LEVELS)
        for wi, window in enumerate(WINDOWS)
    ]


def qualifies_shock(
    stock_log_return: float,
    industry_log_return: float,
    absolute_threshold: float,
    relative_threshold: float,
) -> bool:
    stock_return = math.expm1(stock_log_return)
    industry_return = math.expm1(industry_log_return)
    return (
        stock_return <= absolute_threshold and stock_return - industry_return <= relative_threshold
    )


def absorption_metrics(
    previous_close: float,
    shock_close: float,
    observation_closes: list[float] | tuple[float, ...],
) -> tuple[float, float]:
    if len(observation_closes) not in WINDOWS:
        raise ShockNeighborhoodError("window must be one of 2/3/5")
    shock_loss = previous_close - shock_close
    if not math.isfinite(shock_loss) or shock_loss <= 0:
        raise ShockNeighborhoodError("shock loss must be positive")
    recovery = (float(observation_closes[-1]) - shock_close) / shock_loss
    further = max(0.0, shock_close - min(map(float, observation_closes))) / shock_loss
    return recovery, further


def suppress_overlapping_events(frame: pd.DataFrame, window: int) -> pd.DataFrame:
    if window not in WINDOWS:
        raise ShockNeighborhoodError("unfrozen overlap window")
    accepted: list[int] = []
    ordered = frame.sort_values(["symbol", "shock_cal_idx", "shock_date"])
    for _, group in ordered.groupby("symbol", sort=False):
        blocked_through = -1
        for row in group.itertuples():
            if int(row.shock_cal_idx) <= blocked_through:
                continue
            accepted.append(int(row.Index))
            blocked_through = int(row.shock_cal_idx) + window
    return frame.loc[sorted(accepted)].sort_values(["shock_date", "symbol"]).reset_index(drop=True)


def assign_quintiles(frame: pd.DataFrame, score: str) -> pd.Series:
    ranks = frame.groupby(["cell_id", "signal_date"], sort=False)[score].rank(
        method="average", pct=True
    )
    return np.ceil(ranks * 5).clip(1, 5).astype("Int64")


def manhattan(left: str, right: str) -> int:
    coordinates = {item["cell_id"]: item["coordinate"] for item in grid_cells()}
    return sum(abs(a - b) for a, b in zip(coordinates[left], coordinates[right], strict=True))


def connected_components(cell_ids: set[str]) -> list[list[str]]:
    remaining = set(cell_ids)
    components: list[list[str]] = []
    while remaining:
        seed = min(remaining)
        stack = [seed]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            remaining.discard(current)
            stack.extend(
                candidate for candidate in list(remaining) if manhattan(current, candidate) == 1
            )
        components.append(sorted(component))
    return sorted(components, key=lambda item: (-len(item), tuple(item)))


def region_spans(component: list[str]) -> bool:
    coordinates = {item["cell_id"]: item["coordinate"] for item in grid_cells()}
    values = [coordinates[item] for item in component]
    return (
        len({item[0] for item in values}) >= 2
        and len({item[1] for item in values}) == 2
        and len({item[2] for item in values}) >= 2
    )


def choose_region(components: list[list[str]]) -> list[str]:
    eligible = [item for item in components if len(item) >= 4 and region_spans(item)]
    if not eligible:
        return []
    eligible.sort(key=lambda item: (-len(item), ANCHOR not in item, tuple(item)))
    return eligible[0]


def region_center(component: list[str]) -> str | None:
    if not component:
        return None
    order = {item["cell_id"]: index for index, item in enumerate(grid_cells())}
    return min(
        component,
        key=lambda item: (
            sum(manhattan(item, other) for other in component),
            manhattan(item, ANCHOR),
            order[item],
        ),
    )


def _build_panel_features(connection: duckdb.DuckDBPyConnection) -> None:
    lead_parts = [
        f"lead(cal_idx,{offset}) OVER forward next_cal_idx_{offset}" for offset in range(1, 6)
    ]
    lead_parts.extend(
        f"lead(step_return,{offset}) OVER forward next_step_return_{offset}"
        for offset in range(1, 6)
    )
    lead_parts.extend(
        f"lead(industry_return_loo,{offset}) OVER forward next_industry_return_{offset}"
        for offset in range(1, 6)
    )
    for window in WINDOWS:
        lead_parts.extend(
            [
                f"lead(trade_date,{window}) OVER forward signal_date_{window}",
                f"lead(max_return20,{window}) OVER forward signal_max_return20_{window}",
                f"lead(diffusion_score,{window}) OVER forward signal_diffusion_score_{window}",
            ]
        )
    lead_fields = ",\n".join(lead_parts)
    connection.execute(
        f"""CREATE TEMP TABLE panel_features AS SELECT *,
          count(step_return) OVER prior20 prior_count20,
          min(cal_idx) OVER prior20 prior_start_cal_idx,
          sum(step_return) OVER prior20 pre_shock_trend20,
          stddev_samp(step_return) OVER prior20 pre_shock_volatility20,
          {lead_fields}
        FROM panel WINDOW prior20 AS
          (PARTITION BY symbol ORDER BY cal_idx ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
          forward AS (PARTITION BY symbol ORDER BY cal_idx)"""
    )


def _build_complete_paths(connection: duckdb.DuckDBPyConnection) -> None:
    geometry_parts = []
    for offset in range(1, 6):
        geometry_parts.extend(
            [
                f"lead(cal_idx,{offset}) OVER path geometry_cal_idx_{offset}",
                f"lead(history_valid,{offset}) OVER path geometry_valid_{offset}",
                f"lead(coordinate_close,{offset}) OVER path observation_close_{offset}",
            ]
        )
    geometry_leads = ",\n".join(geometry_parts)
    connection.execute(
        f"""CREATE TEMP TABLE geometry_paths AS SELECT symbol,cal_idx,history_valid,
          coordinate_close shock_coordinate_close,
          lag(cal_idx,1) OVER path previous_cal_idx,
          lag(history_valid,1) OVER path previous_history_valid,
          lag(coordinate_close,1) OVER path previous_coordinate_close,
          {geometry_leads}
        FROM raw_geometry WINDOW path AS (PARTITION BY symbol ORDER BY cal_idx)"""
    )
    signal_fields = ",\n".join(
        f"p.signal_date_{window},p.next_cal_idx_{window} signal_cal_idx_{window},"
        f"p.signal_max_return20_{window},p.signal_diffusion_score_{window}"
        for window in WINDOWS
    )
    close_fields = ",".join(f"g.observation_close_{offset}" for offset in range(1, 6))
    completeness = {}
    for window in WINDOWS:
        panel_checks = " AND ".join(
            f"p.next_cal_idx_{offset}=p.cal_idx+{offset}" for offset in range(1, window + 1)
        )
        geometry_checks = " AND ".join(
            [
                f"g.geometry_cal_idx_{offset}=g.cal_idx+{offset}"
                f" AND g.geometry_valid_{offset}"
                f" AND g.observation_close_{offset}>0"
                for offset in range(1, window + 1)
            ]
        )
        completeness[window] = f"({panel_checks} AND {geometry_checks})"
    metric_fields = []
    for window in WINDOWS:
        minimum = ",".join(f"g.observation_close_{offset}" for offset in range(1, window + 1))
        residual = "+".join(
            f"(p.next_step_return_{offset}-p.next_industry_return_{offset})"
            for offset in range(1, window + 1)
        )
        metric_fields.extend(
            [
                f"{completeness[window]} complete_w{window}",
                f"CASE WHEN {completeness[window]} THEN "
                f"(g.observation_close_{window}-g.shock_coordinate_close)"
                "/nullif(g.previous_coordinate_close-g.shock_coordinate_close,0) END "
                f"recovery_fraction_w{window}",
                f"CASE WHEN {completeness[window]} THEN greatest(0,g.shock_coordinate_close-"
                f"least({minimum}))/nullif(g.previous_coordinate_close-g.shock_coordinate_close,0) "
                f"END further_drawdown_ratio_w{window}",
                f"CASE WHEN {completeness[window]} THEN {residual} END "
                f"industry_rel_recovery_w{window}",
            ]
        )
    connection.execute(
        f"""CREATE TEMP TABLE complete_paths AS SELECT
          p.trade_date shock_date,p.cal_idx shock_cal_idx,p.symbol,p.industry,
          exp(p.step_return)-1 stock_shock_return,
          exp(p.industry_return_loo)-1 industry_shock_return,
          exp(p.step_return)-exp(p.industry_return_loo) relative_shock_return,
          p.pre_shock_trend20,p.pre_shock_volatility20,
          p.avg_amount20 shock_avg_amount20,{signal_fields},
          g.previous_coordinate_close,g.shock_coordinate_close,{close_fields},
          {",".join(metric_fields)}
        FROM panel_features p JOIN geometry_paths g USING(symbol,cal_idx)
        WHERE p.prior_count20=20 AND p.cal_idx-p.prior_start_cal_idx=20
          AND exp(p.step_return)-1<0
          AND g.previous_cal_idx=g.cal_idx-1 AND g.previous_history_valid
          AND g.history_valid AND g.previous_coordinate_close>g.shock_coordinate_close"""
    )


def _candidate_shocks(connection: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = connection.execute(
        """SELECT row_number() OVER(ORDER BY trade_date,symbol)-1 candidate_id,
          trade_date shock_date,cal_idx shock_cal_idx,symbol,industry,
          exp(step_return)-1 stock_shock_return,
          exp(industry_return_loo)-1 industry_shock_return,
          exp(step_return)-exp(industry_return_loo) relative_shock_return
        FROM panel_features
        WHERE prior_count20=20 AND cal_idx-prior_start_cal_idx=20
          AND exp(step_return)-1<=-0.04
          AND exp(step_return)-exp(industry_return_loo)<=-0.02
        ORDER BY trade_date,symbol"""
    ).fetchdf()
    frame["shock_date"] = pd.to_datetime(frame.shock_date).dt.date
    if frame.empty or frame.duplicated(["shock_date", "symbol"]).any():
        raise ShockNeighborhoodError("invalid permissive shock set")
    return frame


def _path_projection(window: int, alias: str = "p") -> str:
    observation_fields = ",".join(
        (
            f"{alias}.observation_close_{offset} observation_close_{offset}"
            if offset <= window
            else f"CAST(NULL AS DOUBLE) observation_close_{offset}"
        )
        for offset in range(1, 6)
    )
    return f"""{alias}.shock_date,{alias}.shock_cal_idx,{alias}.symbol,{alias}.industry,
      {alias}.stock_shock_return,{alias}.industry_shock_return,{alias}.relative_shock_return,
      {alias}.pre_shock_trend20,{alias}.pre_shock_volatility20,
      {alias}.shock_avg_amount20,{alias}.signal_date_{window} signal_date,
      {alias}.signal_cal_idx_{window} signal_cal_idx,
      {alias}.signal_max_return20_{window} signal_max_return20,
      {alias}.signal_diffusion_score_{window} signal_diffusion_score,
      {alias}.previous_coordinate_close,{alias}.shock_coordinate_close,
      {observation_fields},
      {alias}.recovery_fraction_w{window} recovery_fraction,
      {alias}.further_drawdown_ratio_w{window} further_drawdown_ratio,
      {alias}.industry_rel_recovery_w{window} industry_rel_recovery"""


def _build_cell_events(
    connection: duckdb.DuckDBPyConnection, candidates: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame]:
    accepted_frames = []
    coverage_rows = []
    next_event_id = 0
    for cell in grid_cells():
        qualifying = candidates.loc[
            candidates.stock_shock_return.le(cell["absolute_threshold"])
            & candidates.relative_shock_return.le(cell["relative_threshold"])
        ].copy()
        accepted = suppress_overlapping_events(qualifying, cell["window"])
        accepted["cell_id"] = cell["cell_id"]
        accepted["window"] = cell["window"]
        accepted["absolute_threshold"] = cell["absolute_threshold"]
        accepted["relative_threshold"] = cell["relative_threshold"]
        accepted["event_id"] = np.arange(next_event_id, next_event_id + len(accepted))
        next_event_id += len(accepted)
        accepted_frames.append(
            accepted[
                [
                    "event_id",
                    "cell_id",
                    "window",
                    "absolute_threshold",
                    "relative_threshold",
                    "shock_date",
                    "shock_cal_idx",
                    "symbol",
                ]
            ]
        )
        coverage_rows.append(
            {
                **cell,
                "qualifying_events": len(qualifying),
                "accepted_nonoverlap_events": len(accepted),
            }
        )
    accepted_all = pd.concat(accepted_frames, ignore_index=True)
    connection.register("accepted_grid_events", accepted_all)
    parts = []
    for window in WINDOWS:
        parts.append(
            f"""SELECT a.event_id,a.cell_id,a.window,a.absolute_threshold,
              a.relative_threshold,{_path_projection(window)}
            FROM accepted_grid_events a JOIN complete_paths p
              ON p.symbol=a.symbol AND p.shock_cal_idx=a.shock_cal_idx
            WHERE a.window={window} AND p.complete_w{window}"""
        )
    events = connection.execute(
        " UNION ALL ".join(parts) + " ORDER BY cell_id,shock_date,symbol"
    ).fetchdf()
    if events.empty or events.duplicated("event_id").any():
        raise ShockNeighborhoodError("invalid complete grid events")
    events["sample_type"] = "SHOCK"
    events["source_cell_id"] = events.cell_id
    events["shock_date"] = pd.to_datetime(events.shock_date).dt.date
    events["signal_date"] = pd.to_datetime(events.signal_date).dt.date
    events["absolute_shock_magnitude"] = -events.stock_shock_return
    events["relative_shock_magnitude"] = -events.relative_shock_return
    complete_counts = events.groupby("cell_id").size()
    coverage = pd.DataFrame(coverage_rows).drop(columns="coordinate")
    coverage["complete_events"] = coverage.cell_id.map(complete_counts).fillna(0).astype(int)
    return events, coverage


def _matched_generic_controls(
    connection: duckdb.DuckDBPyConnection, events: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, int]]:
    outputs = []
    fallback_counts: dict[str, int] = {}
    for window in WINDOWS:
        source_cell = cell_id(-0.06, -0.04, window)
        generic_cell = f"GENERIC_W{window}"
        source = events.loc[events.cell_id.eq(source_cell)]
        keys = source[
            ["event_id", "shock_date", "stock_shock_return", "industry", "symbol"]
        ].rename(columns={"symbol": "event_symbol"})
        connection.register("generic_match_keys", keys)
        same_industry = connection.execute(
            f"""SELECT * EXCLUDE(match_rank) FROM (
              SELECT e.event_id matched_event_id,'{generic_cell}' cell_id,
                '{source_cell}' source_cell_id,{window} window_size,
                {_path_projection(window)},
                row_number() OVER(PARTITION BY e.event_id ORDER BY
                  abs(p.stock_shock_return-e.stock_shock_return),p.symbol) match_rank
              FROM generic_match_keys e JOIN complete_paths p
                ON p.shock_date=e.shock_date AND p.industry=e.industry
              WHERE p.complete_w{window} AND p.symbol<>e.event_symbol
                AND NOT (p.stock_shock_return<=-0.06 AND p.relative_shock_return<=-0.04)
            ) WHERE match_rank=1 ORDER BY matched_event_id"""
        ).fetchdf()
        matched = set(same_industry.matched_event_id.astype(int))
        missing = keys.loc[~keys.event_id.isin(matched)]
        fallback = pd.DataFrame()
        if not missing.empty:
            connection.unregister("generic_match_keys")
            connection.register("generic_match_keys", missing)
            fallback = connection.execute(
                f"""SELECT * EXCLUDE(match_rank) FROM (
                  SELECT e.event_id matched_event_id,'{generic_cell}' cell_id,
                    '{source_cell}' source_cell_id,{window} window_size,
                    {_path_projection(window)},
                    row_number() OVER(PARTITION BY e.event_id ORDER BY
                      abs(p.stock_shock_return-e.stock_shock_return),p.symbol) match_rank
                  FROM generic_match_keys e JOIN complete_paths p ON p.shock_date=e.shock_date
                  WHERE p.complete_w{window} AND p.symbol<>e.event_symbol
                    AND NOT (p.stock_shock_return<=-0.06 AND p.relative_shock_return<=-0.04)
                ) WHERE match_rank=1 ORDER BY matched_event_id"""
            ).fetchdf()
        connection.unregister("generic_match_keys")
        matched_controls = pd.concat([same_industry, fallback], ignore_index=True)
        if len(matched_controls) != len(source):
            raise ShockNeighborhoodError(f"generic matching incomplete for W{window}")
        matched_controls["sample_type"] = "NONSHOCK"
        matched_controls = matched_controls.rename(columns={"window_size": "window"})
        matched_controls["absolute_threshold"] = -0.06
        matched_controls["relative_threshold"] = -0.04
        matched_controls["shock_date"] = pd.to_datetime(matched_controls.shock_date).dt.date
        matched_controls["signal_date"] = pd.to_datetime(matched_controls.signal_date).dt.date
        matched_controls["absolute_shock_magnitude"] = -matched_controls.stock_shock_return
        matched_controls["relative_shock_magnitude"] = -matched_controls.relative_shock_return
        outputs.append(matched_controls)
        fallback_counts[generic_cell] = len(fallback)
    return pd.concat(outputs, ignore_index=True), fallback_counts


def _rank_samples(events: pd.DataFrame, controls: pd.DataFrame) -> pd.DataFrame:
    frame = pd.concat([events, controls], ignore_index=True, sort=False)
    frame["date_event_count"] = frame.groupby(["cell_id", "signal_date"], sort=False)[
        "symbol"
    ].transform("size")
    frame = frame.loc[frame.date_event_count.ge(5)].copy()
    frame["recovery_quintile"] = assign_quintiles(frame, "recovery_fraction")
    frame["stabilization_score"] = -frame.further_drawdown_ratio
    frame["stabilization_quintile"] = assign_quintiles(frame, "stabilization_score")
    frame = frame.sort_values(["cell_id", "signal_date", "symbol", "event_id"])
    frame["signal_id"] = np.arange(len(frame), dtype=np.int64)
    frame["trade_date"] = frame.signal_date
    frame["cal_idx"] = frame.signal_cal_idx
    return frame.reset_index(drop=True)


def _attach_outcomes(
    connection: duckdb.DuckDBPyConnection,
    signals: pd.DataFrame,
    calendar: list[date],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    attached, actionability = EXECUTION._attach_outcomes(connection, signals)
    for horizon in HORIZONS:
        value = f"net_return_h{horizon}"
        attached[f"industry_mean_h{horizon}"] = attached.groupby(
            ["cell_id", "trade_date", "industry"], sort=False
        )[value].transform("mean")
        attached[f"broad_mean_h{horizon}"] = attached.groupby(
            ["cell_id", "trade_date"], sort=False
        )[value].transform("mean")
        attached[f"industry_relative_h{horizon}"] = (
            attached[value] - attached[f"industry_mean_h{horizon}"]
        )
        attached[f"broad_relative_h{horizon}"] = (
            attached[value] - attached[f"broad_mean_h{horizon}"]
        )
        outcome_dates = []
        for entry_index, outcome in zip(attached.entry_cal_idx, attached[value], strict=True):
            target = int(entry_index) + horizon - 1 if pd.notna(entry_index) else -1
            outcome_dates.append(
                calendar[target] if pd.notna(outcome) and 0 <= target < len(calendar) else pd.NaT
            )
        attached[f"outcome_date_h{horizon}"] = outcome_dates
    return attached, actionability


def _period_mask(frame: pd.DataFrame, period: str) -> pd.Series:
    years = pd.to_datetime(frame.signal_date).dt.year
    if period == "full":
        return pd.Series(True, index=frame.index)
    if period == "early_2018_2021":
        return years.between(2018, 2021)
    if period == "late_2022_2023":
        return years.between(2022, 2023)
    return years.eq(int(period))


def _quintile_metrics(subset: pd.DataFrame, horizon: int) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for quintile in range(1, 6):
        group = subset.loc[subset.recovery_quintile.eq(quintile)]
        absolute = group[f"net_return_h{horizon}"].dropna()
        aligned = group.loc[absolute.index]
        industry_relative = aligned[f"industry_relative_h{horizon}"].dropna()
        aligned = aligned.loc[industry_relative.index]
        prefix = f"q{quintile}"
        output[f"{prefix}_count"] = len(aligned)
        output[f"{prefix}_mean_net"] = absolute.loc[aligned.index].mean()
        output[f"{prefix}_median_net"] = absolute.loc[aligned.index].median()
        output[f"{prefix}_positive_fraction"] = (absolute.loc[aligned.index] > 0).mean()
        output[f"{prefix}_mean_industry_relative"] = industry_relative.mean()
        output[f"{prefix}_median_industry_relative"] = industry_relative.median()
        output[f"{prefix}_severe_fraction"] = (absolute.loc[aligned.index] <= SEVERE).mean()
        output[f"{prefix}_mean_mae_h20"] = aligned.mae_h20.mean() if horizon == 20 else np.nan
    for metric in (
        "mean_net",
        "median_net",
        "positive_fraction",
        "mean_industry_relative",
        "median_industry_relative",
        "severe_fraction",
        "mean_mae_h20",
    ):
        output[f"spread_{metric}"] = output[f"q5_{metric}"] - output[f"q1_{metric}"]
    output["spread_count"] = min(output["q1_count"], output["q5_count"])
    output["dates"] = subset.signal_date.nunique()
    output["securities"] = subset.symbol.nunique()
    output["industries"] = subset.industry.nunique()
    return output


def _surface_table(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    periods = ["full", "early_2018_2021", "late_2022_2023", *map(str, range(2018, 2024))]
    for cell in [item["cell_id"] for item in grid_cells()] + [f"GENERIC_W{w}" for w in WINDOWS]:
        cell_panel = panel.loc[panel.cell_id.eq(cell)]
        for period in periods:
            subset = cell_panel.loc[_period_mask(cell_panel, period)]
            for horizon in HORIZONS:
                rows.append(
                    {
                        "cell_id": cell,
                        "sample_type": ("NONSHOCK" if cell.startswith("GENERIC") else "SHOCK"),
                        "period": period,
                        "horizon": horizon,
                        **_quintile_metrics(subset, horizon),
                    }
                )
    return pd.DataFrame(rows)


def _lookup(surface: pd.DataFrame, cell: str, period: str, horizon: int) -> dict[str, Any]:
    row = surface.loc[
        surface.cell_id.eq(cell) & surface.period.eq(period) & surface.horizon.eq(horizon)
    ]
    if len(row) != 1:
        raise ShockNeighborhoodError(f"missing surface row {cell}/{period}/h{horizon}")
    return row.iloc[0].to_dict()


def _cell_topology(surface: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    rows = []
    for cell in [item["cell_id"] for item in grid_cells()]:
        full = [_lookup(surface, cell, "full", horizon) for horizon in PRIMARY_HORIZONS]
        early = [_lookup(surface, cell, "early_2018_2021", horizon) for horizon in PRIMARY_HORIZONS]
        late = [_lookup(surface, cell, "late_2022_2023", horizon) for horizon in PRIMARY_HORIZONS]
        annual_means = []
        for year in range(2018, 2024):
            annual_means.append(
                np.mean(
                    [
                        _lookup(surface, cell, str(year), horizon)["spread_mean_industry_relative"]
                        for horizon in PRIMARY_HORIZONS
                    ]
                )
            )
        adequate = all(
            row["q1_count"] >= 200 and row["q5_count"] >= 200 and row["dates"] >= 60 for row in full
        )
        full_ir = float(np.mean([row["spread_mean_industry_relative"] for row in full]))
        full_abs = float(np.mean([row["spread_mean_net"] for row in full]))
        early_ir = float(np.mean([row["spread_mean_industry_relative"] for row in early]))
        late_ir = float(np.mean([row["spread_mean_industry_relative"] for row in late]))
        favorable = (
            adequate
            and full_ir >= 0.002
            and sum(row["spread_mean_industry_relative"] > 0 for row in full) >= 2
            and full_abs > 0
        )
        coherent = (
            favorable
            and early_ir > 0
            and late_ir > 0
            and sum(value > 0 for value in annual_means) >= 4
        )
        rows.append(
            {
                "cell_id": cell,
                "adequate": adequate,
                "mean_primary_absolute_spread": full_abs,
                "mean_primary_industry_relative_spread": full_ir,
                "positive_primary_horizons": sum(
                    row["spread_mean_industry_relative"] > 0 for row in full
                ),
                "early_mean_primary_industry_relative_spread": early_ir,
                "late_mean_primary_industry_relative_spread": late_ir,
                "positive_annual_means": sum(value > 0 for value in annual_means),
                "favorable": favorable,
                "coherent": coherent,
                "annual_means": annual_means,
            }
        )
    topology = pd.DataFrame(rows)
    favorable_components = connected_components(set(topology.loc[topology.favorable, "cell_id"]))
    coherent_components = connected_components(set(topology.loc[topology.coherent, "cell_id"]))
    stable_region = choose_region(coherent_components)
    sign_reversals = int(
        (
            topology.early_mean_primary_industry_relative_spread
            * topology.late_mean_primary_industry_relative_spread
            < 0
        ).sum()
    )
    return topology, {
        "favorable_cells": topology.loc[topology.favorable, "cell_id"].tolist(),
        "coherent_cells": topology.loc[topology.coherent, "cell_id"].tolist(),
        "favorable_components": favorable_components,
        "coherent_components": coherent_components,
        "stable_region": stable_region,
        "region_center": region_center(stable_region),
        "isolated_optimum": bool(
            topology.favorable.any()
            and max([len(item) for item in favorable_components], default=0) <= 2
        ),
        "sign_reversal_cells": sign_reversals,
        "mixed_surface": bool(not stable_region and sign_reversals >= 9),
        "broad_null_or_adverse": bool(
            topology.mean_primary_industry_relative_spread.le(0).sum() >= 12
        ),
    }


def _actionability_by_cell(panel: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for cell, group in panel.loc[panel.sample_type.eq("SHOCK")].groupby("cell_id"):
        output[cell] = {
            "signal_observations": len(group),
            "immediate": int(group.entry_status.eq("IMMEDIATE").sum()),
            "delayed": int(group.entry_status.eq("DELAYED").sum()),
            "unusable": int(group.entry_status.eq("UNUSABLE").sum()),
            "actionable_fraction": float(group.entry_status.isin(["IMMEDIATE", "DELAYED"]).mean()),
            "immediate_block_reasons": {
                str(key): int(value)
                for key, value in group.loc[group.entry_status.ne("IMMEDIATE")]
                .immediate_block_reason.value_counts()
                .sort_index()
                .items()
            },
        }
    return output


def _severity_control(panel: pd.DataFrame, target: str) -> dict[str, Any]:
    group = panel.loc[panel.cell_id.eq(target)].copy()
    group["absolute_bin"] = np.select(
        [group.absolute_shock_magnitude.lt(0.08), group.absolute_shock_magnitude.lt(0.10)],
        ["threshold_to_8pct", "8_to_10pct"],
        default="at_least_10pct",
    )
    group["relative_bin"] = np.select(
        [group.relative_shock_magnitude.lt(0.06), group.relative_shock_magnitude.lt(0.08)],
        ["threshold_to_6pct", "6_to_8pct"],
        default="at_least_8pct",
    )
    rows = []
    for (absolute_bin, relative_bin), cell in group.groupby(
        ["absolute_bin", "relative_bin"], sort=True
    ):
        horizon_spreads = []
        q1_h20 = q5_h20 = 0
        for horizon in PRIMARY_HORIZONS:
            q1 = cell.loc[cell.recovery_quintile.eq(1), f"industry_relative_h{horizon}"].dropna()
            q5 = cell.loc[cell.recovery_quintile.eq(5), f"industry_relative_h{horizon}"].dropna()
            horizon_spreads.append(q5.mean() - q1.mean())
            if horizon == 20:
                q1_h20, q5_h20 = len(q1), len(q5)
        rows.append(
            {
                "absolute_bin": absolute_bin,
                "relative_bin": relative_bin,
                "q1_h20_count": q1_h20,
                "q5_h20_count": q5_h20,
                "mean_primary_industry_relative_spread": np.mean(horizon_spreads),
                "supported": q1_h20 >= 20 and q5_h20 >= 20,
            }
        )
    table = pd.DataFrame(rows)
    supported = table.loc[table.supported]
    positive_fraction = (
        float(supported.mean_primary_industry_relative_spread.gt(0).mean())
        if len(supported)
        else 0.0
    )
    return {
        "target": target,
        "cells": table.to_dict("records"),
        "supported_cells": len(supported),
        "positive_supported_fraction": positive_fraction,
        "pass": bool(len(supported) and positive_fraction >= 0.5),
    }


def _coarse_controls(panel: pd.DataFrame, target: str) -> dict[str, Any]:
    target_panel = panel.loc[panel.cell_id.eq(target)].copy()
    definitions = {
        "PRE_SHOCK_TREND": "pre_shock_trend20",
        "REALIZED_VOLATILITY": "pre_shock_volatility20",
        "LIQUIDITY": "shock_avg_amount20",
    }
    output = {}
    for name, column in definitions.items():
        ranks = target_panel.groupby("signal_date", sort=False)[column].rank(
            method="average", pct=True
        )
        target_panel["control_tercile"] = np.ceil(ranks * 3).clip(1, 3).astype("Int64")
        rows = []
        for tercile in range(1, 4):
            group = target_panel.loc[target_panel.control_tercile.eq(tercile)]
            spreads = []
            for horizon in PRIMARY_HORIZONS:
                q1 = group.loc[
                    group.recovery_quintile.eq(1), f"industry_relative_h{horizon}"
                ].dropna()
                q5 = group.loc[
                    group.recovery_quintile.eq(5), f"industry_relative_h{horizon}"
                ].dropna()
                spreads.append(q5.mean() - q1.mean())
            rows.append(
                {
                    "tercile": tercile,
                    "observations": len(group),
                    "mean_primary_industry_relative_spread": np.mean(spreads),
                }
            )
        positive = sum(row["mean_primary_industry_relative_spread"] > 0 for row in rows)
        output[name] = {"terciles": rows, "pass": positive >= 2}
    return output


def _generic_control(surface: pd.DataFrame) -> dict[str, Any]:
    output = {}
    for window in WINDOWS:
        shock = cell_id(-0.06, -0.04, window)
        generic = f"GENERIC_W{window}"
        shock_spread = float(
            np.mean(
                [
                    _lookup(surface, shock, "full", horizon)["spread_mean_industry_relative"]
                    for horizon in PRIMARY_HORIZONS
                ]
            )
        )
        generic_spread = float(
            np.mean(
                [
                    _lookup(surface, generic, "full", horizon)["spread_mean_industry_relative"]
                    for horizon in PRIMARY_HORIZONS
                ]
            )
        )
        output[f"W{window}"] = {
            "shock_mean_primary_industry_relative_spread": shock_spread,
            "generic_mean_primary_industry_relative_spread": generic_spread,
            "generic_similar": bool(generic_spread > 0 and generic_spread >= 0.75 * shock_spread),
        }
    return output


def _rank_correlation(frame: pd.DataFrame, left: str, right: str) -> dict[str, Any]:
    rows = []
    for day, group in frame.groupby("signal_date", sort=True):
        valid = group[[left, right]].dropna()
        if len(valid) >= 5:
            rows.append(
                (
                    pd.Timestamp(day).year,
                    float(spearmanr(valid[left], valid[right]).statistic),
                )
            )
    data = pd.DataFrame(rows, columns=["year", "rho"])
    return {
        "dates": len(data),
        "mean_same_date_spearman": float(data.rho.mean()),
        "median_same_date_spearman": float(data.rho.median()),
        "early_mean": float(data.loc[data.year.le(2021), "rho"].mean()),
        "late_mean": float(data.loc[data.year.ge(2022), "rho"].mean()),
    }


def _independence(panel: pd.DataFrame, target: str, champion_path: Path) -> dict[str, Any]:
    events = panel.loc[panel.cell_id.eq(target)].copy()
    low_max = _rank_correlation(events, "recovery_fraction", "signal_max_return20")
    champion = pd.read_csv(champion_path, usecols=["family", "trade_date", "symbol"])
    champion = champion.loc[champion.family.eq("arm2_low_max"), ["trade_date", "symbol"]]
    champion["signal_date"] = pd.to_datetime(champion.trade_date).dt.date
    champion = champion.drop(columns="trade_date").drop_duplicates()
    champion["champion_selected"] = True
    merged = events.merge(champion, on=["signal_date", "symbol"], how="left")
    merged["champion_selected"] = (
        merged.champion_selected.astype("boolean").fillna(False).astype(bool)
    )
    remaining = merged.loc[~merged.champion_selected]
    removed = {}
    for horizon in PRIMARY_HORIZONS:
        q1 = remaining.loc[
            remaining.recovery_quintile.eq(1), f"industry_relative_h{horizon}"
        ].dropna()
        q5 = remaining.loc[
            remaining.recovery_quintile.eq(5), f"industry_relative_h{horizon}"
        ].dropna()
        removed[f"h{horizon}"] = q5.mean() - q1.mean()
    q5 = merged.recovery_quintile.eq(5)
    return {
        "target": target,
        "low_max_rank_relationship": low_max,
        "champion_selected_observations": int(merged.champion_selected.sum()),
        "q5_champion_overlap_count": int((q5 & merged.champion_selected).sum()),
        "q5_champion_overlap_fraction": float(
            (q5 & merged.champion_selected).sum() / max(1, q5.sum())
        ),
        "economics_after_removing_champion": removed,
    }


def _training_selection(panel: pd.DataFrame, cutoff: str) -> dict[str, Any]:
    cutoff_date = pd.Timestamp(cutoff).date()
    h20_dates = pd.to_datetime(panel.outcome_date_h20).dt.date
    training = panel.loc[
        panel.sample_type.eq("SHOCK") & h20_dates.notna() & h20_dates.le(cutoff_date)
    ]
    favorable = []
    summaries = {}
    for cell in [item["cell_id"] for item in grid_cells()]:
        group = training.loc[training.cell_id.eq(cell)]
        metrics = [_quintile_metrics(group, horizon) for horizon in PRIMARY_HORIZONS]
        support = all(
            row["q1_count"] >= 100 and row["q5_count"] >= 100 and row["dates"] >= 30
            for row in metrics
        )
        industry_relative = [row["spread_mean_industry_relative"] for row in metrics]
        absolute = [row["spread_mean_net"] for row in metrics]
        qualifies = (
            support
            and np.mean(industry_relative) >= 0.002
            and sum(value > 0 for value in industry_relative) >= 2
            and np.mean(absolute) > 0
        )
        if qualifies:
            favorable.append(cell)
        summaries[cell] = {
            "support": support,
            "mean_primary_industry_relative_spread": np.mean(industry_relative),
            "positive_primary_horizons": sum(value > 0 for value in industry_relative),
            "mean_primary_absolute_spread": np.mean(absolute),
            "favorable": qualifies,
        }
    components = connected_components(set(favorable))
    region = choose_region(components)
    return {
        "cutoff": cutoff,
        "favorable_cells": favorable,
        "components": components,
        "region": region,
        "selected_cell": region_center(region),
        "cell_summaries": summaries,
    }


def _application_subset(
    panel: pd.DataFrame, selected_cell: str, year: int, horizon: int
) -> pd.DataFrame:
    year_end = pd.Timestamp(f"{year}-12-31").date()
    base = panel.loc[
        panel.cell_id.eq(selected_cell) & pd.to_datetime(panel.signal_date).dt.year.eq(year)
    ]
    outcome_dates = pd.to_datetime(base[f"outcome_date_h{horizon}"]).dt.date
    return base.loc[outcome_dates.notna() & outcome_dates.le(year_end)]


def _walk_forward(panel: pd.DataFrame) -> dict[str, Any]:
    selections = []
    selected_panels: dict[int, list[pd.DataFrame]] = {horizon: [] for horizon in PRIMARY_HORIZONS}
    for cutoff, year in zip(
        ("2020-12-31", "2021-12-31", "2022-12-31"), (2021, 2022, 2023), strict=True
    ):
        selection = _training_selection(panel, cutoff)
        selected = selection["selected_cell"]
        metrics = {}
        if selected is not None:
            for horizon in PRIMARY_HORIZONS:
                eligible = _application_subset(panel, selected, year, horizon)
                selected_panels[horizon].append(eligible.assign(application_year=year))
                metrics[f"h{horizon}"] = _quintile_metrics(eligible, horizon)
        selections.append(
            {
                "application_year": year,
                **selection,
                "future_metrics": metrics,
            }
        )
    selected_count = sum(item["selected_cell"] is not None for item in selections)
    aggregate = {}
    for horizon in PRIMARY_HORIZONS:
        if selected_panels[horizon]:
            pooled = pd.concat(selected_panels[horizon], ignore_index=True)
            aggregate[f"h{horizon}"] = _quintile_metrics(pooled, horizon)
    aggregate_spreads = [
        aggregate[f"h{horizon}"]["spread_mean_industry_relative"]
        for horizon in PRIMARY_HORIZONS
        if f"h{horizon}" in aggregate
    ]
    year_means = []
    for item in selections:
        if item["future_metrics"]:
            year_means.append(
                np.mean(
                    [
                        item["future_metrics"][f"h{horizon}"]["spread_mean_industry_relative"]
                        for horizon in PRIMARY_HORIZONS
                    ]
                )
            )
    selected_cells = [
        item["selected_cell"] for item in selections if item["selected_cell"] is not None
    ]
    stable_selection = all(manhattan(left, right) <= 2 for left, right in pairwise(selected_cells))
    passed = bool(
        selected_count >= 2
        and len(aggregate_spreads) == 3
        and np.mean(aggregate_spreads) >= 0.002
        and sum(value > 0 for value in aggregate_spreads) >= 2
        and all(value > -0.002 for value in year_means)
        and stable_selection
    )
    return {
        "claim": "DEVELOPMENT_WALK_FORWARD_NOT_OOS",
        "selections": selections,
        "selected_years": selected_count,
        "aggregate": aggregate,
        "aggregate_mean_primary_industry_relative_spread": (
            np.mean(aggregate_spreads) if aggregate_spreads else np.nan
        ),
        "year_mean_primary_industry_relative_spreads": year_means,
        "selection_stable_manhattan_le_2": stable_selection,
        "pass": passed,
    }


def _defensive_surface(surface: pd.DataFrame) -> dict[str, Any]:
    defensive_cells = []
    for cell in [item["cell_id"] for item in grid_cells()]:
        row = _lookup(surface, cell, "full", 20)
        if (
            row["spread_mean_industry_relative"] <= 0
            and row["spread_severe_fraction"] < 0
            and row["spread_mean_mae_h20"] > 0
        ):
            defensive_cells.append(cell)
    return {
        "defensive_cells": defensive_cells,
        "broad_defensive": len(defensive_cells) >= 12,
    }


def _classify(
    topology: pd.DataFrame,
    topology_result: dict[str, Any],
    gate: dict[str, Any],
    walk_forward: dict[str, Any] | None,
    defensive: dict[str, Any],
) -> str:
    if topology_result["stable_region"]:
        if gate["pass"]:
            if walk_forward is None:
                raise ShockNeighborhoodError("walk-forward missing after a passing gate")
            if walk_forward["pass"]:
                return "PROMISING_STABLE_SHOCK_ABSORPTION_FAMILY"
            if walk_forward["selected_years"] < 2:
                return "PARAMETER_REGION_EXISTS_BUT_NOT_SELECTABLE"
            return "PROMISING_REGION_WALKFORWARD_WEAK"
        if gate["generic_not_similar"] is False:
            return "GENERIC_SHORT_TERM_PRICE_PATH_ONLY"
        if (
            gate["severity_pass"] is False
            and gate["trend_pass"]
            and gate["volatility_pass"]
            and gate["liquidity_pass"]
        ):
            return "SHOCK_SEVERITY_ONLY"
        if defensive["broad_defensive"]:
            return "DEFENSIVE_INFORMATION_ONLY"
        return "PARAMETER_REGION_EXISTS_BUT_NOT_SELECTABLE"
    if topology_result["isolated_optimum"]:
        return "ISOLATED_PARAMETER_OPTIMUM_ONLY"
    if topology_result["mixed_surface"]:
        return "CHRONOLOGICALLY_UNSTABLE"
    if defensive["broad_defensive"]:
        return "DEFENSIVE_INFORMATION_ONLY"
    return "NULL"


def _fmt(value: Any) -> str:
    if value is None or pd.isna(value):
        return "NA"
    return f"{float(value):+.3%}"


def _report(result: dict[str, Any], surface: pd.DataFrame) -> str:
    classification = result["final_classification"]
    topology = result["topology"]
    lines = [
        "# A-share Shock Absorption / Recovery Discovery V1.1",
        "",
        "## Executive conclusion",
        "",
        f"Final classification: `{classification}`.",
        "",
        result["economic_interpretation"],
        "",
        "This is consumed 2018-2023 development evidence. The exact V1 result was "
        "already known before V1.1 was frozen; the 18 new cell outcomes were not.",
        "",
        "## Parameter neighborhood",
        "",
        "The complete frozen grid is absolute shock <= -4%/-6%/-8%, "
        "stock-minus-PIT-industry shock <= -2%/-4%, and exact W=2/3/5 completed "
        "sessions: 18 cells, with no additions or removals.",
        "",
        "## Event coverage",
        "",
        f"Across cells there are {result['coverage']['total_ranked_shock_events']:,} "
        f"ranked event instances, spanning {result['coverage']['securities']:,} securities, "
        f"{result['coverage']['industries']} industries, and "
        f"{result['coverage']['dates']} confirmation dates. Per-cell ranked events range "
        f"from {result['coverage']['event_range_by_cell'][0]:,} to "
        f"{result['coverage']['event_range_by_cell'][1]:,}.",
        "",
        "## Parameter surface",
        "",
        "| Cell | Events | h5 net | h5 industry | h10 net | h10 industry | "
        "h20 net | h20 industry | Favorable | Coherent |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    topology_rows = {item["cell_id"]: item for item in result["cell_topology"]}
    coverage_rows = {item["cell_id"]: item for item in result["cell_coverage"]}
    for cell in [item["cell_id"] for item in grid_cells()]:
        values = []
        for horizon in PRIMARY_HORIZONS:
            row = _lookup(surface, cell, "full", horizon)
            values.extend(
                [_fmt(row["spread_mean_net"]), _fmt(row["spread_mean_industry_relative"])]
            )
        info = topology_rows[cell]
        lines.append(
            f"| {cell} | {coverage_rows[cell]['ranked_events']:,} | "
            f"{' | '.join(values)} | {info['favorable']} | {info['coherent']} |"
        )
    lines.extend(
        [
            "",
            "## Stability topology",
            "",
            f"Stable region found: `{bool(topology['stable_region'])}`. "
            f"Favorable cells: {len(topology['favorable_cells'])}; coherent cells: "
            f"{len(topology['coherent_cells'])}; sign-reversal cells: "
            f"{topology['sign_reversal_cells']}. Region: "
            f"{', '.join(topology['stable_region']) or 'none'}. Region center: "
            f"{topology['region_center'] or 'none'}.",
            "",
            "## Controls",
            "",
            f"Control target: `{result['control_target']}`. Severity pass: "
            f"`{result['severity_control']['pass']}`; supported cells: "
            f"{result['severity_control']['supported_cells']}; positive fraction: "
            f"{result['severity_control']['positive_supported_fraction']:.1%}.",
        ]
    )
    for window in WINDOWS:
        generic = result["generic_control"][f"W{window}"]
        lines.append(
            f"- W{window} shock/generic mean primary industry-relative spread: "
            f"{_fmt(generic['shock_mean_primary_industry_relative_spread'])}/"
            f"{_fmt(generic['generic_mean_primary_industry_relative_spread'])}; "
            f"generic-similar={generic['generic_similar']}."
        )
    for name, control in result["coarse_controls"].items():
        values = " / ".join(
            _fmt(item["mean_primary_industry_relative_spread"]) for item in control["terciles"]
        )
        lines.append(f"- {name}: {values}; pass={control['pass']}.")
    lines.extend(
        [
            "",
            "## Chronological stability",
            "",
            "Cell-level early/late and annual signs are persisted in the compact surface "
            "and result artifacts. Coherence requires both blocks positive and at least "
            "four positive annual means; no year is relabeled OOS.",
            "",
            "## Walk-forward gate",
            "",
            f"Gate: `{'PASS' if result['walk_forward_gate']['pass'] else 'FAIL'}`. "
            f"{result['walk_forward_gate']['reason']}",
            "",
            "## Development walk-forward",
            "",
        ]
    )
    if result["walk_forward"] is None:
        lines.append("Not run because the frozen discovery gate failed.")
    else:
        for selection in result["walk_forward"]["selections"]:
            lines.append(
                f"- {selection['application_year']}: "
                f"{selection['selected_cell'] or 'NO_SIGNAL'} from region "
                f"{','.join(selection['region']) or 'none'}."
            )
        lines.append(
            f"Aggregate walk-forward pass: `{result['walk_forward']['pass']}`; "
            f"mean primary industry-relative spread "
            f"{_fmt(result['walk_forward']['aggregate_mean_primary_industry_relative_spread'])}."
        )
    independence = result["strategy_a_independence"]
    lines.extend(
        [
            "",
            "## Strategy-A independence and execution",
            "",
            f"Low-MAX mean same-date rho is "
            f"{independence['low_max_rank_relationship']['mean_same_date_spearman']:.3f}; "
            f"Champion Q5 overlap is {independence['q5_champion_overlap_fraction']:.2%}. "
            "No Strategy-A rule or result changed.",
            "",
            f"Control-target next-open actionability is "
            f"{result['actionability_by_cell'][result['control_target']]['actionable_fraction']:.2%}.",
            "",
            "## Decision",
            "",
            f"`{classification}`. {result['next_recommended_research_direction']}",
            "",
            "No Strategy-B portfolio, parameter rescue, post-2023 outcome, or CY-011 "
            "input was used.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    spec = _load_spec()
    daily_paths = EXECUTION._daily_paths(spec)
    connection = _configure()
    try:
        V1._panel_audit(connection, _resolve(spec["inputs"]["causal_daily_panel"]["path"]))
        calendar, raw_audit = EXECUTION._build_raw_geometry(connection, daily_paths)
        _build_panel_features(connection)
        _build_complete_paths(connection)
        candidates = _candidate_shocks(connection)
        events, coverage = _build_cell_events(connection, candidates)
        generic_controls, fallback_counts = _matched_generic_controls(connection, events)
        signals = _rank_samples(events, generic_controls)
        evaluation, all_actionability = _attach_outcomes(connection, signals, calendar)
    finally:
        connection.close()
    max_outcome = validate_outcome_boundary(evaluation)
    evaluation.to_parquet(PANEL_PATH, index=False, compression="zstd")
    surface = _surface_table(evaluation)
    topology_table, topology_result = _cell_topology(surface)
    control_target = topology_result["region_center"] or ANCHOR
    actionability = _actionability_by_cell(evaluation)
    severity = _severity_control(evaluation, control_target)
    coarse = _coarse_controls(evaluation, control_target)
    generic = _generic_control(surface)
    target_window = next(
        item["window"] for item in grid_cells() if item["cell_id"] == control_target
    )
    gate = {
        "stable_region": bool(topology_result["stable_region"]),
        "severity_pass": severity["pass"],
        "trend_pass": coarse["PRE_SHOCK_TREND"]["pass"],
        "volatility_pass": coarse["REALIZED_VOLATILITY"]["pass"],
        "liquidity_pass": coarse["LIQUIDITY"]["pass"],
        "generic_not_similar": not generic[f"W{target_window}"]["generic_similar"],
        "actionability_pass": actionability[control_target]["actionable_fraction"] >= 0.90,
    }
    gate["pass"] = all(gate.values())
    failed = [key for key, value in gate.items() if key != "pass" and not value]
    gate["reason"] = (
        "All frozen discovery and control gates pass."
        if gate["pass"]
        else "Failed frozen gates: " + ", ".join(failed) + "."
    )
    walk_forward = _walk_forward(evaluation) if gate["pass"] else None
    defensive = _defensive_surface(surface)
    classification = _classify(topology_table, topology_result, gate, walk_forward, defensive)
    if classification == "PROMISING_STABLE_SHOCK_ABSORPTION_FAMILY":
        interpretation = (
            "A coherent neighboring parameter region survives controls and the strictly "
            "past-only development walk-forward selection gate."
        )
        next_direction = "Freeze a separate Strategy-B construction experiment."
    elif classification == "PROMISING_REGION_WALKFORWARD_WEAK":
        interpretation = (
            "The full development surface has a coherent region, but past-only selection "
            "does not carry forward strongly enough for strategy construction."
        )
        next_direction = "Keep the family unresolved; do not construct Strategy B."
    elif classification == "PARAMETER_REGION_EXISTS_BUT_NOT_SELECTABLE":
        interpretation = (
            "A full-history region exists, but the frozen controls or past-only selection "
            "rule cannot identify a deployable parameter family."
        )
        next_direction = "Do not construct Strategy B; move research capital to Dispersion."
    elif classification == "ISOLATED_PARAMETER_OPTIMUM_ONLY":
        interpretation = (
            "Only isolated favorable cells appear; neighboring definitions do not support "
            "a stable shock-absorption mechanism."
        )
        next_direction = "Close the family and move to frozen Dispersion science."
    elif classification == "CHRONOLOGICALLY_UNSTABLE":
        interpretation = "The parameter surface materially reverses across development blocks."
        next_direction = "Close the family and move to frozen Dispersion science."
    elif classification == "GENERIC_SHORT_TERM_PRICE_PATH_ONLY":
        interpretation = (
            "The apparent region is not specific to a preceding material shock and is "
            "explained by generic short-term recovery."
        )
        next_direction = "Close the family and move to frozen Dispersion science."
    elif classification == "SHOCK_SEVERITY_ONLY":
        interpretation = "Initial shock severity explains the apparent absorption region."
        next_direction = "Close the family and move to frozen Dispersion science."
    elif classification == "DEFENSIVE_INFORMATION_ONLY":
        interpretation = "Absorption changes downside shape without convincing return Alpha."
        next_direction = "Park the defensive information and move to Dispersion."
    else:
        interpretation = (
            "The bounded 18-cell neighborhood contains no useful stable post-shock "
            "absorption mechanism in the frozen orientation."
        )
        next_direction = (
            "Close Shock Absorption V1.1 without rescue and resume the frozen "
            "Cross-Sectional Dispersion science."
        )
    ranked_counts = evaluation.loc[evaluation.sample_type.eq("SHOCK")].groupby("cell_id").size()
    coverage["ranked_events"] = coverage.cell_id.map(ranked_counts).fillna(0).astype(int)
    coverage["actionable_fraction"] = coverage.cell_id.map(
        {key: value["actionable_fraction"] for key, value in actionability.items()}
    )
    surface_output = surface.merge(
        topology_table.drop(columns="annual_means"), on="cell_id", how="left"
    )
    surface_output.to_csv(SURFACE_PATH, index=False, float_format="%.12g")
    independence = _independence(
        evaluation,
        control_target,
        _resolve(spec["inputs"]["champion_attribution"]["path"]),
    )
    shock_panel = evaluation.loc[evaluation.sample_type.eq("SHOCK")]
    result = {
        "experiment_id": spec["experiment_id"],
        "starting_checkpoint": spec["starting_checkpoint"],
        "required_ancestor": spec["required_ancestor"],
        "frozen_spec_sha256": EXPECTED_SPEC_SHA256,
        "claim_boundary": spec["claim_boundary"],
        "provenance_boundary": spec["provenance_boundary"],
        "post_2023_outcome_read": False,
        "cy011_read": False,
        "evaluation_start": str(evaluation.signal_date.min()),
        "max_evaluation_outcome_date": str(max_outcome),
        "parameter_grid": grid_cells(),
        "coverage": {
            "total_ranked_shock_events": len(shock_panel),
            "event_range_by_cell": [int(ranked_counts.min()), int(ranked_counts.max())],
            "securities": int(shock_panel.symbol.nunique()),
            "industries": int(shock_panel.industry.nunique()),
            "dates": int(shock_panel.signal_date.nunique()),
        },
        "cell_coverage": coverage.to_dict("records"),
        "cell_topology": topology_table.to_dict("records"),
        "topology": topology_result,
        "control_target": control_target,
        "severity_control": severity,
        "generic_control": generic,
        "generic_fallback_counts": fallback_counts,
        "coarse_controls": coarse,
        "defensive_surface": defensive,
        "walk_forward_gate": gate,
        "walk_forward_selection_rule": spec["walk_forward_selection"],
        "walk_forward": walk_forward,
        "actionability_by_cell": actionability,
        "all_sample_actionability": all_actionability,
        "strategy_a_independence": independence,
        "final_classification": classification,
        "economic_interpretation": interpretation,
        "next_recommended_research_direction": next_direction,
        "input_identity": {
            "daily_partition_years": [2018, 2019, 2020, 2021, 2022, 2023],
            "raw_audit": raw_audit,
        },
        "external_artifacts": {
            "evaluation_panel": str(PANEL_PATH),
            "evaluation_panel_sha256": sha256_file(PANEL_PATH),
        },
        "artifacts": {
            "surface": str(SURFACE_PATH.relative_to(ROOT)),
            "surface_sha256": sha256_file(SURFACE_PATH),
            "report": str(REPORT_PATH.relative_to(ROOT)),
        },
    }
    _atomic_write(REPORT_PATH, _report(result, surface))
    result["artifacts"]["report_sha256"] = sha256_file(REPORT_PATH)
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "classification": classification,
                "stable_region": topology_result["stable_region"],
                "walk_forward_gate": gate["pass"],
                "events": len(shock_panel),
                "result_sha256": sha256_file(RESULT_PATH),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
