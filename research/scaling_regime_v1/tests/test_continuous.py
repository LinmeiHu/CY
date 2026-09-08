import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import duckdb
import numpy as np
import pandas as pd
import pytest
from five_strategy_bundle.strategies import smv6_frozen
from research.scaling_regime_v1 import audit,protocol,snapshot,accounts,closure_checks

HERE=audit.HERE


def test_explicit_protocols_and_research_only_reset():
    d=protocol.definitions()
    assert set(d['protocols'])=={'SEGMENTED_RESEARCH_PROTOCOL','CONTINUOUS_LIVE_PROTOCOL'}
    assert len(d['states'])==50
    assert all(r['segmented_2022']!=r['continuous_2022'] for r in d['states'])
    assert all(r['reset_classification']=='RESEARCH_SEGMENT_ONLY' for r in d['states'])


def test_smv6_week_boundary_is_callback_state_not_year_switch():
    fn=smv6_frozen.is_new_trading_week
    assert not fn(SimpleNamespace(prev_trade_date=None),pd.Timestamp('2022-01-04'))
    assert fn(SimpleNamespace(prev_trade_date=pd.Timestamp('2021-12-31')),pd.Timestamp('2022-01-04'))
    assert not fn(SimpleNamespace(prev_trade_date=pd.Timestamp('2022-01-04')),pd.Timestamp('2022-01-05'))
    source=inspect.getsource(smv6_frozen)
    assert '2022-01-01' not in source


def test_actual_smv6_boundary_trace_and_state_carry():
    data=json.loads((HERE/'output/smv6_boundary_trace.json').read_text())
    a=[r for r in data['continuous']['rows'] if r['phase']=='BEFORE_PREPARE'][0]
    b=[r for r in data['segmented']['rows'] if r['phase']=='BEFORE_PREPARE'][0]
    assert a['positions']==b['positions']=={}
    assert a['callback_state']['prev_trade_date'].startswith('2021-12-31')
    assert b['callback_state']['prev_trade_date'] is None
    assert a['cash']>b['cash']
    assert any('week_boundary=True' in x and 'permission=False' in x for x in data['continuous']['logs'])
    assert any('week_boundary=False' in x and 'permission=True' in x for x in data['segmented']['logs'])
    assert max(data['continuous']['reference_max_abs_errors'].values())<1e-6


def test_mcb_original_snapshot_binding_has_actual_source_hashes():
    source=snapshot.binding()
    proof=json.loads((HERE/'output/mcb_snapshot_source_proof.json').read_text())
    assert source['snapshot_id']==proof['snapshot_id']=='QD-008-EASTMONEY-PIT-20260820'
    assert audit.sha256(snapshot.INDUSTRY)==proof['industry_daily_sha256']
    table=pd.read_csv(HERE/'output/mcb_snapshot_predicate_equivalence.csv')
    assert len(table)>10000 and table.industry_snapshot_id.notna().all()
    assert table.same_result.all()
    assert (pd.to_datetime(table.source_notice_date)<pd.to_datetime(table.date)).all()


def test_mcb_rejects_missing_snapshot_even_when_causal_industry_present(tmp_path):
    row=pd.read_parquet(snapshot.CACHE/'mcb/v53.parquet').iloc[0]
    with duckdb.connect() as c:
        daily=c.execute('SELECT * FROM read_parquet(?) WHERE symbol=? AND trade_date<=? ORDER BY trade_date',
            [str(snapshot.CACHE/'mcb_features.parquet'),row.symbol,row.signal_date]).fetchdf()
    good=tmp_path/'good.parquet';bad=tmp_path/'bad.parquet'
    daily.to_parquet(good,index=False)
    daily['industry_snapshot_id']=None;daily.to_parquet(bad,index=False)
    state=snapshot.CACHE/'mcb_market_industry_state.parquet'
    fn=snapshot.producer('2026-09-04')
    accepted=fn(good,state,tmp_path/'accepted.parquet')
    assert row.event_id in set(accepted.event_id)
    from five_strategy_bundle.errors import ReproductionError
    with pytest.raises(ReproductionError,match='empty or duplicate V53 identity'):
        fn(bad,state,tmp_path/'rejected.parquet')
    assert daily.causal_industry.notna().any()


