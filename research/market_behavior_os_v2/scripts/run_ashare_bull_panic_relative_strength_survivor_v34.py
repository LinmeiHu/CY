#!/usr/bin/env python3
"""Bull-market panic relative-strength survivor rebound research."""

from __future__ import annotations

import argparse,hashlib,json
from pathlib import Path
from typing import Any
import duckdb,numpy as np,pandas as pd
import run_ashare_bull_quiet_inventory_industry_acceptance_v1 as v1

ROOT=Path(__file__).resolve().parents[3];OS=ROOT/'research/market_behavior_os_v2';EXPERIMENT='ASHARE-BULL-PANIC-RELATIVE-STRENGTH-SURVIVOR-V34';EXT=Path('/Volumes/quant/CY_quant_research/ashare_bull_panic_relative_strength_survivor_v34')
CONTRACT=OS/f'experiments/{EXPERIMENT}_contract.json';SPEC=OS/f'experiments/{EXPERIMENT}_spec.json';FREEZE=OS/f'artifacts/{EXPERIMENT}_stage_a_freeze.json';PROFILE_FREEZE=OS/f'artifacts/{EXPERIMENT}_profile_freeze.json';RESULT=OS/f'artifacts/{EXPERIMENT}_result.json'
CANDIDATES=EXT/'stage_a/candidates.parquet';BLIND_INDEX=EXT/'stage_a/blind_index.csv';BLIND_DIR=EXT/'stage_a/blind_charts';BLIND_PDF=ROOT/f'output/pdf/{EXPERIMENT}_30_BLIND_CHARTS.pdf';DEV_OUTCOMES=EXT/'stage_b/development_outcomes.parquet';FORWARD_OUTCOMES=EXT/'stage_b/forward_outcomes.parquet';PROFILE_TABLE=EXT/'stage_b/profile_table.parquet';ACCEPTED=EXT/'stage_b/portfolio_accepted.parquet';SKIPPED=EXT/'stage_b/portfolio_skipped.parquet';NAV=EXT/'stage_b/portfolio_nav.parquet'
YEARS=tuple(range(2014,2024));DEV_YEARS=tuple(range(2014,2021));FORWARD_YEARS=(2021,2022,2023);PROFILES={'H5_SIGNAL_LOW_FAILURE':{'horizon':5,'target':None},'H10_SIGNAL_LOW_FAILURE':{'horizon':10,'target':None},'T10_H5_SIGNAL_LOW_FAILURE':{'horizon':5,'target':.10},'T15_H10_SIGNAL_LOW_FAILURE':{'horizon':10,'target':.15}}


class ResearchError(RuntimeError):pass


def contract_value()->dict[str,Any]:
 return {'experiment':EXPERIMENT,'stage':'A_OUTCOME_BLIND_CONTRACT','economic_hypothesis':'When a causally known bull market suffers a broad one-day liquidity shock, forced de-risking supplies stock indiscriminately. A previously strong stock whose PIT industry and own price both resist that shock while closing in the upper part of its range reveals latent demand. Buying after the completed shock seeks the normalization rebound, not a generic oversold bounce.',
 'four_binding_conditions':{'PRIOR_PIT_BULL':'market regime at immediately prior completed session is BULL','BROAD_LIQUIDITY_PANIC':'signal-day executable-universe median return<=-1.5% and positive-stock share<=30%','INDUSTRY_RELATIVE_RESILIENCE':'prior PIT industry is healthy and signal-day industry median return exceeds market median by >=0.5 percentage point','LEADER_REJECTS_PANIC':'pre-signal completed 20-session return is +5% to +50%; signal return is at least max(-1.5%, market+2.5%); close location>=60%; turnover>=80% of prior20 mean'},
 'decision_clock':'completed signal daily close','entry':'first legal daily open after signal within three market sessions','profiles':PROFILES,'failure_exit':'after T+1, first completed daily close below signal-day low; exit next legal open','cost':.004,'development':{'years':list(DEV_YEARS),'minimum_completed':400,'minimum_positive_years':5,'minimum_mean_net':.03,'maximum_mean_holding_sessions':15},'forward':{'years':list(FORWARD_YEARS),'opened_only_after_profile_freeze':True,'2024_q1_use':'late-2023 execution resolution only'},'portfolio':v1.contract_value()['portfolio'],'outcomes_opened':False}


