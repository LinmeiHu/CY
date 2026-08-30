#!/usr/bin/env python3
"""Execute the frozen consumed falsification of industry rotation persistence."""

from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-ROT-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-INDRS-ROT-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-INDRS-ROT-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-INDRS-ROT-001_falsification.md"
EXPECTED_SPEC_SHA256 = "1af3e49717f5055deb2b7ac6bc95e191b6eaee749fc477d646997acac176610e"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")
BLOCK_NAMES = ("block_a_consumed", "block_b_consumed")
DEFINITION_FIELDS = {
    "spearman": "industry_rank_rotation_spearman_lag5",
    "kendall": "industry_rank_rotation_kendall_lag5",
    "displacement": "industry_rank_rotation_displacement_lag5",
}
CONTROL_FIELDS = (
    "leadership_positive_mass_top10",
    "correlation_median20",
    "realized_volatility_change5",
)


class RotationFalsificationError(RuntimeError):
    """Fail-closed MKT-INDRS-ROT-001 error."""


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
        raise RotationFalsificationError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FALSIFICATION_RESPONSE_CONSTRUCTION":
        raise RotationFalsificationError("spec is not frozen before response construction")
    expected = [
        "delayed_spearman_persistence",
        "kendall_next_block_persistence",
        "displacement_next_block_persistence",
    ]
    if list(spec["replications"]) != expected:
        raise RotationFalsificationError("replication identity/order mismatch")
    if not spec["estimation"]["mechanism_requires_all_replications"]:
        raise RotationFalsificationError("all-replications requirement changed")
    return spec


def _field(raw: str, coordinate: str) -> str:
    suffix = {
        "raw": "",
        "pit": "_pit_3y_pct",
        "relative_to_all": "_relative_to_all",
        "relative_rank": "_relative_view_rank_pct",
    }[coordinate]
    return raw + suffix


def _input_paths(spec: dict[str, Any]) -> dict[str, Path]:
    output: dict[str, Path] = {}
    for name, entry in spec["inputs"].items():
        path = ROOT / entry["path"]
        if sha256_file(path) != entry["sha256"]:
            raise RotationFalsificationError(f"{name} identity mismatch")
        output[name] = path
    return output


def _validate_source_results(spec: dict[str, Any], paths: dict[str, Path]) -> None:
    industry = json.loads(paths["industry_result"].read_text(encoding="utf-8"))
    if "industry_rank_rotation20" not in industry["minimal_panel"]["accepted_roles"]:
        raise RotationFalsificationError("rotation representation is not accepted")
    if industry["usefulness_claim"] != "NONE" or industry["cy011_read"]:
        raise RotationFalsificationError("industry source claim boundary changed")
    geometry = json.loads(paths["geometry_result"].read_text(encoding="utf-8"))
    if "industry_rank_rotation20" not in geometry["compression"]["distinct_engine_coordinates"]:
        raise RotationFalsificationError("rotation is not a direct engine coordinate")
    if geometry["usefulness_claim"] != "NONE" or geometry["future_values_read"]:
        raise RotationFalsificationError("geometry source boundary changed")
    dynamics = json.loads(paths["dynamics_result"].read_text(encoding="utf-8"))
    decision = dynamics["temporal_decision"]
    if decision["accepted_edges"] != [spec["prerequisite"]["accepted_edge"]]:
        raise RotationFalsificationError("accepted dynamics edge changed")
    if decision["rejected_edges"] != spec["prerequisite"]["rejected_edges"]:
        raise RotationFalsificationError("rejected dynamics edges changed")
    if dynamics["confirmation_status"] != (
        "UNTOUCHED_BEFORE_SPECIFICATION_THEN_CONSUMED_BY_THIS_EXPERIMENT"
    ):
        raise RotationFalsificationError("prior confirmation-consumption boundary changed")
    prohibited_lists = (
        "market_return_fields_read",
        "stock_selection_fields_read",
        "strategy_or_outcome_fields_read",
        "failed_industry_roles_read",
        "failed_ma_industry_fields_read",
    )
    if any(dynamics[name] for name in prohibited_lists) or dynamics["cy011_read"]:
        raise RotationFalsificationError("dynamics source boundary changed")


