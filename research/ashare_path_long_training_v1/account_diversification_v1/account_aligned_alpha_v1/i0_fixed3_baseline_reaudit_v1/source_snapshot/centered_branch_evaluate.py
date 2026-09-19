"""One-shot frozen development and unchanged3-seed consensus; no fit or selection."""
import json,gc
import numpy as np,pandas as pd,joblib
from scipy.stats import spearmanr
import centered_branch_numerical_repair as n
from signal_sprint_probes import centered
from train_fit_components_v2 import one
from rank_consensus_accounts import rank_consensus
T=n.T;D=n.D

def predict_all():
 audit=[]
 for year in n.m.YEARS:
  out=D/'daily'/str(year);out.mkdir(parents=True,exist_ok=True)
  if (out/'PREDICTION_COMPLETE.json').exists():audit.extend(json.loads((out/'PREDICTION_COMPLETE.json').read_text())['audit']);continue
  n.state(status='RUNNING',task='INPUT_ONLY_FULL_ELIGIBLE_COMMON_CHECK',year=year)
  source=n.m.r.D/'daily'/str(year);f=pd.read_parquet(source/'PREDICTIONS.parquet',columns=['t','j','decision_date','year']+[f'F00_s{s}' for s in n.m.SEEDS]);assert f.decision_date.max()<'2024';z=pd.concat([pd.read_parquet(p) for p in sorted((source/'embeddings').glob('*.parquet'))],ignore_index=True);f=f.merge(z,on=['t','j'],validate='one_to_one');local=[]
  for seed in n.m.SEEDS:
   fit=json.loads((D/f'{year}_s{seed}/FIT_COMPLETE.json').read_text());assert fit['converged'] and fit['train_pass'];md=joblib.load(D/f'{year}_s{seed}/BRANCH.joblib');x=md['scaler'].transform(centered(f[[f's{seed}_z{k}' for k in range(32)]].to_numpy(),f.t));co=centered((x@md['theta'])[:,None],f.t).ravel();f[f'BRANCH_s{seed}']=f[f'F00_s{seed}']+co;delta=f[['t',f'BRANCH_s{seed}',f'F00_s{seed}']].astype({f'BRANCH_s{seed}':'float64',f'F00_s{seed}':'float64'}).groupby('t').mean().diff(axis=1).iloc[:,1].abs().max();assert delta<=1e-10 and np.isfinite(f[f'BRANCH_s{seed}']).all();local.append(dict(year=year,seed=seed,rows=len(f),dates=f.t.nunique(),max_full_eligible_common_difference=float(delta),prediction_coverage=1.,rank_coverage=1.,label_used=False))
  f=f.drop(columns=[c for c in f if '_z' in c]);f.to_parquet(out/'INPUT_ONLY_PREDICTIONS.parquet',index=False);T.write(out/'PREDICTION_COMPLETE.json',dict(audit=local,model_spec_sha256=T.sha(n.old.SPEC)));audit.extend(local);del x,z,f;gc.collect()
 pd.DataFrame(audit).to_csv(T.DOC/'CENTERED_BRANCH_COMMON_COVERAGE.csv',index=False);gate=json.loads((T.DOC/'CENTERED_BRANCH_REPAIRED_TRAIN_GATE.json').read_text());gate['common_full_eligible']='PASS12/12';T.write(T.DOC/'CENTERED_BRANCH_REPAIRED_TRAIN_GATE.json',gate)

def metric_rows(f,year,seed,ac,bc):
 a=f[['t','j','decision_date','ret20',ac,bc]].rename(columns={ac:'F00_pred20',bc:'BRANCH_pred20'});rows=[]
 for day,g in a.groupby('decision_date'):
  for arm in ['F00','BRANCH']:
   v=one(g,arm);valid=g[['ret20',arm+'_pred20']].dropna();rank=valid[arm+'_pred20'].rank(pct=True);bins=np.minimum(9,np.floor(rank*10).astype(int));means=valid.ret20.groupby(bins).mean();v['decile_monotonicity']=float(spearmanr(means.index,means).statistic) if len(means)>2 else np.nan;rows.append(dict(year=year,seed=str(seed),date=day,arm=arm,**{k:v[k] for k in n.m.KEYS},label_coverage=float(g.ret20.notna().mean())))
 return pd.DataFrame(rows)
