#!/usr/bin/env python3
"""Bull-market long-base inventory-ceiling breakout research."""

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
EXPERIMENT = "ASHARE-BULL-LONG-BASE-CEILING-BREAKOUT-V16"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_long_base_ceiling_breakout_v16")
CONTRACT = OS / f"experiments/{EXPERIMENT}_contract.json"
SPEC = OS / f"experiments/{EXPERIMENT}_spec.json"
FREEZE = OS / f"artifacts/{EXPERIMENT}_stage_a_freeze.json"
RESULT = OS / f"artifacts/{EXPERIMENT}_result.json"
REPORT = OS / f"reports/{EXPERIMENT}_report.md"
RAW_CANDIDATES = EXT / "stage_a/high_recall_candidates.parquet"
CANDIDATES = EXT / "stage_a/candidates.parquet"
BLIND_INDEX = EXT / "stage_a/blind_index.csv"
BLIND_PDF = ROOT / f"output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf"
OUTCOMES = EXT / "stage_b/outcomes.parquet"
ACCEPTED = EXT / "stage_b/portfolio_accepted.parquet"
SKIPPED = EXT / "stage_b/portfolio_skipped.parquet"
NAV = EXT / "stage_b/portfolio_nav.parquet"

RULES = {
    "R1_LONG_CEILING_BREAKOUT": {},
    "R2_TIGHT_LONG_BASE": {},
    "R3_BOUNDED_120D_INVENTORY": {},
    "R4_HIGH_DEMAND_BREAKOUT": {},
}
PROFILES = v6.PROFILES
YEARS = v6.YEARS


