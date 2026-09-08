"""Frozen daily playbook signals and a governed cash-account diagnostic.

This module intentionally reuses the audited V3 account.  It is a diagnostic,
not a replacement for its corporate-action or execution semantics.
"""
import argparse, hashlib, json, sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "research" / "usic_multichampion_ashare_v3"
sys.path.insert(0, str(ROOT))
from research.usic_multichampion_ashare_v3.engine import Market, replay
from research.usic_multichampion_ashare_v3.common import sha

HERE = Path(__file__).resolve().parent
OUT = Path("/Volumes/quant/CY_quant_research/ashare_champion_playbooks_v1")


def dump(name, value):
    p = HERE / name
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def ema(x, span):
    return pd.DataFrame(x).ewm(span=span, adjust=False, min_periods=span).mean().to_numpy()


def signals(m):
    a = m.a; close, high, low = a['close'], a['high'], a['low']
    n, z = close.shape
    e9, e21, e50 = ema(close, 9), ema(close, 21), ema(close, 50)
    rs = np.full((n,z), np.nan); rs[60:] = close[60:] / close[:-60] - 1
    rsrank = np.full((n,z), np.nan)
    for t in range(60,n): rsrank[t] = pd.Series(rs[t]).rank(pct=True).to_numpy()
    valid = (a['hard_valid']==1)&(a['is_st']==0)&(a['trade_status']==1)&np.isfinite(close)&(close>0)
    rows = {k:[] for k in ('P1_NATIVE','P3B_NATIVE','P4_NATIVE')}
    for t in range(61,n-1):
        if m.dates[t] < '2020-01-01': continue
        good = valid[t] & (e9[t]>e21[t]) & (e21[t]>e50[t]) & (e21[t]>e21[t-5]) & (e50[t]>e50[t-5]) & (rsrank[t]>=.9)
        for j in np.flatnonzero(good):
            # Values are frozen at t close; each row fills through V3 at t+1 open.
            event = np.any(close[max(0,t-10):t+1,j] > np.maximum.accumulate(high[max(0,t-30):t-10,j]).max()) if t>=30 else False
            prior20 = high[t-20:t,j].max()
            base_low = low[t-5:t,j].min(); pivot = high[t-5:t,j].max()
            common = dict(t=t,j=int(j),symbol=m.symbols[j],factor=float(a['factor'][t,j]),U=float(high[t,j]),a0=float(np.nanmean(high[t-20:t,j]-low[t-20:t,j])),amount20=float(np.nanmedian(a['amount'][t-20:t,j])),industry=int(a['industry'][t,j]),decision_at=m.dates[t]+'T15:00:00+08:00')
            if event:
                episode = (low[t-9:t+1,j] <= e21[t-9:t+1,j]) | (close[t-9:t+1,j] <= e9[t-9:t+1,j])
                first = np.flatnonzero(episode)
                if len(first) and first[0] < 9 and close[t,j] > high[t-1,j] and close[t,j] > e50[t,j]:
                    stop = low[t-9+first[0]:t+1,j].min()
                    rows['P1_NATIVE'].append(dict(common, route='P1', setup_id=f'P1:{t}:{j}', score=float(rsrank[t,j]), limit=float(close[t,j]*1.03), S0=float(stop)))
            medamt = np.nanmedian(a['amount'][t-20:t,j])
            if close[t,j] >= a['preclose'][t,j]*1.10 and a['amount'][t,j] >= 3*medamt and close[t,j] >= (high[t,j]+low[t,j])/2:
                rows['P3B_NATIVE'].append(dict(common, route='P3B', setup_id=f'P3B:{t}:{j}', score=float(rsrank[t,j]), limit=float(close[t,j]*1.03), S0=float(low[t,j])))
            # P4 is an explicit union of existing early strength, first crossback, continuation.
            crossback = close[t-1,j] <= e9[t-1,j] and close[t,j] > e9[t,j]
            continuation = close[t,j] > pivot and close[t-1,j] <= pivot
            if event or crossback or continuation:
                stop = min(low[t-5:t+1,j].min(), e50[t,j])
                rows['P4_NATIVE'].append(dict(common, route='P4', setup_id=f'P4:{t}:{j}', score=float(rsrank[t,j]), limit=float(close[t,j]*1.03), S0=float(stop)))
    return {k:pd.DataFrame(v) for k,v in rows.items()}


