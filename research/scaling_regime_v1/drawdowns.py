"""Peak-to-trough actual strategy, route and security bridges."""
import json
import numpy as np
import pandas as pd
from .audit import HERE,write_json
from .snapshot import CACHE
from .accounts import folder,END
from .economics import require_identity,cases,read,KEY


def run():
    require_identity();rows=[];components=[]
    actions=pd.read_csv(HERE/'output/full_book_rebalance_attribution.csv',usecols=KEY+['timestamp','category'],parse_dates=['timestamp'])
    for case in cases():
        path=folder(*case);identity=dict(zip(KEY,case[:4]));d,a,t,f=read(path,observations=False)
        native,na,_,_=read(folder(case[0],case[1],'NATIVE','FULL_BOOK_NORMALIZATION',END),observations=False)
        root=pd.read_parquet(CACHE/'attribution'/('__'.join(case[:4])+'.parquet'))
        for year in [2024,2025,2026]:
            indexes=d.index[d.trade_date.dt.year.eq(year)];start=int(indexes[0]);end=int(indexes[-1])
            for scope in ['ANNUAL_LOCAL','FULL_PATH_TROUGH_IN_YEAR']:
                lower=start-1 if scope=='ANNUAL_LOCAL' else -1
                sequence=np.r_[a['initial_cash'] if lower<0 else d.nav.iloc[lower],d.nav.iloc[lower+1:end+1].to_numpy()]
                peaks=np.maximum.accumulate(sequence)
                dd=1-sequence/peaks
                offset=start-lower
                relative=int(np.argmax(dd[offset:]))+offset
                trough=lower+relative
                peak_rel=int(np.argmax(sequence[:relative+1]));peak=lower+peak_rel
                peak_nav=float(sequence[peak_rel]);trough_nav=float(d.nav.iloc[trough])
                peak_date=pd.Timestamp('2018-01-01') if peak<0 else d.trade_date.iloc[peak]
                trough_date=d.trade_date.iloc[trough]
                recover=d.loc[(d.index>trough)&d.nav.ge(peak_nav),'trade_date']
                window=d.iloc[peak+1:trough+1]
                native_loss=float(native.nav.iloc[trough]-(na['initial_cash'] if peak<0 else native.nav.iloc[peak]))
                pnl=trough_nav-peak_nav
                actual_roots=root.loc[root.trade_date.gt(peak_date)&root.trade_date.le(trough_date)]
                assert abs(actual_roots.pnl.sum()-pnl)<1e-5
                current=actions.loc[(actions[KEY]==pd.Series(identity)).all(axis=1)&actions.timestamp.gt(peak_date+pd.Timedelta(hours=15,minutes=5))&actions.timestamp.le(trough_date+pd.Timedelta(hours=15,minutes=5))]
                trades=f.loc[f.timestamp.gt(peak_date+pd.Timedelta(hours=15,minutes=5))&f.timestamp.le(trough_date+pd.Timedelta(hours=15,minutes=5))]
                intra=t.loc[pd.to_datetime(t.timestamp).gt(peak_date+pd.Timedelta(hours=15,minutes=5))&pd.to_datetime(t.timestamp).le(trough_date+pd.Timedelta(hours=15,minutes=5))]
                row=dict(**identity,year=year,scope=scope,peak=peak_date,trough=trough_date,recovery=recover.iloc[0] if len(recover) else pd.NaT,
                    recovery_status='RECOVERED' if len(recover) else 'NOT_RECOVERED_AT_DATA_END',MaxDD=1-trough_nav/peak_nav,peak_nav=peak_nav,trough_nav=trough_nav,
                    actual_pnl=pnl,native_same_window_pnl=native_loss,incremental_scaling_pnl=pnl-native_loss,
                    average_gross=float(window.gross.mean()),average_Demand_exposure=float(((window.ATRDR_exposure+window.MCB_exposure)/window.nav).mean()),
                    max_single_name=float((intra.max_security_exposure/intra.nav).max()) if len(intra) else np.nan,
                    cash_at_peak=float(sum(s['cash'] for s in a['initial_states'].values()) if peak<0 else d.cash.iloc[peak]),cash_at_trough=float(d.cash.iloc[trough]),
                    turnover=float(trades.notional.sum()/window.nav.mean()) if len(window) else 0,fees=float(trades.fee.sum()),
                    full_book_normalizations=int(current.category.eq('CASH_RESIDUAL').sum()),existing_position_increases=int(current.category.eq('EXISTING_POSITION_INCREASE').sum()),existing_position_reductions=int(current.category.eq('EXISTING_POSITION_REDUCTION').sum()))
                rows.append(row)
                for dimension in ['strategy','route','symbol','root']:
                    attribution=actual_roots.groupby(dimension).pnl.sum()
                    for name,value in attribution.items():components.append(dict(**identity,year=year,scope=scope,peak=peak_date,trough=trough_date,dimension=dimension,name=name,pnl=value))
    pd.DataFrame(rows).to_csv(HERE/'output/yearly_drawdown_attribution.csv',index=False)
    component_frame=pd.DataFrame(components).merge(pd.DataFrame(rows)[KEY+['year','scope','peak_nav']],on=KEY+['year','scope'],validate='many_to_one')
    component_frame['drawdown_contribution_percentage_points']=-100*component_frame.pnl/component_frame.peak_nav
    component_frame['contribution_basis']='Additive contribution within the same actual portfolio peak-to-trough window; negative contribution offsets drawdown'
    component_frame.to_csv(HERE/'output/yearly_drawdown_components.csv',index=False)
    print('DRAWDOWN_BRIDGES_COMPLETE',len(rows),flush=True)


if __name__=='__main__':run()
