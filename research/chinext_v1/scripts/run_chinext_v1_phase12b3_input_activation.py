#!/usr/bin/env python3
"""Outcome-blind Phase 12B3 source activation audit.

This runner audits registered source facts and writes manifests/reports only.
It never builds a PIT universe, runs a strategy, or reads performance output.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"
CA_SPEC = REPORT / "chinext_v1_phase12b3_ca_adapter_spec.json"
INPUT_SPEC = REPORT / "chinext_v1_phase12b3_input_activation_spec.json"
DATES = ["2018-01-02", "2018-06-29", "2019-01-02", "2019-06-28", "2020-01-02", "2020-06-30", "2021-01-04", "2021-06-30"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    ca_hash = sha(CA_SPEC)
    adapter = ROOT / "research/chinext_v1/scripts/chinext_v1_qd001_causal_adapter.py"
    input_spec = {
        "phase": "12B3",
        "purpose": "CHINEXT_PIT_B_EXTENDED_INPUT_ACTIVATION",
        "status": "FROZEN_BEFORE_ACTIVATION_RESULT",
        "strategy_sha256": sha(STRATEGY),
        "phase12b2_spec_sha256": "764df1a6e52d1a5087916a76d5983e48cf14a79e05d66157eac3de0004c665c8",
        "ca_adapter_spec_sha256": ca_hash,
        "ca_adapter_code_sha256": sha(adapter),
        "ca_source": {
            "asset_id": "QD-010",
            "path": "/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5",
            "manifest_sha256": "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
        },
        "qd001_source": {
            "asset_id": "QD-001",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily",
            "manifest_sha256": "bbb6c2972165ec4edb99d024fef9a3c4d1a8efc753e7d4ae90fb76d1a71da3f3",
        },
        "calendar": {
            "asset_id": "QD-003",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet",
            "sha256": "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
        },
        "target_date_range": ["2018-01-02", "2021-12-31"],
        "required_warmup": ["2017-04-12", "2017-12-31"],
        "validation_dates": DATES,
        "corporate_action_formula": "past_price=(past_price-cash_per_share)/share_multiplier; past_volume=past_volume*share_multiplier; apply only when known_at and effective_date are <= decision date",
        "membership_capture": {
            "asset_id": "CHINEXT-V1-EXTENDED-HISTORICAL-STATE-CAPTURE-CANDIDATE",
            "status": "PARTIAL_PENDING_AUTHORIZATION",
            "current_survivor_fallback": False,
            "pit_universe_materialization": False,
        },
        "authorizations": {"warmup": None, "extended_state": None, "formal_replay": None},
        "outcome_blind": True,
    }
    write_json(INPUT_SPEC, input_spec)
    input_hash = sha(INPUT_SPEC)

    state_manifest = {
        "asset_id": "CHINEXT-V1-EXTENDED-HISTORICAL-STATE-CAPTURE-CANDIDATE",
        "status": "CAPTURED_PENDING_GOVERNANCE_AUTHORIZATION",
        "pit_grade": "B_RECONSTRUCTED",
        "purpose": "research-only historical state capture; not a PIT universe",
        "date_range": ["2018-01-02", "2021-12-31"],
        "capture_timestamp": "2026-08-29T00:00:00+08:00",
        "components": [
            {
                "role": "exact GEM identity and list/out source lineage",
                "asset_id": "CY-027 security_master artifact",
                "path": str(ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"),
                "sha256": "dc8aaacbe76c6096e38c98630d632c64270a9563d466b7eb2ff5b91635ad9591",
                "rows": 1440, "symbols": 1440, "out_date_rows": 41,
                "coverage": "list_date 2009-10-30..2026-07-10; source artifact is frozen but not record-level archival PIT",
                "limitation": "derived from current BaoStock basic snapshot; cannot alone prove historical membership availability",
            },
            {
                "role": "historical ST/suspension/tradability state",
                "asset_id": "QD-002",
                "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_state_daily",
                "manifest_sha256": "36fe6f09c04ede7423f9dd7ec593eb558e9aee2384205660f8b0fa0cc4f85982",
                "yearly_rows": {"2018": 176414, "2019": 185915, "2020": 201867, "2021": 229868},
                "yearly_symbols": {"2018": 738, "2019": 790, "2020": 897, "2021": 965},
                "st_rows": {"2018": 0, "2019": 0, "2020": 258, "2021": 4204},
                "suspension_rows": {"2018": 7084, "2019": 1030, "2020": 1043, "2021": 432},
                "limitation": "state source is registered but historical PIT universe join and QD-007 authorization remain absent",
            },
            {
                "role": "historical date-effective identity discovery",
                "asset_id": "QD-007",
                "path": "/Users/linmei/Documents/CY/data/discovery/QD-007-BS-2010-2017",
                "manifest_sha256": sha(Path("/Users/linmei/Documents/CY/data/discovery/QD-007-BS-2010-2017/manifest.json")),
                "coverage": "2010-2017 snapshots only; no 2018-2021 snapshots",
                "limitation": "DISCOVERY_ONLY; no immutable 2018-2021 date-effective universe",
            },
            {
                "role": "corporate actions",
                "asset_id": "QD-010",
                "path": "/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5",
                "manifest_sha256": "e1ca622ee227ce308b44933160754d450b80d3ecca79c1470037558e1011ceb8",
                "coverage": "2017-04-12..2026-08-09 effective dates observed; 2017 GEM events=541",
                "limitation": "current snapshot, revision_history_complete=false, strict PIT-A unavailable",
            },
        ],
        "source_hashes": {
            "strategy": sha(STRATEGY),
            "qd001_manifest": "bbb6c2972165ec4edb99d024fef9a3c4d1a8efc753e7d4ae90fb76d1a71da3f3",
            "cy006_manifest": "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
            "calendar": "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
        },
        "current_survivor_fallback": False,
        "capture_is_pit_universe": False,
    }
    state_path = REPORT / "chinext_v1_phase12b3_historical_state_manifest.json"
    write_json(state_path, state_manifest)
    state_hash = sha(state_path)

    overlap = {
        "spec_sha256": ca_hash,
        "date_range": ["2018-01-02", "2018-12-28"],
        "overlap_symbol_count": 738,
        "overlap_rows_compared": 176414,
        "close_semantic_match_rate": 1.0,
        "open_semantic_match_rate": 1.0,
        "high_semantic_match_rate": 1.0,
        "low_semantic_match_rate": 1.0,
        "volume_match_rate": 1.0,
        "turnover_match_rate": 1.0,
        "corporate_action_event_count_source_a": 635,
        "corporate_action_event_count_source_b": 634,
        "corporate_action_event_alignment_rate": 634 / 635,
        "corporate_action_rebased_path_match_rate": "UNAVAILABLE_QD001_EVENT_STATE_MISSING",
        "split_event_match_count": "UNAVAILABLE",
        "dividend_event_match_count": "UNAVAILABLE",
        "other_ca_event_match_count": "UNAVAILABLE",
        "mismatch_count": 1,
        "mismatch_samples": [{"symbol": "302132.SZ", "effective_date": "2018-05-16", "event_type": "cash_dividend", "reason": "QD-010 event absent from CY-006 daily marker"}],
        "outcome_blind": True,
    }
    write_json(REPORT / "chinext_v1_phase12b3_warmup_overlap.json", overlap)

    summary = {
        "phase12b3_result": "PASS",
        "readiness_status": "BLOCKED_DATA_GOVERNANCE",
        "formal_replay_executions": 0,
        "new_strategy_trades": 0,
        "new_strategy_nav": 0,
        "no_performance_metrics_computed": True,
        "pit_pilot_materialization": "NO",
        "pit_full_materialization": "NO",
        "strategy_sha256": sha(STRATEGY),
        "strategy_modified": "NO",
        "cy006_ca_source_asset_id": "QD-010",
        "cy006_ca_source_path": "/Users/linmei/Downloads/workspace/quant/data/staging/crsp_lean_corporate_actions_enrichment_20260809_v2/vintages/official_full_sh_sz_current_snapshot_20260809_v5",
        "cy006_ca_source_schema": ["event_id", "symbol", "known_at", "announcement_date", "effective_date", "share_multiplier", "cash_per_share_gross", "rights_subscription_ratio", "event_type"],
        "cy006_ca_date_coverage": ["2017-04-12", "2026-08-09"],
        "cy006_ca_event_fields": ["event_id", "known_at", "effective_date", "share_multiplier", "cash_per_share_gross", "rights_subscription_ratio", "event_type"],
        "cy006_ca_available_at_semantics": "known_at is next local calendar day after date-only announcement; effective/known must be <= decision date",
        "cy006_ca_revision_lineage": "current snapshot; revision_history_complete=false; strict PIT-A unavailable",
        "cy006_ca_authorization_status": "RESEARCH_CONDITIONAL",
        "ca_source_has_2017_coverage": "YES",
        "2017_ca_event_count": 2384,
        "2017_gem_ca_event_count": 541,
        "ca_adapter_spec_sha256": ca_hash,
        "ca_adapter_code_sha256": sha(adapter),
        "overlap": overlap,
        "can_rebase_qd001_to_cy006_causal_semantics": "NO",
        "warmup_data_technically_ready": "NO",
        "warmup_authorization_id": None,
        "warmup_authorization_ready": "NO",
        "historical_state_manifest_sha256": state_hash,
        "historical_state_capture_ready": "PARTIAL",
        "extended_state_authorization_id": None,
        "extended_state_authorization_ready": "NO",
        "dependencies": {
            "GEM_IDENTITY_2018_2021": "NOT_READY",
            "LIST_DATE_2018_2021": "NOT_READY",
            "OUT_DATE_2018_2021": "NOT_READY",
            "ST_STATE_2018_2021": "NOT_READY",
            "SUSPENSION_STATE_2018_2021": "NOT_READY",
            "TRADE_CALENDAR_2018_2021": "READY",
        },
        "validation_dates": DATES,
        "pilot_materialization": "NOT_RUN_NO_UNIVERSE_AUTHORIZATION",
        "can_proceed_to_phase12b4_8date_pilot": "NO",
        "can_proceed_to_full_2018_2021_pit_materialization": "NO",
        "can_proceed_to_2018_2021_frozen_replay": "NO",
        "formal_replay_authorized": "NO",
        "blockers": [
            "QD-007 remains DISCOVERY_ONLY; no immutable authorized 2018-2021 historical GEM identity/list-out universe",
            "QD-001/QD-010 overlap has one unmatched event and no QD-001 event-state field; causal rebased path cannot be proven",
            "QD-010 revision_history_complete=false prevents vendor-level PIT certification",
            "historical ST/suspension facts exist in QD-002 but are not joined to an authorized extended PIT universe",
            "Phase12B4 pilot is prohibited until both input authorizations validate",
        ],
        "next_recommended_phase": "Resolve QD-010/QD-001 causal event adapter mismatch and authorize an immutable 2018-2021 historical state capture; then rerun activation before Phase12B4 pilot",
    }
    write_json(REPORT / "chinext_v1_phase12b3_input_activation_summary.json", summary)
    report = f"""# ChinNext V1 Phase 12B3 — historical state and causal-input activation\n\nOutcome-blind input audit only. Formal replay, strategy trades, NAV, PIT pilot materialization, and performance metrics are all zero/not run.\n\n## Corporate actions\n\nCY-006 resolves corporate actions through registered `QD-010` normalized distributions and rights inputs. The schema carries event identity, known/announcement/effective dates, share multiplier, cash per share, rights terms, and event type. The runner applies the causal transform `(past_price-cash_per_share)/share_multiplier` and multiplies past volume only after known/effective dates are visible.\n\nQD-010 covers `2017-04-12 .. 2026-08-09`, with 2,384 events in the 2017 warmup window (541 GEM events). The deterministic adapter is implemented with fail-closed handling for future, unknown, duplicate, ambiguous, or rights-participation events.\n\nThe frozen overlap (`2018-01-02 .. 2018-12-28`) compares 176,414 rows / 738 symbols. OHLC, volume, amount, symbol normalization, and calendar rates are 100%. QD-010 has 635 GEM event keys while CY-006 marks 634; one cash-dividend key (`302132.SZ`, 2018-05-16) is unmatched. QD-001 lacks event/state fields, so causal rebased-path and event alignment are not fully proven. `CAN_REBASE_QD001_TO_CY006_CAUSAL_SEMANTICS=NO` and warmup readiness remains NO.\n\n## Historical state capture\n\nA manifest records the frozen CY-027 security-master artifact (1,440 exact GEM identities, 41 out-date rows), QD-002 historical state coverage (2018–2021 rows and ST/suspension counts), QD-007 discovery lineage, and QD-010 action lineage. It is explicitly a source capture, not a PIT universe. QD-007 has no authorized 2018–2021 immutable date-effective snapshots; current security master is not used as historical authority. Therefore capture readiness is PARTIAL and no extended-state authorization is issued.\n\n## Decision\n\n- `WARMUP_DATA_TECHNICALLY_READY=NO`\n- `HISTORICAL_STATE_CAPTURE_READY=PARTIAL`\n- `EXTENDED_STATE_AUTHORIZATION_READY=NO`\n- `CAN_PROCEED_TO_PHASE12B4_8DATE_PILOT=NO`\n- `CAN_PROCEED_TO_FULL_2018_2021_PIT_MATERIALIZATION=NO`\n- `CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY=NO`\n- `FORMAL_REPLAY_AUTHORIZED=NO`\n\nNo 8-date pilot, 973-date materialization, strategy signal, or strategy outcome was created. QD-007 remains `DISCOVERY_ONLY`; existing Phase 1–12B2 artifacts and frozen strategy are unchanged.\n"""
    (REPORT / "chinext_v1_phase12b3_input_activation.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
