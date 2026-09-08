"""State versus year, market beta diagnostics, gate and capital-path explanations."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,parquet,dump

def r2(y,x):
    x=np.column_stack([np.ones(len(y)),np.asarray(x,dtype=float)]);coef=np.linalg.lstsq(x,y,rcond=None)[0]
    res=y-np.einsum('ij,j->i',x,coef,optimize=False);assert np.isfinite(res).all()
    return 1-np.sum(res**2)/np.sum((y-y.mean())**2)

def main():
    state=pd.read_parquet(OUT/'state_daily.parquet');ev=pd.read_parquet(OUT/'event_cash_diagnostics.parquet').merge(state,on=['t','date'],how='left',suffixes=('','_state'))
    models=[];continuous=[]
    for route,g in ev[ev.status=='MATURED'].groupby('route'):
        g=g.groupby('t').agg(net_return=('net_return','mean'),S1=('S1','first'),year=('year','first'),trend_distance=('trend_distance','first'),B60=('B60','first'),DB20=('DB20','first'),past_drawdown=('past_drawdown','first'),vol20=('vol20','first'))
        sy=pd.get_dummies(g.S1,dtype=float);yr=pd.get_dummies(g.year,dtype=float);y=g.net_return.to_numpy();joint=r2(y,pd.concat([sy,yr],axis=1));year=r2(y,yr);sr=r2(y,sy)
        models.append(dict(route=route,dates=len(g),state_r2=sr,year_r2=year,year_plus_state_r2=joint,state_increment_given_year=joint-year,year_increment_given_state=joint-sr,grade='DESCRIPTIVE_DATE_WEIGHTED_NOT_PREDICTION'))
        for col in ['trend_distance','B60','DB20','past_drawdown','vol20']:continuous.append(dict(route=route,feature=col,date_spearman=g[col].rank().corr(g.net_return.rank())))
    pd.DataFrame(models).to_csv(HERE/'state_vs_year.csv',index=False);pd.DataFrame(continuous).to_csv(HERE/'continuous_state_relation.csv',index=False)
    # Same opening-clock full-market research comparator. Not an ETF or executable NAV.
    ax=json.loads((V3/'cache/axes.json').read_text());a={p.stem:np.load(p,mmap_mode='r') for p in (V3/'cache').glob('*.npy')}
    good=(a['hard_valid']==1)&(np.nan_to_num(a['rights_ratio'],nan=0)==0)&(a['corporate_action_blocking']==0)&(a['close']>0)&(np.array(ax['boards'])[None,:]!='UNSUPPORTED')
    previous=np.vstack([np.full((1,len(ax['symbols'])),np.nan),a['close'][:-1]]);reference=(previous-a['cash_per_share'])/a['share_multiplier'];eligible=np.vstack([np.zeros((1,len(ax['symbols'])),bool),good[:-1]])&good&(reference>0)&np.isfinite(a['open'])
    gap=np.where(eligible,a['open']/reference-1,np.nan);den=np.isfinite(gap).sum(axis=1);mean=np.divide(np.nansum(gap,axis=1),den,out=np.full(len(state),np.nan),where=den>0)
    opening=np.r_[np.nan,state['index'].to_numpy()[:-1]]*(1+mean);state['research_open_index']=opening;parquet(OUT/'market_open_diagnostic.parquet',state[['t','date','research_open_index']])
    q=ev[ev.status=='MATURED'].copy();q['market_same_clock']=opening[q.exit_t.astype(int)]/opening[q.entry_t.astype(int)]-1;q['net_minus_market']=q.net_return-q.market_same_clock
    q.groupby(['route','S1']).apply(lambda g:pd.Series({'signal_dates':g.t.nunique(),'date_net':g.groupby('t').net_return.mean().mean(),'date_market':g.groupby('t').market_same_clock.mean().mean(),'date_net_minus_research_market':g.groupby('t').net_minus_market.mean().mean()}),include_groups=False).to_csv(HERE/'market_beta_diagnostic.csv')
    # Explain what old entry gates removed, as an attribution rather than tradable deletion.
    rows=[]
    for mode in ['C_MAX','C_10']:
        base=V3/f'A_H02_{mode}_E10';tr=pd.read_parquet(base/'trades.parquet');od=pd.read_parquet(base/'orders.parquet');h=pd.read_parquet(base/'holdings.parquet')
        tr['old_state']=state.S0.iloc[tr.signal_t.astype(int)].to_numpy();tr['current_state']=state.S0_CURRENT.iloc[tr.signal_t.astype(int)].to_numpy()
        for key,g in tr.groupby(['old_state','current_state']):rows.append(dict(capital=mode,old_state=key[0],current_state=key[1],trades=len(g),original_realized_pnl=g.pnl.sum(),original_committed_cash=g.entry_cash.sum()))
    pd.DataFrame(rows).to_csv(HERE/'old_gate_removed_opportunities.csv',index=False)
    counts=[]
    for year,g in state[state.date>='2020'].groupby(state.date.str[:4]):
        counts.append(dict(year=year,days=len(g),old_current_disagree=(g.S0!=g.S0_CURRENT).sum(),state_fragments=g.S1_episode.nunique(),changes=(g.S1!=g.S1.shift()).sum(),**g.S1.value_counts().to_dict()))
    pd.DataFrame(counts).to_csv(HERE/'state_occupancy.csv',index=False)
    # Continuous account scoring after 2020 warm-start, without restarting cash or positions.
    score=[]
    for d in list((OUT/'accounts').iterdir())+[V3/'A_D08_C_10_E10',V3/'A_D08_C_MAX_E10']:
        if not (d/'result.json').exists():continue
        r=json.loads((d/'result.json').read_text())
        if r['status'] not in ['COMPLETED','COMPLETED_NEW'] or 'D08' not in r['id']:continue
        nav=pd.read_parquet(d/'nav.parquet');g=nav[nav.date>='2021'];v=np.r_[1.,np.cumprod(1+g.return_daily)]
        score.append(dict(id=r['id'],score_start=g.date.iloc[0],score_end=g.date.iloc[-1],net_return=v[-1]-1,maxdd=(v/np.maximum.accumulate(v)-1).min(),mean_exposure=g.exposure.mean(),start_nav=nav[nav.date<'2021'].nav.iloc[-1],end_nav=g.nav.iloc[-1]))
    pd.DataFrame(score).to_csv(HERE/'past_only_matched_score.csv',index=False)

if __name__=='__main__':main()
