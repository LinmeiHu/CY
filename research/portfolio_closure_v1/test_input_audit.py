import json
from pathlib import Path
import pandas as pd

OUT = Path(__file__).parent / 'output'


def test_buy_identity_uses_actual_right_hand_match():
    d = pd.read_csv(OUT / 'native_buy_request_identity.csv')
    assert len(d) == 106 and d.match.all()
    assert d.event_id.is_unique


def test_reduction_fills_are_not_unfilled_buy_requests():
    d = pd.read_csv(OUT / 'opportunity_semantic_errors.csv')
    reductions = d.loc[d.is_reduction_fill]
    assert len(reductions) == 24
    assert reductions.event_type.eq('REBALANCE_FILLED').all()
    assert reductions.filled_delta_qty.lt(0).all()
    assert reductions.funded.all() and not reductions.filled.any()


def test_data_error_prevents_portfolio_recommendation():
    s = json.loads((OUT / 'audit_status.json').read_text())
    assert s['task_status'] == 'BLOCKED_INHERITED_RESEARCH_DATA_ERROR'
    assert not s['portfolio_search_run']
    assert s['final_portfolio_decision'] == 'NOT_EVALUATED'
    assert not s['source_unavailable']


def test_native_receipts_remain_valid():
    assert pd.read_csv(OUT / 'native_receipt_hash_verification.csv').match.all()
