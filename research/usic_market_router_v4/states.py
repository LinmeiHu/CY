"""Fixed S0/current and new S1 descriptors from authorized full market history."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,log,dump,parquet,sha

def calculate(a,dates,boards):
    c=np.asarray(a['coord']);good=(a['hard_valid']==1)&(np.nan_to_num(a['rights_ratio'],nan=0)==0)&(a['corporate_action_blocking']==0)&(a['close']>0)
    supported=np.array(boards)!='UNSUPPORTED';good=good&supported[None,:]
    prior=np.vstack([np.zeros((1,c.shape[1]),bool),good[:-1]])
    step=np.where(prior,a['step'],np.nan)
    count=np.isfinite(step).sum(axis=1);mr=np.divide(np.nansum(step,axis=1),count,out=np.full(len(dates),np.nan),where=count>0);mr[0]=0
    idx=pd.Series(np.cumprod(1+np.nan_to_num(mr,nan=0)));ma=idx.rolling(60).mean()
    original=np.where((idx>=ma)&(ma>=ma.shift(20)),'BULL',np.where((idx<ma)&(ma<ma.shift(20)),'BEAR','TRANSITION'))
    out=pd.DataFrame(dict(t=np.arange(len(dates)),date=dates,market_return=mr,index=idx,S0_CURRENT=original))
    out['S0']=out.S0_CURRENT.shift(1).fillna('TRANSITION')
    out['s0_formula_known']=ma.notna()&ma.shift(20).notna()
    # ST and suspensions stay in the historical market pool. Missing required SMA
    # is excluded from numerator AND denominator, never silently treated as below.
    for n in [20,60]:
        sma=pd.DataFrame(np.where(good,c,np.nan)).rolling(n).mean().to_numpy()
        valid=good&np.isfinite(sma)&np.isfinite(c);denom=valid.sum(axis=1)
        out[f'B{n}']=np.divide((valid&(c>sma)).sum(axis=1),denom,out=np.full(len(dates),np.nan),where=denom>0)
        out[f'B{n}_denominator']=denom
        out[f'B{n}_missing_history']=good.sum(axis=1)-denom
    out['DB20']=out.B20-out.B20.shift(10)
    out['S1']=np.where(out.B60>=.5,np.where(out.DB20>0,'HIGH_IMPROVING','HIGH_NONIMPROVING'),np.where(out.DB20>0,'LOW_IMPROVING','LOW_NONIMPROVING'))
    out.loc[out.B60.isna()|out.DB20.isna(),'S1']='UNKNOWN'
    out['trend_distance']=idx/ma-1;out['past_drawdown']=idx/idx.cummax()-1;out['vol20']=pd.Series(mr).rolling(20).std()*np.sqrt(252)
    for key in ['S0','S0_CURRENT','S1']:out[key+'_episode']=(out[key]!=out[key].shift()).cumsum()
    return out

def main():
    log('S1_FIXED','NEW_STATE','V4 supplied fixed S1; prior habitat payoff increment unestablished',
        'B60 0.5 and B20 ten-session change; no optimized thresholds','S0 original and S0_CURRENT',
        'Within-year support and temporal transitions may explain entry/holding losses','No repeated conditional difference; year dominates')
    ax=json.loads((V3/'cache/axes.json').read_text());a={p.stem:np.load(p,mmap_mode='r') for p in (V3/'cache').glob('*.npy')}
    out=calculate(a,ax['dates'],ax['boards']);old=pd.read_csv(V3/'cache/market.csv')
    np.testing.assert_allclose(out['index'],old['index'],atol=1e-12,rtol=1e-12)
    for end in [600,1000,1300]:
        short=calculate({k:v[:end] for k,v in a.items()},ax['dates'][:end],ax['boards']);pd.testing.assert_frame_equal(out.iloc[:end].reset_index(drop=True),short)
    parquet(OUT/'state_daily.parquet',out)
    dump(HERE/'market_state_dictionary.json',dict(S0='V3 formula including unknown->TRANSITION, state at signal T-1',S0_CURRENT='Identical formula at signal T close; initial missing explicitly flagged',
        S1='B60>=0.5 crossed with DB20=B20(T)-B20(T-10)>0; UNKNOWN blocks new entry',market_pool='Full historical supported boards; good price/action/history; ST and suspensions retained; required-SMA missing excluded and counted',
        prefix_checks=[600,1000,1300],index_parity=True,input_manifest_sha256=sha(HERE.parent/'usic_multichampion_ashare_v3/INPUT_MANIFEST.json'),permission='2018-2023 only',state_hash=sha(OUT/'state_daily.parquet')))
    print(out[out.date>='2020'].groupby([out.date.str[:4],'S1']).size().to_string(),flush=True)

if __name__=='__main__':main()
