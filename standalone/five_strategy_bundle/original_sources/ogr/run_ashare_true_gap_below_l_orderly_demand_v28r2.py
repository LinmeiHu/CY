#!/usr/bin/env python3
# ruff: noqa: E501
"""Test one frozen signal-amount guard on the V28R1 demand-recapture strategy."""

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
    run_ashare_true_gap_below_l_demand_not_locked_v28r1 as v28r1,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_liquidity_trap_guard_v28 as v28,
)

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-ORDERLY-DEMAND-V28R2"
EXT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_orderly_demand_v28r2"
)
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
STAGE_A_FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
DEVELOPMENT_RESULT = OS / f"artifacts/{EXPERIMENT}_development_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"

DEVELOPMENT_YEARS = (2018, 2019, 2020, 2021)
PRIOR_WINDOW = 20
MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN = 2.0
CY033_ASSET_ID = "CY-033"


class V28R2Error(RuntimeError):
    """Fail closed on input governance, timing, history, identity, or freeze drift."""


def sha256(path: Path) -> str:
    return v28.sha256(path)


def write_json(path: Path, value: Any) -> None:
    v28.write_json(path, value)


def selected_path() -> Path:
    return EXT_ROOT / "development/orderly_demand_selected_entries.parquet"


def lane_root() -> Path:
    return EXT_ROOT / "development/orderly_demand"


def parent_selected_path() -> Path:
    return v28r1.selected_path("DEVELOPMENT")


