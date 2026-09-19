"""Read frozen selections, materialize missing daily predictions, evaluate A/B/C separately."""
import joblib, torch
import pandas as pd
from common import get, module, old
from o2_nested_earlystop import *
from account_daily_inference import membership, stock_inputs
from train import predict
from ranking_audit_summary import hac_mean
import o3_pilot_metrics as metrics

ARMS=['EARLYSTOP','MATCHED_NESTED_32K','ORIGINAL_INCUMBENT_32K']
CONTRASTS={'A':(ARMS[1],ARMS[0]),'B':(ARMS[2],ARMS[1]),'C':(ARMS[2],ARMS[0])}

def mean(v):
    v=np.asarray(v);return float(np.nanmean(v)) if np.isfinite(v).any() else np.nan

def infer_year(year):
    dest=DEST/f'{year}_s17';target=dest/'DAILY.parquet';proof=dest/'DAILY.json'
    s=json.loads((dest/'SELECTION.json').read_text());complete=json.loads((dest/'COMPLETE.json').read_text())
    assert complete['selection_sha256']==sha(dest/'SELECTION.json')
    checkpoints={'EARLYSTOP':dest/f"step{s['selected']['step']}.pt",'MATCHED_NESTED_32K':dest/'step32768.pt'}
    assert sha(checkpoints['EARLYSTOP'])==s['selected']['checkpoint_sha256'] and sha(checkpoints['MATCHED_NESTED_32K'])==complete['checkpoint_sha256']
    if proof.exists():assert sha(target)==json.loads(proof.read_text())['sha256'];return pd.read_parquet(target)
    meta=json.loads((PANEL/'axes.json').read_text());dates=np.array(meta['dates']);assert dates[-1]<'2024'
    end=int(np.searchsorted(dates,f'{year+1}-01-01'));ts,member,_,_=membership(meta);sel=np.char.startswith(dates[ts],str(year));ts=ts[sel];member=member[sel]
    keys=['safe','history','adj_close','adj_open','adj_high','adj_low','adj_volume','close','circulating_shares','turnover_fraction','amount','industry_return','market','coordok','entryok','exitok']
    a={k:get(k)[:end] for k in keys};valid=member&a['safe'][ts]&(a['history'][ts]>=60);eligible=np.flatnonzero(valid.any(0));market=a['market'][:,3];mr=[]
    for h in [3,20,60]:
        v=np.full(end,np.nan);v[h:]=market[h:]/market[:-h]-1;mr.append(v)
    base=joblib.load(dest/'M0.joblib');models={}
    for name,path in checkpoints.items():
        ck=torch.load(path,map_location='cpu',weights_only=False);assert ck['identity']['protocol_sha256']==sha(PROTOCOL)
        m=PathResidual(ck['config']);m.load_state_dict(ck['state']);models[name]=m.eval()
    idx=pd.read_parquet(OUT/'index.parquet');idx=idx[idx.year==year];banks=[np.load(OUT/f'{k}.npy',mmap_mode='r') for k in ['raw','legs','factors']];frozen_labels=np.load(OUT/'labels.npy',mmap_mode='r')
    admission=json.loads((DOC/'DAILY_s17_ADMISSION.json').read_text());assert sha(admission['prediction_path'])==admission['sha256']
    incumbent=pd.read_parquet(admission['prediction_path']);incumbent=incumbent[incumbent.year==year].set_index(['t','j'])
    enc=old('features');engine=module('_nested_labels',HERE.parent/'ashare_wave_structure_v1/engine.py')
    shards=dest/'daily_stocks';shards.mkdir(exist_ok=True)
    identity=dict(selection_sha256=sha(dest/'SELECTION.json'),matched_sha256=sha(checkpoints['MATCHED_NESTED_32K']),incumbent_sha256=admission['sha256'],protocol_sha256=sha(PROTOCOL),label_source_sha256=sha(HERE.parent/'ashare_wave_structure_v1/engine.py'))
    write(dest/'DAILY_IDENTITY.json',identity,immutable=True)
    for no,j in enumerate(eligible):
        deadline();path=shards/f'{j:05}.parquet';seal=path.with_suffix('.json')
        if seal.exists():assert sha(path)==json.loads(seal.read_text())['sha256'];continue
        tt=ts[valid[:,j]];raw,legs,factors=stock_inputs(j,tt,a,mr,enc);common=idx[idx.j==j];ii=np.searchsorted(tt,common.t);assert np.array_equal(tt[ii],common.t)
        for bank,v in zip(banks,[raw,legs,factors]):assert np.array_equal(bank[common.index],v[ii],equal_nan=True)
        z=base['scale'].transform(np.nan_to_num(factors).astype('float64'));offset=np.column_stack([f.predict(z) for f in base['fits']]).astype('float32')
        out=pd.DataFrame(dict(t=tt,j=int(j),decision_date=dates[tt],year=year,stock=meta['symbols'][j]))
        for name,m in models.items():
            pred=np.empty((len(tt),3),np.float32)
            with torch.no_grad():
                for start in range(0,len(tt),256):
                    stop=min(start+256,len(tt));x=np.concatenate([raw[start:stop].astype('float32'),np.broadcast_to(offset[start:stop,None,None,:],(stop-start,4,32,3))],-1)
                    pred[start:stop]=m(torch.from_numpy(x),torch.from_numpy(legs[start:stop].astype('float32')))[0][:,:3].numpy()/10
            for k,h in enumerate([10,20,40]):out[f'{name}_pred{h}']=pred[:,k]
        oldpred=incumbent.loc[list(zip(tt,np.repeat(j,len(tt))))]
        for h in [10,20,40]:out[f'ORIGINAL_INCUMBENT_32K_pred{h}']=oldpred[f'pred{h}'].to_numpy()
        # Existing training label function, unchanged. Bound the array at outer-year end.
        ret,_,mae=engine.labels(*[np.ascontiguousarray(a[k][:,j:j+1]) for k in ['adj_open','adj_high','adj_low','coordok','entryok','exitok']])
        for k,h in enumerate([10,20,40]):
            out[f'ret{h}']=ret[tt,0,k+1];known=common.t.to_numpy()+1+h<end
            assert np.array_equal(out[f'ret{h}'].to_numpy()[ii[known]],frozen_labels[common.index[known],k],equal_nan=True)
        out['mae20']=mae[tt,0,2]
        tmp=path.with_suffix('.tmp');out.to_parquet(tmp,index=False);tmp.replace(path);write(seal,dict(sha256=sha(path),feature_parity=True,label_parity=True))
        if no%100==0:print('DAILY',year,no+1,len(eligible),flush=True)
    frame=pd.concat([pd.read_parquet(shards/f'{j:05}.parquet') for j in eligible],ignore_index=True).sort_values(['t','j'])
    assert set(zip(frame.t,frame.j))==set(incumbent.index) and not frame.duplicated(['t','j']).any()
    tmp=target.with_suffix('.tmp');frame.to_parquet(tmp,index=False);tmp.replace(target);write(proof,dict(sha256=sha(target),rows=len(frame),identity=identity,labels='Frozen O2 adjusted-open Ret10/20/40; intraday-low MAE20 from same unchanged engine, not net-account PnL; year-end maturity enforced'))
    return frame