class ResearchError(RuntimeError):
    """Fail-closed V16 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "In a causally known BULL market and healthy industry, a first close above "
            "the completed 120-session high removes the entire recent overhead trading "
            "range. Requiring nested 60/20-session compression, non-expanding recent "
            "turnover, and a high-location volume expansion distinguishes genuine long-"
            "base price discovery from an ordinary short breakout inside old inventory."
        ),
        "market": v1.contract_value()["market_regime"],
        "industry": "same-day median ret20>0 and positive-ret20 share>50%",
        "base": {
            "history": "exactly 120 prior valid completed same-symbol sessions",
            "prior60_range": "<=40%",
            "prior20_range": "<=20%",
            "quiet_turnover": "preceding20 mean<=preceding60 mean",
            "extension": "pre-signal ret20<=15%",
        },
        "trigger": {
            "first_breakout": (
                "close>=preceding120 high and previous close<its then-preceding120 high"
            ),
            "acceptance": "close>=open and close location>=70%",
            "demand": "turnover>=1.5x preceding20 mean",
            "cooldown": "first retained signal per symbol in each causal 30-session window",
        },
        "rules": {
            "R1_LONG_CEILING_BREAKOUT": "base contract",
            "R2_TIGHT_LONG_BASE": "R1 and prior60 range<=30% and prior20 range<=15%",
            "R3_BOUNDED_120D_INVENTORY": "R1 and prior120 range<=60%",
            "R4_HIGH_DEMAND_BREAKOUT": "R1 and turnover expansion>=2.0",
        },
        "profiles": PROFILES,
        "entry": "first legal next daily open within three market sessions",
        "exit": "target or causal H5/H10/H15 decision then next legal open",
        "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {
            "discovery": list(v6.DISCOVERY), "minimum_completed": 300,
            "positive_years_min": 3, "mean_holding_max": 15,
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
    v1.write_json(SPEC, {
        "experiment": EXPERIMENT,
        "status": "OUTCOME_BLIND_LONG_BASE_CEILING_FREEZE",
        "contract_sha256": v1.sha256(CONTRACT),
        "runner_sha256": v1.sha256(Path(__file__)),
        "execution_engine_sha256": v1.sha256(Path(v2.__file__)),
        "portfolio_engine_sha256": v1.sha256(Path(v1.__file__)),
        "selection_engine_sha256": v1.sha256(Path(v6.__file__)),
        "daily_sha256": v1.sha256(v1.DAILY),
        "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
        "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL),
    })
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def _cooldown(frame: pd.DataFrame) -> pd.DataFrame:
    kept: list[int] = []
    for _, part in frame.sort_values(["symbol", "cal_idx"]).groupby("symbol", sort=False):
        last = -(10**9)
        for idx, row in part.iterrows():
            if int(row.cal_idx) > last + 30:
                kept.append(idx)
                last = int(row.cal_idx)
    return frame.loc[kept].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"""
            COPY (
              WITH d0 AS (
                SELECT *,lag(ret20) OVER w AS prior_ret20,
                  max(coord_high) OVER w120 AS prior120_high,
                  min(coord_low) OVER w120 AS prior120_low,
                  max(coord_high) OVER w60 AS prior60_high,
                  min(coord_low) OVER w60 AS prior60_low,
                  max(coord_high) OVER w20 AS prior20_high,
                  min(coord_low) OVER w20 AS prior20_low,
                  avg(turnover_fraction) OVER w20 AS prior20_turnover,
                  avg(turnover_fraction) OVER w60 AS prior60_turnover,
                  count(*) OVER w120 AS history_n120
                FROM read_parquet('{v1.DAILY}')
                WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                  AND hard_valid AND history_valid AND current_valid
                  AND corporate_action_valid AND NOT corporate_action_blocking
                  AND current_day_data_tradable AND market_rule_valid
                  AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
                WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
                  w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING),
                  w60 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),
                  w120 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING)
              ), d1 AS (
                SELECT *,lag(coord_close) OVER w AS previous_close,
                  lag(prior120_high) OVER w AS previous_prior120_high,
                  (coord_close-coord_low)/nullif(coord_high-coord_low,0)
                    AS signal_close_location
                FROM d0 WINDOW w AS (PARTITION BY symbol ORDER BY trade_date)
              ), x AS (
                SELECT d1.*,r.market_regime,r.market_median_ret20,
                  r.market_positive_ret20_share,r.latest_source_timestamp AS market_latest_source,
                  i.industry_median_ret20,i.industry_positive_ret20_share,
                  i.industry_ret20_percentile,i.industry_n20,
                  i.latest_source_timestamp AS industry_latest_source,
                  prior120_high/prior120_low-1 AS prior120_range,
                  prior60_high/prior60_low-1 AS prior60_range,
                  prior20_high/prior20_low-1 AS prior20_range,
                  prior20_turnover/nullif(prior60_turnover,0) AS quiet_turnover_ratio,
                  turnover_fraction/nullif(prior20_turnover,0) AS turnover_expansion,
                  ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
                FROM d1 JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
                JOIN read_parquet('{v1.INDUSTRY_PANEL}') i USING(trade_date,causal_industry)
                WHERE trade_date>=DATE '2014-01-01' AND history_n120=120
                  AND r.market_regime='BULL'
                  AND i.industry_n20>=5 AND i.industry_median_ret20>0
                  AND i.industry_positive_ret20_share>0.50
                  AND coord_close>=prior120_high
                  AND previous_close<previous_prior120_high
                  AND signal_close_location>=0.70 AND coord_close>=coord_open
                  AND turnover_fraction>=1.50*prior20_turnover
                  AND prior_ret20<=0.15
                  AND prior60_high/prior60_low-1<=0.40
                  AND prior20_high/prior20_low-1<=0.20
                  AND prior20_turnover<=prior60_turnover
              )
              SELECT *,'BLBC-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
                trade_date AS signal_date,decision_at AS feature_latest_timestamp,
                prior_ret20 AS prior_runup,coord_close/prior120_high-1 AS pre_drawdown,
                prior120_high AS prior20_high,prior120_high AS platform_high,
                TRUE AS pass_R1_LONG_CEILING_BREAKOUT,
                prior60_range<=0.30 AND prior20_range<=0.15 AS pass_R2_TIGHT_LONG_BASE,
                prior120_range<=0.60 AS pass_R3_BOUNDED_120D_INVENTORY,
                turnover_expansion>=2.00 AS pass_R4_HIGH_DEMAND_BREAKOUT
              FROM x ORDER BY trade_date,symbol
            ) TO '{RAW_CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """)
    finally:
        con.close()
    raw = v1.read_parquet_duckdb(RAW_CANDIDATES)
    frame = _cooldown(raw)
    v1.write_parquet(frame, CANDIDATES)
    for column in (
        "trade_date", "signal_date", "decision_at", "available_at",
        "market_latest_source", "industry_latest_source", "feature_latest_timestamp",
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
    work["hash_order"] = work.event_id.map(lambda value: hashlib.sha256(str(value).encode()).hexdigest())
    work["year"] = work.signal_date.dt.year
    pieces = [part.sort_values("hash_order").head(2)
              for _, part in work.groupby(["year", "sleeve"], sort=True)]
    sample = pd.concat(pieces, ignore_index=True).sort_values("hash_order").head(40)
    if len(sample) < 40:
        rest = work.loc[~work.event_id.isin(sample.event_id)]
        sample = pd.concat([sample, rest.sort_values("hash_order").head(40-len(sample))], ignore_index=True)
    sample = sample.sort_values(["signal_date", "symbol"]).reset_index(drop=True)
    if len(sample) != 40:
        raise ResearchError(f"blind sample has {len(sample)} rows")
    sample.insert(0, "chart_id", [f"BULL-LONGBASE-{i:03d}" for i in range(1, 41)])
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
            "annual": (frame.loc[frame[f"pass_{rule}"]]
                .groupby(frame.loc[frame[f"pass_{rule}"], "signal_date"].dt.year)
                .size().reindex(YEARS, fill_value=0).astype(int).to_dict()),
        } for rule in RULES
    }
    audit = {
        "duplicate_event_count": int(frame.event_id.duplicated().sum()),
        "feature_after_decision_count": int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),
        "post_2023_signal_count": int(frame.signal_date.gt(pd.Timestamp("2023-12-31")).sum()),
        "blind_chart_post_signal_bar_count": 0,
    }
    if any(audit.values()):
        raise ResearchError(str(audit))
    freeze = {
        "experiment": EXPERIMENT, **hashes,
        "runner_sha256": v1.sha256(Path(v6.__file__)),
        "v16_runner_sha256": v1.sha256(Path(__file__)),
        "raw_candidate_sha256": v1.sha256(RAW_CANDIDATES),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
        "candidate_count": len(frame), "blind_chart_count": len(sample),
        "coverage": coverage, "audit": audit, "outcomes_opened": False,
    }
    v1.write_json(FREEZE, freeze)
    return freeze


