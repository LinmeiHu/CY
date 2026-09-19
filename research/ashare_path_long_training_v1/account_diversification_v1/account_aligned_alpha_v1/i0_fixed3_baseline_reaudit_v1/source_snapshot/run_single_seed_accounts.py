#!/usr/bin/env python3
"""CPU-only 2020 single-seed MASTER H10 account diagnostic; never imports torch."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from datetime import datetime, timezone
from decimal import Decimal as D
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
MASTER = HERE.parent
VOL = Path('/Volumes/quant/CY_quant_research/ashare_path_long_training_v1')
FULL = VOL / 'account_diversification_v1/account_aligned_alpha_v1/full_date_cross_stock_reconciliation_v1/full_forward/2020'
PRED = VOL / 'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/predictions/2020'
EXT = VOL / 'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/single_seed_account_diagnostic_v1'
E0_REPORT = MASTER / 'ensemble_tail_autopsy_v1'
E0_CACHE = VOL / 'account_diversification_v1/account_aligned_alpha_v1/master_alpha158_profit_first_v2/ensemble_tail_autopsy_v1'
BROADER = MASTER.parent / 'broader_ranking_portfolio_v1/run.py'
SEEDS = (17, 29, 43)


def sha(p: Path) -> str:
    with p.open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def dump(p: Path, x) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False, default=str) + '\n')


def module(name: str, p: Path):
    s = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


def percentile(keys: pd.DataFrame, raw: np.ndarray) -> np.ndarray:
    out = np.empty(len(raw), float)
    for _, ix in keys.groupby('t', sort=False).indices.items():
        out[ix] = pd.Series(raw[ix]).rank(method='average', pct=True).to_numpy(float)
    return out


def candidate_metrics(br, arm: str, score_path: Path, ledgers: Path, policy: str) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    """Patch metric rank fields to use the actual candidate score, not incumbent ranks."""
    m, _ = br.account_metrics(2020, arm, ledgers, policy)
    score = pd.read_parquet(score_path, columns=['t', 'j', 'score'])
    score['candidate_rank'] = score.groupby('t').score.rank(method='first', ascending=False)
    score['candidate_percentile'] = score.groupby('t').candidate_rank.transform(lambda x: x / len(x))
    orders = br.read_ledger(ledgers, policy, 'orders')
    buys = orders[(orders.side == 'BUY') & (orders.status == 'FILLED')].copy()
    joined = buys.rename(columns={'decision_t':'t_score'}).merge(
        score.rename(columns={'t':'t_score'})[['t_score','j','candidate_rank','candidate_percentile']],
        on=['t_score','j'], how='left', validate='many_to_one')
    uncovered = joined.candidate_rank.isna()
    if (joined.loc[uncovered, 't_score'] >= int(score.t.min())).any():
        raise RuntimeError(f'POST_PANEL_SCORE_MISSING:{arm}')
    covered = joined.loc[~uncovered].copy()
    m.update({'candidate_rank_covered_fills': int(len(covered)), 'candidate_rank_uncovered_inherited_fills': int(uncovered.sum()),
              'median_funded_candidate_rank': float(covered.candidate_rank.median()),
              'p90_funded_candidate_rank': float(covered.candidate_rank.quantile(.9)),
              'mean_funded_candidate_rank_percentile': float(covered.candidate_percentile.mean())})
    nav = br.read_ledger(ledgers, policy, 'nav')
    return m, covered, nav


def run_account(br, arm: str, score_path: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    dates, symbols, ts, market, actions, _ = br.context(2020)
    signal = br.signal_frame(2020, ts[0], ts[-1]).drop(columns=['score'])
    score = pd.read_parquet(score_path, columns=['t','j','score'])
    signal = signal.merge(score, on=['t','j'], how='left', validate='one_to_one')
    if signal.score.isna().any(): raise RuntimeError(f'ACCOUNT_SCORE_MISSING:{arm}')
    starts = br.load(br.BASE / '2020/H10_CANONICAL_STARTS.json')
    if len(starts) != 1 or starts[0]['tag'] != 'ROOT': raise RuntimeError('CANONICAL_START_IDENTITY')
    c = starts[0]
    if br.sha(Path(c['path'])) != c['hash'] or D(c['START_NAV']) != D(1000000): raise RuntimeError('CANONICAL_START_HASH')
    dest = EXT / 'accounts/2020' / arm; ledgers = dest / 'ledgers'; ledgers.mkdir(parents=True, exist_ok=True)
    source = br.devmod.source(2020, 10, 10); src = dest / 'RUN_SOURCE.py'; src.write_text(source)
    identity = {'year':2020,'arm':arm,'score_sha256':sha(score_path),'gate_sha256':br.sha(br.B7/'SIGNALS.parquet'),
                'canonical_start_sha256':c['hash'],'source_sha256':br.sha(src),'TopN':10,'holding':'H10','cpu_only':True}
    result = dest / 'RESULT.json'; policy = f'Y2020_SINGLE_{arm}_ROOT'
    if result.exists():
        old = br.load(result)
        if old['identity'] != identity: raise RuntimeError(f'ACCOUNT_IDENTITY_MISMATCH:{arm}')
    else:
        br.engine.OUT = ledgers
        scope = dict(br.engine.__dict__, holding_horizon=10, normalize_t=None, scale_for=lambda t:D(1), planning_audit=[])
        exec(source, scope)
        q = scope['run'](policy, signal, market, actions, dates, symbols, forecast_through=ts[-1], stagger=True,
                         resume_path=Path(c['path']), snapshot_path=dest/f'{policy}.pkl', entitlement_branch=c['choices'])
        if q['block'] is not None: raise RuntimeError(f'ACCOUNT_BLOCKED:{arm}:{q}')
        br.dump(dest/'ENGINE.json',q); pd.DataFrame(scope['planning_audit']).to_parquet(dest/'PLANNING.parquet',index=False)
        br.dump(result,{'status':'COMPLETE_RECONCILED','identity':identity,'policy':policy})
    return candidate_metrics(br, arm, score_path, ledgers, policy)


def nav_delta(nav_i: pd.DataFrame, nav_m: pd.DataFrame, seed: int, ts: list[int], dates: list[str]) -> pd.DataFrame:
    a = nav_i.set_index('t').reindex(ts); b = nav_m.set_index('t').reindex(ts)
    ri = a.nav.astype(float).pct_change(); rm = b.nav.astype(float).pct_change()
    ri.iloc[0] = float(a.nav.iloc[0]) / 1e6 - 1; rm.iloc[0] = float(b.nav.iloc[0]) / 1e6 - 1
    return pd.DataFrame({'seed':seed,'t':ts,'date':[dates[t] for t in ts], 'i0_daily_return':ri.to_numpy(), 'm_daily_return':rm.to_numpy(), 'm_minus_i0_daily_return':(rm-ri).to_numpy(), 'i0_nav':a.nav.astype(float).to_numpy(), 'm_nav':b.nav.astype(float).to_numpy()})


def main() -> None:
    lock = MASTER/'PIPELINE.lock'; pid=int(lock.read_text().strip())
    try: os.kill(pid,0)
    except OSError as e: raise RuntimeError('MAIN_PIPELINE_NOT_ALIVE') from e
    keys = pd.read_parquet(FULL/'KEYS.parquet',columns=['t','j','decision_date'])
    if keys.duplicated(['t','j']).any(): raise RuntimeError('KEY_IDENTITY_ERROR')
    stage=json.loads((MASTER/'ORCHESTRATION_STATE.json').read_text())
    spec={'status':'FROZEN_2020_ONLY','created_at':datetime.now(timezone.utc).astimezone().isoformat(),'main_pid':pid,'stage_at_start':stage,
          'cpu_only':True,'torch_imported':False,'mps_used':False,'new_training':False,'opened_2021':False,'opened_2022_2026':False,
          'score_contract':'same-date percentile over full ex-ante eligible universe, 1=best; frozen I0 RAW-positive admission unchanged; Top10/H10 canonical account'}
    dump(HERE/'SINGLE_SEED_ACCOUNT_SPEC.json',spec)
    scores={}
    for s in SEEDS:
        i=np.asarray(np.load(FULL/f'I0_s{s}.npy',mmap_mode='r'),float)
        m=pd.read_parquet(PRED/f'M-GTS_s{s}.parquet',columns=['t','j','score'])
        if not np.array_equal(m[['t','j']].to_numpy(),keys[['t','j']].to_numpy()): raise RuntimeError(f'M_KEY_MISMATCH:{s}')
        for tag, raw, src in ((f'I0_s{s}',i,FULL/f'I0_s{s}.npy'),(f'M_s{s}',m.score.to_numpy(float),PRED/f'M-GTS_s{s}.parquet')):
            p=HERE/'scores'/f'{tag}.parquet'; p.parent.mkdir(parents=True,exist_ok=True)
            keys[['t','j','decision_date']].assign(score=percentile(keys,raw)).to_parquet(p,index=False)
            scores[tag]={'path':p,'source':str(src),'source_sha256':sha(src),'score_sha256':sha(p)}
    br=module('single_seed_broader',BROADER)
    i0fixed,_=br.verify_a0(2020)
    e0=pd.read_csv(E0_REPORT/'ENSEMBLE_ACCOUNT_2020.csv').set_index('arm').loc['E0_MEAN3'].to_dict()
    e0score=E0_CACHE/'scores/E0_MEAN3_2020.parquet'
    parity={'I0_FIXED3':{'annual_return':i0fixed['annual_return'],'MaxDD':i0fixed['MaxDD'],'expected_return':.174396,'expected_MaxDD':.153134,
                          'pass':abs(i0fixed['annual_return']-.174396)<1e-5 and abs(i0fixed['MaxDD']-.153134)<1e-5},
            'M_MEAN3_E0_REUSED':{'annual_return':float(e0['annual_return']),'MaxDD':float(e0['MaxDD']),'expected_return':.015158,'expected_MaxDD':.165318,
                                  'score_sha256':sha(e0score),'pass':abs(float(e0['annual_return'])-.015158)<1e-5 and abs(float(e0['MaxDD'])-.165318)<1e-5}}
    if not all(x['pass'] for x in parity.values()): raise RuntimeError('ACCOUNT_PARITY_FAILURE')
    dump(HERE/'ACCOUNT_PARITY.json',parity)
    rows=[{**i0fixed,'arm':'I0_FIXED3','source':'AUTHORITATIVE_REUSED'},{**e0,'arm':'M_MEAN3','source':'E0_EXACT_REUSED'}]
    covered={}; navs={}
    # sequential, cacheable, low-priority process only
    for s in SEEDS:
        for kind in ('I0','M'):
            tag=f'{kind}_s{s}'; met, fills, nav=run_account(br,tag,scores[tag]['path'])
            rows.append({**met,'source':'CPU_REPLAY_FROZEN_2020'}); covered[tag]=fills; navs[tag]=nav
    result=pd.DataFrame(rows); result.to_csv(HERE/'SINGLE_SEED_ACCOUNT_RESULTS.csv',index=False)
    contrasts=[]
    for s in SEEDS:
        a=result.set_index('arm').loc[f'I0_s{s}']; b=result.set_index('arm').loc[f'M_s{s}']
        contrasts.append({'seed':s,'i0_return':a.annual_return,'m_return':b.annual_return,'m_minus_i0_return':b.annual_return-a.annual_return,
                          'i0_MaxDD':a.MaxDD,'m_MaxDD':b.MaxDD,'m_minus_i0_MaxDD':b.MaxDD-a.MaxDD,
                          'i0_exposure':a.average_exposure,'m_exposure':b.average_exposure,'m_minus_i0_exposure':b.average_exposure-a.average_exposure,
                          'i0_fees':a.fees,'m_fees':b.fees,'m_minus_i0_fees':b.fees-a.fees,
                          'i0_buy_fills':a.buy_fills,'m_buy_fills':b.buy_fills,'m_minus_i0_buy_fills':b.buy_fills-a.buy_fills,
                          'm_beats_matched_i0':bool(b.annual_return>a.annual_return),'m_beats_i0_fixed3':bool(b.annual_return>i0fixed['annual_return'])})
    con=pd.DataFrame(contrasts); con.to_csv(HERE/'SINGLE_SEED_MATCHED_CONTRASTS.csv',index=False)
    dates,_,ts,_,_,_=br.context(2020)
    pnl=pd.concat([nav_delta(navs[f'I0_s{s}'],navs[f'M_s{s}'],s,ts,dates) for s in SEEDS],ignore_index=True); pnl.to_csv(HERE/'PNL_ATTRIBUTION_BY_DAY.csv',index=False)
    month=(pnl.assign(month=lambda x:x.date.str.slice(0,7)).groupby(['seed','month'],as_index=False).agg(days=('t','size'),i0_return_sum=('i0_daily_return','sum'),m_return_sum=('m_daily_return','sum'),m_minus_i0_return_sum=('m_minus_i0_daily_return','sum'),positive_delta_days=('m_minus_i0_daily_return',lambda x:int((x>0).sum()))))
    month.to_csv(HERE/'PNL_ATTRIBUTION_BY_MONTH.csv',index=False)
    paths=[]; fund=[]
    for s in SEEDS:
        si=pd.read_parquet(scores[f'I0_s{s}']['path']); sm=pd.read_parquet(scores[f'M_s{s}']['path'])
        ri=si.groupby('t').score.rank(method='first',ascending=False); rm=sm.groupby('t').score.rank(method='first',ascending=False)
        z=si[['t','j','decision_date']].copy(); z['i0_top10']=ri.le(10); z['m_top10']=rm.le(10)
        for t,g in z.groupby('t',sort=False):
            paths.append({'seed':s,'t':int(t),'date':str(g.decision_date.iloc[0])[:10],'top10_overlap':int((g.i0_top10&g.m_top10).sum()),'i0_only':int((g.i0_top10&~g.m_top10).sum()),'m_only':int((~g.i0_top10&g.m_top10).sum())})
        for kind in ('I0','M'):
            x=covered[f'{kind}_s{s}']
            tag=f'{kind}_s{s}'; score=pd.read_parquet(scores[tag]['path'], columns=['t','j','score'])
            admission=br.signal_frame(2020, ts[0], ts[-1]).drop(columns=['score']).merge(score,on=['t','j'],how='left',validate='one_to_one')
            admission['admission_rank']=admission.groupby('t').score.rank(method='first',ascending=False)
            policy=f'Y2020_SINGLE_{tag}_ROOT'; ledgers=EXT/'accounts/2020'/tag/'ledgers'
            orders=br.read_ledger(ledgers,policy,'orders'); inv=br.read_ledger(ledgers,policy,'inventory')
            buys=orders[(orders.side=='BUY') & (orders.decision_t>=int(score.t.min()))]
            carried=inv[inv.t.isin(ts)].groupby('t').j.nunique()
            fund.append({'seed':s,'arm':kind,'raw_positive_admitted_candidate_top10_rows':int(admission.admission_rank.le(10).sum()),'candidate_dates':int(admission.t.nunique()),'new_buy_orders_requested':int(len(buys)),'new_buy_filled':int((buys.status=='FILLED').sum()),'new_buy_rejected_or_blocked':int((buys.status!='FILLED').sum()),'retry_blocked':int((buys.status=='RETRY_BLOCKED').sum()),'cancelled_unbuyable':int((buys.status=='CANCELLED_UNBUYABLE').sum()),'mean_carried_positions':float(carried.mean()),'max_carried_positions':int(carried.max()),'score_covered_new_fills':int(len(x)),'median_funded_rank':float(x.candidate_rank.median()),'p90_funded_rank':float(x.candidate_rank.quantile(.9)),'mean_funded_percentile':float(x.candidate_percentile.mean())})
    pd.DataFrame(paths).to_csv(HERE/'TOP10_TRADE_PATH_SUMMARY.csv',index=False); pd.DataFrame(fund).to_csv(HERE/'FUNDED_SELECTION_DIAGNOSTICS.csv',index=False)
    # Bridge only joins read-only 2020 diagnostics already produced in this side task.
    r10=pd.read_csv(MASTER/'ret10_readonly_diagnostic/RET10_VS_RET20_SUMMARY.csv')
    bridge=[]
    for s in SEEDS:
        q=r10[r10.seed.eq(s)].iloc[0].to_dict(); c=con[con.seed.eq(s)].iloc[0].to_dict()
        bridge.append({'seed':s,**q,'account_m_minus_i0_return':c['m_minus_i0_return'],'account_m_beats_i0':c['m_beats_matched_i0'],'bridge':'SIGNAL_TO_H10_ACCOUNT'})
    pd.DataFrame(bridge).to_csv(HERE/'SIGNAL_TO_ACCOUNT_BRIDGE.csv',index=False)
    wins=int(con.m_beats_matched_i0.sum()); fixed=int(con.m_beats_i0_fixed3.sum())
    verdict='SINGLE_SEED_ALPHA_MONETIZES_ENSEMBLE_IS_BOTTLENECK' if wins>=2 and fixed>=2 else ('MASTER_IMPROVES_SINGLE_SEEDS_BUT_I0_FIXED3_STILL_SUPERIOR' if wins>=2 else 'SIGNAL_DOES_NOT_SURVIVE_H10_ACCOUNT')
    packet={'status':'COMPLETE','main_pipeline_untouched':True,'main_pid_alive':True,'cpu_only':True,'no_new_training':True,'no_model_selection_changed':True,
            'parity':parity,'matched_seed_wins':wins,'m_beats_i0_fixed3':fixed,'verdict':verdict,'opened_2021':False,'opened_2022':False,'opened_2023':False,'opened_2024_2026':False}
    dump(HERE/'DECISION_PACKET_SINGLE_SEED_ACCOUNT.json',packet)
    report=['# MASTER 2020 Single-seed H10 Account Diagnostic','', 'Only completed 2020 frozen predictions were read. CPU-only; the main MPS pipeline was not modified.','', '## Parity','',pd.DataFrame(parity).T.to_markdown(),'','## Account results','',result.to_markdown(index=False),'','## Matched contrasts','',con.to_markdown(index=False),'',f'**VERDICT = {verdict}**','']
    (HERE/'SINGLE_SEED_ACCOUNT_DIAGNOSTIC.md').write_text('\n'.join(report))


if __name__ == '__main__': main()
