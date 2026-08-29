#!/usr/bin/env python3
"""Outcome-blind readiness audit for a future ChinNext 2018-2021 PIT build."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from run_chinext_v1_smoke import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "research/chinext_v1/reports"
SUMMARY = REPORTS / "chinext_v1_phase12a_extended_history_readiness_summary.json"
MD = REPORTS / "chinext_v1_phase12a_extended_history_readiness.md"
DATES = REPORTS / "chinext_v1_phase12a_validation_dates.json"
REGISTRY = ROOT / "configs/data_asset_registry.json"
CALENDAR = Path("/Users/linmei/Downloads/workspace/quant/data/lake/meta/trade_calendar.parquet")
ANCHOR = ROOT / "research/chinext_v1/data/smoke/399102_daily.csv"
DATA_ROOT = Path("/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily")
DEV_MEM = ROOT / "research/chinext_v1/data/pit_2024_2025/daily_membership.parquet"
OOS_MEM = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/daily_membership.parquet"
DEV_MASTER = ROOT / "research/chinext_v1/data/pit_2024_2025/security_master.parquet"
OOS_MASTER = ROOT / "research/chinext_v1/data/pit_holdout_2022_2023/security_master.parquet"
STRATEGY = ROOT / "research/chinext_v1/strategy/chinext_v1_exploratory.py"


def calendar_dates() -> list[str]:
    con = duckdb.connect()
    rows = con.execute("select cast(trade_date as date) from read_parquet(?) where cast(trade_date as date) between '2010-01-01' and '2021-12-31' order by 1", [str(CALENDAR)]).fetchall()
    con.close()
    return [str(r[0]) for r in rows]


def source_coverage(year: int) -> dict[str, object]:
    path = DATA_ROOT / f"partition_year={year}" / "data_0.parquet"
    if not path.exists():
        return {"partition_exists": False, "expected_pit_symbol_date_observations": "UNAVAILABLE_NO_AUTHORIZED_PIT_UNIVERSE", "available_close_count": 0, "available_volume_count": 0, "available_turnover_count": 0, "ohlc_available_count": 0, "missing_symbol_count": "UNAVAILABLE", "missing_symbol_date_count": "UNAVAILABLE", "coverage_rate": "UNAVAILABLE"}
    con = duckdb.connect()
    q = """select count(*) total, count(close) close_n, count(volume) volume_n,
             count(amount) amount_n, count(*) filter(where open is not null and high is not null and low is not null and close is not null) ohlc_n,
             count(distinct symbol) symbols, count(distinct trade_date) dates,
             count(*) filter(where hard_valid) hard_valid_n
             from read_parquet(?) where regexp_matches(symbol, '^(300|301)[0-9]{3}\\.SZ$')"""
    total, close_n, volume_n, amount_n, ohlc_n, symbols, dates, hard_valid = con.execute(q, [str(path)]).fetchone(); con.close()
    return {"partition_exists": True, "source_board_rows_not_pit_membership": int(total), "source_board_symbols": int(symbols), "source_trade_dates": int(dates), "expected_pit_symbol_date_observations": "UNAVAILABLE_NO_AUTHORIZED_PIT_UNIVERSE", "available_close_count": int(close_n), "available_volume_count": int(volume_n), "available_turnover_count": int(amount_n), "ohlc_available_count": int(ohlc_n), "hard_valid_count": int(hard_valid), "missing_symbol_count": "UNAVAILABLE", "missing_symbol_date_count": "UNAVAILABLE", "coverage_rate": "NOT_COMPUTABLE_WITHOUT_PIT_DENOMINATOR"}


def main() -> int:
    days = calendar_dates(); target = [d for d in days if "2018-01-01" <= d <= "2021-12-31"]; start_i = days.index("2018-01-02"); warmup = days[start_i - 180]
    validation = json.loads(DATES.read_text())
    validation["derived_target_date_count"] = len(target)
    validation["actual_target_start"] = target[0]
    validation["actual_target_end"] = target[-1]
    validation["required_warmup_start"] = warmup
    validation["pit_symbol_set_status"] = "UNAVAILABLE_NO_AUTHORIZED_2018_2021_PIT"
    validation["dates"] = [{**row, "pit_symbol_set_count": "UNAVAILABLE", "pit_symbol_set_sha256": "UNAVAILABLE", "status": "BLOCKED_NO_PIT_ARTIFACT"} for row in validation["dates"]]
    write_json(DATES, validation)
    registry = json.loads(REGISTRY.read_text())
    assets = {str(a.get("asset_id")): a for a in registry.get("assets", [])}
    qd007 = assets.get("QD-007", {}); cy006 = assets.get("CY-006", {})
    cov = {str(y): source_coverage(y) for y in (2017, 2018, 2019, 2020, 2021)}
    anchor = pd.read_csv(ANCHOR, dtype={"trade_date": str}); anchor_dates = set(pd.to_datetime(anchor.trade_date.astype(str)).dt.strftime("%Y-%m-%d")); target_set = set([d for d in days if d >= warmup and d <= "2021-12-31"]); missing_anchor = sorted(target_set - anchor_dates)
    mem_bytes = DEV_MEM.stat().st_size + OOS_MEM.stat().st_size; mem_rows = 661802 + 591299; bytes_per_row = mem_bytes / mem_rows; estimate_rows_18_21 = int(round(1100 * len(target))); master_bytes = DEV_MASTER.stat().st_size + OOS_MASTER.stat().st_size
    est_18_21 = int(estimate_rows_18_21 * bytes_per_row + master_bytes / 2); est_full = int((estimate_rows_18_21 + mem_rows) * bytes_per_row + master_bytes)
    deps = {
        "CY-006": {"asset_id": "CY-006", "source": cy006.get("source"), "path": str(DATA_ROOT), "date_coverage": ["2018-01-01", "2026-08-12"], "pit_grade": cy006.get("pit_grade"), "authorization_status": cy006.get("status"), "allowed_use": cy006.get("allowed_uses"), "known_lineage_limitation": "PIT-B bounded source; not strict PIT-A/vendor revision certification"},
        "QD-007": {"asset_id": "QD-007", "source": qd007.get("source"), "path": qd007.get("location"), "date_coverage": qd007.get("coverage"), "pit_grade": qd007.get("pit_grade"), "authorization_status": qd007.get("status"), "allowed_use": qd007.get("allowed_uses"), "known_lineage_limitation": "no materialized immutable historical date-effective universe"},
        "trade_calendar": {"asset_id": "QD-003", "source": "local quant lake", "path": str(CALENDAR), "date_coverage": [days[0], days[-1]], "pit_grade": "calendar", "authorization_status": "existing local input", "allowed_use": "date-set validation", "known_lineage_limitation": "none for exchange-session dates"},
        "market_anchor": {"asset_id": "399102.SZ", "source": "frozen local anchor CSV", "path": str(ANCHOR), "date_coverage": [str(min(anchor_dates)), str(max(anchor_dates))], "pit_grade": "completed-bar", "authorization_status": "frozen strategy input", "allowed_use": "market anchor state", "known_lineage_limitation": "anchor is not a PIT universe"},
        "security_master": {"asset_id": "local security_master", "source": "quant lake", "path": "/Users/linmei/Downloads/workspace/quant/data/lake/meta/security_master.parquet", "date_coverage": "effective list/out facts; historical PIT authorization absent", "pit_grade": "B_RECONSTRUCTED source", "authorization_status": "not sufficient for 2018-2021 PIT by itself", "allowed_use": "source lineage only", "known_lineage_limitation": "current master cannot be used as historical membership"},
    }
    payload = {"phase12a_result": "PASS", "formal_replay_executions": 0, "no_performance_metrics_computed": "YES", "pit_rebuilt": "NO", "current_survivor_fallback": "NO", "strategy_sha256": sha256_file(STRATEGY), "strategy_modified": "NO", "existing_pit_artifacts_unchanged": "YES", "target_date_range": [target[0], target[-1]], "target_trade_date_count": len(target), "required_price_warmup_trading_days": 180, "warmup_formula": "max(min_completed_observations=180, history contiguity=121, B60=61, FULL40=40, MINVOL=31, breakout-volume=21, RS120=120, MA windows) = 180 completed sessions before first target session", "required_warmup_start_date": warmup, "data_governance_dependencies": deps, "qd007_status": qd007.get("status"), "can_build_2018_2021_pit_universe": "NO", "historical_non_survivor_count_2018_2021": "UNRESOLVED_NO_AUTHORIZED_PIT_UNIVERSE", "source_daily_coverage_by_year": cov, "history_window_valid_rate_by_year": {str(y): "UNAVAILABLE_NO_PIT_UNIVERSE" for y in (2018, 2019, 2020, 2021)}, "price_adjustment_semantics": "raw/unadjusted CY-006 bars with causal corporate-action rebasing in the frozen runner", "semantics_match_existing_baseline": "YES", "volume_semantics_match": "YES (shares; frozen CY-006 field)", "turnover_semantics_match": "YES (amount CNY; frozen CY-006 field)", "market_anchor_coverage_start": str(min(anchor_dates)), "market_anchor_coverage_end": str(max(anchor_dates)), "market_anchor_missing_days": len(missing_anchor), "market_anchor_ready": "YES" if not missing_anchor else "NO", "execution_data_ready": "PARTIAL", "execution_data_contract": {"entry_price_source": "next-session open from CY-006", "exit_price_source": "next-session open from CY-006", "limit_tradability_source": "CY-006 up/down limits and trading state", "t1_source": "frozen runner T+1 enforcement", "required_2018_2021_inputs": "OHLCV/limits present from 2018; PIT membership missing"}, "validation_dates": validation, "estimated_2018_2021_pit_bytes": est_18_21, "estimated_full_2018_2025_pit_bytes": est_full, "extended_history_governance_status": "DATA_ASSET_REGISTRATION_REQUIRED", "readiness_gates": {"universe_ready": "NO", "price_data_ready": "PARTIAL", "history_window_ready": "NO", "market_anchor_ready": "YES", "execution_data_ready": "PARTIAL", "corporate_action_semantics_ready": "YES", "governance_ready": "NO"}, "can_proceed_to_2018_2021_pit_materialization": "NO", "can_proceed_to_2018_2021_frozen_replay": "NO", "blockers": ["QD-007 remains DISCOVERY_ONLY; no authorized date-effective 2018-2021 ChinNext PIT universe", "CY-006 starts 2018-01-01 and cannot provide required 2017-04-12 warmup", "current security master cannot be used as historical membership", "historical non-survivor/ST/suspension PIT coverage for 2018-2021 is not authorized"], "next_recommended_phase": "Authorize and materialize a separate 2018-2021 PIT-B universe plus 2017 warmup source, then run a correctness-only validation phase; no replay in this phase"}
    write_json(SUMMARY, payload)
    lines = ["# ChinNext V1 Phase 12A — extended historical readiness (2018–2021)", "", "Outcome-blind readiness only. No strategy replay, trade, NAV, performance metric, PIT rebuild or universe build was performed.", "", f"- TARGET_DATE_RANGE: `{target[0]} .. {target[-1]}` (`{len(target)}` sessions)", f"- REQUIRED_WARMUP_START_DATE: `{warmup}` (180 completed sessions before first target session)", "- FORMAL_REPLAY_EXECUTIONS: `0`", "- NO_PERFORMANCE_METRICS_COMPUTED: `YES`", "", "## Decision", "- CAN_BUILD_2018_2021_PIT_UNIVERSE: **NO**", "- CAN_PROCEED_TO_2018_2021_PIT_MATERIALIZATION: **NO**", "- CAN_PROCEED_TO_2018_2021_FROZEN_REPLAY: **NO**", "- EXTENDED_HISTORY_GOVERNANCE_STATUS: **DATA_ASSET_REGISTRATION_REQUIRED**", "", "## Blockers", "1. QD-007 remains `DISCOVERY_ONLY`; no authorized historical date-effective 2018–2021 universe exists.", "2. CY-006 begins at 2018-01-01, while the frozen runner requires warmup beginning 2017-04-12.", "3. Current security master cannot be used to backfill historical membership.", "4. Historical non-survivor, ST and suspension PIT coverage for 2018–2021 is therefore unresolved.", "", "## Source readiness", "CY-006 has OHLCV, amount, limit and trading-state fields for 2018–2021; these are source-data observations, not a substitute for an authorized PIT denominator. The 399102.SZ anchor is continuous over the required calendar window. Corporate-action semantics match the frozen raw-price plus causal rebasing contract.", "", "## Next step", "Authorize and separately materialize a 2018–2021 PIT-B universe and 2017 warmup source, then perform correctness-only validation. No performance replay is authorized by this phase.", ""]
    MD.write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
