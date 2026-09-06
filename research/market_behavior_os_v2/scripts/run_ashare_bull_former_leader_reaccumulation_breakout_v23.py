#!/usr/bin/env python3
"""Bull former-leader reaccumulation breakout research."""

from __future__ import annotations

import argparse,json
from pathlib import Path
from typing import Any
import duckdb,pandas as pd
import run_ashare_bull_leader_pullback_reacceleration_v2 as v2
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1
import run_ashare_bull_quiet_base_demand_shock_v20 as base
import run_ashare_strong_bull_persistent_industry_breakout_v6 as v6

ROOT=Path(__file__).resolve().parents[3];OS=ROOT/'research/market_behavior_os_v2'
EXPERIMENT='ASHARE-BULL-FORMER-LEADER-REACCUMULATION-BREAKOUT-V23'
EXT=Path('/Volumes/quant/CY_quant_research/ashare_bull_former_leader_reaccumulation_breakout_v23')
CONTRACT=OS/f'experiments/{EXPERIMENT}_contract.json';SPEC=OS/f'experiments/{EXPERIMENT}_spec.json';FREEZE=OS/f'artifacts/{EXPERIMENT}_stage_a_freeze.json';RESULT=OS/f'artifacts/{EXPERIMENT}_result.json';REPORT=OS/f'reports/{EXPERIMENT}_report.md'
RAW_CANDIDATES=EXT/'stage_a/high_recall_candidates.parquet';CANDIDATES=EXT/'stage_a/candidates.parquet';BLIND_INDEX=EXT/'stage_a/blind_index.csv';BLIND_PDF=ROOT/f'output/pdf/{EXPERIMENT}_40_BLIND_CHARTS.pdf';OUTCOMES=EXT/'stage_b/outcomes.parquet';ACCEPTED=EXT/'stage_b/portfolio_accepted.parquet';SKIPPED=EXT/'stage_b/portfolio_skipped.parquet';NAV=EXT/'stage_b/portfolio_nav.parquet'
RULES={'R1_REACCUMULATION_BREAKOUT':{},'R2_TIGHT_REACCUMULATION':{},'R3_LOW_SUPPLY_BASE':{},'R4_STRONG_DEMAND_BREAKOUT':{}}
PROFILES=v6.PROFILES;YEARS=v6.YEARS
class ResearchError(RuntimeError):pass

def contract_value()->dict[str,Any]:
 return {'experiment':EXPERIMENT,'economic_hypothesis':('In a causally known broad BULL market and healthy PIT industry, a former leader with at least 30% prior 120-session appreciation or two prior limit-up closes may reset inventory through a 15%-35% drawdown. A ten-session narrow, lower-turnover base followed by the first high-location, expanded-turnover close above its ceiling marks reaccumulation and a potential second markup phase.'),'market':v1.contract_value()['market_regime'],'industry':'PIT median ret20>0 and positive share>50%','former_leader':'prior completed ret120>=30% or at least two limit-up closes in prior120','reset':'previous close 15%-35% below prior60 high','base':'prior10 range<=15% and turnover<=prior60 average','trigger':'first close above prior10 high, return>=3%, turnover>=1.5x prior10, location>=75%','rules':{'R1_REACCUMULATION_BREAKOUT':'base contract','R2_TIGHT_REACCUMULATION':'R1 and prior10 range<=10%','R3_LOW_SUPPLY_BASE':'R1 and prior10/prior60 turnover<=70%','R4_STRONG_DEMAND_BREAKOUT':'R1 and return>=5%'},'profiles':PROFILES,'entry':'first legal next daily open within three market sessions','exit':'target or causal H5/H10/H15 decision then next legal open','cost':.004,'portfolio':v1.contract_value()['portfolio'],'selection':{'discovery':list(v6.DISCOVERY),'minimum_completed':300,'positive_years_min':3,'mean_holding_max':15},'gate':v1.contract_value()['required_gate'],'governance':{'independent_from_downward_gap_repair':True,'frozen_before_outcomes':True,'no_post_2023_signal_or_feature':True}}

