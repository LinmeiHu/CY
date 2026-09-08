"""Same exogenous signals/reference sizing, separate endogenous admission paths."""
import json
import pandas as pd
from .accounts import folder,END
from .audit import HERE,sha256


def run():
    binding=json.loads((HERE/'account_run_input_identity.json').read_text());rows=[]
    for gap in ['OGR','IFCGR']:
        for mode in ['independent','confirmation_tag']:
            for target in ['G25','G100']:
                a=folder(gap,mode,target,'FULL_BOOK_NORMALIZATION',END);b=folder(gap,mode,target,'ENTRY_ONLY',END)
                ra=json.loads((a/'receipt.json').read_text());rb=json.loads((b/'receipt.json').read_text())
                assert ra['input_identity']==rb['input_identity']==sha256(HERE/'account_run_input_identity.json')
                x=json.loads((a/'account.json').read_text());y=json.loads((b/'account.json').read_text());assert x['initial_states']==y['initial_states']
                for strategy in ['ATRDR','MCB',gap]:
                    name=strategy.lower()+'_intents.parquet';x=pd.read_parquet(a/name);y=pd.read_parquet(b/name)
                    fields=['event_id','symbol','decision_at','earliest_execution_at','price','native_requested_notional','economic_event_definition']
                    fields=[c for c in fields if c in x and c in y]
                    common=set(x.event_id)&set(y.event_id)
                    left=x.loc[x.event_id.isin(common),fields].sort_values('event_id').reset_index(drop=True)
                    right=y.loc[y.event_id.isin(common),fields].sort_values('event_id').reset_index(drop=True)
                    pd.testing.assert_frame_equal(left,right,check_dtype=False,rtol=1e-11,atol=1e-6)
                    rows.append(dict(gap=gap,mcb_mode=mode,target=target,strategy=strategy,input_identity=ra['input_identity'],common_initial_state=True,common_signal_and_quote_inputs=True,common_intent_fields='|'.join(fields),common_events=len(common),full_book_intents=len(x),entry_only_intents=len(y),status='PASS',scope='Common exogenous precapital signals and Native reference requests. Post-state ACTIVE_SYMBOL/MAX_K/native_failures and ownership paths may change admitted intents; not a changed alpha rule'))
    pd.DataFrame(rows).to_csv(HERE/'output/mechanics_input_identity.csv',index=False)


if __name__=='__main__':run()