def persist_contract()->dict[str,str]:
 v1.write_json(CONTRACT,contract_value());v1.write_json(SPEC,{'experiment':EXPERIMENT,'status':'OUTCOME_BLIND_CONTRACT','contract_sha256':v1.sha256(CONTRACT),'sources':{'daily':v1.sha256(v1.DAILY),'regime':v1.sha256(v1.SOURCE_REGIME),'industry':v1.sha256(v1.INDUSTRY_PANEL)},'execution_dependency_sha256':v1.sha256(Path(v1.__file__))});return {'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC)}


def build_candidates()->pd.DataFrame:
 CANDIDATES.parent.mkdir(parents=True,exist_ok=True);con=duckdb.connect();con.execute(f"""COPY (
 WITH eligible AS (SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31' AND hard_valid AND history_valid AND current_valid AND corporate_action_valid AND NOT corporate_action_blocking AND current_day_data_tradable AND market_rule_valid AND trade_status=1 AND NOT is_st AND causal_industry IS NOT NULL AND industry_valid),
 market_day AS (SELECT trade_date,median(step_return) AS market_step_median,avg((step_return>0)::INTEGER) AS market_positive_step_share FROM eligible GROUP BY trade_date),
 industry_day AS (SELECT trade_date,causal_industry,median(step_return) AS industry_step_median,avg((step_return>0)::INTEGER) AS industry_positive_step_share,count(*) AS industry_step_n FROM eligible GROUP BY trade_date,causal_industry),
 regime_prev AS (SELECT trade_date AS state_date,lead(trade_date) OVER(ORDER BY trade_date) AS signal_date,market_regime,market_median_ret20,market_positive_ret20_share,latest_source_timestamp AS market_latest_source FROM read_parquet('{v1.SOURCE_REGIME}')),
 d0 AS (SELECT d.*,lag(coord_close) OVER w AS prev_coord_close,lag(coord_close,20) OVER w AS lag20_coord_close,avg(turnover_fraction) OVER w20 AS prior20_turnover,count(*) OVER w20 AS prior20_n FROM eligible d WINDOW w AS(PARTITION BY symbol ORDER BY trade_date),w20 AS(PARTITION BY symbol ORDER BY trade_date ROWS BETWEEN 20 PRECEDING AND 1 PRECEDING)),
 f AS (SELECT d0.*,prev_coord_close/NULLIF(lag20_coord_close,0)-1 AS prior_completed_ret20,turnover_fraction/NULLIF(prior20_turnover,0) AS turnover_expansion,(coord_close-greatest(coord_open,coord_low))/NULLIF(coord_high-coord_low,0) AS close_location FROM d0),
 joined AS (SELECT f.*,rp.state_date,rp.market_regime,rp.market_median_ret20,rp.market_positive_ret20_share,rp.market_latest_source,i.industry_median_ret20,i.industry_positive_ret20_share,i.industry_n20,i.industry_ret20_percentile,i.latest_source_timestamp AS industry_latest_source,m.market_step_median,m.market_positive_step_share,id.industry_step_median,id.industry_positive_step_share,id.industry_step_n FROM f JOIN market_day m USING(trade_date) JOIN industry_day id USING(trade_date,causal_industry) JOIN regime_prev rp ON rp.signal_date=f.trade_date JOIN read_parquet('{v1.INDUSTRY_PANEL}') i ON i.trade_date=rp.state_date AND i.causal_industry=f.causal_industry)
 SELECT *,'PANIC34-'||strftime(trade_date,'%Y%m%d')||'-'||symbol AS event_id,trade_date AS signal_date,decision_at AS feature_latest_timestamp,coord_low AS structural_low,prior_completed_ret20-industry_median_ret20 AS stock_minus_industry_ret20,'BULL_PANIC_RELATIVE_STRENGTH_SURVIVOR' AS admission_lane
 FROM joined WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' AND prior20_n=20 AND market_regime='BULL' AND industry_n20>=5 AND industry_median_ret20>0 AND industry_positive_ret20_share>0.50 AND market_step_median<=-0.015 AND market_positive_step_share<=0.30 AND industry_step_median-market_step_median>=0.005 AND prior_completed_ret20 BETWEEN 0.05 AND 0.50 AND step_return>=greatest(-0.015,market_step_median+0.025) AND step_return<=0.06 AND close_location>=0.60 AND turnover_expansion>=0.80 ORDER BY trade_date,symbol
 ) TO '{CANDIDATES}' (FORMAT PARQUET,COMPRESSION ZSTD)""");con.close();x=v1.read_parquet_duckdb(CANDIDATES)
 for col in ('trade_date','state_date','signal_date','available_at','decision_at','market_latest_source','industry_latest_source','feature_latest_timestamp'):x[col]=pd.to_datetime(x[col])
 return x


def audit(x:pd.DataFrame)->dict[str,int|bool]:
 latest=pd.concat([x.available_at,x.feature_latest_timestamp],axis=1).max(axis=1);return {'duplicate_event_count':int(x.event_id.duplicated().sum()),'current_feature_after_decision_count':int(latest.gt(x.decision_at).sum()),'prior_market_not_before_signal_count':int(x.market_latest_source.ge(x.decision_at).sum()),'prior_industry_not_before_signal_count':int(x.industry_latest_source.ge(x.decision_at).sum()),'panic_definition_violation_count':int((x.market_step_median.gt(-.015)|x.market_positive_step_share.gt(.30)).sum()),'candidate_after_2023_count':int(x.signal_date.gt(pd.Timestamp('2023-12-31')).sum()),'outcomes_opened':False}


def blind_sample(x:pd.DataFrame,n:int=30)->pd.DataFrame:
 z=x.copy();z['year']=z.signal_date.dt.year;z['hash_order']=z.event_id.map(lambda s:hashlib.sha256(str(s).encode()).hexdigest());s=pd.concat([g.sort_values('hash_order').head(3) for _,g in z.groupby('year')],ignore_index=True)
 if len(s)<n:s=pd.concat([s,z.loc[~z.event_id.isin(s.event_id)].sort_values('hash_order').head(n-len(s))])
 s=s.sort_values(['signal_date','symbol']).head(n).reset_index(drop=True);s.insert(0,'chart_id',[f'V34-BLIND-{i:03d}' for i in range(1,len(s)+1)]);s.to_csv(BLIND_INDEX,index=False);return s


def render_blind(s:pd.DataFrame)->None:
 BLIND_DIR.mkdir(parents=True,exist_ok=True);BLIND_PDF.parent.mkdir(parents=True,exist_ok=True);symbols=pd.DataFrame({'symbol':sorted(s.symbol.unique())});con=duckdb.connect();con.register('symbols',symbols);d=con.execute(f"SELECT trade_date,symbol,coord_open,coord_high,coord_low,coord_close,ret20 FROM read_parquet('{v1.DAILY}') JOIN symbols USING(symbol) WHERE trade_date BETWEEN DATE '2013-01-01' AND DATE '2023-12-31' ORDER BY symbol,trade_date").fetchdf();con.close();d.trade_date=pd.to_datetime(d.trade_date);groups={k:g.reset_index(drop=True) for k,g in d.groupby('symbol')}
 with v1.PdfPages(BLIND_PDF) as pdf:
  for e in s.itertuples(index=False):
   g=groups[e.symbol];p=np.flatnonzero(g.trade_date.eq(e.signal_date).to_numpy())[0];view=g.iloc[max(0,p-89):p+1];fig,axes=v1.plt.subplots(2,1,figsize=(11.7,8.3),gridspec_kw={'height_ratios':[2.5,.8]});xx=v1.mdates.date2num(view.trade_date);colors=np.where(view.coord_close.ge(view.coord_open),'#dc2626','#059669');axes[0].vlines(xx,view.coord_low,view.coord_high,color=colors,lw=.6);axes[0].bar(xx,np.maximum(abs(view.coord_close-view.coord_open),view.coord_close.abs()*.0005),bottom=np.minimum(view.coord_open,view.coord_close),color=colors,width=.65);axes[0].axvline(e.signal_date,color='#2563eb',ls='--',label='completed panic-survivor signal');axes[0].axhline(e.structural_low,color='#f59e0b',ls=':',label='signal low / failure structure');axes[0].set_title(f"{e.chart_id} | {e.symbol} | {e.sleeve} | {e.causal_industry}",fontproperties=v1.CJK_FONT);axes[0].legend(fontsize=8);axes[0].grid(alpha=.2);axes[1].plot(view.trade_date,view.ret20,color='#7c3aed',label='stock ret20');axes[1].axhline(0,color='black',lw=.5);axes[1].grid(alpha=.2);axes[1].legend(fontsize=8)
   fig.text(.01,.01,"Outcome-blind; no post-signal bar. "f"market shock={e.market_step_median:+.1%}, breadth={e.market_positive_step_share:.0%}; industry={e.industry_step_median:+.1%}; stock={e.step_return:+.1%}; prior20={e.prior_completed_ret20:+.1%}; close location={e.close_location:.0%}.",fontsize=7);fig.tight_layout(rect=[0,.035,1,1]);pdf.savefig(fig,dpi=150);fig.savefig(BLIND_DIR/f'{e.chart_id}.png',dpi=135);v1.plt.close(fig)


def run_stage_a()->dict[str,Any]:
 h=persist_contract();x=build_candidates();a=audit(x)
 if any(v for k,v in a.items() if k!='outcomes_opened'):raise ResearchError(str(a))
 s=blind_sample(x);render_blind(s);r={'experiment':EXPERIMENT,**h,'runner_sha256':v1.sha256(Path(__file__)),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF),'candidate_count':len(x),'annual_candidate_counts':x.groupby(x.signal_date.dt.year).size().reindex(YEARS,fill_value=0).astype(int).to_dict(),'unique_signal_dates':int(x.signal_date.nunique()),'maximum_signals_on_one_date':int(x.groupby('signal_date').size().max()),'blind_chart_count':len(s),'audit':a};v1.write_json(FREEZE,r);return r


