import pandas as pd

from five_strategy_bundle.compare import compare_parquet


def test_comparison_handles_quoted_column_identifiers(tmp_path):
    actual, golden = tmp_path/'actual.parquet', tmp_path/'golden.parquet'
    pd.DataFrame({'event id': ['E'], 'value"quoted': [1.]}).to_parquet(actual, index=False)
    pd.DataFrame({'event id': ['E'], 'value"quoted': [2.]}).to_parquet(golden, index=False)
    result = compare_parquet(actual, golden, ['event id'], ['value"quoted'], atol=.1)
    assert result['status'] == 'FAIL'
    assert result['first_difference'] == 'E'
