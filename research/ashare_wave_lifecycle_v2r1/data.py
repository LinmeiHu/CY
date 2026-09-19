"""Bounded daily observed-identity universe, causal coordinates; no inferred action facts."""
import sys
import pandas as pd
from numba import njit
from common import *

@njit(cache=True)
def coordinates(c,o,h,l,pc,m,cash,valid,volume):
 n,k=c.shape; factor=np.full((n,k),np.nan); sharefactor=factor.copy(); coordok=valid.copy()
 for j in range(k):
  f=1.; shares=1.
  for t in range(n):
   if not valid[t,j]: f=1.;shares=1.;continue
   if t==0 or not valid[t-1,j]:f=1.;shares=1.
   elif m[t,j]!=1 or cash[t,j]!=0:
    ref=(c[t-1,j]-cash[t,j])/m[t,j]
    if ref<=0 or abs(ref-pc[t,j])>max(.02,abs(ref)*.002):
     coordok[t,j]=False;f=1.;shares=1.;continue
    f*=c[t-1,j]/ref;shares*=m[t,j]
   factor[t,j]=f;sharefactor[t,j]=shares
 return factor,sharefactor,coordok

def rolling(a,n,fn='mean'):
 return getattr(pd.DataFrame(a).rolling(n,min_periods=n),fn)().to_numpy(dtype=np.float32)

