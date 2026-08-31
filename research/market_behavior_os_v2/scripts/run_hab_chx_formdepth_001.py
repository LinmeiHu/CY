#!/usr/bin/env python3
"""Test the frozen formation-depth CHINEXT V1 habitat association."""

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
SPEC_PATH = PROGRAM / "experiments/HAB-CHX-FORMDEPTH-001_spec.json"
PANEL_PATH = PROGRAM / "artifacts/HAB-CHX-FORMDEPTH-001_panel.csv"
ENDPOINT_PATH = PROGRAM / "artifacts/HAB-CHX-FORMDEPTH-001_endpoint_audit.csv"
BOOTSTRAP_PATH = PROGRAM / "artifacts/HAB-CHX-FORMDEPTH-001_bootstrap_audit.csv"
RESULT_PATH = PROGRAM / "artifacts/HAB-CHX-FORMDEPTH-001_result.json"
REPORT_PATH = PROGRAM / "reports/HAB-CHX-FORMDEPTH-001_habitat.md"
EXPECTED_SPEC_SHA256 = "3a0fc799295eb11167ce95048eb0f9fbd19b645afa6b42c96988455f7620a3c9"


class FormationDepthHabitatError(RuntimeError):
    """Fail-closed formation-depth habitat error."""


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
        raise FormationDepthHabitatError("spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec["status"] != "FROZEN_BEFORE_FORMATION_DEPTH_STRATEGY_OUTCOME_JOIN":
        raise FormationDepthHabitatError("experiment activation changed")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise FormationDepthHabitatError(f"input identity mismatch: {name}")
    economic = json.loads(_resolve(spec["inputs"]["economic_result"]["path"]).read_text())
    required_role = spec["activation"]["required_economic_role"]
    if (
        economic["classifications"][required_role]["status"]
        != spec["activation"]["required_economic_status"]
        or required_role not in economic["supported_market_states"]
    ):
        raise FormationDepthHabitatError("economic market-state activation changed")
    forbidden = "|".join(spec["prohibited_computations"])
    if "CY-011" not in forbidden or "post-2023" not in forbidden:
        raise FormationDepthHabitatError("prohibited boundary changed")
    return spec


def _peak_rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value if platform.system() == "Darwin" else value * 1024


def _resource_guard(spec: dict[str, Any], started: float) -> None:
    budget = spec["resource_budget"]
    if psutil.virtual_memory().available < int(
        budget["system_memory_headroom_floor_gib"] * 2**30
    ):
        raise FormationDepthHabitatError("system memory headroom below frozen floor")
    if _peak_rss_bytes() > int(budget["peak_rss_ceiling_gib"] * 2**30):
        raise FormationDepthHabitatError("process peak RSS ceiling breached")
    if time.monotonic() - started > float(budget["wall_clock_ceiling_minutes"]) * 60:
        raise FormationDepthHabitatError("wall-clock ceiling breached")


def _sign(value: float) -> int:
    if not np.isfinite(value) or value == 0:
        return 0
    return 1 if value > 0 else -1


def _partial_rank_rho(
    frame: pd.DataFrame, state: str, endpoint: str, controls: list[str]
) -> float:
    data = frame[[state, endpoint] + controls].dropna()
    if (
        len(data) < 3
        or data[state].nunique() < 2
        or data[endpoint].nunique() < 2
        or any(data[control].nunique() < 2 for control in controls)
    ):
        return float("nan")
    ranked = data.rank(method="average")
    design = np.column_stack(
        [np.ones(len(ranked))] + [ranked[control].to_numpy(float) for control in controls]
    )
    state_values = ranked[state].to_numpy(float)
    endpoint_values = ranked[endpoint].to_numpy(float)
    state_residual = state_values - design @ np.linalg.lstsq(
        design, state_values, rcond=None
    )[0]
    endpoint_residual = endpoint_values - design @ np.linalg.lstsq(
        design, endpoint_values, rcond=None
    )[0]
    if np.std(state_residual) == 0 or np.std(endpoint_residual) == 0:
        return float("nan")
    return float(np.corrcoef(state_residual, endpoint_residual)[0, 1])


def _tail_residual_gap(
    frame: pd.DataFrame, pit: str, endpoint: str, controls: list[str]
) -> tuple[float, int, int]:
    data = frame[[pit, endpoint] + controls].dropna()
    if len(data) < 3:
        return float("nan"), 0, 0
    ranked_controls = data[controls].rank(method="average")
    design = np.column_stack(
        [np.ones(len(data))]
        + [ranked_controls[control].to_numpy(float) for control in controls]
    )
    endpoint_values = data[endpoint].to_numpy(float)
    residual = endpoint_values - design @ np.linalg.lstsq(
        design, endpoint_values, rcond=None
    )[0]
    pit_values = data[pit].to_numpy(float)
    low = residual[pit_values <= 0.2]
    high = residual[pit_values >= 0.8]
    if len(low) == 0 or len(high) == 0:
        return float("nan"), int(len(low)), int(len(high))
    return float(np.mean(high) - np.mean(low)), int(len(low)), int(len(high))


def _load_panel(spec: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    habitat = pd.read_csv(
        _resolve(spec["inputs"]["strategy_habitat_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    state = pd.read_csv(
        _resolve(spec["inputs"]["formation_state_panel"]["path"]),
        parse_dates=["trade_date"],
    )
    state = state[
        state["market_view"].eq(spec["state"]["view"])
        & state["denominator"].eq(spec["state"]["denominator"])
    ][["trade_date", spec["state"]["absolute"], spec["state"]["pit"]]]
    if state["trade_date"].duplicated().any():
        raise FormationDepthHabitatError("formation-depth state date is not unique")
    volatility = pd.read_csv(
        _resolve(spec["inputs"]["volatility_panel"]["path"]), parse_dates=["trade_date"]
    )
    volatility = volatility[
        volatility["market_view"].eq(spec["state"]["view"])
        & volatility["denominator"].eq(spec["state"]["denominator"])
    ][["trade_date", spec["controls"]["volatility"]]]
    if volatility["trade_date"].duplicated().any():
        raise FormationDepthHabitatError("volatility control date is not unique")
    panel = habitat.merge(state, on="trade_date", how="left", validate="many_to_one").merge(
        volatility, on="trade_date", how="left", validate="many_to_one"
    )
    expected = spec["activation"]
    counts = panel["sample_type"].value_counts().to_dict()
    pit_counts = panel.groupby("sample_type")[spec["state"]["pit"]].count().to_dict()
    audit = {
        "rows": int(len(panel)),
        "sample_counts": {key: int(counts.get(key, 0)) for key in expected["expected_sample_counts"]},
        "pit_counts": {key: int(pit_counts.get(key, 0)) for key in expected["expected_pit_counts"]},
        "first_date": panel["trade_date"].min().strftime("%Y-%m-%d"),
        "last_date": panel["trade_date"].max().strftime("%Y-%m-%d"),
        "missing_absolute_state": int(panel[spec["state"]["absolute"]].isna().sum()),
        "missing_volatility_control": int(panel[spec["controls"]["volatility"]].isna().sum()),
    }
    if (
        audit["rows"] != expected["expected_rows"]
        or audit["sample_counts"] != expected["expected_sample_counts"]
        or audit["pit_counts"] != expected["expected_pit_counts"]
        or audit["first_date"] != expected["expected_first_date"]
        or audit["last_date"] != expected["expected_last_date"]
        or audit["missing_absolute_state"] != 0
        or audit["missing_volatility_control"] != 0
    ):
        raise FormationDepthHabitatError(f"habitat join audit failed: {audit}")
    cycles = panel[panel["sample_type"].eq("COMPLETED_CYCLE")].copy()
    if not (
        pd.to_datetime(cycles["entry_execution_date"])
        > pd.to_datetime(cycles["trade_date"])
    ).all():
        raise FormationDepthHabitatError("same-session or invalid entry execution found")
    return panel, audit


def _endpoint_sample(panel: pd.DataFrame, endpoint: dict[str, Any]) -> pd.DataFrame:
    sample = panel[panel["sample_type"].eq(endpoint["sample_type"])].copy()
    if endpoint["filter"] == "admissible_candidate == 1":
        sample = sample[sample["admissible_candidate"].eq(1)]
    elif endpoint["filter"] == "opportunity20 == 1":
        sample = sample[sample["opportunity20"].eq(1)]
    elif endpoint["filter"] != "ALL":
        raise FormationDepthHabitatError(f"unknown endpoint filter: {endpoint['filter']}")
    field = endpoint["field"]
    if sample[field].isna().any() or not np.isfinite(sample[field].to_numpy(float)).all():
        raise FormationDepthHabitatError(f"missing/nonfinite endpoint inside sample: {field}")
    if endpoint["kind"] == "binary" and not set(sample[field].unique()).issubset({0, 1, False, True}):
        raise FormationDepthHabitatError(f"binary endpoint domain failed: {field}")
    return sample.reset_index(drop=True)


def _bootstrap(
    sample: pd.DataFrame,
    endpoint_id: str,
    endpoint_field: str,
    state: str,
    controls: list[str],
    spec: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    dates = sorted(sample["trade_date"].unique())
    date_indices = {
        date: np.flatnonzero(sample["trade_date"].to_numpy() == date) for date in dates
    }
    values: list[float] = []
    rows: list[dict[str, Any]] = []
    for replicate in range(spec["estimation"]["bootstrap_replicates"]):
        material = f"HAB-CHX-FORMDEPTH-001|{endpoint_id}|{replicate}"
        seed = int(hashlib.sha256(material.encode()).hexdigest()[:16], 16)
        rng = np.random.default_rng(seed)
        selected = rng.choice(dates, size=len(dates), replace=True)
        indices = np.concatenate([date_indices[date] for date in selected])
        rho = _partial_rank_rho(sample.iloc[indices], state, endpoint_field, controls)
        values.append(rho)
        rows.append({"endpoint_id": endpoint_id, "replicate": replicate, "partial_rho": rho})
    valid = np.asarray([value for value in values if np.isfinite(value)], dtype=float)
    valid_fraction = len(valid) / spec["estimation"]["bootstrap_replicates"]
    if valid_fraction < spec["estimation"]["minimum_valid_bootstrap_fraction"]:
        interval = (float("nan"), float("nan"))
        p_value = float("nan")
    else:
        alpha = 1 - spec["estimation"]["bootstrap_interval"]
        interval = (
            float(np.quantile(valid, alpha / 2)),
            float(np.quantile(valid, 1 - alpha / 2)),
        )
        lower_tail = (1 + int(np.sum(valid <= 0))) / (len(valid) + 1)
        upper_tail = (1 + int(np.sum(valid >= 0))) / (len(valid) + 1)
        p_value = min(1.0, 2 * min(lower_tail, upper_tail))
    return pd.DataFrame(rows), {
        "valid_replicates": int(len(valid)),
        "valid_fraction": valid_fraction,
        "interval_low": interval[0],
        "interval_high": interval[1],
        "p_value": p_value,
    }


def _bh_q(p_values: dict[str, float]) -> dict[str, float]:
    finite = {key: value for key, value in p_values.items() if np.isfinite(value)}
    order = sorted(finite, key=finite.get)
    q_values = {key: float("nan") for key in p_values}
    running = 1.0
    m = len(order)
    for reverse_index in range(m - 1, -1, -1):
        key = order[reverse_index]
        rank = reverse_index + 1
        running = min(running, finite[key] * m / rank)
        q_values[key] = running
    return q_values


def _estimate(
    panel: pd.DataFrame, spec: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    absolute = spec["state"]["absolute"]
    pit = spec["state"]["pit"]
    controls = [spec["controls"][name] for name in ("trend", "discovery", "volatility")]
    audits: dict[str, dict[str, Any]] = {}
    bootstrap_frames: list[pd.DataFrame] = []
    p_values_by_family: dict[str, dict[str, float]] = {}
    samples: dict[str, pd.DataFrame] = {}
    for endpoint_id, endpoint in spec["endpoints"].items():
        sample = _endpoint_sample(panel, endpoint)
        samples[endpoint_id] = sample
        field = endpoint["field"]
        rho = _partial_rank_rho(sample, absolute, field, controls)
        pit_rho = _partial_rank_rho(sample, pit, field, controls)
        block_rhos = {}
        for block, years in (
            ("EARLY", spec["estimation"]["early_block"]),
            ("LATE", spec["estimation"]["late_block"]),
        ):
            block_rhos[block] = _partial_rank_rho(
                sample[sample["calendar_year"].isin(years)], absolute, field, controls
            )
        yearly = {}
        for year, yearly_sample in sample.groupby("calendar_year", sort=True):
            eligible = (
                len(yearly_sample) >= spec["estimation"]["minimum_year_n"]
                and yearly_sample[field].nunique() >= 2
                and yearly_sample[absolute].nunique() >= 2
            )
            yearly[str(int(year))] = {
                "n": int(len(yearly_sample)),
                "eligible": bool(eligible),
                "partial_rho": (
                    _partial_rank_rho(yearly_sample, absolute, field, controls)
                    if eligible
                    else float("nan")
                ),
            }
        loo = {}
        for year in sorted(sample["calendar_year"].unique()):
            subset = sample[sample["calendar_year"].ne(year)]
            loo[str(int(year))] = {
                "n": int(len(subset)),
                "partial_rho": _partial_rank_rho(subset, absolute, field, controls),
            }
        gap, low_n, high_n = _tail_residual_gap(sample, pit, field, controls)
        bootstrap, bootstrap_summary = _bootstrap(
            sample, endpoint_id, field, absolute, controls, spec
        )
        bootstrap_frames.append(bootstrap)
        p_values_by_family.setdefault(endpoint["family"], {})[endpoint_id] = bootstrap_summary[
            "p_value"
        ]
        audits[endpoint_id] = {
            "family": endpoint["family"],
            "sample_type": endpoint["sample_type"],
            "field": field,
            "kind": endpoint["kind"],
            "direct_habitat_endpoint": endpoint["direct_habitat_endpoint"],
            "n": int(len(sample)),
            "unique_dates": int(sample["trade_date"].nunique()),
            "partial_rho": rho,
            "pit_partial_rho": pit_rho,
            "block_rhos": block_rhos,
            "yearly": yearly,
            "leave_one_year_out": loo,
            "tail_residual_gap": gap,
            "tail_low_n": low_n,
            "tail_high_n": high_n,
            "tail_residual_gap_floor": endpoint["tail_residual_gap_floor"],
            "bootstrap": bootstrap_summary,
        }
    q_values: dict[str, float] = {}
    for family, values in p_values_by_family.items():
        family_q = _bh_q(values)
        q_values.update(family_q)
    rows = []
    decisions: dict[str, Any] = {}
    for endpoint_id, item in audits.items():
        sign = _sign(item["partial_rho"])
        eligible_years = [value for value in item["yearly"].values() if value["eligible"]]
        same_sign_years = sum(_sign(value["partial_rho"]) == sign for value in eligible_years)
        loo_signs = [
            _sign(value["partial_rho"])
            for value in item["leave_one_year_out"].values()
            if np.isfinite(value["partial_rho"])
        ]
        interval = (item["bootstrap"]["interval_low"], item["bootstrap"]["interval_high"])
        interval_excludes_zero = bool(
            np.isfinite(interval[0])
            and np.isfinite(interval[1])
            and (interval[0] > 0 or interval[1] < 0)
        )
        gates = {
            "minimum_n": item["n"] >= spec["estimation"]["minimum_n"],
            "partial_rho": abs(item["partial_rho"])
            >= spec["gates"]["minimum_absolute_partial_rho"],
            "bootstrap_interval": interval_excludes_zero,
            "bootstrap_valid_fraction": item["bootstrap"]["valid_fraction"]
            >= spec["estimation"]["minimum_valid_bootstrap_fraction"],
            "blocks": all(
                _sign(value) == sign
                and abs(value) >= spec["gates"]["minimum_absolute_block_rho"]
                for value in item["block_rhos"].values()
            ),
            "years": same_sign_years >= spec["gates"]["minimum_same_sign_eligible_years"],
            "leave_one_year_out": bool(loo_signs) and all(value == sign for value in loo_signs),
            "pit_sensitivity": _sign(item["pit_partial_rho"]) == sign
            and abs(item["pit_partial_rho"])
            >= spec["gates"]["minimum_absolute_pit_partial_rho"],
            "tail_residual_gap": _sign(item["tail_residual_gap"]) == sign
            and abs(item["tail_residual_gap"]) >= item["tail_residual_gap_floor"],
            "family_bh": q_values[endpoint_id] <= spec["gates"]["family_bh_q"],
        }
        passed = all(gates.values())
        decisions[endpoint_id] = {
            **item,
            "eligible_year_count": len(eligible_years),
            "same_sign_year_count": same_sign_years,
            "bootstrap_bh_q": q_values[endpoint_id],
            "gates": gates,
            "pass": passed,
        }
        rows.append(
            {
                "endpoint_id": endpoint_id,
                "family": item["family"],
                "sample_type": item["sample_type"],
                "direct_habitat_endpoint": item["direct_habitat_endpoint"],
                "n": item["n"],
                "unique_dates": item["unique_dates"],
                "partial_rho": item["partial_rho"],
                "pit_partial_rho": item["pit_partial_rho"],
                "early_partial_rho": item["block_rhos"]["EARLY"],
                "late_partial_rho": item["block_rhos"]["LATE"],
                "eligible_year_count": len(eligible_years),
                "same_sign_year_count": same_sign_years,
                "tail_residual_gap": item["tail_residual_gap"],
                "tail_low_n": item["tail_low_n"],
                "tail_high_n": item["tail_high_n"],
                "bootstrap_low": interval[0],
                "bootstrap_high": interval[1],
                "bootstrap_p": item["bootstrap"]["p_value"],
                "bootstrap_bh_q": q_values[endpoint_id],
                "pass": passed,
                "failed_gates": ",".join(key for key, value in gates.items() if not value),
            }
        )
    endpoint_audit = pd.DataFrame(rows).sort_values(["family", "endpoint_id"]).reset_index(
        drop=True
    )
    bootstrap_audit = pd.concat(bootstrap_frames, ignore_index=True).sort_values(
        ["endpoint_id", "replicate"]
    )
    return endpoint_audit, bootstrap_audit, decisions


def _render_report(result: dict[str, Any]) -> str:
    lines = [
        "# HAB-CHX-FORMDEPTH-001 strategy-habitat association",
        "",
        f"Status: **{result['status']}**.",
        "",
        "Evidence is exploratory and already consumed across 2018--2023. No rule, "
        "threshold, strategy modification, or untouched confirmation is claimed.",
        "",
        "| endpoint | family | partial rho | PIT rho | tail residual gap | q | pass |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for endpoint_id, item in result["endpoint_decisions"].items():
        lines.append(
            f"| {endpoint_id} | {item['family']} | {item['partial_rho']:.4f} | "
            f"{item['pit_partial_rho']:.4f} | {item['tail_residual_gap']:.4f} | "
            f"{item['bootstrap_bh_q']:.4f} | {item['pass']} |"
        )
    lines.extend(
        [
            "",
            f"Direct habitat endpoints passing: {', '.join(result['passing_direct_endpoints']) or 'none'}.",
            f"Daily opportunity-density endpoints passing: "
            f"{', '.join(result['passing_daily_endpoints']) or 'none'}.",
            "",
            "Formation depth remains a supported broad market downside state regardless of "
            "this strategy-transfer result. CY-011, post-2023 data, source ledgers, raw data, "
            "and strategy-rule optimization were not accessed.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_outputs(
    panel: pd.DataFrame,
    endpoint_audit: pd.DataFrame,
    bootstrap_audit: pd.DataFrame,
    result_without_hashes: dict[str, Any],
    spec: dict[str, Any],
) -> None:
    PANEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    panel.to_csv(PANEL_PATH, index=False, float_format="%.17g", lineterminator="\n")
    endpoint_audit.to_csv(
        ENDPOINT_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    bootstrap_audit.to_csv(
        BOOTSTRAP_PATH, index=False, float_format="%.17g", lineterminator="\n"
    )
    result = dict(result_without_hashes)
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "runner_sha256": sha256_file(Path(__file__)),
        "panel_sha256": sha256_file(PANEL_PATH),
        "endpoint_audit_sha256": sha256_file(ENDPOINT_PATH),
        "bootstrap_audit_sha256": sha256_file(BOOTSTRAP_PATH),
    }
    RESULT_PATH.write_text(
        json.dumps(_clean(result), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    REPORT_PATH.write_text(_render_report(result), encoding="utf-8")
    durable = sum(
        path.stat().st_size
        for path in (PANEL_PATH, ENDPOINT_PATH, BOOTSTRAP_PATH, RESULT_PATH, REPORT_PATH)
    )
    if durable > int(spec["resource_budget"]["durable_output_ceiling_mib"] * 2**20):
        raise FormationDepthHabitatError("durable output ceiling breached")


def main() -> None:
    started = time.monotonic()
    spec = _load_spec()
    _resource_guard(spec, started)
    panel, join_audit = _load_panel(spec)
    endpoint_audit, bootstrap_audit, decisions = _estimate(panel, spec)
    passing_direct = [
        endpoint_id
        for endpoint_id, item in decisions.items()
        if item["pass"] and item["direct_habitat_endpoint"]
    ]
    passing_daily = [
        endpoint_id
        for endpoint_id, item in decisions.items()
        if item["pass"] and not item["direct_habitat_endpoint"]
    ]
    status = (
        "COMPLETE_FORMATION_DEPTH_CHINEXT_V1_HABITAT_SUPPORTED"
        if passing_direct
        else "COMPLETE_NO_CHINEXT_V1_HABITAT_TRANSFER"
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim": "EXPLORATORY_STRATEGY_HABITAT_ASSOCIATION_ONLY",
        "evidence_grade": spec["evidence_grade"],
        "join_audit": join_audit,
        "endpoint_decisions": decisions,
        "passing_direct_endpoints": passing_direct,
        "passing_daily_endpoints": passing_daily,
        "habitat_supported": bool(passing_direct),
        "strategy_rule_authorized": False,
        "canonical_v1_modified": False,
        "source_event_ledgers_reopened": False,
        "raw_data_read": False,
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
    _write_outputs(panel_output, endpoint_audit, bootstrap_audit, result, spec)
    _resource_guard(spec, started)


if __name__ == "__main__":
    main()
