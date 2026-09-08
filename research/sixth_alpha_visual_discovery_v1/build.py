"""Bounded discovery-only preparation; never print sealed case identities."""
from pathlib import Path
import hashlib,json,os,subprocess
import duckdb,numpy as np,pandas as pd
HERE=Path(__file__).resolve().parent
EXT=Path('/Volumes/quant/CY_quant_research/sixth_alpha_visual_discovery_v1')
PARENT=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-capital-admission-v1')
CACHE=Path('/Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1/research/scaling_regime_v1/cache')
DAILY=CACHE/'daily_with_snapshot.parquet'
OPS=PARENT/'research/portfolio_closure_v1/output/precapital_opportunities_v2.csv.gz'
SEED=20260909

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
def js(p,o):p.write_text(json.dumps(o,indent=2,ensure_ascii=False,default=str)+'\n')
def setup():
 assert os.path.ismount('/Volumes/quant')
 for d in ['coverage','visual','panel','tmp']: (EXT/d).mkdir(parents=True,exist_ok=True)
 c=duckdb.connect();c.execute('SET threads=4');c.execute("SET memory_limit='3GB'");c.execute(f"SET temp_directory='{EXT}/tmp'")
 return c

def coverage(c):
 # Project causal columns only: no realized-return or funding amounts enter coverage.
 cols=['strategy','route','event_id','parent_event_id','symbol','decision_at','signal_at','legal_opportunity','actual_funding_status']
 op=pd.read_csv(OPS,usecols=cols);op=op.loc[op.strategy.ne('SMV6') & op.legal_opportunity].copy()
 atr=pd.read_parquet(CACHE/'atrdr/precapital_entry_population.parquet',columns=['event_id','lane'])
 op=op.merge(atr,on='event_id',how='left',validate='many_to_one')
 op['family']=op.strategy
 op.loc[op.strategy.eq('ATRDR'),'family']=np.where(op.loc[op.strategy.eq('ATRDR'),'route'].eq('BULL'),'ATRDR_BULL',np.where(op.loc[op.strategy.eq('ATRDR'),'lane'].str.contains('SLOW',na=False),'ATRDR_SLOW_BEAR','ATRDR_FAST_BEAR'))
 op['trade_date']=pd.to_datetime(op.decision_at).dt.normalize()
 c.register('op',op)
 names=['ATRDR_BULL','ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR','IFCGR']
 fields=','.join(f"bool_or(family='{s}') AS {s}" for s in names)
 c.execute(f"create temp table covered as select symbol,trade_date,{fields},bool_or(actual_funding_status='UNFUNDED') as has_unfunded_opportunity from op group by 1,2")
 c.execute(f"""COPY (SELECT d.symbol,d.trade_date,d.sleeve,d.causal_industry,d.industry_valid,
  {','.join(f'coalesce(c.{s},false) as {s}' for s in names)},coalesce(c.has_unfunded_opportunity,false) has_unfunded_opportunity,
  c.symbol is null as uncovered FROM read_parquet('{DAILY}') d LEFT JOIN covered c USING(symbol,trade_date)
  WHERE d.trade_date>='2018-01-01' AND d.current_valid AND d.hard_valid AND NOT d.is_st
  AND d.current_day_data_tradable AND d.sleeve IN ('MAIN','CHINEXT'))
  TO '{EXT}/coverage/five_strategy_coverage_map.parquet' (FORMAT PARQUET)""")
 # Only discovery summaries visible before freeze.
 c.execute(f"""COPY (select year(trade_date) calendar_year,sleeve,count(*) stock_dates,sum(uncovered::int) uncovered_stock_dates,
 avg(uncovered::int) uncovered_fraction,sum(has_unfunded_opportunity::int) covered_unfunded_dates
 from read_parquet('{EXT}/coverage/five_strategy_coverage_map.parquet') where trade_date<'2022-01-01'
 group by 1,2 order by 1,2) TO '{HERE}/coverage/coverage_summary.csv' (HEADER)""")
 # Save lineage separately, before any outcome joins. OGR/IFCGR flags are unioned, never summed.
 op.drop(columns=['actual_funding_status']).to_parquet(EXT/'coverage/causal_opportunity_lineage.parquet',index=False)
 assert not c.execute('select count(*) from covered where has_unfunded_opportunity and not ('+' OR '.join(names)+')').fetchone()[0]

