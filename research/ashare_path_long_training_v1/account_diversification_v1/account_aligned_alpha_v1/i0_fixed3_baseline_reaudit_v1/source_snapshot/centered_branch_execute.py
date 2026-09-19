"""Execution of exact NEXT_SPEC_A, isolated32 coefficients; frozen solver ceiling."""
import os,json,gc,traceback,fcntl
import numpy as np,pandas as pd,joblib
from scipy.optimize import minimize
from scipy.stats import spearmanr
import mechanism_replication as m
from o2_nested_earlystop import NestedData
from signal_sprint_probes import centered,weights
from train_fit_components_v2 import one
T=m.t;D=T.DEST/'centered_relative_branch';D.mkdir(exist_ok=True);SPEC=T.DOC/'NEXT_SPEC_A_UNDERREAD.json';P=T.DOC/'CENTERED_BRANCH_EXECUTION_PROTOCOL.json';S=T.DOC/'CENTERED_BRANCH_STATE.json'
def state(**kw):
 a=json.loads(S.read_text()) if S.exists() else {};a.update(at=T.now(),**kw);T.write(S,a)
 u=json.loads((T.DOC/'UNIFIED_DAG_STATE.json').read_text());u.update(status=a['status'],phase='CENTERED_RELATIVE_BRANCH_EXECUTION',child_pid=a.get('pid'),child_birth=a.get('birth'),active_state=str(S),active_state_path=str(S),research_terminal=False,current_task=a.get('task'),next='Exact12 fits -> Train gate -> frozen daily consensus -> H20 only if Top10 transfer',new_training_authorized=False);T.write(T.DOC/'UNIFIED_DAG_STATE.json',u)
def freeze():
 if P.exists():return
 T.write(P,dict(at=T.now(),spec_sha256=T.sha(SPEC),user_authorization_sha256=T.sha('/Users/linmei/.codex/attachments/a44e73c9-3b34-430b-90aa-4cc66e7c54f2/pasted-text.txt'),binding_protocol_sha256=T.sha(m.r.P),solver='Exact frozen L-BFGS-B zero32,gtol1e-8,ftol1e-12,maxiter200; no extension or changed parameterization',train_gate='All12 converge with finite reproducible theta, relative Huber improves, relative MSE no worse than baseline within1e-12, common mean within1e-10, source hashes unchanged. No cherry-picking. Nonconverged final iterate diagnostic only.',signal_gate='Same fixed historical directional/concentration logic, Top10 primary: full-daily consensus pooled Top10 delta>0, >=3/4 years positive, >=2/3 individual seeds pooled Top10 positive; pooled GlobalIC>=0 and Top50 delta>0; Top10 remains positive excluding best year, best month or top5dates. Repeat Top10 comparison with unchanged raw-mean>0 positive gate on paired opportunity dates. Top1 positivity not required. All magnitudes reported; no marginal rounding-up or new threshold.',scope='Consumed2020-2023 only; old Ridge adaptive rejection unchanged. New explicit user authorization conditionally permits THIS branch H20, no global bypass of old Ridge gate. No new model invention.',account_baseline='AF_RANK_CONSENSUS_P1_FULL; exact engine/signal identity before replay',reproducibility='Repeat exact solve from zero, single-thread BLAS; no second-run selection'))
def objective(theta,x,e,w):
 a=e+10*(x@theta);val=np.where(abs(a)<1,.5*a*a,abs(a)-.5);return float(w@val),10*(x.T@(w*np.clip(a,-1,1)))
