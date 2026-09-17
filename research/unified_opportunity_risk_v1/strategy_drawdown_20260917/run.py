"""Five independent Native physical accounts on the frozen refreshed dataset."""
from pathlib import Path
import json
import pandas as pd
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.rollforward_20260917 import run as source
from research.shared_capital_v1.common_p0_v06 import replay as native_replay
from research.shared_capital_v1 import gap_p0
from research.shared_capital_v1.causal_adapters import corrected_function
# The already-used pending-exit date guard, without Unified Pool sizing changes.
gap_replay=corrected_function(gap_p0.replay,[("if pd.Timestamp(row['exit_time']).normalize() == day","if pd.notna(row['exit_time']) and pd.Timestamp(row['exit_time']).normalize() == day")])
replay=corrected_function(native_replay,[],gap_replay=gap_replay)
from research.capital_scaling_v1.run import save_account
HERE=Path(__file__).resolve().parent
OUT=HERE/'output'
STRATEGIES=['ATRDR','MCB','OGR','IFCGR','SMV6']
END=source.END

def main():
    manifest=json.loads((source.HERE/'input_manifest.json').read_text())
    for p,h in manifest['registered_inputs'].items():assert repair.digest(Path(p))==h,p
    data,_,_=source.load()
    for strategy in STRATEGIES:
        dest=OUT/'accounts'/strategy;dest.mkdir(parents=True,exist_ok=True)
        identity={str(p):repair.digest(p) for p in [Path(__file__),source.HERE/'input_manifest.json',Path(__import__(native_replay.__module__,fromlist=['x']).__file__),Path(gap_p0.__file__)]}
        if (dest/'receipt.json').exists():
            receipt=json.loads((dest/'receipt.json').read_text());assert receipt['identity']==identity
            for name,h in receipt['hashes'].items():assert repair.digest(dest/name)==h
            continue
        print('START',strategy,flush=True)
        a,d,_,_,_=replay(data,'IFCGR' if strategy=='IFCGR' else 'OGR','CONTINUOUS_NATIVE_STANDALONE','2018-01-01',END,selected=(strategy,))
        assert str(d.trade_date.max().date())==END and len(d)==2114
        checks=pd.DataFrame(a.checkpoints)
        assert checks.cash.ge(-1e-8).all() and checks.gross_exposure.le(checks.nav+1e-8).all() and checks.pnl_delta.abs().max()<1e-6
        save_account(dest,a,d,None)
        repair.write_json(dest/'receipt.json',dict(status='PASS',strategy=strategy,mode='INDEPENDENT_NATIVE_NO_XY_SCALING',identity=identity,hashes={p.name:repair.digest(p) for p in dest.iterdir() if p.is_file()}))
        print('PASS',strategy,flush=True)
if __name__=='__main__':main()
