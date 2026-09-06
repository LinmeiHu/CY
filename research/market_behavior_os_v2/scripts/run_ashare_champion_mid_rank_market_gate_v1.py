#!/usr/bin/env python3
"""Test one frozen Absolute-Market-State gate on Champion ranks 3-5."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
PROGRAM = ROOT / "research/market_behavior_os_v2"
SPEC_PATH = PROGRAM / "experiments/ASHARE-CHAMPION-MID-RANK-MARKET-GATE-V1_spec.json"
ANATOMY_PATH = (
    PROGRAM / "artifacts/ASHARE-CHAMPION-MID-RANK-MARKET-GATE-V1_anatomy.csv"
)
EQUITY_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-MID-RANK-MARKET-GATE-V1_equity.csv"
RESULT_PATH = PROGRAM / "artifacts/ASHARE-CHAMPION-MID-RANK-MARKET-GATE-V1_result.json"
REPORT_PATH = PROGRAM / "reports/ASHARE-CHAMPION-MID-RANK-MARKET-GATE-V1_report.md"
MID_RANK_PATH = PROGRAM / "scripts/run_ashare_champion_mid_rank_concentration_v1.py"
EXPECTED_SPEC_SHA256 = "ee2f354b45ad8f95792a69013c8e6bc6d0fefeca413c6b8cafde80002a6e4bc7"
FAMILY = "industry_diffusion_low_max_ranks_3_5_nonlow_market"


class MidRankMarketGateError(RuntimeError):
    """Fail-closed market-gate experiment error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise MidRankMarketGateError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


MID = _load_module("ashare_mid_rank_for_market_gate", MID_RANK_PATH)
CYCLE016 = MID.CYCLE016
CONSTRUCTION = MID.CONSTRUCTION
CA = MID.CA


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise MidRankMarketGateError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_MID_RANK_STATE_OUTCOME_JOIN":
        raise MidRankMarketGateError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise MidRankMarketGateError(f"bound input changed: {name}")
    return spec


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


def _cohort_panel(spec: dict[str, Any]) -> pd.DataFrame:
    trades = pd.read_parquet(_resolve(spec["inputs"]["champion_trade_panel"]["path"]))
    trades = trades.loc[trades.signal_rank.between(3, 5)].copy()
    cohorts = (
        trades.groupby("signal_date", as_index=False)
        .agg(
            trades=("symbol", "size"),
            cohort_payoff=("final_net_return", "mean"),
            winner_fraction=("final_net_return", lambda values: float((values > 0).mean())),
            severe_fraction=(
                "final_net_return", lambda values: float((values <= -0.10).mean())
            ),
        )
        .sort_values("signal_date")
    )
    states = pd.read_csv(
        _resolve(spec["inputs"]["applicability_panel"]["path"]),
        usecols=["signal_date", "absolute_market_state", "absolute_market_state_state"],
    )
    cohorts["signal_date"] = pd.to_datetime(cohorts.signal_date).dt.date
    states["signal_date"] = pd.to_datetime(states.signal_date).dt.date
    panel = cohorts.merge(states, on="signal_date", how="left", validate="one_to_one")
    if (
        len(panel) != 263
        or panel.absolute_market_state_state.isna().any()
        or not panel.trades.between(2, 3).all()
    ):
        raise MidRankMarketGateError("mid-rank cohort/state alignment failed")
    panel["year"] = pd.to_datetime(panel.signal_date).dt.year
    panel["block"] = np.where(panel.year <= 2020, "generation", "validation")
    panel["admission"] = np.where(
        panel.absolute_market_state_state.eq("LOW"), "LOW", "NONLOW"
    )
    return panel


def _anatomy(panel: pd.DataFrame) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    for state, group in panel.groupby("admission", sort=True):
        groups[state] = {
            "dates": len(group),
            "mean_cohort_payoff": float(group.cohort_payoff.mean()),
            "median_cohort_payoff": float(group.cohort_payoff.median()),
            "winner_fraction": float(group.winner_fraction.mean()),
            "severe_fraction": float(group.severe_fraction.mean()),
        }
    if set(groups) != {"LOW", "NONLOW"}:
        raise MidRankMarketGateError("state support missing")
    return {
        "states": groups,
        "nonlow_minus_low_payoff": float(
            groups["NONLOW"]["mean_cohort_payoff"]
            - groups["LOW"]["mean_cohort_payoff"]
        ),
        "severe_fraction_improvement": float(
            groups["LOW"]["severe_fraction"] - groups["NONLOW"]["severe_fraction"]
        ),
    }


