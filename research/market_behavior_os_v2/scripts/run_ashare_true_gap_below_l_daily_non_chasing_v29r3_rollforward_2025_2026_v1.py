#!/usr/bin/env python3
"""Apply the frozen V29R3 rule to complete 2025 and mature 2026-YTD evidence.

Stage A constructs identities only. Stage B verifies that freeze, attaches the
already-frozen V27 execution outcomes, reruns unchanged K80 capacity, and joins
the result to the immutable 2018-2024 V29R3 history. Existing results are never
overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_true_gap_below_l_daily_non_chasing_v29r3_validation_2022_2024 as v29r3,
)
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
OS_ROOT = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-TRUE-GAP-BELOW-L-DAILY-NON-CHASING-V29R3-ROLLFORWARD-2025-2026-V1"
SPEC = OS_ROOT / f"experiments/{EXPERIMENT}_spec.json"
RESULT = OS_ROOT / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS_ROOT / f"reports/{EXPERIMENT}_report.md"
OUTPUT_ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_true_gap_below_l_daily_non_chasing_v29r3_rollforward_2025_2026_v1"
)
STAGE_A = OUTPUT_ROOT / "stage_a"
STAGE_A_SELECTED = STAGE_A / "selected_signals.parquet"
STAGE_A_FREEZE = STAGE_A / "freeze.json"
STAGE_B = OUTPUT_ROOT / "stage_b"

V28R2_DEV_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_orderly_demand_v28r2/"
    "development/orderly_demand_selected_entries.parquet"
)
V29R3_DEV_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_non_chasing_k80_capacity_"
    "diagnostic_v1/v28r2_parent_plus_non_chasing/full/portfolio_accepted.parquet"
)
V29R3_VALIDATION_SELECTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_daily_non_chasing_"
    "v29r3_validation_2022_2024/stage_a/selected_identity.parquet"
)
V29R3_VALIDATION_ACCEPTED = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_daily_non_chasing_"
    "v29r3_validation_2022_2024/stage_b/full/portfolio_accepted.parquet"
)
V27_2025_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_fresh_capitulation_"
    "snapback_v27_diagnostic_2024_2025_v1/diagnostic_2024_2025"
)
V27_2026_ROOT = Path(
    "/Volumes/quant/CY_quant_research/ashare_true_gap_below_l_fresh_capitulation_"
    "snapback_v27_diagnostic_2026ytd_v1/diagnostic_2026ytd"
)
V27_2025_ENTRIES = V27_2025_ROOT / "entries.parquet"
V27_2025_OUTCOMES = V27_2025_ROOT / "outcomes.parquet"
V27_2025_DAILY = V27_2025_ROOT / "outcome_daily.parquet"
V27_2026_ENTRIES = V27_2026_ROOT / "entries.parquet"
V27_2026_OUTCOMES = V27_2026_ROOT / "outcomes.parquet"
V27_2026_DAILY = V27_2026_ROOT / "outcome_daily.parquet"

YEARS = tuple(range(2018, 2027))
NEW_YEARS = (2025, 2026)
DATA_END = pd.Timestamp("2026-09-04")
MATURE_2026_SIGNAL_END = pd.Timestamp("2026-08-03 23:59:59")
EXPECTED = {
    "v28r2_dev_selected": "963aaae2053c4b62a5060931c757a51bc7776324f14089d4def5502db9e6d112",
    "v29r3_dev_accepted": "dbbd1900999bdea08d4ae4fbae4784ac588f0bdd5ac4f4da85a5f6931528e9a1",
    "v29r3_validation_selected": "a75a789da720d6b91f1a49f14516547fbfdcdb887aae2e648d430c80d4de04ac",
    "v29r3_validation_accepted": "da57f739cdc23eb620f524dd8e0cb04a92bfd92f60e56f486dcdafb8efd4ff25",
    "v27_2025_entries": "bda4fac645192dedf0cf3574555993fd83b2c7512196abc4f5a286ea0adc747a",
    "v27_2025_outcomes": "a2ffbe9e7f08f1b554f9ee601724bc5c2ebd7b51f3249c300af24e25000dbde6",
    "v27_2025_daily": "265f1a5d65099694b0a87ac6418cca61006be89d0df1e6c1d5ed5678c38ef7b0",
    "v27_2026_entries": "62c2f475c3a09d18b4524933fcf14bb69149f7f236d3e4af33d8c188b2579b69",
    "v27_2026_outcomes": "29c10f6e04e3f18949a53214ada7f9ffbb2b3b501a31976871ab485699503f2a",
    "v27_2026_daily": "5766eec79c790b969be593b64a2d5c8935b82b8605e5bccf2412b62686e56d47",
}


class RollforwardError(RuntimeError):
    """Fail closed on rule, identity, PIT, execution, or publication drift."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RollforwardError(f"JSON root is not an object: {path}")
    return value