def account(m, name, f):
    # V3 preserves physical cash, lots, T+1, limit and corporate-action ledgers.
    # Its MAX40-only exit is deliberately not promoted as the requested native shell.
    s = dict(id=name, capital='C_MAX', mode='C_MAX', exit='TREND40', registered_exit='TREND40', cost=1, delay=1, policy='', overlay='NONE', stress='BASE')
    nav,trades,orders,audit,openpos,holds = replay(m,s,f.sort_values(['t','score','symbol'],ascending=[True,False,True]))
    d=OUT/name; d.mkdir(parents=True,exist_ok=True)
    for k,x in dict(nav=nav,trades=trades,orders=orders,audit=audit,open_positions=openpos,holdings=holds).items(): x.to_parquet(d/(k+'.parquet'),index=False)
    assert (nav.cash >= -1e-7).all() and (nav.market_value <= nav.nav+1e-7).all()
    pf = trades.loc[trades.pnl>0,'pnl'].sum() / -trades.loc[trades.pnl<0,'pnl'].sum() if (trades.pnl<0).any() else np.nan
    dd = (nav.nav/nav.nav.cummax()-1).min()
    return dict(playbook=name, signals=len(f), fills=int((orders.status=='FILLED').sum()), trades=len(trades), net_return=float(nav.nav.iloc[-1]/1e6-1), maxdd=float(dd), profit_factor=float(pf), min_cash=float(nav.cash.min()), status='DIAGNOSTIC_ONLY_MISSING_NATIVE_WINNER_SHELL')


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--stage', choices=['signals','account','publish'], default='publish'); ap.add_argument('--playbook'); args=ap.parse_args()
    HERE.mkdir(exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
    m=Market()
    if args.stage == 'signals':
        for name,f in signals(m).items(): f.to_parquet(OUT/(name+'_signals.parquet'),index=False)
        return
    frames={k:pd.read_parquet(OUT/(k+'_signals.parquet')) for k in ('P1_NATIVE','P3B_NATIVE','P4_NATIVE')}
    if args.stage == 'account':
        assert args.playbook in frames
        row=account(m,args.playbook,frames[args.playbook])
        p=OUT/(args.playbook+'_result.json'); p.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
        return
    blocked={
        'P1_NATIVE':'BLOCKED_DATA: HELD_ACTION_MISSING cninfo distribution share_credit_date',
        'P4_NATIVE':'BLOCKED_DATA: HELD_ACTION_MISSING cninfo distribution share_credit_date',
    }
    rows=[]
    for k in frames:
        p=OUT/(k+'_result.json')
        rows.append(json.loads(p.read_text()) if p.exists() else dict(playbook=k,signals=len(frames[k]),status=blocked[k]))
    pd.DataFrame(rows).to_csv(HERE/'scenario_summary.csv',index=False)
    pd.DataFrame(rows).to_csv(HERE/'playbook_trade_stats.csv',index=False)
    dump('ACCOUNT_AUDIT.json',dict(status='FAIL_CLOSED',p1_p4='official action terms incomplete',p3b='diagnostic used C_MAX rather than required planned-risk contract',engine='USIC V3 audited physical account',limitation='native structural failure and EMA10 winner exits are not implemented by reused engine'))
    dump('SAMPLE_PERMISSION_AUDIT.json',dict(status='PASS_PIT_B',development='2020-2023 consumed',warmup='2018-2019',inputs=dict(daily='CY-006',minute='CY-008'),blocked=dict(P2='BLOCKED_MINUTE_DATA: no verified 14:25 feature contract',P3A='BLOCKED_EVENT_DATA: Q1 permission gate')))
    dump('PLAYBOOK_CONTRACTS.json',dict(risk='0.50% planned risk, 15% name, 2% aggregate (required native contract)',execution='T+1 open, lots, limits, actions through V3',non_chase='3% frozen diagnostic limit',p2='not run',p3a='not run'))
    (HERE/'PLAYBOOK_SOURCE_REGISTER.md').write_text('# Source fidelity register\n\nP1 and P4 are public-principle-inspired mechanical proxies, not replications. P2 source: https://afzallokhandwala.com/system/ (accessed 2026-09-08). P3 uses a price/volume proxy because PIT catalyst data is blocked.\n')
    dump('PLAYBOOK_SOURCE_REGISTER.json',dict(P1=dict(SOURCE_EXPLICIT=['pullback into rising EMA support'],SOURCE_UNCERTAIN=['exact champion trigger/exit'],A_SHARE_ADAPTATION=['T+1 and legal open'],MECHANICAL_PROXY=['EMA 9/21/50, RS60, first pullback']),P2=dict(SOURCE_EXPLICIT=['last-half-hour and relative volume'],SOURCE_UNCERTAIN=['exact threshold'],A_SHARE_ADAPTATION=['14:25 cutoff'],MECHANICAL_PROXY=['blocked']),P3=dict(SOURCE_EXPLICIT=['catalyst-led repricing'],SOURCE_UNCERTAIN=['exact reaction rule'],A_SHARE_ADAPTATION=['T+1'],MECHANICAL_PROXY=['10% gap, 3x amount']),P4=dict(SOURCE_EXPLICIT=['phase-aware cycle'],SOURCE_UNCERTAIN=['private phase exits'],A_SHARE_ADAPTATION=['one physical position'],MECHANICAL_PROXY=['daily event union'])))
    (HERE/'RESEARCH_LOG.jsonl').write_text(json.dumps(dict(ROUND=1,PLAYBOOK='P1/P3B/P4',EVIDENCE='contracts frozen before diagnostic account',FAILURE_MECHANISM='native exit shell unavailable in reused engine',NEW_HYPOTHESIS='none',MATERIAL_CHANGE='none',BASELINE='none',EXPECTED='diagnostic only',FALSIFIER='native shell implementation'))+'\n')
    for x in ['r_multiple_distribution.csv','failure_attribution.csv','annual_results.csv','concentration.csv','playbook_overlap.csv','failed_variants.csv']:
        pd.DataFrame().to_csv(HERE/x,index=False)
    (HERE/'TEST_RESULTS.md').write_text('# Tests\n\nDiagnostic account asserts non-negative cash and no market value above NAV; inherited V3 execution/action tests remain the governing tests. Native winner-management tests are not implemented, so this study cannot issue a final economic verdict.\n')
    (HERE/'REPORT.md').write_text('# A-share champion playbooks V1\n\n## Fail-closed conclusion\n\nNo final economic verdict is issued. P2 is `BLOCKED_MINUTE_DATA`: the registered tail execution bar does not supply the required 14:25 same-clock admission state. P3A is `BLOCKED_EVENT_DATA`: first-public catalyst permission is absent. P1 and P4 are `BLOCKED_DATA`: each physical account reaches an official distribution with no verified `share_credit_date`, which the inherited action ledger correctly rejects. P3B completed only as a diagnostic under the inherited `C_MAX` sizing, rather than the frozen 0.50%/2% planned-risk account; its -99.48% net return and 0.459 PF cannot be published as a primary result. The reused engine also lacks the specified failure/EMA10 winner exit. Therefore none may be called rejected, promising, or a shadow candidate.\n\nThe required whole-project four-way verdict cannot truthfully be selected because it presupposes certified primary accounts.\n')
    dump('DELIVERY_STATUS.json',dict(status='FAIL_CLOSED_INCOMPLETE_PRIMARY_ACCOUNTS',verdict='NO_FINAL_ECONOMIC_VERDICT',blocked=dict(P1='action terms',P2='14:25 minute admission',P3A='event permission',P4='action terms'),diagnostic='P3B nonconforming C_MAX replay'))
    (HERE/'REPRODUCTION.md').write_text('Run: PYTHONPATH=. python -m research.ashare_champion_playbooks_v1.run\n')

if __name__=='__main__': main()
