"""One observation per candidate; path rank effects with within-date controls."""
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,log,parquet

def main():
    log('RANK_DEDUP','DIAGNOSTIC','V3 duplicated identical event rows under route names',
        '去重候选、实际连续路径分数、同日排名交换和路径×状态；不重训权重', 'D05/H02 and D01/D02 same candidates',
        '区分全候选弱关系与实际资金选择差异', '控制后路径关系跨零且资金增量不稳定')
    ev=pd.read_parquet(OUT/'event_cash_diagnostics.parquet');state=pd.read_parquet(OUT/'state_daily.parquet')
    controls=pd.read_parquet(V3/'statistics/signal_event_diagnostics.parquet')
    nuisance=['pre_return30','pre_max30','pre_volatility30','pre_beta120','log_liquidity20','log_float_cap']
    rows=[];exchanges=[];details=[]
    for base,new in [('D05','H02'),('D01','D02')]:
        a=pd.read_parquet(V3/f'{base}_signals.parquet');b=pd.read_parquet(V3/f'{new}_signals.parquet')
        a=a.merge(b[['t','j','score']],on=['t','j'],validate='one_to_one',suffixes=('_base','_path'))
        a['path_score']=2*a.score_path-a.score_base if new=='H02' else a.Path
        a['rank_base']=a.groupby('t').score_base.rank(ascending=False,method='first');a['rank_path']=a.groupby('t').score_path.rank(ascending=False,method='first')
        a=a.merge(ev[ev.route==base][['t','j','net_return','label_available_t']],on=['t','j'],validate='one_to_one').merge(state[['t','S1']],on='t')
        a=a.merge(controls[controls.route==base][['t','j']+nuisance],on=['t','j'],validate='one_to_one')
        a['pair']=new+'/'+base
        for mode in ['C_MAX','C_10']:
            for route in [base,new]:
                od=pd.read_parquet(V3/f'A_{route}_{mode}_E10/orders.parquet')
                hit=od[od.status=='FILLED'][['signal_t','symbol','debit']].rename(columns={'signal_t':'t','debit':f'debit_{route}_{mode}'})
                a=a.merge(hit,on=['t','symbol'],how='left',validate='one_to_one')
                selected=od[~od.status.isin(['HELD','SLOTS_OR_RANK','PHYSICAL_SECURITY_DEDUP','NO_CASH','END_BOUNDARY_NO_ENTRY_SESSION'])][['signal_t','symbol']].rename(columns={'signal_t':'t'})
                selected[f'selected_{route}_{mode}']=True
                a=a.merge(selected,on=['t','symbol'],how='left',validate='one_to_one')
        details.append(a)
        for st,g in a.groupby('S1'):
            exchanges.append(dict(pair=new+'/'+base,state=st,n=len(g),dates=g.t.nunique(),rank_changed=(g.rank_base!=g.rank_path).mean(),
                promoted_top10=int(((g.rank_path<=10)&(g.rank_base>10)).sum()),base_top10_return=g[g.rank_base<=10].groupby('t').net_return.mean().mean(),path_top10_return=g[g.rank_path<=10].groupby('t').net_return.mean().mean()))
        for layer,mask in [('ALL',np.ones(len(a),bool)),('TOP10_EITHER',(a.rank_base<=10)|(a.rank_path<=10)),('ACTUAL_SELECTED_EITHER_C10',a[f'selected_{base}_C_10'].notna()|a[f'selected_{new}_C_10'].notna()),('ALLOCATED_EITHER_C10',a[f'debit_{base}_C_10'].notna()|a[f'debit_{new}_C_10'].notna())]:
            g=a.loc[mask].dropna(subset=nuisance+['net_return','path_score','score_base']).copy()
            x=g[['path_score','score_base']+nuisance].copy()
            for st in ['HIGH_NONIMPROVING','LOW_IMPROVING','LOW_NONIMPROVING']:x['path_x_'+st]=g.path_score*(g.S1==st)
            x=pd.concat([x,pd.get_dummies(g[['board','industry']].astype(str),drop_first=True,dtype=float)],axis=1)
            x=x-x.groupby(g.t).transform('mean');y=g.net_return-g.groupby('t').net_return.transform('mean');xx=x.to_numpy();yy=y.to_numpy()
            coef=np.linalg.lstsq(xx,yy,rcond=1e-10)[0];res=yy-np.einsum('ij,j->i',xx,coef,optimize=False)
            gram=np.einsum('ni,nj->ij',xx,xx,optimize=False);values,vectors=np.linalg.eigh(gram);keep=values>values.max()*1e-10
            bread=np.einsum('ik,k,jk->ij',vectors[:,keep],1/values[keep],vectors[:,keep],optimize=False);meat=np.zeros_like(bread)
            for ix in g.groupby(g.t//20).indices.values():
                z=np.einsum('ij,i->j',xx[ix],res[ix],optimize=False);meat+=np.outer(z,z)
            se=np.sqrt(np.maximum(0,np.diag(np.einsum('ij,jk,kl->il',bread,meat,bread,optimize=False))))
            assert np.isfinite(coef).all() and np.isfinite(se).all()
            for term,beta,err in zip(x.columns,coef,se):rows.append(dict(pair=new+'/'+base,layer=layer,term=term,n=len(g),dates=g.t.nunique(),coefficient=beta,block20_se=err,ci_low=beta-1.96*err,ci_high=beta+1.96*err,status='DESCRIPTIVE_DATE_FIXED_EFFECTS_NO_STATE_MAIN_EFFECT'))
    pd.DataFrame(rows).to_csv(HERE/'ranking_diagnostic.csv',index=False);pd.DataFrame(exchanges).to_csv(HERE/'ranking_exchange.csv',index=False);parquet(OUT/'ranking_unique_candidates.parquet',pd.concat(details,ignore_index=True))

if __name__=='__main__':main()
