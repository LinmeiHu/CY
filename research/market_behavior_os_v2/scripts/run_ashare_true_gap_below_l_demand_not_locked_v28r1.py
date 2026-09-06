#!/usr/bin/env python3
# ruff: noqa: E501
"""Add one causal two-sided-price-discovery gate to the frozen V28 strategy."""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DEMAND-NOT-LOCKED-V28R1"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_demand_not_locked_v28r1"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
DIAGNOSTIC_AUTHORIZATION = OS / f"artifacts/{EXPERIMENT}_diagnostic_authorization.json"
DIAGNOSTIC_STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_diagnostic_stage_a_freeze.json"
DIAGNOSTIC_RESULT = OS / f"artifacts/{EXPERIMENT}_diagnostic_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = v28.DEVELOPMENT_YEARS
DIAGNOSTIC_YEARS = v28.DIAGNOSTIC_YEARS
LIMIT_PRICE_TOLERANCE = 0.006


class V28R1Error(RuntimeError):
    """Fail closed on timing, identity, coverage, or freeze drift."""


def sha256(path: Path) -> str:
    return v28.sha256(path)


def write_json(path: Path, value: Any) -> None:
    v28.write_json(path, value)


def selected_path(label: str) -> Path:
    return EXT_ROOT / label.lower() / "demand_not_locked_selected_entries.parquet"


def lane_root(label: str) -> Path:
    return EXT_ROOT / label.lower() / "demand_not_locked"


def demand_not_locked_mask(frame: pd.DataFrame) -> pd.Series:
    required = frame[
        [
            "signal_raw_close",
            "signal_up_limit_price",
            "signal_price_hard_valid",
            "signal_price_available_by_decision",
        ]
    ]
    return (
        required.notna().all(axis=1)
        & frame.signal_price_hard_valid.eq(True)  # noqa: E712
        & frame.signal_price_available_by_decision.eq(True)  # noqa: E712
        & frame.signal_up_limit_price.gt(0)
        & frame.signal_raw_close.lt(
            frame.signal_up_limit_price - LIMIT_PRICE_TOLERANCE
        )
    )


