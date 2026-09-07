"""Validate chronological stock prefixes and serialize live boundary state."""
import json
from pathlib import Path
from copy import deepcopy
import pandas as pd
from .continuous_replay import load_stock_daily
from .stock_p0 import replay,HERE
from .shared_account.held_actions import registered_actions
from .native_states_v06 import state_hash


def run():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    registry=registered_actions();results=[]
    states=pd.read_csv(HERE/'output/native_segment_initial_states.csv')
    states=states.loc[~states.strategy.isin(['ATRDR','MCB'])].to_dict('records')
    for strategy in ('ATRDR','MCB'):
        folder=HERE/'cache'/strategy.lower()/'raw_continuous'
        status=json.loads((folder/'status.json').read_text())
        if status['first_blocker']:raise ValueError(status['first_blocker'])
        entries=pd.read_parquet(HERE/'cache'/strategy.lower()/'precapital_entry_population.parquet')
        daily=load_stock_daily(inputs,entries.symbol)
        snapshots=json.loads((folder/'boundary_snapshots.json').read_text())
        golden=pd.read_parquet(folder/'nav.parquet')
        all_fills=pd.read_parquet(folder/'fills.parquet')
        for boundary in ('2018-01-01','2022-01-01'):
            end=str((pd.Timestamp(boundary)-pd.Timedelta(days=1)).date())
            print('Independent strict prefix',strategy,end,flush=True)
            account,intents,rejects,nav,blocker=replay(strategy,entries.loc[entries.entry_date.lt(boundary)],daily.loc[daily.trade_date.lt(boundary)],'2014-01-01',end,action_registry=registry.loc[registry.record_date.lt(boundary)])
            if blocker:raise ValueError(blocker)
            pd.testing.assert_frame_equal(nav,golden.loc[golden.trade_date.lt(boundary)].reset_index(drop=True))
            reference_intents=pd.read_parquet(folder/'intents.parquet')
            reference_intents=reference_intents.loc[reference_intents.earliest_execution_at.lt(pd.Timestamp(boundary))].reset_index(drop=True)
            intents.native_priority=intents.native_priority.map(json.dumps)
            pd.testing.assert_frame_equal(intents,reference_intents)
            snapshot=snapshots[boundary]
            if account.positions!=snapshot['positions'] or account.pending_positions!=snapshot['pending_entitlement']:raise ValueError('raw boundary quantity prefix mismatch')
            reference_fills=all_fills.loc[(all_fills.side.eq('BUY')&all_fills.entry.lt(boundary))|(all_fills.side.eq('SELL')&all_fills.exit.lt(boundary))]
            actual=pd.DataFrame(account.fills)
            for column in ('event_id','side','quantity','remaining_outlay'):
                pd.testing.assert_series_equal(actual[column].reset_index(drop=True),reference_fills[column].reset_index(drop=True),check_dtype=False)
            period='2018_2021' if boundary[:4]=='2018' else '2022_2023'
            state=dict(strategy=strategy,period=period,segment_start=boundary,warmup_start='2014-01-01',reset_or_continuation='NATIVE_CONTINUATION',
                validation_status='VALIDATED',reason=None,**snapshot,tradable_quantity=snapshot['positions'],nontradable_quantity={},
                cooldown_state={'funded_account_cooldown':'NONE; frozen parent pipeline retains signal cooldowns'},
                route_state={'native_active':snapshot['native_active']},account_grade='RESEARCH_GRADE_SHARED_PHYSICAL_ACCOUNT')
            state['state_hash']=state_hash(state)
            filename=HERE/'output'/f'{strategy.lower()}_initial_state_{boundary[:4]}.json'
            filename.write_text(json.dumps(state,indent=2,sort_keys=True,allow_nan=False)+'\n')
            states.append(dict(strategy=strategy,period=period,warmup_start='2014-01-01',segment_start=boundary,reset_or_continuation='NATIVE_CONTINUATION',
                initial_cash=state['cash'],initial_nav=state['nav'],positions=json.dumps(state['positions'],sort_keys=True),
                tradable_quantity=json.dumps(state['tradable_quantity'],sort_keys=True),pending_quantity=json.dumps(state['pending_entitlement'],sort_keys=True),
                position_count=len(state['positions']),state_hash=state['state_hash'],validation_status='VALIDATED',state_file=str(filename.relative_to(HERE))))
            results.append(dict(strategy=strategy,through=end,eligible_intents='PASS',fills='PASS',cash_nav='PASS',raw_pending_positions='PASS',initial_state='PASS',status='PASS'))
        del daily
    pd.DataFrame(states).sort_values(['strategy','period']).to_csv(HERE/'output/native_segment_initial_states.csv',index=False)
    pd.DataFrame(results).to_csv(HERE/'output/raw_continuous_prefix.csv',index=False)
    return results

if __name__=='__main__':print(run())
