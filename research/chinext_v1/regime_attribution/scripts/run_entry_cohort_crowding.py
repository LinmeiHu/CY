#!/usr/bin/env python3
"""Test whether same-day entry cohort size explains false-breakout incidence."""
from __future__ import annotations
import hashlib,json,sys
from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd
from scipy.stats import pearsonr

ROOT=Path(__file__).resolve().parents[4]; WORK=ROOT/'research/chinext_v1/regime_attribution'
sys.path.insert(0,str(WORK/'scripts'))
import run_winner_loser_trajectory_archaeology as wla  # noqa: E402

SPEC=WORK/'experiments/EXP-ECC-001_spec.json'
TRADES=WORK/'artifacts/entry_gap_premium_attribution.csv'
CONTROLS=WORK/'artifacts/pre_entry_transitions.csv'
LEDGERS={
 'EXTENDED_2018_2021':ROOT/'research/chinext_v1/data/execution_ledgers/extended_execution_ledger.jsonl',
 'HOLDOUT_O0_2022_2023':ROOT/'research/chinext_v1/data/execution_ledgers/holdout_execution_ledger.jsonl',
 'DEVELOPMENT_2024_2025':ROOT/'research/chinext_v1/data/execution_ledgers/development_execution_ledger.jsonl'}
OUT_TABLE=WORK/'artifacts/entry_cohort_crowding.csv'; OUT_JSON=WORK/'artifacts/entry_cohort_crowding.json'; REPORT=WORK/'reports/entry_cohort_crowding.md'
CONTROL_COLS=('breadth_composite','entry_rs_score','index_return_20d','index_realized_vol20','entry_beta60','entry_log_amount20')

class CohortError(RuntimeError): pass
def sha(path:Path)->str: return hashlib.sha256(path.read_bytes()).hexdigest()
def atomic(path:Path,text:str)->None:
 path.parent.mkdir(parents=True,exist_ok=True); tmp=path.with_suffix(path.suffix+'.tmp'); tmp.write_text(text); tmp.replace(path)
def resolve(raw:str)->Path:
 p=Path(raw); return p if p.is_absolute() else ROOT/p
def validate()->tuple[dict[str,Any],dict[str,str]]:
 s=json.loads(SPEC.read_text());
 if s.get('experiment_id')!='EXP-ECC-001' or s.get('status')!='FROZEN_BEFORE_FIRST_COHORT_OUTCOME_TEST': raise CohortError('invalid spec')
 ids={}; bad={}
 for n,b in s['input_bindings'].items():
  p=resolve(b['path']); a=sha(p) if p.is_file() else 'MISSING'; ids[str(p)]=a
  if a!=b['sha256']: bad[n]={'expected':b['sha256'],'actual':a}
 if bad: raise CohortError(f'input mismatch {bad}')
 return s,ids
def entry_counts()->pd.DataFrame:
 rows=[]
 for block,p in LEDGERS.items():
  for line in p.read_text().splitlines():
   r=json.loads(line)
   if r.get('status')=='FILLED' and r.get('side')=='BUY' and r.get('new_position') is True:
    rows.append({'baseline_block':block,'symbol':str(r['symbol']),'entry_signal_date':str(r['signal_date']),'entry_execution_date':str(r['execution_date'])})
 e=pd.DataFrame(rows); e['entry_cohort_size']=e.groupby(['baseline_block','entry_execution_date']).symbol.transform('size')
 return e
def load(s:dict[str,Any])->tuple[pd.DataFrame,pd.DataFrame,dict[str,Any]]:
 t=pd.read_csv(TRADES); c=pd.read_csv(CONTROLS,usecols=['trade_id',*CONTROL_COLS])
 t=t.merge(c,on='trade_id',validate='one_to_one'); e=entry_counts(); keys=['baseline_block','symbol','entry_signal_date','entry_execution_date']
 t=t.merge(e,on=keys,validate='one_to_one')
 if len(t)!=399 or int(t.false_breakout.astype(bool).sum())!=213: raise CohortError('trade sample changed')
 t['entry_year']=pd.to_datetime(t.entry_execution_date).dt.year
 groups=[]
 for (block,date),r in t.groupby(['baseline_block','entry_execution_date'],sort=True):
  groups.append({'baseline_block':block,'entry_execution_date':date,'entry_year':int(r.entry_year.iloc[0]),'entry_cohort_size':int(r.entry_cohort_size.iloc[0]),'completed_entries':len(r),'false_breakout_rate':float(r.false_breakout.astype(float).mean()),'mean_oriented_order':float(r.oriented_order.mean()),'cohort_realized_pnl':float(r.realized_pnl.sum()),'industry_concentration':float(r.entry_industry.value_counts(normalize=True).max()),**{f'mean_{x}':float(r[x].mean()) for x in CONTROL_COLS}})
 g=pd.DataFrame(groups)
 expected=s['sample']['cohort_size_counts']; actual={str(int(k)):int(v) for k,v in g.groupby('entry_cohort_size').size().items()}
 if len(g)!=255 or actual!=expected or not (g.entry_cohort_size==g.completed_entries).all(): raise CohortError('cohort audit changed')
 return t,g,{'trades':399,'cohort_dates':255,'multi_entry_dates':int((g.entry_cohort_size>=2).sum()),'cohort_size_counts':actual,'pseudoreplicated_primary':False,'strategy_replays':0,'rules_tested':0}
