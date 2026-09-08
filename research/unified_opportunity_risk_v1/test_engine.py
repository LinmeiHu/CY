"""Behavioral gates for causal pooled funding, using tiny actual physical books."""
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace
import numpy as np
import pandas as pd
import pytest
from research.shared_capital_v1.shared_account.engine import PhysicalAccount,Intent
from research.shared_capital_v1.shared_account.scheduler import Event,run_streams
from research.unified_opportunity_risk_v1.engine import Pool,PoolFunding,constrain_pro_rata
from research.unified_opportunity_risk_v1.data import OUT,CONTRACT,HERE,Calibration

WHEN=pd.Timestamp('2020-01-02 09:30')

def request(eid='x',symbol='000001.SZ',strategy='ATRDR'):
    return Intent(strategy,'BULL','DEMAND',eid,'',symbol,pd.Timestamp('2020-01-01 15:00'),WHEN,(0,),1000.,10.,.002)

def book(rank='R0',family=False):
    p=Pool(dict(ranking=rank,risk_profile=1.,security_cap=.2,family_cap=family),{}, {})
    p.refs=dict(opportunity=.02,security=.04,family_risk=.1,account=.15)
    p.cal=SimpleNamespace(pairs={},get=lambda eid,s,r,priority=():dict(R1=1.,R2=10.,conservative_tail_loss=.1,family='DEMAND',bucket=0,economic_id=eid,risk_estimate_insufficient=False))
    a=PhysicalAccount('OGR',initial_cash=1e6);p.bind(a)
    return a,p

def test_no_strategy_cap_and_cash_gross():
    a,p=book();batch=[request(str(n),f'{n:06d}.SZ') for n in range(10)]
    p.liquidity={(i.symbol,WHEN.normalize()):1e8 for i in batch}
    p.allocate(batch,WHEN)
    assert a.exposure('ATRDR')/ (a.cash+a.exposure())>.99
    assert a.cash>=-1e-8 and a.exposure()<=a.cash+a.exposure()+1e-8
    assert len(a.lots)==10

def test_same_security_risk_and_hard_cap_aggregated():
    a,p=book();batch=[request('a'),request('b',strategy='MCB')]
    p.liquidity={('000001.SZ',WHEN.normalize()):1e8};p.allocate(batch,WHEN)
    assert a.exposure()/(a.cash+a.exposure())<=.2+1e-8
    assert np.isclose(a.lots['a']['quantity'],a.lots['b']['quantity'])

def test_economic_duplicate_only_one_funded():
    a,p=book();p.cal.pairs={'b':'a'};p.liquidity={('000001.SZ',WHEN.normalize()):1e8}
    p.allocate([request('a'),request('b',strategy='MCB')],WHEN)
    assert len(a.lots)==1 and p.admissions[1]['reason']=='ECONOMIC_DUPLICATE'

def test_family_constraint_and_whole_book_risk():
    a,p=book(family=True);p.refs['family_risk']=.03
    batch=[request(str(n),f'{n:06d}.SZ') for n in range(8)];p.liquidity={(i.symbol,WHEN.normalize()):1e8 for i in batch}
    p.allocate(batch,WHEN)
    assert p.holdings(a.cash+a.exposure())[0]<=.03+1e-8

def test_quality_leaves_cash_idle():
    a,p=book();original=p.cal.get
    p.cal.get=lambda *args:dict(original(*args),R1=-1.)
    p.allocate([request()],WHEN);assert a.cash==1e6 and not a.fills

def test_rank_priority_and_equal_rank_deterministic():
    a,p=book('R1');original=p.cal.get
    p.cal.get=lambda eid,*args:dict(original(eid,*args),R1=2. if eid=='best' else 1.)
    p.refs['account']=.02;p.liquidity={('000001.SZ',WHEN.normalize()):1e8,('000002.SZ',WHEN.normalize()):1e8}
    p.allocate([request('second','000002.SZ'),request('best')],WHEN)
    assert a.lots['best']['quantity']>a.lots.get('second',{}).get('quantity',0)
    assert np.allclose(constrain_pro_rata([100,200],[([1,1],150)]),[50,100])