def test_top5_prefix_cash_nav_positions_and_fills():
    table=pd.read_csv(HERE/'output/new_top5_prefix_identity.csv')
    assert len(table)==5 and table.days.eq(973).all()
    assert table.status.eq('PASS').all() and table.fills_identity.eq('PASS').all()
    assert table[['cash','nav','gross_exposure']].max().max()<1e-6
    selected=pd.read_csv(HERE/'evidence/combined_top5_backtest_curve_selection.csv')
    for case,old in zip(accounts.group_cases('identity_prefix'),selected.itertuples()):
        actual=json.loads((accounts.folder(*case)/'account.json').read_text())
        expected=json.loads((Path(old.source)/'account.json').read_text())
        closure_checks.assert_json_close(actual['positions'],expected['positions'])


def test_bounded_feature_and_signal_producers_match_full_prefix():
    t=pd.read_csv(HERE/'output/continuous_signal_prefix_invariance.csv')
    assert t.end.nunique()==6 and t.status.eq('PASS').all()
    stock=t.loc[t.strategy.isin(['ATRDR','MCB'])]
    assert len(stock)==24 and stock.scope.eq('RAW_DAILY_BOUND_BEFORE_FEATURE_AND_SIGNAL_PRODUCTION').all()


def test_continuous_account_prefix_invariance_all_four_structures():
    table=pd.read_csv(HERE/'output/continuous_prefix_invariance.csv')
    assert len(table)==20 and table.end.nunique()==5
    for field in ['status','intents','fills','positions','cash','nav','callback_state']:assert table[field].eq('PASS').all()


def test_native_historical_identity_all_four_structures():
    table=pd.read_csv(HERE/'output/continuous_native_parent_prefix.csv')
    assert len(table)==4 and table.days.eq(973).all() and table.status.eq('PASS').all()


def test_runtime_matrix_has_no_unresolved_difference_and_exact_universes():
    table=pd.read_csv(HERE/'output/continuous_runtime_identity_matrix.csv')
    assert len(table)==60
    assert set(table.status)<={'EXACT','AUTHORIZED_CONTINUOUS_STATE_CARRY','SEGMENT_PROTOCOL_DIFFERENCE'}
    universe=table.loc[table['item'].eq('universe')]
    assert len(universe)==5 and universe.status.eq('EXACT').all()
    assert table.loc[table.strategy.eq('MCB') & table['item'].eq('eligibility'),'legacy_status'].item()=='BUG'


def test_frozen_costs_execution_and_scaling_class_are_unchanged():
    binding=json.loads((HERE/'account_run_input_identity.json').read_text())
    paths=[audit.PARENT/'scaling.py',audit.ROOT/'research/shared_capital_v1/stock_p0.py',audit.ROOT/'research/shared_capital_v1/gap_p0.py',audit.ROOT/'research/shared_capital_v1/smv6_physical.py']
    assert all(audit.sha256(p)==binding[str(p)] for p in paths)
    source=inspect.getsource(accounts.run_case)
    assert "scaling=Scaling(" in source and "observed_replay(data" in source


def test_no_post2021_top_reselection_or_false_timestamp_claim():
    t=pd.read_csv(HERE/'output/top_combination_selection_identity.csv')
    assert t.ranking_source_period.eq('2018-01-01/2021-12-31').all()
    assert t.selection_timestamp.eq('NOT_RECORDED_IN_ORIGINAL_PRODUCER').all()
    assert t[['gap','mcb_mode','target']].values.tolist()==[['OGR','confirmation_tag','G100'],['IFCGR','confirmation_tag','G100'],['OGR','independent','G100'],['IFCGR','independent','G100'],['OGR','independent','G75']]


