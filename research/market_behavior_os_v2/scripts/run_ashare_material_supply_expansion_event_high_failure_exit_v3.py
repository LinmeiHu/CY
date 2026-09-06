#!/usr/bin/env python3
"""Run the frozen supply-event-high failure exit development test."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from research.market_behavior_os_v2.scripts import (
    run_ashare_high_transfer_low_price_displacement_mother_v1_stage_b as execution,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_material_supply_expansion_demand_reassertion_v1_stage_1 as parent,
)
from research.market_behavior_os_v2.scripts import (
    run_ashare_material_supply_expansion_three_close_acceptance_v2 as shared,
)


EXPERIMENT = "ASHARE-MATERIAL-SUPPLY-EXPANSION-EVENT-HIGH-FAILURE-EXIT-V3"
REPO = Path(__file__).resolve().parents[3]
SPEC = REPO / f"research/market_behavior_os_v2/experiments/{EXPERIMENT}_freeze.json"
ROOT = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_material_supply_expansion_demand_reassertion_v1"
)
PARENT_SELECTIONS = ROOT / "stage_1/selection_ledger_without_returns.parquet"
PATHS = Path(
    "/Volumes/quant/CY_quant_research/"
    "ashare_material_circulating_supply_expansion_mother_v1/"
    "stage_b/future_paths_through_2021h1.parquet"
)
OUTPUT_ROOT = ROOT / "stage_5_event_high_failure_exit_v3"
SELECTIONS = OUTPUT_ROOT / "selection_ledger_without_returns.parquet"
MANIFEST = OUTPUT_ROOT / "breadth_gate_manifest.json"
TRADE_LEDGER = OUTPUT_ROOT / "trade_ledger.parquet"
RESULT = OUTPUT_ROOT / "result.json"
EXPECTED_HASHES = {
    SPEC: "3a11bf948e44e1735772fa9e718a0ceddd460c3091260ccb58fdc12210a90424",
    PARENT_SELECTIONS: "cce313e6aec13912f53566239f2de52c0e5af5e98e3dfb7e9fb7f9d55f76438a",
    PATHS: "39c528941b3e04011264b2a3a2a8dd61950150e30f609c0fbbd50d59efc89a8a",
}
EXPECTED_PARENT_COMPLETED = 525
TIME_EXIT_SESSIONS = 120
MINIMUM_ANNUAL_COMPLETED_STRICT = 50
ROUND_TRIP_COST = 0.004
MAXIMUM_CONTEXT_DATE = pd.Timestamp("2021-06-30")


class ResearchError(RuntimeError):
    """Fail closed on frozen identity, chronology, or coordinate lineage."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_inputs() -> dict[str, str]:
    actual: dict[str, str] = {}
    for path, expected in EXPECTED_HASHES.items():
        if not path.is_file():
            raise ResearchError(f"missing frozen input: {path}")
        value = sha256(path)
        actual[str(path)] = value
        if value != expected:
            raise ResearchError(f"frozen input drift: {path}: {value} != {expected}")
    return actual


