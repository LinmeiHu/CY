#!/usr/bin/env python3
"""Freeze offline crowd-out evidence and the pre-result Phase 4 matched spec."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from typing import Any

from chinext_v1_phase4 import canonical_envelope, crowdout_rows, crowdout_summary
from run_chinext_v1_smoke import atomic_text, sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
OUTPUT = ROOT / "research/chinext_v1/output/chinext_v1_phase3_ablation"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
PIT_MANIFEST = REPORTS / "chinext_v1_pit_master_manifest.json"
PHASE1B = REPORTS / "chinext_v1_pit_replay_summary.json"
PHASE2 = REPORTS / "chinext_v1_winner_attribution_summary.json"
PHASE3_SPEC = REPORTS / "chinext_v1_phase3_ablation_spec.json"
PHASE3_SUMMARY = REPORTS / "chinext_v1_phase3_ablation_summary.json"
CROWDOUT_CSV = REPORTS / "chinext_v1_phase4_winner_crowdout.csv"
SPEC = REPORTS / "chinext_v1_phase4_matched_spec.json"

EXPECTED = {
    "strategy": "dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a",
    "pit_manifest": "8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7",
    "phase1b": "10c9a10860dfaef5ee621a5e98741a9b0f881be247e8115cd524d9098a66d6af",
    "phase2": "185ea2e5da93972b745e8ad60d86cdd71a11a0f8de7cb16e84c88dda39214430",
    "phase3_spec": "530a5cabddf5afbef86f3fd433a6be35a36973bf3f7662944267a3bec97f160c",
    "phase3_summary": "9762426dc2787c6d34a1b6ba6caf44863863ab1f185c85ab799f37aa4b6891b2",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_crowdout_csv(rows: list[dict[str, Any]]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    atomic_text(CROWDOUT_CSV, stream.getvalue())


def main() -> int:
    if SPEC.exists() or CROWDOUT_CSV.exists():
        raise RuntimeError("Phase 4 preparation artifact already exists; overwrite forbidden")
    paths = {
        "strategy": STRATEGY,
        "pit_manifest": PIT_MANIFEST,
        "phase1b": PHASE1B,
        "phase2": PHASE2,
        "phase3_spec": PHASE3_SPEC,
        "phase3_summary": PHASE3_SUMMARY,
    }
    actual = {name: sha256_file(path) for name, path in paths.items()}
    if actual != EXPECTED:
        raise RuntimeError(f"frozen input mismatch: expected={EXPECTED}, actual={actual}")

    phase2 = json.loads(PHASE2.read_text(encoding="utf-8"))
    top20 = phase2["top20_trades"]
    if len(top20) != 20:
        raise RuntimeError("Phase 2 frozen Top20 does not contain exactly twenty episodes")
    all_crowdout: list[dict[str, Any]] = []
    phase3_file_hashes: dict[str, dict[str, str]] = {}
    for raw_arm, directory in (
        ("A0_BASELINE", "a0_baseline"),
        ("A2_MINUS_B60", "a2_minus_b60"),
        ("A3_MINUS_FULL40", "a3_minus_full40"),
    ):
        arm_dir = OUTPUT / directory
        phase3_file_hashes[raw_arm] = {
            name: sha256_file(arm_dir / filename)
            for name, filename in (
                ("engine_summary", "engine_summary.json"),
                ("event_ledger", "event_ledger.jsonl"),
                ("execution_ledger", "execution_ledger.jsonl"),
                ("daily_nav", "daily_nav.jsonl"),
            )
        }
        if raw_arm == "A0_BASELINE":
            continue
        all_crowdout.extend(
            crowdout_rows(
                raw_arm=raw_arm,
                top20=top20,
                events=read_jsonl(arm_dir / "event_ledger.jsonl"),
                executions=read_jsonl(arm_dir / "execution_ledger.jsonl"),
                daily_nav=read_jsonl(arm_dir / "daily_nav.jsonl"),
            )
        )
    if len(all_crowdout) != 40:
        raise RuntimeError("crowd-out output must contain exactly forty arm/episode rows")
    write_crowdout_csv(all_crowdout)

    a0_nav = read_jsonl(OUTPUT / "a0_baseline/daily_nav.jsonl")
    envelope = canonical_envelope(a0_nav)
    summaries = {
        raw_arm: crowdout_summary(
            [row for row in all_crowdout if row["raw_arm"] == raw_arm]
        )
        for raw_arm in ("A2_MINUS_B60", "A3_MINUS_FULL40")
    }
    spec = {
        "phase": "CHINEXT_V1_PHASE4_EXPOSURE_MATCHED_DECOMPOSITION",
        "status": "FROZEN_BEFORE_ANY_MATCHED_RESULT",
        "matched_results_observed_before_freeze": False,
        "new_formal_replay_executions_expected": 2,
        "formal_run_order": [
            "M2_MINUS_B60_BASELINE_CAPACITY",
            "M3_MINUS_FULL40_BASELINE_CAPACITY",
        ],
        "frozen_identity": {
            "authorization_id": "CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1",
            "date_range": ["2024-01-02", "2025-12-31"],
            "current_survivor_fallback": False,
            "pit_rebuilt": False,
            "input_sha256": actual,
            "phase3_file_sha256": phase3_file_hashes,
            "baseline_top20_episode_keys": [
                [str(row["symbol"]), str(row["entry_signal_date"])] for row in top20
            ],
        },
        "offline_winner_crowdout": {
            "completed_before_matched_spec_freeze": True,
            "table_path": str(CROWDOUT_CSV),
            "table_sha256": sha256_file(CROWDOUT_CSV),
            "summaries": summaries,
            "finite_capacity_definition": (
                "remaining-condition eligible episode not selected because all slots were occupied "
                "or higher frozen-RS candidates filled every vacancy"
            ),
        },
        "baseline_capacity_envelope": {
            "source": "Phase 3 frozen A0 daily_nav planned_members after each signal-close decision",
            "source_daily_nav_sha256": phase3_file_hashes["A0_BASELINE"]["daily_nav"],
            "row_count": len(envelope),
            "canonical_sha256": canonical_sha256(envelope),
            "schedule": envelope,
        },
        "capacity_application_contract": {
            "diagnostic_not_deployable_strategy": True,
            "copied_from_A0": "daily allowed target-member count only",
            "not_copied_from_A0": ["symbol identity", "candidate rank", "orders", "returns"],
            "selection": "each matched arm uses its own eligible candidates and frozen RS ordering",
            "vacancies": "max(0, A0_daily_capacity - matched_survivors_after_frozen_exits)",
            "survivor_overflow": (
                "do not invent capacity-triggered exits; preserve survivor-first and all frozen exits; "
                "admit zero new names while surviving targets exceed the A0 envelope and report every overflow day"
            ),
            "position_sizing": "unchanged frozen 10% target weight per desired member",
            "no_realized_exposure_targeting": True,
        },
        "arms": {
            "M2_MINUS_B60_BASELINE_CAPACITY": {
                "raw_parent": "A2_MINUS_B60",
                "only_alpha_module_difference_from_A0": "B60 hard admission disabled",
                "only_difference_from_raw_parent": "frozen A0 daily capacity envelope",
                "full40": "BASELINE",
                "minvol": "BASELINE",
                "rs": "BASELINE",
                "market_entry_gate": "BASELINE",
            },
            "M3_MINUS_FULL40_BASELINE_CAPACITY": {
                "raw_parent": "A3_MINUS_FULL40",
                "only_alpha_module_difference_from_A0": "FULL40 admission module disabled",
                "only_difference_from_raw_parent": "frozen A0 daily capacity envelope",
                "b60": "BASELINE",
                "minvol": "BASELINE",
                "rs": "BASELINE",
                "market_entry_gate": "BASELINE",
            },
        },
        "common_frozen_contract": {
            "pit_artifacts": "EXACT_PHASE1B",
            "date_range": ["2024-01-02", "2025-12-31"],
            "transaction_cost_bps_per_filled_side": 10.0,
            "board_lot": 100,
            "target_weight": 0.1,
            "max_holdings_hard_bound": 10,
            "rank_replacement": "OFF",
            "market_and_individual_exit_semantics": "EXACT_BASELINE",
            "rs_ordering": "20/60/120 = 0.20/0.50/0.30 with frozen tie-break",
            "set_change_only": True,
        },
        "extra_candidate_quality_definition": {
            "extra_entry": (
                "filled BUY with new_position=true whose persisted entry evaluation has the removed "
                "module diagnostic=false on the same signal date"
            ),
            "selected_extra_candidate_count": "all such filled new-position entry episodes",
            "return_statistics_population": "completed FIFO round trips among selected extra episodes",
            "holding_days": "trading-session index(exit_execution_date) - index(entry_execution_date)",
            "mfe_mae": "UNRESOLVED_NOT_COMPUTED",
        },
        "interpretation_contract": {
            "dimensions": [
                "return_and_drawdown",
                "trade_count_and_realized_exposure",
                "baseline_Top20_restoration",
                "return_ex_best20",
                "offline_crowdout_evidence",
                "extra_candidate_quality",
            ],
            "allowed_primary_roles": [
                "SECURITY_SELECTION",
                "OPPORTUNITY_CONTROL",
                "EXPOSURE_CONTROL",
                "CROWD_OUT_PROTECTION",
                "RISK_FILTER",
                "MIXED",
                "INCONCLUSIVE",
            ],
            "allowed_evidence_strength": ["STRONG", "MODERATE", "WEAK"],
            "rule": (
                "Do not infer module value from total return alone. Restoration after matching supports "
                "opportunity/exposure control; persistent weakness and low capture supports security-selection "
                "or crowd-out protection; conflicting dimensions require MIXED or INCONCLUSIVE."
            ),
        },
        "forbidden": [
            "A0_A2_A3_REPLAY",
            "PIT_REBUILD",
            "PARAMETER_SEARCH",
            "EXTRA_MATCHED_ARM",
            "EXIT_RESEARCH",
            "BASELINE_SYMBOL_COPY",
            "FUTURE_REALIZED_EXPOSURE_TARGETING",
        ],
    }
    write_json(SPEC, spec)
    print(
        json.dumps(
            {
                "crowdout_csv_sha256": sha256_file(CROWDOUT_CSV),
                "crowdout_summaries": summaries,
                "envelope_sha256": spec["baseline_capacity_envelope"]["canonical_sha256"],
                "phase4_spec_sha256": sha256_file(SPEC),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
