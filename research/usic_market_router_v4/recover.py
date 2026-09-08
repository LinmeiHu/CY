"""Retry only exact locally blocked accounts after documented official fact repair."""
import json
import pandas as pd
from .common import OUT
from .market import Market,apply_facts
from .engine import replay
from .engine_correction import replay as correction_replay
from .tail_correction import replay as tail_replay
from .runner import run,publish

def main():
    m=Market();m.v4state=pd.read_parquet(OUT/'state_daily.parquet');minute=None
    attempts=list((OUT/'accounts').glob('*/result.json'))
    for p in attempts:
        r=json.loads(p.read_text())
        if r['status']!='BLOCKED_INPUT' or r['id'].endswith('_CA'):continue
        sc=dict(r['identity']['config']);sc['id']+='_CA'
        f=pd.read_parquet(p.parent/'input_signals.parquet');engine=correction_replay if r['version_family']=='V3_CORRECTION' else replay;market=m
        if r['id'].startswith('FIX_Q3'):
            if minute is None:
                from ..usic_multichampion_ashare_v3.minute_market import MinuteMarket
                minute=apply_facts(MinuteMarket())
            market=minute
            if 'ENHANCED' in r['id']:engine=tail_replay
        run(market,sc,f,r['version_family'],engine);publish()

if __name__=='__main__':main()
