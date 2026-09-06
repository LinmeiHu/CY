#!/usr/bin/env python3
"""Strong-bull leader contraction then demand-breakout research."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1
import run_ashare_strong_bull_persistent_industry_breakout_v6 as v6

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-STRONG-BULL-LEADER-CONTRACTION-BREAKOUT-V7"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_strong_bull_leader_contraction_breakout_v7")
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
    "R1_CONTRACTION15_DEMAND15": {},
    "R2_CONTRACTION10_DEMAND15": {},
    "R3_CONTRACTION15_DEMAND20": {},
    "R4_DEEP_DRYUP_CONTRACTION15": {},
}
PROFILES = v6.PROFILES
YEARS = v6.YEARS


class ResearchError(RuntimeError):
    """Fail-closed V7 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "In a strong causal bull market and persistent leading industry, a "
            "five-session price contraction accompanied by turnover dry-up indicates "
            "reduced near-term supply. The first twenty-session high breakout on a "
            "large turnover re-expansion indicates renewed demand dominance."
        ),
        "market": {
            "base_state": v1.contract_value()["market_regime"],
            "strong_bull": "market median ret20>=5%; positive-ret20 share>=60%",
        },
        "industry": ("positive-ret20 share>50%; ret20 percentile>=70% now and five sessions ago"),
        "stock": {
            "first_breakout": ("close>=prior20 high; previous close<its then-prior20 high"),
            "base": "prior20 range<=30%; pre-signal ret20<=30%",
            "supply_dryup": "prior5 mean turnover<=prior20 mean turnover",
            "demand_reexpansion": "signal turnover/prior5 mean turnover",
        },
        "rules": {
            "R1": "prior5 range<=15%; demand re-expansion>=1.5x",
            "R2": "prior5 range<=10%; demand re-expansion>=1.5x",
            "R3": "prior5 range<=15%; demand re-expansion>=2.0x",
            "R4": "R1 and prior5 turnover<=70% of prior20 turnover",
        },
        "profiles": PROFILES,
        "entry": "first legal next daily open within three market sessions",
        "exit": "target or causal H5/H10/H15 decision then next legal open",
        "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {
            "discovery": list(v6.DISCOVERY),
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
            "status": "OUTCOME_BLIND_CONTRACTION_DEMAND_FREEZE",
            "contract_sha256": v1.sha256(CONTRACT),
            "runner_sha256": v1.sha256(Path(__file__)),
            "execution_engine_sha256": v1.sha256(Path(v2.__file__)),
            "portfolio_engine_sha256": v1.sha256(Path(v1.__file__)),
            "selection_engine_sha256": v1.sha256(Path(v6.__file__)),
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
                  max(coord_high) OVER w5 AS prior5_high,
                  min(coord_low) OVER w5 AS prior5_low,
                  avg(turnover_fraction) OVER w5 AS prior5_turnover,
                  count(*) OVER w20 AS history_n20
                FROM read_parquet('{v1.DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                  w5 AS (PARTITION BY symbol ORDER BY trade_date
                    ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)
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
                  r.market_positive_ret20_share,
                  r.latest_source_timestamp AS market_latest_source,
                  i0.industry_median_ret20,i0.industry_positive_ret20_share,
                  i0.industry_ret20_percentile,i0.industry_percentile_tminus5,
                  i0.industry_n20,i0.latest_source_timestamp AS industry_latest_source,
                  prior20_high/prior20_low-1 AS prior20_range,
                  prior5_high/prior5_low-1 AS prior5_range,
                  turnover_fraction/nullif(prior5_turnover,0) AS turnover_expansion,
                  prior5_turnover/nullif(prior20_turnover,0) AS dryup_ratio,
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
                  AND prior20_high/prior20_low-1<=0.30 AND prior_ret20<=0.30
                  AND prior5_turnover<=prior20_turnover
                  AND prior5_high/prior5_low-1<=0.15
                  AND turnover_fraction>=1.50*prior5_turnover
              )
              SELECT *,'BCT-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,decision_at AS feature_latest_timestamp,
                prior_ret20 AS prior_runup,coord_close/prior20_high-1 AS pre_drawdown,
                prior20_high,prior20_high AS platform_high,
                TRUE AS pass_R1_CONTRACTION15_DEMAND15,
                prior5_range<=0.10 AS pass_R2_CONTRACTION10_DEMAND15,
                turnover_expansion>=2.00 AS pass_R3_CONTRACTION15_DEMAND20,
                dryup_ratio<=0.70 AS pass_R4_DEEP_DRYUP_CONTRACTION15
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
    sample.insert(0, "chart_id", [f"BULL-CONTRACT-{i:03d}" for i in range(1, 41)])
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
        "runner_sha256": v1.sha256(Path(v6.__file__)),
        "v7_runner_sha256": v1.sha256(Path(__file__)),
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


def verify_own_freeze() -> None:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT),
        "spec_sha256": v1.sha256(SPEC),
        "v7_runner_sha256": v1.sha256(Path(__file__)),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {
        key: [freeze.get(key), value] for key, value in expected.items() if freeze.get(key) != value
    }
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")


def run_stage_b() -> dict[str, Any]:
    verify_own_freeze()
    names = (
        "EXPERIMENT",
        "CONTRACT",
        "SPEC",
        "FREEZE",
        "RESULT",
        "REPORT",
        "CANDIDATES",
        "BLIND_PDF",
        "OUTCOMES",
        "ACCEPTED",
        "SKIPPED",
        "NAV",
        "RULES",
        "PROFILES",
    )
    values = {name: globals()[name] for name in names}
    old = {name: getattr(v6, name) for name in names}
    try:
        for name, value in values.items():
            setattr(v6, name, value)
        result = v6.run_stage_b()
    finally:
        for name, value in old.items():
            setattr(v6, name, value)
    passed = all(result.get("gate", {}).values())
    result["experiment"] = EXPERIMENT
    result["verdict"] = (
        "STRONG_BULL_LEADER_CONTRACTION_BREAKOUT_EDGE"
        if passed
        else "STRONG_BULL_LEADER_CONTRACTION_BREAKOUT_FAILS_TARGET"
    )
    v1.write_json(RESULT, result)
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