def verify_own_freeze() -> None:
    freeze = json.loads(FREEZE.read_text())
    expected = {
        "contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC),
        "v16_runner_sha256": v1.sha256(Path(__file__)),
        "raw_candidate_sha256": v1.sha256(RAW_CANDIDATES),
        "candidate_sha256": v1.sha256(CANDIDATES),
        "blind_pdf_sha256": v1.sha256(BLIND_PDF),
    }
    drift = {key: [freeze.get(key), value] for key, value in expected.items()
             if freeze.get(key) != value}
    if drift:
        raise ResearchError(f"Stage-A drift {drift}")


def run_stage_b() -> dict[str, Any]:
    verify_own_freeze()
    names = (
        "EXPERIMENT", "CONTRACT", "SPEC", "FREEZE", "RESULT", "REPORT",
        "CANDIDATES", "BLIND_PDF", "OUTCOMES", "ACCEPTED", "SKIPPED", "NAV",
        "RULES", "PROFILES",
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
    gate = result.get("gate")
    passed = isinstance(gate, dict) and bool(gate) and all(gate.values())
    result["experiment"] = EXPERIMENT
    result["verdict"] = "BULL_LONG_BASE_CEILING_BREAKOUT_EDGE" if passed else "BULL_LONG_BASE_CEILING_BREAKOUT_FAILS_TARGET"
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