def verify_stage_a()->dict[str,Any]:
 f=json.loads(FREEZE.read_text());e={'contract_sha256':v1.sha256(CONTRACT),'spec_sha256':v1.sha256(SPEC),'runner_sha256':v1.sha256(Path(__file__)),'candidate_sha256':v1.sha256(CANDIDATES),'blind_pdf_sha256':v1.sha256(BLIND_PDF)};d={k:[f.get(k),v] for k,v in e.items() if f.get(k)!=v}
 if d:raise ResearchError(str(d))
 return f


def load_daily(symbols:list[str],through:str)->pd.DataFrame:
 reg=pd.DataFrame({'symbol':sorted(set(symbols))});con=duckdb.connect();con.register('reg',reg)
 if pd.Timestamp(through)<=pd.Timestamp('2023-12-31'):source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '{through}'"
 else:source=f"SELECT * FROM read_parquet('{v1.DAILY}') WHERE trade_date BETWEEN DATE '2014-01-01' AND DATE '2023-12-31' UNION ALL BY NAME SELECT * FROM read_parquet('{v1.DAILY_TAIL}') WHERE trade_date BETWEEN DATE '2024-01-01' AND DATE '{through}'"
 x=con.execute(f"WITH d AS ({source}) SELECT d.* FROM d JOIN reg USING(symbol) ORDER BY symbol,trade_date").fetchdf();con.close();x.trade_date=pd.to_datetime(x.trade_date);return x