def test_existing_position_not_resized_by_new_signal():
    a,p=book();p.liquidity={('000001.SZ',WHEN.normalize()):1e8,('000002.SZ',WHEN.normalize()):1e8}
    p.allocate([request('a')],WHEN);qty=a.lots['a']['quantity']
    p.allocate([request('b','000002.SZ')],WHEN+pd.Timedelta(minutes=1))
    assert a.lots['a']['quantity']==qty and all(f['side']=='BUY' for f in a.fills)

def test_later_sale_cannot_fund_earlier_request():
    a,p=book();a._fill(request('held'),1e4*1.002,'NATIVE',WHEN-pd.Timedelta(days=1))
    before=a.cash;p.allocate([request('a','000002.SZ')],WHEN)
    recorded=p.admissions[-1]['cash_before_event'];a.close('held',11.,WHEN+pd.Timedelta(minutes=1),.002)
    assert recorded==before and p.admissions[-1]['decision_at']==WHEN

def test_simultaneous_callbacks_single_joint_batch():
    a,p=book();fund=PoolFunding(a);p.liquidity={('000001.SZ',WHEN.normalize()):1e8,('000002.SZ',WHEN.normalize()):1e8}
    def cb(i):return lambda:a.fund([i],{s:1. for s in a.strategies},'P0',WHEN)
    events=[Event(WHEN,'ENTRY','ATRDR','a',cb(request('a'))),Event(WHEN,'OPEN_CALLBACK','SMV6','b',cb(request('b','000002.SZ','SMV6')))]
    fund.run_callbacks(events)
    assert len(p.risk_history)==1 and p.risk_history[0]['batch_requests']==2
    assert p.admissions[0]['cash_before_event']==p.admissions[1]['cash_before_event']

def test_liquidity_fallback_is_native_ceiling():
    a,p=book();i=request();p.native_requests={(i.strategy,i.event_id):5000.}
    p.allocate([i],WHEN);assert sum(f['funded_notional'] for f in a.fills)<=5000.+1e-8

def test_no_borrowing_or_margin():
    a,p=book();p.allocate([request()],WHEN)
    assert p.risk_history[0]['borrowed_cash']==p.risk_history[0]['margin']==0

def test_frozen_strategy_engines_and_exits_unchanged():
    root=HERE.parents[1]
    for file in (root/'src/five_strategy_bundle/strategies').glob('*.py'):
        prior=subprocess.check_output(['git','show','139aca07316449ee63a6d9ae45e18bd8af7d129d:'+str(file.relative_to(root))],cwd=root)
        assert hashlib.sha256(prior).digest()==hashlib.sha256(file.read_bytes()).digest()

def test_p0_identity_and_upstream_and_real_holdings():
    rec=pd.read_csv(OUT/'p0_reconciliation.csv');assert rec.status.eq('PASS').all() and set(rec.gap)=={'OGR','IFCGR'}
    a=pd.read_csv(OUT/'actual_funded_lifecycle.csv.gz');m=pd.read_csv(OUT/'strategy_labeled_opportunity_lineage.csv.gz')
    assert a.lifecycle_source.eq('AUTHORITATIVE_ACTUAL_HOLDINGS').all()
    assert set(zip(a.strategy,a.opportunity_id))<=set(zip(m.strategy,m.opportunity_id))
    assert m.delta_desired_exposure.gt(0).all() and m.classification.eq('EXPOSURE_INCREASE').all()

def test_shadow_only_unfunded_and_provenance():
    a=pd.read_csv(OUT/'actual_funded_lifecycle.csv.gz');s=pd.read_csv(OUT/'unfunded_shadow_lifecycle.csv.gz');m=pd.read_csv(OUT/'strategy_labeled_opportunity_lineage.csv.gz')
    assert not set(a.opportunity_id)&set(s.opportunity_id)
    assert set(s.opportunity_id)<=set(m.loc[m.actual_funding_status.eq('UNFUNDED'),'opportunity_id'])
    for strategy in ['SMV6','IFCGR']:
        for year in [2024,2025,2026]:assert len(m.loc[m.strategy.eq(strategy)&pd.to_datetime(m.decision_at).dt.year.eq(year)])>0

