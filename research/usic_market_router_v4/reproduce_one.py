"""Exactly replay saved V4 account inputs and check every output byte."""
import argparse,json,importlib
import pandas as pd
from .common import HERE,OUT,sha,parquet
from .engine_correction import Market
from .market import apply_facts

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--id',required=True);args=ap.parse_args()
    d=OUT/'accounts'/args.id;row=json.loads((d/'result.json').read_text());assert row['status']=='COMPLETED'
    ident=row['identity'];source=ident['engine_source'];assert sha(HERE/source)==ident['engine']
    if 'Q3' in args.id:
        from ..usic_multichampion_ashare_v3.minute_market import MinuteMarket
        m=MinuteMarket()
    else:m=Market()
    if 'v4_official_facts' in ident['actions']:apply_facts(m)
    assert m.execution_binding==ident['actions']
    m.v4state=pd.read_parquet(OUT/'confirmation_state_daily.parquet')
    f=pd.read_parquet(d/'input_signals.parquet');assert sha(d/'input_signals.parquet')==ident['signal_hash']
    fn=importlib.import_module(__package__+'.'+source[:-3]).replay
    outputs=fn(m,ident['config'],f);dest=OUT/'verification'/(args.id+'_manual');dest.mkdir(parents=True,exist_ok=True)
    for name,value in zip(['nav','trades','orders','audit','open_positions','holdings'],outputs):
        p=dest/(name+'.parquet');parquet(p,value);assert sha(p)==row['artifacts'][p.name],name
    print('SIX_ARTIFACT_HASHES_IDENTICAL',args.id,flush=True)

if __name__=='__main__':main()