def evaluate_all():
 parts=[];top=[]
 for year in n.m.YEARS:
  out=D/'daily'/str(year)
  if (out/'EVALUATION_COMPLETE.json').exists():parts.append(pd.read_parquet(out/'METRICS.parquet'));top.append(pd.read_parquet(out/'POSITIVE_GATED_TOP10.parquet'));continue
  n.state(status='RUNNING',task='FROZEN_DEVELOPMENT_SIGNAL_METRICS',year=year)
  f=pd.read_parquet(out/'INPUT_ONLY_PREDICTIONS.parquet');labels=pd.read_parquet(n.m.r.D/'daily'/str(year)/'PREDICTIONS.parquet',columns=['t','j','ret20','mae20']);f=f.merge(labels,on=['t','j'],validate='one_to_one');per=[]
  for seed in n.m.SEEDS:per.append(metric_rows(f,year,seed,f'F00_s{seed}',f'BRANCH_s{seed}'))
  for arm in ['F00','BRANCH']:
   q=f[['t','j']+[f'{arm}_s{s}' for s in n.m.SEEDS]].rename(columns={f'{arm}_s{s}':f's{s}' for s in n.m.SEEDS});f[arm+'_consensus']=rank_consensus(q);f[arm+'_raw_mean']=q[['s17','s29','s43']].mean(axis=1)
  per.append(metric_rows(f,year,'consensus','F00_consensus','BRANCH_consensus'));pm=pd.concat(per);pm.to_parquet(out/'METRICS.parquet',index=False);f.to_parquet(out/'PREDICTIONS.parquet',index=False);tr=[]
  for day,g in f.groupby('decision_date'):
   for arm in ['F00','BRANCH']:
    z=g[g[arm+'_raw_mean']>0].sort_values([arm+'_consensus','j'],ascending=[False,True]).head(10);tr.append(dict(year=year,date=day,arm=arm,selected=len(z),labels=int(z.ret20.notna().sum()),lift=z.ret20.mean()-g.ret20.mean(),absolute_ret20=z.ret20.mean()))
  tr=pd.DataFrame(tr);tr.to_parquet(out/'POSITIVE_GATED_TOP10.parquet',index=False);parts.append(pm);top.append(tr);T.write(out/'EVALUATION_COMPLETE.json',dict(year=year,consensus='fixed3seed percentile-rank',development_consumed=True));print('DEV_COMPLETE',year,flush=True)
 return pd.concat(parts),pd.concat(top)
def adjudicate(f,top):
 rows=[]
 for seed,g in f.groupby('seed'):
  for period,z in [('ALL',g)]+[(str(y),q) for y,q in g.groupby('year')]:
   a=z[z.arm=='F00'].set_index('date');b=z[z.arm=='BRANCH'].set_index('date');assert a.index.equals(b.index)
   for k in n.m.KEYS:
    x=a[k].mean();v=b[k].mean();rows.append(dict(seed=seed,period=period,metric=k,baseline=x,candidate=v,absolute_delta=(b[k]-a[k]).mean(),relative_delta=(v-x)/abs(x) if x else None,paired_dates=int((b[k]-a[k]).notna().sum())))
 table=pd.DataFrame(rows);table.to_csv(T.DOC/'CENTERED_BRANCH_DEVELOPMENT_COMPARISON.csv',index=False);gated=[]
 for period,z in [('ALL',top)]+[(str(y),q) for y,q in top.groupby('year')]:
  a=z[z.arm=='F00'].set_index('date');b=z[z.arm=='BRANCH'].set_index('date');ok=a.lift.notna()&b.lift.notna();gated.append(dict(period=period,baseline=a.loc[ok,'lift'].mean(),candidate=b.loc[ok,'lift'].mean(),absolute_delta=(b.loc[ok,'lift']-a.loc[ok,'lift']).mean(),paired_dates=int(ok.sum()),baseline_opportunity_dates=int((a.selected>0).sum()),candidate_opportunity_dates=int((b.selected>0).sum()),unpaired_label_dates=int((a.lift.notna()^b.lift.notna()).sum())))
 ga=pd.DataFrame(gated);ga.to_csv(T.DOC/'CENTERED_BRANCH_GATED_TOP10_COMPARISON.csv',index=False);cs=table[table.seed=='consensus'];pool=cs[cs.period=='ALL'].set_index('metric');annual=cs[(cs.period!='ALL')&(cs.metric=='K10_BEFORE_lift')];seeds=table[(table.seed!='consensus')&(table.period=='ALL')&(table.metric=='K10_BEFORE_lift')];gann=ga[ga.period!='ALL'];c=f[f.seed=='consensus'];a=c[c.arm=='F00'].set_index('date');b=c[c.arm=='BRANCH'].set_index('date');dd=(b.K10_BEFORE_lift-a.K10_BEFORE_lift).dropna();months=dd.groupby(dd.index.str[:7]).mean();concentration=dict(without_top5_dates=float(dd.drop(dd.nlargest(5).index).mean()),without_best_month=float(dd[dd.index.str[:7]!=months.idxmax()].mean()),without_best_year=float(annual.absolute_delta.drop(annual.absolute_delta.idxmax()).mean()))
 checks=dict(top10_positive=bool(pool.loc['K10_BEFORE_lift','absolute_delta']>0),top10_years=int((annual.absolute_delta>0).sum()),seed_support=int((seeds.absolute_delta>0).sum()),global_preserved=bool(pool.loc['GlobalIC','absolute_delta']>=0),top50_positive=bool(pool.loc['K50_BEFORE_lift','absolute_delta']>0),nonconcentrated=all(v>0 for v in concentration.values()),gated_top10_positive=bool(ga[ga.period=='ALL'].iloc[0].absolute_delta>0),gated_years=int((gann.absolute_delta>0).sum()),gated_without_best_year=float(gann.absolute_delta.drop(gann.absolute_delta.idxmax()).mean()))
 passed=checks['top10_positive'] and checks['top10_years']>=3 and checks['seed_support']>=2 and checks['global_preserved'] and checks['top50_positive'] and checks['nonconcentrated'] and checks['gated_top10_positive'] and checks['gated_years']>=3 and checks['gated_without_best_year']>0
 verdict='CENTERED_RELATIVE_BRANCH_TOP10_TRANSFER' if passed else 'BROAD_RANKING_ONLY' if checks['global_preserved'] and checks['top50_positive'] and not checks['top10_positive'] else 'CENTERED_RELATIVE_BRANCH_NO_TRANSFER';out=dict(verdict=verdict,signal_gate_pass=passed,checks=checks,concentration=concentration,extreme_tail='TOP10_BOUNDARY_IMPROVES_EXTREME_INTERNAL_RANKING_UNRESOLVED' if checks['top10_positive'] and pool.loc['LocalIC_0.01','candidate']<=0 else 'REPORTED_WITHOUT_TOP1_POSITIVITY_GATE',development_consumed=True,adaptive_bias_erased=False,years_2024_2026_accessed=False);T.write(T.DOC/'CENTERED_BRANCH_SIGNAL_VERDICT.json',out);return out,table,ga

