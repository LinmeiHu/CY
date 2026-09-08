"""Discovery-only robustness of the observed visual scores; no new alpha features."""
import numpy as np,pandas as pd
from .build import HERE,EXT,DAILY,SEED,setup

def main():
 p=HERE/'visual';q=HERE/'quant';q.mkdir(exist_ok=True)
 s=pd.read_parquet(EXT/'visual/revealed_discovery_sample.parquet');v=pd.read_csv(p/'formal_visual_labels.csv');dims=list(v.columns[2:]);f=s.loc[s.stage.eq('formal')].merge(v,on='blind_id');f['year']=f.trade_date.dt.year
 rng=np.random.default_rng(SEED);rows=[]
 for d in dims:
  z=f.pivot(index='triplet_id',columns='label',values=d);delta=(z.WINNER-z.LOSER).dropna().to_numpy();boot=np.mean(rng.choice(delta,(2000,len(delta))),axis=1)
  rows.append(dict(dimension=d,n_pairs=len(delta),paired_difference=delta.mean(),bootstrap_lo=np.quantile(boot,.025),bootstrap_hi=np.quantile(boot,.975),winner_gt_loser=(delta>0).mean(),winner_eq_loser=(delta==0).mean(),modal_share=f[d].value_counts(normalize=True).max(),note='Descriptive triplet bootstrap; overlapping outcomes and shared dates limit independence'))
 pd.DataFrame(rows).to_csv(p/'paired_visual_diagnostics.csv',index=False)
 # Causal market beta: trailing60 covariance of valid daily stock return and equalweight market.
 c=setup();c.execute(f"create temp table r as select symbol,trade_date,cal_idx,case when history_valid and cal_idx=lag(cal_idx) over w+1 and invalid_step_cum=lag(invalid_step_cum) over w then coord_close/lag(coord_close) over w-1 end r from read_parquet('{DAILY}') where trade_date<'2022-01-01' window w as(partition by symbol order by trade_date)")
 c.execute('create temp table m as select trade_date,avg(r) market_return from r group by 1');c.execute('create temp table b as select symbol,trade_date,covar_samp(r,market_return) over w/nullif(var_samp(market_return) over w,0) beta60 from r join m using(trade_date) window w as(partition by symbol order by trade_date rows between 59 preceding and current row)')
 c.register('sample_keys',f[['symbol','trade_date']]);beta=c.execute('select b.* from b join sample_keys using(symbol,trade_date)').fetchdf();f=f.merge(beta,on=['symbol','trade_date'])
 # Fixed triplet intercepts exactly absorb date and industry; residual controls are ranks for robustness.
 controls=['ret20','ret60','ret120','log_cap','log_adv20','vol60','beta60'];f=f.dropna(subset=controls)
 results=[]
 for year,g in [('ALL',f)]+[(str(y),z) for y,z in f.groupby('year')]:
  for d in dims:
   z=g.dropna(subset=[d]).copy();rank=z[controls].rank(pct=True);rank.index=z.index
   for name,cols in [('MATCHED_DATE_INDUSTRY',[]),('MOMENTUM',['ret20','ret60','ret120']),('SIZE_LIQUIDITY_VOL',['log_cap','log_adv20','vol60']),('ALL_STYLE_BETA',controls)]:
    x=z[d].astype(float);y=z.persistent_excess_score.astype(float)
    x=x-x.groupby(z.triplet_id).transform('mean');y=y-y.groupby(z.triplet_id).transform('mean')
    if cols:
     a=rank[cols];a=a-a.groupby(z.triplet_id).transform('mean');a=a.to_numpy();x=x-np.linalg.lstsq(a,x,rcond=None)[0]@a.T;y=y-np.linalg.lstsq(a,y,rcond=None)[0]@a.T
    results.append(dict(year=year,dimension=d,control=name,n=len(z),residual_correlation=x.corr(y),status='VISUAL_DIAGNOSTIC_ONLY_NOT_QUANTITATIVE_ALPHA'))
   # Same-date/industry label permutation inside each triplet, descriptive placebo.
   xx=z[d].to_numpy();yy=z.persistent_excess_score.to_numpy();groups=[a for a in z.reset_index(drop=True).groupby('triplet_id').indices.values()];ics=[]
   for _ in range(250):
    shuffled=yy.copy()
    for a in groups:shuffled[a]=rng.permutation(yy[a])
    ics.append(pd.Series(xx).corr(pd.Series(shuffled),method='spearman'))
   results.append(dict(year=year,dimension=d,control='RANDOM_WITHIN_DATE_INDUSTRY_TRIPLET',n=len(z),residual_correlation=pd.Series(xx).corr(pd.Series(yy),method='spearman'),null_lo=np.quantile(ics,.025),null_hi=np.quantile(ics,.975),status='DESCRIPTIVE_PLACEBO_NOT_PVALUE_GATE'))
 pd.DataFrame(results).to_csv(q/'negative_controls.csv',index=False)
 market=pd.read_parquet(EXT/'panel/discovery_market_context.parquet');print('market context columns',market.columns.tolist())
 market=market[['trade_date','market_regime']].drop_duplicates('trade_date');f=f.merge(market,on='trade_date',how='left');rows=[]
 for dim in dims:
  for statecol in ['market_regime','participation']:
   for state,z in f.groupby(statecol):
    rows.append(dict(dimension=dim,state_type=statecol,state=state,n=len(z),winner_minus_loser=z.loc[z.label.eq('WINNER'),dim].mean()-z.loc[z.label.eq('LOSER'),dim].mean(),rank_ic=z[dim].corr(z.persistent_excess_score,method='spearman'),status='VISUAL_DIAGNOSTIC_ONLY'))
 pd.DataFrame(rows).to_csv(q/'discovery_regime_results.csv',index=False)
 print(pd.read_csv(p/'paired_visual_diagnostics.csv').round(4).to_string(index=False));print(pd.DataFrame(results).query("year=='ALL' and control=='ALL_STYLE_BETA'").round(4).to_string(index=False))
if __name__=='__main__':main()
