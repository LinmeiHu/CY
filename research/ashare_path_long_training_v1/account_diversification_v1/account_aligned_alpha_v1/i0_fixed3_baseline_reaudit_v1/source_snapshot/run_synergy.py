#!/usr/bin/env python3
"""2020-only, CPU-only anatomy of the frozen I0/M mean-percentile ensembles."""
from __future__ import annotations
import hashlib, importlib.util, json, os
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent; MASTER=HERE.parent
VOL=Path('/Volumes/quant/CY_quant_research/ashare_path_long_training_v1')
FULL=VOL/'account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward/2020'
PRED=VOL/'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/predictions/2020'
SINGLE=VOL/'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/single_seed_account_diagnostic_v1/accounts/2020'
E0=VOL/'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/ensemble_tail_autopsy_v1'
BROADER=MASTER.parent/'broader_ranking_portfolio_v1/run.py'; SEEDS=(17,29,43)

def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False,default=str)+'\n')
def module(n,p):
    s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def pct(keys,x):
    o=np.empty(len(x),float)
    for _,ix in keys.groupby('t',sort=False).indices.items():o[ix]=pd.Series(x[ix]).rank(method='average',pct=True).to_numpy(float)
    return o
def rank(keys,x):
    o=np.empty(len(x),int)
    for _,ix in keys.groupby('t',sort=False).indices.items():o[ix]=pd.Series(x[ix]).rank(method='first',ascending=False).to_numpy(int)
    return o
def finite_mean(x):
    x=np.asarray(x,float);return float(np.nanmean(x)) if np.isfinite(x).any() else None
def pos(x):
    x=np.asarray(x,float);x=x[np.isfinite(x)];return float((x>0).mean()) if len(x) else None
def stat(x):
    x=pd.Series(x).replace([np.inf,-np.inf],np.nan).dropna()
    return {'n':int(len(x)),'mean':float(x.mean()),'median':float(x.median()),'p10':float(x.quantile(.1)),'p90':float(x.quantile(.9)),'min':float(x.min()),'max':float(x.max())} if len(x) else {'n':0}
def jacc(a,b):return float((a&b).sum()/max(1,(a|b).sum()))

def metrics(frame, label=''):
    return {'group':label,'count':int(len(frame)),'ret10':finite_mean(frame.ret10),'ret20':finite_mean(frame.ret20),'positive_ret10':pos(frame.ret10),'positive_ret20':pos(frame.ret20)}

def lot_contribution(br, folder, policy, keys, ensemble_set, seed_sets, family):
    """Exact-ledger, non-additive lot cashflow plus end-mark descriptive attribution."""
    _,_,ts,_,_,_=br.context(2020); start,end=ts[0],ts[-1]
    orders=br.read_ledger(folder,policy,'orders'); fills=br.read_ledger(folder,policy,'lot_fills'); li=br.read_ledger(folder,policy,'lot_inventory')
    buys=orders[(orders.side=='BUY')&(orders.status=='FILLED')&(orders.decision_t>=3163)].copy()
    buys['lot_id']=buys.decision_t.astype(int).astype(str)+':'+buys.j.astype(int).astype(str)
    buys['key']=list(zip(buys.decision_t.astype(int),buys.j.astype(int)))
    any_seed=set().union(*seed_sets)
    buys['group']=np.where(buys.key.isin(any_seed),'RETAINED_BY_AT_LEAST_ONE_SEED','ENSEMBLE_ONLY_FUNDED')
    # all seed-funded choices excluded from this ensemble are measured on the common signal key space;
    # their own account cashflows are not additively comparable, so only the ensemble side has lot PnL.
    cash=fills[fills.t.between(start,end)].assign(cash_f=lambda x:x.cash_delta.astype(float)).groupby('lot_id').cash_f.sum()
    endv=li[li.t==end].assign(value_f=lambda x:x.value.astype(float)).groupby('lot_id').value_f.sum()
    startv=li[li.t==start-1].assign(value_f=lambda x:x.value.astype(float)).groupby('lot_id').value_f.sum()
    buys['mechanical_cashflow_plus_endmark']=buys.lot_id.map(cash).fillna(0)+buys.lot_id.map(endv).fillna(0)-buys.lot_id.map(startv).fillna(0)
    out=buys.groupby('group',as_index=False).agg(funded_trades=('lot_id','size'),funded_capital=('reserved',lambda x:float(x.astype(float).sum())),mechanical_cashflow_plus_endmark=('mechanical_cashflow_plus_endmark','sum'),mean_contribution=('mechanical_cashflow_plus_endmark','mean'),positive_contribution_fraction=('mechanical_cashflow_plus_endmark',lambda x:float((x>0).mean())))
    excluded=any_seed-ensemble_set
    out2=pd.DataFrame([{'family':family,'group':'SEED_FUNDED_EXCLUDED_BY_ENSEMBLE','signal_keys':len(excluded),'mechanical_account_contribution':None,'note':'NON_ADDITIVE: these are funded in different stateful seed accounts, so no ensemble-ledger PnL exists'}])
    out.insert(0,'family',family);out['note']='Exact ensemble-ledger lot cashflow plus year-end mark; non-additive across accounts.'
    return pd.concat([out,out2],ignore_index=True),buys

