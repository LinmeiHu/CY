from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from research.capital_scaling_v1.scaling import Scaling
from research.shared_capital_v1.shared_account.engine import PhysicalAccount, Intent
from research.shared_capital_v1.shared_account.corporate_actions import ShareConversion, CashDistribution

T = pd.Timestamp('2020-01-03 09:30')


def setup(target=1., mechanic='FULL_BOOK_NORMALIZATION'):
    a = PhysicalAccount('OGR', initial_cash=4000.)
    states = {s: dict(nav=1000., cash=1000.) for s in a.strategies}
    a.initial_states = deepcopy(states)
    q = {T: {'A': dict(price=10., buy=True, sell=True), 'B': dict(price=10., buy=True, sell=True)}}
    data = dict(gap='OGR', quotes=q, native_requests={})
    c = Scaling(['ATRDR'], target, mechanic=mechanic)
    c.bind(a, states, data, 'P', '2020-01-01', '2020-12-31')
    return a, c


def request(c, eid='E1', symbol='A', qty=2.):
    i = Intent('ATRDR', 'BULL', 'DEMAND', eid, '', symbol, T-pd.Timedelta(days=1), T, (0,), qty, 10., 0., board='MAIN')
    c.data['native_requests'][('P', 'OGR', 'ATRDR', eid)] = dict(native_requested_notional=qty*10.)
    return i


def test_full_book_relative_weights_and_single_name_extreme():
    a, c = setup()
    i, j = request(c), request(c, 'E2', 'B', 6.)
    c.fund([i, j], {}, 'P0', T)
    assert c.root_quantity('E2')/c.root_quantity('E1') == pytest.approx(3.)
    assert a.exposure()/a.initial_cash == pytest.approx(1., abs=1e-10)
    one, control = setup()
    control.fund([request(control)], {}, 'P0', T)
    assert one.positions['A']*10/one.initial_cash == pytest.approx(1., abs=1e-10)
    assert one.cash >= 0


@pytest.mark.parametrize('shortfall,expected', [(0., 100.), (.01, 0.)])
def test_etf_exact_affordable_lot_is_preserved_without_financing(shortfall, expected):
    from research.capital_scaling_v1.scaling import ScalingPlatform
    from research.shared_capital_v1.tests.test_baseline_closure import platform
    p = platform(ScalingPlatform)
    p.shares.clear()
    a = p.physical
    cash = 100*10*1.0008*(1+p.commission_rate)-shortfall
    a.sleeve_cash = {s:cash for s in a.strategies}
    a.initial_states = {s:dict(nav=cash,cash=cash) for s in a.strategies}
    c = Scaling(['SMV6'], 1.)
    data = dict(gap='OGR', quotes={}, native_requests={},
                native_home={('P','OGR'):pd.DataFrame({'SMV6_nav':[10000.]},index=[T])})
    c.bind(a,a.initial_states,data,'P','2020-01-03','2020-01-03')
    c.platform = p
    p.order_target_percent('B', .5)
    assert a.positions.get('B',0.) == expected
    assert a.cash >= 0
    assert a.exposure() <= a.cash+a.exposure()


def test_observed_large_combined_order_uses_same_requested_and_billed_cost():
    # Actual first combined G100 failure: 2021-10-12, 603348.SH.
    a = PhysicalAccount('OGR', initial_cash=20425796.320744384)
    i = Intent('ATRDR', 'V27', 'DEMAND', 'OBSERVED', '', '603348.SH', T-pd.Timedelta(days=1), T,
               (0,), 668361.5169904239, 30.5, .002)
    bill = i.native_requested_quantity*(i.price*(1+i.fee_rate))
    assert i.native_requested_notional == bill
    assert a._fill(i, bill, 'SCALED', T)
    assert a.cash == 20425796.320744384-bill
    assert a.cash >= 0


def test_zero_book_stays_cash_and_price_drift_does_not_normalize():
    a, c = setup(.25)
    c.normalize(T, set(), reason='NO_NATIVE_CHANGE')
    assert not a.lots and not c.normalizations
    c.fund([request(c)], {}, 'P0', T)
    fills = deepcopy(a.fills)
    a.mark({'A': 20.}, observed_at=T+pd.Timedelta(days=1))
    c.completed(T+pd.Timedelta(days=1))
    assert a.fills == fills
    assert a.exposure()/(a.cash+a.exposure()) > .25


