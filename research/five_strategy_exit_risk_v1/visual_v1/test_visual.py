import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parent))
import packets as v
from quantify import representations, MOTIFS


def test_public_payload_excludes_identity_outcome_and_future():
    packets=json.loads((v.OUT/'blind_payload.json').read_text())
    for p in packets:
        assert set(p)=={'case_id','observation_age','path','route','pair_id'}
        assert re.fullmatch('CASE_[0-9]{5}',p['case_id'])
        for row in p['path']:
            assert set(row)==set(v.SAFE)
            assert row['age']<=p['observation_age']
            assert all(not isinstance(x,str) for x in row.values())


def test_real_dates_are_prefix_bounded_and_discovery_mature():
    a=pd.read_parquet(v.OUT/'private/prefix_audit.parquet')
    assert a.latest_chart_available_at.le(a.decision_at).all()
    assert a.decision_at.lt(a.native_time).all()
    d=pd.read_parquet(v.OUT/'private/selected_states.parquet')
    for route,g in d.groupby('route'):
        start,stop,_,_=v.PC['splits'][route]
        assert g.entry_date.ge(start).all()
        assert g.label_available_at.lt(pd.Timestamp(stop)+pd.Timedelta(days=1)).all()
    for fragment in v.C['matching']['exclusions']:
        assert not d.episode_id.str.contains(fragment,regex=False).any()
    assert d.event_cluster.is_unique and d.episode_id.is_unique


def test_actual_pair_calipers_and_identical_blind_canvas():
    m=pd.read_csv(v.HERE/'visual_matching_audit.csv');m=m.loc[m.pair_id.ne('QUOTA')]
    assert len(m)==12
    for col,limit in [('age_difference',1),('return_difference',.015),('mae_difference',.02),('atr_difference',.01)]:
        assert m[col].le(limit).all()
    assert {Image.open(p).size for p in (v.OUT/'blind').glob('*.png')}=={(2520,1650)}


def test_future_poison_cannot_change_blind_payload():
    case=json.loads((v.OUT/'blind_payload.json').read_text())[0]
    p=pd.DataFrame(case['path']);a=v.payload(p,case['case_id'],case['observation_age'])
    bad=p.iloc[[-1]].copy();bad.loc[:,v.SAFE]=999;bad['native_return']=-999;bad['exit_reason']='FUTURE_SECRET'
    p['native_return']=777;p['symbol']='SECRET'
    b=v.payload(pd.concat([p,bad],ignore_index=True),case['case_id'],case['observation_age'])
    assert a==b


def test_feature_prefix_invariance_and_gap_invalid_propagation():
    d=pd.DataFrame(dict(episode_id=['x']*9,age=np.arange(9),decision_at=pd.date_range('2019-01-01',periods=9)+pd.Timedelta(hours=16),
        data_available_at=pd.date_range('2019-01-01',periods=9)+pd.Timedelta(hours=15),state_valid=True,close_location=np.linspace(.1,.9,9),down_volume_ratio=np.arange(9)/2))
    cols=['close_location_mean3','down_volume_mean3']
    expected=representations(d.iloc[:6])[cols].reset_index(drop=True)
    poison=d.copy();poison.loc[6:,['close_location','down_volume_ratio']]=1e20
    actual=representations(poison).iloc[:6][cols].reset_index(drop=True)
    assert_frame_equal(expected,actual)
    gap=d.drop(index=3);result=representations(gap).set_index('age')
    assert result.loc[[4,5],cols].isna().all().all()
    invalid=d.copy();invalid.loc[3,'state_valid']=False;result=representations(invalid)
    assert result.loc[3:5,cols].isna().all().all()


def test_all_motifs_have_actual_counterexamples_and_small_representations():
    m=pd.read_csv(v.HERE/'visual_motif_hypotheses.csv');cases=set(pd.read_csv(v.HERE/'visual_case_manifest.csv').case_id)
    for row in m.itertuples(index=False):
        assert row.COUNTEREXAMPLE_CASE_IDS and set(row.COUNTEREXAMPLE_CASE_IDS.split('|'))<=cases
        assert set(row.SUPPORTING_CASE_IDS.split('|'))<=cases
    for _,(_,features) in MOTIFS.items():assert 1<=len(features)<=3 and len(v.BASE)+len(features)<=12
    assert len(set(f for _,fs in MOTIFS.values() for f in fs)-set(v.EXTRA))<=6


def test_blind_observations_preceded_reveal_and_records_unchanged():
    log=[json.loads(x) for x in (v.HERE/'visual_stage_audit.jsonl').read_text().splitlines()]
    seal=next(x for x in log if x['action']=='BLIND_OBSERVATIONS_SEALED_BEFORE_REVEAL')
    reveal=next(x for x in log if x['action']=='DISCOVERY_CASE_OUTCOMES_REVEALED')
    assert seal['time']<=reveal['time']
    assert seal['sha256']==v.digest(v.HERE/'visual_blind_observations.csv')
    exposure=pd.read_csv(v.HERE/'visual_exposure_manifest.csv')
    blind=exposure.loc[exposure.chart_type.str.startswith('DECISION_TIME_BLIND')]
    assert not blind.future_path_visible.any() and not blind.outcome_labels_visible.any()
    assert pd.to_datetime(blind.viewed_at,utc=True).max()<pd.Timestamp(reveal['time'])


def test_parent_research_files_still_hash_identical():
    locked=json.loads((v.PARENT/'completion_manifest.json').read_text())
    for name,info in locked['research_files'].items():
        assert v.digest(v.PARENT/name)==info['sha256'],name