def finish(sig,table,ga,account=None):
 verdict=sig['verdict'] if not sig['signal_gate_pass'] else ('MECHANISM_DERIVED_ACCOUNT_CANDIDATE' if account and account['account_candidate'] else 'SIGNAL_TRANSFER_ACCOUNT_CONVERSION_FAIL');res=dict(sig,final_verdict=verdict,account=account,production_replaced=False,model_spec_sha256=T.sha(n.old.SPEC),numerical_contract_sha256=T.sha(n.P));T.write(T.DOC/'CENTERED_BRANCH_REPAIRED_RESULT.json',res)
 txt=verdict+'\n\n12 formal frozen bindings; exact original model objective, only numerical coordinates repaired.2020–2023 consumed development,2024–2026 closed. No new predictive variant or regularization.\n\n'+table[(table.seed=='consensus')&table.metric.isin(['GlobalIC','K10_BEFORE_lift','K50_BEFORE_lift','LocalIC_0.01','LocalIC_0.05','LocalIC_0.1'])].to_markdown(index=False)+'\n\nPositive-gated Top10:\n\n'+ga.to_markdown(index=False)+'\n\n'+json.dumps(sig,ensure_ascii=False)+'\n\n'
 if account:txt+='H20 real account:\n\n'+pd.DataFrame(account['comparison']).to_markdown(index=False)+'\n\n'+account['diagnosis']
 else:txt+='H20 NOT_RUN: signal gate did not pass. No new Alpha or account-rule experiment started.'
 (T.DOC/'CENTERED_BRANCH_REPAIRED_REPORT.md').write_text(txt);n.state(status='COMPLETE',task=verdict,pid=None,birth=None);u=json.loads((T.DOC/'UNIFIED_DAG_STATE.json').read_text());u.update(research_terminal=True,research_terminal_state=verdict,next=None,report=str(T.DOC/'CENTERED_BRANCH_REPAIRED_REPORT.md'));T.write(T.DOC/'UNIFIED_DAG_STATE.json',u);print('FINAL',verdict,flush=True)
def run():
 predict_all();f,top=evaluate_all();sig,table,ga=adjudicate(f,top);account=None
 if sig['signal_gate_pass']:
  n.state(status='RUNNING',task='AUTHORIZED_UNCHANGED_H20_ACCOUNT');import centered_branch_account;account=centered_branch_account.run()
 finish(sig,table,ga,account)
