#!/usr/bin/env python3
"""Bull-market industry pullback and breadth-repair research."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1
import run_ashare_bull_quiet_base_demand_shock_v20 as base
import run_ashare_strong_bull_persistent_industry_breakout_v6 as v6

ROOT = Path(__file__).resolve().parents[3]
OS = ROOT / "research/market_behavior_os_v2"
EXPERIMENT = "ASHARE-BULL-INDUSTRY-PULLBACK-BREADTH-REPAIR-V22"
EXT = Path("/Volumes/quant/CY_quant_research/ashare_bull_industry_pullback_breadth_repair_v22")
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
RULES = {"R1_INDUSTRY_BREADTH_REPAIR": {}, "R2_DEEP_INDUSTRY_PULLBACK": {},
         "R3_LEADING_INDUSTRY_REPAIR": {}, "R4_STRONG_STOCK_CARRIER": {}}
PROFILES = v6.PROFILES
YEARS = v6.YEARS


class ResearchError(RuntimeError):
    """Fail-closed V22 error."""


def contract_value() -> dict[str, Any]:
    return {"experiment": EXPERIMENT,
        "economic_hypothesis": ("During a causally known broad BULL market, an industry "
            "whose twenty-session trend remains positive but whose five-session median "
            "return fell below -3% can offer a rotation entry when at least 65% of its "
            "members turn positive and its daily median return exceeds 1%. Stocks with "
            "intact medium-term strength and demand confirmation carry that repair."),
        "market": v1.contract_value()["market_regime"],
        "industry": {"trend": "PIT ret20 percentile>=60% and median ret20>0",
            "pullback": "previous completed industry median five-session return<=-3%",
            "repair": "current median daily return>=1%, positive share>=65%, median5 improving"},
        "stock": "prior ret20>=0, prior ret60>=10%, daily return>=2%, close location>=70%, turnover>=prior20 mean",
        "rules": {"R1_INDUSTRY_BREADTH_REPAIR": "base contract",
            "R2_DEEP_INDUSTRY_PULLBACK": "R1 and prior industry median5<=-5%",
            "R3_LEADING_INDUSTRY_REPAIR": "R1 and PIT industry ret20 percentile>=70%",
            "R4_STRONG_STOCK_CARRIER": "R1 and stock return>=3%, location>=80%"},
        "profiles": PROFILES, "entry": "first legal next daily open within three market sessions",
        "exit": "target or causal H5/H10/H15 decision then next legal open", "cost": 0.004,
        "portfolio": v1.contract_value()["portfolio"],
        "selection": {"discovery": list(v6.DISCOVERY), "minimum_completed": 300,
            "positive_years_min": 3, "mean_holding_max": 15},
        "gate": v1.contract_value()["required_gate"],
        "governance": {"independent_from_downward_gap_repair": True,
            "frozen_before_outcomes": True, "no_post_2023_signal_or_feature": True}}


def persist_contract() -> dict[str, str]:
    v1.write_json(CONTRACT,contract_value())
    v1.write_json(SPEC,{"experiment":EXPERIMENT,"status":"OUTCOME_BLIND_INDUSTRY_REPAIR_FREEZE",
        "contract_sha256":v1.sha256(CONTRACT),"runner_sha256":v1.sha256(Path(__file__)),
        "execution_engine_sha256":v1.sha256(Path(v2.__file__)),"portfolio_engine_sha256":v1.sha256(Path(v1.__file__)),
        "selection_engine_sha256":v1.sha256(Path(v6.__file__)),"daily_sha256":v1.sha256(v1.DAILY),
        "regime_sha256":v1.sha256(v1.SOURCE_REGIME),"industry_sha256":v1.sha256(v1.INDUSTRY_PANEL)})
    return {"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC)}


def build_candidates() -> pd.DataFrame:
    CANDIDATES.parent.mkdir(parents=True,exist_ok=True);con=duckdb.connect()
    try:
        con.execute(f"""COPY(
          WITH d AS (
            SELECT *,coord_close/lag(coord_close,5) OVER w-1 AS return5,
              lag(ret20) OVER w AS prior_ret20,lag(ret60) OVER w AS prior_ret60,
              avg(turnover_fraction) OVER w20 AS prior20_turnover,
              max(coord_high) OVER w20 AS prior20_high,count(*) OVER w20 AS history_n20,
              (coord_close-coord_low)/nullif(coord_high-coord_low,0) AS signal_close_location
            FROM read_parquet('{v1.DAILY}')
            WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31'
              AND hard_valid AND history_valid AND current_valid AND corporate_action_valid
              AND NOT corporate_action_blocking AND current_day_data_tradable AND market_rule_valid
              AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL
            WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),
              w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)
          ), i0 AS (
            SELECT trade_date,causal_industry,count(*) AS industry_member_count,
              median(step_return) AS industry_daily_median_return,
              avg((step_return>0)::INT) AS industry_daily_positive_share,
              median(return5) AS industry_median_return5,max(decision_at) AS industry_state_latest
            FROM d GROUP BY trade_date,causal_industry HAVING count(*)>=5
          ), i1 AS (
            SELECT *,lag(industry_median_return5) OVER(PARTITION BY causal_industry ORDER BY trade_date)
              AS previous_industry_median_return5 FROM i0
          ), x AS (
            SELECT d.*,i1.*,ip.industry_median_ret20,ip.industry_positive_ret20_share,
              ip.industry_ret20_percentile,ip.industry_n20,
              ip.latest_source_timestamp AS industry_latest_source,
              r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,
              r.latest_source_timestamp AS market_latest_source,
              turnover_fraction/nullif(prior20_turnover,0) AS turnover_expansion,
              ret20-ip.industry_median_ret20 AS stock_minus_industry_ret20
            FROM d JOIN i1 USING(trade_date,causal_industry)
            JOIN read_parquet('{v1.INDUSTRY_PANEL}') ip USING(trade_date,causal_industry)
            JOIN read_parquet('{v1.SOURCE_REGIME}') r USING(trade_date)
            WHERE trade_date>=DATE '2014-01-01' AND history_n20=20 AND r.market_regime='BULL'
              AND ip.industry_median_ret20>0 AND ip.industry_ret20_percentile>=0.60
              AND previous_industry_median_return5<=-0.03
              AND industry_median_return5>previous_industry_median_return5
              AND industry_daily_median_return>=0.01 AND industry_daily_positive_share>=0.65
              AND prior_ret20>=0 AND prior_ret60>=0.10 AND step_return>=0.02
              AND signal_close_location>=0.70 AND turnover_fraction>=prior20_turnover
          )
          SELECT *,'BIPR-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,
            trade_date AS signal_date,decision_at AS feature_latest_timestamp,
            prior_ret60 AS prior_runup,previous_industry_median_return5 AS pre_drawdown,
            prior20_high,prior20_high AS platform_high,
            TRUE AS pass_R1_INDUSTRY_BREADTH_REPAIR,
            previous_industry_median_return5<=-0.05 AS pass_R2_DEEP_INDUSTRY_PULLBACK,
            industry_ret20_percentile>=0.70 AS pass_R3_LEADING_INDUSTRY_REPAIR,
            step_return>=0.03 AND signal_close_location>=0.80 AS pass_R4_STRONG_STOCK_CARRIER
          FROM x ORDER BY trade_date,symbol
        )TO '{RAW_CANDIDATES}'(FORMAT PARQUET,COMPRESSION ZSTD)""")
    finally:con.close()
    raw=v1.read_parquet_duckdb(RAW_CANDIDATES);frame=base._cooldown(raw);v1.write_parquet(frame,CANDIDATES)
    for c in ("trade_date","signal_date","decision_at","available_at","industry_state_latest",
              "market_latest_source","industry_latest_source","feature_latest_timestamp"):frame[c]=pd.to_datetime(frame[c])
    causal=(frame.available_at.le(frame.decision_at)&frame.industry_state_latest.le(frame.decision_at)
            &frame.market_latest_source.le(frame.decision_at)&frame.industry_latest_source.le(frame.decision_at)
            &frame.feature_latest_timestamp.le(frame.decision_at))
    if frame.event_id.duplicated().any()or not causal.all():raise ResearchError("identity or chronology failure")
    return frame


def render(frame: pd.DataFrame) -> pd.DataFrame:
    old=(base.BLIND_INDEX,base.BLIND_PDF)
    try:base.BLIND_INDEX,base.BLIND_PDF=BLIND_INDEX,BLIND_PDF;return base.sample_and_render(frame)
    finally:base.BLIND_INDEX,base.BLIND_PDF=old


def run_stage_a() -> dict[str,Any]:
    h=persist_contract();f=build_candidates();s=render(f);coverage={r:{"count":int(f[f"pass_{r}"].sum()),"annual":(f.loc[f[f"pass_{r}"]].groupby(f.loc[f[f"pass_{r}"],"signal_date"].dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict())}for r in RULES};audit={"duplicate_event_count":int(f.event_id.duplicated().sum()),"feature_after_decision_count":int(f.feature_latest_timestamp.gt(f.decision_at).sum()),"post_2023_signal_count":int(f.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),"blind_chart_post_signal_bar_count":0};
    if any(audit.values()):raise ResearchError(str(audit))
    z={"experiment":EXPERIMENT,**h,"runner_sha256":v1.sha256(Path(v6.__file__)),"v22_runner_sha256":v1.sha256(Path(__file__)),"raw_candidate_sha256":v1.sha256(RAW_CANDIDATES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF),"candidate_count":len(f),"blind_chart_count":len(s),"coverage":coverage,"audit":audit,"outcomes_opened":False};v1.write_json(FREEZE,z);return z


def verify() -> None:
    f=json.loads(FREEZE.read_text());e={"contract_sha256":v1.sha256(CONTRACT),"spec_sha256":v1.sha256(SPEC),"v22_runner_sha256":v1.sha256(Path(__file__)),"raw_candidate_sha256":v1.sha256(RAW_CANDIDATES),"candidate_sha256":v1.sha256(CANDIDATES),"blind_pdf_sha256":v1.sha256(BLIND_PDF)};d={k:[f.get(k),v]for k,v in e.items()if f.get(k)!=v};
    if d:raise ResearchError(f"Stage-A drift {d}")


def run_stage_b() -> dict[str,Any]:
    verify();names=("EXPERIMENT","CONTRACT","SPEC","FREEZE","RESULT","REPORT","CANDIDATES","BLIND_PDF","OUTCOMES","ACCEPTED","SKIPPED","NAV","RULES","PROFILES");vals={n:globals()[n]for n in names};old={n:getattr(v6,n)for n in names}
    try:
        for n,v in vals.items():setattr(v6,n,v)
        result=v6.run_stage_b()
    finally:
        for n,v in old.items():setattr(v6,n,v)
    g=result.get("gate");passed=isinstance(g,dict)and bool(g)and all(g.values());result["experiment"]=EXPERIMENT;result["verdict"]="BULL_INDUSTRY_PULLBACK_BREADTH_REPAIR_EDGE"if passed else"BULL_INDUSTRY_PULLBACK_BREADTH_REPAIR_FAILS_TARGET";v1.write_json(RESULT,result);return result


def main()->None:
    p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
    if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
    elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
    else:p.error('choose --stage-a or --stage-b')


if __name__=='__main__':main()
