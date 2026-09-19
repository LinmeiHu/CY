"""Frozen2020 current Alpha: pre2020 Train-only daily materialization, resumable."""
import os,json,ast,fcntl,traceback,subprocess,gc,inspect,pickle
from pathlib import Path
import numpy as np,pandas as pd,torch,joblib,duckdb
from common import HERE,OUT,PANEL,get,sha,now,old
from account_daily_inference import stock_inputs
import train_fit_cycle as reuse
from train import PathResidual
D=HERE/'account_diversification_v1/alpha_held_risk_v2';B=OUT/'account_diversification_v1/alpha_held_risk_v2';B.mkdir(exist_ok=True);D.mkdir(exist_ok=True)
def write(p,x):
 p=Path(p);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(x,indent=2,ensure_ascii=False,default=str));tmp.replace(p)
def state(**kw):
 p=D/'STATE.json';s=json.loads(p.read_text()) if p.exists() else {};s.update(at=now(),**kw);write(p,s)
 u=D.parent/'UNIFIED_DAG_STATE.json';z=json.loads(u.read_text());z.update(status=s['status'],phase='CURRENT_ALPHA_TRAIN_DIAGNOSTIC_BUILD',child_pid=s.get('pid'),child_birth=s.get('birth'),current_task=s.get('task'),active_state=str(p),research_terminal=False,blocking_error=s.get('error'),next=s.get('next'));write(u,z)
def identity():
 bindings=json.loads((D.parent/'READOUT_PROMOTION_PROTOCOL.json').read_text())['bindings'];refs=[];mods={};branches={};m0p=OUT/'M0_CONTEXT_2020.joblib';m0sha=sha(m0p)
 for seed in [17,29,43]:
  r=next(x for x in bindings if x['year']==2020 and x['seed']==seed);cp=Path(r['checkpoint_path']);assert sha(cp)==r['checkpoint_sha256'];ck=torch.load(cp,map_location='cpu',weights_only=False);assert ck['step']==32768 and ck['base_sha256']==m0sha
  archived=OUT/'code_snapshots'/(ck['code_sha256']+'_train.py');assert sha(archived)==ck['code_sha256']
  cl=lambda p:ast.dump(next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='PathResidual'),include_attributes=False)
  assert cl(archived)==cl(HERE/'train.py')
  bp=reuse.DEST/f'centered_branch_numerical_repair/2020_s{seed}/BRANCH.joblib';br=joblib.load(bp);assert br['converged'] and br['checkpoint_sha256']==r['checkpoint_sha256'];branches[seed]=br
  m=PathResidual(ck['config']);m.load_state_dict(ck['state']);mods[seed]=m.to('mps').eval()
  refs.append(dict(seed=seed,checkpoint=str(cp),checkpoint_sha=r['checkpoint_sha256'],source_sha=ck['code_sha256'],cutoff=ck['cutoff'],branch=str(bp),branch_sha=sha(bp),M0=str(m0p),M0_sha=m0sha))
 spec=dict(name='CURRENT_ALPHA_TRAIN_DIAGNOSTIC_ONLY',ALPHA_LAYER_OOS=False,PRODUCTION_EVIDENCE=False,RISK_MECHANISM_SAMPLE='TRAIN_DIAGNOSTIC',bindings=refs,features_sha=sha(HERE/'FEATURES.json'),input_builder_sha=sha(HERE/'account_daily_inference.py'),authorization_sha=sha('/Users/linmei/.codex/attachments/fe52253f-07db-45ae-973b-be4166033f16/pasted-text.txt'),end='2019-12-31',eligibility='latest historical membership <=t AND safe[t] AND history[t]>=60; no label selection',centering='float64 all eligible each t; same frozen scaler/theta; correction mean zero',consensus='average average-tie percentile ranks, raw mean>0, j tiebreak',account='original entitlement-boundary H20, daily5%, perlot0.5%, max10 planned, aggregate10%; no risk layer')
 p=D/'BUILD_IDENTITY.json'
 if p.exists():assert json.loads(p.read_text())==spec
 else:write(p,spec)
 return mods,branches,joblib.load(m0p)
