"""Same corrected P3B signals under the frozen legacy C_MAX/TREND40 account."""
from pathlib import Path
import json,pandas as pd
from .native_engine import Market
from research.usic_multichampion_ashare_v3.engine import replay
from research.usic_multichampion_ashare_v3.common import parquet,dump

def main():
    src=Path('/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1/P3B_NATIVE_signals.parquet');f=pd.read_parquet(src);m=Market();s=dict(id='P3B_SAME_SIGNAL_LEGACY',delay=1,mode='C_MAX',cost=1,exit='TREND40',overlay='NONE',policy='')
    nav,trades,orders,audit,openpos,holds=replay(m,s,f);d=Path('/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1/legacy_same_signal');d.mkdir(parents=True,exist_ok=True)
    for name,x in dict(nav=nav,trades=trades,orders=orders,audit=audit,open_positions=openpos,holdings=holds).items():parquet(d/(name+'.parquet'),x)
    dump(d/'result.json',dict(status='COMPLETED',signals=len(f),fills=int(orders.status.eq('FILLED').sum()),trades=len(trades),final_nav=float(nav.nav.iloc[-1]),net_return=float(nav.nav.iloc[-1]/1e6-1),maxdd=float((nav.nav/nav.nav.cummax()-1).min())))
if __name__=='__main__':main()
