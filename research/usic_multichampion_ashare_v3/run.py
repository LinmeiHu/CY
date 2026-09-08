"""Run the registered accounts, atomically checkpoint real completions, resume exact identities."""
import argparse,json,time,traceback,os
from pathlib import Path
import numpy as np
import pandas as pd
from .common import HERE,OUT,sha,dump,parquet,scenarios,rank
from .engine import Market,replay,metrics,ExecutionGap


def config(s):
    return dict(s,mode=s['capital'],exit='TREND40' if s['exit']=='EST' else 'FIXED10',registered_exit=s['exit'],cost=2 if s['stress']=='COST2' else 1,delay=2 if s['stress']=='DELAY1' else 1,policy=s['signal'] if s['signal'].startswith('P') else '')


def portfolio_frames(m,frames):
    families=['D02','D03','D06','D09'];f=pd.concat([frames[r] for r in families],ignore_index=True)
    f['score']=f.groupby(['route','t']).score.transform(rank);f['family_count']=f.groupby(['t','j']).route.transform('nunique');f['family_order']=f.route.map({r:i for i,r in enumerate(families)})
    p0=f.sort_values(['t','score','family_count','symbol','family_order'],ascending=[True,False,False,True,True]).drop_duplicates(['t','j'])
    f['phase_order']=[(['D02','D03','D09','D06'] if m.state[int(t)-1]=='BULL' else ['D06','D03','D02','D09'] if m.state[int(t)-1]=='TRANSITION' else ['D03','D06','D02','D09']).index(r) for r,t in zip(f.route,f.t)]
    p2=f.sort_values(['t','phase_order','score','symbol'],ascending=[True,True,False,True]).drop_duplicates(['t','j'])
    rows=[];history={}
    for t,g in f.groupby('t',sort=True):
        t=int(t)
        for j,gg in g.groupby('j'):
            j=int(j);prior=history.setdefault(j,[]);prior.extend(gg.to_dict('records'));valid=[]
            for r in prior:
                rt=int(r['t']);expiry=int(r['expiry_t']) if r['route']=='D09' else rt+4
                if rt<t-4 or t>expiry:continue
                cc=m.a['coord'][rt:t+1,j]
                if not np.all(np.isfinite(cc)) or np.any(cc<r['S0']*r['factor']):continue
                valid.append(r)
            history[j]=valid;count=len({r['route'] for r in valid})
            if count<2:continue
            current=[r for r in valid if int(r['t'])==t]
            if not current:continue
            r=sorted(current,key=lambda r:(-r['score'],families.index(r['route'])))[0];rows.append(dict(r,confirming_families=count))
    p3=pd.DataFrame(rows,columns=list(f.columns)+['confirming_families']) if not rows else pd.DataFrame(rows)
    if len(p3):p3=p3.sort_values(['t','confirming_families','score','symbol'],ascending=[True,False,False,True])
    return {'P0_POOL':p0,'P1_BALANCED':f.sort_values(['t','score','symbol'],ascending=[True,False,True]),'P2_PHASE':p2,'P3_CORROBORATE':p3}


def identity(s,framehash):
    names=['common.py','engine.py','legacy_replay.py','legacy_common.py']
    return dict(config=s,engine={n:sha(HERE/n) for n in names},features=framehash,input_manifest=sha(HERE/'INPUT_MANIFEST.json'),action_backfill=sha(HERE/'action_backfill.csv'))


def more_metrics(nav,trades,orders,holds):
    x={};x['filled_buys']=int((orders.status=='FILLED').sum()) if len(orders) else 0
    x['win_rate']=float((trades.pnl>0).mean()) if len(trades) else None
    x['profit_factor']=float(trades.loc[trades.pnl>0,'pnl'].sum()/-trades.loc[trades.pnl<0,'pnl'].sum()) if len(trades) and (trades.pnl<0).any() else None
    x['worst_trade_pnl']=float(trades.pnl.min()) if len(trades) else None
    x['flat_days']=int((nav.holdings==0).sum());x['max_exposure']=float(nav.exposure.max());x['min_cash']=float(nav.cash.min());x['nav_rows']=len(nav)
    d=(nav.nav/np.maximum.accumulate(np.r_[1e6,nav.nav.to_numpy()])[1:]-1).to_numpy();duration=0;maxduration=0;lossrun=0;maxlossrun=0
    for dd,r in zip(d,nav.return_daily):
        duration=duration+1 if dd<0 else 0;maxduration=max(maxduration,duration)
        lossrun=lossrun+1 if r<0 else 0;maxlossrun=max(maxlossrun,lossrun)
    x['max_underwater_sessions']=maxduration;x['max_losing_days']=maxlossrun
    if len(holds):x['max_plan_risk_cny']=float(holds.groupby('date').risk_used.sum().max());x['max_mark_risk_cny']=float(holds.groupby('date').mark_risk.sum().max())
    return x