def fit_all():
 rows=[];binding=json.loads(m.r.P.read_text())['bindings'];spec=json.loads(SPEC.read_text());seal=T.sha(P)
 for year in m.YEARS:
  fs=next(s for s in T.manifest()['all_nested_folds'] if s['outer_year']==year);d=NestedData(fs)
  for seed in m.SEEDS:
   out=D/f'{year}_s{seed}';out.mkdir(exist_ok=True);done=out/'FIT_COMPLETE.json'
   if done.exists():
    q=json.loads(done.read_text());assert q['seal']==seal;rows.append(q);continue
   state(status='RUNNING',task='EXACT_FULL_BATCH_HUBER_FIT',year=year,seed=seed)
   rec=next(b for b in binding if b['year']==year and b['seed']==seed);assert T.sha(rec['checkpoint_path'])==rec['checkpoint_sha256'];a=np.load(m.r.D/f'{year}_s{seed}/TRAIN_EMBED.npz');rr=a['rows'];assert np.array_equal(rr,d.train);idx=d.idx.iloc[rr].reset_index(drop=True);assert pd.Timestamp(idx.decision_date.min())+pd.DateOffset(years=12)<=pd.Timestamp(idx.decision_date.max());old=joblib.load(m.r.D/f'{year}_s{seed}/READOUT.joblib');x=old['scaler'].transform(centered(a['embedding'],idx.t));base=a['pred20'].astype(float);y=d.y[rr,1].astype(float);e=10*centered((base-y)[:,None],idx.t).ravel();w=weights(idx.t.to_numpy(),idx.year.to_numpy());w/=w.sum();zero=np.zeros(32);opts={k:spec['solver'][k] for k in ['gtol','ftol','maxiter']}
   initial=objective(zero,x,e,w)[0];res=minimize(objective,zero,args=(x,e,w),method='L-BFGS-B',jac=True,options=opts)
   repeat=minimize(objective,zero,args=(x,e,w),method='L-BFGS-B',jac=True,options=opts);assert np.array_equal(res.x,repeat.x) and res.fun==repeat.fun,'NONDETERMINISTIC_SOLVER'
   theta=res.x;co=centered((x@theta)[:,None],idx.t).ravel();assert np.isfinite(theta).all();common=pd.Series(co).groupby(idx.t).mean().abs().max();assert common<=1e-10
   before=float(w@(e/10)**2);after=float(w@(e/10+co)**2);q=dict(year=year,seed=seed,seal=seal,spec_sha256=T.sha(SPEC),checkpoint_sha256=rec['checkpoint_sha256'],train_rows=len(rr),converged=bool(res.success),solver_status=int(res.status),message=str(res.message),iterations=int(res.nit),function_evals=int(res.nfev),gradient_inf=float(np.max(abs(res.jac))),huber_before=initial,huber_after=float(res.fun),relative_mse_before=before,relative_mse_after=after,max_common_change=float(common),reproducible=True,theta_finite=True,train_pass=bool(res.success and res.fun<initial and after<=before+1e-12),diagnostic_iterate_only=not bool(res.success))
   joblib.dump(dict(theta=theta,scaler=old['scaler'],seal=seal,checkpoint_sha256=rec['checkpoint_sha256']),out/'BRANCH.joblib');f=idx[['t','j','decision_date']].copy();f['ret20']=y;f['F00_pred20']=base;f['BRANCH_pred20']=base+co;metrics=[]
   for date,g in f.groupby('decision_date'):
    for arm in ['F00','BRANCH']:
     v=one(g,arm);metrics.append(dict(year=year,seed=seed,date=date,arm=arm,**{k:v[k] for k in m.KEYS if k!='decile_monotonicity'}))
   pd.DataFrame(metrics).to_parquet(out/'TRAIN_METRICS.parquet',index=False);T.write(done,q);rows.append(q);pd.DataFrame(rows).to_csv(T.DOC/'CENTERED_BRANCH_TRAIN_FITS.csv',index=False);print('FIT_COMPLETE',json.dumps(q),flush=True)
   del a,x,f;gc.collect()
  del d;gc.collect()
 return rows

def finish_train(rows):
 passed=all(q['train_pass'] for q in rows);T.write(T.DOC/'CENTERED_BRANCH_TRAIN_GATE.json',dict(pass_gate=passed,bindings=len(rows),converged=sum(q['converged'] for q in rows),huber_improved=sum(q['huber_after']<q['huber_before'] for q in rows),mse_improved=sum(q['relative_mse_after']<=q['relative_mse_before']+1e-12 for q in rows),full_eligible_common_check='Before outcome evaluation, required in daily prediction stage' if passed else 'NOT_RUN_TRAIN_GATE_FAILED'))
 parts=[pd.read_parquet(D/f'{y}_s{s}/TRAIN_METRICS.parquet') for y in m.YEARS for s in m.SEEDS];f=pd.concat(parts);f.groupby(['year','seed','arm']).mean(numeric_only=True).to_csv(T.DOC/'CENTERED_BRANCH_TRAIN_METRICS.csv')
 if not passed:
  verdict='CENTERED_RELATIVE_BRANCH_TRAIN_FAIL';state(status='COMPLETE',task=verdict,pid=None,birth=None);T.write(T.DOC/'CENTERED_BRANCH_RESULT.json',dict(verdict=verdict,train_gate=False,development_evaluated=False,account_replayed=False,reason='Exact frozen solver/mechanism requirements not met; no unconverged iterate promoted, no solver rescue',spec_sha256=T.sha(SPEC)))
  u=json.loads((T.DOC/'UNIFIED_DAG_STATE.json').read_text());u.update(research_terminal=True,research_terminal_state=verdict,next=None);T.write(T.DOC/'UNIFIED_DAG_STATE.json',u);print('FINAL',verdict,flush=True)
 return passed

def run():
 freeze();state(status='RUNNING',pid=os.getpid(),birth=T.birth(os.getpid()),task='TRAIN_FITS');rows=fit_all()
 if finish_train(rows):
  state(status='TRAIN_GATE_PASSED',task='DAILY_PREDICTION_COMMON_CONSERVATION_THEN_CONSENSUS')
  import centered_branch_evaluate
  centered_branch_evaluate.run()
if __name__=='__main__':
 with (D/'lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:run()
  except Exception:state(status='NEEDS_AGENT_REPAIR',error=traceback.format_exc(),pid=None,birth=None);raise
