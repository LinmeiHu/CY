"""Read-only scaling traces plus the explicitly requested G25 Entry Only gate."""
from collections import defaultdict
from datetime import datetime,timezone
import json
import inspect
import pandas as pd
from research.capital_scaling_v1.scaling import Scaling
from research.shared_capital_v1.common_p0_v06 import replay
from research.shared_capital_v1.causal_adapters import corrected_function
from .audit import HERE,sha256,write_json
from . import accounts


class ObservedScaling(Scaling):
    def __init__(self,selected,target,**kwargs):
        diagnostic=kwargs.get('mechanic')=='ENTRY_ONLY' and target==.25
        super().__init__(selected,1. if diagnostic else target,**kwargs)
        if diagnostic:self.target=.25
        self.target_observations=[]

    def observe_targets(self,when,reason,targets):
        for root,quantity in targets.items():
            intent=self.desired[root];mark=self.account.marks[intent.symbol]
            self.target_observations.append(dict(timestamp=when,reason=reason,event_id=root,strategy=intent.strategy,symbol=intent.symbol,
                native_target_quantity=intent.native_requested_quantity,native_target_notional=intent.native_requested_quantity*mark,
                scaled_quantity_before=self.root_quantity(root),scaled_quantity_target=quantity,
                scaled_target_before=self.root_quantity(root)*mark,scaled_target_after=quantity*mark,mark=mark))


ObservedScaling.normalize=corrected_function(Scaling.normalize,[
    ('self.pending = targets','self.observe_targets(when,reason,targets)\n    self.pending = targets')])


def observer(account,platform,scaling,row):
    accounts.daily_observation(account,platform,scaling,row)
    row['marks_json']=json.dumps(account.marks,sort_keys=True)
    # Persist actual per-lot realized P&L and cash credits. Credits are root-level
    # in the parent; no fabricated subdivision among same-root virtual lots.
    realized=defaultdict(float)
    for fill in account.fills:
        if fill['side']=='SELL':realized[fill['event_id']]+=fill['pnl']
    row['lot_realized_json']=json.dumps(dict(realized),sort_keys=True)
    row['cash_distributions_json']=json.dumps(account.cash_distributions,sort_keys=True,default=str)


def freeze():
    contract=dict(version='G25_ENTRY_ONLY_DIAGNOSTIC_AND_READ_ONLY_OBSERVATIONS_V1',
        authorization='Original user Section 9 requires Entry Only G25 and G100; continuous closure Section 16 resumes that work after identity PASS',
        extension='Parent constructor validates Entry Only only at G100. Initialize identical Entry Only object then set the user-requested target=.25; no other rule, method or threshold changes',
        observations='Read target vector after frozen normalization solver, before execution. Add marks, per-lot realized P&L and root cash credits to daily observation only. No account, order, price, membership or cash changes',
        continuous_protocol_sha256=sha256(HERE/'contracts/continuous_rollforward_protocol_v1.json'),
        parent_scaling_sha256=sha256(HERE.parent/'capital_scaling_v1/scaling.py'),
        observer_source_sha256=sha256(__file__),base_run_inputs_sha256=sha256(HERE/'account_run_input_identity.json'))
    path=HERE/'contracts/scaling_observation_extension_v1.json'
    if path.exists():assert json.loads(path.read_text())==contract,'SCALING_OBSERVER_CONTRACT_DRIFT'
    else:
        write_json(path,contract)
        write_json(HERE/'contracts/scaling_observation_freeze_receipt.json',dict(sha256=sha256(path),frozen_at=datetime.now(timezone.utc).isoformat(),scaling_outcomes_started=False))
    return sha256(path)


def run_case(case):
    digest=sha256(HERE/'contracts/scaling_observation_extension_v1.json')
    contract=json.loads((HERE/'contracts/scaling_observation_extension_v1.json').read_text())
    assert contract['observer_source_sha256']==sha256(__file__)
    path=accounts.folder(*case)
    if (path/'receipt.json').exists():
        saved=json.loads((path/'observation_receipt.json').read_text())
        assert saved['contract_sha256']==digest
        for name,expected in saved['hashes'].items():assert sha256(path/name)==expected
        return accounts.run_case(case)
    instances=[]
    def factory(*args,**kwargs):
        value=ObservedScaling(*args,**kwargs);instances.append(value);return value
    accounts.Scaling=factory
    accounts.observed_replay=corrected_function(replay,[
        ('daily.append(dict(row,trade_date=when.normalize()))','observer(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],observer=observer)
    receipt=accounts.run_case(case)
    assert len(instances)==1
    pd.DataFrame(instances[0].target_observations).to_parquet(path/'normalization_targets.parquet',index=False)
    write_json(path/'observation_receipt.json',dict(contract_sha256=digest,hashes={'normalization_targets.parquet':sha256(path/'normalization_targets.parquet')}))
    return receipt


if __name__=='__main__':print(freeze())
