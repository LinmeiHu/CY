#!/usr/bin/env python3
"""Execute frozen continuous volatility transition and habitat analysis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-VOL-TRANS-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-VOL-TRANS-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-VOL-TRANS-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "21145136eeb09369b755aad7fca591dcd280e3577159d7c65c5c1362bdacbb43"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")
MODIFIER_COORDINATES = ("raw", "pit")
BLOCK_NAMES = ("block_a_reused", "block_b_reused")
SPLIT_NAMES = ("primary", "shape_neighbor")


class VolatilityTransitionError(RuntimeError):
    """Fail-closed MKT-VOL-TRANS-001 error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


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
        raise VolatilityTransitionError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_VOLATILITY_STATE_CONSTRUCTION":
        raise VolatilityTransitionError("spec is not frozen before future-state construction")
    if spec["population"]["future_shift_sessions"] != 25:
        raise VolatilityTransitionError("nonoverlap response horizon changed")
    if list(spec["habitat_modifiers"]) != ["direction", "discovery"]:
        raise VolatilityTransitionError("modifier identity/order mismatch")
    return spec


def _field(raw: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def _response_name(coordinate: str) -> str:
    return f"future_volatility_change5_t25__{coordinate}"


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise VolatilityTransitionError(f"{name} identity mismatch")
        output[name] = path
    return output


def _validate_source_results(spec: dict[str, Any], paths: dict[str, Path]) -> None:
    volatility = json.loads(paths["volatility_result"].read_text(encoding="utf-8"))
    if volatility["minimal_panel"]["accepted_roles"] != spec["prerequisite"][
        "accepted_volatility_roles"
    ]:
        raise VolatilityTransitionError("accepted volatility roles changed")
    if volatility["usefulness_claim"] != "NONE" or volatility["strategy_or_future_fields_read"]:
        raise VolatilityTransitionError("volatility source boundary changed")
    breadth = json.loads(paths["breadth_result"].read_text(encoding="utf-8"))
    if spec["prerequisite"]["accepted_breadth_role"] not in breadth["minimal_panel"][
        "accepted_roles"
    ]:
        raise VolatilityTransitionError("discovery breadth is not accepted")
    if breadth["usefulness_claim"] != "NONE" or breadth["strategy_or_outcome_fields_read"]:
        raise VolatilityTransitionError("breadth source boundary changed")
    trend = json.loads(paths["trend_result"].read_text(encoding="utf-8"))
    role = spec["prerequisite"]["accepted_trend_representation"]
    if not trend["role_diagnostics"][role]["construction_gate_pass"]:
        raise VolatilityTransitionError("direction representation is not accepted")
    if trend["outcome_fields_read"]:
        raise VolatilityTransitionError("trend source boundary changed")


def _volatility_fields(spec: dict[str, Any]) -> list[str]:
    raw_names = [
        spec["fields"][name]
        for name in (
            "volatility_change",
            "realized_volatility_level",
            "intraday_range_level",
            "volatility_concentration",
        )
    ]
    return list(dict.fromkeys(
        _field(raw, coordinate) for raw in raw_names for coordinate in COORDINATES
    ))


def load_bound_inputs(
    spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    paths = _input_paths(spec)
    _validate_source_results(spec, paths)
    volatility = pd.read_csv(
        paths["volatility_panel"],
        usecols=[*KEYS, "decision_at", *_volatility_fields(spec)],
    ).rename(columns={"decision_at": "volatility_decision_at"})
    discovery_raw = spec["fields"]["discovery"]
    breadth = pd.read_csv(
        paths["breadth_panel"],
        usecols=[*KEYS, "decision_at", discovery_raw, _field(discovery_raw, "pit")],
    ).rename(columns={"decision_at": "breadth_decision_at"})
    population = spec["population"]
    for name, frame in (("volatility", volatility), ("breadth", breadth)):
        if len(frame) != population["base_rows"] or frame.duplicated(KEYS).any():
            raise VolatilityTransitionError(f"{name} row/key identity mismatch")
    base = volatility.merge(breadth, on=KEYS, how="inner", validate="one_to_one")
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="raise")
    if str(base["trade_date"].min().date()) != population["date_start"]:
        raise VolatilityTransitionError("base start changed")
    if str(base["trade_date"].max().date()) != population["date_end"]:
        raise VolatilityTransitionError("base end changed")
    if not (base["volatility_decision_at"] == base["breadth_decision_at"]).all():
        raise VolatilityTransitionError("volatility/breadth availability mismatch")
    decision = pd.to_datetime(
        base["volatility_decision_at"], errors="raise", utc=True
    ).dt.tz_convert("Asia/Shanghai")
    if not (decision.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise VolatilityTransitionError("base decision time is not exact 15:00")
    if not (decision.dt.date == base["trade_date"].dt.date).all():
        raise VolatilityTransitionError("base decision date mismatch")
    counts = base.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not (counts == population["rows_per_base_group"]).all():
        raise VolatilityTransitionError("base group population mismatch")

    direction_raw = spec["fields"]["direction"]
    trend = pd.read_csv(
        paths["trend_panel"],
        usecols=[
            "trade_date",
            "index_symbol",
            "decision_at",
            direction_raw,
            _field(direction_raw, "pit"),
        ],
    ).rename(columns={"decision_at": "trend_decision_at"})
    trend["trade_date"] = pd.to_datetime(trend["trade_date"], errors="raise")
    trend = trend.loc[
        trend["trade_date"].between(base["trade_date"].min(), base["trade_date"].max())
    ].copy()
    if trend.duplicated(["trade_date", "index_symbol"]).any():
        raise VolatilityTransitionError("trend duplicate key")
    if set(trend["index_symbol"]) != set(population["direction_indices"]):
        raise VolatilityTransitionError("trend index identity mismatch")
    trend_counts = trend.groupby("index_symbol", sort=True).size()
    if not (trend_counts == population["rows_per_base_group"]).all():
        raise VolatilityTransitionError("trend index population mismatch")
    trend_decision = pd.to_datetime(
        trend["trend_decision_at"], errors="raise", utc=True
    ).dt.tz_convert("Asia/Shanghai")
    if not (trend_decision.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise VolatilityTransitionError("trend decision time is not exact 15:00")
    if not (trend_decision.dt.date == trend["trade_date"].dt.date).all():
        raise VolatilityTransitionError("trend decision date mismatch")
    return (
        base.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True),
        trend.sort_values(["index_symbol", "trade_date"]).reset_index(drop=True),
    )


def construct_future_state(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    shift = int(spec["population"]["future_shift_sessions"])
    out = panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    grouped = out.groupby(["market_view", "denominator"], sort=False)
    out["future_trade_date"] = grouped["trade_date"].shift(-shift)
    out["response_available_at"] = out["future_trade_date"].dt.strftime(
        "%Y-%m-%dT15:00:00+08:00"
    )
    raw = spec["fields"]["volatility_change"]
    for coordinate in COORDINATES:
        out[_response_name(coordinate)] = grouped[_field(raw, coordinate)].shift(-shift)
    if int(out["future_trade_date"].isna().sum()) != shift * 8:
        raise VolatilityTransitionError("future tail count mismatch")
    predictor_time = pd.to_datetime(out["volatility_decision_at"], errors="raise", utc=True)
    response_time = pd.to_datetime(out["response_available_at"], errors="coerce", utc=True)
    if not (response_time.dropna() > predictor_time.loc[response_time.notna()]).all():
        raise VolatilityTransitionError("response is not strictly later than predictor")
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        if not group["future_trade_date"].equals(group["trade_date"].shift(-shift)):
            raise VolatilityTransitionError("future date is not exact twenty-five-row shift")
    return out.sort_values(KEYS).reset_index(drop=True)


def _block_frame(panel: pd.DataFrame, spec: dict[str, Any], block_name: str) -> pd.DataFrame:
    block = spec["temporal_blocks"][block_name]
    start, end = pd.Timestamp(block["start"]), pd.Timestamp(block["end"])
    return panel.loc[
        panel["trade_date"].between(start, end)
        & panel["future_trade_date"].between(start, end)
    ].copy()


def partial_rank_correlation(
    frame: pd.DataFrame, predictor: str, response: str, controls: list[str]
) -> tuple[float, int]:
    clean = frame[[predictor, response, *controls]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(clean) <= len(controls) + 3:
        return float("nan"), int(len(clean))
    ranked = clean.rank(method="average", pct=True).to_numpy(dtype=float)
    design = np.column_stack([np.ones(len(ranked), dtype=float), ranked[:, 2:]])
    predictor_residual = ranked[:, 0] - design @ np.linalg.lstsq(
        design, ranked[:, 0], rcond=None
    )[0]
    response_residual = ranked[:, 1] - design @ np.linalg.lstsq(
        design, ranked[:, 1], rcond=None
    )[0]
    if np.std(predictor_residual) == 0.0 or np.std(response_residual) == 0.0:
        return float("nan"), int(len(clean))
    return float(np.corrcoef(predictor_residual, response_residual)[0, 1]), int(len(clean))


def _analysis_groups(frame: pd.DataFrame, coordinate: str) -> list[tuple[str, pd.DataFrame]]:
    work = frame
    if coordinate == "relative_to_all":
        work = work.loc[work["market_view"] != "ALL_A"]
    if coordinate.startswith("relative"):
        return [
            (str(denominator), group)
            for denominator, group in work.groupby("denominator", sort=True)
        ]
    return [
        (f"{view}:{denominator}", group)
        for (view, denominator), group in work.groupby(
            ["market_view", "denominator"], sort=True
        )
    ]


def _minimum_support(spec: dict[str, Any], coordinate: str) -> int:
    if coordinate == "raw":
        return spec["gates"]["raw_group_block_minimum_observations"]
    if coordinate == "pit":
        return spec["gates"]["pit_group_block_minimum_observations"]
    if coordinate == "relative_to_all":
        return spec["gates"]["relative_to_all_denominator_block_minimum_observations"]
    return spec["gates"]["relative_rank_denominator_block_minimum_observations"]


def _baseline_fields(spec: dict[str, Any], coordinate: str) -> tuple[str, str, list[str]]:
    edge = spec["baseline_edge"]
    predictor = _field(spec["fields"][edge["predictor"]], coordinate)
    response = _response_name(coordinate)
    controls = [_field(spec["fields"][name], coordinate) for name in edge["controls"]]
    return predictor, response, controls


def _phase_sample(frame: pd.DataFrame, required: list[str], stride: int) -> pd.DataFrame:
    valid = frame.dropna(subset=required).sort_values(KEYS).copy()
    ordinal = valid.groupby(["market_view", "denominator"], sort=False).cumcount()
    return valid.loc[ordinal % stride == 0].copy()


def _baseline_estimate(
    frame: pd.DataFrame, spec: dict[str, Any], coordinate: str
) -> dict[str, Any]:
    predictor, response, controls = _baseline_fields(spec, coordinate)
    required = [predictor, response, *controls]
    primary: dict[str, float] = {}
    support: dict[str, int] = {}
    phase: dict[str, float] = {}
    phase_support: dict[str, int] = {}
    stride = int(spec["population"]["phase_stride"])
    for group_name, group in _analysis_groups(frame, coordinate):
        rho, observations = partial_rank_correlation(group, predictor, response, controls)
        if observations < _minimum_support(spec, coordinate) or not np.isfinite(rho):
            raise VolatilityTransitionError(
                f"baseline support/estimate failed: {coordinate}:{group_name}:{observations}"
            )
        primary[group_name] = rho
        support[group_name] = observations
        phase_group = _phase_sample(group, required, stride)
        phase_rho, phase_observations = partial_rank_correlation(
            phase_group, predictor, response, controls
        )
        if phase_observations <= len(controls) + 3 or not np.isfinite(phase_rho):
            raise VolatilityTransitionError(
                f"baseline phase failed: {coordinate}:{group_name}:{phase_observations}"
            )
        phase[group_name] = phase_rho
        phase_support[group_name] = phase_observations
    values = np.asarray(list(primary.values()), dtype=float)
    phase_values = np.asarray(list(phase.values()), dtype=float)
    median = float(np.median(values))
    sign = int(np.sign(median))
    return {
        "by_group": primary,
        "support_by_group": support,
        "median_partial_rho": median,
        "median_absolute_partial_rho": float(np.median(np.abs(values))),
        "median_sign": sign,
        "group_sign_support": int(np.sum(np.sign(values) == sign)),
        "phase_by_group": phase,
        "phase_support_by_group": phase_support,
        "phase_median_partial_rho": float(np.median(phase_values)),
        "phase_median_absolute_partial_rho": float(np.median(np.abs(phase_values))),
    }


def _baseline_gate(spec: dict[str, Any], blocks: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    block_a = blocks["block_a_reused"]
    block_b = blocks["block_b_reused"]
    raw_sign = block_a["raw"]["median_sign"]
    checks: dict[str, bool] = {
        "block_a_raw_effect": block_a["raw"]["median_absolute_partial_rho"] >= gates[
            "baseline_raw_median_absolute_partial_rho_minimum"
        ],
        "block_b_raw_effect": block_b["raw"]["median_absolute_partial_rho"] >= gates[
            "baseline_raw_median_absolute_partial_rho_minimum"
        ],
        "raw_sign_replication": raw_sign != 0 and block_b["raw"]["median_sign"] == raw_sign,
        "raw_block_b_magnitude": block_b["raw"]["median_absolute_partial_rho"] >= gates[
            "baseline_block_b_to_block_a_magnitude_ratio_minimum"
        ] * block_a["raw"]["median_absolute_partial_rho"],
    }
    for block_name in BLOCK_NAMES:
        block = blocks[block_name]
        checks[f"{block_name}:raw_sign_support"] = block["raw"]["group_sign_support"] >= gates[
            "baseline_group_sign_support_minimum_of_8"
        ]
        checks[f"{block_name}:phase_effect"] = block["raw"][
            "phase_median_absolute_partial_rho"
        ] >= gates["baseline_phase_median_absolute_partial_rho_minimum"]
        checks[f"{block_name}:phase_sign"] = int(
            np.sign(block["raw"]["phase_median_partial_rho"])
        ) == raw_sign
        checks[f"{block_name}:pit_effect"] = block["pit"][
            "median_absolute_partial_rho"
        ] >= gates["baseline_pit_median_absolute_partial_rho_minimum"]
        checks[f"{block_name}:pit_sign"] = block["pit"]["median_sign"] == raw_sign
        checks[f"{block_name}:pit_sign_support"] = block["pit"]["group_sign_support"] >= gates[
            "baseline_group_sign_support_minimum_of_8"
        ]
        for coordinate in ("relative_to_all", "relative_rank"):
            relative = block[coordinate]
            checks[f"{block_name}:{coordinate}_effect"] = relative[
                "median_absolute_partial_rho"
            ] >= gates["baseline_relative_median_absolute_partial_rho_minimum"]
            checks[f"{block_name}:{coordinate}_sign"] = relative["median_sign"] == raw_sign
            checks[f"{block_name}:{coordinate}_sign_support"] = relative[
                "group_sign_support"
            ] >= gates["baseline_relative_sign_support_minimum_of_2"]
    return {"checks": checks, "baseline_gate_pass": bool(all(checks.values()))}


def _split_masks(
    frame: pd.DataFrame, habitat: str, spec: dict[str, Any], split_name: str
) -> tuple[pd.Series, pd.Series, int]:
    split = spec["habitat_splits"][split_name]
    low = frame[habitat] <= float(split["low_maximum"])
    if split_name == "primary":
        high = frame[habitat] > float(split["high_minimum_exclusive"])
    else:
        high = frame[habitat] >= float(split["high_minimum"])
    return low, high, int(split["minimum_cell_observations"])


def _cell_difference(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    coordinate: str,
    habitat: str,
    split_name: str,
) -> tuple[float, dict[str, int], dict[str, float]]:
    predictor, response, controls = _baseline_fields(spec, coordinate)
    low_mask, high_mask, minimum = _split_masks(frame, habitat, spec, split_name)
    low_rho, low_n = partial_rank_correlation(frame.loc[low_mask], predictor, response, controls)
    high_rho, high_n = partial_rank_correlation(frame.loc[high_mask], predictor, response, controls)
    if min(low_n, high_n) < minimum or not np.isfinite(low_rho) or not np.isfinite(high_rho):
        raise VolatilityTransitionError(
            f"modifier cell failed: {habitat}:{split_name}:{coordinate}:{low_n}:{high_n}"
        )
    return (
        float(high_rho - low_rho),
        {"low": int(low_n), "high": int(high_n)},
        {"low": float(low_rho), "high": float(high_rho)},
    )


def _summarize_modifier(
    effects: dict[str, float], supports: dict[str, Any], cell_rhos: dict[str, Any]
) -> dict[str, Any]:
    values = np.asarray(list(effects.values()), dtype=float)
    median = float(np.median(values))
    sign = int(np.sign(median))
    return {
        "by_group": effects,
        "cell_support_by_group": supports,
        "cell_rhos_by_group": cell_rhos,
        "median_high_minus_low": median,
        "median_absolute_high_minus_low": float(abs(median)),
        "median_sign": sign,
        "group_sign_support": int(np.sum(np.sign(values) == sign)),
    }


def _direction_modifier_estimate(
    expanded: pd.DataFrame,
    spec: dict[str, Any],
    coordinate: str,
    split_name: str,
) -> dict[str, Any]:
    habitat = "direction_return_60_pit_3y_pct"
    by_index: dict[str, float] = {}
    supports: dict[str, Any] = {}
    cell_rhos: dict[str, Any] = {}
    for index_symbol, index_frame in expanded.groupby("index_symbol", sort=True):
        group_effects: list[float] = []
        supports[str(index_symbol)] = {}
        cell_rhos[str(index_symbol)] = {}
        for (view, denominator), group in index_frame.groupby(
            ["market_view", "denominator"], sort=True
        ):
            group_name = f"{view}:{denominator}"
            effect, cell_support, rhos = _cell_difference(
                group, spec, coordinate, habitat, split_name
            )
            group_effects.append(effect)
            supports[str(index_symbol)][group_name] = cell_support
            cell_rhos[str(index_symbol)][group_name] = rhos
        if len(group_effects) != 8:
            raise VolatilityTransitionError("direction modifier group count changed")
        by_index[str(index_symbol)] = float(np.median(np.asarray(group_effects, dtype=float)))
    if set(by_index) != set(spec["population"]["direction_indices"]):
        raise VolatilityTransitionError("direction modifier index set changed")
    return _summarize_modifier(by_index, supports, cell_rhos)


def _discovery_modifier_estimate(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    coordinate: str,
    split_name: str,
) -> dict[str, Any]:
    habitat = "breadth_net_new_high_low60_pit_3y_pct"
    effects: dict[str, float] = {}
    supports: dict[str, Any] = {}
    cell_rhos: dict[str, Any] = {}
    for (view, denominator), group in frame.groupby(
        ["market_view", "denominator"], sort=True
    ):
        group_name = f"{view}:{denominator}"
        effect, cell_support, rhos = _cell_difference(
            group, spec, coordinate, habitat, split_name
        )
        effects[group_name] = effect
        supports[group_name] = cell_support
        cell_rhos[group_name] = rhos
    if len(effects) != 8:
        raise VolatilityTransitionError("discovery modifier group count changed")
    return _summarize_modifier(effects, supports, cell_rhos)


def _modifier_gate(
    spec: dict[str, Any], modifier_name: str, blocks: dict[str, Any]
) -> dict[str, Any]:
    gates = spec["gates"]
    support_minimum = spec["habitat_modifiers"][modifier_name]["sign_support_minimum"]
    primary_a = blocks["block_a_reused"]["primary"]
    primary_b = blocks["block_b_reused"]["primary"]
    raw_sign = primary_a["raw"]["median_sign"]
    checks: dict[str, bool] = {
        "block_a_primary_raw_effect": primary_a["raw"][
            "median_absolute_high_minus_low"
        ] >= gates["modifier_primary_raw_median_absolute_difference_minimum"],
        "block_b_primary_raw_effect": primary_b["raw"][
            "median_absolute_high_minus_low"
        ] >= gates["modifier_primary_raw_median_absolute_difference_minimum"],
        "primary_raw_sign_replication": raw_sign != 0
        and primary_b["raw"]["median_sign"] == raw_sign,
        "primary_raw_block_b_magnitude": primary_b["raw"][
            "median_absolute_high_minus_low"
        ] >= gates["modifier_block_b_to_block_a_magnitude_ratio_minimum"]
        * primary_a["raw"]["median_absolute_high_minus_low"],
    }
    for block_name in BLOCK_NAMES:
        primary = blocks[block_name]["primary"]
        neighbor = blocks[block_name]["shape_neighbor"]
        checks[f"{block_name}:primary_raw_sign_support"] = primary["raw"][
            "group_sign_support"
        ] >= support_minimum
        checks[f"{block_name}:primary_pit_effect"] = primary["pit"][
            "median_absolute_high_minus_low"
        ] >= gates["modifier_primary_pit_median_absolute_difference_minimum"]
        checks[f"{block_name}:primary_pit_sign"] = primary["pit"]["median_sign"] == raw_sign
        checks[f"{block_name}:primary_pit_sign_support"] = primary["pit"][
            "group_sign_support"
        ] >= support_minimum
        for coordinate in MODIFIER_COORDINATES:
            checks[f"{block_name}:neighbor_{coordinate}_effect"] = neighbor[coordinate][
                "median_absolute_high_minus_low"
            ] >= gates["modifier_neighbor_raw_and_pit_median_absolute_difference_minimum"]
            checks[f"{block_name}:neighbor_{coordinate}_sign"] = neighbor[coordinate][
                "median_sign"
            ] == raw_sign
            checks[f"{block_name}:neighbor_{coordinate}_sign_support"] = neighbor[coordinate][
                "group_sign_support"
            ] >= support_minimum
    return {"checks": checks, "modifier_gate_pass": bool(all(checks.values()))}


def analyze(
    panel: pd.DataFrame, trend: pd.DataFrame, spec: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    baseline_blocks: dict[str, Any] = {}
    modifier_output: dict[str, Any] = {"direction": {}, "discovery": {}}
    expanded = panel.merge(trend, on="trade_date", how="inner", validate="many_to_many")
    expected_expanded = spec["population"]["base_rows"] * len(
        spec["population"]["direction_indices"]
    )
    if len(expanded) != expected_expanded:
        raise VolatilityTransitionError("direction expansion population mismatch")
    for block_name in BLOCK_NAMES:
        base_block = _block_frame(panel, spec, block_name)
        direction_block = _block_frame(expanded, spec, block_name)
        baseline_blocks[block_name] = {
            coordinate: _baseline_estimate(base_block, spec, coordinate)
            for coordinate in COORDINATES
        }
        for split_name in SPLIT_NAMES:
            modifier_output["direction"].setdefault(block_name, {})[split_name] = {
                coordinate: _direction_modifier_estimate(
                    direction_block, spec, coordinate, split_name
                )
                for coordinate in MODIFIER_COORDINATES
            }
            modifier_output["discovery"].setdefault(block_name, {})[split_name] = {
                coordinate: _discovery_modifier_estimate(
                    base_block, spec, coordinate, split_name
                )
                for coordinate in MODIFIER_COORDINATES
            }
    baseline = {"blocks": baseline_blocks, **_baseline_gate(spec, baseline_blocks)}
    for name in modifier_output:
        modifier_output[name].update(_modifier_gate(spec, name, modifier_output[name]))
    return baseline, modifier_output


def _direction_wide(panel: pd.DataFrame, trend: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    direction_raw = spec["fields"]["direction"]
    pivot = trend.pivot(index="trade_date", columns="index_symbol", values=[
        direction_raw, _field(direction_raw, "pit")
    ])
    pivot.columns = [f"{field}__{symbol}" for field, symbol in pivot.columns]
    return panel.merge(pivot.reset_index(), on="trade_date", how="left", validate="many_to_one")


def _render_report(result: dict[str, Any]) -> str:
    baseline = result["baseline_diagnostics"]
    block_a = baseline["blocks"]["block_a_reused"]
    block_b = baseline["blocks"]["block_b_reused"]
    lines = [
        "# MKT-VOL-TRANS-001 continuous volatility transition",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Evidence label: `{result['evidence_label']}`.",
        "- Response: t+25 five-session RV20 change; current/response complete source spans share no return interval.",
        "- Future price returns, strategy fields, failed roles, post-2023 data, and CY-011 read: **none**.",
        "- State dynamics/modifiers are not strategy habitats, timing, causality, or rules.",
        "",
        "## Baseline",
        "",
        "| Raw A | Raw B | PIT A | PIT B | Phase A | Phase B | Gate |",
        "|---:|---:|---:|---:|---:|---:|---|",
        f"| {block_a['raw']['median_partial_rho']:.3f} | {block_b['raw']['median_partial_rho']:.3f} | "
        f"{block_a['pit']['median_partial_rho']:.3f} | {block_b['pit']['median_partial_rho']:.3f} | "
        f"{block_a['raw']['phase_median_partial_rho']:.3f} | "
        f"{block_b['raw']['phase_median_partial_rho']:.3f} | "
        f"{'PASS' if baseline['baseline_gate_pass'] else 'FAIL'} |",
        "",
        "## Habitat modifiers",
        "",
        "| Modifier | Primary raw A | Primary raw B | Primary PIT A | Primary PIT B | Neighbor raw A | Neighbor raw B | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name, modifier in result["modifier_diagnostics"].items():
        a = modifier["block_a_reused"]
        b = modifier["block_b_reused"]
        lines.append(
            f"| `{name}` | {a['primary']['raw']['median_high_minus_low']:.3f} | "
            f"{b['primary']['raw']['median_high_minus_low']:.3f} | "
            f"{a['primary']['pit']['median_high_minus_low']:.3f} | "
            f"{b['primary']['pit']['median_high_minus_low']:.3f} | "
            f"{a['shape_neighbor']['raw']['median_high_minus_low']:.3f} | "
            f"{b['shape_neighbor']['raw']['median_high_minus_low']:.3f} | "
            f"{'PASS' if modifier['modifier_gate_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Reproducibility",
        "",
        f"- Spec SHA-256: `{result['hashes']['spec_sha256']}`",
        f"- Panel SHA-256: `{result['hashes']['panel_sha256']}`",
    ])
    return "\n".join(lines) + "\n"


def run() -> dict[str, Any]:
    spec = _load_spec()
    base, trend = load_bound_inputs(spec)
    panel = construct_future_state(base, spec)
    baseline, modifiers = analyze(panel, trend, spec)
    classifications = {
        "baseline_transition_dynamic": bool(baseline["baseline_gate_pass"]),
        "direction_modifier": bool(modifiers["direction"]["modifier_gate_pass"]),
        "discovery_modifier": bool(modifiers["discovery"]["modifier_gate_pass"]),
    }
    passed = [name for name, value in classifications.items() if value]
    failed = [name for name, value in classifications.items() if not value]

    output = _direction_wide(panel, trend, spec)
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output["future_trade_date"] = output["future_trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(passed)}_OF_3_TRANSITION_CLAIMS_PASS",
        "evidence_label": "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION",
        "confirmation_status": "INDEPENDENT_FUTURE_TIME_REQUIRED",
        "usefulness_claim": "NONE",
        "future_market_volatility_state_fields_read": [spec["response"]],
        "future_price_return_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_volatility_roles_read": [],
        "failed_breadth_roles_read": [],
        "failed_trend_roles_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "base_rows": int(len(base)),
            "direction_rows": int(len(trend)),
            "expanded_diagnostic_rows": int(len(base) * trend["index_symbol"].nunique()),
            "base_groups": int(base.groupby(["market_view", "denominator"]).ngroups),
            "direction_indices": int(trend["index_symbol"].nunique()),
            "first_predictor_date": str(panel["trade_date"].min().date()),
            "last_predictor_with_response": str(
                panel.loc[panel["future_trade_date"].notna(), "trade_date"].max().date()
            ),
            "last_response_date": str(panel["future_trade_date"].max().date()),
        },
        "baseline_diagnostics": baseline,
        "modifier_diagnostics": modifiers,
        "transition_decision": {
            "passing_claims": passed,
            "failing_claims": failed,
            **classifications,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "volatility_panel_sha256": spec["inputs"]["volatility_panel"]["sha256"],
            "volatility_result_sha256": spec["inputs"]["volatility_result"]["sha256"],
            "breadth_panel_sha256": spec["inputs"]["breadth_panel"]["sha256"],
            "breadth_result_sha256": spec["inputs"]["breadth_result"]["sha256"],
            "trend_panel_sha256": spec["inputs"]["trend_panel"]["sha256"],
            "trend_result_sha256": spec["inputs"]["trend_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "transition_decision": completed["transition_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
