#!/usr/bin/env python3
"""Bull correction survivor followed by broad recovery breakout."""

from __future__ import annotations

import argparse, hashlib, json
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

import run_ashare_bull_correction_relative_leader_v35 as v35
import run_ashare_bull_panic_relative_strength_survivor_v34 as v34
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT=Path(__file__).resolve().parents[3];OS=ROOT/'research/market_behavior_os_v2'
EXPERIMENT='ASHARE-BULL-CORRECTION-RECOVERY-BREAKOUT-V36';EXT=Path('/Volumes/quant/CY_quant_research/ashare_bull_correction_recovery_breakout_v36')
CONTRACT=OS/f'experiments/{EXPERIMENT}_contract.json';SPEC=OS/f'experiments/{EXPERIMENT}_spec.json';FREEZE=OS/f'artifacts/{EXPERIMENT}_stage_a_freeze.json';PROFILE_FREEZE=OS/f'artifacts/{EXPERIMENT}_profile_freeze.json';RESULT=OS/f'artifacts/{EXPERIMENT}_result.json'
CANDIDATES=EXT/'stage_a/candidates.parquet';BLIND_INDEX=EXT/'stage_a/blind_index.csv';BLIND_DIR=EXT/'stage_a/blind_charts';BLIND_PDF=ROOT/f'output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf';DEV_OUTCOMES=EXT/'stage_b/development_outcomes.parquet';FORWARD_OUTCOMES=EXT/'stage_b/forward_outcomes.parquet';PROFILE_TABLE=EXT/'stage_b/profile_table.parquet';ACCEPTED=EXT/'stage_b/portfolio_accepted.parquet';SKIPPED=EXT/'stage_b/portfolio_skipped.parquet';NAV=EXT/'stage_b/portfolio_nav.parquet'
YEARS=tuple(range(2014,2024));DEV_YEARS=tuple(range(2014,2021));FORWARD_YEARS=(2021,2022,2023);PROFILES=v34.PROFILES


class ResearchError(RuntimeError):pass


def contract_value()->dict[str,Any]:
 return {'experiment':EXPERIMENT,'stage':'A_OUTCOME_BLIND_CONTRACT','economic_hypothesis':'A broad correction initially makes a relative leader only a liquidity outlet. Demand is actionable only if the source-day low survives and, within 15 completed sessions, market breadth and the stock industry recover together while the stock closes for the first time above the correction-day high. This converts temporary resistance into a completed repricing auction.','four_binding_conditions':{'CAUSAL_SOURCE':'exact frozen V35 broad-correction relative-leader source; source itself is not traded','SOURCE_STRUCTURE_SURVIVES':'no completed close below the correction-day low and no coordinate-lineage change before trigger','MARKET_AND_INDUSTRY_RECOVER':'trigger-day eligible-universe median return >0, positive share >=55%, and PIT-industry median return >0','FIRST_RECOVERY_BREAKOUT':'within 15 sessions, first qualifying completed close above source-day high; trigger return 0% to +8%; close location >=60%'},'decision_clock':'completed recovery-breakout daily close','entry':'first legal daily open after trigger within three market sessions','profiles':PROFILES,'failure_exit':'after T+1, first completed close below frozen source-day high (failed breakout); exit next legal open','cost':.004,'development_gate':{'years':list(DEV_YEARS),'minimum_completed':400,'minimum_positive_years':5,'minimum_mean_net':.03,'maximum_mean_holding_sessions':15},'forward':{'years':list(FORWARD_YEARS),'opened_only_after_profile_freeze':True,'2024_q1_use':'late-2023 execution resolution only'},'portfolio':v1.contract_value()['portfolio'],'outcomes_opened':False}