def test_authoritative_protocol_and_versioned_attribution_frozen():
    for contract,receipt in [('continuous_rollforward_protocol_v1.json','continuous_protocol_freeze_receipt.json'),('scaling_regime_attribution_v2.json','attribution_v2_freeze_receipt.json')]:
        data=json.loads((HERE/'contracts'/receipt).read_text())
        assert audit.sha256(HERE/'contracts'/contract)==data['sha256']
    c=json.loads((HERE/'contracts/scaling_regime_attribution_v2.json').read_text())
    old=json.loads((HERE/'contracts/scaling_regime_attribution_v1.json').read_text())
    for key in ['state_features','state_definitions','router_actions','scaling_targets']:
        assert c[key]==old[key]


def test_legacy_is_preserved_and_never_relabelled_authoritative():
    legacy=(HERE/'reports/legacy_rollforward_deprecation.md').read_text()
    assert 'LEGACY_ROLLFORWARD_IDENTITY_MISMATCH' in legacy
    assert audit.sha256(HERE/'evidence/combined_top5_backtest_curve_selection.csv') in set(pd.read_csv(HERE/'output/top_combination_selection_identity.csv').source_sha256)
    assert pd.read_csv(HERE/'output/rollforward_identity_audit.csv').status.ne('PASS').any()


def test_native_deterministic_rerun_and_scaling_mechanics_receipts():
    t=pd.read_csv(HERE/'output/continuous_determinism.csv')
    assert t.status.eq('PASS').all() and t.layer.eq('NATIVE_ACTUAL_RERUN').any()
    r=json.loads((HERE/'output/authoritative_scaling_receipts.json').read_text())
    assert len(r)==24 and all(x['status']=='PASS' for x in r)
    assert {tuple(x['case'][2:4]) for x in r}>={('G25','FULL_BOOK_NORMALIZATION'),('G100','FULL_BOOK_NORMALIZATION'),('G100','ENTRY_ONLY')}


def test_annual_attribution_is_additive_actual_pnl():
    t=pd.read_csv(HERE/'output/annual_scaling_metrics.csv')
    c=pd.read_csv(HERE/'output/annual_strategy_contribution.csv')
    keys=['gap','mcb_mode','target','mechanic','year']
    merged=t.merge(c.groupby(keys,as_index=False).pnl_scaled.sum(),on=keys,validate='one_to_one')
    assert np.allclose(merged.net_pnl,merged.pnl_scaled,rtol=0,atol=1e-5)


@pytest.mark.parametrize('target',[.25,1.])
def test_read_only_scaling_observer_preserves_fills_and_cash(monkeypatch,target):
    from research.capital_scaling_v1.tests import test_scaling as base
    from research.scaling_regime_v1.scaling_observer import ObservedScaling
    a,c=base.setup(target)
    c.fund([base.request(c),base.request(c,'E2','B',6.)],{},'P0',base.T)
    with monkeypatch.context() as m:
        m.setattr(base,'Scaling',ObservedScaling)
        b,d=base.setup(target)
        d.fund([base.request(d),base.request(d,'E2','B',6.)],{},'P0',base.T)
    assert a.fills==b.fills and a.positions==b.positions and a.cash==b.cash
    assert len(d.target_observations)==2


def test_explicit_g25_entry_only_extension_preserves_existing_quantity(monkeypatch):
    from research.capital_scaling_v1.tests import test_scaling as base
    from research.scaling_regime_v1.scaling_observer import ObservedScaling
    with monkeypatch.context() as m:
        m.setattr(base,'Scaling',ObservedScaling)
        a,c=base.setup(.25,mechanic='ENTRY_ONLY')
        c.fund([base.request(c)],{},'P0',base.T)
        before=a.positions['A']
        c.fund([base.request(c,'E2','B',6.)],{},'P0',base.T)
        assert a.positions['A']==before
        assert a.exposure()/(a.cash+a.exposure())<=.25+1e-12
