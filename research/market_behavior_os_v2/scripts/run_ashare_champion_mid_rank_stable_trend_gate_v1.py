#!/usr/bin/env python3
"""Test one frozen six-index 60-session direction gate on Champion ranks 3-5."""

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
EXPERIMENT_ID = "ASHARE-CHAMPION-MID-RANK-STABLE-TREND-GATE-V1"
SPEC_PATH = PROGRAM / f"experiments/{EXPERIMENT_ID}_spec.json"
ANATOMY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_anatomy.csv"
EQUITY_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_equity.csv"
RESULT_PATH = PROGRAM / f"artifacts/{EXPERIMENT_ID}_result.json"
REPORT_PATH = PROGRAM / f"reports/{EXPERIMENT_ID}_report.md"
MID_RANK_PATH = PROGRAM / "scripts/run_ashare_champion_mid_rank_concentration_v1.py"
EXPECTED_SPEC_SHA256 = "085ad422510c4dccfb7f9d7d83ad1e1878741c6ed7c5746e1043903380c49580"
FAMILY = "industry_diffusion_low_max_ranks_3_5_nonnegative_stable_trend"


class StableTrendGateError(RuntimeError):
    """Fail-closed stable-trend gate error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_module(name: str, path: Path) -> Any:
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise StableTrendGateError(f"cannot load {path}")
    module = importlib.util.module_from_spec(module_spec)
    sys.modules[name] = module
    module_spec.loader.exec_module(module)
    return module


MID = _load_module("ashare_mid_rank_for_stable_trend_gate", MID_RANK_PATH)
CYCLE016 = MID.CYCLE016
CONSTRUCTION = MID.CONSTRUCTION
CA = MID.CA


def _resolve(raw: str) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _load_spec() -> dict[str, Any]:
    if sha256_file(SPEC_PATH) != EXPECTED_SPEC_SHA256:
        raise StableTrendGateError("frozen spec identity mismatch")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    if spec.get("status") != "FROZEN_BEFORE_MID_RANK_TREND_OUTCOME_JOIN":
        raise StableTrendGateError("spec is not frozen")
    for name, binding in spec["inputs"].items():
        path = _resolve(binding["path"])
        if not path.is_file() or sha256_file(path) != binding["sha256"]:
            raise StableTrendGateError(f"bound input changed: {name}")
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
            winner_fraction=("final_net_return", lambda x: float((x > 0).mean())),
            severe_fraction=("final_net_return", lambda x: float((x <= -0.10).mean())),
        )
        .sort_values("signal_date")
    )
    trend = pd.read_csv(
        _resolve(spec["inputs"]["trend_panel"]["path"]),
        usecols=[
            "trade_date",
            "index_symbol",
            "available_at",
            "direction_return_60",
        ],
    )
    trend["trade_date"] = pd.to_datetime(trend.trade_date).dt.date
    availability = pd.to_datetime(trend.available_at, utc=True).dt.tz_convert(
        "Asia/Shanghai"
    )
    if not (
        availability.dt.date.eq(trend.trade_date)
        & availability.dt.hour.eq(15)
        & availability.dt.minute.eq(0)
    ).all():
        raise StableTrendGateError("trend availability contract changed")
    decision_dates = set(pd.to_datetime(cohorts.signal_date).dt.date)
    trend = trend.loc[trend.trade_date.isin(decision_dates)].copy()
    support = trend.groupby("trade_date").agg(
        index_count=("index_symbol", "nunique"),
        row_count=("index_symbol", "size"),
        finite_count=("direction_return_60", "count"),
        market_direction_60=("direction_return_60", "median"),
    )
    if not (
        support.index_count.eq(6)
        & support.row_count.eq(6)
        & support.finite_count.eq(6)
    ).all():
        raise StableTrendGateError("exact six-index direction support failed")
    support = support.reset_index().rename(columns={"trade_date": "signal_date"})
    cohorts["signal_date"] = pd.to_datetime(cohorts.signal_date).dt.date
    panel = cohorts.merge(support, on="signal_date", how="left", validate="one_to_one")
    if (
        len(panel) != 263
        or panel.market_direction_60.isna().any()
        or not panel.trades.between(2, 3).all()
    ):
        raise StableTrendGateError("mid-rank cohort/trend alignment failed")
    panel["year"] = pd.to_datetime(panel.signal_date).dt.year
    panel["block"] = np.where(panel.year <= 2020, "generation", "validation")
    panel["admission"] = np.where(
        panel.market_direction_60.lt(0.0), "NEGATIVE", "NONNEGATIVE"
    )
    return panel


def _anatomy(panel: pd.DataFrame) -> dict[str, Any]:
    states: dict[str, Any] = {}
    for state, group in panel.groupby("admission", sort=True):
        states[state] = {
            "dates": len(group),
            "mean_cohort_payoff": float(group.cohort_payoff.mean()),
            "median_cohort_payoff": float(group.cohort_payoff.median()),
            "winner_fraction": float(group.winner_fraction.mean()),
            "severe_fraction": float(group.severe_fraction.mean()),
        }
    if set(states) != {"NEGATIVE", "NONNEGATIVE"}:
        raise StableTrendGateError("trend state support missing")
    return {
        "states": states,
        "nonnegative_minus_negative_payoff": float(
            states["NONNEGATIVE"]["mean_cohort_payoff"]
            - states["NEGATIVE"]["mean_cohort_payoff"]
        ),
        "severe_fraction_improvement": float(
            states["NEGATIVE"]["severe_fraction"]
            - states["NONNEGATIVE"]["severe_fraction"]
        ),
    }


def _generation_decision(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    period = _anatomy(panel.loc[panel.year <= 2020])
    gate = spec["generation_gate_all_required"]
    checks = {
        "negative_dates": period["states"]["NEGATIVE"]["dates"]
        >= gate["minimum_negative_state_dates"],
        "nonnegative_dates": period["states"]["NONNEGATIVE"]["dates"]
        >= gate["minimum_nonnegative_state_dates"],
        "negative_payoff": period["states"]["NEGATIVE"]["mean_cohort_payoff"]
        <= gate["maximum_negative_state_mean_cohort_payoff"],
        "nonnegative_payoff": period["states"]["NONNEGATIVE"]["mean_cohort_payoff"]
        >= gate["minimum_nonnegative_state_mean_cohort_payoff"],
        "spread": period["nonnegative_minus_negative_payoff"]
        >= gate["minimum_nonnegative_minus_negative_payoff"],
        "severe": period["severe_fraction_improvement"]
        >= gate["minimum_severe_fraction_improvement"],
    }
    return {"period": period, "gates": checks, "passes": all(checks.values())}


def _validation_decision(panel: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    subset = panel.loc[panel.year >= 2021]
    period = _anatomy(subset)
    yearly = {
        str(year): _anatomy(subset.loc[subset.year.eq(year)])
        for year in range(2021, 2024)
    }
    gate = spec["validation_gate_all_required"]
    checks = {
        "negative_payoff": period["states"]["NEGATIVE"]["mean_cohort_payoff"]
        <= gate["maximum_negative_state_mean_cohort_payoff"],
        "nonnegative_payoff": period["states"]["NONNEGATIVE"]["mean_cohort_payoff"]
        >= gate["minimum_nonnegative_state_mean_cohort_payoff"],
        "spread": period["nonnegative_minus_negative_payoff"]
        >= gate["minimum_nonnegative_minus_negative_payoff"],
        "calendar_years": sum(
            row["nonnegative_minus_negative_payoff"] > 0 for row in yearly.values()
        )
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
    mid_spec = json.loads(
        _resolve(spec["inputs"]["mid_rank_spec"]["path"]).read_text(encoding="utf-8")
    )
    daily = pd.read_parquet(_resolve(mid_spec["inputs"]["causal_daily_panel"]["path"]))
    _, champion = CYCLE016.CYCLE015._weekly_selections(daily, construction_spec)
    champion = champion.copy()
    champion["family"] = FAMILY
    plans = CONSTRUCTION._make_plans(champion, calendar)
    metadata = champion[["trade_date", "symbol", "signal_rank"]].copy()
    metadata["signal_date"] = pd.to_datetime(metadata.pop("trade_date")).dt.date
    plans = plans.merge(
        metadata, on=["signal_date", "symbol"], how="left", validate="one_to_one"
    )
    if plans.signal_rank.isna().any():
        raise StableTrendGateError("Champion signal rank missing")
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
        "# Champion mid-rank stable-trend gate",
        "",
        f"Status: `{result['status']}`.",
        "",
        (
            "The sole rule uses MKT-TRND-001's accepted 60-session direction: "
            "the same-date median across all six frozen indices must be nonnegative "
            "to open a new ranks-3-to-5 cohort. The zero threshold and representation "
            "were frozen before joining Champion outcomes."
        ),
        "",
        "## Generation anatomy",
        "",
        (
            f"NEGATIVE payoff "
            f"{generation['states']['NEGATIVE']['mean_cohort_payoff']:.3%}; "
            f"NONNEGATIVE "
            f"{generation['states']['NONNEGATIVE']['mean_cohort_payoff']:.3%}; "
            f"spread {generation['nonnegative_minus_negative_payoff']:.3%}; "
            f"gate `{result['generation']['passes']}`."
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
            f"NEGATIVE payoff "
            f"{validation['states']['NEGATIVE']['mean_cohort_payoff']:.3%}; "
            f"NONNEGATIVE "
            f"{validation['states']['NONNEGATIVE']['mean_cohort_payoff']:.3%}; "
            f"spread {validation['nonnegative_minus_negative_payoff']:.3%}; "
            f"gate `{result['validation']['passes']}`."
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
        (
            "MKT-TRND-001 itself established representation stability only. This "
            "experiment is a consumed-history strategy-usefulness test, not OOS or "
            "independent confirmation. Post-2023 outcomes and CY-011 were not read."
        ),
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
        allowed_dates = set(
            panel.loc[panel.admission.eq("NONNEGATIVE"), "signal_date"]
        )
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
        "calendar_year_returns": None if candidate is None else MID._year_returns(equity),
        "target": target,
        "target_met": target_met,
        "input_identity": input_identity,
        "action_audit": action_audit,
        "forced_exit_rows": len(exits),
    }
    _atomic_write(
        ANATOMY_PATH,
        panel.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
    _atomic_write(
        EQUITY_PATH,
        equity.to_csv(index=False, lineterminator="\n", float_format="%.12g"),
    )
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
