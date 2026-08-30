from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_right_tail_density_incrementality as rtd
def test_fixed_single_feature_contract():
 assert rtd.FEATURE=='cross_sectional_return20_right_tail_ge20'
 assert len(rtd.BASE)==6 and len(rtd.NEIGHBORS)==2
