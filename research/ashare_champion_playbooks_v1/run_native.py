"""Run one frozen P3B native scenario and persist authoritative artifacts."""
import argparse,json,time
from pathlib import Path
import pandas as pd
from .native_engine import Market,replay,HERE,OUT
from research.usic_multichampion_ashare_v3.common import sha,parquet,dump

SIGNALS=Path('/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1/P3B_NATIVE_signals.parquet')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--scenario',choices=['BASE','COST2','DELAY1'],required=True);ap.add_argument('--repeat',action='store_true');a=ap.parse_args()
    f=pd.read_parquet(SIGNALS);sid='P3B_NATIVE_'+a.scenario;m=Market();s=dict(id=sid,delay=2 if a.scenario=='DELAY1' else 1,mode='NATIVE',cost=2 if a.scenario=='COST2' else 1,exit='NATIVE')
    nav,trades,orders,audit,openpos,holds=replay(m,s,f);d=OUT/sid;d.mkdir(parents=True,exist_ok=True);suffix='_repeat' if a.repeat else ''
    artifacts={}
    for name,x in dict(nav=nav,trades=trades,orders=orders,audit=audit,open_positions=openpos,holdings=holds).items():
        p=d/(name+suffix+'.parquet');parquet(p,x);artifacts[p.name]=sha(p)
    assert len(nav)==970 and (nav.cash>=-1e-7).all() and (nav.borrowed_cash==0).all() and (nav.margin==0).all()
    fills=orders[orders.status.eq('FILLED')]
    assert (nav.market_value<=nav.nav+1e-7).all() and (holds.q%1==0).all() and (fills.aggregate_risk_after<=fills.risk_cap+1e-7).all()
    result=dict(scenario=sid,status='COMPLETED',signals=len(f),fills=int(orders.status.eq('FILLED').sum()),closed_trades=len(trades),open_positions=len(openpos),final_nav=float(nav.nav.iloc[-1]),net_return=float(nav.nav.iloc[-1]/1e6-1),maxdd=float((nav.nav/nav.nav.cummax()-1).min()),min_cash=float(nav.cash.min()),input_sha256=sha(SIGNALS),engine_sha256=sha(HERE/'native_engine.py'),artifacts=artifacts,completed_at=time.time())
    dump(d/('result_repeat.json' if a.repeat else 'result.json'),result);print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