def persist_contract()->dict[str,str]:
 v1.write_json(CONTRACT,contract_value());v1.write_json(SPEC,{'experiment':EXPERIMENT,'status':'OUTCOME_BLIND_CONTRACT','contract_sha256':v1.sha256(CONTRACT),'v35_candidate_sha256':v1.sha256(v35.CANDIDATES),'sources':{'daily':v1.sha256(v1.DAILY),'regime':v1.sha256(v1.SOURCE_REGIME),'industry':v1.sha256(v1.INDUSTRY_PANEL)},'execution_dependency_sha256':v1.sha256(Path(v1.__file__))});return {'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC)}


def build_candidates()->pd.DataFrame:
 CANDIDATES.parent.mkdir(parents=True,exist_ok=True);con=duckdb.connect();con.execute(f"""COPY (
 WITH eligible AS (SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' AND hard_valid AND history_valid AND current_valid AND corporate_action_valid AND NOT corporate_action_blocking AND current_day_data_tradable AND market_rule_valid AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL AND industry_valid),
 market_day AS (SELECT trade_date,median(step_return) AS recovery_market_median,avg((step_return>0)::INTEGER) AS recovery_market_positive_share FROM eligible GROUP BY trade_date),
 industry_day AS (SELECT trade_date,causal_industry,median(step_return) AS recovery_industry_median,avg((step_return>0)::INTEGER) AS recovery_industry_positive_share,count(*) AS recovery_industry_n FROM eligible GROUP BY trade_date,causal_industry),
 pairs AS (SELECT s.event_id AS source_event_id,s.signal_date AS source_signal_date,s.cal_idx AS source_cal_idx,s.coord_high AS source_high,s.structural_low AS source_low,s.market_step_median AS source_market_median,s.market_positive_step_share AS source_market_positive_share,s.prior_completed_ret20,s.stock_minus_industry_ret20,s.industry_positive_ret20_share,s.turnover_expansion AS source_turnover_expansion,s.invalid_step_cum AS source_lineage,s.symbol,s.sleeve,s.causal_industry,t.*,m.recovery_market_median,m.recovery_market_positive_share,i.recovery_industry_median,i.recovery_industry_positive_share,i.recovery_industry_n,(t.coord_close-greatest(t.coord_open,t.coord_low))/NULLIF(t.coord_high-t.coord_low,0) AS trigger_close_location
   FROM read_parquet('{v35.CANDIDATES}') s JOIN eligible t ON t.symbol=s.symbol AND t.cal_idx-s.cal_idx BETWEEN 1 AND 15 JOIN market_day m ON m.trade_date=t.trade_date JOIN industry_day i ON i.trade_date=t.trade_date AND i.causal_industry=s.causal_industry
   WHERE t.invalid_step_cum=s.invalid_step_cum AND t.coord_close>s.coord_high AND t.step_return BETWEEN 0 AND .08 AND (t.coord_close-greatest(t.coord_open,t.coord_low))/NULLIF(t.coord_high-t.coord_low,0)>=.60 AND m.recovery_market_median>0 AND m.recovery_market_positive_share>=.55 AND i.recovery_industry_median>0 AND NOT EXISTS(SELECT 1 FROM eligible p WHERE p.symbol=s.symbol AND p.cal_idx>s.cal_idx AND p.cal_idx<t.cal_idx AND (p.invalid_step_cum<>s.invalid_step_cum OR p.coord_close<s.structural_low))),
 first_source_trigger AS (SELECT *,row_number() OVER(PARTITION BY source_event_id ORDER BY cal_idx) AS source_trigger_rank FROM pairs),
 dedup AS (SELECT *,row_number() OVER(PARTITION BY symbol,trade_date ORDER BY source_signal_date DESC,source_event_id) AS symbol_date_rank FROM first_source_trigger WHERE source_trigger_rank=1)
 SELECT * EXCLUDE(source_trigger_rank,symbol_date_rank),'REC36-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,trade_date AS signal_date,decision_at AS feature_latest_timestamp,source_high AS structural_low,stock_minus_industry_ret20 AS stock_minus_industry_ret20_rank,'BULL_CORRECTION_RECOVERY_BREAKOUT' AS admission_lane
 FROM dedup WHERE symbol_date_rank=1 ORDER BY trade_date,symbol
 ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)""");con.close();x=v1.read_parquet_duckdb(CANDIDATES)
 for c in ('trade_date','signal_date','source_signal_date','available_at','decision_at','feature_latest_timestamp'):x[c]=pd.to_datetime(x[c])
 return x


def audit(x:pd.DataFrame)->dict[str,int|bool]:
 return {'duplicate_event_count':int(x.event_id.duplicated().sum()),'duplicate_symbol_signal_count':int(x.duplicated(['symbol','signal_date']).sum()),'feature_after_decision_count':int(x[['available_at','feature_latest_timestamp']].max(axis=1).gt(x.decision_at).sum()),'source_not_before_signal_count':int(x.source_signal_date.ge(x.signal_date).sum()),'trigger_after_15_sessions_count':int((x.cal_idx-x.source_cal_idx>15).sum()),'recovery_definition_violation_count':int((x.recovery_market_median.le(0)|x.recovery_market_positive_share.lt(.55)|x.recovery_industry_median.le(0)).sum()),'candidate_after_2023_count':int(x.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),'outcomes_opened':False}


def blind_sample(x:pd.DataFrame,n:int=30)->pd.DataFrame:
 z=x.copy();z['year']=z.signal_date.dt.year;z['hash_order']=z.event_id.map(lambda s:hashlib.sha256(str(s).encode()).hexdigest());s=pd.concat([g.sort_values('hash_order').head(3) for _,g in z.groupby('year')],ignore_index=True)
 if len(s)<n:s=pd.concat([s,z.loc[~z.event_id.isin(s.event_id)].sort_values('hash_order').head(n-len(s))])
 s=s.sort_values(['signal_date','symbol']).head(n).reset_index(drop=True);s.insert(0,'chart_id',[f'V36-BLIND-{i:03d}' for i in range(1,len(s)+1)]);s.to_csv(BLIND_INDEX,index=False);return s


def render_blind(sample:pd.DataFrame)->None:
 BLIND_DIR.mkdir(parents=True,exist_ok=True);BLIND_PDF.parent.mkdir(parents=True,exist_ok=True);symbols=pd.DataFrame({'symbol':sorted(sample.symbol.unique())});con=duckdb.connect();con.register('symbols',symbols);d=con.execute(f"SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close,ret20 FROM read_parquet('{v1.DAILY}') JOIN symbols USING(symbol) WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31' ORDER BY symbol,trade_date").fetchdf();con.close();d.trade_date=pd.to_datetime(d.trade_date);groups={k:g.reset_index(drop=True) for k,g in d.groupby('symbol')}
 with v1.PdfPages(BLIND_PDF) as pdf:
  for e in sample.itertuples(index=False):
   g=groups[e.symbol];p=np.flatnonzero(g.trade_date.eq(e.signal_date).to_numpy())[0];view=g.iloc[max(0,p-109):p+1];fig,axes=v1.plt.subplots(2,1,figsize=(11.7,8.3),gridspec_kw={'height_ratios':[2.5,.8]});xx=v1.mdates.date2num(view.trade_date);colors=np.where(view.coord_close.ge(view.coord_open),'#dc2626','#059669');axes[0].vlines(xx,view.coord_low,view.coord_high,color=colors,lw=.6);axes[0].bar(xx,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65);axes[0].axvline(e.source_signal_date,color='#7c3aed',ls='--',label='broad-correction source');axes[0].axvline(e.signal_date,color='#2563eb',ls='--',label='recovery breakout trigger');axes[0].axhline(e.source_high,color='#f59e0b',ls=':',label='source high / breakout floor');axes[0].axhline(e.source_low,color='#dc2626',ls=':',label='source low');axes[0].set_title(f'{e.chart_id} | {e.symbol} | {e.sleeve} | {e.causal_industry}',fontproperties=v1.CJK_FONT);axes[0].legend(fontsize=8,ncol=4);axes[0].grid(alpha=.2);axes[1].plot(view.trade_date,view.ret20,color='#7c3aed',label='stock ret20');axes[1].axhline(0,color='black',lw=.5);axes[1].legend(fontsize=8);axes[1].grid(alpha=.2);fig.text(.01,.01,f'Outcome-blind; source to trigger={int(e.cal_idx-e.source_cal_idx)} sessions; recovery market={e.recovery_market_median:+.1%}, breadth={e.recovery_market_positive_share:.0%}; industry={e.recovery_industry_median:+.1%}; trigger={e.step_return:+.1%}.',fontsize=7);fig.tight_layout(rect=[0,.035,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f'{e.chart_id}.png',dpi=135);v1.plt.close(fig)


def cap_upper(x:pd.DataFrame)->tuple[int,dict[str,int]]:
 g=x.groupby(['signal_date','sleeve']).size().clip(upper=10);return int(g.sum()),g.groupby(lambda z:pd.Timestamp(z[0]).year).sum().reindex(YEARS,fill_value=0).astype(int).to_dict()


def run_stage_a()->dict[str,Any]:
 h=persist_contract();x=build_candidates();a=audit(x)
 if any(v for k,v in a.items() if k!='outcomes_opened'):raise ResearchError(str(a))
 s=blind_sample(x);render_blind(s);cap,annual_cap=cap_upper(x);r={'experiment':EXPERIMENT,**h,'runner_sha256':v1.sha256(Path(__file__)),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF),'candidate_count':len(x),'annual_candidate_counts':x.groupby(x.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),'unique_signal_dates':int(x.signal_date.nunique()),'maximum_signals_on_one_date':int(x.groupby('signal_date').size().max()),'mechanical_k10_capacity_upper_bound':cap,'annual_mechanical_capacity_upper_bound':annual_cap,'blind_chart_count':len(s),'audit':a};v1.write_json(FREEZE,r);return r


def verify_stage_a()->dict[str,Any]:
 f=json.loads(FREEZE.read_text());e={'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC),'runner_sha256':v1.sha256(Path(__file__)),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF)};d={k:[f.get(k),v] for k,v in e.items() if f.get(k)!=v}
 if d:raise ResearchError(str(d))
 return f


def run_stage_b()->dict[str,Any]:
 stage_a=verify_stage_a();c=v1.read_parquet_duckdb(CANDIDATES)
 for col in ('signal_date','decision_at'):c[col]=pd.to_datetime(c[col])
 dev=c[c.signal_date.dt.year.isin(DEV_YEARS)];o,a=v34.build_outcomes(dev,'2021-03-31',DEV_OUTCOMES);table=v34.profile_table(o);v1.write_parquet(table,PROFILE_TABLE);el=table[(table.completed_trades>=400)&(table.positive_years>=5)&(table.mean_net>=.03)&(table.mean_holding_sessions<=15)]
 if el.empty:r={'experiment':EXPERIMENT,'verdict':'BULL_CORRECTION_RECOVERY_BREAKOUT_DEVELOPMENT_FAILED','stage_a':stage_a,'profile_table':table.replace({np.nan:None}).to_dict('records'),'development_audit':a,'forward_years_opened':False};v1.write_json(RESULT,r);return r
 s=el.sort_values(['median_annual_mean_net','mean_net','severe_loss10','mean_holding_sessions'],ascending=[False,False,True,True]).iloc[0];profile=str(s.profile);v1.write_json(PROFILE_FREEZE,{'experiment':EXPERIMENT,'selected_profile':profile,'development_outcomes_sha256':v1.sha256(DEV_OUTCOMES),'profile_table_sha256':v1.sha256(PROFILE_TABLE),'forward_opened':False});fwd=c[c.signal_date.dt.year.isin(FORWARD_YEARS)];fo,fa=v34.build_outcomes(fwd,'2024-03-31',FORWARD_OUTCOMES);chosen=pd.concat([o,fo]).loc[lambda x:x.profile.eq(profile)].merge(c[['event_id','industry_positive_ret20_share','stock_minus_industry_ret20_rank','source_turnover_expansion']],on='event_id',validate='one_to_one').rename(columns={'stock_minus_industry_ret20_rank':'stock_minus_industry_ret20','source_turnover_expansion':'turnover_expansion'});daily=v34.load_daily(c.symbol.unique().tolist(),'2024-03-31');accepted,skipped,nav,pa=v1.replay_portfolio(chosen,daily);v1.write_parquet(accepted,ACCEPTED);v1.write_parquet(skipped,SKIPPED);v1.write_parquet(nav,NAV);overall=v34.metrics(accepted.assign(status='COMPLETED'),PROFILES[profile]['target']);annual={str(y):v34.metrics(accepted[accepted.signal_date.dt.year.eq(y)].assign(status='COMPLETED'),PROFILES[profile]['target']) for y in YEARS};portfolio=v1.portfolio_metrics(nav,accepted);conc=v1.concentration_metrics(accepted);gate={'completed_per_year_gt_50':len(accepted)/10>50,'mean_net_gt_5pct':overall['mean_net']>.05,'mean_hold_lt_15':overall['mean_holding_sessions']<15,'forward_each_positive':all(annual[str(y)]['mean_net'] is not None and annual[str(y)]['mean_net']>0 for y in FORWARD_YEARS),'at_least_8_positive_years':sum(v['mean_net'] is not None and v['mean_net']>0 for v in annual.values())>=8,'max_date_share_le_10pct':conc['top_signal_date_share']<=.10};r={'experiment':EXPERIMENT,'verdict':'BULL_CORRECTION_RECOVERY_BREAKOUT_EDGE' if all(gate.values()) else 'BULL_CORRECTION_RECOVERY_BREAKOUT_FAILED_FORWARD_OR_TARGET','selected_profile':profile,'profile_table':table.replace({np.nan:None}).to_dict('records'),'capacity_accepted_completed_trades':len(accepted),'capacity_skips':len(skipped),'completed_per_year':len(accepted)/10,'overall_2014_2023':overall,'annual':annual,'portfolio':portfolio,'concentration':conc,'gate':gate,'audit':{**a,**{f'forward_{k}':v for k,v in fa.items()},**pa,'profile_selected_before_forward_open':True,'feature_after_decision_count':0,'2024_rows_for_2023_resolution_only':True,'2024_signal_count':0}};v1.write_json(RESULT,r);return r


def main()->None:
 p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
 if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
 elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
 else:p.error('choose --stage-a or --stage-b')
if __name__=='__main__':main()
