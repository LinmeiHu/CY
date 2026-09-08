"""Do not compare stock coordinate marks across unresolved validity/lineage breaks."""
import duckdb
import numpy as np
import pandas as pd
from .snapshot import CACHE
from .accounts import folder


def qualify(details,case):
    mask=details.side.eq('SELL')&details.strategy.ne('SMV6')
    selected=details.loc[mask]
    if selected.empty:return details
    registry=selected[['symbol']].drop_duplicates()
    with duckdb.connect() as c:
        c.register('registry',registry)
        prices=c.execute('''SELECT symbol,trade_date,invalid_step_cum,
            coalesce(hard_valid AND history_valid AND current_valid AND corporate_action_valid AND current_day_data_tradable AND market_rule_valid AND NOT corporate_action_blocking AND trade_status=1,false) mark_valid
            FROM read_parquet(?) JOIN registry USING(symbol) ORDER BY symbol,trade_date''',[str(CACHE/'daily_with_snapshot.parquet')]).fetchdf().set_index(['symbol','trade_date'])
    calendar=pd.read_parquet(folder(*case)/'daily.parquet',columns=['trade_date']).trade_date.to_numpy(dtype='datetime64[ns]')
    dates=pd.to_datetime(selected.timestamp).dt.normalize().to_numpy(dtype='datetime64[ns]')
    where=np.searchsorted(calendar,dates);base=prices.reindex(pd.MultiIndex.from_arrays([selected.symbol,dates]))
    for horizon in [1,3,5,10,20]:
        available=where+horizon<len(calendar)
        end=calendar[np.minimum(where+horizon,len(calendar)-1)]
        future=prices.reindex(pd.MultiIndex.from_arrays([selected.symbol,end]))
        valid=base.mark_valid.eq(True).to_numpy()&future.mark_valid.eq(True).to_numpy()&(base.invalid_step_cum.to_numpy()==future.invalid_step_cum.to_numpy())
        rejected=available&~valid
        details.loc[selected.index[rejected],f'forward_{horizon}d_pnl']=np.nan
        details.loc[selected.index[rejected],f'forward_{horizon}d_status']='UNRESOLVED_STOCK_COORDINATE_LINEAGE_OR_UNAVAILABLE_MARK;COUNTERFACTUAL_NOT_ESTIMATED'
    return details
