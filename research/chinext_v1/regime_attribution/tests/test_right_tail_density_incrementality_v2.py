from __future__ import annotations
import json,sys
from pathlib import Path
SCRIPTS=Path(__file__).resolve().parents[1]/'scripts';sys.path.insert(0,str(SCRIPTS))
import run_right_tail_density_incrementality_v2 as rtd
def test_science_matches_invalid_predecessor_exactly():
 old=json.loads((rtd.WORK/'experiments/EXP-RTD-001_spec.json').read_text());new=json.loads(rtd.SPEC.read_text())
 for key in ('hypothesis_id','question','mechanism','prediction','sample','primary_feature','primary_outcome','controls','neighbors','gates','forbidden'):assert new[key]==old[key]
def test_index_volatility_has_one_intended_source():
 assert rtd.RISK.count('index_realized_vol20')==1
 assert rtd.OUT_JSON.name=='right_tail_density_incrementality_v2.json'
def test_frozen_result_rejects_incrementality():
 result=json.loads(rtd.OUT_JSON.read_text());p=result['primary']
 assert result['decision']=='REJECT'
 assert p['raw_gate'] is True and p['controlled_gate'] is False
 assert p['controlled_breadth_trend']['partial_rank_rho']<.10
 assert p['controlled_plus_risk']['partial_rank_rho']<.08
 assert p['falsification_gate'] is False