def main():
    pid=int((MASTER/'PIPELINE.lock').read_text().strip())
    try:os.kill(pid,0)
    except OSError as e:raise RuntimeError('MAIN_PIPELINE_NOT_ALIVE') from e
    stage=json.loads((MASTER/'ORCHESTRATION_STATE.json').read_text())
    keys=pd.read_parquet(FULL/'KEYS.parquet',columns=['t','j','decision_date']);r10=np.load(FULL/'ret10.npy',mmap_mode='r');r20=np.load(FULL/'ret20.npy',mmap_mode='r')
    if keys.duplicated(['t','j']).any() or len(keys)!=len(r10):raise RuntimeError('KEY_LABEL_IDENTITY')
    spec={'status':'FROZEN_2020_ONLY','created_at':datetime.now(timezone.utc).astimezone().isoformat(),'main_pid':pid,'stage_at_start':stage,'cpu_only':True,'torch_imported':False,'mps_used':False,'opened_2021':False,'opened_2022_2026':False,'no_new_ensemble':True,'families':['I0','MASTER'],'normalization':'same-date percentile on complete ex-ante eligible universe; 1=best'}
    dump(HERE/'SYNERGY_SPEC.json',spec)
    raw={'I0':{},'MASTER':{}}
    for s in SEEDS:
        raw['I0'][s]=np.asarray(np.load(FULL/f'I0_s{s}.npy',mmap_mode='r'),float)
        p=pd.read_parquet(PRED/f'M-GTS_s{s}.parquet',columns=['t','j','score'])
        if not np.array_equal(p[['t','j']].to_numpy(),keys[['t','j']].to_numpy()):raise RuntimeError(f'M_KEY_MISMATCH_{s}')
        raw['MASTER'][s]=p.score.to_numpy(float)
    P={f:{s:pct(keys,raw[f][s]) for s in SEEDS} for f in raw}; R={f:{s:rank(keys,P[f][s]) for s in SEEDS} for f in raw}
    ensemble={f:np.mean([P[f][s] for s in SEEDS],axis=0) for f in raw}; ER={f:rank(keys,ensemble[f]) for f in raw}
    # Frozen E0 parity makes sure the MASTER ensemble has not been reconstructed with different semantics.
    e0=pd.read_parquet(E0/'scores/E0_MEAN3_2020.parquet',columns=['t','j','score'])
    if not np.array_equal(e0[['t','j']].to_numpy(),keys[['t','j']].to_numpy()) or not np.allclose(e0.score.to_numpy(),ensemble['MASTER'],atol=0,rtol=0):raise RuntimeError('M_MEAN3_SCORE_PARITY_FAILURE')
    br=module('synergy_broader',BROADER); i0m,_=br.verify_a0(2020)
    e0acc=pd.read_csv(MASTER/'ensemble_tail_autopsy_v1/ENSEMBLE_ACCOUNT_2020.csv').set_index('arm').loc['E0_MEAN3']
    single=pd.read_csv(MASTER/'single_seed_account_diagnostic_v1/SINGLE_SEED_ACCOUNT_RESULTS.csv').set_index('arm')
    parity={'I0_FIXED3':{'return':i0m['annual_return'],'MaxDD':i0m['MaxDD'],'pass':abs(i0m['annual_return']-.174396)<1e-5 and abs(i0m['MaxDD']-.153134)<1e-5},'M_MEAN3':{'return':float(e0acc.annual_return),'MaxDD':float(e0acc.MaxDD),'pass':abs(float(e0acc.annual_return)-.015158)<1e-5 and abs(float(e0acc.MaxDD)-.165318)<1e-5},'single_seed_anchor':{f'{f}_s{s}':float(single.loc[f'{"I0" if f=="I0" else "M"}_s{s}','annual_return']) for f in raw for s in SEEDS}}
    if not all(parity[x]['pass'] for x in ('I0_FIXED3','M_MEAN3')):raise RuntimeError('ACCOUNT_PARITY_FAILURE')
    dump(HERE/'PARITY.json',parity)
    geo=[]; overlap=[]; support=[]; comp=[]; prd=[]; profiles=[]; hc=[]; dispersion=[]; calib=[]; percal=[]
    cuts=(5,10,20,50,100,200); buckets=((1,2),(3,5),(6,10),(11,20),(21,50),(51,100),(101,200))
    allr=pd.DataFrame({'ret10':np.asarray(r10,float),'ret20':np.asarray(r20,float)})
    for fam in raw:
        seed_top={n:{s:R[fam][s]<=n for s in SEEDS} for n in (10,20,50)}
        for _,ix in keys.groupby('t',sort=False).indices.items():
            date=str(keys.decision_date.iloc[ix[0]])[:10]
            for a,b in ((17,29),(17,43),(29,43)):
                geo.append({'family':fam,'date':date,'pair':f'{a}_{b}','spearman':float(pd.Series(P[fam][a][ix]).corr(pd.Series(P[fam][b][ix]),method='spearman'))})
                for n in cuts:overlap.append({'family':fam,'date':date,'pair':f'{a}_{b}','rank_cutoff':n,'jaccard':jacc(R[fam][a][ix]<=n,R[fam][b][ix]<=n)})
            for n in (10,20,50):
                supp=np.column_stack([seed_top[n][s][ix] for s in SEEDS]).sum(axis=1)
                for q in (1,2,3):
                    jj=np.asarray(ix)[supp==q];z=allr.iloc[jj];support.append({'family':fam,'top_n':n,'support_count':q,**metrics(z,f'{fam}_{n}_{q}')})
            # composition, retained/dropped/promoted and rank geometry on ensemble top10.
            s10=np.column_stack([seed_top[10][s][ix] for s in SEEDS]).sum(axis=1); em=ER[fam][ix]<=10
            for q in range(4):
                jj=np.asarray(ix)[em&(s10==q)];z=allr.iloc[jj];comp.append({'family':fam,'support_count':q,**metrics(z)})
            union=s10>0
            for name,mask in [('RETAINED',union&em),('DROPPED',union&~em),('PROMOTED',~union&em)]:
                jj=np.asarray(ix)[mask];z=allr.iloc[jj];prd.append({'family':fam,'classification':name,**metrics(z)})
            jj=np.asarray(ix)[em]; rr=np.column_stack([R[fam][s][jj] for s in SEEDS]);z=allr.iloc[jj].copy()
            z['best_rank']=rr.min(1);z['second_best_rank']=np.sort(rr,axis=1)[:,1];z['worst_rank']=rr.max(1);z['mean_rank']=rr.mean(1);z['median_rank']=np.median(rr,axis=1);z['rank_std']=rr.std(1);z['rank_range']=rr.max(1)-rr.min(1);z['family']=fam;profiles.append(z.drop(columns=['ret10','ret20']))
            # hc group rows are date-level contributions and aggregate afterwards.
            rrall=np.column_stack([R[fam][s][ix] for s in SEEDS]); groups={'HC1':(rrall.min(1)<=5)&(rrall.max(1)>100),'HC2':(rrall.min(1)<=10)&(rrall.max(1)>100),'CONSENSUS':(rrall<=50).all(1),'MODERATE':((rrall>=11)&(rrall<=100)).all(1)}
            for name,mask in groups.items():
                j2=np.asarray(ix)[mask];z=allr.iloc[j2];hc.append({'family':fam,'group':name,'count':int(mask.sum()),'ret10_sum':float(np.nansum(z.ret10)),'ret20_sum':float(np.nansum(z.ret20)),'ret10_obs':int(np.isfinite(z.ret10).sum()),'ret20_obs':int(np.isfinite(z.ret20).sum()),'ensemble_selected':int(em[mask].sum())})
            # fixed score calibration.
            for lo,hi in buckets:
                j2=np.asarray(ix)[(ER[fam][ix]>=lo)&(ER[fam][ix]<=hi)];z=allr.iloc[j2];calib.append({'family':fam,'bucket':f'{lo}-{hi}',**metrics(z)})
            for s in SEEDS:
                for lo,hi in buckets:
                    j2=np.asarray(ix)[(R[fam][s][ix]>=lo)&(R[fam][s][ix]<=hi)];z=allr.iloc[j2];percal.append({'family':fam,'seed':s,'bucket':f'{lo}-{hi}',**metrics(z)})
            # mean percentile decile, disagreement quintile within each date/decile.
            mean=ensemble[fam][ix];std=np.column_stack([P[fam][s][ix] for s in SEEDS]).std(1)
            dec=pd.qcut(pd.Series(mean).rank(method='first'),10,labels=False).to_numpy()+1
            for d in range(1,11):
                loc=np.flatnonzero(dec==d)
                quint=pd.qcut(pd.Series(std[loc]).rank(method='first'),min(5,len(loc)),labels=False).to_numpy()+1
                for q in np.unique(quint):
                    jj=np.asarray(ix)[loc[quint==q]];z=allr.iloc[jj];dispersion.append({'family':fam,'mean_percentile_decile':d,'std_quintile':int(q),**metrics(z)})
    def aggregate(rows,groups):
        d=pd.DataFrame(rows);return d.groupby(groups,as_index=False).agg(count=('count','sum'),ret10=('ret10',lambda x:float(pd.Series(x).mean())),ret20=('ret20',lambda x:float(pd.Series(x).mean())),positive_ret10=('positive_ret10','mean'),positive_ret20=('positive_ret20','mean'))
    gdf=pd.DataFrame(geo);gdf.to_csv(HERE/'GLOBAL_SEED_GEOMETRY.csv',index=False)
    odf=pd.DataFrame(overlap);oc=odf.groupby(['family','rank_cutoff'])['jaccard'].agg(['mean','median',lambda x:x.quantile(.1),lambda x:x.quantile(.9)]).reset_index();oc.columns=['family','rank_cutoff','mean','median','p10','p90'];oc.to_csv(HERE/'TAIL_OVERLAP_CURVE.csv',index=False)
    aggregate(support,['family','top_n','support_count']).to_csv(HERE/'SUPPORT_BUCKET_ECONOMICS.csv',index=False)
    aggregate(comp,['family','support_count']).to_csv(HERE/'ENSEMBLE_TOP10_COMPOSITION.csv',index=False)
    aggregate(prd,['family','classification']).to_csv(HERE/'PROMOTED_RETAINED_DROPPED.csv',index=False)
    prof=pd.concat(profiles,ignore_index=True)
    profile_summary=[]
    for fam,g in prof.groupby('family'):
        row={'family':fam,'count':int(len(g))}
        for col in ('best_rank','second_best_rank','worst_rank','mean_rank','median_rank','rank_std','rank_range'):
            row.update({f'{col}_mean':float(g[col].mean()),f'{col}_median':float(g[col].median()),f'{col}_p10':float(g[col].quantile(.1)),f'{col}_p90':float(g[col].quantile(.9))})
        profile_summary.append(row)
    pd.DataFrame(profile_summary).to_csv(HERE/'ENSEMBLE_TOP10_RANK_PROFILE.csv',index=False)
    h=pd.DataFrame(hc).groupby(['family','group'],as_index=False).agg(count=('count','sum'),ret10_sum=('ret10_sum','sum'),ret20_sum=('ret20_sum','sum'),ret10_obs=('ret10_obs','sum'),ret20_obs=('ret20_obs','sum'),ensemble_selected=('ensemble_selected','sum'));h['ret10']=h.ret10_sum/h.ret10_obs;h['ret20']=h.ret20_sum/h.ret20_obs;h['ensemble_selection_rate']=h.ensemble_selected/h['count'];h.to_csv(HERE/'HIGH_CONVICTION_DISAGREEMENT.csv',index=False)
    aggregate(dispersion,['family','mean_percentile_decile','std_quintile']).to_csv(HERE/'SCORE_DISPERSION_BUCKETS.csv',index=False)
    aggregate(calib,['family','bucket']).to_csv(HERE/'ENSEMBLE_RANK_CALIBRATION.csv',index=False)
    pc=aggregate(percal,['family','seed','bucket']);pc.to_csv(HERE/'PER_SEED_RANK_CALIBRATION.csv',index=False)
    # Accounts and daily account synergy: exact ledger identities.
    led={'I0_FIXED3':br.baseline_paths(2020)[1], 'M_MEAN3':E0/'accounts/2020/E0_MEAN3/ledgers'}
    pol={'I0_FIXED3':br.baseline_paths(2020)[0]['policy'],'M_MEAN3':'Y2020_ENSEMBLE_E0_MEAN3_ROOT'}
    for f,prefix in [('I0','I0'),('MASTER','M')]:
        for s in SEEDS:led[f'{f}_s{s}']=SINGLE/f'{prefix}_s{s}'/'ledgers';pol[f'{f}_s{s}']=f'Y2020_SINGLE_{prefix}_s{s}_ROOT'
    _,_,ts,_,_,_=br.context(2020); dates=br.context(2020)[0]
    nav={}
    for arm in led:
        x=br.read_ledger(led[arm],pol[arm],'nav').set_index('t').reindex(ts);rr=x.nav.astype(float).pct_change();rr.iloc[0]=float(x.nav.iloc[0])/1e6-1;nav[arm]=rr
    asr=[];daily=[];monthly=[]
    for fam,ens in [('I0','I0_FIXED3'),('MASTER','M_MEAN3')]:
        vals=[float(single.loc[f'{"I0" if fam=="I0" else "M"}_s{s}','annual_return']) for s in SEEDS];dds=[float(single.loc[f'{"I0" if fam=="I0" else "M"}_s{s}','MaxDD']) for s in SEEDS];eret=float(i0m['annual_return'] if fam=='I0' else e0acc.annual_return);edd=float(i0m['MaxDD'] if fam=='I0' else e0acc.MaxDD)
        asr.append({'family':fam,'single_seed_returns':json.dumps(vals),'mean_single_seed_return':float(np.mean(vals)),'best_single_seed_return':float(np.max(vals)),'worst_single_seed_return':float(np.min(vals)),'ensemble_return':eret,'ACCOUNT_SYNERGY':eret-float(np.mean(vals)),'mean_single_seed_MaxDD':float(np.mean(dds)),'ensemble_MaxDD':edd})
        meanseed=pd.concat([nav[f'{fam}_s{s}'] for s in SEEDS],axis=1).mean(axis=1);sy=nav[ens]-meanseed
        d=pd.DataFrame({'family':fam,'t':ts,'date':[dates[t] for t in ts],'ensemble_daily_return':nav[ens].to_numpy(),'mean_single_seed_daily_return':meanseed.to_numpy(),'ensemble_daily_synergy':sy.to_numpy()});daily.append(d)
        m=d.assign(month=lambda x:x.date.str[:7]).groupby('month',as_index=False).agg(ensemble_daily_synergy_sum=('ensemble_daily_synergy','sum'),positive_days=('ensemble_daily_synergy',lambda x:int((x>0).sum())),days=('t','size'));m.insert(0,'family',fam);monthly.append(m)
    asdf=pd.DataFrame(asr);asdf.to_csv(HERE/'ACCOUNT_SYNERGY_SUMMARY.csv',index=False);pd.concat(daily).to_csv(HERE/'DAILY_ACCOUNT_SYNERGY.csv',index=False);pd.concat(monthly).to_csv(HERE/'MONTHLY_ACCOUNT_SYNERGY.csv',index=False)
    # Exact ledger funded trade support / non-additive holding-path descriptors.
    etrades=[]; holding=[]
    for fam,ens,prefix in [('I0','I0_FIXED3','I0'),('MASTER','M_MEAN3','M')]:
        seed_sets=[]
        for s in SEEDS:
            o=br.read_ledger(led[f'{fam}_s{s}'],pol[f'{fam}_s{s}'],'orders');q=o[(o.side=='BUY')&(o.status=='FILLED')&(o.decision_t>=3163)];seed_sets.append(set(zip(q.decision_t.astype(int),q.j.astype(int))))
        eo=br.read_ledger(led[ens],pol[ens],'orders');q=eo[(eo.side=='BUY')&(eo.status=='FILLED')&(eo.decision_t>=3163)];ensset=set(zip(q.decision_t.astype(int),q.j.astype(int)))
        a,b=lot_contribution(br,led[ens],pol[ens],keys,ensset,seed_sets,fam);etrades.append(a)
        # support inside actual ensemble funded buys.
        q=q.copy();q['support']=[sum((t,j) in x for x in seed_sets) for t,j in zip(q.decision_t.astype(int),q.j.astype(int))]
        hq=q.groupby('support',as_index=False).agg(funded_trades=('j','size'),funded_capital=('reserved',lambda x:float(x.astype(float).sum())));hq['family']=fam;holding.append(hq)
    pd.concat(etrades,ignore_index=True).to_csv(HERE/'ENSEMBLE_ONLY_TRADES.csv',index=False);pd.concat(holding,ignore_index=True).to_csv(HERE/'RETAINED_FUNDED_SUPPORT.csv',index=False)
    hp=[]
    for fam in ('I0','MASTER'):
        d=asdf[asdf.family.eq(fam)].iloc[0];hp.append({'family':fam,'NEW_NAME_SELECTION':'DESCRIPTIVE_ONLY: see ENSEMBLE_ONLY_TRADES.csv','SAME_NAME_DIFFERENT_ENTRY':'NON_ADDITIVE','CAPITAL_AVAILABILITY':'NON_ADDITIVE','CARRY_INTERACTION':'NON_ADDITIVE','OTHER_UNATTRIBUTABLE':'Account NAV is nonlinear/stateful; no additive allocation is asserted.','account_synergy':d.ACCOUNT_SYNERGY})
    pd.DataFrame(hp).to_csv(HERE/'HOLDING_PATH_DIAGNOSTIC.csv',index=False)
    # Classification from symmetric, predeclared descriptors.
    pr=pd.read_csv(HERE/'PROMOTED_RETAINED_DROPPED.csv').set_index(['family','classification']); cal=pd.read_csv(HERE/'ENSEMBLE_RANK_CALIBRATION.csv').set_index(['family','bucket'])
    i0drop, i0ret=pr.loc[('I0','DROPPED'),'ret20'],pr.loc[('I0','RETAINED'),'ret20']; md, mr=pr.loc[('MASTER','DROPPED'),'ret20'],pr.loc[('MASTER','RETAINED'),'ret20']
    i0_mech='CONSENSUS_DENOISING_AND_TAIL_SHARPENING' if i0ret>i0drop and cal.loc[('I0','1-2'),'ret20']>cal.loc[('I0','21-50'),'ret20'] else 'MIXED'
    m_mech='TAIL_ALPHA_COMPRESSION' if md>mr else 'MIXED'
    packet={'status':'COMPLETE','main_pipeline_untouched':True,'main_pid_alive':True,'cpu_only':True,'parity':parity,'I0_ENSEMBLE_MECHANISM':i0_mech,'MASTER_ENSEMBLE_MECHANISM':m_mech,'are_mechanisms_opposite':bool(i0_mech=='CONSENSUS_DENOISING_AND_TAIL_SHARPENING' and m_mech=='TAIL_ALPHA_COMPRESSION'),'no_new_ensemble_created':True,'no_model_selection_changed':True,'no_new_training':True,'opened_2021':False,'opened_2022':False,'opened_2023':False,'opened_2024_2026':False}
    dump(HERE/'SYNERGY_DECISION_PACKET.json',packet)
    report=['# I0 vs MASTER Seed Ensemble Synergy Anatomy, 2020','', 'Read-only CPU diagnostic. Frozen 2020 scores and existing account ledgers only.','', '## Account synergy','',asdf.to_markdown(index=False),'','## Global geometry','',gdf.groupby('family').spearman.agg(['mean','median','min','max']).to_markdown(),'','## Mechanism','',f'**I0 = {i0_mech}**  ',f'**MASTER = {m_mech}**','', 'Account paths are stateful; lot-level trade groups are descriptive and no additive causal PnL allocation is claimed.','']
    (HERE/'ENSEMBLE_SYNERGY_ANATOMY_REPORT.md').write_text('\n'.join(report))

if __name__=='__main__':main()