def inference(meta):
 mods,branches,m0=identity();seal=sha(D/'BUILD_IDENTITY.json');done=B/'INFERENCE_COMPLETE.json'
 if done.exists():assert json.loads(done.read_text())['identity_sha']==seal;return
 n=len(meta['dates']);dates=np.array(meta['dates']);ts,member=reuse.historical_membership(meta,n-1);a={k:get(k)[:n] for k in ['safe','history','adj_close','adj_open','adj_high','adj_low','adj_volume','close','circulating_shares','turnover_fraction','amount','industry_return','market']};valid=member&a['safe']&(a['history']>=60)
 js=np.flatnonzero(valid.any(0));mr=[]
 for h in [3,20,60]:
  v=np.full(n,np.nan);v[h:]=a['market'][h:,3]/a['market'][:-h,3]-1;mr.append(v)
 idx=pd.read_parquet(OUT/'index.parquet');idx=idx[idx.t<n];banks=[np.load(OUT/f'{k}.npy',mmap_mode='r') for k in ['raw','legs','factors']];offsetbank=np.load(OUT/'M0_CONTEXT_2020_offset.npy',mmap_mode='r');enc=old('features')
 sparse={};rr=None
 for s in mods:
  q=np.load(reuse.DEST/f'readout_promotion/2020_s{s}/TRAIN_EMBED.npz');sparse[s]=q;rr=q['rows']
 registered=pd.read_parquet(OUT/'index.parquet').iloc[rr].copy();registered['cache_row']=np.arange(len(rr));shards=B/'stock_inference';shards.mkdir(exist_ok=True);inputs=B/'inputs';inputs.mkdir(exist_ok=True)
 for no,j in enumerate(js):
  fp=shards/f'{j:05}.parquet';proof=fp.with_suffix('.json');tt=ts[valid[:,j]]
  if proof.exists():
   pr=json.loads(proof.read_text());assert pr['identity_sha']==seal and fp.stat().st_size==pr['bytes'];continue
  raw,legs,factors=stock_inputs(j,tt,a,mr,enc);common=idx[idx.j==j];pos=np.searchsorted(tt,common.t);assert np.array_equal(tt[pos],common.t)
  for bank,x in zip(banks,[raw,legs,factors]):assert np.array_equal(bank[common.index],x[pos],equal_nan=True),(int(j),'FEATURE_PARITY')
  off=np.column_stack([f.predict(m0['scale'].transform(np.nan_to_num(factors).astype('float64'))) for f in m0['fits']]).astype('float32');assert not len(pos) or np.max(abs(off[pos]-offsetbank[common.index]))<=2e-7
  if no==0:
   # Prefix replay proves later rows cannot change an earlier feature on this fixed sample.
   cut=int(tt[len(tt)//2]);ix=np.searchsorted(tt,cut);r,l,f=stock_inputs(j,np.array([cut]),{k:v[:cut+1] for k,v in a.items()},[v[:cut+1] for v in mr],enc)
   assert np.array_equal(r[0],raw[ix]) and np.array_equal(l[0],legs[ix]) and np.array_equal(f[0],factors[ix],equal_nan=True)
  ip=inputs/f'{j:05}.npz';np.savez_compressed(ip,t=tt,raw=raw,legs=legs,factors=factors,offset=off)
  output=pd.DataFrame(dict(t=tt,j=int(j),decision_date=dates[tt],year=[int(v[:4]) for v in dates[tt]],stock=meta['symbols'][j],eligibility=True));errors={}
  for s,m in mods.items():
   z=np.empty((len(tt),32),np.float32);p=np.empty(len(tt),np.float32)
   with torch.inference_mode():
    for lo in range(0,len(tt),512):
     hi=min(lo+512,len(tt));x=np.concatenate([raw[lo:hi].astype('float32'),np.broadcast_to(off[lo:hi,None,None,:],(hi-lo,4,32,3))],-1);pred,emb,_=m(torch.from_numpy(x).to('mps'),torch.from_numpy(legs[lo:hi].astype('float32')).to('mps'));p[lo:hi]=pred[:,1].cpu().numpy()/10;z[lo:hi]=emb.cpu().numpy()
   reg=registered[registered.j==j];ii=np.searchsorted(tt,reg.t);er=float(np.max(abs(p[ii]-sparse[s]['pred20'][reg.cache_row]))) if len(ii) else 0.;assert er<=2e-5,(int(j),s,er,'FORMAL_PREDICTION_PARITY');assert not len(ii) or np.allclose(z[ii],sparse[s]['embedding'][reg.cache_row],atol=2e-5,rtol=2e-4)
   errors[s]=er;output[f'F00_s{s}']=p
   for k in range(32):output[f's{s}_z{k}']=z[:,k]
  tmp=fp.with_suffix('.tmp');output.to_parquet(tmp,index=False);tmp.replace(fp);write(proof,dict(identity_sha=seal,sha256=sha(fp),bytes=fp.stat().st_size,rows=len(tt),feature_parity=True,formal_prediction_errors=errors,input_sha=sha(ip)))
  if no%25==0:state(status='RUNNING',task='FROZEN_FULL_DAILY_INFERENCE',stocks_done=no+1,stocks_total=len(js));print('INFER',no+1,len(js),flush=True)
 # Full eligible cross-section centering only after all stock shards are present.
 from signal_sprint_probes import centered
 con=duckdb.connect();con.execute('SET threads=1');con.execute("SET memory_limit='3GB'");years=B/'daily';years.mkdir(exist_ok=True)
 for year in range(2007,2020):
  fp=years/f'{year}.parquet'
  if fp.exists():continue
  f=con.execute('SELECT * FROM read_parquet(?) WHERE year=?',[str(shards/'*.parquet'),year]).df()
  if not len(f):continue
  for s,br in branches.items():
   z=f[[f's{s}_z{k}' for k in range(32)]].to_numpy();co=centered((br['scaler'].transform(centered(z,f.t))@br['theta'])[:,None],f.t).ravel();assert pd.Series(co).groupby(f.t).mean().abs().max()<=1e-10;f[f'correction_s{s}']=co;f[f'pred_s{s}']=f[f'F00_s{s}']+co;f[f'rank_s{s}']=f.groupby('t')[f'pred_s{s}'].rank(method='average',pct=True)
  f['consensus_rank']=f[[f'rank_s{s}' for s in mods]].mean(axis=1);f['final_prediction']=f[[f'pred_s{s}' for s in mods]].mean(axis=1);f['positive_gate']=f.final_prediction>0;f['Top10']=False
  selected=f[f.positive_gate].sort_values(['t','consensus_rank','j'],ascending=[True,False,True]).groupby('t').head(10).index;f.loc[selected,'Top10']=True
  f=f.drop(columns=[c for c in f if '_z' in c]);tmp=fp.with_suffix('.tmp');f.to_parquet(tmp,index=False);tmp.replace(fp);print('CENTERED_YEAR',year,len(f),flush=True)
 con.close();f=pd.concat([pd.read_parquet(p,columns=['t','j','consensus_rank','final_prediction','positive_gate']) for p in sorted(years.glob('*.parquet'))],ignore_index=True);q=f[f.positive_gate].rename(columns={'consensus_rank':'score','final_prediction':'pred20'});q['logamount20']=np.log(get('adv20')[q.t,q.j]);assert np.isfinite(q.logamount20).all();q.to_parquet(B/'SIGNALS.parquet',index=False)
 write(done,dict(identity_sha=seal,rows=len(f),dates=int(f.t.nunique()),first=dates[int(f.t.min())],last=dates[int(f.t.max())],signals_sha=sha(B/'SIGNALS.parquet'),ALPHA_LAYER_OOS=False));state(status='INFERENCE_COMPLETE',task='BUILD_PHYSICAL_TRAIN_ACCOUNT');del mods;gc.collect();torch.mps.empty_cache()
def accounts(meta):
 import entitlement_boundary_engine as e
 import entitlement_boundary as boundary
 import account_formation as af
 from verify_entitlement_v1 import verify_lots
 af.SYMBOLS=meta['symbols'];config=json.loads((D.parent/'GENERAL_ENTITLEMENT_INFRASTRUCTURE.json').read_text());boundary.REGISTRY=config['events'];a_path=OUT/'account_diversification_v1/held_action_value_v1/REGISTERED_ACTIONS_PRE2020.parquet';
 from alpha_train_timing import validate_asset,validate_prefix
 if (B/'REGISTERED_ACTIONS_PRE2020_TIMING_V1.parquet').exists():a_path=B/'REGISTERED_ACTIONS_PRE2020_TIMING_V1.parquet';actions=validate_asset(a_path)
 else:actions=pd.read_parquet(a_path)
 signals=pd.read_parquet(B/'SIGNALS.parquet');n=len(meta['dates']);market={k:get(k)[:n] for k in ['up_limit_price','limit_pct']}
 identity=dict(build=sha(D/'BUILD_IDENTITY.json'),signals=sha(B/'SIGNALS.parquet'),engine=sha(Path(e.__file__)),actions=sha(a_path));tp=B/'ACCOUNT_TREE.json'
 tree=json.loads(tp.read_text()) if tp.exists() else dict(identity=identity,nodes=[dict(id='ROOT',choices={},resume=None,status='PENDING')]);assert tree['identity']==identity
 for node in tree['nodes']:
  if node['status'] in ['COMPLETE','SPLIT']:continue
  policy='CURRENT_ALPHA_TRAIN_DIAGNOSTIC_ONLY_'+node['id'];rp=B/f"ACCOUNT_{node['id']}.json";snap=B/f"ACCOUNT_{node['id']}_NEXT.pkl";state(status='RUNNING',task=policy)
  if rp.exists():r=json.loads(rp.read_text());assert r['identity']==identity
  else:
   r=e.run(policy,signals,market,actions,meta['dates'],meta['symbols'],stagger=True,resume_path=node['resume'],snapshot_path=snap,entitlement_branch=node['choices']);r.update(identity=identity,ALPHA_LAYER_OOS=False,PRODUCTION_EVIDENCE=False,RISK_MECHANISM_SAMPLE='TRAIN_DIAGNOSTIC');write(rp,r)
  if r['status']=='ENTITLEMENT_BRANCH_REQUIRED':
   assert sum(x['status']!='SPLIT' for x in tree['nodes'])+1<=config['max_leaves'];node['status']='SPLIT'
   for side in ['LOW','HIGH']:tree['nodes'].append(dict(id=node['id']+'_'+side,choices={**node['choices'],r['block']['event_id']:side},resume=str(snap),status='PENDING'))
   write(tp,tree);continue
  assert r['status']=='COMPLETE_RESEARCH_ACCOUNT',r.get('block')
  validate_prefix(policy);r['verification']=verify_lots(policy,meta['symbols']);r['metrics']=af.stats(policy);write(rp,r);node.update(status='COMPLETE',report=str(rp),policy=policy);write(tp,tree);print('ACCOUNT_VERIFIED',policy,flush=True)
 write(B/'ACCOUNTS_COMPLETE.json',tree);state(status='ACCOUNTS_COMPLETE',task='BUILD_HELD_LABELS_AND_DRAWDOWN_MAP')
def main():
 torch.set_num_threads(1);assert torch.backends.mps.is_available();meta=json.loads((PANEL/'axes.json').read_text());meta['dates']=[d for d in meta['dates'] if d<'2020'];assert meta['dates'][-1]=='2019-12-31';birth=subprocess.check_output(['ps','-p',str(os.getpid()),'-o','lstart='],text=True).strip();state(status='RUNNING',task='FROZEN_INPUT_IDENTITY',pid=os.getpid(),birth=birth,error=None,next='inference -> physical Train account -> held labels/map -> V2 rolling mechanisms')
 inference(meta);accounts(meta)
 from alpha_train_risk_base import run
 run(meta)
if __name__=='__main__':
 with (B/'build.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:main()
  except Exception:
   state(status='NEEDS_AGENT_REPAIR',pid=None,error=traceback.format_exc());raise