def test_discovery_only_no_future_ranking_tail_scores():
    t=pd.read_csv(OUT/'discovery_training_identity.csv.gz');q=pd.read_csv(OUT/'discovery_quality_calibration.csv')
    assert pd.to_datetime(t.decision_at).lt('2022-01-01').all() and pd.to_datetime(t.exit_at).lt('2022-01-01').all()
    assert pd.to_datetime(q.training_latest_exit).lt('2022-01-01').all()
    frozen=json.loads((OUT/'calibration_frozen.json').read_text())
    assert all(len(edges)<=4 for edges in frozen['score_edges'].values())
    assert 'year' not in q.columns and q.groupby('route_key').bucket.max().le(4).all()
    assert q.conservative_tail_loss.ge(.05).all()

def test_candidate_freeze_when_available():
    file=OUT/'candidate_freeze_receipt.json'
    if not file.exists():pytest.skip('candidate freeze follows discovery execution')
    r=json.loads(file.read_text());assert r['frozen_before_validation']
    assert r['candidates_sha256']==hashlib.sha256((OUT/'frozen_validation_candidates.csv').read_bytes()).hexdigest()


def test_unavailable_observer_delegates_native_marking(monkeypatch):
    from research.portfolio_closure_v1.repair import ObservedPlatform
    from research.shared_capital_v1.smv6_physical import PhysicalPlatform
    platform=ObservedPlatform.__new__(ObservedPlatform)
    platform._current_row=lambda symbol:SimpleNamespace(executable_09_30=False)
    platform._mark=lambda *args:(_ for _ in ()).throw(AssertionError('observer touched unavailable quote'))
    seen=[]
    monkeypatch.setattr(PhysicalPlatform,'order_target_percent',lambda self,symbol,weight:seen.append((symbol,weight)) or 'NATIVE_NO_FILL_AFTER_NATIVE_MARKS')
    assert platform.order_target_percent('UNAVAILABLE',.5)=='NATIVE_NO_FILL_AFTER_NATIVE_MARKS'
    assert seen==[('UNAVAILABLE',.5)]


def test_p0_intraday_and_complete_account_identity():
    from research.portfolio_closure_v1 import repair
    for gap in ['OGR','IFCGR']:
        p=OUT/'native_replay'/gap;q=repair.CACHE/'accounts'/f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04'
        cols=['timestamp','cash','nav','gross_exposure','fees']
        a=pd.read_parquet(p/'timeline.parquet',columns=cols);b=pd.read_parquet(q/'timeline.parquet',columns=cols)
        pd.testing.assert_frame_equal(a,b,check_dtype=False,atol=1e-6,rtol=1e-10)
        assert json.loads((p/'account.json').read_text())==json.loads((q/'account.json').read_text())
    same=pd.read_csv(OUT/'observation_repair_parameter_identity.csv')
    assert same.before_sha256.eq(same.after_sha256).all()


def test_economic_master_has_exactly_one_lifecycle():
    m=pd.read_csv(OUT/'economic_opportunity_master_v2.csv.gz');a=pd.read_csv(OUT/'actual_funded_lifecycle.csv.gz');u=pd.read_csv(OUT/'unfunded_shadow_lifecycle.csv.gz')
    assert m.economic_opportunity_id.is_unique
    assert a.economic_opportunity_id.is_unique and u.economic_opportunity_id.is_unique
    assert not set(a.economic_opportunity_id)&set(u.economic_opportunity_id)
    assert set(a.economic_opportunity_id)|set(u.economic_opportunity_id)==set(m.economic_opportunity_id)
    assert len(a)==2920 and len(u)==790 and len(m)==3710
    labels=pd.read_csv(OUT/'actual_funded_strategy_label_lifecycle.csv.gz');requests=pd.read_csv(OUT/'strategy_labeled_opportunity_lineage.csv.gz')
    assert len(labels)==4217
    assert set(zip(labels.strategy,labels.opportunity_id))<=set(zip(requests.strategy,requests.opportunity_id))