def persist_contract()->dict[str,str]:
 v1.write_json(CONTRACT,contract_value());v1.write_json(SPEC,{'experiment':EXPERIMENT,'status':'OUTCOME_BLIND_FORMER_LEADER_REACCUMULATION_FREEZE','contract_sha256':v1.sha256(CONTRACT),'runner_sha256':v1.sha256(Path(__file__)),'execution_engine_sha256':v1.sha256(Path(v2.__file__)),'portfolio_engine_sha256':v1.sha256(Path(v1.__file__)),'selection_engine_sha256':v1.sha256(Path(v6.__file__)),'daily_sha256':v1.sha256(v1.DAILY),'regime_sha256':v1.sha256(v1.SOURCE_REGIME),'industry_sha256':v1.sha256(v1.INDUSTRY_PANEL)});return{'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC)}

def build_candidates()->pd.DataFrame:
 CANDIDATES.parent.mkdir(parents=True,exist_ok=True);con=duckdb.connect()
 try:con.execute(f"""COPY(WITH d0 AS(SELECT *,lag(ret120)OVER w AS prior_ret120,max(coord_high)OVER w60 AS prior60_high,min(coord_low)OVER w10 AS prior10_low,max(coord_high)OVER w10 AS prior10_high,avg(turnover_fraction)OVER w10 AS prior10_turnover,avg(turnover_fraction)OVER w60 AS prior60_turnover,count(*)OVER w120 AS history_n120 FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE'2013-01-01'AND DATE'2023-12-31'AND hard_valid AND history_valid AND current_valid AND corporate_action_valid AND NOT corporate_action_blocking AND current_day_data_tradable AND market_rule_valid AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),w10 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING),w60 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 60 PRECEDING AND 1 PRECEDING),w120 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 120 PRECEDING AND 1 PRECEDING)),d1 AS(SELECT *,lag(prior10_high)OVER w AS previous_prior10_high,lag(coord_close)OVER w AS previous_close,(coord_close-coord_low)/nullif(coord_high-coord_low,0)AS signal_close_location FROM d0 WINDOW w AS(PARTITION BY symbol ORDER BY trade_date)),x AS(SELECT d1.*,r.market_regime,r.market_median_ret20,r.market_positive_ret20_share,r.latest_source_timestamp AS market_latest_source,i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_ret20_percentile,i.industry_n20,i.latest_source_timestamp AS industry_latest_source,prior10_high/prior10_low-1 AS prior10_range,prior10_turnover/nullif(prior60_turnover,0)AS base_turnover_ratio,turnover_fraction/nullif(prior10_turnover,0)AS turnover_expansion,previous_close/prior60_high-1 AS drawdown_from_prior60_high,ret20-i.industry_median_ret20 AS stock_minus_industry_ret20 FROM d1 JOIN read_parquet('{v1.SOURCE_REGIME}')r USING(trade_date)JOIN read_parquet('{v1.INDUSTRY_PANEL}')i USING(trade_date,causal_industry)WHERE trade_date>=DATE'2014-01-01'AND history_n120=120 AND r.market_regime='BULL'AND i.industry_n20>=5 AND i.industry_median_ret20>0 AND i.industry_positive_ret20_share>.50 AND(prior_ret120>=.30 OR limit_up_days120>=2)AND previous_close/prior60_high-1 BETWEEN -.35 AND -.15 AND prior10_high/prior10_low-1<=.15 AND prior10_turnover<=prior60_turnover AND coord_close>prior10_high AND previous_close<=previous_prior10_high AND step_return>=.03 AND turnover_fraction>=1.5*prior10_turnover AND signal_close_location>=.75)SELECT *,'BFLR-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,trade_date AS signal_date,decision_at AS feature_latest_timestamp,prior_ret120 AS prior_runup,drawdown_from_prior60_high AS pre_drawdown,prior10_high AS prior20_high,prior10_high AS platform_high,TRUE AS pass_R1_REACCUMULATION_BREAKOUT,prior10_range<=.10 AS pass_R2_TIGHT_REACCUMULATION,base_turnover_ratio<=.70 AS pass_R3_LOW_SUPPLY_BASE,step_return>=.05 AS pass_R4_STRONG_DEMAND_BREAKOUT FROM x ORDER BY trade_date,symbol)TO'{RAW_CANDIDATES}'(FORMAT PARQUET,COMPRESSION ZSTD)""")
 finally:con.close()
 raw=v1.read_parquet_duckdb(RAW_CANDIDATES);frame=base._cooldown(raw);v1.write_parquet(frame,CANDIDATES)
 for c in('trade_date','signal_date','decision_at','available_at','market_latest_source','industry_latest_source','feature_latest_timestamp'):frame[c]=pd.to_datetime(frame[c])
 causal=frame.available_at.le(frame.decision_at)&frame.market_latest_source.le(frame.decision_at)&frame.industry_latest_source.le(frame.decision_at)&frame.feature_latest_timestamp.le(frame.decision_at)
 if frame.event_id.duplicated().any()or not causal.all():raise ResearchError('identity or chronology failure')
 return frame

def render(f:pd.DataFrame)->pd.DataFrame:
 old=(base.BLIND_INDEX,base.BLIND_PDF)
 try:base.BLIND_INDEX,base.BLIND_PDF=BLIND_INDEX,BLIND_PDF;return base.sample_and_render(f)
 finally:base.BLIND_INDEX,base.BLIND_PDF=old

def run_stage_a()->dict[str,Any]:
 h=persist_contract();f=build_candidates();s=render(f);coverage={r:{'count':int(f[f'pass_{r}'].sum()),'annual':f.loc[f[f'pass_{r}']].groupby(f.loc[f[f'pass_{r}'],'signal_date'].dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict()}for r in RULES};audit={'duplicate_event_count':int(f.event_id.duplicated().sum()),'feature_after_decision_count':int(f.feature_latest_timestamp.gt(f.decision_at).sum()),'post_2023_signal_count':int(f.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),'blind_chart_post_signal_bar_count':0};
 if any(audit.values()):raise ResearchError(str(audit))
 z={'experiment':EXPERIMENT,**h,'runner_sha256':v1.sha256(Path(v6.__file__)),'v23_runner_sha256':v1.sha256(Path(__file__)),'raw_candidate_sha256':v1.sha256(RAW_CANDIDATES),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF),'candidate_count':len(f),'blind_chart_count':len(s),'coverage':coverage,'audit':audit,'outcomes_opened':False};v1.write_json(FREEZE,z);return z

def verify()->None:
 f=json.loads(FREEZE.read_text());e={'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC),'v23_runner_sha256':v1.sha256(Path(__file__)),'raw_candidate_sha256':v1.sha256(RAW_CANDIDATES),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF)};d={k:[f.get(k),v]for k,v in e.items()if f.get(k)!=v};
 if d:raise ResearchError(f'Stage-A drift {d}')

def run_stage_b()->dict[str,Any]:
 verify();names=('EXPERIMENT','CONTRACT','SPEC','FREEZE','RESULT','REPORT','CANDIDATES','BLIND_PDF','OUTCOMES','ACCEPTED','SKIPPED','NAV','RULES','PROFILES');vals={n:globals()[n]for n in names};old={n:getattr(v6,n)for n in names}
 try:
  for n,v in vals.items():setattr(v6,n,v)
  result=v6.run_stage_b()
 finally:
  for n,v in old.items():setattr(v6,n,v)
 g=result.get('gate');passed=isinstance(g,dict)and bool(g)and all(g.values());result['experiment']=EXPERIMENT;result['verdict']='BULL_FORMER_LEADER_REACCUMULATION_EDGE'if passed else'BULL_FORMER_LEADER_REACCUMULATION_FAILS_TARGET';v1.write_json(RESULT,result);return result

def main()->None:
 p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
 if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
 elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
 else:p.error('choose --stage-a or --stage-b')
if __name__=='__main__':main()
