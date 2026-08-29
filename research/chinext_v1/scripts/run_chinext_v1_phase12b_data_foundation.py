#!/usr/bin/env python3
"""Outcome-blind Phase 12B data-foundation readiness audit.

This script deliberately does not import the strategy runner, read trade/NAV
artifacts, materialize the full PIT universe, or calculate performance.
It records the frozen inputs, audits registered source coverage, and fails
closed when an authorized 2018-2021 PIT universe and compatible 2017 warmup
are unavailable.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
REPORT = ROOT / "research/chinext_v1/reports"
PHASE12A_SUMMARY = REPORT / "chinext_v1_phase12a_extended_history_readiness_summary.json"
VALIDATION_DATES = REPORT / "chinext_v1_phase12a_validation_dates.json"
REGISTRY = ROOT / "configs/data_asset_registry.json"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"

TARGET_DATES = [
    "2018-01-02", "2018-06-29", "2019-01-02", "2019-06-28",
    "2020-01-02", "2020-06-30", "2021-01-04", "2021-06-30",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    phase12a = json.loads(PHASE12A_SUMMARY.read_text(encoding="utf-8"))
    validation = json.loads(VALIDATION_DATES.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert [x["trade_date"] for x in validation["dates"]] == TARGET_DATES

    spec = {
        "phase": "12B",
        "purpose": "CHINEXT_PIT_B_EXTENDED_HISTORY_2018_2021_DATA_FOUNDATION",
        "status": "FROZEN_BEFORE_PILOT",
        "outcome_blind": True,
        "validation_dates": TARGET_DATES,
        "target_date_range": ["2018-01-02", "2021-12-31"],
        "required_price_warmup_trading_days": 180,
        "required_warmup_start_date": "2017-04-12",
        "strategy_sha256": sha256(STRATEGY),
        "phase12a_commit": "cc8808317a0a52c8ef3848675f10ba44e94bbfba",
        "phase12a_validation_dates_sha256": sha256(VALIDATION_DATES),
        "trade_calendar_asset": {
            "asset_id": "QD-003",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet",
            "sha256": "1ccd72b98ead430557f214917ca161dd2f92c26c605262bcd9fe7bc3db2c64ae",
        },
        "extended_universe_source": {
            "asset_id": "QD-007",
            "status": "DISCOVERY_ONLY",
            "path": None,
            "pit_required": True,
            "current_survivor_fallback": False,
        },
        "daily_source_candidate": {
            "asset_id": "QD-001",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily",
            "manifest_sha256": "bbb6c2972165ec4edb99d024fef9a3c4d1a8efc753e7d4ae90fb76d1a71da3f3",
            "coverage": ["2004-01-02", "2026-08-14"],
            "status": "RESEARCH_CONDITIONAL_NOT_ACTIVATED_FOR_THIS_PURPOSE",
        },
        "minute_source_candidate": {
            "asset_id": "QD-004",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813",
            "manifest_sha256": "767298a88618f30d4cc6d5db8a7f609670f88ba32987de6a32994844ad75746c",
            "source_manifest_sha256": "b1a6c88996e5015a23544d63398b49d5dd269d50c71567dc03344fbb83e69e8e",
            "coverage": ["2000-06-09", "2026-08-12"],
            "status": "RESEARCH_CONDITIONAL_1MIN_NOT_DAILY_SUBSTITUTE",
        },
        "existing_cy006": {
            "asset_id": "CY-006",
            "manifest_sha256": "de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2",
            "coverage": ["2018-01-01", "2026-08-12"],
            "status": "RESEARCH_CONDITIONAL",
            "missing_required_warmup_partition": "2017",
        },
        "membership_logic": {
            "board_identity": "GEM/ChinNext A-share identity",
            "min_listed_trading_days": 180,
            "boundary": "179 excluded; 180 included",
            "future_listing": "excluded on trade_date",
            "out_delisting": "retained while historically active, excluded after out_date",
            "st_risk_warning": "excluded on effective state date",
            "suspension_non_tradable": "excluded/fail-closed on effective state date",
            "current_survivor_fallback": False,
            "date_set": "frozen exchange-session calendar",
        },
        "price_semantics": {
            "baseline": "raw/unadjusted bars with causal corporate-action rebasing",
            "volume_unit": "shares",
            "turnover_unit": "CNY amount",
            "pilot_required_fields": ["open", "high", "low", "close", "volume", "amount", "preclose"],
        },
        "authorization": {
            "id": None,
            "status": "NOT_CREATED_DATA_GOVERNANCE_BLOCKED",
            "allowed": ["PIT materialization", "correctness validation", "research-only data preparation"],
            "blocked": ["formal strategy replay", "production", "live trading", "other periods", "current-survivor fallback"],
        },
        "no_performance_metrics_computed": True,
        "formal_replay_executions": 0,
    }
    spec_path = REPORT / "chinext_v1_phase12b_data_foundation_spec.json"
    write_json(spec_path, spec)
    spec_digest = sha256(spec_path)

    pilot = {
        "phase": "12B",
        "status": "BLOCKED_NO_AUTHORIZED_PIT_UNIVERSE_OR_WARMUP",
        "spec_sha256": spec_digest,
        "materialized": False,
        "formal_replay_executions": 0,
        "dates": [
            {
                "trade_date": date,
                "symbol_count": None,
                "set_digest": None,
                "validation_status": "BLOCKED_NO_AUTHORIZED_PIT_ARTIFACT",
            }
            for date in TARGET_DATES
        ],
    }
    write_json(REPORT / "chinext_v1_phase12b_validation_pilot.json", pilot)

    source_matrix = [
        {
            "source": "QD-007 BaoStock query_all_stock(date)", "asset_id": "QD-007",
            "path": None, "date_coverage": "bounded probes only (2010-2017/2018/2020/2026)",
            "field": "date-effective security identity/listing/trade status",
            "pit_semantics": "discovery snapshots; no immutable manifest/record available_at",
            "authorization": "DISCOVERY_ONLY", "known_limitation": "cannot construct PIT universe",
        },
        {
            "source": "CY-006 daily PIT-B v2", "asset_id": "CY-006",
            "path": "/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily",
            "date_coverage": "2018-01-01..2026-08-12", "field": "daily OHLCV/amount/state/limits/actions",
            "pit_semantics": "B frozen causal table with hard_valid", "authorization": "RESEARCH_CONDITIONAL",
            "known_limitation": "no 2017 partition and no standalone historical membership denominator",
        },
        {
            "source": "quant stock_daily", "asset_id": "QD-001",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_daily",
            "date_coverage": "2004-01-02..2026-08-14", "field": "raw daily OHLCV/amount",
            "pit_semantics": "B source; completed-bar available_at but no record-level available_at",
            "authorization": "RESEARCH_CONDITIONAL", "known_limitation": "not activated as CY-006-compatible 2017 warmup; corporate-action parity unproven",
        },
        {
            "source": "quant canonical 1-minute lake", "asset_id": "QD-004",
            "path": "/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813",
            "date_coverage": "2000-06-09..2026-08-12", "field": "raw 1-minute OHLCV/amount",
            "pit_semantics": "B source; completed-bar available_at", "authorization": "RESEARCH_CONDITIONAL",
            "known_limitation": "minute data cannot silently substitute for daily CY-006 PIT rows",
        },
        {
            "source": "historical PIT-B bridge v3", "asset_id": "CYQ-PIT-B-HISTORICAL-BRIDGE-2010-2017-V3",
            "path": "/Users/linmei/Documents/CY/data/registered_inputs/CYQ-PIT-B-HISTORICAL-BRIDGE-2010-2017-v3",
            "date_coverage": "2010-01-01..2017-12-31", "field": "industry/capital/actions bridge",
            "pit_semantics": "derived PIT-B; no supplier revision chain", "authorization": "RESEARCH_CONDITIONAL",
            "known_limitation": "blocked for state generation until QD-007 universe is authorized; actions revision history incomplete",
        },
    ]

    summary = {
        "phase12b_result": "PASS",
        "readiness_status": "BLOCKED_DATA_GOVERNANCE",
        "formal_replay_executions": 0,
        "new_strategy_trades": 0,
        "new_strategy_nav": 0,
        "no_performance_metrics_computed": True,
        "pit_full_materialization": "NO",
        "strategy_sha256": sha256(STRATEGY),
        "strategy_modified": "NO",
        "target_date_range": ["2018-01-02", "2021-12-31"],
        "target_trade_date_count": 973,
        "required_price_warmup_trading_days": 180,
        "required_warmup_start_date": "2017-04-12",
        "validation_dates": TARGET_DATES,
        "phase12b_spec_sha256": spec_digest,
        "extended_universe_source": "QD-007 discovery snapshots plus frozen CY-006 dependencies; no authorized PIT artifact",
        "extended_universe_authorization_id": None,
        "extended_universe_authorization_ready": "NO",
        "warmup_source": "QD-001 candidate (not activated); QD-004 1-minute candidate cannot substitute",
        "warmup_data_asset_id": None,
        "warmup_data_authorization_ready": "NO",
        "warmup_price_semantics_match": "NO_UNPROVEN_CAUSAL_REBASE",
        "warmup_volume_semantics_match": "YES_SCHEMA_ONLY",
        "warmup_turnover_semantics_match": "YES_SCHEMA_ONLY",
        "warmup_symbol_identity_match": "YES_ADAPTER_REQUIRED",
        "warmup_calendar_match": "YES",
        "overlap_validation_result": "NOT_RUN_NO_AUTHORIZED_CY006_COMPATIBLE_WARMUP",
        "pilot_materialization_authorized": "NO",
        "pilot_exact_set_match_result": "NOT_RUN_BLOCKED",
        "pilot_date_results": pilot["dates"],
        "boundary_validation": {
            "179_180": "NOT_RUN_FOR_2018_2021_NO_AUTHORIZED_UNIVERSE",
            "future_listing": "NOT_RUN_BLOCKED",
            "historical_non_survivor": "UNRESOLVED_NO_AUTHORIZED_PIT_UNIVERSE",
            "historical_st": "UNRESOLVED_NO_AUTHORIZED_PIT_UNIVERSE",
            "historical_suspension": "UNRESOLVED_NO_AUTHORIZED_PIT_UNIVERSE",
        },
        "early_2018_warmup_coverage": "UNAVAILABLE_NO_AUTHORIZED_WARMUP_AND_PIT_DENOMINATOR",
        "historical_non_survivor_count_2018_2021": "UNRESOLVED",
        "full_materialization_estimated_rows": 1070300,
        "full_materialization_estimated_bytes": 3161896,
        "full_materialization_technically_ready": "NO",
        "full_materialization_authorized": "NO",
        "formal_replay_authorized": "NO",
        "readiness_gates": {
            "extended_universe_ready": "NO",
            "price_data_ready": "PARTIAL",
            "history_window_ready": "NO",
            "market_anchor_ready": "YES",
            "execution_data_ready": "PARTIAL",
            "corporate_action_semantics_ready": "YES",
            "governance_ready": "NO",
        },
        "source_matrix": source_matrix,
        "blockers": [
            "QD-007 remains DISCOVERY_ONLY; no immutable authorized date-effective 2018-2021 ChinNext PIT universe",
            "QD-001 2017 daily candidate is not activated/authorized as a CY-006-compatible causal warmup source",
            "QD-004 is 1-minute and cannot silently substitute for required daily PIT rows",
            "historical non-survivor/ST/suspension PIT coverage cannot be proven without the authorized universe and state joins",
            "full 2018-2021 materialization and frozen replay require a future separate authorization",
        ],
        "next_recommended_phase": "Authorize/activate a separate PIT-B universe and CY-006-compatible 2017 daily warmup, then run Phase 12C correctness-only full materialization; no replay in Phase 12B",
        "qd007_status": registry["assets"][next(i for i, a in enumerate(registry["assets"]) if a.get("asset_id") == "QD-007")]["status"],
        "phase12a_summary_sha256": sha256(PHASE12A_SUMMARY),
    }
    write_json(REPORT / "chinext_v1_phase12b_data_foundation_summary.json", summary)

    report = f"""# ChinNext V1 Phase 12B — extended-history data foundation\n\nOutcome-blind readiness only. This run performed zero strategy replay, zero full PIT materialization, and computed no strategy performance metrics.\n\n## Frozen inputs\n\n- Target: `2018-01-02 .. 2021-12-31` (973 exchange sessions)\n- Required price warmup: 180 completed sessions; derived start `2017-04-12`\n- Validation dates (frozen in Phase 12A): {', '.join(TARGET_DATES)}\n- Strategy SHA-256: `{summary['strategy_sha256']}`\n- QD-007 remains `DISCOVERY_ONLY`.\n\n## Governance decision\n\n`PHASE12B_RESULT = PASS` means the audit and blocker evidence are complete. Readiness for materialization is **BLOCKED_DATA_GOVERNANCE**. No new bounded authorization was created because its required source facts are not yet authorized. QD-007 was not upgraded.\n\nThe existing CY-006 table is a frozen PIT-B daily source beginning at 2018-01-01 and has no 2017 partition. QD-001 has local raw daily bars reaching earlier years, but its causal corporate-action rebasing and CY-006-compatible adapter are not activated for this purpose. QD-004 has earlier raw 1-minute bars; using them as daily bars would be a silent semantic substitution and is prohibited.\n\nThe QD-007 discovery snapshots and the 2010–2017 bridge do not provide an immutable, authorized date-effective ChinNext universe with the required historical listing, out/delisting, ST/risk-warning, suspension, and non-survivor semantics. A current security master cannot fill this gap.\n\n## Source matrix\n\nThe script records the complete candidate matrix in the JSON summary. All unknown required facts fail closed. Existing 2022–2025 PIT artifacts and their authorizations are not extended or rebuilt.\n\n## Pilot and correctness\n\nThe eight frozen dates were not changed. Pilot materialization was **not run** because no authorized PIT universe and compatible warmup source passed the gate; each date is recorded as `BLOCKED_NO_AUTHORIZED_PIT_ARTIFACT`. Boundary, future-listing, non-survivor, ST, suspension, and overlap checks are therefore explicitly unavailable for 2018–2021 rather than inferred from current membership.\n\nThe 179/180 contract remains the frozen rule (`179` excluded, `180` included), but a 2018–2021 source-specific test is deferred until authorization exists.\n\n## Readiness gates\n\n- Extended universe: **NO**\n- Price data: **PARTIAL** (2018–2021 CY-006 observations exist; 2017 compatible warmup is not activated)\n- History window: **NO**\n- Market anchor: **YES** (existing 399102.SZ coverage)\n- Execution data: **PARTIAL**\n- Corporate-action semantics: **YES** for the frozen CY-006 contract; warmup equivalence is not proven\n- Governance: **NO**\n\n`CAN_PROCEED_TO_FULL_2018_2021_PIT_MATERIALIZATION = NO` and `CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY = NO`.\n\nEstimated full materialization size is approximately 1,070,300 membership rows / 3,161,896 bytes using the Phase 12A empirical estimate; no large build was started.\n\n## Blockers and next action\n\n1. Materialize and authorize an immutable QD-007-derived 2018–2021 date-effective universe, including historical non-survivor, ST, suspension, and out-date evidence.\n2. Activate a daily 2017 warmup source with proven raw-price, causal corporate-action, volume/amount, symbol, and calendar equivalence to CY-006.\n3. Create a new bounded data-foundation authorization tied to exact manifests and the eight dates.\n4. Run Phase 12C full PIT materialization and correctness validation only after those gates; keep replay authorization separate.\n\nNo strategy parameters, frozen strategy source, existing PIT artifacts, or Phase 1–12A reports were modified.\n"""
    (REPORT / "chinext_v1_phase12b_data_foundation.md").write_text(report, encoding="utf-8")


if __name__ == "__main__":
    main()
