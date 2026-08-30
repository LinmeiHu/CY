#!/usr/bin/env python3
"""Test H-006 right-tail density incrementality beyond frozen breadth/trend."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import numpy as np,pandas as pd
from scipy.stats import pearsonr
ROOT=Path(__file__).resolve().parents[4]; WORK=ROOT/'research/chinext_v1/regime_attribution'; sys.path.insert(0,str(WORK/'scripts'))
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402
SPEC=WORK/'experiments/EXP-RTD-001_spec.json'; DAILY=WORK/'artifacts/daily_regime_features.parquet'; TRADES=WORK/'artifacts/yearly_trades.csv'; PRE=WORK/'artifacts/pre_entry_transitions.csv'
OUT_TABLE=WORK/'artifacts/right_tail_density_incrementality.csv'; OUT_JSON=WORK/'artifacts/right_tail_density_incrementality.json'; REPORT=WORK/'reports/right_tail_density_incrementality.md'
FEATURE='cross_sectional_return20_right_tail_ge20'; NEIGHBORS=('cross_sectional_return20_p90','cross_sectional_return20_p90_p10_spread')
BASE=('breadth_above_ma20','breadth_above_ma60','breadth_above_ma20_change20','index_return_20d','index_close_to_ma60','index_ma20_slope_5d'); RISK=('entry_beta60','entry_log_amount20','index_realized_vol20')
class DensityError(RuntimeError):pass
def sha(p:Path)->str:return hashlib.sha256(p.read_bytes()).hexdigest()
def atomic(p:Path,s:str)->None:p.parent.mkdir(parents=True,exist_ok=True);q=p.with_suffix(p.suffix+'.tmp');q.write_text(s);q.replace(p)
def validate()->tuple[dict[str,Any],dict[str,str]]:
 s=json.loads(SPEC.read_text());
 if s.get('experiment_id')!='EXP-RTD-001' or s.get('status')!='FROZEN_BEFORE_FIRST_INCREMENTALITY_TEST':raise DensityError('invalid spec')
 ids={};bad={}
 for n,b in s['input_bindings'].items():
  p=Path(b['path']);p=p if p.is_absolute() else ROOT/p;a=sha(p) if p.is_file() else 'MISSING';ids[str(p)]=a
  if a!=b['sha256']:bad[n]={'expected':b['sha256'],'actual':a}
 if bad:raise DensityError(f'input mismatch {bad}')
 return s,ids
def load()->pd.DataFrame:
 t=pd.read_csv(TRADES,usecols=['trade_id','baseline_block','symbol','entry_signal_date','mfe','round_trip_return','realized_pnl']);p=pd.read_csv(PRE,usecols=['trade_id','entry_industry','false_breakout',*RISK]);d=pd.read_parquet(DAILY,columns=['baseline_block','trade_date',FEATURE,*NEIGHBORS,*BASE,'index_realized_vol20'])
 t['entry_signal_date']=pd.to_datetime(t.entry_signal_date);d['trade_date']=pd.to_datetime(d.trade_date);f=t.merge(p,on='trade_id',validate='one_to_one').merge(d,left_on=['baseline_block','entry_signal_date'],right_on=['baseline_block','trade_date'],validate='many_to_one');f['entry_year']=f.entry_signal_date.dt.year;f['opportunity20']=f.mfe>=.20;f['non_false_breakout']=~f.false_breakout.astype(bool)
 if len(f)!=399 or f[FEATURE].notna().sum()!=387 or f[[FEATURE,*BASE]].notna().all(axis=1).sum()!=383:raise DensityError('coverage changed')
 return f
def partial(f:pd.DataFrame,controls:tuple[str,...])->dict[str,Any]:
 d=f[[FEATURE,'mfe',*controls,'entry_year']].replace([np.inf,-np.inf],np.nan).dropna();o={'n':len(d),'partial_rank_rho':None,'p_value':None}
 if len(d)<300:return o
 x=d[FEATURE].rank(pct=True).to_numpy();y=d.mfe.rank(pct=True).to_numpy();z=np.column_stack([d[c].rank(pct=True) for c in controls]);dum=pd.get_dummies(d.entry_year.astype(str),drop_first=True,dtype=float).to_numpy();a=np.column_stack([np.ones(len(d)),z,dum]);xr=x-a@np.linalg.lstsq(a,x,rcond=None)[0];yr=y-a@np.linalg.lstsq(a,y,rcond=None)[0];e=pearsonr(xr,yr);o.update(partial_rank_rho=float(e.statistic),p_value=float(e.pvalue));return o
def controlled(f:pd.DataFrame,controls:tuple[str,...])->dict[str,Any]:
 o=partial(f,controls);l={str(y):partial(f[f.entry_year!=y],controls) for y in range(2018,2026)};return {**o,'loyo':l,'loyo_positive_count':sum(v['partial_rank_rho'] is not None and v['partial_rank_rho']>0 for v in l.values())}
def analyze(f:pd.DataFrame)->dict[str,Any]:
 raw=wla.rank_association(f.dropna(subset=[FEATURE]),FEATURE,'mfe');ctl=controlled(f,BASE);risk=controlled(f,(*BASE,*RISK));opp=wla.rank_association(f.dropna(subset=[FEATURE]),FEATURE,'opportunity20');nf=wla.rank_association(f.dropna(subset=[FEATURE]),FEATURE,'non_false_breakout');nei={n:wla.rank_association(f.dropna(subset=[n]),n,'mfe') for n in NEIGHBORS};blocks={str(k):wla.safe_spearman(r[FEATURE],r.mfe) for k,r in f.groupby('baseline_block')};top=wla.deterministic_top_flag(f,4);ex=wla.rank_association(f.loc[~top].dropna(subset=[FEATURE]),FEATURE,'mfe');sec=wla.omit_group_sensitivity(f.dropna(subset=[FEATURE]),FEATURE,'mfe','symbol');ind=wla.omit_group_sensitivity(f.dropna(subset=[FEATURE,'entry_industry']),FEATURE,'mfe','entry_industry')
 rg=raw['rho'] is not None and raw['rho']>=.10 and raw['within_year_rank_rho']>0 and raw['loyo_positive_count']>=7;cg=ctl['partial_rank_rho'] is not None and ctl['partial_rank_rho']>=.10 and ctl['loyo_positive_count']>=7;og=opp['rho'] is not None and opp['rho']>=.10 and opp['loyo_positive_count']>=7 and nf['rho'] is not None and nf['rho']>0;ng=all(v['rho'] is not None and v['rho']>0 and v['loyo_positive_count']>=6 for v in nei.values());fg=risk['partial_rank_rho'] is not None and risk['partial_rank_rho']>=.08 and sum(v['rho'] is not None and v['rho']>0 for v in blocks.values())>=2 and ex['rho'] is not None and ex['rho']>0 and sec['positive_fraction']>=.8 and ind['positive_fraction']>=.8
 if all((rg,cg,og,ng,fg)):dec,ver='VALIDATE','RIGHT_TAIL_DENSITY_IS_INCREMENTAL_OPPORTUNITY_STATE'
 elif rg and cg:dec,ver='REFINE','INCREMENTAL_ASSOCIATION_FAILS_FULL_REPLICATION'
 elif rg:dec,ver='REJECT','RIGHT_TAIL_DENSITY_IS_REDUNDANT_OR_BLOCK_UNSTABLE'
 else:dec,ver='REJECT','UNIVARIATE_RIGHT_TAIL_DENSITY_DOES_NOT_REPLICATE'
 return {'experiment_id':'EXP-RTD-001','decision':dec,'mechanism_verdict':ver,'primary':{'raw':raw,'controlled_breadth_trend':ctl,'controlled_plus_risk':risk,'opportunity20':opp,'non_false_breakout':nf,'neighbors':nei,'blocks':blocks,'ex_top4_pnl':ex,'leave_one_security_out':sec,'leave_one_industry_out':ind,'raw_gate':rg,'controlled_gate':cg,'outcome_gate':og,'neighbor_gate':ng,'falsification_gate':fg},'strategy_modification':'NONE','interpretation_boundary':'historically consumed opportunity attribution only; no threshold, overlay, or strategy rule'}
def main()->int:
 s,ids=validate();f=load();r=analyze(f);r.update(spec_sha256=sha(SPEC),input_identities=ids,audit={'cycles':399,'feature_complete':387,'fixed_control_complete':383,'strategy_replays':0,'thresholds_tested':0},evidence_grade='EXPLORATORY_INCREMENTAL_MECHANISM');atomic(OUT_TABLE,f.sort_values('trade_id').to_csv(index=False,lineterminator='\n',float_format='%.17g'));atomic(OUT_JSON,json.dumps(wla.clean_json(r),indent=2,sort_keys=True)+'\n');p=r['primary'];atomic(REPORT,f"# Eligible-universe right-tail density incrementality\n\n- Raw MFE rho: `{p['raw']['rho']}`\n- Breadth/trend controlled rho: `{p['controlled_breadth_trend']['partial_rank_rho']}`\n- Decision: `{r['decision']}` / `{r['mechanism_verdict']}`\n\nNo threshold, overlay, replay, or strategy change was tested.\n");return 0
if __name__=='__main__':raise SystemExit(main())
