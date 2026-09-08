import json
from types import SimpleNamespace

import pandas as pd
import pytest

from five_strategy_bundle.io import load_input_config
from five_strategy_bundle.errors import ReproductionError
from research.shared_capital_v1.causal_adapters import record_pending_signals
from research.shared_capital_v1.shared_account.engine import PhysicalAccount
from research.shared_capital_v1.stock_p0 import replay
from research.shared_capital_v1.tests.test_baseline_closure import outcomes


def test_config_relative_and_selected_strategy_only(tmp_path, monkeypatch):
    data = tmp_path / 'input.parquet'
    data.touch()
    config = tmp_path / 'inputs.json'
    config.write_text(json.dumps({'inputs': {'daily_hist': 'input.parquet', 'smv6_qmt_root': 'unavailable'}}))
    monkeypatch.chdir('/')
    assert load_input_config(config, required=['daily_hist']) == {'daily_hist': data}
    with pytest.raises(ReproductionError, match='missing'):
        load_input_config(config, required=['smv6_qmt_root'])


@pytest.mark.parametrize('current,previous', [
    ('2020-01-06', '2020-01-03'),
    ('2020-10-09', '2020-09-30'),
    ('2020-05-06', '2020-04-30'),
])
def test_signal_metadata_uses_frozen_event_date(current, previous):
    rows = []
    p = SimpleNamespace(current_date=pd.Timestamp(current).date(), _record=lambda *args, **kw: rows.append((args, kw)))
    context = SimpleNamespace(prev_trade_date=pd.Timestamp(previous), pending_desired=['ETF'], pending_reason='NATIVE')
    record_pending_signals(p, context, set())
    assert rows[0][1]['signal_date'] == pd.Timestamp(previous).date()
    assert context.pending_desired == ['ETF']


def test_account_missing_timestamp_rejected_before_record():
    account = PhysicalAccount('OGR')
    for when in (None, pd.NaT, 'not a timestamp'):
        with pytest.raises(ValueError):
            account.checkpoint(when, 'BROKEN')
    assert account.checkpoints == []


def test_initial_native_callback_reports_completed_input_date():
    rows = []
    p = SimpleNamespace(current_date=pd.Timestamp('2022-01-04').date(),
                        history=lambda *args: {'000852.SH': pd.DataFrame({'close': [10.]}, index=pd.to_datetime(['2021-12-31']))},
                        _record=lambda *args, **kw: rows.append(kw))
    context = SimpleNamespace(prev_trade_date=pd.Timestamp('2022-01-04'), pending_desired=['ETF'], pending_reason='NATIVE_INIT')
    record_pending_signals(p, context, set(), previous_event_date=None)
    assert rows[0]['signal_date'] == pd.Timestamp('2021-12-31').date()


def test_stock_empty_and_unfinished_schema():
    dates = pd.bdate_range('2020-01-03', periods=2)
    rows = [dict(symbol='A', trade_date=d, cal_idx=i, coord_open=10., coord_close=10., coord_high=10., open=10., close=10., coordinate_factor=1., corporate_action_count=0, down_limit_price=8., invalid_step_cum=0., trade_status=1, hard_valid=True, history_valid=True, current_valid=True, corporate_action_valid=True, current_day_data_tradable=True, historical_identity_valid=True, market_rule_valid=True, corporate_action_blocking=False) for i, d in enumerate(dates)]
    entries = outcomes('INCOMPLETE_PATH').assign(source_rank_order=0, route='BULL')
    results = []
    for candidate in (entries.iloc[:0], entries):
        account, intents, rejected, nav, blocker = replay('ATRDR', candidate, pd.DataFrame(rows), '2020-01-03', '2020-01-06', action_registry=pd.DataFrame(columns=['record_date']))
        assert blocker is None
        assert not any(f['side'] == 'SELL' for f in account.fills)
        assert {'event_id', 'native_requested_notional'} <= set(intents)
        assert list(rejected) == ['event_id', 'reason']
        results.append(list(intents))
    assert results[0] == results[1]


def test_p0_native_callback_can_reuse_legally_released_cash():
    from research.shared_capital_v1.shared_account.engine import Intent
    from research.shared_capital_v1.shared_account.native_funding import NativeFunding
    from research.shared_capital_v1.shared_account.scheduler import Event, run_streams
    a = PhysicalAccount('OGR', initial_cash=10000.)
    a.strategies = ('SMV6',)
    a.sleeve_cash = {'SMV6': 10000.}
    a.realized = {'SMV6': 0.}
    funding = NativeFunding(a, 'P0')
    when = pd.Timestamp('2020-01-03 09:30')
    def callback():
        for eid in ('FIRST', 'SECOND'):
            i = Intent('SMV6', 'NATIVE', 'ETF_TIMING', eid, '', eid, when-pd.Timedelta(days=1), when, (0,), 800., 10., 0., lot_size=100)
            a.fund([i], {'SMV6': 10000.}, 'P0', when)
            if eid == 'FIRST':
                a.close(eid, 10., when, 0.)
    run_streams([[Event(when, 'OPEN_CALLBACK', 'SMV6', 'NATIVE', callback)]], funding=funding)
    assert a.positions == {'SECOND': 800.}
    assert a.cash == 2000.


