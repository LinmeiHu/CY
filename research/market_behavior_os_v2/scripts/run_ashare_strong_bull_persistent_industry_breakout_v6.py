#!/usr/bin/env python3
"""Strong-bull persistent-industry first-breakout research."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd
import run_ashare_bull_emerging_industry_first_breakout_v5 as v5
import run_ashare_bull_first_limit_next_day_acceptance_v4 as v4
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-STRONG-BULL-PERSISTENT-INDUSTRY-BREAKOUT-V6"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_strong_bull_persistent_industry_breakout_v6")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

RULES = {
    "R1_PERSISTENT_LEADER": {},
    "R2_TOP20_PERSISTENT": {},
    "R3_LOW_EXTENSION": {},
    "R4_HIGH_DEMAND": {},
}
PROFILES = v5.PROFILES
YEARS = v5.YEARS
DISCOVERY = v5.DISCOVERY
CONFIRMATION = v5.CONFIRMATION


class ResearchError(RuntimeError):
    """Fail-closed V6 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A broad bull market is strong when the cross-sectional median has "
            "gained at least 5% over twenty sessions and at least 60% of stocks are "
            "positive. An industry that remains in the top 30% for five sessions is "
            "a persistent leadership state rather than a one-day rotation. The first "
            "twenty-session stock breakout on expanded turnover expresses continued "
            "capital concentration in that main line."
        ),
        "market": {
            "base_state": v1.contract_value()["market_regime"],
            "strong_bull": "median ret20>=5% and positive-ret20 share>=60%",
        },
        "industry": ("positive-ret20 share>50%; ret20 percentile>=70% now and five sessions ago"),
        "stock": {
            "first_breakout": ("close>=prior20 high; previous close<its then-prior20 high"),
            "base": "prior20 range<=30%; pre-signal ret20<=30%",
            "demand": "turnover>=prior20 mean",
        },
        "rules": {
            "R1_PERSISTENT_LEADER": "base contract",
            "R2_TOP20_PERSISTENT": "R1 and industry percentile>=80% now and t-5",
            "R3_LOW_EXTENSION": "R1 and pre-signal ret20<=15%",
            "R4_HIGH_DEMAND": "R1 and turnover expansion>=1.5x",
        },
        "profiles": PROFILES,
        "entry": "first legal next daily open within three market sessions",
        "exit": "target or causal H5/H10/H15 decision then next legal open",
        "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {
            "discovery": list(DISCOVERY),
            "minimum_completed": 300,
            "positive_years_min": 3,
            "mean_holding_max": 15,
        },
        "gate": v1.contract_value()["required_gate"],
        "governance": {
            "independent_from_gap_repair": True,
            "frozen_before_outcomes": True,
            "no_post_2023_signal_or_feature": True,
        },
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(
        SPEC,
        {
            "experiment": EXPERIMENT,
            "status": "OUTCOME_BLIND_PERSISTENT_LEADERSHIP_FREEZE",
            "contract_sha256": v1.sha256(CONTRACT),
            "runner_sha256": v1.sha256(Path(__file__)),
            "dependency_hashes": {
                "v1": v1.sha256(Path(v1.__file__)),
                "v2": v1.sha256(Path(v2.__file__)),
                "v4": v1.sha256(Path(v4.__file__)),
                "v5": v1.sha256(Path(v5.__file__)),
            },
            "daily_sha256": v1.sha256(v1.DAILY),
            "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
            "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
        },
    )
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""
            COPY (
              WITH da AS (
                SELECT *,lag(ret20) OVER w AS prior_ret20,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  count(*) OVER w20 AS history_n20
                FROM read_parquet('{v1.DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
              ), d0 AS (
                SELECT *,lag(coord_close) OVER w AS previous_close,
                  lag(prior20_high) OVER w AS previous_prior20_high
                FROM da WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
              ), i0 AS (
                SELECT *,lag(industry_ret20_percentile,5) OVER (
                  PARTITION BY causal_industry ORDER BY trade_date
                ) AS industry_percentile_tminus5
                FROM read_parquet('{v1.INDUSTRY_PANEL}')
              ), x AS (
                SELECT d0.*,r.market_regime,r.market_median_ret20,
                  r.market_positive_ret20_share,r.market_positive_ret60_share,
                  r.latest_source_timestamp AS market_latest_source,
                  i0.industry_median_ret20,i0.industry_positive_ret20_share,
                  i0.industry_ret20_percentile,i0.industry_percentile_tminus5,
                  i0.industry_n20,i0.latest_source_timestamp AS industry_latest_source,
                  prior20_high/prior20_low-1 AS prior20_range,
                  turnover_fraction/nullif(prior20_turnover,0) AS turnover_expansion,
                  ret20-i0.industry_median_ret20 AS stock_minus_industry_ret20
                FROM d0 JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
                JOIN i0 USING(trade_date,causal_industry)
                WHERE trade_date>=DATE '2014-01-01' AND history_n20=20
                  AND r.market_regime='BULL' AND r.market_median_ret20>=0.05
                  AND r.market_positive_ret20_share>=0.60
                  AND i0.industry_n20>=5 AND i0.industry_positive_ret20_share>0.50
                  AND i0.industry_ret20_percentile>=0.70
                  AND i0.industry_percentile_tminus5>=0.70
                  AND coord_close>=prior20_high
                  AND previous_close<previous_prior20_high
                  AND turnover_fraction>=prior20_turnover
                  AND prior20_high/prior20_low-1<=0.30 AND prior_ret20<=0.30
              )
              SELECT *,'BPL-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,decision_at AS feature_latest_timestamp,
                prior_ret20 AS prior_runup,coord_close/prior20_high-1 AS pre_drawdown,
                prior20_high,prior20_high AS platform_high,
                TRUE AS pass_R1_PERSISTENT_LEADER,
                industry_ret20_percentile>=0.80 AND industry_percentile_tminus5>=0.80
                  AS pass_R2_TOP20_PERSISTENT,
                prior_ret20<=0.15 AS pass_R3_LOW_EXTENSION,
                turnover_expansion>=1.50 AS pass_R4_HIGH_DEMAND
              FROM x ORDER BY trade_date,symbol
            ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
            """
        )
    finally:
        con.close()
    frame = v1.read_parquet_duckdb(CANDIDATES)
    for column in (
        "trade_date",
        "signal_date",
        "decision_at",
        "available_at",
        "market_latest_source",
        "industry_latest_source",
        "feature_latest_timestamp",
    ):
        frame[column] = pd.to_datetime(frame[column])
    causal = (
        frame.available_at.le(frame.decision_at)
        & frame.market_latest_source.le(frame.decision_at)
        & frame.industry_latest_source.le(frame.decision_at)
        & frame.feature_latest_timestamp.le(frame.decision_at)
    )
    if frame.event_id.duplicated().any() or not causal.all():
        raise ResearchError("candidate identity or chronology failure")
    return frame


def sample_and_render(frame: pd.DataFrame) -> pd.DataFrame:
    work = frame.copy()
    work["hash_order"] = work.event_id.map(
        lambda value: hashlib.sha256(str(value).encode()).hexdigest()
    )
    work["year"] = work.signal_date.dt.year
    pieces = [
        part.sort_values("hash_order").head(2)
        for _, part in work.groupby(["year", "sleeve"], sort=True)
    ]
    sample = pd.concat(pieces, ignore_index=True).sort_values("hash_order").head(40)
    if len(sample) < 40:
        rest = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat(
            [sample, rest.sort_values("hash_order").head(40 - len(sample))], ignore_index=True
        )
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    if len(sample) != 40:
        raise ResearchError(f"blind sample has {len(sample)} rows")
    sample.insert(0, "chart_id", [f"BULL-MAINLINE-{i:03d}" for i in range(1, 41)])
    sample.to_csv(BLIND_INDEX, index=False)
    old_pdf = v2.BLIND_PDF
    try:
        v2.BLIND_PDF = BLIND_PDF
        v2.render_blind_charts(sample)
    finally:
        v2.BLIND_PDF = old_pdf
    return sample


def run_stage_a() -> dict[str, Any]:
    hashes = persist_contract()
    frame = build_candidates()
    sample = sample_and_render(frame)
    coverage = {
        rule: {
            "count": int(frame[f"pass_{rule}"].sum()),
            "annual": (
                frame.loc[frame[f"pass_{rule}"]]
                .groupby(frame.loc[frame[f"pass_{rule}"], "signal_date"].dt.year)
                .size()
                .reindex(YEARS, fill_value=0)
                .astype(int)
                .to_dict()
            ),
        }
        for rule in RULES
    }
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(
            frame.feature_latest_timestamp.gt(frame.decision_at).sum()
        ),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT,
        **hashes,
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(frame),
        "blind_chart_count": len(sample),
        "coverage": coverage,
        "audit": audit,
        "outcomes_opened": False,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_stage_a() -> None:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")


def build_candidate_table(outcomes: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    old = (v4.RULES, v4.PROFILES, v4.DISCOVERY)
    try:
        v4.RULES, v4.PROFILES, v4.DISCOVERY = RULES, PROFILES, DISCOVERY
        return v4.candidate_table(outcomes, candidates)
    finally:
        v4.RULES, v4.PROFILES, v4.DISCOVERY = old


def choose(table: pd.DataFrame) -> pd.Series | None:
    old = (v4.RULES, v4.PROFILES)
    try:
        v4.RULES, v4.PROFILES = RULES, PROFILES
        return v4.select_candidate(table)
    finally:
        v4.RULES, v4.PROFILES = old


def persist_failure(table: pd.DataFrame, reason: str) -> dict[str, Any]:
    best = table.sort_values(
        ["positive_years", "median_annual_mean_net", "mean_net"],
        ascending=False,
        kind="mergesort",
    ).iloc[0]
    result = {
        "experiment": EXPERIMENT,
        "verdict": "STRONG_BULL_PERSISTENT_BREAKOUT_FAILS_DISCOVERY_SUPPORT",
        "reason": reason,
        "best_diagnostic_candidate": best.replace({np.nan: None}).to_dict(),
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "repository_2024_plus_signal_or_feature_rows": 0,
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        f"# {EXPERIMENT}\n\n`{result['verdict']}`\n\n{reason}. No portfolio replay.\n",
        encoding="utf-8",
    )
    return result


def run_stage_b() -> dict[str, Any]:
    verify_stage_a()
    candidates = v1.read_parquet_duckdb(CANDIDATES)
    for column in ("signal_date", "decision_at", "feature_latest_timestamp"):
        candidates[column] = pd.to_datetime(candidates[column])
    old_profiles, old_outcomes = v2.PROFILES, v2.OUTCOMES
    try:
        v2.PROFILES, v2.OUTCOMES = PROFILES, OUTCOMES
        outcomes, audit = v2.build_outcomes(candidates)
    finally:
        v2.PROFILES, v2.OUTCOMES = old_profiles, old_outcomes
    if any(audit.values()):
        raise ResearchError(str(audit))
    table = build_candidate_table(outcomes, candidates)
    selected = choose(table)
    if selected is None:
        return persist_failure(table, "No frozen rule/profile meets discovery support")
    rule, profile = str(selected.rule), str(selected.profile)
    selected_all = outcomes.merge(
        candidates[
            [
                "event_id",
                "industry_positive_ret20_share",
                "stock_minus_industry_ret20",
                "turnover_expansion",
                f"pass_{rule}",
            ]
        ],
        on="event_id",
        validate="many_to_one",
    )
    selected_all = selected_all.loc[
        selected_all.profile.eq(profile) & selected_all[f"pass_{rule}"]
    ].copy()
    daily = v1.load_trade_daily(selected_all.symbol.astype(str).unique().tolist())
    old_paths = (v1.ACCEPTED, v1.SKIPPED, v1.NAV)
    try:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = ACCEPTED, SKIPPED, NAV
        accepted, skipped, _nav, portfolio = v1.replay_portfolio(selected_all, daily)
    finally:
        v1.ACCEPTED, v1.SKIPPED, v1.NAV = old_paths
    for column in ("signal_date", "entry_date", "exit_date"):
        accepted[column] = pd.to_datetime(accepted[column])
    annual = v1.annual_summary(accepted.assign(status="COMPLETED"))
    full = v1.summary(accepted.assign(status="COMPLETED"))
    concentration = v1.concentration_metrics(accepted)
    gate = {
        "trades_per_year_gt_50": len(accepted) / 10 > 50,
        "mean_net_ge_3pct": full["mean_net"] >= 0.03,
        "mean_holding_le_15": full["mean_holding_sessions"] <= 15,
        "2019_2021_each_positive": all(annual[str(y)]["mean_net"] > 0 for y in CONFIRMATION),
        "2022_positive": annual["2022"]["mean_net"] > 0,
        "2023_positive": annual["2023"]["mean_net"] > 0,
        "mean_ex_best5_positive": concentration["mean_excluding_best_five_signal_dates"] > 0,
        "top5_positive_pnl_share_le_25pct": concentration["top_five_signal_date_positive_pnl_share"]
        <= 0.25,
    }
    result = {
        "experiment": EXPERIMENT,
        "selected_rule": rule,
        "selected_profile": profile,
        "candidate_table": table.replace({np.nan: None}).to_dict("records"),
        "capacity_accepted_completed_trades": len(accepted),
        "capacity_skips": len(skipped),
        "average_trades_per_year": len(accepted) / 10,
        "full_2014_2023": full,
        "annual": annual,
        "portfolio": portfolio,
        "concentration": concentration,
        "gate": gate,
        "audit": {**audit, "repository_2024_plus_rows_used_for_signal_or_feature": 0},
        "verdict": "STRONG_BULL_PERSISTENT_INDUSTRY_BREAKOUT_EDGE"
        if all(gate.values())
        else "STRONG_BULL_PERSISTENT_INDUSTRY_BREAKOUT_FAILS_TARGET",
        "hashes": {
            "outcomes": v1.sha256(OUTCOMES),
            "accepted": v1.sha256(ACCEPTED),
            "skipped": v1.sha256(SKIPPED),
            "nav": v1.sha256(NAV),
        },
    }
    v1.write_json(RESULT, result)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(
        f"# {EXPERIMENT}\n\n`{result['verdict']}`\n\n"
        f"Selected `{rule}` with `{profile}`.\n\n"
        f"Gate: `{json.dumps(gate, sort_keys=True)}`.\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", action="store_true")
    parser.add_argument("--stage-b", action="store_true")
    args = parser.parse_args()
    if args.stage_a:
        print(json.dumps(run_stage_a(), indent=2, default=str))
    elif args.stage_b:
        print(json.dumps(run_stage_b(), indent=2, default=str))
    else:
        parser.error("choose --stage-a or --stage-b")


if __name__ == "__main__":
    main()
