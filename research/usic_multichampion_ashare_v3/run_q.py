"""Run only the registered qualified Q3/Q4 paired accounts."""
import argparse,json,time,traceback
import numpy as np
import pandas as pd
from .common import HERE,OUT,sha,dump,parquet,scenarios
from .engine import replay as open_replay,ExecutionGap,metrics
from .tail_engine import replay as tail_replay
from .minute_market import MinuteMarket
from .run import config,more_metrics,publish_summary

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--ids',default='');ap.add_argument('--repeat',action='store_true');args=ap.parse_args()
    assert (HERE/'Q_FREEZE.json').exists();gates=json.loads((HERE/'DATA_GATES.json').read_text());assert gates['Q3']['status']=='PASS_PIT_B' and gates['Q4']['status']=='PASS_PIT_B'
    m=MinuteMarket();frames={p:pd.read_parquet(OUT/f'{p}_signals.parquet') for p in ['Q3','Q4_BASE','Q4_ENHANCED']};dump(HERE/'Q_EXECUTION_INPUT_BINDING.json',m.execution_binding)
    for s in scenarios():
        if not s['id'].startswith(('Q3_','Q4_')) or args.ids and s['id'] not in args.ids.split(','):continue
        isq3=s['overlay']=='Q3';tail=not (isq3 and s['arm']=='BASE');f=frames['Q3' if isq3 else 'Q4_'+s['arm']].sort_values(['t','score','symbol'],ascending=[True,False,True]).copy()
        sc=config(s);sc.update(delay=0 if tail else 1,fixed_holding=10 if isq3 else int(s['exit'][1:]),overlay='NONE');d=OUT/s['id'];d.mkdir(exist_ok=True);parquet(d/'input_signals.parquet',f)
        ident=dict(config=sc,engine={p:sha(HERE/p) for p in ['common.py','engine.py','tail_engine.py','minute_market.py','run_q.py','legacy_replay.py']},signals=sha(d/'input_signals.parquet'),minute_inputs=sha(HERE/'MINUTE_INPUT_MANIFEST.json'),minute_window=sha(HERE/'MINUTE_EXECUTION_MANIFEST.json'),actions=sha(HERE/'action_backfill.csv'),daily_inputs=sha(HERE/'INPUT_MANIFEST.json'))
        if not args.repeat and (d/'identity.json').exists() and (d/'result.json').exists():
            old=json.loads((d/'identity.json').read_text());row=json.loads((d/'result.json').read_text())
            if old['inputs']==ident and row['status'] in ['COMPLETED_NEW','NO_ELIGIBLE_SIGNAL'] and all(sha(d/p)==h for p,h in old['artifacts'].items()):print('RESUME_VERIFIED',s['id'],flush=True);continue
        row=dict(s,status='RUNNING',started_at=time.time(),output=str(d))
        if not args.repeat:dump(d/'result.json',row);publish_summary()
        try:
            nav,trades,orders,audit,op,hold=(tail_replay if tail else open_replay)(m,sc,f);artifacts={}
            assert len(nav)==sum(day>='2020-01-01' for day in m.dates)
            for name,df in [('nav',nav),('trades',trades),('orders',orders),('audit',audit),('open_positions',op),('holdings',hold)]:
                p=d/(name+('_repeat' if args.repeat else '')+'.parquet');parquet(p,df);artifacts[p.name]=sha(p)
            row.update(metrics(nav,trades),**more_metrics(nav,trades,orders,hold),status='COMPLETED_NEW' if len(f) else 'NO_ELIGIBLE_SIGNAL',reason='',ended_at=time.time(),execution_grade='MINUTE_OHLC_PROXY' if tail else 'MINUTE_SIGNAL_DAILY_OPEN_MODEL',signals=len(f))
            row={k:(None if isinstance(v,(float,np.floating)) and not np.isfinite(v) else v.item() if isinstance(v,np.generic) else v) for k,v in row.items()}
            if args.repeat:
                old=json.loads((d/'identity.json').read_text());checks={p.replace('_repeat',''):h==old['artifacts'].get(p.replace('_repeat','')) for p,h in artifacts.items()};dump(d/'repeat_checks.json',checks);assert all(checks.values())
            else:dump(d/'identity.json',dict(inputs=ident,artifacts=artifacts));dump(d/'result.json',row)
        except ExecutionGap as e:row.update(status='BLOCKED_INPUT',reason=str(e),ended_at=time.time());dump(d/'result.json',row)
        except Exception as e:row.update(status='INVALIDATED_BY_BUG',reason=repr(e),ended_at=time.time());dump(d/'result.json',row);publish_summary();raise
        print('Q_ACCOUNT',s['id'],row['status'],round(time.time()-row['started_at'],2),flush=True);publish_summary()
    print('Q_COUNTS',publish_summary(),flush=True)
if __name__=='__main__':main()
