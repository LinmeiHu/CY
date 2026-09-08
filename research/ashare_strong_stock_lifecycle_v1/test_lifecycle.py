import json
from pathlib import Path
def test_semantic_contract_has_strict_order():
    x=json.loads((Path(__file__).parent/'SEMANTIC_PREFLIGHT.json').read_text())
    assert 't+6' in x['economic_sequence']
    assert 'repair-negative rows retained' in x['future_leakage_checks']