def publish_summary():
    rows=[]
    gates=json.loads((HERE/'DATA_GATES.json').read_text()) if (HERE/'DATA_GATES.json').exists() else {}
    for s in scenarios():
        p=OUT/s['id']/'result.json'
        if p.exists():rows.append(json.loads(p.read_text()));continue
        r=dict(s,reason='')
        if s['group']=='Q_DATA_CONDITIONAL':
            gate=gates.get(s['overlay'],gates.get(s['stress'],{}))
            if gate.get('status') in ['NOT_RUN_DATA_GATE','BLOCKED_PERMISSION']:r.update(status=gate['status'],reason=gate['reason'])
        if s['group']=='I_FIVE_STRATEGY_CONDITIONAL' and gates.get('I',{}).get('status')=='BLOCKED_EXISTING_ACCOUNT_BASELINE':r.update(status='BLOCKED_INPUT',reason='BLOCKED_EXISTING_ACCOUNT_BASELINE: '+gates['I']['reason'])
        rows.append(r)
    dest=HERE/'scenario_summary.csv';temp=dest.with_name(dest.name+f'.tmp.{os.getpid()}');pd.DataFrame(rows).to_csv(temp,index=False);temp.replace(dest)
    counts=pd.Series([r['status'] for r in rows]).value_counts().to_dict();dump(HERE/'RUN_CHECKPOINT.json',dict(updated_at=time.time(),counts=counts,total_slots=296,core_slots=216))
    return counts


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--groups',default='A,B,C,D,E');ap.add_argument('--ids',default='');ap.add_argument('--repeat',action='store_true');args=ap.parse_args()
    assert (HERE/'CORE_FREEZE.json').exists(),'Freeze and test before account outcomes'
    m=Market();dump(HERE/'EXECUTION_INPUT_BINDING.json',m.execution_binding)
    frames={r:pd.read_parquet(OUT/f'{r}_signals.parquet') for r in [f'D{i:02d}' for i in range(10)]+['H01','H02']}
    frames.update(portfolio_frames(m,frames));desired=args.ids.split(',') if args.ids else []
    for s in scenarios():
        if desired and s['id'] not in desired:continue
        if not desired and s['group'].split('_')[0] not in args.groups.split(','):continue
        if s['group']=='I_FIVE_STRATEGY_CONDITIONAL':continue
        if s['group']=='Q_DATA_CONDITIONAL':
            if s['id'].startswith('Q5_'):
                f=frames['D02'].copy()
                # Arrow/Pandas respects case: industry is membership, Industry is the leader score.
                score=pd.read_parquet(OUT/'cache/N_candidates.parquet',columns=['t','j','Industry'])
                f=f.drop(columns=['Industry'],errors='ignore').merge(score,on=['t','j'],how='left',validate='one_to_one')
                f=f[f.Industry.notna()].copy()
                if s['arm']=='ENHANCED':f['score']=.8*f.score+.2*f.Industry
            else:continue
        else:f=frames[s['signal']].copy()
        if s['signal']!='P1_BALANCED':f=f.sort_values(['t','score','symbol'],ascending=[True,False,True]) if not s['signal'].startswith('P') else f
        sc=config(s);d=OUT/s['id'];d.mkdir(exist_ok=True);start=time.time()
        inputfile=d/'input_signals.parquet';parquet(inputfile,f);ident=identity(s,sha(inputfile));idpath=d/'identity.json';resultpath=d/'result.json'
        if not args.repeat and idpath.exists() and resultpath.exists():
            old=json.loads(idpath.read_text());row=json.loads(resultpath.read_text())
            if old.get('inputs')==ident and row['status'] in ['COMPLETED_NEW','NO_ELIGIBLE_SIGNAL'] and all(sha(d/n)==h for n,h in old['artifacts'].items()):
                print('RESUME_VERIFIED',s['id'],flush=True);continue
        row=dict(s,status='RUNNING',started_at=start,output=str(d))
        if not args.repeat:dump(resultpath,row);publish_summary()
        try:
            nav,trades,orders,audit,openpos,holds=replay(m,sc,f)
            artifacts={}
            for name,df in [('nav',nav),('trades',trades),('orders',orders),('audit',audit),('open_positions',openpos),('holdings',holds)]:
                dest=d/(name+('_repeat' if args.repeat else '')+'.parquet');parquet(dest,df);artifacts[dest.name]=sha(dest)
            # A prefix failure never publishes a completed account.
            assert len(nav)==sum(day>='2020-01-01' for day in m.dates)
            assert np.all(nav.cash>=-1e-7) and np.all(nav.market_value<=nav.nav+1e-7)
            row.update(metrics(nav,trades),**more_metrics(nav,trades,orders,holds),status='COMPLETED_NEW' if len(f) else 'NO_ELIGIBLE_SIGNAL',reason='',ended_at=time.time(),execution_grade='DAILY_OPEN_MODEL',signals=len(f))
            row={k:(None if isinstance(v,(float,np.floating)) and not np.isfinite(v) else v.item() if isinstance(v,np.generic) else v) for k,v in row.items()}
            if args.repeat:
                old=json.loads(idpath.read_text());checks={n.replace('_repeat',''):h==old['artifacts'].get(n.replace('_repeat','')) for n,h in artifacts.items()};dump(d/'repeat_checks.json',checks);assert all(checks.values()),checks
            else:dump(idpath,dict(inputs=ident,artifacts=artifacts));dump(resultpath,row)
        except ExecutionGap as e:
            row.update(status='BLOCKED_INPUT',reason=str(e),ended_at=time.time());dump(resultpath,row)
        except Exception as e:
            row.update(status='INVALIDATED_BY_BUG',reason=repr(e),ended_at=time.time());dump(resultpath,row);publish_summary();traceback.print_exc();raise
        print('ACCOUNT',s['id'],row['status'],round(time.time()-start,2),flush=True);publish_summary()
    print('COUNTS',publish_summary(),flush=True)

if __name__=='__main__':main()
