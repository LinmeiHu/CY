"""Verify all parent-supported scaled historical prefixes after instrumented runs."""
import json
import pandas as pd
from .audit import HERE,PARENT,compare_accounts,sha256,write_json
from .accounts import folder
from .economics import cases,require_identity


def validate_case(case):
    actual=folder(*case)
    receipt=json.loads((actual/'receipt.json').read_text())
    assert receipt['status']=='PASS'
    for name,digest in receipt['hashes'].items():assert sha256(actual/name)==digest
    gap,mode,target,mechanic=case[:4]
    if target=='G25' and mechanic=='ENTRY_ONLY':
        return dict(gap=gap,mcb_mode=mode,target=target,mechanic=mechanic,status='PASS_AUTHORIZED_DIAGNOSTIC',basis='Original constructor extension, same Entry Only methods; separately tested existing-position preservation')
    table=pd.read_csv(PARENT/'output/scenario_summary.csv').fillna({'priority':''})
    row=table.loc[table.scope.eq('COMBINED')&table.gap.eq(gap)&table.mcb_mode.eq(mode)&table.period.eq('2018_2021')&table.target.eq(target)&table.mechanic.eq(mechanic)&table.grade.eq('EXECUTION_AWARE_SCALING')&table.priority.eq('')]
    assert len(row)==1
    d=pd.read_parquet(actual/'daily.parquet',columns=['trade_date','cash','nav','gross_exposure']);p=pd.read_parquet(row.source.iloc[0]+'/daily.parquet',columns=['trade_date','cash','nav','gross_exposure'])
    days,errors,passed=compare_accounts(d,p,['cash','nav','gross_exposure'])
    assert passed and days==973,(case,errors)
    return dict(gap=gap,mcb_mode=mode,target=target,mechanic=mechanic,status='PASS',days=days,**errors,basis='Actual 2018-2021 prefix vs frozen parent; read-only trace does not change economic outputs')


def main():
    require_identity();rows=[validate_case(case) for case in cases() if case[2]!='NATIVE']
    pd.DataFrame(rows).to_csv(HERE/'output/continuous_scaling_parent_prefix.csv',index=False)
    print('SCALING_HISTORICAL_IDENTITY_PASS',len(rows),flush=True)


if __name__=='__main__':main()
