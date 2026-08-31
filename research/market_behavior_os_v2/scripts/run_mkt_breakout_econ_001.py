#!/usr/bin/env python3
"""Estimate the frozen objective-crossing level and transition market response."""

from __future__ import annotations

import hashlib
import json
import platform
import resource
import time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psutil

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-BREAKOUT-ECON-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_panel.csv"
LEVEL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_level_audit.csv"
YEAR_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_year_audit.csv"
EPISODE_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_episode_audit.csv"
TRANSITION_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_transition_audit.csv"
PLACEBO_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_placebo_audit.csv"
CONDITIONAL_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_conditional_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-BREAKOUT-ECON-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-BREAKOUT-ECON-001_response.md"
EXPECTED_SPEC_SHA256 = "278ec3834f4e62adc209c6c7f81b2abe5382679b1add636fc23a3b84fbd03fea"


class EconomicResponseError(RuntimeError):
    """Fail-closed objective-crossing economic-response error."""


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
        raise EconomicResponseError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if (
        spec["status"] != "FROZEN_BEFORE_STATE_RESPONSE_ESTIMATES"
        or spec["outcome_access"] != "FUTURE_PRE2024_MARKET_RETURN_AND_DOWNSIDE_ONLY"
    ):
        raise EconomicResponseError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise EconomicResponseError(f"input identity mismatch: {name}")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise EconomicResponseError("prohibited boundary changed")
    result = json.loads(_resolve(spec["inputs"]["response_result"]["path"]).read_text())
    if result["status"] != spec["activation"]["required_response_status"]:
        raise EconomicResponseError("response domain is not activated")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise EconomicResponseError("system memory headroom below frozen floor")
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise EconomicResponseError("process peak RSS ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60:
        raise EconomicResponseError("wall-clock ceiling breached")


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _median(values: list[float] | np.ndarray | pd.Series) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    return float(np.median(array)) if len(array) else float("nan")


def _spearman(x: pd.Series, y: pd.Series) -> float:
    frame = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(frame) < 3 or frame["x"].nunique() < 2 or frame["y"].nunique() < 2:
        return float("nan")
    return float(frame["x"].rank(method="average").corr(frame["y"].rank(method="average")))


def _summary(values: pd.Series | np.ndarray) -> dict[str, float | int]:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if len(array) == 0:
        return {key: float("nan") for key in ("mean", "median", "positive", "p10", "p90")} | {
            "n": 0
        }
    return {
        "n": int(len(array)),
        "mean": float(np.mean(array)),
        "median": float(np.median(array)),
        "positive": float(np.mean(array > 0)),
        "p10": float(np.quantile(array, 0.1)),
        "p90": float(np.quantile(array, 0.9)),
    }


def _tail_metrics(frame: pd.DataFrame, pit: str, outcome: str) -> dict[str, Any]:
    valid = frame[[pit, outcome]].dropna()
    low = valid.loc[valid[pit] <= 0.2, outcome]
    high = valid.loc[valid[pit] >= 0.8, outcome]
    low_summary = _summary(low)
    high_summary = _summary(high)
    effect = (
        float(high_summary["mean"]) - float(low_summary["mean"])
        if low_summary["n"] and high_summary["n"]
        else float("nan")
    )
    output: dict[str, Any] = {"tail_effect": effect}
    for prefix, values in (("low", low_summary), ("high", high_summary)):
        output.update({f"{prefix}_{key}": value for key, value in values.items()})
    return output


def _support_audit(state: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    raw_years = spec["activation"]["expected_raw_years"]
    pit_years = spec["activation"]["pit_supported_years"]
    zero_years = spec["activation"]["pit_zero_coverage_years"]
    roles: dict[str, str] = spec["roles"]
    cells: dict[str, Any] = {}
    all_pass = True
    for role, raw in roles.items():
        pit = f"{raw}_pit_3y_pct"
        role_cells: dict[str, Any] = {}
        for (view, denominator), group in state.groupby(
            ["market_view", "denominator"], sort=True
        ):
            counts = group.assign(year=group["trade_date"].dt.year).groupby("year")[pit].count()
            item = {
                "raw_years_present": sorted(group["trade_date"].dt.year.unique().tolist()),
                "pit_counts": {str(year): int(counts.get(year, 0)) for year in raw_years},
            }
            item["pass"] = (
                item["raw_years_present"] == raw_years
                and all(item["pit_counts"][str(year)] == 0 for year in zero_years)
                and all(item["pit_counts"][str(year)] >= 150 for year in pit_years)
            )
            all_pass &= item["pass"]
            role_cells[f"{view}:{denominator}"] = item
        cells[role] = role_cells
    if not all_pass:
        raise EconomicResponseError("causal PIT/raw support audit failed before response read")
    return {"all_pass": True, "cells": cells}


def _load_and_join(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    state = pd.read_csv(
        _resolve(spec["inputs"]["state_panel"]["path"]), parse_dates=["trade_date"]
    )
    support = _support_audit(state, spec)
    response = pd.read_csv(
        _resolve(spec["inputs"]["response_panel"]["path"]), parse_dates=["trade_date"]
    )
    response = response[response["response_complete"]].copy()
    breadth = pd.read_csv(
        _resolve(spec["inputs"]["breadth_panel"]["path"]), parse_dates=["trade_date"]
    )
    volatility = pd.read_csv(
        _resolve(spec["inputs"]["volatility_panel"]["path"]), parse_dates=["trade_date"]
    )
    keys = ["trade_date", "market_view", "denominator"]
    response_metrics = [
        column
        for column in response
        if column.startswith("terminal_") or column.startswith("adverse_")
    ]
    state_columns = keys + [
        field for raw in spec["roles"].values() for field in (raw, f"{raw}_pit_3y_pct")
    ]
    frame = state[state_columns].merge(
        response[keys + response_metrics], on=keys, how="inner", validate="one_to_one"
    )
    breadth_control = spec["conditional_controls"]["breadth"]
    volatility_control = spec["conditional_controls"]["volatility"]
    frame = frame.merge(
        breadth[keys + [breadth_control]], on=keys, how="left", validate="one_to_one"
    ).merge(
        volatility[keys + [volatility_control]],
        on=keys,
        how="left",
        validate="one_to_one",
    )
    if len(frame) != spec["activation"]["expected_joined_complete_rows"]:
        raise EconomicResponseError("joined response row count changed")
    frame["event_year"] = frame["trade_date"].dt.year
    date_order = {date: idx for idx, date in enumerate(sorted(frame["trade_date"].unique()))}
    frame["session_ordinal"] = frame["trade_date"].map(date_order).astype(int)
    frame = frame.sort_values(keys).reset_index(drop=True)
    return frame, support


def _outcome_fields(horizon: int) -> dict[str, str]:
    return {
        "terminal": f"terminal_mean_log_return_h{horizon}",
        "downside": f"adverse_mean_log_excursion_h{horizon}",
    }


def _level_audits(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    level_rows: list[dict[str, Any]] = []
    year_rows: list[dict[str, Any]] = []
    for role, raw in spec["roles"].items():
        pit = f"{raw}_pit_3y_pct"
        for (view, denominator), group in panel.groupby(
            ["market_view", "denominator"], sort=True
        ):
            group = group.sort_values("trade_date")
            for horizon in spec["outcomes"]["horizons"]:
                for outcome_kind, outcome in _outcome_fields(horizon).items():
                    for coordinate, state_column in (("absolute", raw), ("pit", pit)):
                        valid = group[[state_column, outcome]].dropna()
                        row = {
                            "role": role,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "overall",
                            "scope_value": "ALL",
                            "coordinate": coordinate,
                            "horizon": horizon,
                            "outcome": outcome_kind,
                            "n": int(len(valid)),
                            "spearman": _spearman(valid[state_column], valid[outcome]),
                        }
                        row.update(_tail_metrics(group, pit, outcome) if coordinate == "pit" else {})
                        level_rows.append(row)
                    for block, years in (
                        ("A", [2018, 2019, 2020]),
                        ("B", [2021, 2022, 2023]),
                    ):
                        subset = group[group["event_year"].isin(years)]
                        row = {
                            "role": role,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "block",
                            "scope_value": block,
                            "coordinate": "pit",
                            "horizon": horizon,
                            "outcome": outcome_kind,
                            "n": int(subset[[pit, outcome]].dropna().shape[0]),
                            "spearman": _spearman(subset[pit], subset[outcome]),
                        }
                        row.update(_tail_metrics(subset, pit, outcome))
                        level_rows.append(row)
                    for phase in range(horizon):
                        subset = group[group["session_ordinal"] % horizon == phase]
                        row = {
                            "role": role,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "phase",
                            "scope_value": str(phase),
                            "coordinate": "pit",
                            "horizon": horizon,
                            "outcome": outcome_kind,
                            "n": int(subset[[pit, outcome]].dropna().shape[0]),
                            "spearman": _spearman(subset[pit], subset[outcome]),
                        }
                        row.update(_tail_metrics(subset, pit, outcome))
                        level_rows.append(row)
                    for year, subset in group.groupby("event_year", sort=True):
                        for coordinate, state_column in (("absolute", raw), ("pit", pit)):
                            valid = subset[[state_column, outcome]].dropna()
                            row = {
                                "role": role,
                                "market_view": view,
                                "denominator": denominator,
                                "event_year": int(year),
                                "coordinate": coordinate,
                                "horizon": horizon,
                                "outcome": outcome_kind,
                                "n": int(len(valid)),
                                "spearman": _spearman(valid[state_column], valid[outcome]),
                            }
                            row.update(
                                _tail_metrics(subset, pit, outcome)
                                if coordinate == "pit"
                                else {}
                            )
                            year_rows.append(row)
    level = pd.DataFrame(level_rows)
    year = pd.DataFrame(year_rows)
    return level.sort_values(
        ["role", "market_view", "denominator", "horizon", "outcome", "scope", "scope_value", "coordinate"]
    ).reset_index(drop=True), year.sort_values(
        ["role", "market_view", "denominator", "event_year", "horizon", "outcome", "coordinate"]
    ).reset_index(drop=True)


def _episode_and_transition_audits(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    episode_rows: list[dict[str, Any]] = []
    effect_rows: list[dict[str, Any]] = []
    support: dict[str, Any] = {}
    for role, raw in spec["roles"].items():
        pit = f"{raw}_pit_3y_pct"
        role_match_counts: dict[str, dict[str, Any]] = {"UP": {}, "DOWN": {}}
        for (view, denominator), group in panel.groupby(
            ["market_view", "denominator"], sort=True
        ):
            group = group.sort_values("trade_date").reset_index(drop=True).copy()
            x = group[pit]
            group["raw_up"] = x.ge(0.5) & x.shift(1).lt(0.5)
            group["raw_down"] = x.lt(0.5) & x.shift(1).ge(0.5)
            group["episode_up"] = x.ge(0.5)
            group["episode_down"] = x.lt(0.5)
            for lag in range(1, 6):
                group["episode_up"] &= x.shift(lag).lt(0.5)
                group["episode_down"] &= x.shift(lag).ge(0.5)
            raw_any = (group["raw_up"] | group["raw_down"]).to_numpy(bool)
            near_cross = np.zeros(len(group), dtype=bool)
            for index in np.flatnonzero(raw_any):
                near_cross[max(0, index - 5) : min(len(group), index + 6)] = True
            group["near_cross"] = near_cross
            matched_dates: dict[str, list[pd.Timestamp]] = {"UP": [], "DOWN": []}
            event_effects: list[dict[str, Any]] = []
            for direction, episode_col, high_side in (
                ("UP", "episode_up", True),
                ("DOWN", "episode_down", False),
            ):
                events = group[group[episode_col]].copy()
                for event in events.itertuples(index=False):
                    candidates = group[
                        (~group["near_cross"])
                        & (~group["raw_up"])
                        & (~group["raw_down"])
                        & group[pit].notna()
                        & group["event_year"].eq(event.event_year)
                        & (group[pit].ge(0.5) if high_side else group[pit].lt(0.5))
                        & group[pit].sub(getattr(event, pit)).abs().le(
                            spec["matching"]["pit_caliper"]
                        )
                    ].copy()
                    candidates["distance"] = candidates[pit].sub(getattr(event, pit)).abs()
                    candidates = candidates.sort_values(["distance", "trade_date"]).head(
                        spec["matching"]["controls_per_event"]
                    )
                    if len(candidates) == 0:
                        continue
                    matched_dates[direction].append(event.trade_date)
                    for horizon in spec["outcomes"]["horizons"]:
                        for outcome_kind, outcome in _outcome_fields(horizon).items():
                            value = float(getattr(event, outcome)) - float(candidates[outcome].mean())
                            event_effects.append(
                                {
                                    "direction": direction,
                                    "event_year": int(event.event_year),
                                    "horizon": horizon,
                                    "outcome": outcome_kind,
                                    "effect": value,
                                }
                            )
                counts = (
                    pd.to_datetime(pd.Series(matched_dates[direction])).dt.year.value_counts()
                    if matched_dates[direction]
                    else pd.Series(dtype=int)
                )
                role_match_counts[direction][f"{view}:{denominator}"] = {
                    "total": len(matched_dates[direction]),
                    "by_year": {
                        str(year): int(counts.get(year, 0))
                        for year in spec["activation"]["expected_raw_years"]
                    },
                }
            for year, yearly in group.groupby("event_year", sort=True):
                episode_rows.append(
                    {
                        "role": role,
                        "market_view": view,
                        "denominator": denominator,
                        "event_year": int(year),
                        "pit_observations": int(yearly[pit].notna().sum()),
                        "raw_up_crossings": int(yearly["raw_up"].sum()),
                        "raw_down_crossings": int(yearly["raw_down"].sum()),
                        "declustered_up_episodes": int(yearly["episode_up"].sum()),
                        "declustered_down_episodes": int(yearly["episode_down"].sum()),
                        "matched_up_episodes": int(
                            sum(date.year == year for date in matched_dates["UP"])
                        ),
                        "matched_down_episodes": int(
                            sum(date.year == year for date in matched_dates["DOWN"])
                        ),
                    }
                )
            event_frame = pd.DataFrame(event_effects)
            if not event_frame.empty:
                for (direction, horizon, outcome), values in event_frame.groupby(
                    ["direction", "horizon", "outcome"], sort=True
                ):
                    stats = _summary(values["effect"])
                    effect_rows.append(
                        {
                            "role": role,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "overall",
                            "scope_value": "ALL",
                            "direction": direction,
                            "horizon": horizon,
                            "outcome": outcome,
                            **stats,
                        }
                    )
                for (direction, year, horizon, outcome), values in event_frame.groupby(
                    ["direction", "event_year", "horizon", "outcome"], sort=True
                ):
                    stats = _summary(values["effect"])
                    effect_rows.append(
                        {
                            "role": role,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "year",
                            "scope_value": str(year),
                            "direction": direction,
                            "horizon": horizon,
                            "outcome": outcome,
                            **stats,
                        }
                    )
        role_support: dict[str, Any] = {}
        for direction, cells in role_match_counts.items():
            cells_25 = sum(item["total"] >= 25 for item in cells.values())
            year_minimums = {
                str(year): min(item["by_year"][str(year)] for item in cells.values())
                for year in spec["activation"]["expected_raw_years"]
            }
            years_5 = sum(count >= 5 for count in year_minimums.values())
            passed = cells_25 >= 6 and years_5 >= 5
            role_support[direction] = {
                "cells_with_at_least_25": cells_25,
                "years_with_minimum_cell_count_at_least_5": years_5,
                "minimum_cell_count_by_year": year_minimums,
                "pass": passed,
                "status": (
                    "SUPPORTED" if passed else spec["episodes"]["support_failure_status"]
                ),
            }
        support[role] = role_support
    episode = pd.DataFrame(episode_rows).sort_values(
        ["role", "market_view", "denominator", "event_year"]
    )
    transition = pd.DataFrame(effect_rows)
    if not transition.empty:
        transition = transition.sort_values(
            ["role", "market_view", "denominator", "direction", "horizon", "outcome", "scope", "scope_value"]
        )
    return episode.reset_index(drop=True), transition.reset_index(drop=True), support


def _group_median(
    audit: pd.DataFrame,
    role: str,
    horizon: int,
    outcome: str,
    field: str,
    **filters: Any,
) -> float:
    subset = audit[
        audit["role"].eq(role)
        & audit["horizon"].eq(horizon)
        & audit["outcome"].eq(outcome)
    ]
    for column, value in filters.items():
        subset = subset[subset[column].eq(value)]
    return _median(subset[field])


def _level_preclassification(
    level: pd.DataFrame, year: pd.DataFrame, panel: pd.DataFrame, spec: dict[str, Any]
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    gate = spec["level_gate"]
    pit_years = spec["activation"]["pit_supported_years"]
    raw_years = spec["activation"]["expected_raw_years"]
    for role, raw in spec["roles"].items():
        role_result: dict[str, Any] = {}
        pit = f"{raw}_pit_3y_pct"
        for outcome in ("terminal", "downside"):
            base = level[
                level["role"].eq(role)
                & level["horizon"].eq(3)
                & level["outcome"].eq(outcome)
                & level["scope"].eq("overall")
            ]
            pit_cells = base[base["coordinate"].eq("pit")]
            raw_cells = base[base["coordinate"].eq("absolute")]
            effect = _median(pit_cells["tail_effect"])
            pit_rho = _median(pit_cells["spearman"])
            raw_rho = _median(raw_cells["spearman"])
            sign = _sign(effect)
            cell_signs = int(sum(_sign(value) == sign for value in pit_cells["tail_effect"]))
            block_signs = []
            for block in ("A", "B"):
                block_signs.append(
                    _sign(
                        _group_median(
                            level,
                            role,
                            3,
                            outcome,
                            "tail_effect",
                            scope="block",
                            scope_value=block,
                            coordinate="pit",
                        )
                    )
                )
            raw_year_signs = []
            pit_year_signs = []
            for event_year in raw_years:
                rows = year[
                    year["role"].eq(role)
                    & year["event_year"].eq(event_year)
                    & year["horizon"].eq(3)
                    & year["outcome"].eq(outcome)
                ]
                raw_year_signs.append(_sign(_median(rows[rows["coordinate"].eq("absolute")]["spearman"])))
                if event_year in pit_years:
                    pit_year_signs.append(_sign(_median(rows[rows["coordinate"].eq("pit")]["tail_effect"])))
            raw_loo_signs = []
            for omitted in raw_years:
                values = []
                for _, group in panel[panel["event_year"].ne(omitted)].groupby(
                    ["market_view", "denominator"], sort=True
                ):
                    values.append(_spearman(group[raw], group[_outcome_fields(3)[outcome]]))
                raw_loo_signs.append(_sign(_median(values)))
            pit_loo_signs = []
            for omitted in pit_years:
                values = []
                for _, group in panel[panel["event_year"].ne(omitted)].groupby(
                    ["market_view", "denominator"], sort=True
                ):
                    values.append(
                        _tail_metrics(group, pit, _outcome_fields(3)[outcome])["tail_effect"]
                    )
                pit_loo_signs.append(_sign(_median(values)))
            neighbor_signs = {
                str(horizon): _sign(
                    _group_median(
                        level,
                        role,
                        horizon,
                        outcome,
                        "tail_effect",
                        scope="overall",
                        scope_value="ALL",
                        coordinate="pit",
                    )
                )
                for horizon in (1, 5)
            }
            phase_support = {}
            for horizon, required in ((3, 2), (5, 4)):
                signs = []
                for phase in range(horizon):
                    signs.append(
                        _sign(
                            _group_median(
                                level,
                                role,
                                horizon,
                                outcome,
                                "tail_effect",
                                scope="phase",
                                scope_value=str(phase),
                                coordinate="pit",
                            )
                        )
                    )
                phase_support[str(horizon)] = {
                    "signs": signs,
                    "same_sign": sum(item == sign for item in signs),
                    "required": required,
                }
            size_pass = bool(
                np.isfinite(effect)
                and abs(effect) >= gate["minimum_absolute_h3_effect"]
                and np.isfinite(pit_rho)
                and abs(pit_rho) >= gate["minimum_absolute_median_cell_pit_spearman"]
            )
            portability_pass = bool(
                sign != 0
                and _sign(pit_rho) == sign
                and _sign(raw_rho) == sign
                and cell_signs >= gate["minimum_same_sign_cells"]
                and all(item == sign for item in block_signs)
                and sum(item == sign for item in raw_year_signs)
                >= gate["minimum_same_sign_raw_years"]
                and all(item == sign for item in pit_year_signs)
                and all(item == sign for item in raw_loo_signs)
                and all(item == sign for item in pit_loo_signs)
                and all(item == sign for item in neighbor_signs.values())
                and phase_support["3"]["same_sign"] >= phase_support["3"]["required"]
                and phase_support["5"]["same_sign"] >= phase_support["5"]["required"]
            )
            role_result[outcome] = {
                "h3_median_tail_effect": effect,
                "h3_median_pit_spearman": pit_rho,
                "h3_median_raw_spearman": raw_rho,
                "effect_sign": sign,
                "same_sign_cells": cell_signs,
                "block_signs": block_signs,
                "raw_year_signs": raw_year_signs,
                "pit_supported_year_signs": pit_year_signs,
                "raw_leave_one_year_out_signs": raw_loo_signs,
                "pit_leave_one_supported_year_out_signs": pit_loo_signs,
                "neighbor_signs": neighbor_signs,
                "phase_support": phase_support,
                "size_pass": size_pass,
                "portability_pass": portability_pass,
                "unconditioned_candidate": size_pass and portability_pass,
            }
        output[role] = role_result
    return output


def _placebo_audit(
    panel: pd.DataFrame, preclassification: dict[str, Any], spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, float]]:
    rows: list[dict[str, Any]] = []
    p_values: dict[str, float] = {}
    replicates = int(spec["placebo"]["replicates"])
    for role, raw in spec["roles"].items():
        pit = f"{raw}_pit_3y_pct"
        actual_return = abs(preclassification[role]["terminal"]["h3_median_tail_effect"])
        actual_downside = abs(preclassification[role]["downside"]["h3_median_tail_effect"])
        actual = max(actual_return, actual_downside)
        null_stats: list[float] = []
        groups = list(panel.groupby(["market_view", "denominator"], sort=True))
        for replicate in range(replicates):
            return_effects: list[float] = []
            downside_effects: list[float] = []
            for (view, denominator), group in groups:
                group = group.sort_values("trade_date").copy()
                shifted = pd.Series(np.nan, index=group.index, dtype=float)
                for year, yearly in group.groupby("event_year", sort=True):
                    valid_index = yearly.index[yearly[pit].notna()]
                    n = len(valid_index)
                    if n < 41:
                        continue
                    material = f"MKT-BREAKOUT-ECON-001|{role}|{view}|{denominator}|{year}|{replicate}"
                    seed = int(hashlib.sha256(material.encode()).hexdigest(), 16)
                    offset = 20 + seed % (n - 39)
                    shifted.loc[valid_index] = np.roll(group.loc[valid_index, pit].to_numpy(), offset)
                placebo = group.assign(placebo_pit=shifted)
                return_effects.append(
                    _tail_metrics(placebo, "placebo_pit", "terminal_mean_log_return_h3")[
                        "tail_effect"
                    ]
                )
                downside_effects.append(
                    _tail_metrics(placebo, "placebo_pit", "adverse_mean_log_excursion_h3")[
                        "tail_effect"
                    ]
                )
            statistic = max(abs(_median(return_effects)), abs(_median(downside_effects)))
            null_stats.append(statistic)
            rows.append(
                {
                    "role": role,
                    "family": "level",
                    "replicate": replicate,
                    "null_statistic": statistic,
                }
            )
        p_values[role] = (1 + sum(value >= actual for value in null_stats)) / (replicates + 1)
    order = sorted(p_values, key=p_values.get)
    q_values: dict[str, float] = {}
    running = 1.0
    m = len(order)
    for reverse_index in range(m - 1, -1, -1):
        role = order[reverse_index]
        rank = reverse_index + 1
        running = min(running, p_values[role] * m / rank)
        q_values[role] = running
    audit = pd.DataFrame(rows)
    summary_rows = [
        {
            "role": role,
            "family": "level_summary",
            "replicate": -1,
            "null_statistic": float("nan"),
            "empirical_p": p_values[role],
            "bh_q": q_values[role],
        }
        for role in spec["roles"]
    ]
    audit = pd.concat([audit, pd.DataFrame(summary_rows)], ignore_index=True)
    return audit.sort_values(["role", "family", "replicate"]).reset_index(drop=True), q_values


def _partial_rho(frame: pd.DataFrame, state: str, response: str, controls: list[str]) -> float:
    data = frame[[state, response] + controls].dropna()
    if len(data) < 30:
        return float("nan")
    ranked = data.rank(method="average")
    x = np.column_stack([np.ones(len(ranked))] + [ranked[column].to_numpy() for column in controls])
    state_residual = ranked[state].to_numpy() - x @ np.linalg.lstsq(
        x, ranked[state].to_numpy(), rcond=None
    )[0]
    response_residual = ranked[response].to_numpy() - x @ np.linalg.lstsq(
        x, ranked[response].to_numpy(), rcond=None
    )[0]
    if np.std(state_residual) == 0 or np.std(response_residual) == 0:
        return float("nan")
    return float(np.corrcoef(state_residual, response_residual)[0, 1])


def _conditional_audit(
    panel: pd.DataFrame, preclassification: dict[str, Any], spec: dict[str, Any]
) -> tuple[pd.DataFrame, dict[str, dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    decisions: dict[str, dict[str, Any]] = {}
    controls = [
        spec["conditional_controls"]["breadth"],
        spec["conditional_controls"]["volatility"],
    ]
    for role, raw in spec["roles"].items():
        pit = f"{raw}_pit_3y_pct"
        decisions[role] = {}
        for outcome in ("terminal", "downside"):
            candidate = preclassification[role][outcome]["unconditioned_candidate"]
            if not candidate:
                decisions[role][outcome] = {"estimated": False, "pass": False}
                continue
            response = _outcome_fields(3)[outcome]
            cell_values = []
            block_values: dict[str, list[float]] = {"A": [], "B": []}
            for (view, denominator), group in panel.groupby(
                ["market_view", "denominator"], sort=True
            ):
                rho = _partial_rho(group, pit, response, controls)
                cell_values.append(rho)
                rows.append(
                    {
                        "role": role,
                        "outcome": outcome,
                        "market_view": view,
                        "denominator": denominator,
                        "scope": "overall",
                        "scope_value": "ALL",
                        "n": int(group[[pit, response] + controls].dropna().shape[0]),
                        "partial_rho": rho,
                    }
                )
                for block, years in (("A", [2018, 2019, 2020]), ("B", [2021, 2022, 2023])):
                    subset = group[group["event_year"].isin(years)]
                    block_rho = _partial_rho(subset, pit, response, controls)
                    block_values[block].append(block_rho)
                    rows.append(
                        {
                            "role": role,
                            "outcome": outcome,
                            "market_view": view,
                            "denominator": denominator,
                            "scope": "block",
                            "scope_value": block,
                            "n": int(subset[[pit, response] + controls].dropna().shape[0]),
                            "partial_rho": block_rho,
                        }
                    )
            sign = preclassification[role][outcome]["effect_sign"]
            median_rho = _median(cell_values)
            passed = bool(
                abs(median_rho)
                >= spec["conditional_controls"]["minimum_absolute_median_partial_rho"]
                and sum(_sign(value) == sign for value in cell_values)
                >= spec["conditional_controls"]["minimum_same_sign_cells"]
                and all(_sign(_median(values)) == sign for values in block_values.values())
            )
            decisions[role][outcome] = {
                "estimated": True,
                "median_partial_rho": median_rho,
                "same_sign_cells": sum(_sign(value) == sign for value in cell_values),
                "block_signs": {
                    block: _sign(_median(values)) for block, values in block_values.items()
                },
                "pass": passed,
            }
    columns = [
        "role",
        "outcome",
        "market_view",
        "denominator",
        "scope",
        "scope_value",
        "n",
        "partial_rho",
    ]
    audit = pd.DataFrame(rows, columns=columns)
    if not audit.empty:
        audit = audit.sort_values(
            ["role", "outcome", "market_view", "denominator", "scope", "scope_value"]
        )
    return audit.reset_index(drop=True), decisions


def _classify(
    preclassification: dict[str, Any],
    q_values: dict[str, float],
    conditional: dict[str, dict[str, Any]],
    transition_support: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for role in spec["roles"]:
        q_pass = q_values[role] <= spec["level_gate"]["maximum_placebo_q"]
        return_unconditioned = preclassification[role]["terminal"]["unconditioned_candidate"]
        downside_unconditioned = preclassification[role]["downside"]["unconditioned_candidate"]
        return_supported = return_unconditioned and q_pass and conditional[role]["terminal"]["pass"]
        downside_supported = (
            downside_unconditioned and q_pass and conditional[role]["downside"]["pass"]
        )
        any_size = preclassification[role]["terminal"]["size_pass"] or preclassification[role][
            "downside"
        ]["size_pass"]
        if return_supported:
            status = "LEVEL_ECONOMIC_RESPONSE"
        elif downside_supported:
            status = "TAIL_RISK_RESPONSE"
        elif any_size:
            status = "UNSTABLE_ECONOMIC_RESPONSE"
        else:
            status = "NO_ECONOMIC_RESPONSE"
        output[role] = {
            "status": status,
            "retained_tier": (
                "SUPPORTED_MARKET_STATE"
                if return_supported or downside_supported
                else "DESCRIPTIVE_ONLY"
            ),
            "return_supported": return_supported,
            "downside_supported": downside_supported,
            "conditional_response": return_supported or downside_supported,
            "level_placebo_q": q_values[role],
            "transition": transition_support[role],
            "transition_incremental_response": False,
            "transition_placebo_run": False,
            "preclassification": preclassification[role],
            "conditional": conditional[role],
        }
    return output


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# MKT-BREAKOUT-ECON-001 economic market response",
        "",
        f"Status: **{result['status']}**.",
        "",
        "This is pre-2024 strategy-independent market behavior. It is not a trading rule, "
        "strategy habitat, causal claim, or execution backtest.",
        "",
        "## Role decisions",
        "",
        "| role | status | retained tier | h3 return effect | h3 downside effect | placebo q | transition |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for role, item in result["classifications"].items():
        pre = item["preclassification"]
        transition_statuses = sorted(
            {value["status"] for value in item["transition"].values()}
        )
        lines.append(
            f"| {role} | {item['status']} | {item['retained_tier']} | "
            f"{pre['terminal']['h3_median_tail_effect']:.6f} | "
            f"{pre['downside']['h3_median_tail_effect']:.6f} | "
            f"{item['level_placebo_q']:.4f} | {','.join(transition_statuses)} |"
        )
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            f"Supported market states: {', '.join(result['supported_market_states']) or 'none'}.",
            f"Descriptive-only states: {', '.join(result['descriptive_only_states']) or 'none'}.",
            "Up/down transition incrementality was not promoted unless the fixed episode "
            "support gate passed; insufficient support is not interpreted as no effect.",
            "",
            "CY-011, post-2023 data, strategy outcomes, fills, P&L, and CHINEXT habitat "
            "fields were not read.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_outputs(
    panel: pd.DataFrame,
    level: pd.DataFrame,
    year: pd.DataFrame,
    episode: pd.DataFrame,
    transition: pd.DataFrame,
    placebo: pd.DataFrame,
    conditional: pd.DataFrame,
    result_without_hashes: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    outputs = {
        PANEL_PATH: panel,
        LEVEL_PATH: level,
        YEAR_PATH: year,
        EPISODE_PATH: episode,
        TRANSITION_PATH: transition,
        PLACEBO_PATH: placebo,
        CONDITIONAL_PATH: conditional,
    }
    for path, frame in outputs.items():
        frame.to_csv(path, index=False, float_format="%.17g", lineterminator="\n")
    result = dict(result_without_hashes)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "runner_sha256": sha256_file(Path(__file__)),
        **{path.stem + "_sha256": sha256_file(path) for path in outputs},
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable = sum(path.stat().st_size for path in list(outputs) + [RESULT_PATH, REPORT_PATH])
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise EconomicResponseError("durable output ceiling breached")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    _resource_guard(spec, started)
    panel, support_audit = _load_and_join(spec)
    _resource_guard(spec, started)
    level, year = _level_audits(panel, spec)
    episode, transition, transition_support = _episode_and_transition_audits(panel, spec)
    preclassification = _level_preclassification(level, year, panel, spec)
    placebo, q_values = _placebo_audit(panel, preclassification, spec)
    conditional, conditional_decisions = _conditional_audit(panel, preclassification, spec)
    classifications = _classify(
        preclassification, q_values, conditional_decisions, transition_support, spec
    )
    supported = [
        role for role, item in classifications.items() if item["retained_tier"] == "SUPPORTED_MARKET_STATE"
    ]
    descriptive = [
        role for role, item in classifications.items() if item["retained_tier"] == "DESCRIPTIVE_ONLY"
    ]
    status = (
        "COMPLETE_SUPPORTED_MARKET_STATE_RESPONSE"
        if supported
        else "COMPLETE_SEVEN_DESCRIPTIVE_ONLY_NO_REPRODUCIBLE_ECONOMIC_RESPONSE"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": "ECONOMIC_MARKET_BEHAVIOR_ONLY",
        "support_audit": support_audit,
        "classifications": classifications,
        "supported_market_states": supported,
        "descriptive_only_states": descriptive,
        "habitat_frontier_open": bool(supported),
        "transition_support_all_roles": transition_support,
        "population": {
            "joined_complete_rows": int(len(panel)),
            "groups": int(panel.groupby(["market_view", "denominator"]).ngroups),
            "first_date": panel["trade_date"].min().strftime("%Y-%m-%d"),
            "last_event_date": panel["trade_date"].max().strftime("%Y-%m-%d"),
        },
        "outcome_access": spec["outcome_access"],
        "strategy_fields_read": [],
        "post_2023_read": False,
        "cy011_read": False,
        "resource_contract": {
            "status": "PASS",
            "peak_rss_ceiling_gib": spec["resource_budget"]["peak_rss_ceiling_gib"],
            "wall_clock_ceiling_minutes": spec["resource_budget"][
                "wall_clock_ceiling_minutes"
            ],
            "dynamic_measurements_serialized": False,
        },
    }
    panel_output = panel.copy()
    panel_output["trade_date"] = panel_output["trade_date"].dt.strftime("%Y-%m-%d")
    _write_outputs(
        panel_output,
        level,
        year,
        episode,
        transition,
        placebo,
        conditional,
        result,
        spec,
    )
    _resource_guard(spec, started)


if __name__ == "__main__":
    main()
