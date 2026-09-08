import json
import numpy as np
import pytest
from research.unified_opportunity_risk_v1.test_engine import book,request,WHEN
from research.unified_opportunity_risk_v1.exposure_scale.run import ScalePool,BASE_CONFIG,REASONS


def pool(x):
    a,old=book('R1',True)
    p=ScalePool(dict(BASE_CONFIG,exposure_scale=x,risk_profile=1. if x=='MAX_FILL' else x),{}, {})
    p.cal=old.cal;p.refs=dict(opportunity=.001,security=.003,account=.05,family_risk=.04)
    p.bind(a);return a,p


@pytest.mark.parametrize('x',[1.,1.5,2.,3.,5.,8.,10.,'MAX_FILL'])
def test_scale_targets_and_hard_cash_security_defenses(x):
    a,p=pool(x);p.liquidity={('000001.SZ',WHEN.normalize()):1e9}
    p.allocate([request()],WHEN)
    r=p.admissions[0]
    if x!='MAX_FILL':assert r['scaled_request']==x*r['baseline_target']
    assert a.cash>=-1e-8 and a.exposure()<=a.cash+a.exposure()+1e-8
    assert a.exposure()/(a.cash+a.exposure())<=.1+1e-9
    assert np.isclose(sum(p.cash_attribution[0][k] for k in REASONS),a.cash)
    if x=='MAX_FILL':
        assert a.exposure()/(a.cash+a.exposure())>.099
        assert p.cash_attribution[0]['SOFT_RISK_BUDGET']==p.cash_attribution[0]['FAMILY_RISK_BUDGET']==0


def test_same_security_shared_liquidity_and_no_resizing():
    a,p=pool(10.);p.liquidity={('000001.SZ',WHEN.normalize()):100000.}
    p.allocate([request('a'),request('b',strategy='MCB')],WHEN)
    assert a.exposure()<=1000.+1e-8
    old={eid:lot['quantity'] for eid,lot in a.lots.items()}
    p.scale=1.;p.config['risk_profile']=1.
    p.liquidity[('000002.SZ',WHEN.normalize())]=1e8
    p.allocate([request('c','000002.SZ')],WHEN)
    assert all(a.lots[eid]['quantity']==qty for eid,qty in old.items())


def test_max_fill_quality_gate_still_applies():
    a,p=pool('MAX_FILL');original=p.cal.get
    p.cal.get=lambda *args:dict(original(*args),R1=-1.)
    p.allocate([request()],WHEN)
    assert not a.fills and p.cash_attribution[0]['NO_QUALIFYING_OPPORTUNITY']==a.cash


def test_etf_baseline_target_separate_from_registered_hard_window():
    a,p=pool(3.);i=request(strategy='SMV6');p.etf_limits[i.event_id]=100000.
    b,t,hard,raw=p.target(i,500.,1000.,100000.,500.)
    assert (b,t,hard,raw)==(500.,1500.,100000.,1500.)
    p.scale='MAX_FILL';p.max_fill=True
    assert p.target(i,500.,1000.,100000.,500.)[1]==100000.


def test_soft_family_budget_scales_and_max_fill_removes_it():
    values=[]
    for x in [1.,3.,'MAX_FILL']:
        a,p=pool(x);p.refs['family_risk']=.0005;p.refs['account']=.0005
        p.liquidity={('000001.SZ',WHEN.normalize()):1e9,('000002.SZ',WHEN.normalize()):1e9}
        p.allocate([request('a'),request('b','000002.SZ')],WHEN)
        values.append(a.exposure())
    assert np.isclose(values[1],3*values[0])
    assert values[2]>10*values[1]


def test_parent_engine_and_verdict_remain_frozen():
    from research.unified_opportunity_risk_v1.data import HERE as PARENT
    from research.portfolio_closure_v1 import repair
    manifest=json.loads((PARENT/'input_manifest.json').read_text())
    assert repair.digest(PARENT/'engine.py')==manifest['research_sources']['engine.py']
    assert json.loads((PARENT/'output/final_system_spec.json').read_text())['final_decision']=='KEEP_NATIVE'