def attach_signal_price_state(
    entries: pd.DataFrame, years: tuple[int, ...]
) -> pd.DataFrame:
    paths = [v28.cy033_file(year) for year in years]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise V28R1Error(f"missing CY033 partitions: {missing}")
    state = pd.concat(
        [
            pd.read_parquet(
                path,
                columns=[
                    "symbol",
                    "trade_date",
                    "close",
                    "up_limit_price",
                    "hard_valid",
                    "available_at",
                    "snapshot_id",
                ],
            )
            for path in paths
        ],
        ignore_index=True,
    )
    state["trade_date"] = pd.to_datetime(state.trade_date).dt.normalize()
    state["available_at"] = pd.to_datetime(state.available_at)
    if state.duplicated(["symbol", "trade_date"]).any():
        raise V28R1Error("duplicate CY033 signal price state")
    result = entries.copy()
    result["signal_date"] = pd.to_datetime(result.signal_date).dt.normalize()
    result["signal_time"] = pd.to_datetime(result.signal_time)
    state = state.loc[state.symbol.astype(str).isin(set(result.symbol.astype(str)))].rename(
        columns={
            "trade_date": "signal_date",
            "close": "signal_raw_close",
            "up_limit_price": "signal_up_limit_price",
            "hard_valid": "signal_price_hard_valid",
            "available_at": "signal_price_available_at",
            "snapshot_id": "signal_price_snapshot_id",
        }
    )
    result = result.merge(
        state,
        on=["symbol", "signal_date"],
        how="left",
        validate="many_to_one",
    )
    available = result.signal_price_available_at.notna() & result.signal_price_available_at.le(
        result.signal_time
    )
    result["signal_price_available_by_decision"] = available
    result["signal_price_hard_valid"] = result.signal_price_hard_valid.eq(True) & available  # noqa: E712
    result["signal_closed_at_up_limit"] = (
        result.signal_raw_close.notna()
        & result.signal_up_limit_price.notna()
        & result.signal_raw_close.ge(
            result.signal_up_limit_price - LIMIT_PRICE_TOLERANCE
        )
    )
    return result


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "RETROSPECTIVE_ONE_GATE_DEVELOPMENT_WITH_LOCKED_LATER_DIAGNOSTIC",
        "parent": v28.EXPERIMENT,
        "economic_hypothesis": (
            "A genuine demand recapture should finish with two-sided price discovery. "
            "If the signal close remains locked at the daily up limit, the observable "
            "move contains rationed buying and the next-session order chases an exhausted "
            "imbalance rather than entering a newly accepted cost zone."
        ),
        "single_additional_gate": {
            "condition": "signal raw close < registered signal-day up-limit price - 0.006 CNY",
            "known_time": "completed signal close",
            "missing_or_invalid": "fail closed",
            "threshold_search": "NONE; 0.006 is the existing half-fen price-equality tolerance",
        },
        "unchanged": {
            "v28_liquidity_trap_and_non_st_gates": True,
            "v27_M20_F14_R5": True,
            "entry_target_horizon_stop_cost": "unchanged next legal 1m entry/A67/H20/no stop/40bp",
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "execution_lineage_and_T1": "unchanged",
        },
        "development": ["2018-01-01", "2021-12-31"],
        "locked_diagnostic": ["2022-01-01", "2024-12-31"],
        "success": v28.contract_value()["development_success"],
        "governance": {
            "diagnostic_identity_after_development_pass_only": True,
            "diagnostic_outcomes_after_identity_freeze_only": True,
            "post_2021_gate_result_not_used_for_selection": True,
            "parent_v27_and_v28_are_retrospective": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "fixed_rule": "V28 AND signal_close_not_at_up_limit",
            "only_new_degree_of_freedom": "daily exchange up-limit equality using frozen 0.006 tolerance",
            "diagnostic_unlock": "all V28 user goals pass on 2018-2021",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def parent_selected_path(label: str) -> Path:
    if label == "DEVELOPMENT":
        return v28.development_selected_path()
    if label == "DIAGNOSTIC_2022_2024":
        return v28.diagnostic_selected_path()
    raise V28R1Error(f"unknown label: {label}")


def stage_a_source_hashes(label: str, years: tuple[int, ...]) -> dict[str, str]:
    paths: dict[str, Path] = {
        "v28_runner": Path(v28.__file__),
        "v28_contract": v28.CONTRACT,
        "v28_parent_selected_entries": parent_selected_path(label),
    }
    if label == "DEVELOPMENT":
        paths["v28_parent_result"] = v28.DEVELOPMENT_RESULT
        paths["v28_parent_freeze"] = v28.STAGE_A_FREEZE
    else:
        paths["v28_parent_result"] = v28.DIAGNOSTIC_RESULT
        paths["v28_parent_freeze"] = v28.DIAGNOSTIC_STAGE_A_FREEZE
    paths.update({f"cy033_{year}": v28.cy033_file(year) for year in years})
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V28R1Error(f"missing frozen parent source: {missing}")
    return {name: sha256(path) for name, path in paths.items()}


def build_stage_a_period(label: str, years: tuple[int, ...]) -> dict[str, Any]:
    entries = pd.read_parquet(parent_selected_path(label))
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.loc[entries.signal_date.dt.year.isin(years)].copy()
    if entries.empty or entries.gap_id.duplicated().any():
        raise V28R1Error(f"{label} parent identity failure")
    featured = attach_signal_price_state(entries, years)
    featured["v28r1_demand_not_locked_gate"] = demand_not_locked_mask(featured)
    featured["v28r1_feature_latest_timestamp"] = featured.signal_price_available_at
    featured["v28r1_feature_uses_post_signal_information"] = False
    selected = featured.loc[featured.v28r1_demand_not_locked_gate].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V28R1Error(f"{label} selected identity failure")
    v28.replay.repair.write_parquet(selected, selected_path(label))
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    return {
        "parent_signals": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "rejected_signal_close_at_up_limit": int(featured.signal_closed_at_up_limit.sum()),
        "rejected_missing_invalid_or_unavailable": int((~featured.signal_price_hard_valid.eq(True)).sum()),
        "selected_by_signal_year": {str(year): int(by_year.get(year, 0)) for year in years},
        "post_signal_feature_count": int(featured.v28r1_feature_uses_post_signal_information.sum()),
        "selected_entries_sha256": sha256(selected_path(label)),
    }


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    period = build_stage_a_period("DEVELOPMENT", DEVELOPMENT_YEARS)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": stage_a_source_hashes("DEVELOPMENT", DEVELOPMENT_YEARS),
        "development": period,
        "development_outcomes_opened": "NO_IN_THIS_STAGE",
        "post_2021_entries_or_outcomes_opened": "NO_IN_THIS_STAGE",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_freeze(path: Path, label: str, years: tuple[int, ...]) -> dict[str, Any]:
    if not path.is_file():
        raise V28R1Error(f"missing freeze: {path}")
    freeze = json.loads(path.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    expected_selected = (
        freeze["development"]["selected_entries_sha256"]
        if label == "DEVELOPMENT"
        else freeze["selected_entries_sha256"]
    )
    checks["selected_entries_sha256"] = sha256(selected_path(label))
    drift = {
        key: [freeze.get(key), value]
        for key, value in checks.items()
        if key != "selected_entries_sha256" and freeze.get(key) != value
    }
    if checks["selected_entries_sha256"] != expected_selected:
        drift["selected_entries_sha256"] = [expected_selected, checks["selected_entries_sha256"]]
    sources = stage_a_source_hashes(label, years)
    if sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), sources]
    if drift:
        raise V28R1Error(f"freeze drift: {drift}")
    return {"verified": True, "checks": checks}


