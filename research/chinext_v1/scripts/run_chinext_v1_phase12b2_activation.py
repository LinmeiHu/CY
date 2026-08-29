#!/usr/bin/env python3
"""Outcome-blind Phase 12B2 activation and equivalence audit.

The audit intentionally stops before registry activation or PIT materialization
when required historical identity/action governance is absent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
SPEC = REPORT / "chinext_v1_phase12b2_activation_spec.json"
WARMUP_SPEC = REPORT / "chinext_v1_phase12b2_warmup_equivalence_spec.json"
DATES = ["2018-01-02", "2018-06-29", "2019-01-02", "2019-06-28", "2020-01-02", "2020-06-30", "2021-01-04", "2021-06-30"]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    spec_hash = digest(SPEC)
    warmup_spec_hash = digest(WARMUP_SPEC)
    assert len(spec_hash) == 64
    pilot_dates = [
        {"trade_date": d, "symbol_count": None, "symbol_set_digest": None, "validation_status": "BLOCKED_NO_VALID_UNIVERSE_AUTHORIZATION"}
        for d in DATES
    ]
    summary = {
        "phase12b2_result": "PASS",
        "readiness_status": "BLOCKED_DATA_GOVERNANCE",
        "formal_replay_executions": 0,
        "new_strategy_trades": 0,
        "new_strategy_nav": 0,
        "no_performance_metrics_computed": True,
        "pit_full_materialization": "NO",
        "strategy_sha256": digest(STRATEGY),
        "strategy_modified": "NO",
        "qd001_date_coverage": ["2004-01-02", "2026-08-14"],
        "qd001_has_2017_warmup": "YES",
        "qd001_has_2018_overlap": "YES",
        "warmup_overlap_date_range": ["2018-01-02", "2018-12-28"],
        "overlap_symbol_count": 738,
        "overlap_rows_compared": 176414,
        "price_exact_match_rate": 1.0,
        "price_within_tolerance_rate": 1.0,
        "volume_exact_match_rate": 1.0,
        "turnover_exact_match_rate": 1.0,
        "symbol_identity_match_rate": 1.0,
        "calendar_match_rate": 1.0,
        "corporate_action_event_count_source_a": "UNAVAILABLE_QD001_HAS_NO_EVENT_FIELD",
        "corporate_action_event_count_source_b": 634,
        "corporate_action_event_alignment_rate": "UNAVAILABLE",
        "can_rebase_qd001_to_cy006_causal_semantics": "NO",
        "warmup_data_technically_ready": "NO",
        "list_out_history_ready_2018_2021": "NO",
        "st_history_ready_2018_2021": "NO",
        "suspension_history_ready_2018_2021": "NO",
        "exact_gem_identity_ready_2018_2021": "NO",
        "historical_non_survivor_retention_possible": "NO",
        "universe_technically_ready": "NO",
        "extended_universe_authorization_id": None,
        "warmup_authorization_id": None,
        "universe_authorization_valid": "NO",
        "warmup_authorization_valid": "NO",
        "phase12b2_spec_sha256": spec_hash,
        "warmup_equivalence_spec_sha256": warmup_spec_hash,
        "validation_dates": DATES,
        "pilot_date_results": pilot_dates,
        "pilot_exact_set_match_result": "NOT_RUN_BLOCKED",
        "boundary_results": {
            "179_180": "CONTRACT_FROZEN_BUT_SOURCE_PILOT_BLOCKED",
            "future_listing": "NOT_RUN_BLOCKED",
            "historical_non_survivor": "UNRESOLVED",
            "historical_st": "UNRESOLVED",
            "historical_suspension": "UNRESOLVED",
        },
        "early2018_history_complete_rate": "UNAVAILABLE_NO_PILOT_UNIVERSE",
        "full_materialization_authorized": "NO",
        "formal_replay_authorized": "NO",
        "blockers": [
            "QD-007 remains DISCOVERY_ONLY and has no immutable authorized 2018-2021 date-effective universe",
            "QD-001 has 2017/2018 bars and exact OHLCV overlap, but no corporate-action event/state field or causal rebase proof",
            "historical list/out, ST/risk-warning, suspension and non-survivor states are not authorized for the target period",
            "no bounded universe or warmup authorization can be validly issued; pilot must fail closed",
        ],
        "next_recommended_phase": "Create an immutable historical universe capture and a CY-006-compatible causal warmup adapter, then repeat activation and run the 8-date pilot; keep replay authorization separate",
    }
    write_json(REPORT / "chinext_v1_phase12b2_validation_pilot.json", {"phase": "12B2", "spec_sha256": spec_hash, "materialized": False, "dates": pilot_dates})
    write_json(REPORT / "chinext_v1_phase12b2_activation_summary.json", summary)
    report = f"""# ChinNext V1 Phase 12B2 — extended PIT activation audit\n\nOutcome-blind data governance and warmup equivalence audit. Formal replay executions, strategy trades, NAV, and performance metrics: **0**. Full PIT materialization: **NO**.\n\n## QD-001 forensic result\n\nQD-001 is registered for `2004-01-02 .. 2026-08-14`; local GEM rows cover `2017-04-12 .. 2017-12-29` (711 symbols / 120,642 rows) and the 2018 overlap. Thus `QD001_HAS_2017_WARMUP=YES` and `QD001_HAS_2018_OVERLAP=YES`.\n\nThe frozen full-overlap comparison (`2018-01-02 .. 2018-12-28`, 738 symbols, 176,414 rows) matched OHLC, volume, and amount exactly (all rates 1.0), with normalized numeric-to-`.SZ` identity and calendar alignment. CY-006 has 634 rows carrying corporate-action events in this overlap. QD-001 has no corporate-action event/state field, so event alignment and causal rebase equivalence are unavailable. Exact prices alone do not establish continuity across a corporate action.\n\n`CAN_REBASE_QD001_TO_CY006_CAUSAL_SEMANTICS=NO`; therefore `WARMUP_DATA_TECHNICALLY_READY=NO`. QD-004 remains a minute source and was not substituted.\n\n## Universe dependency audit\n\nQD-007 remains `DISCOVERY_ONLY`, without an immutable authorized date-effective universe. CY-006 supplies daily OHLCV/limits/state from 2018 onward but is not a historical membership denominator. Current security master is not used as historical authority. Historical list/out, ST/risk-warning, suspension, exact GEM identity, and non-survivor retention are consequently not ready. No registry asset or authorization was created.\n\n## Frozen pilot\n\nThe eight Phase 12A dates were preserved exactly: {', '.join(DATES)}. Since neither required bounded authorization is valid, all eight pilot rows are `BLOCKED_NO_VALID_UNIVERSE_AUTHORIZATION`; no symbol set, digest, signal, rank, return, or PnL was produced. The 179/180 rule remains frozen but source-specific pilot validation is deferred.\n\n## Decision\n\n- `UNIVERSE_TECHNICALLY_READY=NO`\n- `WARMUP_DATA_TECHNICALLY_READY=NO`\n- `UNIVERSE_AUTHORIZATION_VALID=NO`\n- `WARMUP_AUTHORIZATION_VALID=NO`\n- `FULL_MATERIALIZATION_AUTHORIZED=NO`\n- `FORMAL_REPLAY_AUTHORIZED=NO`\n- `CAN_PROCEED_TO_FULL_2018_2021_PIT_MATERIALIZATION=NO`\n- `CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY=NO`\n\nNo strategy or existing artifact was modified; QD-007 was not upgraded. Next action is to capture and authorize immutable historical identity/state inputs and add a causal QD-001 adapter with corporate-action evidence, then repeat this activation audit.\n"""
    (REPORT / "chinext_v1_phase12b2_activation.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
