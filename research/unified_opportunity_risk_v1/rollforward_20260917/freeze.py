"""Freeze inputs only after all data and signal gates pass."""
from pathlib import Path
import json
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.exposure_scale import run as previous
from .prepare_stock import HERE,CACHE,END

def main():
    for name in ['stock_data_audit.json','atrdr_signal_prefix.json','mcb_signal_prefix.json','gap_signal_audit.json']:
        assert json.loads((HERE/name).read_text())['status']=='PASS',name
    d=pd.read_parquet(CACHE/'pit_delta.parquet',columns=['invalid_reasons'])
    assert not d.invalid_reasons.str.contains('UNRESOLVED_REFERENCE_PRICE',na=False).any()
    contract=dict(candidate='R1_RP100_S10_F1',X=previous.SCALES,Y=[.1,.15,.2,.3],start='2018-01-01',end=END,
        requested_today='2026-09-17',cutoff_reason='2026-09-17 session incomplete at acquisition; latest completed session 2026-09-16',
        baseline='Frozen Candidate B target formula evaluated using each diagnostic account current NAV',
        opportunity_population='Frozen original signal producers; native holdings-state feedback may change legal requests',
        finite_X='Scale new/increasing targets and RP100 total/family soft risk budgets by X',
        max_fill='R1 order; maximum cash/gross/security/liquidity permitted; no RP or family soft budget',
        immutable=['R1','discovery calibration','quality threshold','Native exits','signal timing','execution rules','no renormalization of existing holdings'],
        hard_defenses=['gross <= 100%','cash >= 0','no leverage','same-security aggregation','registered execution/liquidity limits'],
        security_cap='Y applies to new/increasing requests; passive price drift follows unchanged Native contract',
        latest_front_adjustment='User authorized full 2018 replay on latest front-adjusted ETF prices; no historical price-basis splice',
        historical_comparison='Separate refreshed-through-20260904 changes from returns during new sessions',
        verdict='KEEP_NATIVE',diagnostic_only=True,optimize_X=False)
    files=[CACHE/'daily_with_snapshot.parquet',CACHE/'action_registry.parquet',CACHE/'smv6/availability.parquet']
    for s in ['atrdr','mcb']:files.append(CACHE/s/'precapital_entry_population.parquet')
    for s in ['ogr','ifcgr']:files.append(CACHE/s/'signals_all.parquet')
    files.append(CACHE/'ogr/outcomes_all.parquet')
    files+=sorted((CACHE/'smv6/daily').rglob('*.parquet'))+sorted((CACHE/'smv6/minute_critical').rglob('*.parquet'))+sorted((CACHE/'benchmarks').glob('*.parquet'))
    files+=sorted(p for p in HERE.glob('*.py') if p.name not in ['analyze.py','plot.py','report.py'])+sorted((HERE/'official_facts').rglob('*.*'))
    files+=sorted((CACHE/'gap_minutes').glob('*.parquet'))+sorted((CACHE/'issuer_capture').rglob('*.*'))
    files+=[CACHE/'qmt_market/manifest.json',HERE/'qmt_daily_cross_provider_audit.json']
    files+=[previous.PARENT_OUT/'calibration_frozen.json',previous.PARENT_OUT/'risk_references_frozen.json']
    assert all(p.exists() for p in files)
    repair.write_json(HERE/'contract.json',contract)
    repair.write_json(HERE/'input_manifest.json',dict(status='PASS',end=END,registered_inputs={str(p):repair.digest(p) for p in files},
        data_proofs={p.name:repair.digest(p) for p in HERE.glob('*audit.json')},etf_proof=repair.digest(HERE/'etf_refresh_manifest.json'),
        prior_input_manifest=repair.digest(previous.HERE/'input_manifest.json') if (previous.HERE/'input_manifest.json').exists() else None))
    print('FROZEN',len(files),flush=True)
if __name__=='__main__':main()