def daily_metrics(frame):
    metrics.LOCAL=[.0025,.005,.01,.02,.05,.1];metrics.TOPK=[5,10,20,30,50,100,200];metrics.PCTS=[.0025,.005,.01,.02,.05,.1]
    result=[]
    for (year,t),g in frame.groupby(['year','t']):
        for arm in ARMS:
            score=g[f'{arm}_pred20'].to_numpy();order=np.lexsort((g.j.to_numpy(),-score));y=g.ret20.to_numpy();mae=g.mae20.to_numpy()
            rows=metrics.day_metrics(g,f'{arm}_pred20','ret20')
            for h in [10,40]:rows.append(dict(scope='GLOBAL',metric=f'mse{h}',value=mean((g[f'{arm}_pred{h}']-g[f'ret{h}'])**2),n=int(g[f'ret{h}'].notna().sum())))
            for scope,k in [(f'P{p:g}',max(1,int(np.ceil(len(g)*p)))) for p in metrics.PCTS]+[('LOCAL_K20',20),('LOCAL_K50',50)]:
                ix=order[:k];v=y[ix];ok=np.isfinite(v);m=mae[ix];mok=np.isfinite(m)
                vals={'positive_ratio':float(np.mean(v[ok]>0)) if ok.any() else np.nan,'large_loss_frequency':float(np.mean(v[ok]<-.1)) if ok.any() else np.nan,'mae20':mean(m),'mae_large_loss_frequency':float(np.mean(m[mok]<-.1)) if mok.any() else np.nan,'return_coverage':ok.mean(),'mae_coverage':mok.mean()}
                if scope.startswith('LOCAL_'):vals['rank_ic']=metrics.corr(score[ix],v)
                rows.extend(dict(scope=scope,metric=k,value=v,n=len(ix)) for k,v in vals.items())
            result.extend(dict(year=int(year),t=int(t),date=g.decision_date.iloc[0],arm=arm,**r) for r in rows)
    return pd.DataFrame(result)

