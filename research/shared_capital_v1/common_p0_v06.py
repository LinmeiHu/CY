"""Four native P0 dispatches; initialization failure never becomes a cash sleeve."""
import json
from pathlib import Path
import pandas as pd
from five_strategy_bundle.execution.daily import load_daily
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.run_shared_capital_v1 import HERE
from research.shared_capital_v1.native_states_v06 import state_hash
from research.shared_capital_v1.shared_account.allocator import active_strategies
from research.shared_capital_v1.shared_account.p0 import initialize, run as common_run
from research.shared_capital_v1.build_inputs import execution_paths
from research.shared_capital_v1.stock_p0 import replay as stock_replay
from research.shared_capital_v1.gap_p0 import replay as gap_replay
from research.shared_capital_v1.smv6_physical import PhysicalPlatform, callback_stream
from research.shared_capital_v1.smv6_baseline import load_bounded


def run():
    rows=[]
    for gap in ('OGR','IFCGR'):
        for period,start,end in [('2018_2021','2018-01-01','2021-12-31'),('2022_2023','2022-01-01','2023-12-31')]:
            states={s:json.loads((HERE/'output'/f'{s.lower()}_initial_state_{start[:4]}.json').read_text()) for s in active_strategies(gap)}
            for s,state in states.items():
                if state_hash({k:v for k,v in state.items() if k!='state_hash'})!=state['state_hash']:raise ValueError(f'{s} native state hash mismatch')
            blockers=[f'{s}: {state.get("reason")}' for s,state in states.items() if state['validation_status']!='VALIDATED']
            row=dict(policy='P0',gap=gap,period=period,status='NOT_RUN_INITIAL_STATE_UNRESOLVED',first_blocker='; '.join(blockers),physical_account_created=False,shared_scenarios_run=0)
            if blockers:
                rows.append(row)
                continue
            initialize(gap,states) # before loading raw execution inputs or making factories
            inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
            factories={}
            results={}
            for strategy in ('ATRDR','MCB'):
                entries=pd.read_parquet(HERE/'cache'/strategy.lower()/'precapital_entry_population.parquet')
                daily=load_daily(execution_paths(inputs),entries.symbol.tolist())
                def factory(account,state,s=strategy,e=entries,d=daily):
                    stream,result=stock_replay(s,e,d,start,end,physical=account,stream_only=True,initial_state=state)
                    results[s]=result
                    return stream
                factories[strategy]=factory
            outcomes=pd.read_parquet(HERE/'cache/ogr/outcomes.parquet')
            selected=pd.read_parquet(HERE/'cache/ogr/signals.parquet') if gap=='OGR' else pd.concat([pd.read_parquet(HERE/'cache/ifcgr'/p/'signals.parquet') for p in ('2018_2021','2022_2023')])
            trades=outcomes.loc[outcomes.gap_id.isin(selected.gap_id)]
            daily=ogr.load_daily(inputs['daily_hist'],end='2023-12-31')
            def gap_factory(account,state):
                stream,result=gap_replay(gap,trades,daily,start,end,physical=account,stream_only=True,initial_state=state)
                results[gap]=result
                return stream
            factories[gap]=gap_factory
            etf_daily,minute,availability=load_bounded(inputs)
            calendar=list(etf_daily['000852.SH'].loc[start:end].dropna(subset=['pre_adj_close']).index)
            def etf_factory(account,state):
                if state['positions']:raise ValueError('SMV6 native init reset unexpectedly has holdings')
                platform=PhysicalPlatform(etf_daily,minute,availability,calendar,initial_cash=state['cash'],lot_size=100,fee_bps=0,physical=account)
                return callback_stream(platform,calendar)
            factories['SMV6']=etf_factory
            account,trace=common_run(gap,states,factories)
            folder=HERE/'cache/common_p0'/gap/period;folder.mkdir(parents=True,exist_ok=True)
            pd.DataFrame(trace).to_parquet(folder/'scheduler.parquet',index=False)
            pd.DataFrame(account.checkpoints).to_parquet(folder/'checkpoints.parquet',index=False)
            # Dispatch/account reconciliation alone cannot certify independent
            # native equivalence. Keep this gate explicit if data later arrives.
            row.update(status='DISPATCHED_NATIVE_REFERENCE_RECONCILIATION_REQUIRED',physical_account_created=True,first_blocker='complete independent multi-layer native reference comparison')
            rows.append(row)
    pd.DataFrame(rows).to_csv(HERE/'output/p0_reconciliation.csv',index=False)
    pd.DataFrame(rows).to_csv(HERE/'output/scenario_run_status.csv',index=False)
    return rows


if __name__=='__main__':run()
