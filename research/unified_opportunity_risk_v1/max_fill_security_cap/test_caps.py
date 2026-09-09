import numpy as np
import pandas as pd
import pytest
from research.unified_opportunity_risk_v1.exposure_scale.test_scale import pool
from research.unified_opportunity_risk_v1.test_engine import request,WHEN
from research.unified_opportunity_risk_v1.max_fill_security_cap.run import CapPool

@pytest.mark.parametrize('cap',[.1,.15,.2,.3])
def test_only_security_cap_changes_max_fill_and_attribution(cap):
    a,old=pool('MAX_FILL')
    p=CapPool(dict(old.config,security_cap=cap),{('000001.SZ',WHEN.normalize()):1e9},{})
    p.cal=old.cal;p.refs=old.refs;p.bind(a)
    p.allocate([request('one'),request('two',strategy='MCB')],WHEN)
    nav=a.cash+a.exposure()
    assert cap*.99<a.exposure()/nav<=cap+1e-9
    assert a.cash>=-1e-8 and a.exposure()<=nav+1e-8
    assert p.cash_attribution[0]['SOFT_RISK_BUDGET']==p.cash_attribution[0]['FAMILY_RISK_BUDGET']==0
    assert abs(p.cash_attribution[0]['native_execution_residual'])<1e-6


def test_replay_detail_comparison_preserves_small_float_delta():
    from research.unified_opportunity_risk_v1.max_fill_security_cap.analyze import structured_delta
    delta=structured_delta({'quantity':[114.24120244589238]}, {'quantity':[114.2412024458924]})
    assert 0<delta<1e-10


def test_replay_detail_comparison_rejects_changed_economics_or_identity():
    from research.unified_opportunity_risk_v1.max_fill_security_cap.analyze import structured_delta
    for a,b in [({'quantity':1.},{'quantity':1.00001}),({'symbol':'A'},{'symbol':'B'}),({'a':1},{'b':1})]:
        with pytest.raises(AssertionError):structured_delta(a,b)


def test_ten_percent_matches_previous_allocator():
    a,old=pool('MAX_FILL');old.config['security_cap']=.1;old.liquidity={('000001.SZ',WHEN.normalize()):1e9}
    b,p=pool('MAX_FILL');new=CapPool(dict(p.config,security_cap=.1),old.liquidity,{})
    new.cal=p.cal;new.refs=p.refs;new.bind(b)
    batch=[request('one'),request('two',strategy='MCB')]
    old.allocate(batch,WHEN);new.allocate(batch,WHEN)
    pd.testing.assert_frame_equal(pd.DataFrame(a.fills),pd.DataFrame(b.fills),check_exact=True)
    assert a.cash==b.cash

@pytest.mark.parametrize('x',[1.,1.5,2.,3.,5.,8.,10.])
@pytest.mark.parametrize('cap',[.1,.15,.2,.3])
def test_finite_x_y_preserves_target_scaling_and_soft_budgets(x,cap):
    a,old=pool(x)
    p=CapPool(dict(old.config,security_cap=cap),{('000001.SZ',WHEN.normalize()):1e9},{})
    p.cal=old.cal;p.refs=old.refs;p.bind(a)
    p.allocate([request('a')],WHEN)
    row=p.admissions[0]
    assert row['scaled_request']==x*row['baseline_target']
    assert p.risk_history[0]['account_budget']==x*p.refs['account']
    assert a.exposure()/(a.cash+a.exposure())<=cap+1e-9
    assert abs(p.cash_attribution[0]['native_execution_residual'])<1e-6
