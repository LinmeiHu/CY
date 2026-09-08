"""Execution and cache failures found by the September engineering audit."""
from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from research.capital_scaling_v1.tests.test_scaling import setup, request, T


@pytest.mark.parametrize('field,value', [
    ('decision_at', T), ('decision_at', pd.NaT),
    ('earliest_execution_at', T + pd.Timedelta(minutes=1)),
    ('earliest_execution_at', pd.NaT), ('price', np.nan),
])
def test_scaled_intent_validation_precedes_mutation(field, value):
    account, scaling = setup()
    intent = replace(request(scaling), **{field: value})
    before = (account.cash, deepcopy(account.lots), len(account.checkpoints))
    with pytest.raises(ValueError):
        scaling.fund([intent], {}, 'P0', T)
    assert (account.cash, account.lots, len(account.checkpoints)) == before
    assert not scaling.desired and not scaling.membership


def test_scaled_completed_event_cannot_be_funded_twice():
    account, scaling = setup()
    intent = request(scaling)
    scaling.fund([intent], {}, 'P0', T)
    later = T + pd.Timedelta(days=3)
    scaling.native_close(intent.event_id, 10., later, 0.)
    with pytest.raises(ValueError, match='duplicate|replay'):
        scaling.fund([intent], {}, 'P0', later)
    assert not account.positions


def test_native_request_cannot_override_registered_buy_restriction():
    account, scaling = setup()
    scaling.data['quotes'][T]['A']['buy'] = False
    scaling.fund([request(scaling)], {}, 'P0', T)
    assert not account.fills
    assert not scaling.desired


def test_satisfied_entry_only_target_is_not_a_pending_order():
    account, scaling = setup(mechanic='ENTRY_ONLY')
    scaling.fund([request(scaling)], {}, 'P0', T)
    later = T + pd.Timedelta(days=3)
    scaling.data['quotes'][later] = scaling.data['quotes'][T]
    scaling.fund([replace(request(scaling, 'E2', 'B'), earliest_execution_at=later)], {}, 'P0', later)
    assert account.positions['A'] > 0
    assert not scaling.pending


def test_relative_weight_error_reports_locked_inventory():
    _, scaling = setup()
    scaling.fund([request(scaling)], {}, 'P0', T)
    scaling.fund([request(scaling, 'E2', 'B')], {}, 'P0', T)
    assert scaling.normalizations[-1]['relative_weight_error'] > .4


@pytest.mark.parametrize('field', ['cash', 'nav', 'gross_exposure'])
def test_baseline_nan_reference_cannot_pass(tmp_path, monkeypatch, field):
    from research.capital_scaling_v1 import run
    case = dict(scope='COMBINED', gap='OGR', period='P', mcb_mode='independent')
    folder = tmp_path/'cache/scenarios/OGR/P/independent/P0'
    folder.mkdir(parents=True)
    daily = pd.DataFrame([dict(trade_date=T.normalize(), cash=100., nav=100., gross_exposure=0.)])
    reference = daily.copy()
    reference[field] = np.nan
    reference.to_parquet(folder/'daily.parquet', index=False)
    monkeypatch.setattr(run, 'PARENT', tmp_path)
    with pytest.raises(ValueError, match='nonfinite|baseline'):
        run.verify_baseline(case, daily)


