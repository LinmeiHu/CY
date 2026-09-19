"""Equivalent Train-only coordinates for the original unregularized centered Huber."""
import os,json,gc,traceback,fcntl
import numpy as np,pandas as pd,joblib
from scipy.optimize import minimize
from scipy.linalg import svd
import centered_branch_execute as old
from o2_nested_earlystop import NestedData
from signal_sprint_probes import centered,weights
from train_fit_components_v2 import one
T=old.T;m=old.m;D=T.DEST/'centered_branch_numerical_repair';D.mkdir(exist_ok=True);P=T.DOC/'CENTERED_BRANCH_NUMERICAL_CONTRACT.json';S=T.DOC/'CENTERED_BRANCH_REPAIRED_STATE.json'
def state(**kw):
 a=json.loads(S.read_text()) if S.exists() else {};a.update(at=T.now(),**kw);T.write(S,a)
 u=json.loads((T.DOC/'UNIFIED_DAG_STATE.json').read_text());u.update(status=a['status'],phase='CENTERED_BRANCH_NUMERICAL_REPAIR',child_pid=a.get('pid'),child_birth=a.get('birth'),active_state=str(S),active_state_path=str(S),research_terminal=False,current_task=a.get('task'),next='Equivalent12 fits -> Train PASS -> frozen development consensus -> conditional H20');T.write(T.DOC/'UNIFIED_DAG_STATE.json',u)
def freeze():
 if P.exists():return
 T.write(P,dict(at=T.now(),model_spec_sha256=T.sha(old.SPEC),signal_protocol_sha256=T.sha(old.P),authorization_sha256=T.sha('/Users/linmei/.codex/attachments/97298067-48d4-4997-a22b-f04f61daf0f8/pasted-text.txt'),old_failure='NUMERICAL_SOLVER_CONTRACT_FAILURE_NOT_MECHANISM_FALSIFICATION',transform='Weighted thin SVD of sqrt(w)*X with exact prior centering/scaling; Xnew=X@V@diag(1/s). theta=V@diag(1/s)@eta; eta=diag(s)@V.T@theta',rank_criterion='s > eps_float64*max(n,32)*s_max; derived solely from backward-error rank convention, no labels or predictive selection. Retain all identifiable near-null directions.',equivalence_tolerance='128*eps64*32*(1+max_row_L1(X)*Linf(theta)+max_row_L1(Xnew)*Linf(eta)); arithmetic forward-error bound; objective tolerance derived via10-Lipschitz Huber bound',solver='Zero eta; deterministic L-BFGS-B gtol1e-10,ftol0,maxiter5000,maxfun20000,maxcor20. Both whitened and mapped-original gradient_inf<=1e-8 required. On failure deterministic trust-exact on same objective/Hessian with gtol1e-10,maxiter1000; no predictive selection.',unchanged='32input, labels, scaler, Huber delta, weights, no bias, no L2, frozenencoder/M0, original signal/account protocol, sealed2024-2026',train_gate='All12 genuine convergence, repeatability, Huber lower than zero; MSE reported per new user instruction; full eligible common conservation checked before any development outcome evaluation',source_sha256=T.sha(T.Path(__file__))))
def tolerance(x,z,theta,eta):
 return 128*np.finfo(float).eps*32*(1+np.max(np.sum(abs(x),axis=1))*np.max(abs(theta))+np.max(np.sum(abs(z),axis=1))*np.max(abs(eta)))