def apply_event_high_exit_without_returns(
    selected: Any, path: pd.DataFrame
) -> dict[str, Any]:
    ordered_path = path.sort_values("cal_idx", kind="mergesort")
    if ordered_path.empty or int(ordered_path.iloc[0].cal_idx) != int(selected.signal_cal_idx) + 1:
        raise ResearchError("event path does not start on the next market session")
    lineage = float(ordered_path.iloc[0].invalid_step_cum)
    if not np.isfinite(lineage):
        raise ResearchError("event path has no valid frozen coordinate lineage")
    entry_idx = int(selected.entry_cal_idx)
    event_high = float(selected.event_high)
    common = {
        key: getattr(selected, key)
        for key in selected._fields
        if key not in {"exit_date", "exit_cal_idx", "exit_reason", "holding_market_sessions", "status"}
    }
    by_idx = {
        int(row.cal_idx): row for row in ordered_path.itertuples(index=False)
    }
    entry = by_idx.get(entry_idx)
    if entry is None or not parent.same_coordinate_lineage(entry, lineage):
        return {**common, "status": "INVALID_PARENT_ENTRY"}

    below_high_streak = 0
    pending_failure_exit = False
    exit_row = None
    exit_reason = None
    for idx in range(entry_idx, int(ordered_path.cal_idx.max()) + 1):
        row = by_idx.get(idx)
        if row is None:
            return {**common, "status": "MISSING_POST_ENTRY_MARKET_SESSION"}
        if not parent.same_coordinate_lineage(row, lineage):
            return {**common, "status": "INVALID_COORDINATE_LINEAGE"}
        if pending_failure_exit and idx > entry_idx and execution.sellable_open(row):
            exit_row = row
            exit_reason = "EVENT_HIGH_ACCEPTANCE_FAILURE"
            break
        if idx >= entry_idx + TIME_EXIT_SESSIONS and execution.sellable_open(row):
            exit_row = row
            exit_reason = "TIME_EXIT_H120"
            break
        if parent.valid_completed_close(row, lineage):
            below_high_streak = below_high_streak + 1 if float(row.coord_close) < event_high else 0
            if below_high_streak >= 2:
                pending_failure_exit = True

    if exit_row is None:
        return {**common, "status": "NO_COMPLETED_EXIT"}
    return {
        **common,
        "exit_date": pd.Timestamp(exit_row.trade_date),
        "exit_cal_idx": int(exit_row.cal_idx),
        "exit_reason": exit_reason,
        "holding_market_sessions": int(exit_row.cal_idx) - entry_idx,
        "status": "COMPLETED",
    }


def run_stage_1() -> dict[str, Any]:
    source_hashes = verify_inputs()
    selected = pd.read_parquet(PARENT_SELECTIONS)
    selected = selected.loc[selected.status.eq("COMPLETED")].copy()
    paths = pd.read_parquet(PATHS)
    for column in ("trade_date", "decision_at", "available_at"):
        paths[column] = pd.to_datetime(paths[column])
    if len(selected) != EXPECTED_PARENT_COMPLETED or selected.event_id.duplicated().any():
        raise ResearchError("parent completed-trade identity drift")
    if selected.signal_year.gt(2020).any():
        raise ResearchError("post-2020 signal identity entered development")
    if paths.trade_date.max() > MAXIMUM_CONTEXT_DATE:
        raise ResearchError("post-2021H1 context entered stage 1")
    path_lookup = {key: part for key, part in paths.groupby("event_id", sort=False)}
    selections = pd.DataFrame(
        [
            apply_event_high_exit_without_returns(row, path_lookup[str(row.event_id)])
            for row in selected.sort_values(
                ["signal_date", "pit_industry", "symbol"], kind="mergesort"
            ).itertuples(index=False)
        ]
    ).sort_values(["signal_date", "pit_industry", "symbol"], kind="mergesort")
    shared.write_parquet(selections, SELECTIONS)
    completed = selections.loc[selections.status.eq("COMPLETED")]
    annual_completed = {
        str(year): int(completed.signal_year.eq(year).sum()) for year in (2018, 2019, 2020)
    }
    breadth_gate_pass = all(
        count > MINIMUM_ANNUAL_COMPLETED_STRICT for count in annual_completed.values()
    )
    manifest = {
        "experiment": EXPERIMENT,
        "stage": "OUTCOME_UNAGGREGATED_EXIT_APPLICATION",
        "source_hashes": source_hashes,
        "script_sha256": sha256(Path(__file__)),
        "selection_ledger": str(SELECTIONS),
        "selection_ledger_sha256": sha256(SELECTIONS),
        "parent_completed_trades": int(len(selections)),
        "status_counts": {
            str(key): int(value)
            for key, value in selections.status.value_counts().sort_index().items()
        },
        "annual_completed": annual_completed,
        "minimum_annual_completed_strictly_greater_than": MINIMUM_ANNUAL_COMPLETED_STRICT,
        "breadth_gate_pass": bool(breadth_gate_pass),
        "annual_or_pooled_return_aggregate_produced": False,
        "post_2021_signal_identity_read": False,
        "validation_2022_2024_outcome_read": False,
        "maximum_context_date": str(paths.trade_date.max().date()),
    }
    shared.write_json(MANIFEST, manifest)
    return manifest