@contextmanager
def development_runtime() -> Iterator[None]:
    replay = v28.replay
    old_root = replay.EXT_ROOT
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.selected_entries_path = lambda label: selected_path("DEVELOPMENT")
        replay.lane_root = lambda label: lane_root("DEVELOPMENT")
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def run_development() -> dict[str, Any]:
    verification = verify_freeze(STAGE_A_FREEZE, "DEVELOPMENT", DEVELOPMENT_YEARS)
    with development_runtime():
        lane = v28.replay.run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    accepted = pd.read_parquet(lane_root("DEVELOPMENT") / "portfolio_accepted.parquet")
    summary = v28._accepted_summary(accepted, DEVELOPMENT_YEARS)
    checks = v28.development_checks(summary)
    passed = all(checks.values())
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "lane": lane,
        "accepted_summary": summary,
        "goal_checks": checks,
        "selector_passed": passed,
        "verdict": "DEVELOPMENT_PASS_DIAGNOSTIC_AUTHORIZED" if passed else "DEVELOPMENT_FAILED_DIAGNOSTIC_LOCKED",
        "diagnostic_outcomes_opened": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    if passed:
        write_json(
            DIAGNOSTIC_AUTHORIZATION,
            {
                "experiment": EXPERIMENT,
                "development_result_sha256": sha256(DEVELOPMENT_RESULT),
                "contract_sha256": sha256(CONTRACT),
                "spec_sha256": sha256(SPEC),
                "runner_sha256": sha256(Path(__file__)),
                "fixed_rule": "V28 AND signal_close_not_at_up_limit",
                "diagnostic_outcomes_opened": "NO_IN_THIS_STAGE",
            },
        )
    render_report(result, None)
    return result


