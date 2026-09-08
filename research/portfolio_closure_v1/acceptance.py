"""Versioned repair acceptance: unfinished gates cannot authorize portfolio search."""
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd
from .repair import OUT, HERE, CACHE, END, digest, write_json
from .assemble import csv


def run():
    ops=pd.read_csv(OUT/'precapital_opportunities_v2.csv.gz')
    stock=OUT/'shadow_stock_lifecycle_v2_rerun.csv.gz'
    parts=[pd.read_csv(stock),pd.read_csv(OUT/'shadow_gap_lifecycle_v2.csv.gz'),pd.read_csv(OUT/'shadow_smv6_lifecycle_v2.csv.gz')]
    lifecycle=pd.concat(parts,ignore_index=True)
    assert len(lifecycle)==len(ops)
    keys=['strategy','opportunity_id']
    assert not lifecycle.duplicated(keys).any()
    assert set(map(tuple,lifecycle[keys].values))==set(map(tuple,ops[keys].values))
    completed=lifecycle.status.eq('COMPLETED')
    assert lifecycle.loc[completed,['pre_exit_MFE','pre_exit_MAE','native_realized_return','native_realized_pnl']].notna().all().all()
    assert np.isfinite(lifecycle.loc[completed,['pre_exit_MFE','pre_exit_MAE','native_realized_return','native_realized_pnl']].to_numpy()).all()
    csv(lifecycle,'shadow_native_lifecycle_v2.csv.gz')
    identities=[]
    for label,name in [('STOCK','shadow_stock_identity_v2_rerun.csv'),('GAP','shadow_gap_identity_v2.csv'),('SMV6','shadow_smv6_identity_v2.csv')]:
        f=pd.read_csv(OUT/name);f['replay_family']=label
        identities.append(f)
    identity=pd.concat(identities,ignore_index=True)
    assert identity.status.eq('PASS').all()
    funded=ops.loc[ops.actual_funding_status.eq('FUNDED')]
    assert len(identity)==len(funded)
    # Add endpoint, exit-reason, and corporate-action sequence comparisons to
    # the native quantity/price/fee/P&L comparisons performed by each replay.
    detail=[]
    for gap in ['IFCGR','OGR']:
        p=CACHE/'accounts'/f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__{END}'
        f=pd.read_parquet(p/'fills.parquet');account=json.loads((p/'account.json').read_text())
        use=lifecycle.loc[lifecycle.strategy.eq('OGR')] if gap=='OGR' else lifecycle.loc[~lifecycle.strategy.eq('OGR')]
        for row in use.itertuples(index=False):
            own=f.loc[f.event_id.eq(row.opportunity_id)|f.root_event_id.eq(row.opportunity_id)]
            buy=own.loc[own.side.eq('BUY')];sell=own.loc[own.side.eq('SELL')]
            if buy.empty:continue
            entry_match=pd.Timestamp(row.entry_at)==pd.Timestamp(buy.entry.min())
            exit_match=(pd.isna(row.exit_at) and row.status=='RIGHT_CENSORED') or (pd.notna(row.exit_at) and pd.Timestamp(row.exit_at)==pd.Timestamp(sell.exit.max()))
            fee_match=bool(np.isclose(row.fees,own.fee.sum(),rtol=1e-10,atol=1e-6))
            if row.strategy in ['OGR','IFCGR']:
                raw=pd.read_csv(OUT/'gap_raw_exit_identity_v2.csv')
                reason_match=bool(raw.loc[raw.gap_id.eq(row.opportunity_id),'identity'].all()) and sell.reason.eq('NATIVE_EXIT').all()
            else:
                expected='|'.join(sell.reason.astype(str).drop_duplicates())
                reason_match=(str(row.exit_reason)==expected) if len(sell) and pd.notna(row.exit_at) else True
            if row.strategy=='SMV6':
                ca_match=row.corporate_actions=='PRE_ADJUSTED_ETF_NATIVE_COORDINATE'
            else:
                actual_actions=json.loads(row.corporate_actions)
                expected_actions=[a for a in account['held_actions'] if a['strategy']==row.strategy and a['symbol']==row.symbol
                    and pd.Timestamp(a['record_date'])>=pd.Timestamp(row.entry_at).normalize()
                    and pd.Timestamp(a['record_date'])<=pd.Timestamp(row.exit_at if pd.notna(row.exit_at) else END).normalize()]
                fields=['action_id','ex_date','tradable_date','cash_payment_date','share_ratio','cash_ratio']
                canonical=lambda a:sorted(tuple(str(r.get(k)) for k in fields) for r in a)
                ca_match=canonical(actual_actions)==canonical(expected_actions)
            detail.append(dict(opportunity_id=row.opportunity_id,strategy=row.strategy,entry_match=entry_match,exit_match=exit_match,
                exit_reason_match=bool(reason_match),fee_match=fee_match,corporate_action_sequence_match=ca_match,
                normalized_return=row.native_realized_return,normalized_pnl_1m=row.pnl_normalized_1m,
                status='PASS' if all([entry_match,exit_match,reason_match,fee_match,ca_match]) else 'FAIL'))
    detail=pd.DataFrame(detail)
    csv(detail,'shadow_native_identity_v2.csv')
    # Keep the prior detailed numerical comparisons available; do not upgrade
    # an endpoint pass when a underlying fill comparison failed.
    csv(identity,'shadow_fill_identity_components_v2.csv')
    status='PASS' if detail.status.eq('PASS').all() and len(detail)==len(funded) else 'FAIL_IDENTITY_DETAILS'
    deterministic=[]
    for stem in ['shadow_stock_lifecycle_v2','shadow_stock_identity_v2']:
        suffix='.csv.gz' if 'lifecycle' in stem else '.csv'
        a=OUT/(stem+suffix);b=OUT/(stem+'_rerun'+suffix)
        if a.exists() and b.exists():
            read=lambda p:gzip.decompress(p.read_bytes()) if p.name.endswith('.gz') else p.read_bytes()
            x,y=read(a),read(b)
            deterministic.append(dict(artifact=stem,first_hash=hashlib.sha256(x).hexdigest(),second_hash=hashlib.sha256(y).hexdigest(),match=x==y))
    csv(pd.DataFrame(deterministic),'shadow_determinism_v2.csv')
    acceptance=dict(TASK_STATUS='IN_PROGRESS_REPAIR_AND_AUTOMATIC_RESUME',OPPORTUNITY_SEMANTICS='PASS',
        SHADOW_NATIVE_REPLAY=status,CAPITAL_STATE_CAUSALITY='IN_PROGRESS_SIMULTANEOUS_FUNDING_SCHEDULER',
        P0_NATIVE_RECONCILIATION='PASS',SMV6_POST2023_COVERAGE='PASS',IFCGR_POST2023_COVERAGE='PASS',
        input_acceptance='NOT_YET_PASS',portfolio_contract_frozen=False,portfolio_search_run=False,
        legal_precapital_opportunities=len(ops),reduction_rows_removed=24,shadow_completed_lifecycles=int(completed.sum()),
        shadow_right_censored=int((~completed).sum()),funded_identity_rows=len(detail),funded_identity_pass=int(detail.status.eq('PASS').sum()),
        input_hashes_verified=442,input_hashes_pass=bool(pd.read_csv(OUT/'registered_input_hash_verification_v2.csv').match.all()),
        semantics_contract_sha256=digest(HERE/'contracts/opportunity_semantics_v2.json'),
        remaining_work='Integrate exact-timestamp simultaneous pro-rata with live native request/feedback and actual execution caps; validate before acceptance. Then freeze original contract and execute all A-R portfolio research. P0 funding rounds are observations, not the validated new allocator.',
        final_portfolio_decision='NOT_EVALUATED',real_source_or_identity_blocker=None)
    write_json(OUT/'input_acceptance_v2.json',acceptance)
    print(json.dumps(acceptance,indent=2),flush=True)


if __name__=='__main__':run()