def build_outcomes(c:pd.DataFrame,through:str,out:Path)->tuple[pd.DataFrame,dict[str,int]]:
 daily=load_daily(c.symbol.unique().tolist(),through);groups={k:g.reset_index(drop=True) for k,g in daily.groupby('symbol')};rows=[]
 for e in c.itertuples(index=False):
  g=groups[e.symbol];sp=np.flatnonzero(g.trade_date.eq(e.signal_date).to_numpy());entry_pos=None
  if len(sp)!=1:raise ResearchError(f'missing signal {e.event_id}')
  for p in range(int(sp[0])+1,len(g)):
   if int(g.iloc[p].cal_idx)>int(e.cal_idx)+3:break
   if v1.legal_buy(g.iloc[p],float(e.invalid_step_cum)):entry_pos=p;break
  for profile,s in PROFILES.items():
   base={'event_id':e.event_id,'symbol':e.symbol,'sleeve':e.sleeve,'signal_date':e.signal_date,'signal_cal_idx':int(e.cal_idx),'profile':profile,'structural_low':float(e.structural_low)}
   if entry_pos is None:rows.append({**base,'status':'NO_LEGAL_ENTRY'});continue
   entry=g.iloc[entry_pos];price=float(entry.coord_open);target=None if s['target'] is None else price*(1+s['target']);horizon=int(entry.cal_idx)+s['horizon'];ep=xp=exit_price=reason=decision=None
   for p in range(entry_pos+1,len(g)):
    row=g.iloc[p]
    if not v1.legal_state(row,float(e.invalid_step_cum)):continue
    if target is not None and float(row.coord_high)>=target:xp=p;exit_price=target;reason=f"TARGET_{int(s['target']*100)}";decision=int(row.cal_idx);break
    if float(row.coord_close)<float(e.structural_low):
     decision=int(row.cal_idx)
     for q in range(p+1,len(g)):
      if v1.legal_sell_open(g.iloc[q],float(e.invalid_step_cum)):xp=q;exit_price=float(g.iloc[q].coord_open);reason='SIGNAL_LOW_FAILURE';break
     break
    if int(row.cal_idx)>=horizon:
     decision=int(row.cal_idx)
     for q in range(p+1,len(g)):
      if v1.legal_sell_open(g.iloc[q],float(e.invalid_step_cum)):xp=q;exit_price=float(g.iloc[q].coord_open);reason=f"H{s['horizon']}_TIME_STOP";break
     break
   if xp is None:rows.append({**base,'status':'UNRESOLVED'});continue
   er=g.iloc[int(xp)];gross=float(exit_price)/price-1;rows.append({**base,'status':'COMPLETED','entry_date':entry.trade_date,'entry_cal_idx':int(entry.cal_idx),'entry_price':price,'exit_date':er.trade_date,'exit_cal_idx':int(er.cal_idx),'exit_price':float(exit_price),'exit_reason':reason,'exit_decision_cal_idx':decision,'holding_sessions':int(er.cal_idx)-int(entry.cal_idx),'gross_return':gross,'net_return':gross-.004})
 x=pd.DataFrame(rows)
 for col in ('signal_date','entry_date','exit_date'):x[col]=pd.to_datetime(x[col])
 v1.write_parquet(x,out);return x,{'signal_bar_fill_count':int((x.entry_date.notna()&x.entry_date.le(x.signal_date)).sum()),'t1_same_day_exit_count':int((x.status.eq('COMPLETED')&x.exit_cal_idx.le(x.entry_cal_idx)).sum())}