def run_stage_2() -> dict[str, Any]:
    source_hashes = verify_inputs()
    if not MANIFEST.is_file() or not SELECTIONS.is_file():
        raise ResearchError("stage 1 outputs are missing")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if not manifest.get("breadth_gate_pass"):
        raise ResearchError("stage-1 breadth gate did not authorize aggregation")
    if manifest.get("annual_or_pooled_return_aggregate_produced"):
        raise ResearchError("stage 1 unexpectedly contains a return aggregate")
    if sha256(SELECTIONS) != manifest.get("selection_ledger_sha256"):
        raise ResearchError("stage-1 selection ledger drift")
    selections = pd.read_parquet(SELECTIONS)
    completed = selections.loc[selections.status.eq("COMPLETED")].copy()
    paths = pd.read_parquet(
        PATHS, columns=["event_id", "cal_idx", "trade_date", "coord_open"]
    )
    if pd.to_datetime(paths.trade_date).max() > MAXIMUM_CONTEXT_DATE:
        raise ResearchError("context crossed the frozen 2021H1 cap")
    entries = paths.rename(
        columns={"cal_idx": "entry_cal_idx", "trade_date": "entry_price_date", "coord_open": "entry_price"}
    )[["event_id", "entry_cal_idx", "entry_price_date", "entry_price"]]
    exits = paths.rename(
        columns={"cal_idx": "exit_cal_idx", "trade_date": "exit_price_date", "coord_open": "exit_price"}
    )[["event_id", "exit_cal_idx", "exit_price_date", "exit_price"]]
    ledger = completed.merge(entries, on=["event_id", "entry_cal_idx"], how="left", validate="one_to_one").merge(
        exits, on=["event_id", "exit_cal_idx"], how="left", validate="one_to_one"
    )
    if ledger[["entry_price", "exit_price"]].isna().any().any():
        raise ResearchError("entry or exit price is missing")
    if (ledger[["entry_price", "exit_price"]] <= 0).any().any():
        raise ResearchError("entry or exit price is non-positive")
    ledger["gross_return"] = ledger.exit_price / ledger.entry_price - 1.0
    ledger["net_return"] = ledger.gross_return - ROUND_TRIP_COST
    if not np.isfinite(ledger[["gross_return", "net_return"]].to_numpy(dtype=float)).all():
        raise ResearchError("non-finite return")
    shared.write_parquet(ledger, TRADE_LEDGER)
    annual = {
        str(year): shared.summarize(ledger.loc[ledger.signal_year.eq(year)])
        for year in (2018, 2019, 2020)
    }
    for values in annual.values():
        values["breadth_pass"] = bool(values["n"] > 50)
        values["mean_gate_pass"] = bool(values["mean_net_return"] > 0.04)
        values["median_gate_pass"] = bool(values["median_net_return"] > 0.0)
        values["full_year_gate_pass"] = bool(
            values["breadth_pass"] and values["mean_gate_pass"] and values["median_gate_pass"]
        )
    all_gates = all(values["full_year_gate_pass"] for values in annual.values())
    result = {
        "experiment": EXPERIMENT,
        "research_status": "ONE_SHOT_DEVELOPMENT_RESULT",
        "source_hashes": source_hashes,
        "stage_1_manifest_sha256": sha256(MANIFEST),
        "script_sha256": sha256(Path(__file__)),
        "trade_ledger": str(TRADE_LEDGER),
        "trade_ledger_sha256": sha256(TRADE_LEDGER),
        "annual": annual,
        "pooled": shared.summarize(ledger),
        "by_exit_reason": {
            str(reason): shared.summarize(part)
            for reason, part in ledger.groupby("exit_reason", sort=True)
        },
        "all_development_gates_pass": bool(all_gates),
        "validation_2022_2024_authorized": bool(all_gates),
        "validation_2022_2024_outcome_read": False,
        "post_2021_signal_identity_read": False,
        "maximum_context_date": "2021-06-30",
        "no_parameter_rescue": True,
        "classification": (
            "DEVELOPMENT_GATE_PASS_VALIDATION_AUTHORIZED"
            if all_gates
            else "DEVELOPMENT_GATE_FAIL_EXACT_RULE_CLOSED"
        ),
    }
    shared.write_json(RESULT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("stage1", "stage2"))
    args = parser.parse_args()
    result = run_stage_1() if args.stage == "stage1" else run_stage_2()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