def test_incomplete_cache_receipt_fails_before_read(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import run
    case = run.scenarios()[0][0]
    folder = tmp_path/run.case_key(case)
    folder.mkdir()
    (folder/'receipt.json').write_text(json.dumps(dict(case=case, hashes={}, validation='PASS')))
    monkeypatch.setattr(run, 'read_account', lambda _: pytest.fail('unverified cache was read'))
    with pytest.raises(ValueError, match='receipt|artifact'):
        run.run_case(case, {}, tmp_path)


def test_delayed_gap_exit_uses_next_legal_quote_and_releases_all_inventory():
    from research.capital_scaling_v1.scaling import Scaling
    from research.shared_capital_v1.gap_p0 import replay
    from research.shared_capital_v1.shared_account.engine import PhysicalAccount
    from research.shared_capital_v1.shared_account.scheduler import Event, run_streams
    account = PhysicalAccount('OGR', initial_cash=4000.)
    account.initial_states = {s: dict(nav=1000., cash=1000.) for s in account.strategies}
    scaling = Scaling(['OGR'], .5)
    entry, exit_time, next_open = T, T + pd.Timedelta(days=3, hours=1), T + pd.Timedelta(days=4)
    data = dict(gap='OGR', native_requests={('P', 'OGR', 'OGR', 'G'): dict(native_requested_notional=20.)},
                quotes={t: {'A': dict(price=p, buy=True, sell=True)} for t, p in [(entry, 10.), (exit_time, 11.), (next_open, 12.)]})
    scaling.bind(account, account.initial_states, data, 'P', '2020-01-03', '2020-01-07')
    trades = pd.DataFrame([dict(gap_id='G', symbol='A', board='MAIN', signal_time=T-pd.Timedelta(minutes=1),
        entry_time=entry, entry_date=entry.normalize(), exit_time=exit_time, exit_date=exit_time.normalize(),
        entry_raw_price=10., exit_raw_price=11., entry_coordinate_price=10., target_coordinate=11.,
        pre_gap_inside_density_relative_local=.1)])
    daily = pd.DataFrame([dict(symbol='A', trade_date=d, open=10., close=10.) for d in pd.bdate_range('2020-01-03', '2020-01-07')])
    stream, _ = replay('OGR', trades, daily, '2020-01-03', '2020-01-07', physical=account, stream_only=True,
                       action_registry=pd.DataFrame(columns=['record_date']))
    def lock_new_shares():
        # Model a capital add-on acquired on the native exit date.
        account.lots['G']['acquired_at'] = exit_time.normalize()
    run_streams([stream, [Event(exit_time-pd.Timedelta(minutes=1), 'SCALING', 'CAPITAL', 'LOCK', lock_new_shares)]])
    sells = [f for f in account.fills if f['side'] == 'SELL']
    assert len(sells) == 1 and sells[0]['exit'] == next_open
    assert sells[0]['exit_price'] == 12.
    assert not account.positions and not account.lots


def test_etf_native_zero_target_liquidates_scaled_holding():
    from research.capital_scaling_v1.scaling import Scaling, ScalingPlatform
    from research.shared_capital_v1.tests.test_baseline_closure import platform
    p = platform(ScalingPlatform)
    p.shares.clear()
    account = p.physical
    account.initial_states = {s: dict(nav=10000., cash=10000.) for s in account.strategies}
    scaling = Scaling(['SMV6'], 1.)
    data = dict(gap='OGR', quotes={}, native_requests={},
                native_home={('P', 'OGR'): pd.DataFrame({'SMV6_nav': [10000.]}, index=[T])})
    scaling.bind(account, account.initial_states, data, 'P', '2020-01-03', '2020-01-03')
    scaling.platform = p
    p.order_target_percent('B', .5)
    assert account.positions['B'] > 0
    p.order_target_percent('B', 0.)
    assert not account.positions and not p.shares and not scaling.desired


def test_failed_preflight_replaces_stale_pass_before_loading(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import run
    monkeypatch.setattr(run, 'OUT', tmp_path)
    for name in ('baseline_gate.json', 'research_gate.json'):
        (tmp_path/name).write_text('{"status":"PASS"}')
    def reject():
        raise ValueError('input drift')
    monkeypatch.setattr(run, 'preflight', reject)
    monkeypatch.setattr(run, 'load', lambda: pytest.fail('loaded before preflight'))
    with pytest.raises(ValueError, match='input drift'):
        run.main(['--stage', 'all'])
    assert all(json.loads((tmp_path/n).read_text())['status'] == 'FAIL'
               for n in ('baseline_gate.json', 'research_gate.json'))


def test_native_cache_reuse_requires_same_native_producers_and_states():
    from research.capital_scaling_v1.run import native_identity_matches
    current = dict(contract='C', input_manifest='I', native_reference_manifest='R', initial_states={'A': 'V1'},
                   producers={'research/shared_capital_v1/shared_account/engine.py': 'NATIVE_V1',
                              'research/capital_scaling_v1/scaling.py': 'SCALE_V1'})
    previous = deepcopy(current)
    previous['producers']['research/capital_scaling_v1/scaling.py'] = 'SCALE_OLD'
    assert native_identity_matches(previous, current)
    previous['producers']['research/shared_capital_v1/shared_account/engine.py'] = 'NATIVE_OLD'
    assert not native_identity_matches(previous, current)
    previous = deepcopy(current)
    previous['initial_states']['A'] = 'OLD'
    assert not native_identity_matches(previous, current)


def test_cache_roundtrip_regenerates_summaries_without_invalidating_replay(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import run
    from research.shared_capital_v1.shared_account.engine import PhysicalAccount
    case = next(c for c in run.scenarios()[0] if c['scope'] == 'COMBINED')
    account = PhysicalAccount('OGR', initial_cash=4000.)
    account.initial_states = {s: dict(nav=1000., cash=1000.) for s in account.strategies}
    account.funding = SimpleNamespace(demand=[])
    account.capital_days_by_event = {}
    rows = []
    for day in pd.bdate_range('2018-01-02', periods=2):
        row = dict(account.complete_timestamp(day+pd.Timedelta(hours=15, minutes=1)), trade_date=day,
                   max_security_exposure=0., root_pnl_json='{}')
        for s in account.strategies:
            row.update({s+'_cash': 1000., s+'_nav': 1000., s+'_exposure': 0.})
        account.account_timeline[-1].update(row)
        rows.append(row)
    daily = pd.DataFrame(rows)
    data = dict(etf=({'000852.SH': pd.DataFrame({'pre_adj_close': 10.}, index=daily.trade_date)}, {}, None))
    calls = []
    def replay(*args, **kwargs):
        calls.append(True)
        return account, daily, {}, None, []
    monkeypatch.setattr(run, 'replay', replay)
    monkeypatch.setattr(run, 'verify_baseline', lambda *_: {})
    folder = tmp_path/run.case_key(case)
    folder.mkdir()
    (folder/'summary.json').write_text('interrupted old summary')
    first = run.run_case(case, data, tmp_path)
    (folder/'summary.json').write_text('replaceable derived summary')
    second = run.run_case(case, data, tmp_path)
    assert len(calls) == 1 and first['final_nav'] == second['final_nav'] == 4000.
    assert first['net_pnl'] == second['net_pnl'] == 0.
    assert 'summary.json' not in json.loads((folder/'receipt.json').read_text())['hashes']


@pytest.mark.parametrize('selected', [[], ['ATRDR', 'ATRDR'], ['UNKNOWN']])
def test_invalid_scaling_selection_fails_at_construction(selected):
    from research.capital_scaling_v1.scaling import Scaling
    with pytest.raises(ValueError, match='selection'):
        Scaling(selected, 1.)


def test_scaling_cannot_admit_an_unselected_strategy():
    account, scaling = setup()
    order = replace(request(scaling), strategy='MCB')
    scaling.data['native_requests'][('P', 'OGR', 'MCB', order.event_id)] = dict(native_requested_notional=20.)
    with pytest.raises(ValueError, match='inactive'):
        scaling.fund([order], {}, 'P0', T)
    assert not account.fills and not scaling.desired
