"""Read-only admission of inherited research artifacts before portfolio search."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT / 'research/capital_admission_v1'
ACCOUNTS = Path('/Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1/research/scaling_regime_v1/cache/accounts')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def audit():
    inputs = set()

    def read(path):
        inputs.add(path)
        return pd.read_parquet(path) if path.suffix == '.parquet' else pd.read_csv(path)

    out = HERE / 'output'
    out.mkdir(parents=True, exist_ok=True)
    account = ACCOUNTS / 'IFCGR__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04'
    fills = read(account / 'fills.parquet')
    buys = fills.loc[fills.strategy.eq('SMV6') & fills.side.eq('BUY') & pd.to_datetime(fills.entry).between('2024-01-01', '2026-09-04 23:59:59')]
    requests = read(PRIOR / 'output/smv6_post2023_replay_intents.parquet')
    joined = buys.merge(requests, on='event_id', how='left', suffixes=('_fill', '_request'), indicator=True, validate='one_to_one')
    joined['match'] = joined['_merge'].eq('both') & joined.symbol_fill.eq(joined.symbol_request)
    joined['match'] &= pd.to_datetime(joined.entry).eq(pd.to_datetime(joined.earliest_execution_at_request))
    joined['match'] &= np.isclose(joined.native_requested_quantity_fill, joined.native_requested_quantity_request, rtol=1e-10, atol=1e-6)
    joined['match'] &= np.isclose(joined.requested_notional, joined.native_requested_notional, rtol=1e-10, atol=1e-6)
    joined[['event_id', 'symbol_fill', 'symbol_request', 'entry', 'earliest_execution_at_request', 'native_requested_quantity_fill', 'native_requested_quantity_request', 'match']].to_csv(out / 'native_buy_request_identity.csv', index=False)

    events = read(PRIOR / 'output/smv6_post2023_replay_events.parquet')
    selected = events.loc[pd.to_datetime(events.trade_date).between('2024-01-01', '2026-09-04') & events.event_type.isin(['BUY_SIGNAL', 'BUY_FILLED', 'BUY_OR_REBALANCE_NO_FILL', 'REBALANCE_FILLED'])].reset_index(names='event_row_id')
    selected['opportunity_id'] = selected.apply(lambda r: f'SMV6|{pd.Timestamp(r.trade_date).date()}|{r.symbol}|{r.event_row_id}', axis=1)
    claimed = read(PRIOR / 'output/smv6_post2023_precapital_opportunities.csv.gz')
    evidence = claimed.merge(selected[['opportunity_id', 'event_type', 'filled_delta_qty']], on='opportunity_id', validate='one_to_one', how='left')
    evidence['is_reduction_fill'] = evidence.filled_delta_qty.lt(0)
    evidence[['opportunity_id', 'event_type', 'filled_delta_qty', 'funded', 'filled', 'is_reduction_fill']].to_csv(out / 'opportunity_semantic_errors.csv', index=False)
    yearly = []
    for year in (2024, 2025, 2026):
        se = selected.loc[pd.to_datetime(selected.trade_date).dt.year.eq(year)]
        rq = requests.loc[pd.to_datetime(requests.decision_at).dt.year.eq(year)]
        yearly.append(dict(year=year, reported_opportunities=len(se), replay_buy_requests=len(rq), reduction_fills=int(se.filled_delta_qty.lt(0).sum()), signal_rows=int(se.event_type.eq('BUY_SIGNAL').sum())))
    pd.DataFrame(yearly).to_csv(out / 'population_count_reconciliation.csv', index=False)
    shadow = read(PRIOR / 'output/shadow_native_opportunity_lifecycle.csv.gz')
    conflicts = read(PRIOR / 'output/capital_conflict_timeline.csv')
    daily = read(account / 'daily.parquet')
    daily['trade_date'] = pd.to_datetime(daily.trade_date).dt.normalize()
    conflicts['trade_date'] = pd.to_datetime(conflicts.trade_date)
    c = conflicts.merge(daily[['trade_date', 'cash', 'gross_exposure']], on='trade_date', validate='many_to_one')
    # An EOD number is a valid EOD observation, not a pre-funding observation.
    cash_is_eod = np.allclose(c.cash_available_before_funding, c.cash, equal_nan=True)
    headroom_is_exposure = np.allclose(c.gross_headroom_before_funding, c.gross_exposure, equal_nan=True)
    receipts = []
    for gap in ('OGR', 'IFCGR'):
        folder = ACCOUNTS / f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__2026-09-04'
        receipt = folder / 'receipt.json'
        inputs.add(receipt)
        for name, expected in json.loads(receipt.read_text())['hashes'].items():
            path = folder / name
            inputs.add(path)
            actual = digest(path)
            receipts.append(dict(path=str(path), expected=expected, actual=actual, match=actual == expected))
    pd.DataFrame(receipts).to_csv(out / 'native_receipt_hash_verification.csv', index=False)
    for path in (PRIOR / 'recover_smv6.py', PRIOR / 'continue_closure.py', PRIOR / 'REPORT_V2.md', ROOT / 'research/scaling_regime_v1/contracts/continuous_rollforward_protocol_v1.json'):
        inputs.add(path)
    inputs.update((ROOT / 'src/five_strategy_bundle/strategies').glob('*.py'))
    summary = dict(task_status='BLOCKED_INHERITED_RESEARCH_DATA_ERROR', portfolio_search_run=False,
        final_portfolio_decision='NOT_EVALUATED', contract_status='NOT_FROZEN_INPUT_ADMISSION_FAILED',
        native_buys=len(buys), matched_native_buys=int(joined.match.sum()),
        reported_opportunities=len(claimed), mapped_event_rows=int(evidence.event_type.notna().sum()),
        reduction_fills_misclassified_as_opportunities=int(evidence.is_reduction_fill.sum()),
        shadow_rows=len(shadow), missing_shadow_return=int(shadow.shadow_native_return.isna().sum()),
        missing_mfe=int(shadow.pre_exit_MFE.isna().sum()), missing_mae=int(shadow.pre_exit_MAE.isna().sum()),
        precapital_cash_equals_same_day_eod_cash=bool(cash_is_eod),
        gross_headroom_equals_gross_exposure=bool(headroom_is_exposure),
        native_receipt_files=len(receipts), native_receipt_hashes_pass=all(x['match'] for x in receipts),
        previous_keep_native_conclusion='UNSUPPORTED_BY_IMPLEMENTED_EXPERIMENT',
        source_unavailable=False)
    (out / 'audit_status.json').write_text(json.dumps(summary, indent=2) + '\n')
    (HERE / 'input_manifest.json').write_text(json.dumps({str(p): digest(p) for p in sorted(inputs)}, indent=2) + '\n')
    (out / 'output_manifest.sha256').write_text(''.join(f'{digest(p)}  {p.name}\n' for p in sorted(out.iterdir()) if p.is_file() and p.name != 'output_manifest.sha256'))
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    audit()