def verify_registered_cy033(years: tuple[int, ...]) -> dict[str, str]:
    """Verify the targeted registry identity and every CY033 partition actually used."""
    registry = json.loads(v28.CY033_REGISTRY.read_text(encoding="utf-8"))
    matches = [item for item in registry.get("assets", []) if item.get("asset_id") == CY033_ASSET_ID]
    if len(matches) != 1:
        raise V28R2Error("CY033 must resolve to exactly one registry entry")
    registered = matches[0]
    if (
        registered.get("status") != "RESEARCH_CONDITIONAL"
        or registered.get("physical_state") != "MATERIALIZED"
        or Path(str(registered.get("location"))) != v28.CY033_ROOT
        or registered.get("lineage", {}).get("record_available_at") is not True
        or registered.get("lineage", {}).get("record_snapshot_id") is not True
    ):
        raise V28R2Error("CY033 registry state does not authorize this research use")

    manifest_path = Path(str(registered.get("lineage", {}).get("manifest_path", "")))
    expected_manifest_hash = registered.get("lineage", {}).get("manifest_sha256")
    if not manifest_path.is_file() or manifest_path != v28.CY033_ROOT / "asset_manifest.json":
        raise V28R2Error("CY033 registered manifest is missing or points elsewhere")
    if not expected_manifest_hash or sha256(manifest_path) != expected_manifest_hash:
        raise V28R2Error("CY033 registered manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("asset_id") != CY033_ASSET_ID or manifest.get("status") != "PASS":
        raise V28R2Error("CY033 asset manifest is not active for conditional research")
    listed = {item.get("path"): item.get("sha256") for item in manifest.get("files", [])}
    verified: dict[str, str] = {}
    for year in years:
        path = v28.cy033_file(year)
        relative = str(path.relative_to(v28.CY033_ROOT))
        if not path.is_file() or not listed.get(relative):
            raise V28R2Error(f"CY033 partition is absent from its manifest: {year}")
        actual = sha256(path)
        if actual != listed[relative]:
            raise V28R2Error(f"CY033 partition hash mismatch: {year}")
        verified[f"cy033_{year}"] = actual
    return {
        "data_asset_registry": sha256(v28.CY033_REGISTRY),
        "cy033_asset_manifest": sha256(manifest_path),
        **verified,
    }


def load_cy033_amount_daily(years: tuple[int, ...]) -> pd.DataFrame:
    verify_registered_cy033(years)
    frame = pd.concat(
        [
            pd.read_parquet(
                v28.cy033_file(year),
                columns=[
                    "symbol",
                    "trade_date",
                    "decision_at",
                    "amount",
                    "trade_status",
                    "hard_valid",
                    "available_at",
                    "snapshot_id",
                ],
            )
            for year in years
        ],
        ignore_index=True,
    )
    frame["trade_date"] = pd.to_datetime(frame.trade_date).dt.normalize()
    frame["decision_at"] = pd.to_datetime(frame.decision_at)
    frame["available_at"] = pd.to_datetime(frame.available_at)
    if frame.duplicated(["symbol", "trade_date"]).any():
        raise V28R2Error("duplicate symbol-date in registered CY033 amount input")
    return frame


def _nonempty_snapshot(values: pd.Series) -> pd.Series:
    return (values.notna() & values.astype("string").str.strip().ne("")).fillna(False)


def attach_orderly_amount_feature(entries: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    """Attach a strict signal/prior-20 amount ratio without using the signal in its baseline."""
    entry_columns = {"gap_id", "symbol", "signal_date", "signal_time"}
    daily_columns = {
        "symbol",
        "trade_date",
        "decision_at",
        "amount",
        "trade_status",
        "hard_valid",
        "available_at",
        "snapshot_id",
    }
    if not entry_columns.issubset(entries.columns) or not daily_columns.issubset(daily.columns):
        raise V28R2Error("missing columns for the orderly-demand amount feature")
    if entries.gap_id.duplicated().any():
        raise V28R2Error("duplicate gap identity in amount-feature input")

    wanted = entries.copy()
    wanted["signal_date"] = pd.to_datetime(wanted.signal_date).dt.normalize()
    wanted["signal_time"] = pd.to_datetime(wanted.signal_time)
    source = daily.copy()
    source["trade_date"] = pd.to_datetime(source.trade_date).dt.normalize()
    source["decision_at"] = pd.to_datetime(source.decision_at)
    source["available_at"] = pd.to_datetime(source.available_at)
    if source.duplicated(["symbol", "trade_date"]).any():
        raise V28R2Error("duplicate symbol-date in amount-feature input")
    source = source.loc[source.symbol.astype(str).isin(set(wanted.symbol.astype(str)))].copy()
    source = source.sort_values(["symbol", "trade_date"], kind="mergesort")
    groups = {str(symbol): group.reset_index(drop=True) for symbol, group in source.groupby("symbol", sort=False)}

    records: list[dict[str, Any]] = []
    for event in wanted[["gap_id", "symbol", "signal_date", "signal_time"]].itertuples(index=False):
        symbol = str(event.symbol)
        group = groups.get(symbol)
        signal = pd.DataFrame() if group is None else group.loc[group.trade_date.eq(event.signal_date)]
        signal_unique = len(signal) == 1
        signal_row = signal.iloc[0] if signal_unique else None
        signal_amount = np.nan if signal_row is None else pd.to_numeric(pd.Series([signal_row.amount]), errors="coerce").iloc[0]
        signal_available = bool(
            signal_row is not None
            and pd.notna(signal_row.available_at)
            and signal_row.available_at <= event.signal_time
            and pd.notna(signal_row.decision_at)
            and signal_row.decision_at <= event.signal_time
        )
        signal_valid = bool(
            signal_row is not None
            and pd.notna(signal_row.hard_valid)
            and bool(signal_row.hard_valid)
            and pd.notna(signal_row.trade_status)
            and float(signal_row.trade_status) == 1.0
            and pd.notna(signal_amount)
            and np.isfinite(float(signal_amount))
            and float(signal_amount) > 0
            and bool(_nonempty_snapshot(pd.Series([signal_row.snapshot_id])).iloc[0])
            and signal_available
        )

        before = pd.DataFrame() if group is None else group.loc[group.trade_date.lt(event.signal_date)]
        traded = before.loc[before.trade_status.eq(1)].tail(PRIOR_WINDOW)
        count = len(traded)
        unknown_between_count = 0
        if count == PRIOR_WINDOW:
            window_start = traded.trade_date.iloc[0]
            between = before.loc[before.trade_date.ge(window_start)]
            unknown_between_count = int((~between.trade_status.isin([0, 1])).sum())
        amounts = pd.to_numeric(traded.amount, errors="coerce")
        finite_positive = bool(
            count == PRIOR_WINDOW
            and np.isfinite(amounts.to_numpy(dtype=float)).all()
            and amounts.gt(0).all()
        )
        history_valid = bool(
            count == PRIOR_WINDOW
            and unknown_between_count == 0
            and traded.hard_valid.eq(True).all()  # noqa: E712
            and traded.available_at.notna().all()
            and traded.available_at.le(event.signal_time).all()
            and traded.decision_at.notna().all()
            and traded.decision_at.le(event.signal_time).all()
            and _nonempty_snapshot(traded.snapshot_id).all()
            and finite_positive
        )
        median_amount = float(amounts.median()) if history_valid else np.nan
        latest_values = []
        if signal_row is not None and pd.notna(signal_row.available_at):
            latest_values.append(signal_row.available_at)
        latest_values.extend(traded.available_at.dropna().tolist())
        records.append(
            {
                "gap_id": event.gap_id,
                "signal_raw_amount": float(signal_amount) if pd.notna(signal_amount) else np.nan,
                "signal_amount_state_hard_valid": signal_valid,
                "signal_amount_available_by_decision": signal_available,
                "signal_amount_snapshot_id": None if signal_row is None else signal_row.snapshot_id,
                "prior20_completed_trading_sessions": count,
                "prior20_unknown_trading_state_rows": unknown_between_count,
                "prior20_hard_valid_sessions": int(traded.hard_valid.eq(True).sum()),  # noqa: E712
                "prior20_available_by_decision_sessions": int(
                    (traded.available_at.notna() & traded.available_at.le(event.signal_time)).sum()
                ),
                "prior20_finite_positive_amount_sessions": int(
                    (amounts.notna() & amounts.gt(0) & np.isfinite(amounts)).sum()
                ),
                "prior20_amount_history_complete": history_valid,
                "prior20_median_amount": median_amount,
                "signal_amount_to_prior20_median": (
                    float(signal_amount) / median_amount
                    if signal_valid and history_valid and median_amount > 0
                    else np.nan
                ),
                "v28r2_feature_latest_timestamp": max(latest_values) if latest_values else pd.NaT,
            }
        )
    result = wanted.merge(pd.DataFrame.from_records(records), on="gap_id", how="left", validate="one_to_one")
    result["v28r2_orderly_amount_gate"] = orderly_amount_mask(result)
    result["v28r2_feature_uses_post_signal_information"] = False
    return result


def orderly_amount_mask(frame: pd.DataFrame) -> pd.Series:
    required = frame[
        [
            "signal_raw_amount",
            "signal_amount_state_hard_valid",
            "signal_amount_available_by_decision",
            "prior20_completed_trading_sessions",
            "prior20_amount_history_complete",
            "prior20_median_amount",
            "signal_amount_to_prior20_median",
        ]
    ]
    return (
        required.notna().all(axis=1)
        & frame.signal_amount_state_hard_valid.eq(True)  # noqa: E712
        & frame.signal_amount_available_by_decision.eq(True)  # noqa: E712
        & frame.prior20_completed_trading_sessions.eq(PRIOR_WINDOW)
        & frame.prior20_amount_history_complete.eq(True)  # noqa: E712
        & frame.signal_raw_amount.gt(0)
        & frame.prior20_median_amount.gt(0)
        & frame.signal_amount_to_prior20_median.le(MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN)
    )


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_SECOND_DEVELOPMENT_CANDIDATE_LATER_DATA_LOCKED",
        "parent": v28r1.EXPERIMENT,
        "economic_hypothesis": (
            "A recovered key cost zone is more credible when buyers regain it through orderly "
            "two-sided trade. Signal-day value above twice the stock's own preceding-month median "
            "is more likely to be a crowded terminal scramble whose next-session entry pays for "
            "already-realized demand rather than fresh acceptance."
        ),
        "single_additional_gate": {
            "condition": "signal-day amount <= 2.0 * median(amount over the 20 completed trading sessions strictly before the signal)",
            "input": "registered CY033 raw CNY amount only",
            "signal_day_in_baseline": False,
            "coverage": "exactly 20 completed trading sessions; every row hard_valid with snapshot_id and available_at<=decision_at",
            "missing_invalid_or_unknown": "fail closed",
            "threshold_search": "NONE_IN_THIS_RUN; 2.0 was frozen before outcome replay",
        },
        "retained_parent_gate": "V28R1 signal close strictly below registered up-limit by more than 0.006 CNY",
        "unchanged": {
            "v28_liquidity_trap_and_non_st_gates": True,
            "v27_M20_F14_R5": True,
            "entry_target_horizon_stop_cost": "unchanged next legal 1m entry/A67/H20/no stop/40bp",
            "portfolio": "Main/ChiNext 50/50; K80 per sleeve",
            "execution_lineage_and_T1": "unchanged",
        },
        "development": ["2018-01-01", "2021-12-31"],
        "success": v28.contract_value()["development_success"],
        "governance": {
            "identity_frozen_before_development_outcome_open": True,
            "post_2021_entries_and_outcomes_opened": False,
            "later_diagnostic_authorization_created": False,
            "parent_v27_v28_v28r1_are_retrospective": True,
        },
    }


def persist_contracts() -> dict[str, str]:
    write_json(CONTRACT, contract_value())
    write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "contract_sha256": sha256(CONTRACT),
            "fixed_rule": "V28R1 AND signal_amount<=2.0*strict_prior20_median_amount",
            "only_new_degree_of_freedom": "frozen 2.0 signal amount multiple",
            "data_boundary": "2018-2021 development only; no later diagnostic modes exist in this runner",
        },
    )
    return {"contract_sha256": sha256(CONTRACT), "spec_sha256": sha256(SPEC)}