def solve(z,x,B,e,w):
 opts=dict(gtol=1e-10,ftol=0,maxiter=5000,maxfun=20000,maxcor=20);r=minimize(old.objective,np.zeros(z.shape[1]),args=(z,e,w),method='L-BFGS-B',jac=True,options=opts);method='L-BFGS-B'
 def good(r):
  return np.isfinite(r.x).all() and np.max(abs(old.objective(r.x,z,e,w)[1]))<=1e-8 and np.max(abs(old.objective(B@r.x,x,e,w)[1]))<=1e-8
 if not good(r):
  def hess(eta):
   active=abs(e+10*z@eta)<1;return 100*z.T@(z*(w*active)[:,None])
  r=minimize(old.objective,r.x,args=(z,e,w),method='trust-exact',jac=True,hess=lambda eta,*args:hess(eta),options=dict(gtol=1e-10,maxiter=1000));method='trust-exact'
 if not good(r):
  # Near the optimum objective differences round to zero; solve the stationarity equation.
  from scipy.optimize import OptimizeResult
  eta=r.x.copy()
  for it in range(50):
   f,g=old.objective(eta,z,e,w)
   if np.max(abs(g))<=1e-11:break
   active=abs(e+10*z@eta)<1;H=100*z.T@(z*(w*active)[:,None]);step=np.linalg.solve(H,g);alpha=1.
   for bt in range(30):
    trial=eta-alpha*step;fv,gv=old.objective(trial,z,e,w)
    if fv<=f+64*np.finfo(float).eps*max(1.,abs(f)) and np.linalg.norm(gv)<np.linalg.norm(g):break
    alpha*=.5
   else:break
   eta=trial
  f,g=old.objective(eta,z,e,w);r=OptimizeResult(x=eta,fun=f,jac=g,status=0,success=np.max(abs(g))<=1e-8,nit=int(r.nit)+it+1,message='Deterministic active-Hessian stationarity polish');method+=' + Newton-stationarity'
 return r,method,good(r)
def fit_all():
 records=[];binding=json.loads(m.r.P.read_text())['bindings'];seal=T.sha(P)
 for year in m.YEARS:
  fs=next(q for q in T.manifest()['all_nested_folds'] if q['outer_year']==year);d=NestedData(fs)
  for seed in m.SEEDS:
   out=D/f'{year}_s{seed}';out.mkdir(exist_ok=True);done=out/'FIT_COMPLETE.json'
   if done.exists():q=json.loads(done.read_text());assert q['seal']==seal;records.append(q);continue
   state(status='RUNNING',task='TRAIN_SVD_AND_EQUIVALENT_SOLVE',year=year,seed=seed);rec=next(b for b in binding if b['year']==year and b['seed']==seed);assert T.sha(rec['checkpoint_path'])==rec['checkpoint_sha256'];cache=np.load(m.r.D/f'{year}_s{seed}/TRAIN_EMBED.npz');rr=cache['rows'];assert np.array_equal(rr,d.train);idx=d.idx.iloc[rr].reset_index(drop=True);scaler=joblib.load(m.r.D/f'{year}_s{seed}/READOUT.joblib')['scaler'];x=scaler.transform(centered(cache['embedding'],idx.t));base=cache['pred20'].astype(float);y=d.y[rr,1].astype(float);e=10*centered((base-y)[:,None],idx.t).ravel();w=weights(idx.t.to_numpy(),idx.year.to_numpy());w/=w.sum()
   U,s,Vt=svd(x*np.sqrt(w[:,None]),full_matrices=False,lapack_driver='gesdd');del U;cut=np.finfo(float).eps*max(x.shape)*s[0];keep=s>cut;V=Vt[keep].T;ss=s[keep];sign=np.sign(V[np.argmax(abs(V),axis=0),np.arange(V.shape[1])]);V*=sign;B=V/ss;A=ss[:,None]*V.T;z=x@B
   # Equivalence BEFORE optimizing this binding; the first binding precedes all other fits.
   rng=np.random.default_rng(912);tests=[]
   for j in range(3):
    theta=rng.normal(size=32);eta=A@theta;err=float(np.max(abs(x@theta-z@eta)));tol=tolerance(x,z,theta,eta);assert err<=tol,(err,tol);tests.append(dict(error=err,bound=tol))
   v,g=old.objective(np.zeros(len(ss)),z,e,w);u=rng.normal(size=len(ss));u/=np.linalg.norm(u);eps=1e-6;fd=(old.objective(eps*u,z,e,w)[0]-old.objective(-eps*u,z,e,w)[0])/(2*eps);assert np.isclose(fd,g@u,rtol=2e-5,atol=1e-7)
   r,method,converged=solve(z,x,B,e,w);assert converged,('NUMERICAL_REPAIR_BLOCKED',year,seed,str(r.message),np.max(abs(r.jac)))
   r2,method2,ok2=solve(z,x,B,e,w);assert ok2 and method==method2 and np.array_equal(r.x,r2.x) and r.fun==r2.fun
   theta=B@r.x;co=centered((x@theta)[:,None],idx.t).ravel();tol=tolerance(x,z,theta,r.x);mapping=float(np.max(abs(x@theta-z@r.x)));assert mapping<=tol
   orig_obj,orig_grad=old.objective(theta,x,e,w);assert abs(orig_obj-r.fun)<=10*tol;common=float(pd.Series(co).groupby(idx.t).mean().abs().max());assert common<=1e-10
   zero=old.objective(np.zeros(32),x,e,w)[0];q=dict(year=year,seed=seed,seal=seal,model_spec_sha256=T.sha(old.SPEC),train_rows=len(rr),numerical_rank=int(keep.sum()),rank_cutoff=float(cut),singular_values=s.tolist(),weighted_covariance_eigenvalues=(s*s).tolist(),condition_number=float(s[0]/s[-1]),whitened_covariance_error=float(np.max(abs(z.T@(z*w[:,None])-np.eye(len(ss))))),arbitrary_theta_equivalence=tests,mapped_solution_prediction_error=mapping,equivalence_error_bound=tol,objective_mapping_error=float(abs(orig_obj-r.fun)),solver=method,solver_status=int(r.status),solver_message=str(r.message),iterations=int(r.nit),converged=True,whitened_gradient_inf=float(np.max(abs(old.objective(r.x,z,e,w)[1]))),original_gradient_inf=float(np.max(abs(orig_grad))),huber_before=zero,huber_after=orig_obj,relative_mse_before=float(w@(e/10)**2),relative_mse_after=float(w@(e/10+co)**2),max_common_change=common,reproducible=True,train_pass=bool(orig_obj<zero),checkpoint_sha256=rec['checkpoint_sha256'])
   joblib.dump(dict(theta=theta,eta=r.x,scaler=scaler,original_from_transformed=B,transformed_from_original=A,seal=seal,converged=True,checkpoint_sha256=rec['checkpoint_sha256']),out/'BRANCH.joblib');f=idx[['t','j','decision_date']].copy();f['ret20']=y;f['F00_pred20']=base;f['BRANCH_pred20']=base+co;metrics=[]
   for date,g in f.groupby('decision_date'):
    for arm in ['F00','BRANCH']:
     vals=one(g,arm);metrics.append(dict(year=year,seed=seed,date=date,arm=arm,**{k:vals[k] for k in m.KEYS if k!='decile_monotonicity'}))
   pd.DataFrame(metrics).to_parquet(out/'TRAIN_METRICS.parquet',index=False);T.write(done,q);records.append(q);pd.DataFrame([{k:v for k,v in q.items() if not isinstance(v,list)} for q in records]).to_csv(T.DOC/'CENTERED_BRANCH_REPAIRED_TRAIN_FITS.csv',index=False);print('FIT_COMPLETE',year,seed,'rank',keep.sum(),'iterations',r.nit,'gradient',q['original_gradient_inf'],flush=True);del x,z,cache,f;gc.collect()
  del d;gc.collect()
 return records

