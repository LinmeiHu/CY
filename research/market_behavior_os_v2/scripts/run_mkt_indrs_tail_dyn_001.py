#!/usr/bin/env python3
"""Construct frozen nonoverlapping residual-leadership state dynamics."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/MKT-INDRS-TAIL-DYN-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/MKT-INDRS-TAIL-DYN-001_panel.csv"
RESULT_PATH = PROGRAM / "artifacts/MKT-INDRS-TAIL-DYN-001_result.json"
REPORT_PATH = PROGRAM / "reports/MKT-INDRS-TAIL-DYN-001_dynamics.md"
EXPECTED_SPEC_SHA256 = "56a83827c7ba0bea69d611f6d0ec8778a3364cb2c14d62d444e230d839fb5bca"
KEYS = ["trade_date", "market_view", "denominator"]
COORDINATES = ("raw", "pit", "relative_to_all", "relative_rank")
BLOCK_NAMES = ("block_a_reused", "block_b_reused")


class ResidualTailDynamicsError(RuntimeError):
    """Fail-closed MKT-INDRS-TAIL-DYN-001 error."""


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
        raise ResidualTailDynamicsError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FUTURE_STATE_CONSTRUCTION":
        raise ResidualTailDynamicsError("spec is not frozen before future-state construction")
    expected = [
        "tail_balance_nonoverlap_persistence",
        "concentration_nonoverlap_persistence",
        "concentration_to_future_tail_balance",
        "tail_balance_to_future_concentration",
    ]
    if list(spec["edges"]) != expected:
        raise ResidualTailDynamicsError("edge identity/order mismatch")
    if spec["population"]["future_shift_sessions"] != 20:
        raise ResidualTailDynamicsError("nonoverlap horizon changed")
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
            raise ResidualTailDynamicsError(f"{name} identity mismatch")
        output[name] = path
    return output


def _validate_source_results(spec: dict[str, Any], paths: dict[str, Path]) -> None:
    industry = json.loads(paths["industry_result"].read_text(encoding="utf-8"))
    required = spec["prerequisite"]["accepted_direct_engine_coordinates"]
    if not set(required).issubset(industry["minimal_panel"]["accepted_roles"]):
        raise ResidualTailDynamicsError("source representations are not accepted")
    if industry["usefulness_claim"] != "NONE" or industry["cy011_read"]:
        raise ResidualTailDynamicsError("industry source boundary changed")
    geometry = json.loads(paths["geometry_result"].read_text(encoding="utf-8"))
    if not set(required).issubset(geometry["compression"]["distinct_engine_coordinates"]):
        raise ResidualTailDynamicsError("targets are not direct engine coordinates")
    if geometry["usefulness_claim"] != "NONE" or geometry["future_values_read"]:
        raise ResidualTailDynamicsError("geometry source boundary changed")
    rotation = json.loads(paths["rotation_falsification_result"].read_text(encoding="utf-8"))
    if rotation["falsification_decision"]["mechanism_survives_all_replications"]:
        raise ResidualTailDynamicsError("rotation prerequisite changed")
    if rotation["market_return_fields_read"] or rotation["strategy_or_outcome_fields_read"]:
        raise ResidualTailDynamicsError("rotation result boundary changed")
    if rotation["post_2023_data_read"] or rotation["cy011_read"]:
        raise ResidualTailDynamicsError("rotation data boundary changed")


def _allowed_source_fields(spec: dict[str, Any]) -> list[str]:
    return list(dict.fromkeys(
        _field(raw, coordinate)
        for raw in spec["fields"].values()
        for coordinate in COORDINATES
    ))


def load_bound_input(spec: dict[str, Any]) -> pd.DataFrame:
    paths = _input_paths(spec)
    _validate_source_results(spec, paths)
    fields = _allowed_source_fields(spec)
    panel = pd.read_csv(
        paths["geometry_panel"], usecols=[*KEYS, "geometry_decision_at", *fields]
    )
    population = spec["population"]
    if len(panel) != population["expected_rows"] or panel.duplicated(KEYS).any():
        raise ResidualTailDynamicsError("source row/key identity mismatch")
    panel["trade_date"] = pd.to_datetime(panel["trade_date"], errors="raise")
    if str(panel["trade_date"].min().date()) != population["date_start"]:
        raise ResidualTailDynamicsError("source start changed")
    if str(panel["trade_date"].max().date()) != population["date_end"]:
        raise ResidualTailDynamicsError("source end changed")
    decision = pd.to_datetime(panel["geometry_decision_at"], errors="raise", utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    if not (decision.dt.strftime("%H:%M:%S") == "15:00:00").all():
        raise ResidualTailDynamicsError("predictor availability is not exact 15:00")
    if not (decision.dt.date == panel["trade_date"].dt.date).all():
        raise ResidualTailDynamicsError("predictor date/availability mismatch")
    counts = panel.groupby(["market_view", "denominator"], sort=True).size()
    if len(counts) != 8 or not (counts == population["expected_rows_per_group"]).all():
        raise ResidualTailDynamicsError("source group population mismatch")
    if set(panel["market_view"]) != set(population["views"]):
        raise ResidualTailDynamicsError("source view identity mismatch")
    if set(panel["denominator"]) != set(population["denominators"]):
        raise ResidualTailDynamicsError("source denominator identity mismatch")
    return panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)


def _response_name(response: str, coordinate: str) -> str:
    return f"{response}__{coordinate}"


def construct_future_states(panel: pd.DataFrame, spec: dict[str, Any]) -> pd.DataFrame:
    shift = int(spec["population"]["future_shift_sessions"])
    out = panel.sort_values(["market_view", "denominator", "trade_date"]).reset_index(drop=True)
    grouped = out.groupby(["market_view", "denominator"], sort=False)
    out["future_trade_date"] = grouped["trade_date"].shift(-shift)
    out["response_available_at"] = out["future_trade_date"].dt.strftime(
        "%Y-%m-%dT15:00:00+08:00"
    )
    response_fields = {
        "future_tail_balance20": spec["fields"]["tail_balance"],
        "future_residual_concentration20": spec["fields"]["residual_concentration"],
    }
    if set(response_fields) != set(spec["responses"]):
        raise ResidualTailDynamicsError("response identity mismatch")
    for response, raw in response_fields.items():
        for coordinate in COORDINATES:
            out[_response_name(response, coordinate)] = grouped[_field(raw, coordinate)].shift(
                -shift
            )
    if int(out["future_trade_date"].isna().sum()) != shift * 8:
        raise ResidualTailDynamicsError("future tail count mismatch")
    predictor_time = pd.to_datetime(out["geometry_decision_at"], errors="raise", utc=True)
    response_time = pd.to_datetime(out["response_available_at"], errors="coerce", utc=True)
    if not (response_time.dropna() > predictor_time.loc[response_time.notna()]).all():
        raise ResidualTailDynamicsError("response is not strictly later than predictor")
    for _, group in out.groupby(["market_view", "denominator"], sort=True):
        if not group["future_trade_date"].equals(group["trade_date"].shift(-shift)):
            raise ResidualTailDynamicsError("future date is not exact twenty-row shift")
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


def _edge_fields(
    spec: dict[str, Any], edge_name: str, coordinate: str
) -> tuple[str, str, list[str]]:
    edge = spec["edges"][edge_name]
    predictor = _field(spec["fields"][edge["predictor"]], coordinate)
    response = _response_name(edge["response"], coordinate)
    controls = [_field(spec["fields"][name], coordinate) for name in edge["controls"]]
    return predictor, response, controls


def _coordinate_block_estimate(
    frame: pd.DataFrame, spec: dict[str, Any], edge_name: str, coordinate: str
) -> dict[str, Any]:
    predictor, response, controls = _edge_fields(spec, edge_name, coordinate)
    required = [predictor, response, *controls]
    primary: dict[str, float] = {}
    support: dict[str, int] = {}
    phase: dict[str, float] = {}
    phase_support: dict[str, int] = {}
    stride = int(spec["population"]["phase_stride"])
    for group_name, group in _analysis_groups(frame, coordinate):
        rho, observations = partial_rank_correlation(group, predictor, response, controls)
        if observations < _minimum_support(spec, coordinate) or not np.isfinite(rho):
            raise ResidualTailDynamicsError(
                f"support/estimate failed: {edge_name}:{coordinate}:{group_name}:{observations}"
            )
        primary[group_name] = rho
        support[group_name] = observations
        phase_group = _phase_sample(group, required, stride)
        phase_rho, phase_observations = partial_rank_correlation(
            phase_group, predictor, response, controls
        )
        if phase_observations <= len(controls) + 3 or not np.isfinite(phase_rho):
            raise ResidualTailDynamicsError(
                f"phase estimate failed: {edge_name}:{coordinate}:{group_name}:{phase_observations}"
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


def _edge_gate(spec: dict[str, Any], blocks: dict[str, Any]) -> dict[str, Any]:
    gates = spec["gates"]
    block_a = blocks["block_a_reused"]
    block_b = blocks["block_b_reused"]
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
    return {"checks": checks, "edge_gate_pass": bool(all(checks.values()))}


def analyze(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for edge_name in spec["edges"]:
        blocks: dict[str, Any] = {}
        for block_name in BLOCK_NAMES:
            frame = _block_frame(panel, spec, block_name)
            blocks[block_name] = {
                coordinate: _coordinate_block_estimate(
                    frame, spec, edge_name, coordinate
                )
                for coordinate in COORDINATES
            }
        output[edge_name] = {"blocks": blocks, **_edge_gate(spec, blocks)}
    return output


def _classify(diagnostics: dict[str, Any]) -> dict[str, bool]:
    tail = diagnostics["tail_balance_nonoverlap_persistence"]["edge_gate_pass"]
    concentration = diagnostics["concentration_nonoverlap_persistence"]["edge_gate_pass"]
    cross_a = diagnostics["concentration_to_future_tail_balance"]["edge_gate_pass"]
    cross_b = diagnostics["tail_balance_to_future_concentration"]["edge_gate_pass"]
    return {
        "tail_balance_state_process": bool(tail),
        "residual_concentration_state_process": bool(concentration),
        "coupled_tail_concentration_process": bool(cross_a and cross_b),
    }


def _render_report(result: dict[str, Any], spec: dict[str, Any]) -> str:
    lines = [
        "# MKT-INDRS-TAIL-DYN-001 residual leadership dynamics",
        "",
        "## Boundary",
        "",
        f"- Status: `{result['status']}`",
        f"- Evidence label: `{result['evidence_label']}`.",
        "- Future values are t+20 residual tail-balance/concentration states only.",
        "- Market/industry/stock returns, named-security futures, strategies, failed roles, post-2023 data, and CY-011 read: **none**.",
        "- Passing is exploratory state-process evidence, not confirmation, selection alpha, timing, causality, habitat, or a rule.",
        "",
        "## Fixed temporal edges",
        "",
        "| Edge | Raw block A | Raw block B | PIT block A | PIT block B | Phase block A | Phase block B | Gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for edge_name in spec["edges"]:
        edge = result["edge_diagnostics"][edge_name]
        block_a = edge["blocks"]["block_a_reused"]
        block_b = edge["blocks"]["block_b_reused"]
        lines.append(
            f"| `{edge_name}` | {block_a['raw']['median_partial_rho']:.3f} | "
            f"{block_b['raw']['median_partial_rho']:.3f} | "
            f"{block_a['pit']['median_partial_rho']:.3f} | "
            f"{block_b['pit']['median_partial_rho']:.3f} | "
            f"{block_a['raw']['phase_median_partial_rho']:.3f} | "
            f"{block_b['raw']['phase_median_partial_rho']:.3f} | "
            f"{'PASS' if edge['edge_gate_pass'] else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## Process classification",
        "",
        f"- Tail-balance state process: `{result['process_classification']['tail_balance_state_process']}`",
        f"- Residual-concentration state process: `{result['process_classification']['residual_concentration_state_process']}`",
        f"- Coupled tail/concentration process: `{result['process_classification']['coupled_tail_concentration_process']}`",
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
    accepted = [name for name in spec["edges"] if diagnostics[name]["edge_gate_pass"]]
    rejected = [name for name in spec["edges"] if name not in accepted]
    classification = _classify(diagnostics)

    response_columns = [
        _response_name(response, coordinate)
        for response in spec["responses"]
        for coordinate in COORDINATES
    ]
    output = panel[[
        *KEYS,
        "geometry_decision_at",
        "future_trade_date",
        "response_available_at",
        *_allowed_source_fields(spec),
        *response_columns,
    ]].copy()
    output["trade_date"] = output["trade_date"].dt.strftime("%Y-%m-%d")
    output["future_trade_date"] = output["future_trade_date"].dt.strftime("%Y-%m-%d")
    output.to_csv(PANEL_PATH, index=False, float_format="%.12g", lineterminator="\n")

    result: dict[str, Any] = {
        "experiment_id": spec["experiment_id"],
        "status": f"COMPLETE_{len(accepted)}_OF_{len(spec['edges'])}_EXACT_EDGES_PASS",
        "evidence_label": "REUSED_PRE2024_EXPLORATORY_REPLICATION_NOT_CONFIRMATION",
        "confirmation_status": "INDEPENDENT_FUTURE_TIME_REQUIRED",
        "usefulness_claim": "NONE",
        "future_market_industry_state_fields_read": list(spec["responses"]),
        "market_return_fields_read": [],
        "industry_return_fields_read": [],
        "stock_return_fields_read": [],
        "future_security_identity_fields_read": [],
        "stock_selection_fields_read": [],
        "strategy_or_outcome_fields_read": [],
        "failed_industry_roles_read": [],
        "failed_temporal_edges_read": [],
        "failed_ma_industry_fields_read": [],
        "post_2023_data_read": False,
        "cy011_read": False,
        "population": {
            "source_rows": int(len(source)),
            "response_rows": int(panel["future_trade_date"].notna().sum()),
            "groups": int(source.groupby(["market_view", "denominator"]).ngroups),
            "first_predictor_date": str(panel["trade_date"].min().date()),
            "last_predictor_with_response": str(
                panel.loc[panel["future_trade_date"].notna(), "trade_date"].max().date()
            ),
            "last_response_date": str(panel["future_trade_date"].max().date()),
        },
        "edge_diagnostics": diagnostics,
        "temporal_decision": {"accepted_edges": accepted, "rejected_edges": rejected},
        "process_classification": classification,
        "hashes": {
            "spec_sha256": sha256_file(SPEC_PATH),
            "industry_result_sha256": spec["inputs"]["industry_result"]["sha256"],
            "geometry_panel_sha256": spec["inputs"]["geometry_panel"]["sha256"],
            "geometry_result_sha256": spec["inputs"]["geometry_result"]["sha256"],
            "rotation_falsification_result_sha256": spec["inputs"][
                "rotation_falsification_result"
            ]["sha256"],
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
        "temporal_decision": completed["temporal_decision"],
        "process_classification": completed["process_classification"],
        "panel_sha256": completed["hashes"]["panel_sha256"],
    }, indent=2, sort_keys=True))