def verify_authorization() -> dict[str, Any]:
    if not DIAGNOSTIC_AUTHORIZATION.is_file() or not DEVELOPMENT_RESULT.is_file():
        raise V28R1Error("diagnostic authorization missing")
    authorization = json.loads(DIAGNOSTIC_AUTHORIZATION.read_text(encoding="utf-8"))
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    if not development.get("selector_passed"):
        raise V28R1Error("development did not pass")
    checks = {
        "development_result_sha256": sha256(DEVELOPMENT_RESULT),
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {key: [authorization.get(key), value] for key, value in checks.items() if authorization.get(key) != value}
    if drift:
        raise V28R1Error(f"authorization drift: {drift}")
    return authorization


def run_diagnostic_stage_a() -> dict[str, Any]:
    authorization = verify_authorization()
    period = build_stage_a_period("DIAGNOSTIC_2022_2024", DIAGNOSTIC_YEARS)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DIAGNOSTIC_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        "authorization_sha256": sha256(DIAGNOSTIC_AUTHORIZATION),
        "authorization": authorization,
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": stage_a_source_hashes("DIAGNOSTIC_2022_2024", DIAGNOSTIC_YEARS),
        **period,
        "diagnostic_outcomes_opened": "NO_IN_THIS_STAGE",
    }
    write_json(DIAGNOSTIC_STAGE_A_FREEZE, freeze)
    return freeze


def run_diagnostic() -> dict[str, Any]:
    verify_authorization()
    verification = verify_freeze(
        DIAGNOSTIC_STAGE_A_FREEZE,
        "DIAGNOSTIC_2022_2024",
        DIAGNOSTIC_YEARS,
    )
    selected = pd.read_parquet(selected_path("DIAGNOSTIC_2022_2024"))
    executable = selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")].copy()
    ids = set(executable.gap_id.astype(str))
    outcomes = pd.read_parquet(v28.diagnostic_lane_root() / "outcomes.parquet")
    outcomes = outcomes.loc[outcomes.gap_id.astype(str).isin(ids)].copy()
    for column in ("signal_date", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if outcomes.gap_id.duplicated().any() or len(outcomes) != len(ids) or set(outcomes.gap_id.astype(str)) != ids:
        raise V28R1Error("diagnostic outcome identity conservation failure")
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    old_daily = pd.read_parquet(v28.replay.source_paths("POST_OBSERVATION_DIAGNOSTIC")["outcome_daily"])
    later_daily = pd.read_parquet(v28.V27_LATER_DAILY, filters=[("trade_date", "<=", max_exit.to_pydatetime())])
    daily = pd.concat([old_daily, later_daily], ignore_index=True)
    daily["trade_date"] = pd.to_datetime(daily.trade_date)
    duplicate = daily.duplicated(["symbol", "trade_date"], keep=False)
    if duplicate.any():
        overlap = daily.loc[duplicate, ["symbol", "trade_date", "open", "high", "low", "close"]]
        inconsistent = overlap.groupby(["symbol", "trade_date"]).nunique(dropna=False).gt(1).any(axis=1)
        if inconsistent.any():
            raise V28R1Error("inconsistent overlapping daily rows")
    daily = daily.sort_values(["symbol", "trade_date"], kind="mergesort").drop_duplicates(
        ["symbol", "trade_date"], keep="last"
    )
    root = lane_root("DIAGNOSTIC_2022_2024")
    root.mkdir(parents=True, exist_ok=True)
    v28.replay.repair.write_parquet(outcomes, root / "outcomes.parquet")
    old_k = v28.replay.repair.v1.PORTFOLIO_K
    try:
        v28.replay.repair.v1.PORTFOLIO_K = v28.PORTFOLIO_K
        v28.replay.repair.v1.configure_external(root, max_exit)
        portfolio = v28.replay.repair.v1.run_portfolio(
            outcomes,
            daily.loc[daily.trade_date.le(max_exit)].copy(),
            tuple(range(min(DIAGNOSTIC_YEARS), int(max_exit.year) + 1)),
        )
    finally:
        v28.replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    summary = v28._accepted_summary(accepted, DIAGNOSTIC_YEARS)
    result = {
        "experiment": EXPERIMENT,
        "stage_a_verification": verification,
        "accepted_summary": summary,
        "portfolio": portfolio,
        "diagnostic_descriptive_checks": {
            "accepted_trades_per_year_gt_50": summary["accepted_trades_per_year"] > v28.MIN_ACCEPTED_TRADES_PER_YEAR,
            "mean_net_ge_4pct": summary["mean_net"] >= v28.MIN_MEAN_NET,
            "average_holding_sessions_lt_15": summary["average_holding_sessions"] < v28.MAX_AVERAGE_HOLDING_SESSIONS,
        },
        "maximum_exit_date_used": str(max_exit.date()),
        "scientific_status": "LOCKED_POST_OBSERVATION_DIAGNOSTIC_NOT_PRISTINE_EXTERNAL_VALIDATION",
    }
    write_json(DIAGNOSTIC_RESULT, result)
    development = json.loads(DEVELOPMENT_RESULT.read_text(encoding="utf-8"))
    render_report(development, result)
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def summary_rows(summary: dict[str, Any], years: tuple[int, ...]) -> list[str]:
    rows: list[str] = []
    for year in years:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = item["average_holding_sessions"]
        rows.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|"
            f"{pct(item['win'])}|{pct(item['severe10'])}|{'—' if hold is None else f'{hold:.2f}'}|"
        )
    return rows