def test_same_day_new_quantity_cannot_be_sold_with_old_inventory():
    a, c = setup()
    c.fund([request(c)], {}, 'P0', T)
    before = a.positions.copy()
    c.native_close('E1', 10., T+pd.Timedelta(hours=1), 0.)
    assert a.positions == before
    c.native_close('E1', 10., T+pd.Timedelta(days=3), 0.)
    assert not a.positions and a.cash == pytest.approx(1000.)
    assert 'E1' not in c.desired


def test_native_exit_sells_old_inventory_but_waits_for_same_day_addon():
    a, c = setup()
    c.fund([request(c), request(c, 'E2', 'B')], {}, 'P0', T)
    later = T+pd.Timedelta(days=3)
    c.data['quotes'][later] = c.data['quotes'][T]
    c.native_close('E2', 10., later, 0.)
    c.normalize(later, {'ATRDR'}, reason='PRIOR_NATIVE_EXIT')
    extra = [(key, lot) for key, lot in c.roots('E1') if key != 'E1']
    assert extra and extra[0][1]['quantity'] > 0
    added = extra[0][1]['quantity']
    for key, _ in list(c.roots('E1')):
        c.native_close(key, 10., later+pd.Timedelta(hours=1), 0.)
    assert c.root_quantity('E1') == pytest.approx(added)
    assert 'E1' not in c.desired
    for key, _ in list(c.roots('E1')):
        c.native_close(key, 10., later+pd.Timedelta(days=1), 0.)
    assert not a.positions


def test_actual_scaled_inventory_drives_future_native_exit_and_state():
    a, c = setup()
    c.fund([request(c)], {}, 'P0', T)
    actual = a.positions['A']
    assert actual > 2.
    c.native_close('E1', 11., T+pd.Timedelta(days=3), .002)
    assert a.cash == pytest.approx(1000.-actual*10+actual*11*.998)
    assert not c.desired and not a.positions
    assert a.fills[-1]['filled_quantity'] == actual


def test_no_new_reference_signal_or_symbol_and_gap_exclusion():
    a, c = setup()
    unknown = request(c)
    c.data['native_requests'].clear()
    c.fund([unknown], {}, 'P0', T)
    assert not a.fills
    with pytest.raises(ValueError, match='mutual'):
        Scaling(['OGR', 'IFCGR'], 1.)
    with pytest.raises(ValueError, match='unregistered'):
        Scaling(['ATRDR'], .35)


def test_scaled_corporate_entitlements_use_actual_record_ownership():
    a, c = setup()
    c.fund([request(c)], {}, 'P0', T)
    quantity = a.positions['A']
    ca = ShareConversion(a)
    dividend = CashDistribution(a)
    day = T+pd.Timedelta(days=3)
    ca.record('C', 'A', .3, day, day)
    dividend.record('D', 'A', .2, day, day, ex_date=day+pd.Timedelta(days=1), payment_date=day+pd.Timedelta(days=1))
    ca.transition('C', 'ACCOUNTING_EFFECTIVE_DATE', day+pd.Timedelta(days=1), day, ex_price=10/1.3)
    assert a.pending_positions['A'] == pytest.approx(quantity*.3)
    assert sum(c.tradable(l, day+pd.Timedelta(days=1)) for l in a.lots.values()) == pytest.approx(quantity)
    before = a.cash
    dividend.pay('D', day+pd.Timedelta(days=1), day)
    assert a.cash-before == pytest.approx(quantity*.2)
    ca.transition('C', 'SHARE_ARRIVAL_DATE', day+pd.Timedelta(days=2), day)
    ca.transition('C', 'TRADABLE_DATE', day+pd.Timedelta(days=2), day)
    assert a.positions['A'] == pytest.approx(quantity*1.3)


def test_entry_only_is_distinct_and_deterministic():
    outcomes = []
    for mechanic in ('FULL_BOOK_NORMALIZATION', 'ENTRY_ONLY', 'FULL_BOOK_NORMALIZATION'):
        a, c = setup(mechanic=mechanic)
        first = request(c)
        c.fund([first], {}, 'P0', T)
        second_time = T+pd.Timedelta(days=3)
        c.data['quotes'][second_time] = c.data['quotes'][T]
        second = replace(request(c, 'E2', 'B'), earliest_execution_at=second_time)
        c.fund([second], {}, 'P0', second_time)
        outcomes.append((a.positions, a.cash, c.orders))
    assert outcomes[0] == outcomes[2]
    assert outcomes[0][0] != outcomes[1][0]
    assert 'B' in outcomes[0][0] and 'B' not in outcomes[1][0]