def test_all_72_physical_configs_and_post_validation_immutability():
    from research.portfolio_closure_v1 import repair
    grid=pd.read_csv(OUT/'unified_discovery_grid.csv');assert len(grid)==72 and grid.case_id.is_unique
    for p in (OUT/'accounts').glob('*/*/receipt.json'):
        r=json.loads(p.read_text())
        if 'identity' in r and 'calibration_frozen.json' in r['identity']:
            assert r['identity']['calibration_frozen.json']==repair.digest(OUT/'calibration_frozen.json')
            assert r['identity']['risk_references_frozen.json']==repair.digest(OUT/'risk_references_frozen.json')
    v=pd.read_csv(OUT/'physical_account_validation.csv');assert v.status.eq('PASS').all() and v.min_cash.ge(-1e-8).all() and v.max_gross.le(1+1e-12).all()
    h=pd.read_csv(OUT/'registered_input_hash_verification.csv');assert len(h)==442 and h.status.eq('PASS').all()
    exact=pd.read_csv(OUT/'deterministic_rerun.csv');assert exact.economic_state.eq('PASS').all() and exact.actual_fills.eq('PASS').all()


def test_same_security_validated_liquidity_is_shared():
    a,p=book();p.liquidity={('000001.SZ',WHEN.normalize()):100000.}
    p.allocate([request('a'),request('b',strategy='MCB')],WHEN)
    assert np.isclose(a.exposure(),1000.)
    assert np.isclose(a.lots['a']['quantity'],a.lots['b']['quantity'])


def test_same_security_liquidity_consumed_across_rank_groups():
    a,p=book('R1');original=p.cal.get
    p.cal.get=lambda eid,*args:dict(original(eid,*args),R1=2. if eid=='best' else 1.)
    p.liquidity={('000001.SZ',WHEN.normalize()):100000.}
    p.allocate([request('second',strategy='MCB'),request('best')],WHEN)
    assert np.isclose(a.exposure(),1000.)
    assert 'best' in a.lots and 'second' not in a.lots


def test_certified_cache_preserves_generator_identity_and_rejects_drift(tmp_path,monkeypatch):
    from research.unified_opportunity_risk_v1 import provenance
    from research.portfolio_closure_v1 import repair
    monkeypatch.setattr(provenance,'OUT',tmp_path)
    dest=tmp_path/'accounts/case';dest.mkdir(parents=True)
    artifact=dest/'daily.parquet';artifact.write_bytes(b'physical-state')
    receipt=dest/'receipt.json';old={'engine.py':'old','calibration':'frozen'};new=dict(old,**{'engine.py':'new'})
    saved=dict(identity=old,hashes={artifact.name:repair.digest(artifact)})
    repair.write_json(receipt,saved);original=receipt.read_bytes()
    evidence=tmp_path/'proof.json';evidence.write_text('verified')
    repair.write_json(tmp_path/'engine_equivalence_certificate.json',dict(accounts={'accounts/case':dict(receipt_sha256=repair.digest(receipt),accepted_identity=new)},evidence_hashes={'proof.json':repair.digest(evidence)}))
    assert provenance.verify_cache(receipt,new)==saved and receipt.read_bytes()==original
    with pytest.raises(ValueError):provenance.verify_cache(receipt,dict(new,calibration='retuned'))
    evidence.write_text('changed')
    with pytest.raises(ValueError,match='evidence drift'):provenance.verify_cache(receipt,new)
    evidence.write_text('verified');artifact.write_bytes(b'changed-state')
    with pytest.raises(ValueError,match='artifact drift'):provenance.verify_cache(receipt,new)