def main():
 OUT.mkdir(exist_ok=True,parents=True)
 old=HERE.parent/'ashare_wave_structure_v1'; manifest=json.loads((old/'INPUT_MANIFEST.json').read_text())
 meta=json.loads((SOURCE/'axes.json').read_text());dates=meta['dates'];syms=meta['symbols'];shape=(len(dates),len(syms))
 # Verify actual reused arrays and old reports without changing their seals.
 refs=[]
 for folder in ['ashare_wave_structure_v1','ashare_selective_wave_parsing_v2','ashare_wave_adaptive_path_v3']:
  p=HERE.parent/folder/'DELIVERY_MANIFEST.json'
  if p.exists():
   for x in json.loads(p.read_text())['files']:
    q=Path(x['path'])
    if q.is_file():
     assert sha(q)==x['sha256'],q;refs.append({'path':str(q),'sha256':x['sha256']})
 nums=['open','high','low','close','preclose','volume','amount','turnover_fraction','circulating_shares','share_multiplier','cash_per_share']
 flags=['hard_valid','historical_identity_valid','buy_blocked_open','sell_blocked_open','is_st','corporate_action_blocking','trading_state_valid']
 arrays={x:np.full(shape,np.nan) for x in nums}; arrays.update({x:np.zeros(shape,bool) for x in flags})
 status=np.zeros(shape,np.int8);available=np.zeros(shape,np.int64);industry=np.full(shape,-1,np.int16)
 industries=meta['industries']; source_rows=[];lineage=[]
 cols=nums+flags+['trade_date','symbol','trade_status','available_at','decision_at','snapshot_id','industry','rights_ratio']
 for b in manifest['source_bindings']:
  assert sha(b['path'])==b['sha256'];df=pd.read_parquet(b['path'],columns=cols)
  ti=pd.Index(dates).get_indexer(pd.to_datetime(df.trade_date).dt.strftime('%Y-%m-%d'));ji=pd.Index(syms).get_indexer(df.symbol)
  assert (ti>=0).all() and (ji>=0).all();assert not pd.MultiIndex.from_arrays([ti,ji]).has_duplicates
  assert df.snapshot_id.notna().all() and df.available_at.notna().all()
  assert (df.available_at<=df.decision_at).all()
  for x in nums:arrays[x][ti,ji]=df[x]
  for x in flags:arrays[x][ti,ji]=df[x].fillna(x in ['is_st','buy_blocked_open','sell_blocked_open','corporate_action_blocking'])
  status[ti,ji]=df.trade_status.fillna(0);available[ti,ji]=pd.to_datetime(df.available_at).astype('int64')
  industry[ti,ji]=df.industry.map(industries).fillna(-1).astype('int16')
  source_rows.append(dict(year=str(df.trade_date.iloc[0])[:4],rows=len(df),hard_valid=int(df.hard_valid.sum()),action_rows=int((df.cash_per_share.gt(0)|df.share_multiplier.ne(1)).sum())))
  lineage.append(df[['trade_date','symbol','available_at','snapshot_id']])
  print('verified daily',source_rows[-1],flush=True)
 # Snapshot ancestry establishes first known identity only; daily eligibility is reconstructed independently.
 parent=json.loads((HERE.parent/'stock_predictability_v1/UNIVERSE_QUALIFIED_MANIFEST.json').read_text())
 first=np.full(shape[1],shape[0],np.int32); snapshot_rows=[]
 for r in parent['records']:
  assert sha(r['path'])==r['sha256'];x=json.loads(Path(r['path']).read_text());assert x['error_code']=='0'
  ids=[]
  for row in x['rows']:
   d=dict(zip(x['fields'],row));s=d['code'];s=s[3:]+'.'+s[:2].upper()
   if s in syms:ids.append(s)
  js=pd.Index(syms).get_indexer(ids);t=dates.index(r['date']);first[js]=np.minimum(first[js],t)
  snapshot_rows.append(dict(t=t,count=len(js)))
 valid=arrays['hard_valid']&~arrays['corporate_action_blocking']
 for x in ['open','high','low','close','preclose']:valid &= np.isfinite(arrays[x])&(arrays[x]>0)
 valid &= np.isfinite(arrays['share_multiplier'])&np.isfinite(arrays['cash_per_share'])
 factor,sharefactor,coordok=coordinates(*[arrays[x] for x in ['close','open','high','low','preclose','share_multiplier','cash_per_share']],valid,arrays['volume'])
 save=lambda k,v:np.save(OUT/(k+'.npy'),v)
 for x in nums:save(x,arrays[x])
 for x in ['close','open','high','low']:save('adj_'+x,arrays[x]*factor)
 save('adj_volume',arrays['volume']/sharefactor);save('factor',factor);save('coordok',coordok)
 eligible=coordok&arrays['historical_identity_valid']&arrays['trading_state_valid']&(status==1)&~arrays['is_st']&(np.arange(shape[0])[:,None]>=first)
 entry=eligible&~arrays['buy_blocked_open'];ex=coordok&arrays['trading_state_valid']&(status==1)&~arrays['sell_blocked_open']
 for k,v in [('eligible',eligible),('entryok',entry),('exitok',ex),('industry',industry),('available',available),('first_identity',first)]:save(k,v)
 # Prior warm-up may not straddle a coordinate/eligibility reset.
 sys.path.insert(0,str(old));from engine import streak
 history=streak(eligible);save('history',history)
 c=arrays['close']*factor;h=arrays['high']*factor;l=arrays['low']*factor
 prev=np.vstack([np.full((1,shape[1]),np.nan),c[:-1]])
 tr=np.maximum(h-l,np.maximum(abs(h-prev),abs(l-prev)))/prev
 atr=rolling(tr,20);save('atr',np.vstack([np.full((1,shape[1]),np.nan),atr[:-1]]))
 ret=c/prev-1;save('vol20',rolling(ret,20,'std'))
 for n in [3,20,60]:
  r=np.full(shape,np.nan,np.float32);r[n:]=c[n:]/c[:-n]-1;r[history<=n]=np.nan;save('ret'+str(n),r)
 save('ma5',rolling(c,5));save('drawdown20',c/rolling(c,20,'max')-1)
 save('prior_high5',np.vstack([np.full((1,shape[1]),np.nan),rolling(c,5,'max')[:-1]]))
 save('turnover20',rolling(arrays['turnover_fraction'],20));save('logamount20',np.log(rolling(arrays['amount'],20)))
 save('logcap',np.log(arrays['close']*arrays['circulating_shares']))
 ir=np.full(shape,np.nan,np.float32)
 for t in range(shape[0]):
  ok=eligible[t]&np.isfinite(ret[t])&(industry[t]>=0);ids=industry[t,ok]
  count=np.bincount(ids,minlength=len(industries));sums=np.bincount(ids,weights=ret[t,ok],minlength=len(industries))
  means=np.divide(sums,count,out=np.full(len(count),np.nan),where=count>0);ir[t,industry[t]>=0]=means[industry[t,industry[t]>=0]]
 # Industry path follows the subject's contemporaneous industry; missing days propagate.
 save('industry20',np.exp(rolling(np.log1p(ir),20,'sum'))-1)
 market=np.load(SOURCE/'market.npy');save('market',market)
 for n in [20,60]:
  r=np.full(shape[0],np.nan);r[n:]=market[n:,3]/market[:-n,3]-1;save('market'+str(n),r)
 save('breadth',np.sum(eligible&(get('ret20')>0),axis=1)/np.maximum(eligible.sum(axis=1),1))
 (OUT/'axes.json').write_text(json.dumps(meta,ensure_ascii=False))
 pd.concat(lineage).to_parquet(OUT/'source_lineage.parquet',index=False)
 pd.DataFrame(source_rows).to_csv(HERE/'DATA_COVERAGE.csv',index=False)
 dump('INPUT_MANIFEST.json',dict(created_at=now(),asset_id='CY-WAVE-LIFECYCLE-V2R1',protocol_sha256=sha(HERE/'PROTOCOL.md'),source_bindings=manifest['source_bindings'],parent_identity_manifest=parent['asset_id'],parent_identity_sha256=sha(HERE.parent/'stock_predictability_v1/UNIVERSE_QUALIFIED_MANIFEST.json'),shape=shape,dates=[dates[0],dates[-1]],pit_grade='B',eligible_stock_days=int(eligible.sum()),warm_stock_days=int((eligible&(history>=60)).sum()),coordinate_rejections=int((valid&~coordok).sum()),scope='SH/SZ first-asof-identity-admitted and directly observed daily valid rows; not complete daily historical market',arrays=[dict(path=str(p),sha256=sha(p)) for p in sorted(OUT.glob('*.npy'))],old_frozen_files=refs))
 print('DATA COMPLETE',shape,int(eligible.sum()),flush=True)
if __name__=='__main__':main()