def source_hashes() -> dict[str, str]:
    paths = {
        "v28r1_runner": Path(v28r1.__file__),
        "v28r1_contract": v28r1.CONTRACT,
        "v28r1_spec": v28r1.SPEC,
        "v28r1_development_freeze": v28r1.STAGE_A_FREEZE,
        "v28r1_development_selected_entries": parent_selected_path(),
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise V28R2Error(f"missing frozen V28R1 parent source: {missing}")
    return {name: sha256(path) for name, path in paths.items()} | verify_registered_cy033(DEVELOPMENT_YEARS)


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contracts()
    entries = pd.read_parquet(parent_selected_path())
    for column in ("signal_date", "signal_time", "entry_date", "entry_time"):
        entries[column] = pd.to_datetime(entries[column])
    entries = entries.loc[entries.signal_date.dt.year.isin(DEVELOPMENT_YEARS)].copy()
    if entries.empty or entries.gap_id.duplicated().any():
        raise V28R2Error("V28R1 development parent identity failure")
    if (
        "v28r1_demand_not_locked_gate" not in entries
        or not entries.v28r1_demand_not_locked_gate.eq(True).all()  # noqa: E712
        or entries.signal_closed_at_up_limit.eq(True).any()  # noqa: E712
    ):
        raise V28R2Error("V28R1 non-locked-demand parent invariant failed")
    daily = load_cy033_amount_daily(DEVELOPMENT_YEARS)
    featured = attach_orderly_amount_feature(entries, daily)
    selected = featured.loc[featured.v28r2_orderly_amount_gate].copy()
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort").reset_index(drop=True)
    if selected.empty or selected.gap_id.duplicated().any():
        raise V28R2Error("V28R2 development identity failure")
    v28.replay.repair.write_parquet(selected, selected_path())
    by_year = selected.groupby(selected.signal_date.dt.year).size()
    period = {
        "parent_signals": len(entries),
        "selected_signals": len(selected),
        "executable_entries": int(selected.entry_status.eq("EXECUTABLE_ENTRY").sum()),
        "selected_by_signal_year": {str(year): int(by_year.get(year, 0)) for year in DEVELOPMENT_YEARS},
        "rejected_amount_above_2x_prior20_median": int(featured.signal_amount_to_prior20_median.gt(MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN).sum()),
        "rejected_missing_invalid_or_incomplete_amount_state": int((~featured.prior20_amount_history_complete.eq(True) | ~featured.signal_amount_state_hard_valid.eq(True)).sum()),
        "post_signal_feature_count": int(featured.v28r2_feature_uses_post_signal_information.sum()),
        "selected_entries_sha256": sha256(selected_path()),
    }
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "DEVELOPMENT_IDENTITY_FREEZE_BEFORE_OUTCOME_OPEN",
        **hashes,
        "runner_sha256": sha256(Path(__file__)),
        "source_hashes": source_hashes(),
        "development": period,
        "development_outcomes_opened": "NO_IN_THIS_STAGE",
        "post_2021_entries_or_outcomes_opened": "NO_IN_THIS_STAGE",
    }
    write_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> dict[str, Any]:
    if not STAGE_A_FREEZE.is_file():
        raise V28R2Error("development Stage-A freeze missing")
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))
    checks = {
        "contract_sha256": sha256(CONTRACT),
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
    }
    drift = {key: [freeze.get(key), value] for key, value in checks.items() if freeze.get(key) != value}
    current_sources = source_hashes()
    if current_sources != freeze.get("source_hashes"):
        drift["source_hashes"] = [freeze.get("source_hashes"), current_sources]
    selected_hash = sha256(selected_path())
    if selected_hash != freeze.get("development", {}).get("selected_entries_sha256"):
        drift["selected_entries_sha256"] = [freeze.get("development", {}).get("selected_entries_sha256"), selected_hash]
    if drift:
        raise V28R2Error(f"development Stage-A drift: {drift}")
    return {"verified": True, "checks": checks}


