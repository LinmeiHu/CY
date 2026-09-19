"""Frozen conditional risk test; outcome missingness never defines candidate bins."""
import argparse, re
import pandas as pd
from common import *

CARD = 'FORWARD_DEVELOPMENT'

def contract():
    return json.loads(re.search(r'```json\s*(.*?)\s*```', (HERE/'RESEARCH_CONTRACT.md').read_text(), re.S).group(1))

def date_statistics(frame, rules):
    rows = []
    for t, g in frame.groupby('t', sort=True):
        g = g.sort_values(['pred20','j']).copy()
        # Full prediction set first; ties in Ret20 have deterministic stock ordering.
        g['return_bin'] = np.arange(len(g))*rules['return_bins']//len(g)
        bins = []
        for _, z in g.groupby('return_bin'):
            z = z.sort_values(['path_down10','j']).copy()
            z['risk_bin'] = np.arange(len(z))*rules['risk_bins']//len(z)
            low = z[z.risk_bin == 0]; high = z[z.risk_bin == rules['risk_bins']-1]
            lo = low[np.isfinite(low.mae)]; hi = high[np.isfinite(high.mae)]
            ok = z[np.isfinite(z.mae)]
            if len(lo)<10 or len(hi)<10 or z.path_down10.nunique()<2:continue
            failure_gap = float((hi.mae<-.1).mean()-(lo.mae<-.1).mean())
            severity_gap = float(lo.mae.mean()-hi.mae.mean())
            ic = ok.path_down10.corr(-ok.mae, method='spearman') if ok.mae.nunique()>1 else np.nan
            lr=low.ret20.dropna();hr=high.ret20.dropna()
            bins.append(dict(failure_gap=failure_gap,mae_severity_gap=severity_gap,risk_ic=ic,
                low_risk_ret20_mean=float(lr.mean()),high_risk_ret20_mean=float(hr.mean()),
                low_risk_ret20_median=float(lr.median()),high_risk_ret20_median=float(hr.median()),
                low_minus_high_ret20_mean=float(lr.mean()-hr.mean()),low_minus_high_ret20_median=float(lr.median()-hr.median()),
                terminal_loss_gap=float((hr<-.1).mean()-(lr<-.1).mean()) if len(lr) and len(hr) else np.nan,
                return_prediction_gap=float(high.pred20.mean()-low.pred20.mean()),
                low_risk_label_coverage=len(lo)/len(low),high_risk_label_coverage=len(hi)/len(high)))
        if bins:
            rows.append(dict(t=int(t),year=int(g.year.iloc[0]),date=g.decision_date.iloc[0],
                candidate_count=len(g),valid_bins=len(bins),risk_label_coverage=float(g.mae.notna().mean()),
                **pd.DataFrame(bins).mean().to_dict()))
    return pd.DataFrame(rows)

def adjudicate(per, rules):
    if per.empty:return dict(status='INSUFFICIENT_SUPPORT',risk_information=False,annual=[],intervals={})
    cols=['failure_gap','mae_severity_gap','risk_ic','terminal_loss_gap','return_prediction_gap','low_minus_high_ret20_mean','low_minus_high_ret20_median']
    annual=per.groupby('year')[cols].mean();counts=per.groupby('year').size()
    rng=np.random.default_rng(rules['bootstrap_seed']);draws=[]
    # Resample consecutive decision-date blocks inside each year, never individual stocks.
    for _ in range(rules['bootstrap_draws']):
        sampled=[]
        for _,g in per.groupby('year'):
            n=len(g);starts=rng.integers(0,n,size=int(np.ceil(n/rules['bootstrap_blocks'])))
            idx=np.concatenate([(s+np.arange(rules['bootstrap_blocks']))%n for s in starts])[:n]
            sampled.append(g.iloc[idx][cols].mean().to_numpy())
        draws.append(np.nanmean(sampled,axis=0))
    bounds=np.nanquantile(draws,[rules['lower_quantile'],1-rules['lower_quantile']],axis=0)
    intervals={col:dict(low=float(bounds[0,i]),high=float(bounds[1,i])) for i,col in enumerate(cols)}
    supported=set(annual.index)=={2022,2023} and bool((counts>=rules['minimum_dates_each_year']).all())
    directional=bool((annual[['failure_gap','mae_severity_gap','risk_ic']]>0).all().all())
    informative=supported and directional and intervals['failure_gap']['low']>0 and intervals['mae_severity_gap']['low']>0
    preservation=bool((annual[['low_minus_high_ret20_mean','low_minus_high_ret20_median']]>=-.01).all().all())
    return dict(status='INFORMATION_SUPPORTED_IN_DEVELOPMENT' if informative else 'NO_STABLE_CONDITIONAL_RISK_INFORMATION' if supported else 'INSUFFICIENT_SUPPORT',
                risk_information=informative,return_preservation=preservation,return_preservation_rule='Low-risk Ret20 mean/median no more than1 percentage point below high-risk within each development year; frozen diagnostic tolerance',
                combined=per[cols].mean().to_dict(),annual=[dict(year=int(y),dates=int(counts[y]),**r.to_dict()) for y,r in annual.iterrows()],intervals=intervals)