def run():
 freeze();state(status='RUNNING',pid=os.getpid(),birth=T.birth(os.getpid()),task='FIRST_BINDING_EQUIVALENCE_PREFLIGHT');rows=fit_all();passed=all(q['train_pass'] and q['converged'] for q in rows);T.write(T.DOC/'CENTERED_BRANCH_REPAIRED_TRAIN_GATE.json',dict(verdict='CENTERED_RELATIVE_BRANCH_TRAIN_PASS' if passed else 'CENTERED_RELATIVE_MECHANISM_TRAIN_NO_INCREMENT',passed=passed,bindings=len(rows),converged=sum(q['converged'] for q in rows),original_model_spec_sha256=T.sha(old.SPEC),common_full_eligible='PENDING_INPUT_ONLY_CHECK_BEFORE_OUTCOME_EVALUATION'))
 if passed:
  state(status='TRAIN_PASS',task='FROZEN_FULL_DAILY_SIGNAL_EVALUATION');import centered_branch_evaluate;centered_branch_evaluate.run()
 else:state(status='COMPLETE',task='CENTERED_RELATIVE_MECHANISM_TRAIN_NO_INCREMENT',pid=None,birth=None)
if __name__=='__main__':
 with (D/'lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:run()
  except Exception:state(status='NEEDS_AGENT_REPAIR',error=traceback.format_exc(),pid=None,birth=None);raise
