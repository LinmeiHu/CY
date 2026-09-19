"""Frozen transfer input build; no outcome selection and no Alpha inference."""
import json,inspect
from pathlib import Path
import numpy as np,pandas as pd
from common import HERE,OUT,PANEL,get,sha
import account
from action_supplement import load_registration,validate_and_apply
from alpha_train_timing import validate_asset
N='linear_positive_gate_transfer_2020_2023_v1';W=HERE/'account_diversification_v1'/N;B=OUT/'account_diversification_v1'/N;B.mkdir(exist_ok=True);S=B.parent/'alpha_held_risk_v2';old=B.parent/'positive_gate_calibration_v2_autonomous';dates=json.loads((PANEL/'axes.json').read_text())['dates'];dates=[d for d in dates if d<'2024'];parts=[];samples=[];ids=[]
for y in range(2020,2024):
 p=S/'transfer_v1/daily'/f'{y}.parquet';f=pd.read_parquet(p);assert f.year.eq(y).all() and all(dates[int(t)].startswith(str(y)) for t in f.t)
 raw=f[[f'BRANCH_s{s}' for s in [17,29,43]]].mean(axis=1);assert np.allclose(raw,f.final_prediction,rtol=0,atol=0)
 ranks=pd.concat([f.groupby('t')[f'BRANCH_s{s}'].rank(pct=True) for s in [17,29,43]],axis=1).mean(axis=1);assert np.allclose(ranks,f.consensus_rank,rtol=0,atol=0)
 ids.append(dict(year=y,path=str(p),sha256=sha(p),rows=len(f),dates=f.t.nunique()));parts.append(f)
 for t,g in f.groupby('t'):
  rng=np.random.default_rng(37019+int(t));g=g.copy();g['stratum']=np.searchsorted([-.05,0,.05],g.final_prediction,side='left')
  for st,q in g.groupby('stratum'):
   h=q.iloc[rng.choice(len(q),size=min(2,len(q)),replace=False)].copy();h['stratum_N']=len(q);h['stratum_n']=len(h);h['eligible_N']=len(g);h['population_weight']=len(q)/len(h)/len(g);samples.append(h)
f=pd.concat(parts,ignore_index=True);f.to_parquet(B/'DEVELOPMENT_POPULATION.parquet',index=False);s=f[f.positive_gate].rename(columns={'consensus_rank':'score','final_prediction':'pred20'});s['logamount20']=np.log(get('adv20')[s.t,s.j]);s=s[['t','j','score','pred20','logamount20']]
prior=pd.read_parquet(S/'SIGNALS.parquet')[s.columns];pd.concat([prior,s],ignore_index=True).to_parquet(B/'SIGNALS.parquet',index=False)
a=pd.concat(samples,ignore_index=True);a['logamount20']=np.log(get('adv20')[a.t,a.j]);assert np.allclose(a.groupby('t').population_weight.sum(),1)
# Previously right-censored2019 labels may legally resolve in2020; retain original sample IDs/weights.
labels=pd.read_parquet(old/'CALIBRATION_LABELS.parquet');missing=labels[(labels.branch=='LOW')&labels.Y.isna()&labels.label_status.isin(['UNMATURED_BOUNDARY','UNRESOLVED_NATIVE_LIFECYCLE'])];prior_samples=pd.read_parquet(old/'SAMPLED_CANDIDATES.parquet');keys=set(zip(missing.t,missing.j));extra=prior_samples[[(t,j) in keys for t,j in zip(prior_samples.t,prior_samples.j)]]
# Whole original date batch, preserving minfees/physical entitlement label construction.
extra=prior_samples[prior_samples.t.isin(extra.t)];a=pd.concat([extra,a],ignore_index=True);assert not a.duplicated(['t','j']).any();a.to_parquet(B/'SAMPLED_CANDIDATES.parquet',index=False)
# Bounded original registered loader, SQL excludes2024 effective outcomes before loading rows.
source=inspect.getsource(account.actions).replace("DATE '2024-02-29'","DATE '2023-12-31'");scope=dict(account.__dict__);exec(source,scope);acts=scope['actions']();reg,evidence=load_registration();acts=validate_and_apply(acts,reg,evidence)
pre=validate_asset(S/'REGISTERED_ACTIONS_PRE2020_TIMING_V1.parquet');acts=pd.concat([pre,acts[~acts.event_id.isin(pre.event_id)]],ignore_index=True);assert acts.event_id.is_unique
assert acts.effective_date.max()<pd.Timestamp('2024-01-01');acts.to_parquet(B/'REGISTERED_ACTIONS_THROUGH2023.parquet',index=False)
(W/'INPUT_BINDINGS.json').write_text(json.dumps(dict(predictions=ids,signals_sha256=sha(B/'SIGNALS.parquet'),sample_sha256=sha(B/'SAMPLED_CANDIDATES.parquet'),actions_sha256=sha(B/'REGISTERED_ACTIONS_THROUGH2023.parquet'),action_source_query=source,old_2019_boundary_dates=extra.t.nunique(),sample_dates=a.t.nunique(),sample_names=len(a),end=dates[-1]),indent=2))
(W/'AUTONOMOUS_STATE.json').write_text(json.dumps(dict(CURRENT_PHASE='MARGINAL_LABEL_BUILD',COMPLETED=['frozen preflight','full development prediction parity','probability sample','registered bounded actions'],NEXT_AUTHORIZED_ACTION='native marginal label build, then daily frozen linear online stream',BLOCKERS=[],sample_dates=a.t.nunique(),ARTIFACTS=str(B)),indent=2));print('PREPARED',len(a),a.t.nunique())