def main():
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=17);p.add_argument('--probe',action='store_true');a=p.parse_args();c=contract();frames=[];bindings=[]
    index=pd.read_parquet(OUT/'index.parquet');lookup=pd.MultiIndex.from_frame(index[['t','j']])
    mae=np.load(OUT/'mae_close20.npy',mmap_mode='r');labels=np.load(OUT/'labels.npy',mmap_mode='r')
    audit=json.loads((HERE/'MAE_LABEL_AUDIT.json').read_text());assert sha(OUT/'mae_close20.npy')==audit['label_sha256']
    dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates'])
    for year in c['development_years']:
        name=f'M1_FROZENRISK_{year}_s{a.seed}' if a.probe else f'M1_PATHRISK_{year}_s{a.seed}_O2_B{c["steps"]}';path=OUT/f'{name}_{CARD}_pred.parquet'
        f=pd.read_parquet(path);assert set(f.year)=={year} and set(f.scorecard)=={CARD}
        assert not f.duplicated(['t','j']).any() and np.isfinite(f[['pred20','path_down10']]).all().all()
        assert f.path_down10.between(0,1).all()
        ck=json.loads((HERE/f'{name}_{"RISK_PROBE" if a.probe else "TRAINING"}.json').read_text())
        assert (ck['fit_cutoff'] if a.probe else ck['coverage']['fit_cutoff'])<f'{year}-01-01'
        rr=lookup.get_indexer(pd.MultiIndex.from_frame(f[['t','j']]));assert (rr>=0).all()
        end=np.searchsorted(dates,f'{year}-12-31',side='right')-1;mature=f.t.to_numpy()+21<=end
        f['mae']=np.where(mature,mae[rr],np.nan);f['ret20']=np.where(mature,labels[rr,1],np.nan)
        frames.append(f);bindings.append(dict(path=str(path),sha256=sha(path)))
    full=pd.concat(frames,ignore_index=True);per=date_statistics(full,c['risk_check']);result=adjudicate(per,c['risk_check'])
    if a.probe:
        severity=full.copy();severity['path_down10']=-severity.predicted_mae20
        severity_per=date_statistics(severity,c['risk_check']);result['severity_head']=adjudicate(severity_per,c['risk_check'])
        severity_per.to_csv(HERE/f'FROZENRISK_s{a.seed}_SEVERITY_CONDITIONAL_DATES.csv',index=False)
    prefix=f'{"FROZENRISK" if a.probe else "PATHRISK"}_s{a.seed}'
    per.to_csv(HERE/f'{prefix}_CONDITIONAL_DATES.csv',index=False)
    result.update(at=now(),seed=a.seed,rules=c['risk_check'],inputs=bindings,contract_sha256=sha(HERE/'RESEARCH_CONTRACT.md'),
        limitation='Consumed2022/2023 development; means and medians are equal-date averages of within-return-bin group means/medians, not pooled-stock statistics. Coarse conditioning is not causal independence; missing safe-path labels are conditional and not used to discard account requests; date/block inference, not independent stocks.')
    dump(f'{prefix}_CONDITIONAL_RISK.json',result);print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