def causal_rolling_percentile(
    values: pd.Series, window: int = 756, min_history: int = 504
) -> pd.Series:
    """Exact existing causal percentile: current value is included, old row expires."""
    output = np.full(len(values), np.nan, dtype=float)
    ordered: list[float] = []
    raw = values.to_numpy(dtype=float)
    for position, value in enumerate(raw):
        if np.isfinite(value):
            bisect.insort(ordered, float(value))
        expired_position = position - window
        if expired_position >= 0 and np.isfinite(raw[expired_position]):
            expired = float(raw[expired_position])
            removal = bisect.bisect_left(ordered, expired)
            if removal >= len(ordered) or ordered[removal] != expired:
                raise RotationFalsificationError("rolling percentile state lost exact value")
            ordered.pop(removal)
        if np.isfinite(value) and len(ordered) >= min_history:
            left = bisect.bisect_left(ordered, float(value))
            right = bisect.bisect_right(ordered, float(value))
            output[position] = (left + right + 1.0) / (2.0 * len(ordered))
    return pd.Series(output, index=values.index, dtype=float)


def _attach_alternate_coordinates(panel: pd.DataFrame) -> pd.DataFrame:
    alternate = [DEFINITION_FIELDS["kendall"], DEFINITION_FIELDS["displacement"]]
    pieces: list[pd.DataFrame] = []
    ordered = panel.sort_values(["market_view", "denominator", "trade_date"])
    for _, group in ordered.groupby(["market_view", "denominator"], sort=True):
        item = group.copy()
        for raw in alternate:
            item[_field(raw, "pit")] = causal_rolling_percentile(item[raw])
        pieces.append(item)
    out = pd.concat(pieces, ignore_index=True).sort_values(
        ["trade_date", "denominator", "market_view"]
    )
    for raw in alternate:
        all_values = out.loc[
            out["market_view"] == "ALL_A", ["trade_date", "denominator", raw]
        ].rename(columns={raw: "_all_value"})
        out = out.merge(all_values, on=["trade_date", "denominator"], how="left", validate="many_to_one")
        out[_field(raw, "relative_to_all")] = out[raw] - out["_all_value"]
        counts = out.groupby(["trade_date", "denominator"])[raw].transform("count")
        ranks = out.groupby(["trade_date", "denominator"])[raw].rank(method="average", pct=True)
        out[_field(raw, "relative_rank")] = ranks.where(counts >= 3)
        out = out.drop(columns="_all_value")
    return out.sort_values(KEYS).reset_index(drop=True)


