"""Native boundaries, preserving per-strategy continuation/reset semantics."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from five_strategy_bundle.execution.daily import load_daily, replay_sleeves
from five_strategy_bundle.strategies import ogr, smv6
from research.shared_capital_v1.build_inputs import execution_paths
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.gap_p0 import replay as gap_replay
from research.shared_capital_v1.smv6_physical import PhysicalPlatform, callback_stream
from research.shared_capital_v1.smv6_baseline import load_bounded
from research.shared_capital_v1.run_shared_capital_v1 import HERE, sha256

PERIODS = [('2018_2021','2018-01-01'),('2022_2023','2022-01-01')]


def state_hash(state):
    return hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def native_position(row):
    # Outcomes are deliberately not serialized as already-known route/exit state.
    fields=('strategy','price_basis','event_id','gap_id','symbol','board','sleeve','route','source','entry_date','entry_time','entry_price','entry_raw_price','entry_cal_idx','target_coordinate','entry_coordinate_price','quantity','remaining_outlay','lineage')
    result={}
    for key in fields:
        value=row.get(key)
        if value is None or (not isinstance(value,(list,dict)) and pd.isna(value)):continue
        result[key]=str(value) if isinstance(value,(pd.Timestamp,)) else value.item() if isinstance(value,np.generic) else value
    return result


def write_state(strategy,period,boundary,snapshot,mode,origin,status,reason=None,extra=None):
    state={'strategy':strategy,'period':period,'segment_start':boundary,'warmup_start':origin,
        'reset_or_continuation':mode,'validation_status':status,'reason':reason,
        'cash':None,'nav':None,'positions':None,'tradable_quantity':None,'pending_entitlement':None,
        'cooldown_state':None,'route_state':None}
    if snapshot is not None:
        active={k:native_position(v) for k,v in snapshot.get('native_active',{}).items()}
        state.update(cash=float(snapshot['cash']),nav=float(snapshot['nav']),positions=snapshot['positions'],
            tradable_quantity=snapshot['positions'],pending_entitlement={},nontradable_quantity={},
            board_cash=snapshot.get('board_cash'),marks=snapshot.get('marks',{}),native_active=active,
            virtual_lots={k:native_position(v) for k,v in snapshot.get('virtual_lots',{}).items()},
            cooldown_state={'funded_account_cooldown':'NONE_IN_NATIVE_ACCOUNT; signal-level warmup remains in registered parent pipeline'},
            route_state={'native_active':active,'native_exits':'UNCHANGED; future outcome fields not serialized'},
            asof=None if snapshot.get('asof') is None else str(snapshot['asof']))
    if extra:state.update(extra)
    digest=state_hash(state)
    state['state_hash']=digest
    target=HERE/'output'/f'{strategy.lower()}_initial_state_{boundary[:4]}.json'
    target.write_text(json.dumps(state,indent=2,sort_keys=True,allow_nan=False)+'\n')
    return {'strategy':strategy,'period':period,'warmup_start':origin,'segment_start':boundary,
        'reset_or_continuation':mode,'initial_cash':state['cash'],'initial_nav':state['nav'],
        'position_count':None if snapshot is None else len(snapshot['positions']),
        'position_notional':None if snapshot is None else state['nav']-state['cash'],
        'pending_entitlement_count':None if snapshot is None else 0,'state_hash':digest,
        'validation_status':status,'reason':reason,'state_file':str(target.relative_to(HERE))}


def run():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    probes=pd.read_csv(HERE/'output/native_initial_state_probe.csv')
    rows=[]
    for strategy in ('ATRDR','MCB'):
        snapshots=json.loads((HERE/'cache'/strategy.lower()/'native_continuous/boundary_snapshots.json').read_text())
        # Independently verify reachable MCB boundary with frozen native account.
        if strategy=='MCB':
            entries=pd.read_parquet(HERE/'cache/mcb/precapital_entry_population.parquet')
            daily=load_daily(execution_paths(inputs),entries.symbol.tolist())
            cohort=entries.loc[entries.entry_date.between('2014-01-01','2017-12-31')]
            _,_,reference,_=replay_sleeves(cohort,daily.loc[daily.trade_date.between('2014-01-01','2017-12-31')],rank_columns=('industry_positive_ret20_share','stock_minus_industry_ret20','turnover_expansion'),k_per_sleeve=30,daily_cap=10)
            expected=reference.combined_nav.iloc[-1]*1e6
            if abs(expected-snapshots['2018-01-01']['nav'])>1e-6:raise ValueError('MCB 2018 native initial NAV mismatch')
        for period,boundary in PERIODS:
            probe=probes.loc[probes.strategy.eq(strategy)&probes.period.eq(period)].iloc[0]
            snapshot=snapshots.get(boundary)
            rows.append(write_state(strategy,period,boundary,snapshot,'NATIVE_CONTINUATION','2014-01-01',
                'VALIDATED' if snapshot else 'CORPORATE_ACTION_STATE_UNRESOLVED',None if snapshot else probe.first_blocker,
                {'initialization_reference':'native stock account replay from 2014; no flat replacement'}))
    daily=ogr.load_daily(inputs['daily_hist'],end='2023-12-31')
    outcomes=pd.read_parquet(HERE/'cache/ogr/outcomes.parquet')
    board=corrected_function(ogr._replay_board,[('period_end = min(\n        pd.Timestamp(trades.exit_date.max()).normalize(), pd.Timestamp(account_end)\n    )','period_end = pd.Timestamp(account_end)')])
    native=corrected_function(ogr.replay_portfolio,[],_replay_board=board)
    comparisons=[]
    for strategy in ('OGR','IFCGR'):
        selected=pd.read_parquet(HERE/'cache/ogr/signals.parquet') if strategy=='OGR' else pd.concat([pd.read_parquet(HERE/'cache/ifcgr'/period/'signals.parquet') for period,_ in PERIODS])
        trades=outcomes.loc[outcomes.gap_id.isin(selected.gap_id)&outcomes.entry_date.ge('2018-01-01')]
        account,intents,other,nav=gap_replay(strategy,trades,daily,'2018-01-01','2023-12-31',boundaries=('2018-01-01','2022-01-01'))
        _,_,golden=native(trades,daily,account_start='2018-01-01',account_end='2023-12-31')
        golden=golden.loc[golden.board.eq('COMBINED')]
        pd.testing.assert_series_equal(nav.trade_date.reset_index(drop=True),golden.trade_date.reset_index(drop=True),check_names=False)
        difference=max(float(np.max(np.abs(nav[f].to_numpy()-golden[f].to_numpy()*1e6))) for f in ('cash','nav','gross_exposure'))
        if difference>1e-6:raise ValueError(f'{strategy} continuous native comparison failed: {difference}')
        # Replay the strict account prefix separately: future outcomes cannot alter the boundary.
        prefix=gap_replay(strategy,trades,daily.loc[daily.trade_date.lt('2022-01-01')],'2018-01-01','2021-12-31')
        pd.testing.assert_frame_equal(prefix[3],nav.loc[nav.trade_date.lt('2022-01-01')].reset_index(drop=True))
        if prefix[0].positions != account.boundary_snapshots['2022-01-01']['positions']:raise ValueError('Gap boundary holdings prefix failure')
        root=HERE/'cache'/strategy.lower()/'native_continuous';root.mkdir(exist_ok=True)
        nav.to_parquet(root/'nav.parquet',index=False)
        pd.DataFrame(account.checkpoints).to_parquet(root/'checkpoints.parquet',index=False)
        comparisons.append({'strategy':strategy,'scope':'NATIVE_CONTINUOUS_2018_2023','max_abs_cash_nav_exposure_diff':difference,'prefix_status':'PASS_ACCOUNT_PREFIX','status':'PASS','final_nav':float(nav.nav.iloc[-1])})
        for period,boundary in PERIODS:
            rows.append(write_state(strategy,period,boundary,account.boundary_snapshots[boundary],
                'NATIVE_ACCOUNT_ORIGIN_RESET' if period=='2018_2021' else 'NATIVE_CONTINUATION','2013-01-01_MARKET_WARMUP_ACCOUNT_ORIGIN_2018', 'VALIDATED',
                extra={'initialization_reference':'ogr._replay_board account origin 2018; continue cash/holdings through 2022; IFCGR same account with PIT-B-selected parents','pit_grade':'PIT_B_CURRENT_OFFICIAL_ENUMERATION_REVISION_HISTORY_INCOMPLETE' if strategy=='IFCGR' else None}))
    daily,minute,availability=load_bounded(inputs)
    for period,boundary in PERIODS:
        end='2021-12-31' if period=='2018_2021' else '2023-12-31'
        calendar=list(daily['000852.SH'].loc[boundary:end].dropna(subset=['pre_adj_close']).index)
        p=PhysicalPlatform(daily,minute,availability,calendar,initial_cash=1e6,lot_size=100,fee_bps=0)
        stream=callback_stream(p,calendar);next(stream) # init executes, first before_trading callback has not run
        context={k:(sorted(v) if isinstance(v,set) else v) for k,v in vars(p.native_context).items() if k!='portfolio'}
        context_set_fields=[k for k,v in vars(p.native_context).items() if isinstance(v,set)]
        snapshot={'cash':p.cash,'nav':p.cash,'positions':dict(p.shares)}
        rows.append(write_state('SMV6',period,boundary,snapshot,'NATIVE_CALLBACK_INIT_RESET','ALL_REGISTERED_PRIOR_DAILY_HISTORY','VALIDATED',extra={'native_context':context,'native_context_set_fields':context_set_fields,'initialization_reference':'smv6._run_callbacks explicitly init on each native interval; prior daily history remains available; local platform equivalence unverified'}))
    pd.DataFrame(rows).to_csv(HERE/'output/native_segment_initial_states.csv',index=False)
    pd.DataFrame(comparisons).to_csv(HERE/'output/native_continuous_reconciliation.csv',index=False)
    print(pd.DataFrame(rows).to_string(index=False),flush=True)
    return rows


if __name__=='__main__':run()
