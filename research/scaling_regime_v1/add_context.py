"""Was an existing holding losing at the last completed close when topped up?"""
import json
import numpy as np
import pandas as pd
from .audit import HERE
from .economics import cases,KEY
from .accounts import folder


def run():
    all_rows=[];summaries=[]
    for case in cases():
        if case[2]=='NATIVE' or case[3]!='FULL_BOOK_NORMALIZATION':continue
        d=pd.read_parquet(folder(*case)/'daily.parquet',columns=['trade_date','lots_json','marks_json'])
        data=[]
        for r in d.itertuples():
            marks=json.loads(r.marks_json);values={}
            for root,lot in json.loads(r.lots_json).items():
                key=lot.get('root_event_id') or root
                values[key]=values.get(key,0.)+(lot['quantity']+(lot.get('pending_quantity') or 0.))*marks[lot['symbol']]-lot['remaining_outlay']
            data.extend(dict(prior_completed_date=r.trade_date,event_id=root,prior_held_unrealized_pnl=value) for root,value in values.items())
        prior=pd.DataFrame(data)
        calendar=pd.Series(d.trade_date.shift(1).to_numpy(),index=d.trade_date)
        path=HERE/'cache/rebalance'/('__'.join(case[:4]))
        actions=pd.read_parquet(path/'details.parquet')
        buys=actions.loc[actions.category.eq('EXISTING_POSITION_INCREASE')].copy()
        buys['prior_completed_date']=pd.to_datetime(buys.timestamp).dt.normalize().map(calendar)
        buys=buys.merge(prior,on=['prior_completed_date','event_id'],how='left',validate='many_to_one')
        buys['known_prior_holding_state']=np.where(buys.prior_held_unrealized_pnl.isna(),'NO_PRIOR_CLOSE_HOLDING',np.where(buys.prior_held_unrealized_pnl.lt(0),'PRIOR_CLOSE_LOSING_HOLDING','PRIOR_CLOSE_NONLOSING_HOLDING'))
        buys['information_limit']='Known preceding session held unrealized P&L; not same-clock mark, not an optimized threshold or live rule'
        all_rows.append(buys[KEY+['timestamp','vintage_id','event_id','strategy','symbol','delta_notional','prior_completed_date','prior_held_unrealized_pnl','known_prior_holding_state','information_limit']])
        annual=pd.read_parquet(path/'annual.parquet')
        annual=annual.loc[annual.category.eq('EXISTING_POSITION_INCREASE')].merge(buys[['vintage_id','known_prior_holding_state']],left_on='seed_event_id',right_on='vintage_id',validate='many_to_one')
        summaries.append(annual.groupby(KEY+['year','strategy','known_prior_holding_state'],as_index=False).pnl.sum())
    pd.concat(all_rows).to_csv(HERE/'output/existing_add_known_state.csv',index=False)
    pd.concat(summaries).to_csv(HERE/'output/existing_add_known_state_annual_pnl.csv',index=False)
    print('KNOWN_PRIOR_CLOSE_ADD_CONTEXT_COMPLETE',flush=True)


if __name__=='__main__':run()