def panel(c):
 # SQL WHERE precedes every history/lead computation, including late-2021 labels.
 c.execute(f"create temp table raw as select * from read_parquet('{DAILY}') where trade_date<'2022-01-01'")
 c.execute('''create temp table hist as select *,lag(coord_close) over w pc,lag(cal_idx) over w pi,
 lag(coordinate_factor) over w pf,lag(history_valid) over w pv,
 lag(coord_close,20) over w p20,lag(coord_close,60) over w p60,lag(coord_close,120) over w p120,
 lag(cal_idx,120) over w i120,
 min(history_valid::int) over(partition by symbol order by trade_date rows between 249 preceding and current row) valid250,
 count(*) over(partition by symbol order by trade_date rows between 249 preceding and current row) n250,
 lag(cal_idx,249) over w i250,
 avg(amount) over(partition by symbol order by trade_date rows between 19 preceding and current row) adv20
 from raw window w as(partition by symbol order by trade_date)''')
 checks=c.execute('''select count(*) filter(where abs(close*coordinate_factor-coord_close)>1e-7),
 count(*) filter(where history_valid and pv and abs(coordinate_factor/pf-1)>1e-9 and corporate_action_count=0),
 count(*) filter(where available_at>decision_at) from hist''').fetchone(); assert checks==(0,0,0),checks
 js(HERE/'output/coordinate_checks.json',dict(raw_coordinate_mismatch=checks[0],unexplained_valid_factor_changes=checks[1],late_available_rows=checks[2]))
 leads=[]
 for h in [5,10,20,40,60]:
  leads += [f"case when lead(cal_idx,{h}) over w=cal_idx+{h} and lead(invalid_step_cum,{h}) over w=invalid_step_cum then lead(coord_close,{h}) over w/coord_close-1 end r{h}"]
 c.execute('''create temp table base as select *,coord_close/p20-1 ret20,coord_close/p60-1 ret60,coord_close/p120-1 ret120,
 stddev_samp(case when pi=cal_idx-1 and history_valid and pv then coord_close/pc-1 end)
 over(partition by symbol order by trade_date rows between 59 preceding and current row) vol60,
 '''+','.join(leads)+''' from hist window w as(partition by symbol order by trade_date)''')
 c.execute(f'''create temp table eligible as select b.* from base b join read_parquet('{EXT}/coverage/five_strategy_coverage_map.parquet') c using(symbol,trade_date) where trade_date>='2018-01-01' ''')
 rel=[]
 for h in [5,10,20,40,60]:
  rel.extend([f"r{h}-(sum(r{h}) over(partition by trade_date,causal_industry)-r{h})/nullif(count(r{h}) over(partition by trade_date,causal_industry)-1,0) ir{h}",f"r{h}-(sum(r{h}) over(partition by trade_date)-r{h})/nullif(count(r{h}) over(partition by trade_date)-1,0) mr{h}"])
 c.execute('create temp table relative as select *, '+','.join(rel)+',avg((ret20>0)::int) over(partition by trade_date) breadth from eligible where industry_valid')
 c.execute(f'''create temp table uncovered as select r.* from relative r join read_parquet('{EXT}/coverage/five_strategy_coverage_map.parquet') c using(symbol,trade_date) where c.uncovered''')
 c.execute('create temp table ranks as select *, '+','.join(f'percent_rank() over(partition by trade_date order by ir{h}) q{h}' for h in [20,40,60])+' from uncovered where ir20 is not null and ir40 is not null and ir60 is not null')
 c.execute("create temp table scored as with a as(select *,list_median([q20,q40,q60]) persistent_excess_score from ranks) select *,percent_rank() over(partition by trade_date order by persistent_excess_score) persistent_rank from a")
 c.execute(f"copy scored to '{EXT}/panel/discovery_scored.parquet' (format parquet)")
 # Breadth regimes: expanding, current information only; 2018 warm-start uses observed prefix.
 breadth=c.execute('select distinct trade_date,breadth from relative order by trade_date').fetchdf()
 q=breadth.breadth.expanding().rank(pct=True);breadth['participation']=np.select([q<=1/3,q<=2/3],['LOW','MID'],default='HIGH')
 breadth.to_parquet(EXT/'panel/discovery_breadth.parquet',index=False)
 print('Discovery panel written; sealed outcomes not displayed.',flush=True)

def size(c):
 m=Path('/Users/linmei/Documents/CY/data/input_inventories/CY-006-pit-b-daily-v2-2018-2026-20260821.json');d=json.loads(m.read_text());paths=[];checks=[]
 for row in d['files']:
  if any('partition_year='+str(y)+'/' in row['path'] for y in range(2018,2022)):
   p=Path(d['root'])/row['path'];h=sha(p);assert h==row['sha256'];paths.append(str(p));checks.append(dict(path=str(p),sha256=h))
 c.read_parquet(paths).create_view('size_source')
 assert c.execute('select count(*) from size_source where hard_valid and float_valid and (available_at>decision_at or float_available_date>trade_date)').fetchone()[0]==0
 c.execute(f"copy (select symbol,trade_date,close*circulating_shares circulating_market_value from size_source where hard_valid and float_valid and circulating_shares>0 and close>0) to '{EXT}/panel/discovery_size.parquet' (format parquet)")
 js(HERE/'output/size_source_identity.json',dict(manifest=str(m),manifest_sha256=sha(m),inputs=checks,qualification='PIT_B_CAUSAL_RESEARCH',semantics='circulating market value',late_available_rows=0))