def atomic_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def write_parquet(frame: pd.DataFrame, path: Path) -> None:
    v28.replay.repair.write_parquet(frame, path)


def assert_hash(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256(path) != expected:
        raise RollforwardError(f"missing or drifting frozen input {label}: {path}")


def verify_rule_and_daily() -> dict[str, str]:
    if not SPEC.is_file():
        raise RollforwardError("frozen rollforward specification is missing")
    spec = read_json(SPEC)
    if (
        spec.get("experiment") != EXPERIMENT
        or spec.get("fixed_rule", {}).get("parameter_change_count") != 0
        or spec.get("rollforward_scope", {}).get("development_or_threshold_selection_allowed")
        is not False
        or v29r3.THRESHOLD != 0.02
        or v28.MAX_PRIOR_ONE_PRICE_LIMIT_DOWNS != 1
        or v28r1.LIMIT_PRICE_TOLERANCE != 0.006
        or v28r2.MAX_SIGNAL_AMOUNT_TO_PRIOR_MEDIAN != 2.0
        or v28.PORTFOLIO_K != 80
        or not math.isclose(float(v28.replay.repair.v1.COST), 0.002, abs_tol=1e-12)
    ):
        raise RollforwardError("frozen V29R3 rule constants drifted")
    registered = v28r2.verify_registered_cy033(YEARS)
    expected_partitions = spec["input_governance"]["daily_partition_sha256"]
    for year in YEARS:
        if registered[f"cy033_{year}"] != expected_partitions[str(year)]:
            raise RollforwardError(f"CY-033 partition drift: {year}")
    if registered["cy033_asset_manifest"] != spec["input_governance"][
        "registered_daily_manifest_sha256"
    ]:
        raise RollforwardError("CY-033 manifest drift")
    return registered


def load_market_daily(years: tuple[int, ...]) -> pd.DataFrame:
    columns = [
        "symbol",
        "trade_date",
        "decision_at",
        "close",
        "preclose",
        "trade_status",
        "hard_valid",
        "current_day_data_tradable",
        "available_at",
        "snapshot_id",
    ]
    return pd.concat(
        [pd.read_parquet(v28.cy033_file(year), columns=columns) for year in years],
        ignore_index=True,
    )


def yearly_count(frame: pd.DataFrame) -> dict[str, int]:
    dates = pd.to_datetime(frame.signal_date)
    counts = frame.groupby(dates.dt.year).size()
    return {str(year): int(counts.get(year, 0)) for year in YEARS}


def build_stage_a() -> dict[str, Any]:
    if OUTPUT_ROOT.exists():
        raise RollforwardError(f"independent output root already exists: {OUTPUT_ROOT}")
    registered = verify_rule_and_daily()
    identity_inputs = {
        "v28r2_dev_selected": V28R2_DEV_SELECTED,
        "v29r3_validation_selected": V29R3_VALIDATION_SELECTED,
        "v27_2025_entries": V27_2025_ENTRIES,
        "v27_2026_entries": V27_2026_ENTRIES,
    }
    for label, path in identity_inputs.items():
        assert_hash(path, EXPECTED[label], label)

    # Recompute the frozen 2% feature for all V28R2 development signals. The
    # executable subset must reproduce the original 265 fixed-trade identities.
    development_parent = pd.read_parquet(V28R2_DEV_SELECTED)
    development = v29r3.attach_daily_non_chasing_feature(
        development_parent, load_market_daily((2018, 2019, 2020, 2021))
    )
    development = development.loc[development.v29r3_daily_non_chasing_2pct_gate].copy()
    fixed = pd.read_parquet(
        V29R3_DEV_ACCEPTED.parent / "fixed_trades.parquet", columns=["gap_id"]
    )
    computed_ids = set(
        development.loc[development.entry_status.eq("EXECUTABLE_ENTRY"), "gap_id"].astype(str)
    )
    if computed_ids != set(fixed.gap_id.astype(str)) or len(computed_ids) != 265:
        raise RollforwardError("2018-2021 frozen executable V29R3 identity did not reproduce")

    validation = pd.read_parquet(V29R3_VALIDATION_SELECTED)
    if len(validation) != 63 or validation.gap_id.astype(str).duplicated().any():
        raise RollforwardError("2022-2024 frozen V29R3 identity drift")

    entries_2025 = pd.read_parquet(V27_2025_ENTRIES)
    entries_2025 = entries_2025.loc[pd.to_datetime(entries_2025.signal_date).dt.year.eq(2025)]
    entries_2026 = pd.read_parquet(V27_2026_ENTRIES)
    entries_2026 = entries_2026.loc[pd.to_datetime(entries_2026.signal_date).dt.year.eq(2026)]
    new_parent = pd.concat([entries_2025, entries_2026], ignore_index=True)
    if (
        len(entries_2025) != 44
        or len(entries_2026) != 43
        or new_parent.gap_id.astype(str).duplicated().any()
        or pd.to_datetime(entries_2026.signal_time).max() > MATURE_2026_SIGNAL_END
    ):
        raise RollforwardError("frozen V27 2025/2026 parent identity drift")

    feature_daily = v28.load_cy033_feature_daily(NEW_YEARS)
    after_v28 = v28.attach_prior_limit_down_feature(new_parent, feature_daily)
    after_v28 = v28.load_signal_state(after_v28, NEW_YEARS)
    after_v28 = after_v28.loc[v28.v28_admission_mask(after_v28)].copy()
    after_v28r1 = v28r1.attach_signal_price_state(after_v28, NEW_YEARS)
    after_v28r1 = after_v28r1.loc[v28r1.demand_not_locked_mask(after_v28r1)].copy()
    amount_daily = v28r2.load_cy033_amount_daily((2024, 2025, 2026))
    after_v28r2 = v28r2.attach_orderly_amount_feature(after_v28r1, amount_daily)
    after_v28r2 = after_v28r2.loc[after_v28r2.v28r2_orderly_amount_gate].copy()
    featured = v29r3.attach_daily_non_chasing_feature(
        after_v28r2, load_market_daily(NEW_YEARS)
    )
    rollforward = featured.loc[featured.v29r3_daily_non_chasing_2pct_gate].copy()
    rollforward = rollforward.sort_values(
        ["signal_time", "symbol", "gap_id"], kind="mergesort"
    )
    if rollforward.empty or rollforward.gap_id.astype(str).duplicated().any():
        raise RollforwardError("empty or duplicate V29R3 rollforward identity")

    selected = pd.concat([development, validation, rollforward], ignore_index=True)
    selected["signal_date"] = pd.to_datetime(selected.signal_date).dt.normalize()
    selected["signal_time"] = pd.to_datetime(selected.signal_time)
    selected = selected.sort_values(["signal_time", "symbol", "gap_id"], kind="mergesort")
    if selected.gap_id.astype(str).duplicated().any():
        raise RollforwardError("2018-2026 selected identity collision")

    stage_counts = {
        "v27": yearly_count(new_parent),
        "v28": yearly_count(after_v28),
        "v28r1": yearly_count(after_v28r1),
        "v28r2": yearly_count(after_v28r2),
        "v29r3": yearly_count(rollforward),
    }
    STAGE_A.mkdir(parents=True, exist_ok=False)
    write_parquet(selected, STAGE_A_SELECTED)
    freeze = {
        "experiment": EXPERIMENT,
        "stage": "IDENTITY_FREEZE_BEFORE_ROLLFORWARD_OUTCOME_ATTACHMENT",
        "scientific_status": "FROZEN_RULE_POST_OBSERVATION_ROLLFORWARD_DIAGNOSTIC_NOT_PRISTINE_OOS",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "cy033_manifest_sha256": registered["cy033_asset_manifest"],
        "cy033_partition_hashes": {
            str(year): registered[f"cy033_{year}"] for year in YEARS
        },
        "identity_input_hashes": {label: sha256(path) for label, path in identity_inputs.items()},
        "reproduction": {
            "development_executable_ids_computed": len(computed_ids),
            "development_frozen_fixed_ids": len(fixed),
            "development_id_symmetric_difference": 0,
        },
        "rollforward_gate_counts": stage_counts,
        "annual_signals": yearly_count(selected),
        "annual_executable_entries": yearly_count(
            selected.loc[selected.entry_status.eq("EXECUTABLE_ENTRY")]
        ),
        "selected_path": str(STAGE_A_SELECTED),
        "selected_sha256": sha256(STAGE_A_SELECTED),
        "outcome_rows_read_in_this_stage": False,
        "data_end": str(DATA_END.date()),
        "mature_2026_signal_end": str(MATURE_2026_SIGNAL_END.date()),
    }
    atomic_json(STAGE_A_FREEZE, freeze)
    return freeze


def verify_stage_a() -> tuple[dict[str, Any], pd.DataFrame]:
    verify_rule_and_daily()
    if not STAGE_A_FREEZE.is_file() or not STAGE_A_SELECTED.is_file():
        raise RollforwardError("Stage-A freeze is missing")
    freeze = read_json(STAGE_A_FREEZE)
    if (
        freeze.get("stage") != "IDENTITY_FREEZE_BEFORE_ROLLFORWARD_OUTCOME_ATTACHMENT"
        or freeze.get("spec_sha256") != sha256(SPEC)
        or freeze.get("runner_sha256") != sha256(Path(__file__))
        or freeze.get("selected_sha256") != sha256(STAGE_A_SELECTED)
        or freeze.get("outcome_rows_read_in_this_stage") is not False
    ):
        raise RollforwardError("Stage-A freeze drift")
    selected = pd.read_parquet(STAGE_A_SELECTED)
    if len(selected) != sum(freeze["annual_signals"].values()):
        raise RollforwardError("Stage-A selected row conservation failed")
    return freeze, selected


def select_outcomes(selected: pd.DataFrame, source: pd.DataFrame, year: int) -> pd.DataFrame:
    chosen = selected.loc[
        pd.to_datetime(selected.signal_date).dt.year.eq(year)
        & selected.entry_status.eq("EXECUTABLE_ENTRY")
    ].copy()
    ids = set(chosen.gap_id.astype(str))
    outcomes = source.loc[source.gap_id.astype(str).isin(ids)].copy()
    if len(outcomes) != len(ids) or outcomes.gap_id.astype(str).duplicated().any():
        raise RollforwardError(f"outcome identity conservation failed for {year}")
    left = chosen[["gap_id", "symbol", "signal_date", "signal_time", "entry_date", "entry_time"]]
    right = outcomes[["gap_id", "symbol", "signal_date", "signal_time", "entry_date", "entry_time"]]
    joined = left.merge(right, on="gap_id", suffixes=("_selected", "_outcome"), validate="one_to_one")
    for column in ("symbol", "signal_date", "signal_time", "entry_date", "entry_time"):
        a = joined[f"{column}_selected"]
        b = joined[f"{column}_outcome"]
        if column != "symbol":
            a, b = pd.to_datetime(a), pd.to_datetime(b)
        else:
            a, b = a.astype(str), b.astype(str)
        if not a.eq(b).all():
            raise RollforwardError(f"selected/outcome {column} mismatch in {year}")
    for column in ("signal_date", "signal_time", "entry_date", "entry_time", "exit_date", "exit_time"):
        outcomes[column] = pd.to_datetime(outcomes[column])
    if (
        not outcomes.entry_time.gt(outcomes.signal_time).all()
        or not outcomes.exit_time.ge(outcomes.entry_time).all()
        or not outcomes.alpha.eq(0.67).all()
        or not outcomes.horizon.eq(20).all()
        or not outcomes.stop.eq("NONE").all()
        or outcomes.entry_at_or_before_signal.eq(True).any()
        or outcomes.buy_at_or_above_up_limit.eq(True).any()
    ):
        raise RollforwardError(f"execution invariant drift in {year}")
    return outcomes.sort_values(["entry_time", "symbol", "gap_id"], kind="mergesort")


def stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "accepted": 0,
            "completed": 0,
            "mean_net": None,
            "median_net": None,
            "win": None,
            "severe10": None,
            "mean_holding_sessions": None,
            "median_holding_sessions": None,
            "exit_reasons": {},
        }
    values = frame.net_return.astype(float)
    completed = int(frame.completed.eq(True).sum()) if "completed" in frame else len(frame)
    return {
        "accepted": len(frame),
        "completed": completed,
        "mean_net": float(values.mean()),
        "median_net": float(values.median()),
        "win": float(values.gt(0).mean()),
        "severe10": float(values.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
        "exit_reasons": {
            str(key): int(value) for key, value in frame.exit_reason.value_counts().items()
        },
    }


def run_new_year(selected: pd.DataFrame, year: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    if year == 2025:
        source_path, daily_path = V27_2025_OUTCOMES, V27_2025_DAILY
    else:
        source_path, daily_path = V27_2026_OUTCOMES, V27_2026_DAILY
    source = pd.read_parquet(source_path)
    outcomes = select_outcomes(selected, source, year)
    max_exit = pd.Timestamp(outcomes.exit_date.max()).normalize()
    daily = pd.read_parquet(daily_path, filters=[("trade_date", "<=", max_exit.to_pydatetime())])
    daily["trade_date"] = pd.to_datetime(daily.trade_date).dt.normalize()
    if daily.empty or daily.trade_date.max() > DATA_END:
        raise RollforwardError(f"daily outcome support drift in {year}")
    root = STAGE_B / f"signal_year={year}"
    root.mkdir(parents=True, exist_ok=False)
    write_parquet(outcomes, root / "outcomes.parquet")
    old_k = v28.replay.repair.v1.PORTFOLIO_K
    try:
        v28.replay.repair.v1.PORTFOLIO_K = 80
        v28.replay.repair.v1.configure_external(root, max_exit)
        audit = v28.replay.repair.v1.run_portfolio(outcomes, daily, (year,))
    finally:
        v28.replay.repair.v1.PORTFOLIO_K = old_k
    accepted = pd.read_parquet(root / "portfolio_accepted.parquet")
    if len(accepted) > len(outcomes) or not accepted.completed.eq(True).all():
        raise RollforwardError(f"portfolio completion/capacity failure in {year}")
    return accepted, audit


def run_stage_b() -> dict[str, Any]:
    freeze, selected = verify_stage_a()
    if STAGE_B.exists() or RESULT.exists() or REPORT.exists():
        raise RollforwardError("Stage-B publication already exists; overwrite prohibited")
    outcome_inputs = {
        "v29r3_dev_accepted": V29R3_DEV_ACCEPTED,
        "v29r3_validation_accepted": V29R3_VALIDATION_ACCEPTED,
        "v27_2025_outcomes": V27_2025_OUTCOMES,
        "v27_2025_daily": V27_2025_DAILY,
        "v27_2026_outcomes": V27_2026_OUTCOMES,
        "v27_2026_daily": V27_2026_DAILY,
    }
    for label, path in outcome_inputs.items():
        assert_hash(path, EXPECTED[label], label)
    accepted_2025, audit_2025 = run_new_year(selected, 2025)
    accepted_2026, audit_2026 = run_new_year(selected, 2026)
    accepted = pd.concat(
        [
            pd.read_parquet(V29R3_DEV_ACCEPTED),
            pd.read_parquet(V29R3_VALIDATION_ACCEPTED),
            accepted_2025,
            accepted_2026,
        ],
        ignore_index=True,
    )
    accepted["signal_date"] = pd.to_datetime(accepted.signal_date).dt.normalize()
    selected["signal_date"] = pd.to_datetime(selected.signal_date).dt.normalize()
    annual: dict[str, Any] = {}
    for year in YEARS:
        item = stats(accepted.loc[accepted.signal_date.dt.year.eq(year)].copy())
        signals = selected.loc[selected.signal_date.dt.year.eq(year)]
        item["signals"] = len(signals)
        item["executable_entries"] = int(signals.entry_status.eq("EXECUTABLE_ENTRY").sum())
        annual[str(year)] = item
    if any(item["accepted"] != item["completed"] for item in annual.values()):
        raise RollforwardError("annual accepted/completed conservation failed")
    result = {
        "experiment": EXPERIMENT,
        "scientific_status": "FROZEN_RULE_POST_OBSERVATION_ROLLFORWARD_DIAGNOSTIC_NOT_PRISTINE_OOS",
        "fixed_rule": "V28R2 AND signal_stock_return-conditional_observed_row_market_median<=0.02",
        "spec_sha256": sha256(SPEC),
        "runner_sha256": sha256(Path(__file__)),
        "stage_a_freeze_sha256": sha256(STAGE_A_FREEZE),
        "stage_a_selected_sha256": sha256(STAGE_A_SELECTED),
        "annual_by_signal_year": annual,
        "rollforward_gate_counts": freeze["rollforward_gate_counts"],
        "rollforward_portfolio_audit": {"2025": audit_2025, "2026": audit_2026},
        "outcome_input_hashes": {label: sha256(path) for label, path in outcome_inputs.items()},
        "data_end": str(DATA_END.date()),
        "mature_2026_signal_end": str(MATURE_2026_SIGNAL_END.date()),
        "2026_scope": "MATURE_YTD_NOT_FULL_YEAR",
        "cross_section_limitation": v29r3.CROSS_SECTION_SEMANTICS,
        "execution": {
            "entry": "next legal one-minute entry strictly after completed signal",
            "target": "A67 below L",
            "time_stop": "H20",
            "failure_stop": "NONE",
            "cost_per_side": 0.002,
            "portfolio_k_per_sleeve": 80,
        },
        "rule_change_count": 0,
    }
    atomic_json(RESULT, result)
    atomic_text(REPORT, render_report(result))
    return result


def pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.3f}%"


def render_report(result: dict[str, Any]) -> str:
    rows = []
    for year in YEARS:
        item = result["annual_by_signal_year"][str(year)]
        rows.append(
            f"|{year}{'*' if year == 2026 else ''}|{item['signals']}|"
            f"{item['executable_entries']}|{item['accepted']}|{item['completed']}|"
            f"{pct(item['mean_net'])}|{pct(item['median_net'])}|{pct(item['win'])}|"
            f"{pct(item['severe10'])}|{item['mean_holding_sessions']:.3f}|"
            f"{item['median_holding_sessions']:.1f}|"
            f"{json.dumps(item['exit_reasons'], ensure_ascii=False, sort_keys=True)}|"
        )
    return "\n".join(
        [
            f"# {EXPERIMENT}",
            "",
            "The frozen V29R3 2% rule was rolled forward without parameter changes.",
            "",
            "|Signal year|Signals|Executable|Accepted|Completed|Mean net|Median net|Win|Severe10|Mean hold|Median hold|Exit reasons|",
            "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
            *rows,
            "",
            "*2026 is mature YTD only: signal cutoff 2026-08-03, data end 2026-09-04. It is not a full-year frequency observation.*",
            "",
            "Execution remains T+1/next legal minute, A67, H20, no stop, 20bp per side and K80 per board sleeve.",
            "",
            "The market median is conditional on eligible rows physically present in registered CY-033. Historical-universe completeness and survivorship freedom are unproven because QD-007 is unavailable.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", required=True, choices=("stage-a", "stage-b", "verify-stage-a"))
    args = parser.parse_args()
    if args.mode == "stage-a":
        payload = build_stage_a()
    elif args.mode == "verify-stage-a":
        freeze, selected = verify_stage_a()
        payload = {"verified": True, "freeze": freeze, "selected_rows": len(selected)}
    else:
        payload = run_stage_b()
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