def summarize(daily):
    summary=daily.groupby(['year','arm','scope','metric']).agg(mean=('value','mean'),median=('value','median'),std=('value','std'),dates=('value','count'),positive_ratio=('value',lambda v:float((v.dropna()>0).mean()))).reset_index();summary.to_csv(DOC/'O2_NESTED_STAGE_A_ABSOLUTES.csv',index=False)
    keys=['year','t','date','scope','metric'];pairs=[]
    for label,(baseline,candidate) in CONTRASTS.items():
        a=daily[daily.arm==baseline][keys+['value']];b=daily[daily.arm==candidate][keys+['value']];g=a.merge(b,on=keys,suffixes=('_baseline','_candidate'),validate='one_to_one');g['delta']=g.value_candidate-g.value_baseline;g['comparison']=label;pairs.append(g)
    pairs=pd.concat(pairs,ignore_index=True);pairs['month']=pairs.date.str[:7];pairs['quarter']=pd.to_datetime(pairs.date).dt.to_period('Q').astype(str);pairs.to_parquet(DEST/'STAGE_A_PAIRED.parquet',index=False)
    sums=[]
    for (comparison,scope,metric),g in pairs.groupby(['comparison','scope','metric']):
        for year,v in [*g.groupby('year'),('ALL',g)]:
            h=hac_mean(v,'delta');monthly=v.groupby('month').delta.mean();best=monthly.idxmax() if monthly.notna().any() else None;worst=monthly.idxmin() if monthly.notna().any() else None
            sums.append(dict(comparison=comparison,year=year,scope=scope,metric=metric,baseline=v.value_baseline.mean(),candidate=v.value_candidate.mean(),delta=v.delta.mean(),equal_year_delta=v.groupby('year').delta.mean().mean(),hac20_se=h['se'],low95=h['lower'],high95=h['upper'],dates=h['n'],leave_best_month_out=v[v.month!=best].groupby('year').delta.mean().mean(),leave_worst_month_out=v[v.month!=worst].groupby('year').delta.mean().mean()))
    table=pd.DataFrame(sums);table.to_csv(DOC/'O2_NESTED_STAGE_A_COMPARISONS.csv',index=False)
    for period in ['month','quarter']:pairs.groupby(['comparison',period,'scope','metric'])[['value_baseline','value_candidate','delta']].mean().to_csv(DOC/f'O2_NESTED_STAGE_A_{period.upper()}.csv')
    return table

