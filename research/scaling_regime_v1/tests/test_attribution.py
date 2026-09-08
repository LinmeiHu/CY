import inspect
import json
import numpy as np
import pandas as pd
from research.scaling_regime_v1.audit import HERE,sha256
from research.scaling_regime_v1.economics import KEY,capital_at,fills_frame
from research.scaling_regime_v1.accounts import folder,END
from research.scaling_regime_v1 import states

K=KEY+['year']


def test_annual_amount_and_route_strategy_bridges():
    annual=pd.read_csv(HERE/'output/annual_scaling_metrics.csv')
    assert len(annual)==252 and annual[K].duplicated().sum()==0
    for dimension in ['strategy','route','symbol']:
        data=pd.read_csv(HERE/f'output/annual_{dimension}_contribution.csv')
        a=annual.merge(data.groupby(K,as_index=False)[['pnl_scaled','pnl_native','incremental_pnl']].sum(),on=K,validate='one_to_one')
        assert np.allclose(a.net_pnl,a.pnl_scaled,atol=1e-5,rtol=0)
        assert np.allclose(a.incremental_pnl,a.pnl_scaled-a.pnl_native,atol=1e-5,rtol=0)


def test_calendar_capital_days_includes_holiday_and_terminal_carry():
    t=pd.DataFrame(dict(timestamp=pd.to_datetime(['2023-12-29 15:01','2024-01-02 09:30']),gross_exposure=[100.,80.],capital_days=[1000.,1377.013888888889]))
    boundary=capital_at(t,'2024-01-01')
    assert np.isclose(boundary,1000+100*(pd.Timestamp('2024-01-01')-t.timestamp.iloc[0]).total_seconds()/86400)
    bridge=pd.read_csv(HERE/'output/calendar_capital_days_bridge.csv')
    assert len(bridge)==180
    assert np.allclose(bridge.capital_days_root,bridge.capital_days_account,atol=1e-4,rtol=1e-11)


def test_state_information_prefix_and_no_year_feature():
    full=states.observable();past=full.loc[full.state_as_of.le('2023-12-31')]
    probes=pd.DataFrame({'decision_at':pd.to_datetime(['2018-01-02 09:30','2022-01-04 09:30','2023-12-29 14:57'])})
    pd.testing.assert_frame_equal(states.join_states(probes,full,'decision_at'),states.join_states(probes,past,'decision_at'))
    contract=json.loads((HERE/'contracts/scaling_regime_attribution_v2.json').read_text())
    assert not any(any(x in f for x in ['year','future','forward']) for f in contract['state_features'])
    decisions=pd.read_csv(HERE/'output/scaling_decision_state.csv',usecols=['decision_at','state_as_of','account_state_as_of','active_Demand_as_of'],parse_dates=['decision_at','state_as_of','account_state_as_of','active_Demand_as_of'])
    assert decisions.state_as_of.le(decisions.decision_at).all()
    assert decisions.account_state_as_of.lt(decisions.decision_at).all()
    assert decisions.active_Demand_as_of.lt(decisions.decision_at).all()


def test_state_total_is_actual_increment_counted_once_per_family():
    states_=pd.read_csv(HERE/'output/scaling_daily_state_increment.csv')
    inc=pd.read_csv(HERE/'output/annual_scaling_increment.csv')
    actual=states_.groupby(K,as_index=False).incremental_pnl.sum().merge(inc[K+['incremental_net_pnl']],on=K,validate='one_to_one')
    assert np.allclose(actual.incremental_pnl,actual.incremental_net_pnl,atol=1e-5,rtol=0)
    summary=pd.read_csv(HERE/'output/state_conditioned_scaling_results.csv')
    for family,part in summary.groupby('state_family'):
        compared=part.groupby(KEY,as_index=False).incremental_pnl.sum().merge(states_.groupby(KEY,as_index=False).incremental_pnl.sum(),on=KEY,suffixes=('_bucket','_daily'))
        assert np.allclose(compared.incremental_pnl_bucket,compared.incremental_pnl_daily,atol=1e-5,rtol=0)


def test_full_book_actual_categories_and_lot_pnl_bridge():
    annual=pd.read_csv(HERE/'output/annual_scaling_metrics.csv');categories=pd.read_csv(HERE/'output/annual_full_book_category_contribution.csv')
    joined=categories.groupby(K,as_index=False).pnl.sum().merge(annual[K+['net_pnl']],on=K,validate='one_to_one')
    assert len(joined)==144 and np.allclose(joined.pnl,joined.net_pnl,atol=1e-5,rtol=0)
    for gap in ['OGR','IFCGR']:
        p=folder(gap,'independent','G25','FULL_BOOK_NORMALIZATION',END)
        actual=fills_frame(p)
        d=pd.read_parquet(HERE/'cache/rebalance'/f'{gap}__independent__G25__FULL_BOOK_NORMALIZATION/details.parquet')
        d=d.loc[d.category.ne('CASH_RESIDUAL')]
        assert len(d)==len(actual)
        assert np.isclose(d.delta_notional.abs().sum(),actual.notional.sum())
        assert np.isclose(d.fees.sum(),actual.fee.sum())
        assert d.loc[d.side.eq('BUY'),'vintage_id'].is_unique


