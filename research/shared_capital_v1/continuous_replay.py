"""Continuous raw native stock reconstruction; no outcome scenario bypass."""
import json
from pathlib import Path
import duckdb
import pandas as pd
from .stock_p0 import replay, HERE
from .build_inputs import execution_paths
from .shared_account.held_actions import registered_actions


def load_stock_daily(inputs, symbols):
    registry=pd.DataFrame({'symbol':sorted(set(symbols))})
    columns='symbol,trade_date,open,close,coord_open,coord_close,coord_high,coordinate_factor,cal_idx,invalid_step_cum,hard_valid,history_valid,current_valid,corporate_action_valid,current_day_data_tradable,market_rule_valid,corporate_action_blocking,trade_status,down_limit_price,corporate_action_count,historical_identity_valid'
    with duckdb.connect() as con:
        con.register('registry',registry)
        pieces=' UNION ALL '.join(f"SELECT {columns}, {i} priority FROM read_parquet('{p}') JOIN registry USING(symbol) WHERE trade_date < DATE '2024-01-01'" for i,p in enumerate(execution_paths(inputs)))
        return con.execute(f'WITH d AS ({pieces}) SELECT * EXCLUDE(priority) FROM d QUALIFY row_number() OVER(PARTITION BY symbol,trade_date ORDER BY priority)=1 ORDER BY symbol,trade_date').fetchdf()


def save(account,intents,rejects,nav,blocker,strategy):
    folder=HERE/'cache'/strategy.lower()/'raw_continuous';folder.mkdir(exist_ok=True)
    for name,frame in [('intents',intents),('other_rejected',rejects),('nav',nav),('fills',pd.DataFrame(account.fills)),('checkpoints',pd.DataFrame(account.checkpoints))]:
        if 'native_priority' in frame:
            frame=frame.copy();frame.native_priority=frame.native_priority.map(json.dumps)
        frame.to_parquet(folder/f'{name}.parquet',index=False)
    (folder/'boundary_snapshots.json').write_text(json.dumps(account.boundary_snapshots,default=str,indent=2))
    service=account.held_actions[strategy]
    pd.DataFrame(service.audit).to_csv(folder/'held_actions.csv',index=False)
    pd.DataFrame(service.timeline).to_csv(folder/'action_timeline.csv',index=False)
    row=dict(strategy=strategy,status='BLOCKED' if blocker else 'RAW_CONTINUOUS_REPLAY_COMPLETED',first_blocker=blocker,
        completed_dates=len(nav),through=str(nav.trade_date.max()) if len(nav) else None,held_events=len(service.audit),
        unresolved_events=sum(bool(x['first_missing_field']) for x in service.audit),funded_entries=sum(f['side']=='BUY' for f in account.fills),
        final_nav=float(nav.nav.iloc[-1]) if len(nav) else None)
    (folder/'status.json').write_text(json.dumps(row,indent=2)+'\n')
    print(row,flush=True)
    return row


def run():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    actions=registered_actions();rows=[]
    for strategy in ('ATRDR','MCB'):
        entries=pd.read_parquet(HERE/'cache'/strategy.lower()/'precapital_entry_population.parquet')
        print('Loading bounded raw execution:',strategy,flush=True)
        daily=load_stock_daily(inputs,entries.symbol)
        print('Replaying',strategy,len(daily),'rows',flush=True)
        result=replay(strategy,entries,daily,'2014-01-01','2023-12-31',boundaries=('2018-01-01','2022-01-01'),action_registry=actions)
        rows.append(save(*result,strategy))
    pd.DataFrame(rows).to_csv(HERE/'output/raw_continuous_replay_status.csv',index=False)
    if any(r['first_blocker'] for r in rows): raise ValueError('continuous native replay blocked; see raw_continuous_replay_status.csv')
    return rows

if __name__=='__main__':
    run()
