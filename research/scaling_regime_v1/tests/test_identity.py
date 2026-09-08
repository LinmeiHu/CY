import json

import numpy as np
import pandas as pd
import pytest

from research.scaling_regime_v1 import audit


def test_ranking_ignores_post2021_outcomes_and_other_mechanics():
    frame = pd.read_csv(audit.PARENT / 'output/scenario_summary.csv')
    expected = audit.frozen_ranking(frame)
    altered = frame.copy()
    altered.loc[altered.period.ne('2018_2021'), 'CAGR'] = 1e12
    altered.loc[altered.mechanic.ne('FULL_BOOK_NORMALIZATION'), 'CAGR'] = 1e13
    pd.testing.assert_frame_equal(audit.frozen_ranking(altered), expected)
    actual = pd.read_csv(audit.HERE / 'evidence/combined_top5_backtest_curve_selection.csv')
    assert actual[['gap', 'mcb_mode', 'target']].to_dict('records') == expected[['gap', 'mcb_mode', 'target']].to_dict('records')


@pytest.mark.parametrize('status', ['FAIL', 'UNVERIFIED'])
def test_required_mismatch_or_missing_evidence_cannot_pass(status):
    rows = [dict(required=True, status='PASS', check='PREFIX'),
            dict(required=True, status=status, check='BOUNDARY')]
    with pytest.raises(ValueError, match='BOUNDARY'):
        audit.require_identity(rows)
    rows[1]['status'] = 'PASS'
    audit.require_identity(rows)


def test_real_prefix_pass_does_not_certify_boundary():
    prefix = pd.read_csv(audit.OUT / 'historical_prefix_reconciliation.csv')
    boundary = pd.read_csv(audit.OUT / 'native_boundary_mismatch.csv')
    assert len(prefix) == 5 and prefix.status.eq('PASS').all()
    assert prefix.shared_days.eq(973).all()
    smv6 = boundary.loc[boundary.field.eq('SMV6_exposure')]
    assert len(smv6) == 2 and smv6.status.eq('FAIL').all()
    assert (smv6.parent_value > 500000).all() and smv6.rollforward_value.eq(0).all()
    checks = pd.read_csv(audit.OUT / 'rollforward_identity_audit.csv')
    for _, rows in checks.groupby('rank'):
        with pytest.raises(ValueError, match='INITIAL_STATE_BOUNDARY_PROTOCOL'):
            audit.require_identity(rows.to_dict('records'))


@pytest.mark.parametrize('defect', ['missing_date', 'duplicate_date', 'nonfinite'])
def test_account_identity_fails_on_incomplete_or_invalid_evidence(defect):
    expected = pd.DataFrame(dict(trade_date=pd.date_range('2022-01-04', periods=2), nav=[100., 101.]))
    actual = expected.copy()
    if defect == 'missing_date':
        actual = actual.iloc[:1]
    elif defect == 'duplicate_date':
        actual = pd.concat([actual, actual.iloc[:1]])
    else:
        actual.loc[0, 'nav'] = np.nan
    with pytest.raises(ValueError):
        audit.compare_accounts(actual, expected, ['nav'])


def test_cash_difference_detected_even_with_equal_nav():
    expected = pd.DataFrame(dict(trade_date=pd.date_range('2022-01-04', periods=2), nav=[100., 101.], cash=[80., 81.]))
    actual = expected.copy()
    actual['cash'] = [100., 101.]
    assert audit.compare_accounts(actual, expected, ['nav'])[2]
    assert not audit.compare_accounts(actual, expected, ['nav', 'cash'])[2]


def test_mcb_runtime_guard_change_cannot_be_hidden_by_frozen_file_hash():
    evidence = json.loads((audit.OUT / 'mcb_predicate_audit.json').read_text())
    assert evidence['parent_guard_present'] and evidence['runtime_replacement_present']
    assert not evidence['panel_has_industry_snapshot_id']
    assert evidence['panel_has_causal_industry']
    # Concrete counterexample: a name exists without an identified snapshot.
    row = {'causal_industry': 'EXAMPLE', 'industry_snapshot_id': None}
    assert row['causal_industry'] is not None and row['industry_snapshot_id'] is None
    assert not evidence['signal_difference_claimed']


def test_stock_requests_are_not_misreported_as_changed():
    frame = pd.read_csv(audit.OUT / 'native_request_comparison.csv')
    assert len(frame) == 6 and frame.status.eq('PASS').all()
    assert frame.shared_events.eq(frame.parent_events).all()
    assert frame.max_abs_difference.le(1e-6).all()


def test_contract_is_frozen_and_does_not_claim_router_validation():
    contract_path = audit.HERE / 'contracts/scaling_regime_attribution_v1.json'
    receipt = json.loads((audit.HERE / 'contracts/freeze_receipt.json').read_text())
    assert audit.sha256(contract_path) == receipt['contract_sha256']
    contract = json.loads(contract_path.read_text())
    assert set(contract['router_actions']) == {'NATIVE', 'G25'}
    assert not any('year' in f or 'future' in f or 'forward' in f for f in contract['state_features'])
    assert not receipt['state_conditioned_outcomes_started']
    result = json.loads((audit.OUT / 'completion.json').read_text())
    assert not result['economic_attribution_run'] and not result['state_conditioned_analysis_run']
    assert result['router_status'] == 'NOT_EVALUATED_IDENTITY_GATE'
    assert not (audit.OUT / 'router_results.csv').exists()


def test_frozen_strategy_files_match_parent_expected_hashes():
    manifest = json.loads((audit.HERE / 'input_manifest.json').read_text())
    parent = json.loads((audit.PARENT / 'input_manifest.json').read_text())['frozen_source_hashes']
    bound = {row['path']: row['sha256'] for row in manifest['files']}
    assert len(parent) == 26
    for path, expected in parent.items():
        actual_path = str(audit.ROOT / path)
        assert bound[actual_path] == expected == audit.sha256(actual_path)