def metrics(x:pd.DataFrame,target:float|None=None)->dict[str,Any]:
 z=x[x.status.eq('COMPLETED')]
 if z.empty:return {'completed_trades':0,'mean_net':None,'median_net':None,'win_rate':None,'severe_loss10':None,'target_hit_rate':None,'mean_holding_sessions':None,'median_holding_sessions':None}
 reason=None if target is None else f"TARGET_{int(target*100)}";return {'completed_trades':len(z),'mean_net':float(z.net_return.mean()),'median_net':float(z.net_return.median()),'win_rate':float(z.net_return.gt(0).mean()),'severe_loss10':float(z.net_return.le(-.10).mean()),'target_hit_rate':None if reason is None else float(z.exit_reason.eq(reason).mean()),'mean_holding_sessions':float(z.holding_sessions.mean()),'median_holding_sessions':float(z.holding_sessions.median())}


def profile_table(o:pd.DataFrame)->pd.DataFrame:
 rows=[]
 for p,s in PROFILES.items():
  x=o[o.profile.eq(p)];a={str(y):metrics(x[x.signal_date.dt.year.eq(y)],s['target']) for y in DEV_YEARS};means=[v['mean_net'] for v in a.values() if v['mean_net'] is not None];rows.append({'profile':p,**metrics(x,s['target']),'positive_years':sum(v>0 for v in means),'median_annual_mean_net':float(np.median(means)),'annual_json':json.dumps(a,sort_keys=True)})
 return pd.DataFrame(rows)