def load_bound_input(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_source_results(spec, paths)
    geometry_fields = list(dict.fromkeys(
        _field(raw, coordinate)
        for raw in (DEFINITION_FIELDS["spearman"], *CONTROL_FIELDS)
        for coordinate in COORDINATES
    ))
    geometry = pd.read_csv(
        paths["geometry_panel"], usecols=[*KEYS, "geometry_decision_at", *geometry_fields]
    )
    industry = pd.read_csv(
        paths["industry_panel"],
        usecols=[
            *KEYS,
            "decision_at",
            DEFINITION_FIELDS["spearman"],
            DEFINITION_FIELDS["kendall"],
            DEFINITION_FIELDS["displacement"],
        ],
    ).rename(columns={DEFINITION_FIELDS["spearman"]: "_industry_spearman"})
    population = spec["population"]
    for name, frame in (("geometry", geometry), ("industry", industry)):
        if len(frame) != population["expected_rows"] or frame.duplicated(KEYS).any():
            raise RotationFalsificationError(f"{name} row/key identity mismatch")
    panel = geometry.merge(industry, on=KEYS, how="inner", validate="one_to_one")
    spearman = DEFINITION_FIELDS["spearman"]
    same = panel[spearman].eq(panel["_industry_spearman"]) | (
        panel[spearman].isna() & panel["_industry_spearman"].isna()
    )
    if not same.all():
        raise RotationFalsificationError("primary rotation differs across frozen panels")
    panel = panel.drop(columns="_industry_spearman")
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    if str(panel["trade_date"].min().date()) != population["date_start"]:
        raise RotationFalsificationError("source start changed")
    if str(panel["trade_date"].max().date()) != population["date_end"]:
        raise RotationFalsificationError("source end changed")
    for field in ("geometry_decision_at", "decision_at"):
        decision = pd.to_datetime(panel[field], errors="raise", utc=True).dt.tz_convert("Asia/Shanghai")
        if not (decision.dt.strftime("%H:%M:%S") == "15:00:00").all():
            raise RotationFalsificationError(f"{field} is not exact 15:00")
        if not (decision.dt.date == panel["trade_date"].dt.date).all():
            raise RotationFalsificationError(f"{field} date mismatch")
    if not (panel["geometry_decision_at"] == panel["decision_at"]).all():
        raise RotationFalsificationError("frozen panel availability mismatch")
    panel = panel.drop(columns="decision_at")
    counts = panel.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not (counts == population["expected_rows_per_group"]).all():
        raise RotationFalsificationError("source group population mismatch")
    if set(panel["market_view"]) != set(population["views"]):
        raise RotationFalsificationError("source view identity mismatch")
    if set(panel["denominator"]) != set(population["denominators"]):
        raise RotationFalsificationError("source denominator identity mismatch")
    return _attach_alternate_coordinates(panel)


def _response_name(replication: str, coordinate: str) -> str:
    return f"{replication}__response__{coordinate}"


def _future_date_name(replication: str) -> str:
    return f"{replication}__future_trade_date"


def _available_name(replication: str) -> str:
    return f"{replication}__response_available_at"


def construct_future_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    out = panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    grouped = out.groupby(["market_view", "denominator"], sort=False)
    predictor_time = pd.to_datetime(out["geometry_decision_at"], errors="raise", utc=True)
    for name, replication in spec["replications"].items():
        shift = int(replication["response_shift_sessions"])
        future_date = _future_date_name(name)
        available = _available_name(name)
        out[future_date] = grouped["trade_date"].shift(-shift)
        out[available] = out[future_date].dt.strftime("%Y-%m-%dT15:00:00+08:00")
        response_raw = DEFINITION_FIELDS[replication["response_definition"]]
        for coordinate in COORDINATES:
            out[_response_name(name, coordinate)] = grouped[_field(response_raw, coordinate)].shift(-shift)
        if int(out[future_date].isna().sum()) != shift * 8:
            raise RotationFalsificationError(f"future tail count mismatch: {name}")
        response_time = pd.to_datetime(out[available], errors="coerce", utc=True)
        if not (response_time.dropna() > predictor_time.loc[response_time.notna()]).all():
            raise RotationFalsificationError(f"response not later than predictor: {name}")
        for _, group in out.groupby(["market_view", "denominator"], sort=True):
            if not group[future_date].equals(group["trade_date"].shift(-shift)):
                raise RotationFalsificationError(f"response is not exact row shift: {name}")
    return out.sort_values(KEYS).reset_index(drop=True)


def _block_frame(
    panel: pd.DataFrame, spec: dict[str, Any], replication: str, block_name: str
) -> pd.DataFrame:
    block = spec["temporal_blocks"][block_name]
    start, end = pd.Timestamp(block["start"]), pd.Timestamp(block["end"])
    future_date = _future_date_name(replication)
    return panel.loc[
        panel["trade_date"].between(start, end) & panel[future_date].between(start, end)
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


def _phase_sample(frame: pd.DataFrame, required: list[str], stride: int) -> pd.DataFrame:
    valid = frame.dropna(subset=required).sort_values(KEYS).copy()
    ordinal = valid.groupby(["market_view", "denominator"], sort=False).cumcount()
    return valid.loc[ordinal % stride == 0].copy()


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


def _replication_fields(
    spec: dict[str, Any], replication: str, coordinate: str
) -> tuple[str, str, list[str]]:
    definition = spec["replications"][replication]["predictor_definition"]
    predictor = _field(DEFINITION_FIELDS[definition], coordinate)
    response = _response_name(replication, coordinate)
    controls = [_field(raw, coordinate) for raw in CONTROL_FIELDS]
    return predictor, response, controls


def _coordinate_block_estimate(
    frame: pd.DataFrame,
    spec: dict[str, Any],
    replication: str,
    coordinate: str,
) -> dict[str, Any]:
    predictor, response, controls = _replication_fields(spec, replication, coordinate)
    required = [predictor, response, *controls]
    primary: dict[str, float] = {}
    support: dict[str, int] = {}
    phase: dict[str, float] = {}
    phase_support: dict[str, int] = {}
    stride = int(spec["replications"][replication]["phase_stride"])
    for group_name, group in _analysis_groups(frame, coordinate):
        rho, observations = partial_rank_correlation(group, predictor, response, controls)
        if observations < _minimum_support(spec, coordinate) or not np.isfinite(rho):
            raise RotationFalsificationError(
                f"support/estimate failed: {replication}:{coordinate}:{group_name}:{observations}"
            )
        primary[group_name] = rho
        support[group_name] = observations
        phase_group = _phase_sample(group, required, stride)
        phase_rho, phase_observations = partial_rank_correlation(
            phase_group, predictor, response, controls
        )
        if phase_observations <= len(controls) + 3 or not np.isfinite(phase_rho):
            raise RotationFalsificationError(
                f"phase estimate failed: {replication}:{coordinate}:{group_name}:{phase_observations}"
            )
        phase[group_name] = phase_rho
        phase_support[group_name] = phase_observations
    values = np.asarray(list(primary.values()), dtype=float)
    phase_values = np.asarray(list(phase.values()), dtype=float)
    return {
        "by_group": primary,
        "support_by_group": support,
        "median_partial_rho": float(np.median(values)),
        "positive_group_support": int(np.sum(values > 0.0)),
        "phase_by_group": phase,
        "phase_support_by_group": phase_support,
        "phase_median_partial_rho": float(np.median(phase_values)),
        "phase_positive_group_support": int(np.sum(phase_values > 0.0)),
    }


def _replication_gate(spec: dict[str, Any], blocks: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    block_a = blocks["block_a_consumed"]
    block_b = blocks["block_b_consumed"]
    checks: dict[str, bool] = {
        "block_a_raw_effect": block_a["raw"]["median_partial_rho"]
        >= gates["raw_median_partial_rho_minimum"],
        "block_b_raw_effect": block_b["raw"]["median_partial_rho"]
        >= gates["raw_median_partial_rho_minimum"],
        "block_a_raw_positive_support": block_a["raw"]["positive_group_support"]
        >= gates["raw_positive_group_support_minimum_of_8"],
        "block_b_raw_positive_support": block_b["raw"]["positive_group_support"]
        >= gates["raw_positive_group_support_minimum_of_8"],
        "block_b_magnitude_replication": block_b["raw"]["median_partial_rho"]
        >= gates["block_b_to_block_a_magnitude_ratio_minimum"]
        * block_a["raw"]["median_partial_rho"],
    }
    for block_name in BLOCK_NAMES:
        block = blocks[block_name]
        checks[f"{block_name}:phase_effect"] = block["raw"]["phase_median_partial_rho"] >= (
            gates["phase_median_partial_rho_minimum"]
        )
        checks[f"{block_name}:pit_effect"] = block["pit"]["median_partial_rho"] >= (
            gates["pit_median_partial_rho_minimum"]
        )
        checks[f"{block_name}:pit_positive_support"] = block["pit"][
            "positive_group_support"
        ] >= gates["pit_positive_group_support_minimum_of_8"]
        for coordinate in ("relative_to_all", "relative_rank"):
            checks[f"{block_name}:{coordinate}_effect"] = block[coordinate][
                "median_partial_rho"
            ] >= gates["relative_median_partial_rho_minimum"]
            checks[f"{block_name}:{coordinate}_positive_support"] = block[coordinate][
                "positive_group_support"
            ] >= gates["relative_positive_group_support_minimum_of_2"]
    return {"checks": checks, "replication_gate_pass": bool(all(checks.values()))}


def analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for replication in spec["replications"]:
        blocks: dict[str, Any] = {}
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, replication, block_name)
            blocks[block_name] = {
                coordinate: _coordinate_block_estimate(
                    frame, spec, replication, coordinate
                )
                for coordinate in COORDINATES
            }
        output[replication] = {"blocks": blocks, **_replication_gate(spec, blocks)}
    return output


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-INDRS-ROT-001 rotation-persistence falsification",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Evidence label: `{result['evidence_label']}`.",
        "- Both 2019-2021 and 2022-2023 were already consumed before these post-result hypotheses.",
        "- Market/stock returns, selection outcomes, strategy fields, failed roles, post-2023 data, and CY-011 read: **none**.",
        "- Passing all three would remain exploratory state-process support, not confirmation, usefulness, causality, or a rule.",
        "",
        "## Fixed replications",
        "",
        "| Replication | Raw block A | Raw block B | PIT block A | PIT block B | Phase block A | Phase block B | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for name in spec["replications"]:
        replication = result["replication_diagnostics"][name]
        block_a = replication["blocks"]["block_a_consumed"]
        block_b = replication["blocks"]["block_b_consumed"]
        lines.append(
            f"| `{name}` | {block_a['raw']['median_partial_rho']:.3f} | "
            f"{block_b['raw']['median_partial_rho']:.3f} | "
            f"{block_a['pit']['median_partial_rho']:.3f} | "
            f"{block_b['pit']['median_partial_rho']:.3f} | "
            f"{block_a['raw']['phase_median_partial_rho']:.3f} | "
            f"{block_b['raw']['phase_median_partial_rho']:.3f} | "
            f"{'PASS' if replication['replication_gate_pass'] else 'FAIL'} |"
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
    source = load_bound_input(spec)
    panel = construct_future_states(source, spec)
    diagnostics = analyze(panel, spec)
    passed = [
        name for name in spec["replications"] if diagnostics[name]["replication_gate_pass"]
    ]
    failed = [name for name in spec["replications"] if name not in passed]
    mechanism_survives = len(passed) == len(spec["replications"])

    definition_columns = list(dict.fromkeys(
        _field(raw, coordinate)
        for raw in DEFINITION_FIELDS.values()
        for coordinate in COORDINATES
    ))
    control_columns = list(dict.fromkeys(
        _field(raw, coordinate) for raw in CONTROL_FIELDS for coordinate in COORDINATES
    ))
    temporal_columns: list[str] = []
    for name in spec["replications"]:
        temporal_columns.extend([_future_date_name(name), _available_name(name)])
        temporal_columns.extend(_response_name(name, coordinate) for coordinate in COORDINATES)
    output = panel[[
        *KEYS,
        "geometry_decision_at",
        *definition_columns,
        *control_columns,
        *temporal_columns,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    for name in spec["replications"]:
        future_date = _future_date_name(name)
        output[future_date] = output[future_date].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    status = (
        "COMPLETE_ROTATION_PERSISTENCE_SURVIVES_ALL_3_CONSUMED_FALSIFICATIONS"
        if mechanism_survives
        else f"COMPLETE_ROTATION_PERSISTENCE_FAILS_FALSIFICATION_{len(passed)}_OF_3_PASS"
    )
    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "evidence_label": "CONSUMED_EXPLORATORY_FALSIFICATION_NOT_CONFIRMATION",
        "confirmation_status": "INDEPENDENT_FUTURE_TIME_REQUIRED",
        "usefulness_claim": "NONE",
        "future_market_industry_state_fields_read": [
            "delayed t+10 Spearman rotation",
            "next-block t+5 Kendall rotation",
            "next-block t+5 mean-rank-displacement rotation",
        ],
        "market_return_fields_read": [],
        "stock_selection_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_industry_roles_read": [],
        "failed_ma_industry_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "source_rows": int(len(source)),
            "groups": int(source.groupby(["market_view", "denominator"]).ngroups),
            "first_predictor_date": str(panel["trade_date"].min().date()),
            "last_source_date": str(panel["trade_date"].max().date()),
        },
        "replication_diagnostics": diagnostics,
        "falsification_decision": {
            "passing_replications": passed,
            "failing_replications": failed,
            "mechanism_survives_all_replications": mechanism_survives,
        },
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "industry_panel_sha256": spec["inputs"]["industry_panel"]["sha256"],
            "industry_result_sha256": spec["inputs"]["industry_result"]["sha256"],
            "geometry_panel_sha256": spec["inputs"]["geometry_panel"]["sha256"],
            "geometry_result_sha256": spec["inputs"]["geometry_result"]["sha256"],
            "dynamics_result_sha256": spec["inputs"]["dynamics_result"]["sha256"],
            "panel_sha256": sha256_file(PANEL_PATH),
        },
    }
    result = _clean(result)
    RESULT_PATH.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result, spec), encoding="utf-8")
    return result


if __name__ == "__main__":
    completed = run()
    print(json.dumps({
        "status": completed["status"],
        "falsification_decision": completed["falsification_decision"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
