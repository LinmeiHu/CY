from pathlib import Path
import sys
SCRIPTS=Path(__file__).resolve().parents[1]/"scripts"
if str(SCRIPTS) not in sys.path: sys.path.insert(0,str(SCRIPTS))
import run_minvol_support_outcome_reveal as module
def test_fresh_reveal_identity():
    assert module.SPEC.name=="EXP-OBL-016_spec.json"
    assert module.PREDICTOR=="support_held"
    assert "minimum_volume_ratio" in module.CONTROLS_FIXED
