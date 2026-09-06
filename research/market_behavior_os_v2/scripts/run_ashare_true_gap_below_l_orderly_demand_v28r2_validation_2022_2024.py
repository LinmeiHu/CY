#!/usr/bin/env python3
# ruff: noqa: E501
"""Run the frozen V28R2 rule once on the 2022-2024 temporal diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_demand_not_locked_v28r1 as v28r1,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_orderly_demand_v28r2 as v28r2,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2-VALIDATION-2022-2024"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_orderly_demand_v28r2_validation_2022_2024"
)
IDENTITY_FREEZE = OS / f"artifacts/{EXPERIMENT}_identity_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
SELECTED = EXT_ROOT / "diagnostic_2022_2024/orderly_demand_selected_entries.parquet"
LANE_ROOT = EXT_ROOT / "diagnostic_2022_2024/orderly_demand"

VALIDATION_YEARS = (2022, 2023, 2024)
FEATURE_INPUT_YEARS = (2021, 2022, 2023, 2024)
VALIDATION_END = pd.Timestamp("2024-12-31 23:59:59")


class V28R2ValidationError(RuntimeError):
    """Fail closed on frozen-rule drift, temporal leakage, or identity mismatch."""


def sha256(path: Path) -> str:
    return v28.sha256(path)


def write_json(path: Path, value: Any) -> None:
    v28.write_json(path, value)


def _assert_development_payload(freeze: dict[str, Any], result: dict[str, Any]) -> None:
    if freeze.get("experiment") != v28r2.EXPERIMENT:
        raise V28R2ValidationError("wrong V28R2 development freeze identity")
    if freeze.get("stage") != "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN":
        raise V28R2ValidationError("V28R2 development identity was not frozen before outcomes")
    if result.get("experiment") != v28r2.EXPERIMENT or result.get("selector_passed") is not True:
        raise V28R2ValidationError("V28R2 development selector did not pass")
    goal_checks = result.get("goal_checks", {})
    if not goal_checks or not all(value is True for value in goal_checks.values()):
        raise V28R2ValidationError("not every frozen V28R2 development goal passed")
    if result.get("post_2021_entries_or_outcomes_opened") != "NO":
        raise V28R2ValidationError("V28R2 development result reports later-data access")
    if result.get("diagnostic_authorization_created") != "NO":
        raise V28R2ValidationError("unexpected authorization mutation in development runner")
    stage_checks = result.get("stage_a_verification", {}).get("checks", {})
    for key in ("contract_sha256", "spec_sha256", "runner_sha256"):
        if stage_checks.get(key) != freeze.get(key):
            raise V28R2ValidationError(f"V28R2 development result/freeze mismatch: {key}")


def verify_development_lock() -> dict[str, Any]:
    required = [
        Path(v28r2.__file__),
        v28r2.CONTRACT,
        v28r2.SPEC,
        v28r2.STAGE_A_FREEZE,
        v28r2.DEVELOPMENT_RESULT,
        v28r2.selected_path(),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise V28R2ValidationError(f"missing frozen V28R2 development source: {missing}")
    freeze = json.loads(v28r2.STAGE_A_FREEZE.read_text(encoding="utf-8"))
    result = json.loads(v28r2.DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    _assert_development_payload(freeze, result)
    current = {
        "contract_sha256": sha256(v28r2.CONTRACT),
        "spec_sha256": sha256(v28r2.SPEC),
        "runner_sha256": sha256(Path(v28r2.__file__)),
        "selected_entries_sha256": sha256(v28r2.selected_path()),
    }
    expected = {
        "contract_sha256": freeze["contract_sha256"],
        "spec_sha256": freeze["spec_sha256"],
        "runner_sha256": freeze["runner_sha256"],
        "selected_entries_sha256": freeze["development"]["selected_entries_sha256"],
    }
    drift = {key: [expected[key], value] for key, value in current.items() if value != expected[key]}
    if drift:
        raise V28R2ValidationError(f"V28R2 frozen development drift: {drift}")
    return {
        "verified": True,
        **current,
        "stage_a_freeze_sha256": sha256(v28r2.STAGE_A_FREEZE),
        "development_result_sha256": sha256(v28r2.DEVELOPMENT_RESULT),
    }


def verify_v28r1_diagnostic_identity() -> dict[str, Any]:
    required = [
        Path(v28r1.__file__),
        v28r1.CONTRACT,
        v28r1.SPEC,
        v28r1.DIAGNOSTIC_AUTHORIZATION,
        v28r1.DIAGNOSTIC_STAGE_A_FREEZE,
        v28r1.selected_path("DIAGNOSTIC_2022_2024"),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise V28R2ValidationError(f"missing frozen V28R1 diagnostic identity: {missing}")
    authorization = v28r1.verify_authorization()
    freeze = json.loads(v28r1.DIAGNOSTIC_STAGE_A_FREEZE.read_text(encoding="utf-8"))
    expected = {
        "runner_sha256": freeze.get("runner_sha256"),
        "contract_sha256": freeze.get("contract_sha256"),
        "spec_sha256": freeze.get("spec_sha256"),
        "authorization_sha256": freeze.get("authorization_sha256"),
        "selected_entries_sha256": freeze.get("selected_entries_sha256"),
    }
    current = {
        "runner_sha256": sha256(Path(v28r1.__file__)),
        "contract_sha256": sha256(v28r1.CONTRACT),
        "spec_sha256": sha256(v28r1.SPEC),
        "authorization_sha256": sha256(v28r1.DIAGNOSTIC_AUTHORIZATION),
        "selected_entries_sha256": sha256(v28r1.selected_path("DIAGNOSTIC_2022_2024")),
    }
    drift = {key: [expected[key], value] for key, value in current.items() if value != expected[key]}
    if drift:
        raise V28R2ValidationError(f"V28R1 diagnostic identity drift: {drift}")
    if freeze.get("diagnostic_outcomes_opened") != "NO_IN_THIS_STAGE":
        raise V28R2ValidationError("V28R1 parent identity was not frozen before outcomes")
    return {"verified": True, "authorization": authorization, **current}


def identity_source_hashes() -> dict[str, str]:
    paths = {
        "v28r2_development_runner": Path(v28r2.__file__),
        "v28r2_development_contract": v28r2.CONTRACT,
        "v28r2_development_spec": v28r2.SPEC,
        "v28r2_development_stage_a_freeze": v28r2.STAGE_A_FREEZE,
        "v28r2_development_result": v28r2.DEVELOPMENT_RESULT,
        "v28r2_development_selected_entries": v28r2.selected_path(),
        "v28r1_runner": Path(v28r1.__file__),
        "v28r1_contract": v28r1.CONTRACT,
        "v28r1_spec": v28r1.SPEC,
        "v28r1_diagnostic_authorization": v28r1.DIAGNOSTIC_AUTHORIZATION,
        "v28r1_diagnostic_identity_freeze": v28r1.DIAGNOSTIC_STAGE_A_FREEZE,
        "v28r1_diagnostic_selected_entries": v28r1.selected_path("DIAGNOSTIC_2022_2024"),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V28R2ValidationError(f"missing diagnostic identity source: {missing}")
    return {name: sha256(path) for name, path in paths.items()} | v28r2.verify_registered_cy033(FEATURE_INPUT_YEARS)


def _assert_parent_rule(entries: pd.DataFrame) -> None:
    if (
        "v28r1_demand_not_locked_gate" not in entries
        or "signal_closed_at_up_limit" not in entries
        or not entries.v28r1_demand_not_locked_gate.eq(True).all()  # noqa: E712
        or entries.signal_closed_at_up_limit.eq(True).any()  # noqa: E712
    ):
        raise V28R2ValidationError("frozen V28R1 non-locked-demand invariant failed")


def run_identity_stage() -> dict[str, Any]:
    development = verify_development_lock()
    parent = verify_v28r1_diagnostic_identity()
    entries = pd.read_parquet(v28r1.selected_path("DIAGNOSTIC_2022_2024"))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.loc[entries.signal_date.dt.year.isin(VALIDATION_YEARS)].copy()
    if entries.empty or entries.gap_id.duplicated().any():
        raise V28R2ValidationError("V28R1 validation parent identity failure")
    _assert_parent_rule(entries)
    daily = v28r2.load_cy033_amount_daily(FEATURE_INPUT_YEARS)
    featured = v28r2.attach_orderly_amount_feature(entries, daily)
    selected = featured.loc[featured.v28r2_orderly_amount_gate].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V28R2ValidationError("V28R2 validation identity failure")
    if not selected.signal_date.dt.year.isin(VALIDATION_YEARS).all():
        raise V28R2ValidationError("signal outside the authorized validation years")
    v28.replay.repair.write_parquet(selected, SELECTED)
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    period = {
        "parent_signals": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "selected_by_signal_year": {str(year): int(by_year.get(year, 0)) for year in VALIDATION_YEARS},
        "rejected_amount_above_2x_prior20_median": int(featured.signal_amount_to_prior20_median.gt(v28r2.MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN).sum()),
        "rejected_missing_invalid_or_incomplete_amount_state": int((~featured.prior20_amount_history_complete.eq(True) | ~featured.signal_amount_state_hard_valid.eq(True)).sum()),
        "post_signal_feature_count": int(featured.v28r2_feature_uses_post_signal_information.sum()),
        "selected_entries_sha256": sha256(SELECTED),
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "TEMPORAL_DIAGNOSTIC_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        "fixed_rule": "V28R1 AND signal_amount<=2.0*strict_prior20_median_amount",
        "validation_years": list(VALIDATION_YEARS),
        "runner_sha256": sha256(Path(__file__)),
        "development_lock": development,
        "parent_identity": parent,
        "source_hashes": identity_source_hashes(),
        "diagnostic": period,
        "diagnostic_outcomes_opened": "NO_IN_THIS_STAGE",
        "2025_or_later_data_opened": "NO_IN_THIS_STAGE",
        "rule_change_after_diagnostic": "PROHIBITED",
    }
    write_json(IDENTITY_FREEZE, freeze)
    return freeze


def verify_identity_freeze() -> dict[str, Any]:
    if not IDENTITY_FREEZE.is_file() or not SELECTED.is_file():
        raise V28R2ValidationError("validation identity freeze or selected identity missing")
    freeze = json.loads(IDENTITY_FREEZE.read_text(encoding="utf-8"))
    if freeze.get("diagnostic_outcomes_opened") != "NO_IN_THIS_STAGE":
        raise V28R2ValidationError("identity freeze does not certify unopened outcomes")
    verify_development_lock()
    verify_v28r1_diagnostic_identity()
    current = {
        "runner_sha256": sha256(Path(__file__)),
        "selected_entries_sha256": sha256(SELECTED),
    }
    expected = {
        "runner_sha256": freeze.get("runner_sha256"),
        "selected_entries_sha256": freeze.get("diagnostic", {}).get("selected_entries_sha256"),
    }
    drift = {key: [expected[key], value] for key, value in current.items() if value != expected[key]}
    sources = identity_source_hashes()
    if sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), sources]
    if drift:
        raise V28R2ValidationError(f"validation identity freeze drift: {drift}")
    return {"verified": True, **current, "source_hashes": sources}


def _assert_no_post_2024(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    for column in columns:
        values = pd.to_datetime(frame[column], errors="raise")
        if values.notna().any() and values.max() > VALIDATION_END:
            raise V28R2ValidationError(f"post-2024 value prohibited in {column}")


def select_frozen_outcomes(selected: pd.DataFrame, source: pd.DataFrame) -> pd.DataFrame:
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    outcomes = source.loc[source.gap_id.astype(str).isin(ids)].copy()
    if outcomes.gap_id.duplicated().any() or len(outcomes) != len(ids) or set(outcomes.gap_id.astype(str)) != ids:
        raise V28R2ValidationError("diagnostic outcome identity conservation failure")
    for column in ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if not outcomes.signal_date.dt.year.isin(VALIDATION_YEARS).all():
        raise V28R2ValidationError("outcome source escaped the frozen signal cohort")
    _assert_no_post_2024(outcomes, ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time"))
    if not outcomes.entry_time.gt(outcomes.signal_time).all():
        raise V28R2ValidationError("T+1/next-session entry ordering failure")
    if (
        not outcomes.alpha.eq(0.67).all()
        or not outcomes.horizon.eq(20).all()
        or not outcomes.stop.eq("NONE").all()
        or outcomes.entry_at_or_before_signal.eq(True).any()  # noqa: E712
        or outcomes.buy_at_or_above_up_limit.eq(True).any()  # noqa: E712
    ):
        raise V28R2ValidationError("frozen A67/H20/no-stop/execution semantics drift")
    return outcomes


def frame_digest(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values([column for column in ("symbol", "trade_date") if column in frame], kind="mergesort")
    row_hashes = pd.util.hash_pandas_object(ordered, index=False).to_numpy(dtype=np.uint64)
    return hashlib.sha256(row_hashes.tobytes()).hexdigest()


def _tail_mean(values: pd.Series) -> float:
    count = max(1, math.ceil(len(values) * 0.05))
    return float(values.astype(float).sort_values().iloc[:count].mean())


def detailed_summary(accepted: pd.DataFrame, years: tuple[int, ...]) -> dict[str, Any]:
    work = accepted.copy()
    work["signal_date"] = pd.to_datetime(work.signal_date)
    work["entry_date"] = pd.to_datetime(work.entry_date)

    def one(frame: pd.DataFrame) -> dict[str, Any]:
        if frame.empty:
            return {
                "trades": 0,
                "mean_net": None,
                "median_net": None,
                "win": None,
                "target_hit": None,
                "severe10": None,
                "cvar5": None,
                "worst_net": None,
                "average_holding_sessions": None,
                "median_holding_sessions": None,
                "unique_symbols": 0,
                "unique_entry_dates": 0,
                "exit_reasons": {},
            }
        values = frame.net_return.astype(float)
        return {
            "trades": len(frame),
            "mean_net": float(values.mean()),
            "median_net": float(values.median()),
            "win": float(values.gt(0).mean()),
            "target_hit": float(frame.exit_reason.eq("PRE_L_TARGET").mean()),
            "severe10": float(values.le(-0.10).mean()),
            "cvar5": _tail_mean(values),
            "worst_net": float(values.min()),
            "average_holding_sessions": float(frame.holding_sessions.mean()),
            "median_holding_sessions": float(frame.holding_sessions.median()),
            "unique_symbols": int(frame.symbol.nunique()),
            "unique_entry_dates": int(frame.entry_date.dt.normalize().nunique()),
            "exit_reasons": {str(key): int(value) for key, value in frame.exit_reason.value_counts().items()},
        }

    overall = one(work)
    overall["accepted_trades_per_year"] = len(work) / len(years)
    return {
        "overall": overall,
        "yearly_by_signal_year": {
            str(year): one(work.loc[work.signal_date.dt.year.eq(year)].copy()) for year in years
        },
    }


def _load_validation_daily(max_exit: pd.Timestamp) -> tuple[pd.DataFrame, dict[str, Any]]:
    if max_exit > VALIDATION_END:
        raise V28R2ValidationError("post-2024 outcome tail is not authorized")
    old_path = v28.replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"]
    later_path = v28.V27_LATER_DAILY
    old_daily = pd.read_parquet(old_path)
    later_daily = pd.read_parquet(later_path, filters=[("trade_date", "<=", max_exit.to_pydatetime())])
    daily = pd.concat([old_daily, later_daily], ignore_index=True)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    daily = daily.loc[daily.trade_date.le(max_exit)].copy()
    _assert_no_post_2024(daily, ("trade_date",))
    duplicate = daily.duplicated(["symbol", "trade_date"], keep=False)
    if duplicate.any():
        overlap = daily.loc[duplicate, ["symbol", "trade_date", "open", "high", "low", "close"]]
        inconsistent = overlap.groupby(["symbol", "trade_date"]).nunique(dropna=False).gt(1).any(axis=1)
        if inconsistent.any():
            raise V28R2ValidationError("inconsistent overlapping diagnostic daily rows")
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )
    return daily, {
        "old_daily_path": str(old_path),
        "later_daily_path": str(later_path),
        "later_daily_row_filter": f"trade_date <= {max_exit.date()}",
        "maximum_trade_date_loaded": str(daily.trade_date.max().date()),
        "filtered_daily_rows": len(daily),
        "filtered_daily_digest": frame_digest(daily),
    }


def run_diagnostic() -> dict[str, Any]:
    verification = verify_identity_freeze()
    if not math.isclose(float(v28.replay.repair.v1.COST), 0.002, rel_tol=0.0, abs_tol=1e-12):
        raise V28R2ValidationError("frozen 20bp-per-side cost drift")
    selected = pd.read_parquet(SELECTED)
    source_outcomes_path = v28.diagnostic_lane_root() / "outcomes.parquet"
    source_outcomes = pd.read_parquet(source_outcomes_path)
    outcomes = select_frozen_outcomes(selected, source_outcomes)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    daily, daily_audit = _load_validation_daily(max_exit)
    LANE_ROOT.mkdir(parents=True, exist_ok=True)
    v28.replay.repair.write_parquet(outcomes, LANE_ROOT / "outcomes.parquet")
    old_k = v28.replay.repair.v1.PORTFOLIO_K
    try:
        v28.replay.repair.v1.PORTFOLIO_K = v28.PORTFOLIO_K
        v28.replay.repair.v1.configure_external(LANE_ROOT, max_exit)
        portfolio = v28.replay.repair.v1.run_portfolio(outcomes, daily, VALIDATION_YEARS)
    finally:
        v28.replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(LANE_ROOT / "portfolio_accepted.parquet")
    summary = detailed_summary(accepted, VALIDATION_YEARS)
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_RULE_TEMPORAL_DIAGNOSTIC_NOT_USED_TO_CHANGE_RULE",
        "identity_freeze_verification": verification,
        "fixed_rule": "V28R1 AND signal_amount<=2.0*strict_prior20_median_amount",
        "detailed_summary": summary,
        "portfolio": portfolio,
        "descriptive_goal_checks": {
            "accepted_trades_per_year_gt_50": summary["overall"]["accepted_trades_per_year"] > v28.MIN_ACCEPTED_TRADES_PER_YEAR,
            "mean_net_ge_4pct": summary["overall"]["mean_net"] >= v28.MIN_MEAN_NET,
            "average_holding_sessions_lt_15": summary["overall"]["average_holding_sessions"] < v28.MAX_AVERAGE_HOLDING_SESSIONS,
        },
        "maximum_exit_date_used": str(max_exit.date()),
        "execution_invariants": {
            "entry_strictly_after_signal": True,
            "target": "A67 below L",
            "time_stop": "H20",
            "failure_stop": "NONE",
            "cost_per_side": float(v28.replay.repair.v1.COST),
            "portfolio_k_per_sleeve": v28.PORTFOLIO_K,
        },
        "outcome_sources_opened_after_identity_freeze": {
            "outcomes_path": str(source_outcomes_path),
            "outcomes_sha256": sha256(source_outcomes_path),
            **daily_audit,
        },
        "output_hashes": {
            "outcomes": sha256(LANE_ROOT / "outcomes.parquet"),
            "portfolio_accepted": sha256(LANE_ROOT / "portfolio_accepted.parquet"),
            "portfolio_nav": sha256(LANE_ROOT / "portfolio_nav.parquet"),
        },
        "2025_or_later_data_opened": "NO",
        "rule_changed_after_result": "NO",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    render_report(result)
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def render_report(result: dict[str, Any]) -> None:
    summary = result["detailed_summary"]
    overall = summary["overall"]
    rows = []
    for year in VALIDATION_YEARS:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = "—" if item["average_holding_sessions"] is None else f"{item['average_holding_sessions']:.2f}"
        rows.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['target_hit'])}|{pct(item['severe10'])}|{pct(item['cvar5'])}|{pct(item['worst_net'])}|{hold}|"
        )
    identity = json.loads(IDENTITY_FREEZE.read_text(encoding="utf-8"))["diagnostic"]
    checks = result["descriptive_goal_checks"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "This is the one-way temporal diagnostic of the rule frozen on 2018-2021. The 2022-2024 result is descriptive and did not change the rule.",
        "",
        "Rule: retain every V28R1 condition and require signal-day CY033 raw amount to be no more than 2.0 times the median amount of the 20 completed trading sessions strictly before the signal. Every feature row remains hard-valid and available by decision time.",
        "",
        "## Frozen identity",
        "",
        f"Before outcomes were opened, Stage A retained {identity['selected_signals']} of {identity['parent_signals']} V28R1 signals; {identity['executable_entries']} had frozen executable entries.",
        "",
        "## 2022-2024 exact K80 diagnostic",
        "",
        f"Accepted {overall['trades']} ({overall['accepted_trades_per_year']:.2f}/year), mean {pct(overall['mean_net'])}, median {pct(overall['median_net'])}, win {pct(overall['win'])}, target hit {pct(overall['target_hit'])}, severe10 {pct(overall['severe10'])}, CVaR5 {pct(overall['cvar5'])}, worst {pct(overall['worst_net'])}, average/median hold {overall['average_holding_sessions']:.2f}/{overall['median_holding_sessions']:.2f} sessions.",
        "",
        "|Signal year|Trades|Mean|Median|Win|Target hit|Severe10|CVaR5|Worst|Avg hold|",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"Descriptive goals: frequency >50/year **{checks['accepted_trades_per_year_gt_50']}**; mean ≥4% **{checks['mean_net_ge_4pct']}**; average hold <15 **{checks['average_holding_sessions_lt_15']}**.",
        "",
        f"Exit reasons: {json.dumps(overall['exit_reasons'], ensure_ascii=False, sort_keys=True)}.",
        "",
        "Execution is unchanged: entry strictly after the completed signal, A67 target below L, H20 time stop, no failure stop, 20bp cost per side, and Main/ChiNext K80 per sleeve.",
        "",
        f"Maximum data date used was {result['maximum_exit_date_used']}. No 2025-or-later data were opened.",
        "",
        "This is a frozen-rule temporal diagnostic, not a pristine external validation of the retrospective V27/V28/V28R1 ancestry, and it must not be used to revise V28R2.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stage-a", "diagnostic", "all"), default="all")
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["identity_freeze"] = run_identity_stage()
    if args.mode in ("diagnostic", "all"):
        payload["diagnostic"] = run_diagnostic()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