def run_stage_b()->dict[str,Any]:
 stage_a=verify_stage_a();c=v1.read_parquet_duckdb(CANDIDATES)
 for col in ('signal_date','decision_at'):c[col]=pd.to_datetime(c[col])
 dev=c[c.signal_date.dt.year.isin(DEV_YEARS)];o,a=build_outcomes(dev,'2021-03-31',DEV_OUTCOMES);table=profile_table(o);v1.write_parquet(table,PROFILE_TABLE);el=table[(table.completed_trades>=400)&(table.positive_years>=5)&(table.mean_net>=.03)&(table.mean_holding_sessions<=15)]
 if el.empty:r={'experiment':EXPERIMENT,'verdict':'BULL_PANIC_SURVIVOR_DEVELOPMENT_FAILED','stage_a':stage_a,'profile_table':table.replace({np.nan:None}).to_dict('records'),'development_audit':a,'forward_years_opened':False};v1.write_json(RESULT,r);return r
 s=el.sort_values(['median_annual_mean_net','mean_net','severe_loss10','mean_holding_sessions'],ascending=[False,False,True,True]).iloc[0];profile=str(s.profile);v1.write_json(PROFILE_FREEZE,{'experiment':EXPERIMENT,'selected_profile':profile,'development_outcomes_sha256':v1.sha256(DEV_OUTCOMES),'profile_table_sha256':v1.sha256(PROFILE_TABLE),'forward_opened':False});fwd=c[c.signal_date.dt.year.isin(FORWARD_YEARS)];fo,fa=build_outcomes(fwd,'2024-03-31',FORWARD_OUTCOMES);chosen=pd.concat([o,fo]).loc[lambda x:x.profile.eq(profile)].merge(c[['event_id','industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion']],on='event_id',validate='one_to_one');accepted,skipped,nav=v1.replay_portfolio(chosen);v1.write_parquet(accepted,ACCEPTED);v1.write_parquet(skipped,SKIPPED);v1.write_parquet(nav,NAV);overall=metrics(accepted.assign(status='COMPLETED'),PROFILES[profile]['target']);annual={str(y):metrics(accepted[accepted.signal_date.dt.year.eq(y)].assign(status='COMPLETED'),PROFILES[profile]['target']) for y in YEARS};portfolio=v1.portfolio_metrics(nav,accepted);conc=v1.concentration_metrics(accepted);gate={'completed_per_year_gt_50':len(accepted)/10>50,'mean_net_gt_5pct':overall['mean_net']>.05,'mean_hold_lt_15':overall['mean_holding_sessions']<15,'forward_each_positive':all(annual[str(y)]['mean_net'] is not None and annual[str(y)]['mean_net']>0 for y in FORWARD_YEARS),'at_least_8_positive_years':sum(v['mean_net'] is not None and v['mean_net']>0 for v in annual.values())>=8,'max_date_share_le_10pct':conc['top_signal_date_share']<=.10};verdict='BULL_PANIC_RELATIVE_STRENGTH_EDGE' if all(gate.values()) else 'BULL_PANIC_SURVIVOR_FAILED_FORWARD_OR_TARGET';r={'experiment':EXPERIMENT,'verdict':verdict,'selected_profile':profile,'profile_table':table.replace({np.nan:None}).to_dict('records'),'capacity_accepted_completed_trades':len(accepted),'capacity_skips':len(skipped),'completed_per_year':len(accepted)/10,'overall_2014_2023':overall,'annual':annual,'portfolio':portfolio,'concentration':conc,'gate':gate,'audit':{**a,**{f'forward_{k}':v for k,v in fa.items()},'profile_selected_before_forward_open':True,'feature_after_decision_count':0,'2024_rows_for_2023_resolution_only':True,'2024_signal_count':0}};v1.write_json(RESULT,r);return r


def main()->None:
 p=argparse.ArgumentParser();p.add_argument('--stage-a',action='store_true');p.add_argument('--stage-b',action='store_true');a=p.parse_args()
 if a.stage_a:print(json.dumps(run_stage_a(),indent=2,default=str))
 elif a.stage_b:print(json.dumps(run_stage_b(),indent=2,default=str))
 else:p.error('choose --stage-a or --stage-b')
if __name__=='__main__':main()
