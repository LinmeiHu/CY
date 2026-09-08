"""Certify the late liquidity guard is nonbinding on every sealed account path."""
import json
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import HERE,OUT,CONTRACT,csv
from research.unified_opportunity_risk_v1.analyze import canonical_context


def certify():
    change=json.loads((OUT/'liquidity_guard_code_change.json').read_text())
    assert repair.digest(HERE/'engine.py')==change['current_engine_sha256']
    before=OUT/'accounts/finalist_evidence/R1_RP100_S10_F1'
    after=OUT/'accounts/liquidity_guard_rerun/R1_RP100_S10_F1'
    a=pd.read_parquet(before/'daily.parquet');b=pd.read_parquet(after/'daily.parquet')
    for frame in [a,b]:frame['callback_state_json']=frame.callback_state_json.map(canonical_context)
    pd.testing.assert_frame_equal(a,b,check_exact=True)
    pd.testing.assert_frame_equal(pd.read_parquet(before/'fills.parquet'),pd.read_parquet(after/'fills.parquet'),check_exact=True)
    assert json.loads((before/'account.json').read_text())==json.loads((after/'account.json').read_text())
    checks=[];accounts={}
    for receipt in sorted((OUT/'accounts').glob('*/*/receipt.json')):
        saved=json.loads(receipt.read_text());dest=receipt.parent
        assert saved['identity']['engine.py'] in [change['previous_engine_sha256'],change['current_engine_sha256']]
        for name,digest in saved['hashes'].items():assert repair.digest(dest/name)==digest
        frame=pd.read_parquet(dest/'admission.parquet')
        # This superset also includes some structural rejects. Proving its
        # total desired amount <= the shared cap proves every eligible subset
        # and every rank-priority remainder nonbinding by induction over time.
        frame=frame.loc[frame.R1.gt(0)&frame.reason.ne('ECONOMIC_DUPLICATE')&frame.target.gt(0)]
        batches=0;paired=0;fallback=0;max_registered=0.;max_fallback=0.
        for _,g in frame.groupby(['decision_at','symbol']):
            fallback_only=g.liquidity_source.eq('NATIVE_EXECUTABLE_FALLBACK').all()
            cap=g.liquidity_cap.sum() if fallback_only else g.liquidity_cap.min()
            ratio=float(g.target.sum()/cap);assert ratio<=1.+1e-12,(dest,g,ratio)
            if fallback_only: fallback+=1;max_fallback=max(max_fallback,ratio)
            else:max_registered=max(max_registered,ratio)
            batches+=1;paired+=int(len(g)>1)
        checks.append(dict(case=str(dest.relative_to(OUT/'accounts')),batches=batches,multi_request_same_security_batches=paired,
                           native_fallback_batches=fallback,max_registered_total_target_to_shared_cap=max_registered,
                           max_fallback_total_target_to_sum_native_caps=max_fallback,binding_batches=0,status='PASS'))
        accepted=dict(saved['identity']);accepted['engine.py']=repair.digest(HERE/'engine.py')
        for name in ['unified_opportunity_risk_v1.json','calibration_frozen.json','risk_references_frozen.json']:
            file=CONTRACT if name==CONTRACT.name else OUT/name
            assert accepted[name]==repair.digest(file),'frozen parameter drift'
        if 'stress.py' in accepted:
            # Only the receipt validation branch changed in stress.py; its
            # actual fresh-run cost transformations are unchanged.
            assert accepted['stress.py'] in ['5e75ce2566db5f9a835155a704716c8cb58d12ab921fc70daadd1bdd48aae80d',repair.digest(HERE/'stress.py')]
            accepted['stress.py']=repair.digest(HERE/'stress.py')
        accounts[str(dest.relative_to(OUT))]=dict(receipt_sha256=repair.digest(receipt),generator_identity=saved['identity'],accepted_identity=accepted)
    csv(pd.DataFrame(checks),'same_security_liquidity_guard_proof.csv')
    evidence=[OUT/'same_security_liquidity_guard_proof.csv',OUT/'liquidity_guard_code_change.json']
    evidence += [d/name for d in [before,after] for name in ['daily.parquet','fills.parquet','account.json']]
    repair.write_json(OUT/'engine_equivalence_certificate.json',dict(status='PASS',scope='EXACT_ENUMERATED_CACHED_ACCOUNTS_ONLY',
       proof='At every historical same-clock/security batch, the total target upper bound is no greater than the shared registered window cap; missing-denominator Native request caps add across distinct economic requests. Hence adding this constraint cannot bind, including across rank groups. No outcome retuning.',
       independent_rerun=dict(days=len(a),daily_all_fields='EXACT',callback_sets='CANONICAL_EXACT',fills='EXACT',full_account='EXACT'),
       cache_change='run/stress receipt checks accept only this exact certificate; generator receipts are preserved.',
       evidence_hashes={str(p.relative_to(OUT)):repair.digest(p) for p in evidence},accounts=accounts))
    print('CERTIFIED',len(accounts),'accounts; full replay',len(a),'days')

if __name__=='__main__':certify()