def sample(c):
 df=pd.read_parquet(EXT/'panel/discovery_scored.parquet')
 size=pd.read_parquet(EXT/'panel/discovery_size.parquet');size['trade_date']=pd.to_datetime(size.trade_date);df=df.merge(size,on=['symbol','trade_date'],validate='one_to_one')
 df=df.loc[df.valid250.eq(1)&df.n250.eq(250)&df.cal_idx.sub(df.i250).eq(249)].copy()
 df['label']=np.select([(df.persistent_rank>=.85)&((df[['q20','q40','q60']]>.7).sum(axis=1)>=2),df.persistent_rank.between(.45,.55),(df.persistent_rank<=.15)&((df[['q20','q40','q60']]<.3).sum(axis=1)>=2)],['WINNER','NEUTRAL','LOSER'],default='')
 df=df.loc[df.label.ne('')].merge(pd.read_parquet(EXT/'panel/discovery_breadth.parquet')[['trade_date','participation']],on='trade_date')
 df['log_adv20']=np.log(df.adv20.where(df.adv20>0));df['log_cap']=np.log(df.circulating_market_value);features=['log_cap','log_adv20','ret20','ret60','vol60']
 df=df.dropna(subset=features)
 for f in features:
  df['z_'+f]=df.groupby('trade_date')[f].transform(lambda s:(s-s.mean())/s.std())
 z=['z_'+f for f in features]; rng=np.random.default_rng(SEED); triples=[]; used={};trip=0
 cells={k:g for k,g in df.groupby(['trade_date','causal_industry'],sort=False)}
 for year in range(2018,2022):
  for part in ['LOW','MID','HIGH']:
   wins=df.loc[df.trade_date.dt.year.eq(year)&df.participation.eq(part)&df.label.eq('WINNER')]
   count=0
   for idx in rng.permutation(wins.index):
    w=df.loc[idx];day=w.cal_idx
    if any(abs(day-x)<120 for x in used.get(w.symbol,[])):continue
    g=cells[(w.trade_date,w.causal_industry)];members=[w];dist=[]
    for label in ['NEUTRAL','LOSER']:
     cand=g.loc[g.label.eq(label)].copy()
     cand=cand.loc[[not any(abs(day-x)<120 for x in used.get(s,[])) for s in cand.symbol]]
     if cand.empty:break
     delta=cand[z].to_numpy(float)-w[z].to_numpy(float);ds=np.sqrt((delta**2).sum(axis=1));pos=int(np.argmin(ds));members.append(cand.iloc[pos]);dist.append(float(ds[pos]))
    if len(members)!=3:continue
    trip+=1
    for m in members:
     rec=m.to_dict();rec.update(triplet_id=trip,match_neutral_distance=dist[0],match_loser_distance=dist[1]);triples.append(rec);used.setdefault(m.symbol,[]).append(day)
    count+=1
    if count==20:break
   print('Sample cell',year,part,count,'triplets',flush=True)
 s=pd.DataFrame(triples);assert len(s)>0 and len(s)<=720
 # Stage membership balanced per year/participation before blind random assignment.
 ts=s.drop_duplicates('triplet_id');open_ids=[]
 for _,g in ts.groupby([ts.trade_date.dt.year,'participation']):open_ids+=rng.permutation(g.triplet_id)[:5].tolist()
 s['stage']=np.where(s.triplet_id.isin(open_ids),'open','formal')
 s=s.iloc[rng.permutation(len(s))].reset_index(drop=True);pool=rng.permutation(np.arange(1,len(s)+round(.15*int(s.stage.eq('formal').sum()))+1));s['blind_id']=[f'CASE_{i:06d}' for i in pool[:len(s)]]
 s.to_parquet(EXT/'visual/sealed_outcome_map.parquet',index=False)
 # User-requested matching manifest is also sealed until labels frozen, to avoid reconstructing triplets.
 s[['blind_id','triplet_id','symbol','trade_date','label','match_neutral_distance','match_loser_distance']].to_csv(EXT/'visual/winner_control_triplets_SEALED.csv',index=False)
 order=s[['blind_id','stage']].copy();dup=s.loc[s.stage.eq('formal')].sample(frac=.15,random_state=SEED).copy()
 dup['original_id']=dup.blind_id;dup['blind_id']=[f'CASE_{i:06d}' for i in pool[len(s):]]
 dup[['blind_id','original_id']].to_parquet(EXT/'visual/sealed_duplicates.parquet',index=False)
 order=pd.concat([order,dup[['blind_id','stage']]]).sample(frac=1,random_state=SEED).reset_index(drop=True)
 order.to_csv(HERE/'visual/blind_order.csv',index=False)
 js(HERE/'visual/blinding_manifest.json',dict(seed=SEED,triplets=trip,primary_charts=len(s),repeatability_charts=len(dup),open_charts=int(s.stage.eq('open').sum()),formal_charts=int(s.stage.eq('formal').sum()),sealed_map_sha256=sha(EXT/'visual/sealed_outcome_map.parquet'),operational_blinding=True,outcomes_opened=False,matching_features=features,missing_matching_covariates=[],size_semantics='circulating market value, not total or free-float cap',parent_industry_fallback=False,overlap_spacing=120))
 print('Blind sample complete',len(s),'primary cases; no case outcomes printed.',flush=True)

if __name__=='__main__':
 import sys
 c=setup()
 for step in sys.argv[1:]:globals()[step](c)
