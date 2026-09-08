"""Reveal discovery labels only after their committed hash exists."""
import json,subprocess,shutil
import numpy as np,pandas as pd
from .build import HERE,EXT,DAILY,setup,sha,js

def main():
 p=HERE/'visual';receipt=json.loads((p/'formal_labels_freeze.json').read_text())
 for n,h in receipt['files'].items():assert sha(p/n)==h
 subprocess.run(['git','cat-file','-e','eb8873f13b:research/sixth_alpha_visual_discovery_v1/visual/formal_labels_freeze.json'],check=True)
 labels=pd.read_csv(p/'formal_visual_labels.csv');dims=list(labels.columns[2:]);s=pd.read_parquet(EXT/'visual/sealed_outcome_map.parquet');assert pd.to_datetime(s.trade_date).max()<pd.Timestamp('2022-01-01')
 dup=pd.read_parquet(EXT/'visual/sealed_duplicates.parquet');a=dup.merge(labels,on='blind_id').merge(labels,left_on='original_id',right_on='blind_id',suffixes=('_repeat','_original'))
 rows=[]
 for d in dims:
  x=a[d+'_original'];y=a[d+'_repeat'];ok=x.notna()&y.notna();rows.append(dict(dimension=d,n=int(ok.sum()),exact=(x[ok]==y[ok]).mean(),within1=((x[ok]-y[ok]).abs()<=1).mean(),spearman=x[ok].corr(y[ok],method='spearman'),missing_pair_fraction=1-ok.mean()))
 pd.DataFrame(rows).to_csv(p/'visual_repeatability.csv',index=False)
 c=setup();c.register('samples',s[['symbol','trade_date','cal_idx','coord_close','invalid_step_cum']]);c.execute(f"create temp table raw as select symbol,trade_date,cal_idx,coord_close,coord_high,coord_low,invalid_step_cum from read_parquet('{DAILY}') where trade_date<'2022-01-01'")
 path=c.execute('''select s.symbol,s.trade_date,d.cal_idx-s.cal_idx h,d.coord_high/s.coord_close-1 hi,d.coord_low/s.coord_close-1 lo,d.coord_close/s.coord_close equity,d.invalid_step_cum=s.invalid_step_cum legal from samples s join raw d on s.symbol=d.symbol and d.cal_idx between s.cal_idx+1 and s.cal_idx+60 order by 1,2,3''').fetchdf()
 paths=[]
 for (symbol,date),g in path.groupby(['symbol','trade_date']):
  row=dict(symbol=symbol,trade_date=date)
  for h in [20,40,60]:
   z=g.loc[g.h<=h];ok=len(z)==h and z.legal.all();eq=np.r_[1,z.equity.to_numpy()];dd=(eq/np.maximum.accumulate(eq)-1).min()
   row.update({f'mfe{h}':z.hi.max() if ok else np.nan,f'mae{h}':z.lo.min() if ok else np.nan,f'future_dd{h}':dd if ok else np.nan})
  paths.append(row)
 s=s.merge(pd.DataFrame(paths),on=['symbol','trade_date'],validate='one_to_one');s.to_parquet(EXT/'visual/revealed_discovery_sample.parquet',index=False)
 f=s.loc[s.stage.eq('formal')].merge(labels,on='blind_id',validate='one_to_one');f['year']=f.trade_date.dt.year;f.to_csv(p/'formal_labels_revealed.csv',index=False,columns=['blind_id','triplet_id','symbol','trade_date','year','label','participation']+dims+['ir20','ir40','ir60','persistent_excess_score','mfe60','mae60','future_dd60'])
 means=[];dist=[];buckets=[];spreads=[]
 for year,g in [('ALL',f)]+[(str(y),v) for y,v in f.groupby('year')]:
  for d in dims:
   for label,z in g.groupby('label'):
    means.append(dict(year=year,dimension=d,label=label,n=len(z),valid=z[d].notna().sum(),mean=z[d].mean(),median=z[d].median(),std=z[d].std()))
    for score,n in z[d].value_counts(dropna=False).items():dist.append(dict(year=year,dimension=d,label=label,score=score,n=n,fraction=n/len(z)))
   w=g.loc[g.label.eq('WINNER'),d];l=g.loc[g.label.eq('LOSER'),d];spreads.append(dict(year=year,dimension=d,winner_minus_loser=w.mean()-l.mean(),rank_ic=g[d].corr(g.persistent_excess_score,method='spearman')))
   for score,z in g.groupby(d):
    row=dict(year=year,dimension=d,score=score,n=len(z));row.update(z[['ir20','ir40','ir60','persistent_excess_score','mfe20','mfe40','mfe60','mae20','mae40','mae60','future_dd60']].mean().to_dict());buckets.append(row)
 for name,rows in [('visual_outcome_means',means),('visual_outcome_distributions',dist),('visual_score_response',buckets),('visual_year_spreads',spreads)]:pd.DataFrame(rows).to_csv(p/(name+'.csv'),index=False)
 shutil.copyfile(EXT/'visual/winner_control_triplets_SEALED.csv',p/'winner_control_triplets.csv')
 js(p/'outcome_reveal_receipt.json',{'labels_freeze_commit':'eb8873f13b','outcomes_max_date':str(s.trade_date.max()),'formal_primary':len(f),'repeat_pairs':len(a),'2022_outcomes_opened':False})
 print(pd.read_csv(p/'visual_repeatability.csv').to_string(index=False));print(pd.DataFrame(spreads).pivot(index='dimension',columns='year',values='winner_minus_loser').round(3).to_string())
if __name__=='__main__':main()