def main():
    torch.set_num_threads(1)
    for b in json.loads(PROTOCOL.read_text())['sources']:assert sha(b['path'])==b['sha256']
    all_daily=[]
    for year in range(2020,2024):
        deadline();dest=DEST/f'{year}_s17';p=dest/'METRICS.parquet'
        if not p.exists():daily_metrics(infer_year(year)).to_parquet(p,index=False)
        all_daily.append(pd.read_parquet(p))
    daily=pd.concat(all_daily,ignore_index=True);table=summarize(daily)
    # Report the frozen gate components; retain signed numbers, not only a pass count.
    a=table[table.comparison=='A'];annual=a[a.year!='ALL'];allrow=a[a.year=='ALL']
    def rows(scope,metric):return annual[(annual.scope==scope)&(annual.metric==metric)]
    def tail_branch(scopes,metric):
        v=[rows(s,metric).set_index('year') for s in scopes]
        years=sum(all(x.loc[y,'delta']>0 for x in v) for y in range(2020,2024))
        catastrophic=any(all(x.loc[y,'high95']<0 for x in v) for y in range(2020,2024))
        broad=all(float(allrow[(allrow.scope==s)&(allrow.metric==metric)].leave_best_month_out.iloc[0])>0 for s in scopes)
        return dict(improved_years=years,catastrophic=bool(catastrophic),not_single_month=bool(broad),pass_gate=bool(years>=3 and not catastrophic and broad))
    ic=rows('GLOBAL','rank_ic');mse=rows('GLOBAL','mse20');local=tail_branch(['LOCAL_0.01','LOCAL_0.05'],'rank_ic');top=tail_branch(['K5','K10'],'lift')
    checks=dict(mse_improved_years=int((mse.delta<0).sum()),global_mean_preserved=bool(ic.delta.mean()>=0),global_catastrophic=bool((ic.high95<0).any()),local=local,topk=top)
    passed=checks['mse_improved_years']>=3 and checks['global_mean_preserved'] and not checks['global_catastrophic'] and (local['pass_gate'] or top['pass_gate'])
    verdict='EARLY_STOPPING_ALPHA_CANDIDATE' if passed else 'MSE_OVERTRAINING_WITHOUT_ALPHA_OVERTRAINING' if checks['mse_improved_years']>=3 and ic.delta.mean()<=0 and not local['pass_gate'] and not top['pass_gate'] else 'INCONCLUSIVE'
    write(DOC/'O2_NESTED_STAGE_A_GATE.json',dict(at=now(),stage='A',seed=17,checks=checks,stage_b_signal_gate_passed=bool(passed),verdict=verdict,evidence_strength='DIRECTIONAL_SUPPORT' if passed else 'INCONCLUSIVE',no_account_run=True,protocol_sha256=sha(PROTOCOL)))
    core=table[(table.scope.isin(['GLOBAL','LOCAL_0.01','LOCAL_0.05','K5','K10','K50']))&(table.metric.isin(['mse20','rank_ic','lift']))]
    (DOC/'O2_NESTED_STAGE_A_REPORT.md').write_text('# '+verdict+'\n\nSeed17 only; 2020–2023 development, not final validation.\n\n'+json.dumps(checks,indent=2)+'\n\nA: early versus matched nested32k (duration). B: matched nested32k versus original incumbent (window). C: early versus original incumbent (practical). The primary mechanism gate applies to A; C remains separately reportable. No account was run.\n\n'+core[['comparison','year','scope','metric','baseline','candidate','delta','low95','high95']].to_markdown(index=False)+'\n\nIntervals: same-date paired differences, Bartlett HAC20 using actual trading-session distance. Missing labels remain missing. LocalIC uses >=5 observed names. MAE is frozen label-engine intraday-low coordinate, not realized account return. Full coverage, monthly and quarterly tables accompany this report. A gate pass authorizes limited fixed-seed replication only, never production promotion.\n')
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,3,figsize=(19,10))
    for ax,(scope,metric) in zip(axes.flat,[('GLOBAL','mse20'),('GLOBAL','rank_ic'),('LOCAL_0.01','rank_ic'),('LOCAL_0.05','rank_ic'),('K10','lift'),('K50','lift')]):
        for arm,g in daily[(daily.scope==scope)&(daily.metric==metric)].groupby('arm'):
            v=g.groupby('year').value.mean();ax.plot(v.index,v.values,marker='o',label=arm)
        ax.set_title(f'{scope} / {metric}');ax.grid(alpha=.2);ax.set_xticks(range(2020,2024));ax.legend(fontsize=7)
    fig.suptitle('O2 nested H2 / seed17 / development only');fig.tight_layout();fig.savefig(DOC/'O2_NESTED_STAGE_A_KEY_RESULTS.png',dpi=150);plt.close(fig)
    print(verdict,checks,flush=True)

if __name__=='__main__':main()
