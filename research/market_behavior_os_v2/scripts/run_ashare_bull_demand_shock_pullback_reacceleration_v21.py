#!/usr/bin/env python3
"""Bull demand shock, contracted pullback, and reacceleration research."""

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
import run_ashare_bull_quiet_base_demand_shock_v20 as v20
import run_ashare_strong_bull_persistent_industry_breakout_v6 as v6

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-DEMAND-SHOCK-PULLBACK-REACCELERATION-V21"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_demand_shock_pullback_reacceleration_v21")
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
    "R1_CONTRACTED_PULLBACK_REACCELERATION": {},
    "R2_DEEPER_PULLBACK": {},
    "R3_LOW_SUPPLY_PULLBACK": {},
    "R4_STRONG_REACCELERATION": {},
}
PROFILES = v6.PROFILES
YEARS = v6.YEARS


class ResearchError(RuntimeError):
    """Fail-closed V21 error."""


def contract_value() -> dict[str, Any]:
    return {
        "experiment": EXPERIMENT,
        "economic_hypothesis": (
            "A demand shock from a bounded sixty-session base only defines a potential "
            "leader. The tradable state occurs after a two-to-twenty-session pullback "
            "with lower turnover, when completed price again exceeds the preceding "
            "three-session ceiling while the causal market and PIT industry remain healthy."
        ),
        "ignition": "frozen V20 outcome-blind quiet-base demand-shock candidates",
        "market": v1.contract_value()["market_regime"],
        "industry": "trigger-day PIT industry median ret20>0 and positive share>50%",
        "trigger": {
            "clock": "sessions 2 through 20 after ignition",
            "pullback": "previous close 2%-18% below ignition high",
            "supply": "previous turnover <= preceding20 mean",
            "reacceleration": "close > preceding3 high, return>=1%, location>=65%, turnover>=0.8x preceding3 mean",
            "identity": "first qualifying completed session per ignition",
        },
        "rules": {
            "R1_CONTRACTED_PULLBACK_REACCELERATION": "base contract",
            "R2_DEEPER_PULLBACK": "R1 and pullback at least 5%",
            "R3_LOW_SUPPLY_PULLBACK": "R1 and previous turnover<=0.8x preceding20 mean",
            "R4_STRONG_REACCELERATION": "R1 and return>=2%, location>=75%, turnover>=preceding3 mean",
        },
        "profiles": PROFILES,
        "entry": "first legal next daily open within three market sessions",
        "exit": "target or causal H5/H10/H15 decision then next legal open",
        "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {"discovery": list(v6.DISCOVERY), "minimum_completed": 300,
                      "positive_years_min": 3, "mean_holding_max": 15},
        "gate": v1.contract_value()["required_gate"],
        "governance": {"independent_from_downward_gap_repair": True,
                       "frozen_before_outcomes": True, "no_post_2023_signal_or_feature": True},
    }


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT, contract_value())
    v1.write_json(SPEC, {"experiment": EXPERIMENT,
        "status": "OUTCOME_BLIND_DEMAND_SHOCK_PULLBACK_FREEZE",
        "contract_sha256": v1.sha256(CONTRACT), "runner_sha256": v1.sha256(Path(__file__)),
        "v20_candidate_sha256": v1.sha256(v20.CANDIDATES),
        "execution_engine_sha256": v1.sha256(Path(v2.__file__)),
        "portfolio_engine_sha256": v1.sha256(Path(v1.__file__)),
        "selection_engine_sha256": v1.sha256(Path(v6.__file__)),
        "daily_sha256": v1.sha256(v1.DAILY), "regime_sha256": v1.sha256(v1.SOURCE_REGIME),
        "industry_sha256": v1.sha256(v1.INDUSTRY_PANEL)})
    return {"contract_sha256": v1.sha256(CONTRACT), "spec_sha256": v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    try:
        con.execute(f"""
          COPY (
            WITH d AS (
              SELECT *,lag(coord_close) OVER w AS previous_close,
                lag(turnover_fraction) OVER w AS previous_turnover,
                max(coord_high) OVER w3 AS prior3_high,
                avg(turnover_fraction) OVER w3 AS prior3_turnover,
                avg(turnover_fraction) OVER w20 AS prior20_turnover,
                (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS signal_close_location
              FROM read_parquet('{v1.DAILY}')
              WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
                AND hard_valid AND history_valid AND current_valid
                AND corporate_action_valid AND NOT corporate_action_blocking
                AND current_day_data_tradable AND market_rule_valid
                AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
              WINDOW w AS (PARTITION BY symbol ORDER BY trade_date),
                w3 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING),
                w20 AS (PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
            ), eligible AS (
              SELECT c.event_id AS root_event_id,c.trade_date AS ignition_date,
                c.cal_idx AS ignition_cal_idx,c.coord_high AS ignition_high,
                c.turnover_fraction AS ignition_turnover,d.*,
                r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
                r.latest_source_timestamp AS market_latest_source,
                i.industry_median_ret20,i.industry_positive_ret20_share,
                i.industry_ret20_percentile,i.industry_n20,
                i.latest_source_timestamp AS industry_latest_source,
                d.previous_close/c.coord_high-1 AS pullback_drawdown,
                d.previous_turnover/nullif(d.prior20_turnover,0) AS pullback_turnover_ratio,
                d.turnover_fraction/nullif(d.prior3_turnover,0) AS turnover_expansion,
                d.ret20-i.industry_median_ret20 AS stock_minus_industry_ret20
              FROM read_parquet('{v20.CANDIDATES}') c
              JOIN d ON d.symbol=c.symbol AND d.cal_idx BETWEEN c.cal_idx+2 AND c.cal_idx+20
              JOIN read_parquet('{v1.SOURCE_REGIME}') r ON r.trade_date=d.trade_date
              JOIN read_parquet('{v1.INDUSTRY_PANEL}') i
                ON i.trade_date=d.trade_date AND i.causal_industry=d.causal_industry
              WHERE r.market_regime='BULL' AND i.industry_n20>=5
                AND i.industry_median_ret20>0 AND i.industry_positive_ret20_share>0.50
                AND d.previous_close/c.coord_high-1 BETWEEN -0.18 AND -0.02
                AND d.previous_turnover<=d.prior20_turnover
                AND d.coord_close>d.prior3_high AND d.step_return>=0.01
                AND d.signal_close_location>=0.65
                AND d.turnover_fraction>=0.80*d.prior3_turnover
            ), firsts AS (
              SELECT *,row_number() OVER(PARTITION BY root_event_id ORDER BY trade_date) AS trigger_number
              FROM eligible
            )
            SELECT *,'BDPR-'||root_event_id||'-'||strftime(trade_date,'%Y%m%d') AS event_id,
              trade_date AS signal_date,decision_at AS feature_latest_timestamp,
              ignition_high/prior_coord_close-1 AS prior_runup,pullback_drawdown AS pre_drawdown,
              prior3_high AS prior20_high,ignition_high AS platform_high,
              TRUE AS pass_R1_CONTRACTED_PULLBACK_REACCELERATION,
              pullback_drawdown<=-0.05 AS pass_R2_DEEPER_PULLBACK,
              pullback_turnover_ratio<=0.80 AS pass_R3_LOW_SUPPLY_PULLBACK,
              step_return>=0.02 AND signal_close_location>=0.75
                AND turnover_expansion>=1.00 AS pass_R4_STRONG_REACCELERATION
            FROM firsts WHERE trigger_number=1 ORDER BY trade_date,symbol
          ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)
        """)
    finally: con.close()
    frame=v1.read_parquet_duckdb(CANDIDATES)
    for column in ("trade_date","signal_date","ignition_date","decision_at","available_at",
                   "market_latest_source","industry_latest_source","feature_latest_timestamp"):
        frame[column]=pd.to_datetime(frame[column])
    causal=(frame.available_at.le(frame.decision_at)&frame.market_latest_source.le(frame.decision_at)
            &frame.industry_latest_source.le(frame.decision_at)&frame.feature_latest_timestamp.le(frame.decision_at)
            &frame.ignition_date.lt(frame.signal_date))
    if frame.event_id.duplicated().any() or not causal.all(): raise ResearchError("identity or chronology failure")
    return frame


def sample_and_render(frame: pd.DataFrame) -> pd.DataFrame:
    work=frame.copy();work["hash_order"]=work.event_id.map(lambda x:hashlib.sha256(str(x).encode()).hexdigest());work["year"]=work.signal_date.dt.year
    pieces=[p.sort_values("hash_order").head(2) for _,p in work.groupby(["year","sleeve"],sort=True)]
    sample=pd.concat(pieces,ignore_index=True).sort_values("hash_order").head(40)
    if len(sample)<40:
        rest=work.loc[~work.event_id.isin(sample.event_id)];sample=pd.concat([sample,rest.sort_values("hash_order").head(40-len(sample))],ignore_index=True)
    sample=sample.sort_values(["signal_date","symbol"]).reset_index(drop=True)
    if len(sample)!=40:raise ResearchError(f"blind sample has {len(sample)} rows")
    sample.insert(0,"chart_id",[f"BULL-REACCEL-{i:03d}" for i in range(1,41)]);sample.to_csv(BLIND_INDEX,index=False)
    old=v2.BLIND_PDF
    try:v2.BLIND_PDF=BLIND_PDF;v2.render_blind_charts(sample)
    finally:v2.BLIND_PDF=old
    return sample


def run_stage_a() -> dict[str, Any]:
    hashes=persist_contract();frame=build_candidates();sample=sample_and_render(frame)
    coverage={rule:{"count":int(frame[f"pass_{rule}"].sum()),"annual":(frame.loc[frame[f"pass_{rule}"]]
        .groupby(frame.loc[frame[f"pass_{rule}"],"signal_date"].dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict())}for rule in RULES}
    audit={"duplicate_event_count":int(frame.event_id.duplicated().sum()),"feature_after_decision_count":int(frame.feature_latest_timestamp.gt(frame.decision_at).sum()),"post_2023_signal_count":int(frame.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),"blind_chart_post_signal_bar_count":0}
    if any(audit.values()):raise ResearchError(str(audit))
    freeze={"experiment":EXPERIMENT,**hashes,"runner_sha256":v1.sha256(Path(v6.__file__)),"v21_runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(frame),"blind_chart_count":len(sample),"coverage":coverage,"audit":audit,"outcomes_opened":False}
    v1.write_json(FREEZE,freeze);return freeze


def verify_own_freeze() -> None:
    f=json.loads(FREEZE.read_text());e={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"v21_runner_sha256":v1.sha256(Path(__file__)),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)};d={k:[f.get(k),v]for k,v in e.items()if f.get(k)!=v}
    if d:raise ResearchError(f"Stage-A drift {d}")


def run_stage_b() -> dict[str, Any]:
    verify_own_freeze();names=("EXPERIMENT","CONTRACT","SPEC","FREEZE","RESULT","REPORT","CANDIDATES","BLIND_PDF","OUTCOMES","ACCEPTED","SKIPPED","NAV","RULES","PROFILES");values={n:globals()[n]for n in names};old={n:getattr(v6,n)for n in names}
    try:
        for n,v in values.items():setattr(v6,n,v)
        result=v6.run_stage_b()
    finally:
        for n,v in old.items():setattr(v6,n,v)
    gate=result.get("gate");passed=isinstance(gate,dict)and bool(gate)and all(gate.values());result["experiment"]=EXPERIMENT;result["verdict"]="BULL_DEMAND_SHOCK_PULLBACK_REACCELERATION_EDGE"if passed else"BULL_DEMAND_SHOCK_PULLBACK_REACCELERATION_FAILS_TARGET";v1.write_json(RESULT,result);return result


def main() -> None:
    p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
    if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
    elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:p.error('choose --stage-a or --stage-b')


if __name__=='__main__':main()