def _generation_decision(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    period = _anatomy(panel.loc[panel.year <= 2020])
    gate = spec["generation_gate_all_required"]
    checks = {
        "low_dates": period["states"]["LOW"]["dates"] >= gate["minimum_low_state_dates"],
        "low_payoff": period["states"]["LOW"]["mean_cohort_payoff"]
        <= gate["maximum_low_state_mean_cohort_payoff"],
        "nonlow_payoff": period["states"]["NONLOW"]["mean_cohort_payoff"]
        >= gate["minimum_nonlow_state_mean_cohort_payoff"],
        "spread": period["nonlow_minus_low_payoff"]
        >= gate["minimum_nonlow_minus_low_payoff"],
        "severe": period["severe_fraction_improvement"]
        >= gate["minimum_severe_fraction_improvement"],
    }
    return {"period": period, "gates": checks, "passes": all(checks.values())}


def _validation_decision(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    subset = panel.loc[panel.year >= 2021]
    period = _anatomy(subset)
    yearly = {str(year): _anatomy(subset.loc[subset.year.eq(year)]) for year in range(2021, 2024)}
    gate = spec["validation_gate_all_required"]
    checks = {
        "low_payoff": period["states"]["LOW"]["mean_cohort_payoff"]
        <= gate["maximum_low_state_mean_cohort_payoff"],
        "nonlow_payoff": period["states"]["NONLOW"]["mean_cohort_payoff"]
        >= gate["minimum_nonlow_state_mean_cohort_payoff"],
        "spread": period["nonlow_minus_low_payoff"]
        >= gate["minimum_nonlow_minus_low_payoff"],
        "calendar_years": sum(row["nonlow_minus_low_payoff"] > 0 for row in yearly.values())
        >= gate["minimum_positive_calendar_year_spreads"],
        "severe": period["severe_fraction_improvement"]
        >= gate["minimum_severe_fraction_improvement"],
    }
    return {
        "period": period,
        "calendar_years": yearly,
        "gates": checks,
        "passes": all(checks.values()),
    }


def _run_replay(
    spec: dict[str, Any], allowed_dates: set[date]
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame, dict[str, Any], dict[str, Any]]:
    ca_spec = CA._load_spec()
    paths, calendar, input_identity = CA._load_market_inputs(ca_spec)
    construction_spec = CONSTRUCTION._load_spec()
    anatomy_spec = json.loads(
        _resolve(spec["inputs"]["mid_rank_spec"]["path"]).read_text(encoding="utf-8")
    )
    daily = pd.read_parquet(_resolve(anatomy_spec["inputs"]["causal_daily_panel"]["path"]))
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["family"] = FAMILY
    plans = CONSTRUCTION._make_plans(champion, calendar)
    metadata = champion[["trade_date", "symbol", "signal_rank"]].copy()
    metadata["signal_date"] = pd.to_datetime(metadata.pop("trade_date")).dt.date
    plans = plans.merge(
        metadata, on=["signal_date", "symbol"], how="left", validate="one_to_one"
    )
    plans["signal_rank"] = plans.signal_rank.astype(int)
    plans = plans.loc[
        plans.signal_rank.between(3, 5) & plans.signal_date.isin(allowed_dates)
    ].copy()
    plans["family"] = FAMILY
    market_rows = CA.PRIOR._query_execution_rows(paths, plans, calendar)
    events, action_audit = CA._load_risk_events(ca_spec, calendar)
    candidate, equity, exits = CA._replay(FAMILY, plans, market_rows, calendar, events)
    return candidate, equity, exits, input_identity, action_audit


def _render(result: dict[str, Any]) -> str:
    generation = result["generation"]["period"]
    lines = [
        "# Champion mid-rank Absolute-Market-State gate",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The only tested state is the pre-existing causal Absolute Market State. "
            "LOW blocks a new cohort; no other dimension, cell, or scaling was opened."
        ),
        "",
        "## Generation anatomy",
        "",
        (
            f"LOW payoff {generation['states']['LOW']['mean_cohort_payoff']:.3%}; "
            f"NONLOW {generation['states']['NONLOW']['mean_cohort_payoff']:.3%}; "
            f"spread {generation['nonlow_minus_low_payoff']:.3%}; gate "
            f"`{result['generation']['passes']}`."
        ),
        "",
        "## Fixed validation",
        "",
    ]
    if result["validation"] is None:
        lines.append("Unopened because the generation gate failed.")
    else:
        validation = result["validation"]["period"]
        lines.append(
            f"LOW payoff {validation['states']['LOW']['mean_cohort_payoff']:.3%}; "
            f"NONLOW {validation['states']['NONLOW']['mean_cohort_payoff']:.3%}; "
            f"spread {validation['nonlow_minus_low_payoff']:.3%}; gate "
            f"`{result['validation']['passes']}`."
        )
    lines += ["", "## Executable result", ""]
    candidate = result["candidate"]
    if candidate is None:
        lines.append("No replay was authorized.")
    else:
        lines.append(
            f"Total {candidate['total_return']:.2%}; annualized "
            f"{candidate['annualized_return']:.2%}; maximum drawdown "
            f"{candidate['maximum_drawdown']:.2%}; Sharpe "
            f"{candidate['daily_sharpe']:.3f}; target met `{result['target_met']}`."
        )
    lines += [
        "",
        "This is consumed 2018-2023 post-hoc development optimization. Post-2023 "
        "outcomes and CY-011 were not read.",
        "",
    ]
    return "\n".join(lines)


def run() -> dict[str, Any]:
    spec = _load_spec()
    panel = _cohort_panel(spec)
    generation = _generation_decision(panel, spec)
    validation = _validation_decision(panel, spec) if generation["passes"] else None
    authorized = validation is not None and validation["passes"]
    candidate = None
    equity = pd.DataFrame(columns=["trade_date", "nav"])
    exits = pd.DataFrame()
    input_identity = None
    action_audit = None
    if authorized:
        allowed_dates = set(panel.loc[panel.admission.eq("NONLOW"), "signal_date"])
        candidate, equity, exits, input_identity, action_audit = _run_replay(
            spec, allowed_dates
        )
    baseline_result = json.loads(
        _resolve(spec["inputs"]["mid_rank_result"]["path"]).read_text(encoding="utf-8")
    )
    baseline = baseline_result["candidate"]
    comparison = None if candidate is None else MID._comparison(candidate, baseline)
    target = spec["success_target"]
    target_met = bool(
        candidate is not None
        and candidate["annualized_return"] >= target["minimum_annualized_return"]
        and candidate["maximum_drawdown"]
        > target["maximum_drawdown_must_be_greater_than"]
    )
    status = (
        "TARGET_ACHIEVED"
        if target_met
        else "COMPLETE_ANATOMY_GATE_FAILED"
        if not authorized
        else "COMPLETE_REPLAY_TARGET_NOT_MET"
    )
    _atomic_write(
        ANATOMY_PATH,
        panel.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    result = {
        "experiment_id": spec["experiment_id"],
        "status": status,
        "claim_boundary": spec["claim_boundary"],
        "post_2023_outcome_read": "NO",
        "cy011_read": "NO",
        "state": spec["fixed_state"],
        "generation": generation,
        "validation": validation,
        "replay_authorized": authorized,
        "baseline": baseline,
        "candidate": candidate,
        "comparison": comparison,
        "target": target,
        "target_met": target_met,
        "input_identity": input_identity,
        "action_audit": action_audit,
        "forced_exit_rows": len(exits),
    }
    result["hashes"] = {
        "spec_sha256": sha256_file(SPEC_PATH),
        "anatomy_sha256": sha256_file(ANATOMY_PATH),
        "equity_sha256": sha256_file(EQUITY_PATH),
    }
    _atomic_write(RESULT_PATH, json.dumps(_clean(result), indent=2, sort_keys=True) + "\n")
    _atomic_write(REPORT_PATH, _render(result))
    return result


if __name__ == "__main__":
    print(json.dumps(_clean(run()), indent=2, sort_keys=True))
