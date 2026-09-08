from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from research.shared_capital_v1.shared_account.engine import Intent, PhysicalAccount

T = pd.Timestamp('2020-01-03 09:30')


def intent(**changes):
    return replace(Intent('ATRDR', 'BULL', 'DEMAND', 'E', '', 'A', T-pd.Timedelta(days=1), T,
                          (0,), 2., 10., 0.), **changes)


@pytest.mark.parametrize('field', ['decision_at', 'earliest_execution_at'])
def test_missing_intent_clock_cannot_fund(field):
    account = PhysicalAccount('OGR', initial_cash=4000.)
    with pytest.raises(ValueError):
        account.fund([intent(**{field: pd.NaT})], {s: 1000. for s in account.strategies}, 'P0', T)
    assert account.cash == 4000. and not account.fills and not account.seen


@pytest.mark.parametrize('operation', ['fund', 'close', 'credit', 'mark'])
def test_invalid_operation_timestamp_does_not_mutate_account(operation):
    account = PhysicalAccount('OGR', initial_cash=4000.)
    account.fund([intent()], {s: 1000. for s in account.strategies}, 'P0', T)
    before = deepcopy(account.__dict__)
    with pytest.raises(ValueError):
        if operation == 'fund':
            account.fund([intent(event_id='NEW', symbol='B')], {s: 1000. for s in account.strategies}, 'P0', pd.NaT)
        elif operation == 'close':
            account.close('E', 11., pd.NaT, 0.)
        elif operation == 'credit':
            account.credit('E', 1., pd.NaT)
        else:
            account.mark({'B': 10.}, basis='RAW', observed_at=pd.NaT)
    assert account.__dict__ == before


@pytest.mark.parametrize('caps,expected', [(dict(native_max_positions=1), 1), (dict(native_daily_entries=1), 1)])
def test_native_limits_work_independently(caps, expected):
    account = PhysicalAccount('OGR', initial_cash=4000.)
    orders = [intent(event_id=str(i), symbol=str(i), **caps) for i in range(2)]
    account.fund(orders, {s: 1000. for s in account.strategies}, 'P0', T)
    assert len(account.lots) == expected