def render_report(development: dict[str, Any], diagnostic: dict[str, Any] | None) -> None:
    dev = development["accepted_summary"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "Fixed addition to V28: reject a signal whose registered raw close is still at the signal-day up-limit price. The 0.006 CNY equality tolerance is inherited from the existing execution comparisons; no price threshold was searched.",
        "",
        "Economic meaning: demand recapture must end with two-sided price discovery. A locked close reveals rationed buying and makes the next legal session an imbalance chase.",
        "",
        "## Development 2018-2021",
        "",
        f"Accepted {dev['accepted_trades']} ({dev['accepted_trades_per_year']:.2f}/year), mean {pct(dev['mean_net'])}, median {pct(dev['median_net'])}, win {pct(dev['win'])}, severe10 {pct(dev['severe10'])}, average hold {dev['average_holding_sessions']:.2f} sessions.",
        "",
        "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *summary_rows(dev, DEVELOPMENT_YEARS),
        "",
        f"Development passed: **{development['selector_passed']}**.",
    ]
    if diagnostic is not None:
        item = diagnostic["accepted_summary"]
        lines.extend(
            [
                "",
                "## Locked diagnostic 2022-2024",
                "",
                f"Accepted {item['accepted_trades']} ({item['accepted_trades_per_year']:.2f}/year), mean {pct(item['mean_net'])}, median {pct(item['median_net'])}, win {pct(item['win'])}, severe10 {pct(item['severe10'])}, average hold {item['average_holding_sessions']:.2f} sessions.",
                "",
                "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
                "|---:|---:|---:|---:|---:|---:|---:|",
                *summary_rows(item, DIAGNOSTIC_YEARS),
                "",
                "This is not pristine external validation because V27/V28 are retrospective parents.",
            ]
        )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("stage-a", "development", "diagnostic-stage-a", "diagnostic", "all"),
        default="all",
    )
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["stage_a"] = run_stage_a()
    if args.mode in ("development", "all"):
        payload["development"] = run_development()
        if args.mode == "all" and not payload["development"]["selector_passed"]:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            return
    if args.mode in ("diagnostic-stage-a", "all"):
        payload["diagnostic_stage_a"] = run_diagnostic_stage_a()
    if args.mode in ("diagnostic", "all"):
        payload["diagnostic"] = run_diagnostic()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
