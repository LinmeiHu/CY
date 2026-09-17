"""Refresh QMT front adjustment without inventing unavailable old minute bars."""
from pathlib import Path
import numpy as np
import pandas as pd
from five_strategy_bundle.strategies import smv6
from research.portfolio_closure_v1 import repair
from .prepare_stock import HERE,CACHE,END

OLD=Path('/Volumes/quant/CY_quant_research/five_strategy_capital_scaling_rollforward_v2/smv6')


def adjusted_history(frame,events):
    frame=frame.copy()
    for event in events.sort_values('effective_date').itertuples():
        assert event.allotNum==0 and event.gugai==0,'unsupported QMT adjustment type'
        multiplier=1+event.stockBonus+event.stockGift
        assert multiplier>0
        mask=pd.to_datetime(frame.trade_date).lt(event.effective_date)
        for field in ['pre_adj_open','pre_adj_high','pre_adj_low','pre_adj_close']:
            frame.loc[mask,field]=(frame.loc[mask,field]-event.interest)/multiplier
    return frame


def main():
    facts=pd.read_parquet(CACHE/'etf_adjustment_facts.parquet');audits=[];availability=[]
    root=CACHE/'smv6'
    for symbol in [smv6.canonical_symbol(s) for s in smv6.raw_pool()]+['000852.SH']:
        dp=Path('daily')/f'symbol={symbol}'/'daily.parquet';mp=Path('minute_critical')/f'symbol={symbol}'/'critical.parquet'
        oldd=pd.read_parquet(OLD/dp);d=pd.read_parquet(CACHE/'qmt_etf_full'/dp)
        oldm=pd.read_parquet(OLD/mp);events=facts.loc[facts.symbol.eq(symbol)]
        for frame in [oldd,d,oldm]:frame.trade_date=pd.to_datetime(frame.trade_date)
        converted=adjusted_history(oldd,events)
        j=converted.merge(d,on=['symbol','trade_date'],suffixes=('_old','_new'))
        j=j.loc[j.row_status_old.eq('VALID')&j.row_status_new.eq('VALID')]
        maxdiff=0.;rawdiff=0.
        for field in ['open','high','low','close']:
            delta=(j[f'pre_adj_{field}_old']-j[f'pre_adj_{field}_new']).abs().max()
            maxdiff=max(maxdiff,float(delta))
            rawdiff=max(rawdiff,float((j[f'raw_{field}_old']-j[f'raw_{field}_new']).abs().max()))
        assert maxdiff<1e-8,(symbol,maxdiff,'unexpected historical adjustment revision')
        transformed=adjusted_history(oldm,events)
        recent_path=CACHE/'qmt_etf_full'/mp
        if not recent_path.exists():recent_path=CACHE/'qmt_etf'/mp
        recent=pd.read_parquet(recent_path);recent.trade_date=pd.to_datetime(recent.trade_date)
        overlap=transformed.merge(recent,on=['symbol','trade_date','bar_role'],suffixes=('_old','_new'))
        valid=overlap.row_status_old.eq('VALID')&overlap.row_status_new.eq('VALID')
        minute_diff=max(float((overlap.loc[valid,f'pre_adj_{field}_old']-overlap.loc[valid,f'pre_adj_{field}_new']).abs().max()) for field in ['open','high','low','close'])
        # Preserve registered bar availability/execution semantics. Only price
        # adjustment is refreshed on legacy history; fresh tail is appended.
        assert minute_diff<1e-8,(symbol,minute_diff,'minute/daily adjustment mismatch')
        m=pd.concat([transformed,recent.loc[recent.trade_date.gt(oldm.trade_date.max())]],ignore_index=True)
        d=d.sort_values('trade_date');m=m.sort_values(['trade_date','bar_role'])
        assert not d.trade_date.duplicated().any() and not m.duplicated(['trade_date','bar_role']).any()
        assert str(d.trade_date.max().date())==END,(symbol,'daily tail missing')
        for path,frame in [(dp,d),(mp,m)]:
            out=root/path;out.parent.mkdir(parents=True,exist_ok=True);frame.to_parquet(out,index=False)
        expected=d.loc[d.row_status.eq('VALID'),['trade_date']].copy();expected['symbol']=symbol
        for role,column in [('OPEN_BAR_09_30','executable_09_30'),('PSEUDO_CLOSE_14_57_OPEN','tail_signal_available_14_57'),('FINAL_CLOSE_BAR','executable_15_00')]:
            selected=m.loc[m.bar_role.eq(role),['trade_date','row_status']].copy();selected[column]=selected.row_status.eq('VALID')
            expected=expected.merge(selected[['trade_date',column]],on='trade_date',how='left',validate='one_to_one');expected[column]=expected[column].eq(True)
        expected.trade_date=expected.trade_date.dt.date;availability.append(expected)
        audits.append(dict(symbol=symbol,daily_overlap_rows=len(j),old_daily_raw_max_diff=rawdiff,adjustment_prediction_max_diff=maxdiff,
            minute_overlap_rows=int(valid.sum()),minute_adjustment_max_diff=minute_diff,actions=len(events),end=END))
    pd.concat(availability,ignore_index=True).to_parquet(root/'availability.parquet',index=False)
    pd.DataFrame(audits).to_csv(HERE/'etf_adjustment_validation.csv',index=False)
    repair.write_json(HERE/'etf_refresh_manifest.json',dict(status='PASS',symbols=len(audits),user_authorized_history_refresh=True,
        history_method='QMT latest daily; new QMT cash/split factors applied to prior registered critical-minute prices and checked against fresh overlap',
        adjustment_fact_sha256=repair.digest(CACHE/'etf_adjustment_facts.parquet')))
    print('ETF REFRESH PASS',len(audits),flush=True)


if __name__=='__main__':main()