def partial(g:pd.DataFrame)->dict[str,Any]:
 cols=['entry_cohort_size','false_breakout_rate',*[f'mean_{x}' for x in CONTROL_COLS],'industry_concentration','entry_year']; d=g[cols].replace([np.inf,-np.inf],np.nan).dropna()
 out={'n':len(d),'partial_rank_rho':None,'p_value':None}
 if len(d)<150:return out
 x=d.entry_cohort_size.rank(pct=True).to_numpy(); y=d.false_breakout_rate.rank(pct=True).to_numpy(); z=d[[f'mean_{x}' for x in CONTROL_COLS]+['industry_concentration']].rank(pct=True).to_numpy(); dum=pd.get_dummies(d.entry_year.astype(str),drop_first=True,dtype=float).to_numpy(); design=np.column_stack([np.ones(len(d)),z,dum]); xr=x-design@np.linalg.lstsq(design,x,rcond=None)[0]; yr=y-design@np.linalg.lstsq(design,y,rcond=None)[0]; est=pearsonr(xr,yr); out.update(partial_rank_rho=float(est.statistic),p_value=float(est.pvalue)); return out
def controlled(g:pd.DataFrame)->dict[str,Any]:
 full=partial(g); l={str(y):partial(g[g.entry_year!=y]) for y in range(2018,2026)}; return {**full,'loyo':l,'loyo_positive_count':sum(v['partial_rank_rho'] is not None and v['partial_rank_rho']>0 for v in l.values())}
def analyze(t:pd.DataFrame,g:pd.DataFrame)->dict[str,Any]:
 raw=wla.rank_association(g.rename(columns={'entry_execution_date':'trade_id'}),'entry_cohort_size','false_breakout_rate'); ctl=controlled(g); trade=wla.rank_association(t,'entry_cohort_size','false_breakout'); topo=wla.rank_association(g.rename(columns={'entry_execution_date':'trade_id'}),'entry_cohort_size','mean_oriented_order'); small=wla.rank_association(g[g.entry_cohort_size<5].rename(columns={'entry_execution_date':'trade_id'}),'entry_cohort_size','false_breakout_rate'); blocks={str(k):wla.safe_spearman(r.entry_cohort_size,r.false_breakout_rate) for k,r in g.groupby('baseline_block')}; multi=float(g.loc[g.entry_cohort_size>=2,'false_breakout_rate'].mean()-g.loc[g.entry_cohort_size==1,'false_breakout_rate'].mean())
 rg=raw['rho'] is not None and raw['rho']>=.10 and raw['within_year_rank_rho']>0 and raw['loyo_positive_count']>=7; cg=ctl['partial_rank_rho'] is not None and ctl['partial_rank_rho']>=.10 and ctl['loyo_positive_count']>=7; ng=trade['rho'] is not None and trade['rho']>0 and trade['loyo_positive_count']>=6 and multi>0; tg=topo['rho'] is not None and topo['rho']>=.10 and topo['loyo_positive_count']>=7; fg=small['rho'] is not None and small['rho']>0 and sum(v['rho'] is not None and v['rho']>0 for v in blocks.values())>=2
 if all((rg,cg,ng,tg,fg)):dec,ver='DEEPEN','ENTRY_COHORT_CROWDING_CONTRIBUTES_TO_FALSE_BREAKOUTS'
 elif rg and cg:dec,ver='REFINE','COHORT_SIZE_ASSOCIATES_WITH_FALSE_BREAKOUTS_BUT_NOT_FULL_TOPOLOGY'
 elif rg:dec,ver='PIVOT','RAW_COHORT_EFFECT_IS_REDUNDANT_WITH_BREADTH_OR_ENTRY_STATE'
 else:dec,ver='REJECT','ENTRY_COHORT_SIZE_DOES_NOT_EXPLAIN_FALSE_BREAKOUTS'
 return {'experiment_id':'EXP-ECC-001','decision':dec,'mechanism_verdict':ver,'primary':{'cohort_date_raw':raw,'controlled':ctl,'trade_level_neighbor':trade,'topology':topo,'cohort_size_below5':small,'multi_minus_single_rate':multi,'blocks':blocks,'raw_gate':rg,'controlled_gate':cg,'neighbor_gate':ng,'topology_gate':tg,'falsification_gate':fg},'strategy_modification':'NONE','interpretation_boundary':'cohort counts describe accepted fills and do not authorize throttling simultaneous entries'}
def main()->int:
 s,ids=validate(); t,g,a=load(s); r=analyze(t,g); r.update(spec_sha256=sha(SPEC),input_identities=ids,audit=a,evidence_grade='EXPLORATORY_PORTFOLIO_INTERACTION')
 atomic(OUT_TABLE,g.sort_values(['baseline_block','entry_execution_date']).to_csv(index=False,lineterminator='\n',float_format='%.17g')); atomic(OUT_JSON,json.dumps(wla.clean_json(r),indent=2,sort_keys=True)+'\n'); p=r['primary']; atomic(REPORT,f"# Same-day entry cohort crowding\n\nEXP-ECC-001 uses 255 cohort dates as the primary independent units.\n\n- Raw rho: `{p['cohort_date_raw']['rho']}`\n- Controlled rho: `{p['controlled']['partial_rank_rho']}`\n- Decision: `{r['decision']}` / `{r['mechanism_verdict']}`\n\nNo entry throttle, filter, sizing, or production change was tested.\n"); return 0
if __name__=='__main__': raise SystemExit(main())
