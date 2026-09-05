#!/usr/bin/env python3
"""Frozen sectoral-bull quiet-platform repricing strategy evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-SECTORAL-QUIET-PLATFORM-REPRICING-V59"
EXT = Path("/Volumes/quant/CY_quant_research/bull_sectoral_quiet_platform_repricing_v59")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
CANDIDATE_MANIFEST = EXT / "stage_a/candidate_manifest.json"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"
COMBINED_ACCEPTED = EXT / "stage_b/combined_v24_v59_accepted.parquet"
COMBINED_SKIPPED = EXT / "stage_b/combined_v24_v59_skipped.parquet"
COMBINED_NAV = EXT / "stage_b/combined_v24_v59_nav.parquet"
V24_CANDIDATES = Path("/Volumes/quant/CY_quant_research/ashare_bull_quiet_platform_dual_demand_v24/stage_a/candidates.parquet")
V24_OUTCOMES = Path("/Volumes/quant/CY_quant_research/ashare_bull_quiet_platform_dual_demand_v24/stage_b/outcomes.parquet")
PROFILE = "T15_H15_NO_STOP"
YEARS = tuple(range(2014, 2024))


class ResearchError(RuntimeError):
    """Fail-closed V59 error."""


def _load_candidates() -> pd.DataFrame:
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in (
        "trade_date", "signal_date", "decision_at", "available_at",
        "formation_known_at", "market_latest_source", "industry_latest_source",
        "market_state_latest", "industry_state_latest", "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    required = {
        "BROAD_AND_SECTOR_BULL",
        "SECTOR_BULL_ONLY",
    }
    causal = (
        frame.available_at.le(frame.decision_at)
        & frame.formation_known_at.le(frame.decision_at)
        & frame.feature_latest_timestamp.le(frame.decision_at)
    )
    rule = (
        frame.industry_n20.ge(5)
        & frame.industry_median_ret20.gt(0)
        & frame.industry_median_ret60.gt(-0.05)
        & frame.industry_positive_ret20_share.ge(0.50)
        & frame.industry_ret20_percentile.ge(0.50)
        & frame.industry_median_ret1.gt(0)
        & frame.industry_positive_ret1_share.ge(0.50)
        & frame.market_median_ret20.gt(-0.08)
        & frame.market_positive_ret20_share.gt(0.30)
    )
    broad_lane = frame.regime_lane.eq("BROAD_AND_SECTOR_BULL") & frame.market_regime.eq("BULL")
    sector_lane = frame.regime_lane.eq("SECTOR_BULL_ONLY") & frame.market_regime.ne("BULL")
    if v1.sha256(CANDIDATES) != "1be1c277d0f4c07a69bed6912054fc6c8a14ff8046158395a44d19b387a35681":
        raise ResearchError("frozen candidate bytes changed")
    if frame.event_id.duplicated().any() or not causal.all() or not rule.all():
        raise ResearchError("candidate identity, causal clock, or frozen admission failed")
    if set(frame.regime_lane.unique()) != required or not (broad_lane | sector_lane).all():
        raise ResearchError("regime-lane identity failed")
    if frame.signal_date.gt(pd.Timestamp("2023-12-31")).any():
        raise ResearchError("post-2023 signal found")
    return frame


def verify_stage_a() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "candidate_manifest_sha256": v1.sha256(CANDIDATE_MANIFEST),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A freeze drift: {drift}")
    _load_candidates()
    return freeze


def _summary(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "completed_trades": 0, "mean_net": None, "median_net": None,
            "win_rate": None, "target_hit_rate": None, "severe_loss10": None,
            "mean_holding_sessions": None, "median_holding_sessions": None,
        }
    return {
        "completed_trades": int(len(frame)),
        "mean_net": float(frame.net_return.mean()),
        "median_net": float(frame.net_return.median()),
        "win_rate": float(frame.net_return.gt(0).mean()),
        "target_hit_rate": float(frame.exit_reason.eq("TARGET_15").mean()),
        "severe_loss10": float(frame.net_return.le(-0.10).mean()),
        "mean_holding_sessions": float(frame.holding_sessions.mean()),
        "median_holding_sessions": float(frame.holding_sessions.median()),
    }


def _attach_features(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "event_id", "regime_lane", "industry_positive_ret20_share",
        "stock_minus_industry_ret20", "turnover_expansion",
    ]
    return outcomes.merge(candidates[columns], on="event_id", how="left", validate="many_to_one")


def _replay(trades: pd.DataFrame, accepted_path: Path, skipped_path: Path, nav_path: Path):
    symbols = trades.loc[trades.status.eq("COMPLETED"), "symbol"].astype(str).unique().tolist()
    daily = v1.load_trade_daily(symbols)
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = accepted_path, skipped_path, nav_path
        return v1.replay_portfolio(trades, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths


def _combined_trade_set(v59_trades: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    v24_outcomes = v1.read_parquet_duckdb(V24_OUTCOMES)
    v24_candidates = v1.read_parquet_duckdb(V24_CANDIDATES)
    for column in ("signal_date", "entry_date", "exit_date"):
        v24_outcomes[column] = pd.to_datetime(v24_outcomes[column])
    v24_features = v24_candidates[
        [
            "event_id", "admission_lane", "industry_positive_ret20_share",
            "stock_minus_industry_ret20", "turnover_expansion",
        ]
    ].rename(columns={"admission_lane": "regime_lane"})
    v24 = v24_outcomes.loc[v24_outcomes.profile.eq(PROFILE)].copy().merge(
        v24_features, on="event_id", how="left", validate="many_to_one"
    )
    overlap = v24.merge(
        v59_trades,
        on="event_id",
        suffixes=("_v24", "_v59"),
        how="inner",
    )
    mismatch = 0
    for column in ("symbol", "signal_date", "status", "entry_date", "exit_date", "entry_price", "exit_price", "net_return"):
        left, right = overlap[f"{column}_v24"], overlap[f"{column}_v59"]
        if pd.api.types.is_numeric_dtype(left):
            mismatch += int((~np.isclose(left, right, equal_nan=True)).sum())
        else:
            mismatch += int((left.fillna("<NA>") != right.fillna("<NA>")).sum())
    if mismatch:
        raise ResearchError(f"V24/V59 shared event outcome mismatch count {mismatch}")
    v24["strategy_source"] = "V24"
    v59 = v59_trades.copy()
    v59["strategy_source"] = "V59"
    combined = pd.concat([v24, v59], ignore_index=True, sort=False)
    source_count = combined.groupby("event_id").strategy_source.nunique()
    combined["strategy_source"] = combined.event_id.map(
        source_count.map(lambda count: "BOTH_V24_V59" if count == 2 else "SINGLE")
    )
    combined = combined.sort_values(["event_id", "strategy_source"], kind="mergesort").drop_duplicates("event_id")
    return combined, {
        "shared_event_count": int(overlap.event_id.nunique()),
        "shared_outcome_mismatch_count": int(mismatch),
        "combined_unique_event_count": int(combined.event_id.nunique()),
    }


def render_report(result: dict[str, Any]) -> None:
    lines = [
        f"# {EXPERIMENT}", "", "## Frozen mechanism", "",
        "A frozen quiet-inventory platform is admitted when a PIT industry is locally bullish and improving, while a broad-market crash veto is satisfied. Broad-market BULL and sector-only BULL are kept as separate lanes.",
        "", "Entry is the next legal daily open, target +15%, no failure stop, H15 time stop, and 40 bp round-trip costs.",
        "", "## Capacity-constrained 2014–2023 result", "",
        f"- Trades: {result['full']['completed_trades']} ({result['average_trades_per_year']:.1f}/year)",
        f"- Mean / median net: {result['full']['mean_net']:.4%} / {result['full']['median_net']:.4%}",
        f"- Mean holding: {result['full']['mean_holding_sessions']:.2f} sessions",
        f"- Gate passed: {result['gate_passed']}", "", "## Annual evidence", "",
        "| Year | Trades | Mean net | Median net | Mean hold |", "|---:|---:|---:|---:|---:|",
    ]
    for year, row in result["annual"].items():
        lines.append(f"| {year} | {row['completed_trades']} | {row['mean_net']:.2%} | {row['median_net']:.2%} | {row['mean_holding_sessions']:.2f} |")
    lines += ["", "## Interpretation", "", result["interpretation"], "", f"Verdict: **{result['verdict']}**"]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_stage_b() -> dict[str, Any]:
    freeze = verify_stage_a()
    candidates = _load_candidates()
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES = {PROFILE: {"horizon": 15, "target": 0.15}}
        v2.OUTCOMES = OUTCOMES
        outcomes, outcome_audit = v2.build_outcomes(candidates)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    trades = _attach_features(outcomes.loc[outcomes.profile.eq(PROFILE)].copy(), candidates)
    accepted, skipped, nav, portfolio = _replay(trades, ACCEPTED, SKIPPED, NAV)
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    full = _summary(accepted)
    annual = {str(year): _summary(accepted.loc[accepted.signal_date.dt.year.eq(year)]) for year in YEARS}
    lanes = {str(lane): _summary(part) for lane, part in accepted.groupby("regime_lane", sort=True)}
    concentration = v1.concentration_metrics(accepted)
    combined_trades, combined_audit = _combined_trade_set(trades)
    combined_accepted, combined_skipped, combined_nav, combined_portfolio = _replay(
        combined_trades, COMBINED_ACCEPTED, COMBINED_SKIPPED, COMBINED_NAV
    )
    for column in ("signal_date", "entry_date", "exit_date"):
        combined_accepted[column] = pd.to_datetime(combined_accepted[column])
    v24_events = set(v1.read_parquet_duckdb(V24_OUTCOMES).event_id.astype(str))
    accepted_overlap = int(accepted.event_id.astype(str).isin(v24_events).sum())
    gate = {
        "accepted_completed_trades_gt_500": len(accepted) > 500,
        "mean_net_gt_3pct": full["mean_net"] > 0.03,
        "mean_holding_lt_15": full["mean_holding_sessions"] < 15,
        "2021_2023_each_positive": all(annual[str(year)]["mean_net"] is not None and annual[str(year)]["mean_net"] > 0 for year in (2021, 2022, 2023)),
        "mean_excluding_best_five_dates_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top_five_date_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"] <= 0.25,
        "sector_bull_only_mean_positive": lanes.get("SECTOR_BULL_ONLY", {}).get("mean_net", -1) > 0,
    }
    audit = {
        **outcome_audit,
        **combined_audit,
        "candidate_feature_after_decision_count": int(candidates.feature_latest_timestamp.gt(candidates.decision_at).sum()),
        "post_2023_signal_or_feature_count": int(candidates.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "negative_cash_count": int(portfolio["negative_cash_count"]),
        "max_k_violation_count": int(portfolio["max_k_violation_count"]),
        "combined_negative_cash_count": int(combined_portfolio["negative_cash_count"]),
        "combined_max_k_violation_count": int(combined_portfolio["max_k_violation_count"]),
    }
    fail_keys = [key for key, value in audit.items() if key not in {"shared_event_count", "combined_unique_event_count"} and value]
    if fail_keys:
        raise ResearchError(f"audit failed: {fail_keys}")
    gate_passed = all(gate.values())
    interpretation = (
        "The frozen sector-local bull translation meets the revised economic gate and contributes a positive sector-only lane."
        if gate_passed else
        "The frozen sector-local bull translation does not meet the revised gate; no threshold or execution rule was changed after outcomes were opened."
    )
    result = {
        "experiment": EXPERIMENT,
        "contract_sha256": freeze["contract_sha256"],
        "spec_sha256": freeze["spec_sha256"],
        "profile": PROFILE,
        "candidate_count": int(len(candidates)),
        "capacity_accepted_completed_trades": int(len(accepted)),
        "capacity_skips": int(len(skipped)),
        "average_trades_per_year": float(len(accepted) / 10),
        "full": full,
        "annual": annual,
        "regime_lanes": lanes,
        "portfolio": portfolio,
        "concentration": concentration,
        "v24_overlap": {
            "accepted_event_overlap": accepted_overlap,
            "accepted_unique_to_v59": int(len(accepted) - accepted_overlap),
            "combined_accepted_trades": int(len(combined_accepted)),
            "combined_capacity_skips": int(len(combined_skipped)),
            "combined_summary": _summary(combined_accepted),
            "combined_portfolio": combined_portfolio,
        },
        "gate": gate,
        "gate_passed": gate_passed,
        "audit": audit,
        "repository_2024_plus_signal_or_feature_rows_opened": 0,
        "post_2023_rows_used_only_to_resolve_pre_2024_trades": True,
        "interpretation": interpretation,
        "verdict": "BULL_SECTORAL_QUIET_PLATFORM_TARGET_MET" if gate_passed else "BULL_SECTORAL_QUIET_PLATFORM_TARGET_FAILED",
        "hashes": {
            "outcomes": v1.sha256(OUTCOMES), "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED), "nav": v1.sha256(NAV),
            "combined_accepted": v1.sha256(COMBINED_ACCEPTED),
            "combined_skipped": v1.sha256(COMBINED_SKIPPED), "combined_nav": v1.sha256(COMBINED_NAV),
        },
    }
    v1.write_json(RESULT, result)
    render_report(result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if not args.stage_b:
        parser.error("choose --stage-b")
    print(json.dumps(run_stage_b(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
