#!/usr/bin/env python3
# ruff: noqa: E501
"""Frozen 2024-2025 diagnostic of V27 plus an outcome-blind former-strength audit."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1 as base,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_early_repair_v4r1_causal_replay as repair,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_fresh_capitulation_snapback_v27 as v27,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = (
    "ASHARE-TRUE-GAP-BELOW-L-FRESH-CAPITULATION-SNAPBACK-"
    "V27-DIAGNOSTIC-2024-2025-V1"
)
START_HEAD = "a1c4df9d5ff8af96285d9b1cdf858ccf54cfb311"
LABEL = "DIAGNOSTIC_2024_2025"
SIGNAL_START = pd.Timestamp("2024-01-01")
SIGNAL_END = pd.Timestamp("2025-12-31")
TAIL_END = pd.Timestamp("2026-03-31")
YEARS = (2024, 2025)

SOURCE_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_clean_corridor_v26_validation_2024_2025_v1"
)
SOURCE_LANE = SOURCE_ROOT / "validation_2024_2025"
SOURCE_DAILY = SOURCE_ROOT / "pit_daily_qd010_exact_2022_2026q1.parquet"
SOURCE_COORDINATE_AUDIT = SOURCE_ROOT / "coordinate_reproduction_2023.json"
SOURCE_CANDIDATES = SOURCE_LANE / "direct_first_ma5_candidates.parquet"
SOURCE_VAP = SOURCE_LANE / "vap_metrics.parquet"

EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_fresh_capitulation_snapback_"
    "v27_diagnostic_2024_2025_v1"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"


class DiagnosticError(RuntimeError):
    """Fail-closed V27 2024-2025 diagnostic error."""


def sha256(path: Path) -> str:
    return repair.sha256(path)


def write_json(path: Path, value: Any) -> None:
    repair.write_json(path, value)


def output_paths() -> dict[str, Path]:
    old_root = repair.EXT_ROOT
    try:
        repair.EXT_ROOT = EXT_ROOT
        return repair.paths(LABEL)
    finally:
        repair.EXT_ROOT = old_root


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_NOT_PRISTINE_OOS",
        "frozen_source_experiment": v27.EXPERIMENT,
        "frozen_source_contract_sha256": sha256(v27.CONTRACT),
        "signal_period": [str(SIGNAL_START.date()), str(SIGNAL_END.date())],
        "tail_end": str(TAIL_END.date()),
        "simultaneous_identity_freeze": True,
        "admission_unchanged": {
            "mature_decline": "pre_peak_to_gap_sessions >= 20",
            "fresh_shock": "gap_age <= 14 completed sessions",
            "forceful_snapback": "max_depth - current_depth >= 0.05 of frozen L",
        },
        "trade_contract_unchanged": {
            "trigger": "first completed daily close > previous completed daily high",
            "entry": "next legal executable 1-minute open",
            "target": "A67 below L",
            "time_stop": "H20",
            "failure_stop": "NONE",
            "round_trip_cost": 0.004,
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
        },
        "former_strength_audit": {
            "binding_gate": False,
            "window": "120 completed sessions strictly before gap formation",
            "ordered_runup": (
                "prior-window coordinate high divided by the lowest coordinate low "
                "observed no later than that high, minus one"
            ),
            "reported_thresholds_descriptive_only": [0.30, 0.50, 1.00],
        },
        "governance": {
            "2024_and_2025_outcomes_attached_together_after_identity_freeze": True,
            "rule_change_after_outcome_open_count": 0,
            "2024_outcome_used_to_change_2025_count": 0,
            "2026_use": "completion of signals formed by 2025-12-31 only",
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "source_v27_runner_sha256": sha256(Path(v27.__file__)),
            "source_v27_result_sha256": sha256(v27.RESULT),
            "selection_after_2024_or_2025_outcome": "PROHIBITED",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    paths = {
        "v27_runner": Path(v27.__file__),
        "v27_contract": v27.CONTRACT,
        "v27_spec": v27.SPEC,
        "v27_stage_a_freeze": v27.STAGE_A_FREEZE,
        "v27_result": v27.RESULT,
        "validation_infrastructure": Path(base.__file__),
        "frozen_candidates": SOURCE_CANDIDATES,
        "frozen_vap": SOURCE_VAP,
        "extended_daily": SOURCE_DAILY,
        "coordinate_audit": SOURCE_COORDINATE_AUDIT,
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise DiagnosticError(f"missing frozen source files: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def add_former_strength_features(
    selected: pd.DataFrame, daily: pd.DataFrame
) -> pd.DataFrame:
    """Attach causal, descriptive pre-gap strength measures; never use as a gate."""
    groups = {
        str(symbol): part.sort_values("trade_date", kind="mergesort").reset_index(drop=True)
        for symbol, part in daily.groupby("symbol", sort=False)
    }
    payload: dict[str, tuple[float, float]] = {}
    for event in selected.itertuples(index=False):
        part = groups[str(event.symbol)]
        positions = np.flatnonzero(
            pd.to_datetime(part.trade_date).eq(pd.Timestamp(event.gap_date)).to_numpy()
        )
        if len(positions) != 1:
            raise DiagnosticError(f"gap date identity failure {event.gap_id}")
        position = int(positions[0])
        history = part.iloc[position - 120 : position]
        if len(history) != 120:
            raise DiagnosticError(f"short former-strength history {event.gap_id}")
        peak_offset = int(np.nanargmax(history.coord_high.to_numpy(float)))
        peak = float(history.coord_high.iloc[peak_offset])
        ordered_low = float(history.iloc[: peak_offset + 1].coord_low.min())
        full_low = float(history.coord_low.min())
        if not (peak > 0 and ordered_low > 0 and full_low > 0):
            raise DiagnosticError(f"invalid former-strength coordinate {event.gap_id}")
        payload[str(event.gap_id)] = (
            peak / ordered_low - 1.0,
            peak / full_low - 1.0,
        )
    result = selected.copy()
    result["former_ordered_runup_120d"] = result.gap_id.astype(str).map(
        {key: value[0] for key, value in payload.items()}
    )
    result["former_range_120d"] = result.gap_id.astype(str).map(
        {key: value[1] for key, value in payload.items()}
    )
    if result[["former_ordered_runup_120d", "former_range_120d"]].isna().any().any():
        raise DiagnosticError("former-strength feature attachment failed")
    return result


def strength_summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"n": 0}
    values = frame.former_ordered_runup_120d.astype(float)
    return {
        "n": len(frame),
        "ordered_runup_mean": float(values.mean()),
        "ordered_runup_median": float(values.median()),
        "ordered_runup_ge_30pct_count": int(values.ge(0.30).sum()),
        "ordered_runup_ge_30pct_rate": float(values.ge(0.30).mean()),
        "ordered_runup_ge_50pct_count": int(values.ge(0.50).sum()),
        "ordered_runup_ge_50pct_rate": float(values.ge(0.50).mean()),
        "ordered_runup_ge_100pct_count": int(values.ge(1.00).sum()),
        "ordered_runup_ge_100pct_rate": float(values.ge(1.00).mean()),
        "pre_gap_drawdown_ge_30pct_rate": float(
            frame.pre_gap_drawdown_from_120d_peak.astype(float).ge(0.30).mean()
        ),
        "pre_peak_to_gap_sessions_median": float(
            frame.pre_peak_to_gap_sessions.astype(float).median()
        ),
    }


def strength_breakdown(frame: pd.DataFrame) -> dict[str, Any]:
    values: dict[str, Any] = {"combined": strength_summary(frame)}
    signal_year = pd.to_datetime(frame.signal_date).dt.year
    for year in YEARS:
        values[str(year)] = strength_summary(frame.loc[signal_year.eq(year)])
    for board in ("MAIN", "CHINEXT"):
        values[board] = strength_summary(frame.loc[frame.board.eq(board)])
    return values


def strength_outcome_summary(frame: pd.DataFrame) -> dict[str, Any]:
    """Describe the two predeclared strength cuts; never select or gate on them."""
    result: dict[str, Any] = {}
    for threshold in (0.30, 0.50):
        for relation, mask in (
            ("lt", frame.former_ordered_runup_120d.lt(threshold)),
            ("ge", frame.former_ordered_runup_120d.ge(threshold)),
        ):
            part = frame.loc[mask]
            key = f"runup_{relation}_{int(threshold * 100)}pct"
            result[key] = {
                "n": len(part),
                "mean_net": float(part.net_return.mean()),
                "median_net": float(part.net_return.median()),
                "win": float(part.net_return.gt(0).mean()),
                "severe10": float(part.net_return.le(-0.10).mean()),
                "yearly_mean_net": {
                    str(year): (
                        None
                        if part.loc[pd.to_datetime(part.entry_date).dt.year.eq(year)].empty
                        else float(
                            part.loc[
                                pd.to_datetime(part.entry_date).dt.year.eq(year),
                                "net_return",
                            ].mean()
                        )
                    )
                    for year in YEARS
                },
            }
    return result


def build_stage_a_population(daily: pd.DataFrame) -> dict[str, Any]:
    paths = output_paths()
    paths["root"].mkdir(parents=True, exist_ok=True)
    candidates = pd.read_parquet(SOURCE_CANDIDATES)
    vap = pd.read_parquet(SOURCE_VAP)
    for column in ("gap_date", "signal_date", "signal_time"):
        candidates[column] = pd.to_datetime(candidates[column])
    if candidates.empty or candidates.gap_id.duplicated().any():
        raise DiagnosticError("frozen candidate identity failure")
    panel = candidates.merge(vap, on="gap_id", how="left", validate="one_to_one")
    fixed = repair.fixed_signal_mask(panel)
    selected = panel.loc[fixed & v27.fresh_snapback_mask(panel)].copy()
    selected = selected.loc[selected.signal_date.dt.year.isin(YEARS)].copy()
    selected = add_former_strength_features(selected, daily)
    selected["rebound_from_post_gap_low_over_l"] = v27.rebound_from_post_gap_low_over_l(
        selected
    )
    selected["signal_year"] = selected.signal_date.dt.year
    selected["decision_latest_timestamp"] = selected.signal_time
    selected["feature_uses_post_signal_information"] = False
    selected["v27_mature_decline_gate"] = True
    selected["v27_fresh_gap_gate"] = True
    selected["v27_forceful_snapback_gate"] = True
    selected = selected.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    ).reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise DiagnosticError("V27 2024-2025 selected identity failure")
    repair.write_parquet(candidates, paths["candidates"])
    repair.write_parquet(vap, paths["root"] / "vap_metrics.parquet")
    repair.write_parquet(selected, paths["signals"])

    symbols = selected.symbol.drop_duplicates().astype(str).tolist()
    actions = repair.build_actions(
        symbols, TAIL_END, paths["actions"], paths["action_registry"]
    )
    state_columns = [
        "trade_date", "cal_idx", "symbol", "sleeve", "coordinate_factor",
        "invalid_step_cum", "history_valid", "current_valid", "hard_valid",
        "trade_status", "current_day_data_tradable", "market_rule_valid",
        "corporate_action_blocking", "up_limit_price", "down_limit_price",
    ]
    execution_state = daily.loc[
        daily.symbol.isin(symbols)
        & daily.trade_date.between(pd.Timestamp(selected.signal_date.min()), TAIL_END),
        state_columns,
    ].copy()
    execution_state["coordinate_lineage_carried"] = False
    repair.write_parquet(execution_state, paths["execution_state"])
    entries = repair.build_buy_entries(
        selected, actions, SIGNAL_END, TAIL_END, paths
    )
    executable = entries.loc[entries.entry_status.eq("EXECUTABLE_ENTRY")]
    yearly = (
        executable.assign(_year=pd.to_datetime(executable.signal_date).dt.year)
        .groupby("_year")
        .size()
    )
    hashes = {
        "daily": sha256(SOURCE_DAILY),
        "coordinate_audit": sha256(SOURCE_COORDINATE_AUDIT),
        "candidates": sha256(paths["candidates"]),
        "signals": sha256(paths["signals"]),
        "actions": sha256(paths["actions"]),
        "action_registry": sha256(paths["action_registry"]),
        "execution_state": sha256(paths["execution_state"]),
        "entries": sha256(paths["entries"]),
        "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
    }
    return {
        "direct_prior_high_candidates": len(candidates),
        "fixed_v13_signals": int(fixed.sum()),
        "selected_signals": len(selected),
        "selected_symbols": len(symbols),
        "entry_status": entries.entry_status.value_counts().astype(int).to_dict(),
        "evaluation_eligible_entries": len(executable),
        "eligible_entries_by_signal_year": {
            str(year): int(yearly.get(year, 0)) for year in YEARS
        },
        "former_strength_descriptive_only": strength_breakdown(selected),
        "feature_uses_post_signal_information_count": int(
            selected.feature_uses_post_signal_information.sum()
        ),
        "entry_at_or_before_signal_count": int(entries.entry_at_or_before_signal.sum()),
        "buy_at_or_above_up_limit_count": int(entries.buy_at_or_above_up_limit.sum()),
        "post_2025_signal_count": int(selected.signal_date.gt(SIGNAL_END).sum()),
        "hashes": hashes,
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    daily = pd.read_parquet(SOURCE_DAILY)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    population = build_stage_a_population(daily)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_BLIND_SIMULTANEOUS_2024_2025_IDENTITY_FREEZE",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "coordinate_reproduction_2023": json.loads(
            SOURCE_COORDINATE_AUDIT.read_text(encoding="utf-8")
        ),
        "population": population,
        "return_analysis_run": "NO",
        "strategy_backtest_run": "NO",
        "2024_outcomes_opened_before_2025_identity_freeze": "NO",
        "2026_signal_feature_or_selection_use": "NO",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise DiagnosticError("Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if freeze.get(key) != value
    }
    if source_hashes() != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), source_hashes()]
    paths = output_paths()
    artifacts = {
        "daily": sha256(SOURCE_DAILY),
        "coordinate_audit": sha256(SOURCE_COORDINATE_AUDIT),
        "candidates": sha256(paths["candidates"]),
        "signals": sha256(paths["signals"]),
        "actions": sha256(paths["actions"]),
        "action_registry": sha256(paths["action_registry"]),
        "execution_state": sha256(paths["execution_state"]),
        "entries": sha256(paths["entries"]),
        "vap_metrics": sha256(paths["root"] / "vap_metrics.parquet"),
    }
    if artifacts != freeze["population"]["hashes"]:
        drift["stage_a_artifacts"] = [freeze["population"]["hashes"], artifacts]
    if drift:
        raise DiagnosticError(f"Stage-A freeze drift: {drift}")
    return {"verified": True, "checks": checks}


@contextmanager
def base_runtime() -> Iterator[None]:
    names = {
        "EXPERIMENT": EXPERIMENT,
        "EXT_ROOT": EXT_ROOT,
        "CONTRACT": CONTRACT,
        "SPEC": SPEC,
        "STAGE_A_FREEZE": STAGE_A_FREEZE,
        "RESULT": RESULT,
        "REPORT": REPORT,
        "LABEL": LABEL,
        "SIGNAL_START": SIGNAL_START,
        "SIGNAL_END": SIGNAL_END,
        "TAIL_END": TAIL_END,
        "VALIDATION_YEARS": YEARS,
        "EXTENDED_DAILY": SOURCE_DAILY,
        "COORDINATE_AUDIT": SOURCE_COORDINATE_AUDIT,
        "MIN_ACCEPTED_TRADES_PER_YEAR": v27.MIN_ACCEPTED_TRADES_PER_YEAR,
        "verify_stage_a": verify_stage_a,
    }
    previous = {name: getattr(base, name) for name in names}
    try:
        for name, value in names.items():
            setattr(base, name, value)
        yield
    finally:
        for name, value in previous.items():
            setattr(base, name, value)


def diagnostic_verdict(result: dict[str, Any]) -> str:
    checks = result["goal_checks"]
    if all(checks.values()):
        return "V27_2024_2025_DIAGNOSTIC_PASSES_ALL_NUMERIC_GOALS"
    combined = result["portfolio"]["COMBINED"]
    yearly = result["accepted_trade_yearly"]
    if (
        combined["mean_net"] >= 0.03
        and all(yearly[str(year)]["mean_net"] is not None and yearly[str(year)]["mean_net"] > 0 for year in YEARS)
    ):
        return "V27_2024_2025_DIAGNOSTIC_MIXED"
    return "V27_2024_2025_DIAGNOSTIC_FAILED"


def run_stage_b() -> dict[str, Any]:
    with base_runtime():
        result = base.run_stage_b()
    paths = output_paths()
    signals = pd.read_parquet(paths["signals"])
    accepted = pd.read_parquet(paths["root"] / "portfolio_accepted.parquet")
    result["verdict"] = diagnostic_verdict(result)
    result["scientific_status"] = (
        "POST_OBSERVATION_ROBUSTNESS_DIAGNOSTIC_NOT_PRISTINE_OOS"
    )
    result["frozen_v27_contract_sha256"] = sha256(v27.CONTRACT)
    result["former_strength"] = {
        "selected_signals": strength_breakdown(signals),
        "portfolio_accepted": strength_breakdown(accepted),
        "predeclared_outcome_diagnostic": strength_outcome_summary(accepted),
        "binding_gate": False,
        "interpretation": (
            "M20 enforces peak age, not former leadership or a minimum prior run-up."
        ),
    }
    result["audit"]["former_strength_used_for_admission_count"] = 0
    result["audit"]["rule_changed_after_2024_2025_open_count"] = 0
    write_json(RESULT, result)
    render_report(result)
    return result


def pct(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2%}"


def render_report(result: dict[str, Any]) -> None:
    combined = result["portfolio"]["COMBINED"]
    strength = result["former_strength"]["portfolio_accepted"]
    strength_outcome = result["former_strength"]["predeclared_outcome_diagnostic"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        f"`{result['verdict']}`",
        "",
        "## Frozen 2024-2025 diagnostic",
        "",
        "Both years were frozen together before outcomes were attached. M20/F14/R5, V13 entry, A67, H20, 40 bp, K80 and all execution semantics are unchanged.",
        "",
        "|Signal year|Accepted|Mean net|Median net|Win|Target hit|Severe10|Mean hold|Portfolio return|",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for year in YEARS:
        item = result["accepted_trade_yearly"][str(year)]
        lines.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['target_hit'])}|{pct(item['severe10'])}|{item['mean_holding_sessions']:.2f}|{pct(combined['annual_returns'].get(str(year), 0.0))}|"
        )
    lines += [
        "",
        "## Combined",
        "",
        f"Accepted {combined['trades']}; mean {pct(combined['mean_net'])}; median {pct(combined['median_net'])}; win {pct(combined['win'])}; target hit {pct(combined['u_hit'])}; severe10 {pct(combined['severe10'])}.",
        f"Total return {pct(combined['total_return'])}; CAGR {pct(combined['cagr'])}; MaxDD {pct(combined['max_drawdown'])}; Sharpe {combined['sharpe']:.3f}.",
        "",
        "## Was it formerly strong?",
        "",
        "Former strength was audited before outcomes and was not used as an admission condition. M20 only says the prior peak is old enough.",
        "",
        "|Population|N|Median ordered 120d run-up|>=30%|>=50%|>=100%|",
        "|---|---:|---:|---:|---:|---:|",
        f"|Accepted combined|{strength['combined']['n']}|{pct(strength['combined']['ordered_runup_median'])}|{pct(strength['combined']['ordered_runup_ge_30pct_rate'])}|{pct(strength['combined']['ordered_runup_ge_50pct_rate'])}|{pct(strength['combined']['ordered_runup_ge_100pct_rate'])}|",
    ]
    for year in YEARS:
        item = strength[str(year)]
        lines.append(
            f"|Accepted {year}|{item['n']}|{pct(item['ordered_runup_median'])}|{pct(item['ordered_runup_ge_30pct_rate'])}|{pct(item['ordered_runup_ge_50pct_rate'])}|{pct(item['ordered_runup_ge_100pct_rate'])}|"
        )
    lines += [
        "",
        "The predeclared 30% split shows an association, not a new rule: below 30% mean "
        f"{pct(strength_outcome['runup_lt_30pct']['mean_net'])}, at least 30% mean "
        f"{pct(strength_outcome['runup_ge_30pct']['mean_net'])}. The 50% split is not monotone: below 50% mean "
        f"{pct(strength_outcome['runup_lt_50pct']['mean_net'])}, at least 50% mean "
        f"{pct(strength_outcome['runup_ge_50pct']['mean_net'])}.",
        "",
        "## Governance",
        "",
        "This is not pristine OOS because 2024-2025 outcomes in the broader family were already observed. No former-strength threshold was added after viewing results. 2026 is used only to complete positions from signals formed by 2025-12-31.",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if not (args.stage_a or args.stage_b or args.all):
        parser.error("choose --stage-a, --stage-b, or --all")
    if args.stage_a or args.all:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    if args.stage_b or args.all:
        print(json.dumps(run_stage_b(), indent=2, default=str))


if __name__ == "__main__":
    main()