@contextmanager
def development_runtime() -> Iterator[None]:
    replay = v28.replay
    old_root = replay.EXT_ROOT
    old_selected = replay.selected_entries_path
    old_lane = replay.lane_root
    try:
        replay.EXT_ROOT = EXT_ROOT
        replay.selected_entries_path = lambda label: selected_path()
        replay.lane_root = lambda label: lane_root()
        yield
    finally:
        replay.EXT_ROOT = old_root
        replay.selected_entries_path = old_selected
        replay.lane_root = old_lane


def run_development() -> dict[str, Any]:
    verification = verify_stage_a()
    with development_runtime():
        lane = v28.replay.run_lane("DEVELOPMENT", DEVELOPMENT_YEARS)
    accepted = pd.read_parquet(lane_root() / "portfolio_accepted.parquet")
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
        "verdict": "DEVELOPMENT_PASS_LATER_DATA_REMAINS_LOCKED" if passed else "DEVELOPMENT_FAILED_LATER_DATA_REMAINS_LOCKED",
        "development_outcomes_opened": "YES",
        "post_2021_entries_or_outcomes_opened": "NO",
        "diagnostic_authorization_created": "NO",
    }
    write_json(DEVELOPMENT_RESULT, result)
    render_report(result)
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def render_report(result: dict[str, Any]) -> None:
    summary = result["accepted_summary"]
    rows = []
    for year in DEVELOPMENT_YEARS:
        item = summary["yearly_by_signal_year"][str(year)]
        hold = item["average_holding_sessions"]
        rows.append(
            f"|{year}|{item['trades']}|{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|{pct(item['severe10'])}|{'—' if hold is None else f'{hold:.2f}'}|"
        )
    freeze = json.loads(STAGE_A_FREEZE.read_text(encoding="utf-8"))["development"]
    lines = [
        f"# {EXPERIMENT}",
        "",
        "Frozen addition to V28R1: signal-day raw amount must be no more than 2.0 times the median raw amount of the 20 completed trading sessions strictly before the signal. The signal session is excluded from its own baseline.",
        "",
        "Economic meaning: a regained cost zone should show orderly, two-sided demand. An extreme value burst can be a crowded terminal scramble, leaving the next legal entry to pay for demand already spent.",
        "",
        "Every signal and history row comes from registered CY033, must be hard-valid, hash-bound, and available by the signal decision. Missing history, nonpositive amount, unknown trading state, or missing lineage rejects the signal.",
        "",
        "## Development 2018-2021",
        "",
        f"Stage A retained {freeze['selected_signals']} of {freeze['parent_signals']} V28R1 signals before outcomes were opened.",
        "",
        f"Exact K80 accepted {summary['accepted_trades']} ({summary['accepted_trades_per_year']:.2f}/year), mean {pct(summary['mean_net'])}, median {pct(summary['median_net'])}, win {pct(summary['win'])}, severe10 {pct(summary['severe10'])}, average hold {summary['average_holding_sessions']:.2f} sessions.",
        "",
        "|Signal year|Trades|Mean|Median|Win|Severe10|Avg hold|",
        "|---:|---:|---:|---:|---:|---:|---:|",
        *rows,
        "",
        f"Development passed: **{result['selector_passed']}**.",
        "",
        "No post-2021 entries or outcomes were read, no later identity was built, and no diagnostic authorization was created.",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("stage-a", "development", "all"), default="all")
    args = parser.parse_args()
    payload: dict[str, Any] = {}
    if args.mode in ("stage-a", "all"):
        payload["stage_a"] = run_stage_a()
    if args.mode in ("development", "all"):
        payload["development"] = run_development()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