def test_research_cache_identity_binds_inputs_config_and_producer(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import data
    study, parent = tmp_path/'capital', tmp_path/'shared'
    study.mkdir()
    (parent/'contracts').mkdir(parents=True)
    (tmp_path/'five_strategy_exit_risk_v1').mkdir()
    manifest = study/'input_manifest.json'
    manifest.write_text('{}')
    (parent/'contracts/strategy_universe_v1.json').write_text('{}')
    config = tmp_path/'five_strategy_exit_risk_v1/input_config.json'
    config.write_text('{}')
    monkeypatch.setattr(data, 'HERE', study)
    monkeypatch.setattr(data, 'PARENT', parent)
    first = data.cache_identity()
    assert all(first[k] for k in ('inputs', 'period', 'strategy_version', 'producer_version', 'configuration_hash'))
    manifest.write_text('{"changed":true}')
    assert data.cache_identity()['inputs'] != first['inputs']
    config.write_text('{"changed":true}')
    assert data.cache_identity()['configuration_hash'] != first['configuration_hash']


def test_corrupt_cached_scenario_fails_before_reuse(tmp_path):
    from research.capital_scaling_v1.run import run_case, case_key
    case = dict(scope='SINGLE', strategy='ATRDR', gap='OGR', mcb_mode='independent', period='P', target='G100',
                grade='EXECUTION_AWARE_SCALING', mechanic='FULL_BOOK_NORMALIZATION', priority='')
    folder = tmp_path/case_key(case)
    folder.mkdir()
    (folder/'data').write_text('changed')
    (folder/'receipt.json').write_text(json.dumps(dict(case=case, hashes={'data': 'wrong'})))
    with pytest.raises(ValueError, match='hash mismatch'):
        run_case(case, {}, tmp_path)


def test_cli_passes_approved_baseline_and_overwrites_stale_success(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import run
    monkeypatch.setattr(run, 'OUT', tmp_path)
    approved = {'status': 'PASS', 'native_engine_identity': 'native_producer'}
    (tmp_path/'baseline_gate.json').write_text(json.dumps(approved))
    (tmp_path/'research_gate.json').write_text('{"status":"PASS"}')
    calls = []
    def fail(stage, **kwargs):
        calls.append((stage, kwargs))
        assert json.loads((tmp_path/'research_gate.json').read_text())['status'] == 'NOT_RUN'
        raise ValueError('input failed')
    monkeypatch.setattr(run, 'run_stage', fail)
    with pytest.raises(ValueError, match='input failed'):
        run.main(['--stage', 'all', '--revalidate-native'])
    assert calls == [('all', {'revalidate_native': True, 'prior_gate': approved, 'workers': 1})]
    assert json.loads((tmp_path/'baseline_gate.json').read_text())['status'] == 'FAIL'
    assert json.loads((tmp_path/'research_gate.json').read_text())['status'] == 'FAIL'


def test_source_changed_during_run_fails_closed(tmp_path, monkeypatch):
    from research.capital_scaling_v1 import run
    producer = tmp_path/'producer.py'
    producer.write_text('original')
    monkeypatch.setattr(run, 'ROOT', tmp_path)
    payload = {'producers': {'producer.py': run.sha256(producer)}}
    run.verify_running_source(payload)
    producer.write_text('concurrent edit')
    with pytest.raises(ValueError, match='producer changed'):
        run.verify_running_source(payload)


def test_schema_hardening_cannot_override_alpha_identity(tmp_path, monkeypatch):
    from research.shared_capital_v1 import universe
    from five_strategy_bundle.io import sha256
    source = tmp_path/'src/five_strategy_bundle/execution/daily.py'
    source.parent.mkdir(parents=True)
    source.write_text('old')
    name = str(source.relative_to(tmp_path))
    old = sha256(source)
    raw = tmp_path/'raw'
    raw.write_text('unchanged input')
    contract = tmp_path/'universe.json'
    contract.write_text(json.dumps(dict(source_hashes={name:old}, stock_input=dict(path=str(raw),sha256=sha256(raw)))))
    monkeypatch.setattr(universe, 'CONTRACT', contract)
    monkeypatch.setattr(universe, 'ROOT', tmp_path)
    source.write_text('schema corrected')
    with pytest.raises(ValueError, match='source changed'):
        universe.verify()
    override = tmp_path/'repair.json'
    override.write_text(json.dumps({name:dict(parent_sha256=old,corrected_sha256=sha256(source))}))
    universe.verify(execution_hardening=override)
    override.write_text(json.dumps({'src/five_strategy_bundle/strategies/atrdr.py':{}}))
    with pytest.raises(ValueError, match='cannot override'):
        universe.verify(execution_hardening=override)