def test_mechanics_common_inputs_and_historical_parent_identity():
    receipts=json.loads((HERE/'output/authoritative_scaling_receipts.json').read_text())
    assert len(receipts)==24
    check=pd.read_csv(HERE/'output/continuous_scaling_parent_prefix.csv')
    assert len(check)==24 and check.status.str.startswith('PASS').all()
    for gap in ['OGR','IFCGR']:
        for mode in ['independent','confirmation_tag']:
            for target in ['G25','G100']:
                a=folder(gap,mode,target,'FULL_BOOK_NORMALIZATION',END);b=folder(gap,mode,target,'ENTRY_ONLY',END)
                proof=pd.read_csv(HERE/'output/mechanics_input_identity.csv')
                proof=proof.loc[proof.gap.eq(gap)&proof.mcb_mode.eq(mode)&proof.target.eq(target)]
                assert len(proof)==3 and proof.status.eq('PASS').all()
                assert proof.input_identity.eq(sha256(HERE/'account_run_input_identity.json')).all()
                x=json.loads((a/'account.json').read_text());y=json.loads((b/'account.json').read_text())
                assert x['initial_states']==y['initial_states']


def test_capacity_observed_units_and_linear_stress_only():
    d=pd.read_csv(HERE/'output/g25_capacity_audit.csv')
    observed=d.daily_turnover_cny.gt(0)
    assert np.allclose(d.loc[observed,'participation_daily'],d.loc[observed,'notional']/d.loc[observed,'daily_turnover_cny'])
    m=d.minute_amount_cny.gt(0)
    assert np.allclose(d.loc[m,'order_over_minute_amount'],d.loc[m,'notional']/d.loc[m,'minute_amount_cny'])
    assert not json.loads((HERE/'output/g25_capacity_status.json').read_text())['fills_modified']
    s=pd.read_csv(HERE/'output/account_size_capacity_reference.csv')
    for _,p in s.groupby(['gap','mcb_mode','strategy']):
        p=p.set_index('account_size_multiple')
        assert np.allclose(p.max_participation,p.loc[1,'max_participation']*p.index)


def test_drawdown_components_sum_to_actual_peak_trough_change():
    d=pd.read_csv(HERE/'output/yearly_drawdown_attribution.csv');c=pd.read_csv(HERE/'output/yearly_drawdown_components.csv')
    assert len(d)==168
    for dimension,frame in c.groupby('dimension'):
        t=frame.groupby(K+['scope'],as_index=False).pnl.sum().merge(d[K+['scope','actual_pnl']],on=K+['scope'],validate='one_to_one')
        assert np.allclose(t.pnl,t.actual_pnl,atol=1e-5,rtol=0)


def test_router_gate_has_no_forced_candidate_or_large_action_space():
    contract=json.loads((HERE/'contracts/scaling_regime_attribution_v2.json').read_text())
    assert contract['router_actions']==['NATIVE','G25'] and contract['maximum_router_candidates']==1
    q=pd.read_csv(HERE/'output/router_candidate_evidence.csv')
    status=json.loads((HERE/'output/router_qualification_status.json').read_text())
    if status['status']=='NO_STABLE_SCALING_REGIME_ROUTER':
        assert q.numerical_stability_gate.eq('FAIL').all()
        assert not (HERE/'output/router_results.csv').exists()
    else:
        assert status['status']=='NATIVE_OR_G25_SHADOW_ROUTER_CANDIDATE'
        assert (HERE/'output/router_results.csv').exists()


def test_actual_independent_recalculation_receipts():
    economic=pd.read_csv(HERE/'output/economic_output_reproduction.csv')
    assert len(economic)==7 and economic.status.eq('PASS').all() and economic.byte_identical.all()
    action=json.loads((HERE/'output/rebalance_independent_reproduction.json').read_text())
    assert action['status']=='PASS' and action['actual_recomputation_from_account']
    assert action['rows']>100000


def test_forward_diagnostics_do_not_cross_unresolved_stock_lineage():
    d=pd.read_parquet(HERE/'cache/rebalance/OGR__independent__G25__FULL_BOOK_NORMALIZATION/details.parquet')
    rejected=0
    for horizon in [1,3,5,10,20]:
        mask=d[f'forward_{horizon}d_status'].fillna('').str.startswith('UNRESOLVED_STOCK_COORDINATE')
        rejected+=int(mask.sum())
        assert d.loc[mask,f'forward_{horizon}d_pnl'].isna().all()
        assert d.loc[mask,'side'].eq('SELL').all() and d.loc[mask,'strategy'].ne('SMV6').all()
    assert rejected>0


def test_losing_holding_context_uses_prior_completed_date_only():
    d=pd.read_csv(HERE/'output/existing_add_known_state.csv',usecols=['timestamp','prior_completed_date','prior_held_unrealized_pnl','known_prior_holding_state'],parse_dates=['timestamp','prior_completed_date'])
    observed=d.prior_held_unrealized_pnl.notna()
    assert d.loc[observed,'prior_completed_date'].lt(d.loc[observed,'timestamp'].dt.normalize()).all()
    assert d.loc[d.known_prior_holding_state.eq('PRIOR_CLOSE_LOSING_HOLDING'),'prior_held_unrealized_pnl'].lt(0).all()
