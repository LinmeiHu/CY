"""Discovery-bounded chart packets. Selection labels never enter blind payloads."""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
import duckdb
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
sys.path.insert(0, str(PARENT))
from state_v2 import read_bound, BASE, EXTRA

C = json.loads((HERE/'visual_contract.json').read_text())
PC = json.loads((PARENT/'research_contract.json').read_text())
CFG = json.loads((PARENT/'input_config.json').read_text())
OLD = Path(CFG['external_root'])
OUT = Path(C['external_root'])
ROUTES = ['ATRDR_BULL','ATRDR_FAST_BEAR','ATRDR_SLOW_BEAR','MCB','OGR','SMV6']
SAFE = ['age','open','high','low','close','current_pnl','mae_sofar','mfe_sofar','giveback',
        'anchor','target','volume_entry','volume_prior5','relative_strength','critical_change']

def digest(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def token(s):
    return hashlib.sha256(('visual-v1-1729|'+str(s)).encode()).hexdigest()

def write_json(p, x):
    Path(p).write_text(json.dumps(x, indent=2, ensure_ascii=False, default=str)+'\n')

def log(action, **kwargs):
    with (HERE/'visual_stage_audit.jsonl').open('a') as f:
        f.write(json.dumps(dict(time=datetime.now().astimezone().isoformat(), action=action, **kwargs))+'\n')

def discovery_states():
    sql = """route <> 'IFCGR' AND entry_date >= CASE WHEN route IN ('OGR','SMV6') THEN DATE '2018-01-01' ELSE DATE '2014-01-01' END
      AND label_available_at < CASE WHEN route IN ('OGR','SMV6') THEN DATE '2022-01-01' ELSE DATE '2021-01-01' END
      AND label_status='MATURE' AND state_valid AND data_available_at<=decision_at"""
    return pd.concat([read_bound(OLD/(n+'.parquet'),sql) for n in
                      ['position_state_snapshots','SMV6_position_state_snapshots']],ignore_index=True)

def select_pairs(states):
    rows=[]; audits=[]; used=set(); used_clusters=set()
    for route in ROUTES:
        d=states.loc[states.route.eq(route)&states.age.between(3,8)&states.current_pnl.between(-.10,-.005)].copy()
        for excluded in C['matching']['exclusions']:
            d=d.loc[~d.episode_id.str.contains(excluded,regex=False)]
        d=d.dropna(subset=['current_pnl','mae_sofar','atr_entry_frac'])
        got=0
        for level in ['PRIMARY','FALLBACK']:
            good=.05 if level=='PRIMARY' and route!='SMV6' else .02
            bad=-.10 if level=='PRIMARY' and route!='SMV6' else -.02
            a=d.loc[d.native_net_return.ge(good)]; b=d.loc[d.native_net_return.le(bad)]
            pairs=[]
            for i,x in a.iterrows():
                diff=(b[['age','current_pnl','mae_sofar','atr_entry_frac']]-x[['age','current_pnl','mae_sofar','atr_entry_frac']]).astype(float).abs()
                delta=diff.div([1,.015,.02,.01])
                for j,v in delta.loc[delta.le(1).all(axis=1)].iterrows():
                    if b.loc[j,'event_cluster']==x.event_cluster: continue
                    pairs.append((float((v*v).sum()),token(f'{i}|{j}'),i,j))
            for distance,_,i,j in sorted(pairs):
                x,y=d.loc[i],d.loc[j]
                if got>=2:break
                if x.episode_id in used or y.episode_id in used or x.event_cluster in used_clusters or y.event_cluster in used_clusters:continue
                got+=1;pair=f'{route}_PAIR_{got}'
                for z in [x,y]:
                    case='CASE_'+str(int(token(z.episode_id+'|'+str(z.decision_at))[:12],16)%100000).zfill(5)
                    rows.append(dict(z,case_id=case,pair_id=pair,match_tier=level,match_distance=distance))
                    used.add(z.episode_id);used_clusters.add(z.event_cluster)
                audits.append(dict(route=route,pair_id=pair,tier=level,distance=distance,
                    age_difference=abs(x.age-y.age),return_difference=abs(x.current_pnl-y.current_pnl),
                    mae_difference=abs(x.mae_sofar-y.mae_sofar),atr_difference=abs(x.atr_entry_frac-y.atr_entry_frac)))
        audits.append(dict(route=route,pair_id='QUOTA',tier='FILLED' if got==2 else 'SHORTAGE',selected_pairs=got,eligible_states=len(d),eligible_events=d.episode_id.nunique()))
    result=pd.DataFrame(rows)
    assert result.case_id.is_unique and result.episode_id.is_unique
    return result.sort_values(['route','pair_id','case_id']),pd.DataFrame(audits)

def source_for(ids):
    bound="route<>'IFCGR' AND entry_date>=CASE WHEN route='OGR' THEN DATE '2018-01-01' ELSE DATE '2014-01-01' END AND native_time < CASE WHEN route='OGR' THEN DATE '2022-01-01' ELSE DATE '2021-01-01' END"
    d=read_bound(OLD/'all_source_normalized.parquet',bound)
    return d.loc[d.episode_id.isin(ids)].drop_duplicates('episode_id').set_index('episode_id')

def stock_path(e, through):
    # Bound before fetch; final native-exit-day OHLC cannot be used after an open exit.
    eid=e.episode_id.replace("'","''")
    p=read_bound(OLD/'candidate_position_paths.parquet',
        f"episode_id='{eid}' AND trade_date<=TIMESTAMP '{pd.Timestamp(through)}'")
    p=p.sort_values('age')
    close_at=pd.to_datetime(p.trade_date)+pd.Timedelta(hours=16)
    p=p.loc[(close_at<=pd.Timestamp(through))&(close_at<pd.Timestamp(e.native_time))].copy()
    if p.empty:return p
    price=float(e.entry_price)
    for col in ['open','high','low','close']:
        p[col]=p['coord_'+col]/price
        p.loc[~p.state_valid,col]=np.nan
    p['anchor']=float(e.anchor)/price if pd.notna(e.anchor_available_at) and e.anchor_available_at<=e.entry_time else np.nan
    p['target']=1.15 if e.route in ['ATRDR_BULL','MCB'] else 1.10
    if e.route=='OGR':p['target']=float(e.target_coordinate)/float(e.entry_coordinate_price)
    p['volume_entry']=p.volume/p.volume.iloc[0] if p.volume.iloc[0]>0 else np.nan
    p['volume_prior5']=p.volume/p.volume.shift(1).rolling(5,min_periods=3).mean()
    p.loc[~p.state_valid,['volume_entry','volume_prior5','current_pnl','mae_sofar','mfe_sofar','giveback']]=np.nan
    p['relative_strength']=np.nan;p['critical_change']=np.nan
    return p

def smv_source(ids):
    q="entry_date BETWEEN DATE '2018-01-01' AND DATE '2021-12-31' AND native_time<DATE '2022-01-01'"
    con=duckdb.connect()
    r=con.execute(f'SELECT * FROM read_csv_auto(?) WHERE {q}',[str(PARENT/'smv6_residual_loss.csv')]).fetchdf();con.close()
    r=r.loc[r.episode_id.isin(ids)].copy()
    inv=read_bound(OLD/'SMV6_inventory.parquet',"entry_date>=DATE '2018-01-01' AND trade_date<DATE '2022-01-01'",'symbol,entry_date,entry_price,trade_date')
    first=inv.sort_values('trade_date').drop_duplicates(['symbol','entry_date'])
    r=r.merge(first[['symbol','entry_date','entry_price']],on=['symbol','entry_date'],validate='one_to_one')
    r['route']='SMV6';r['entry_time']=pd.to_datetime(r.entry_date)+pd.Timedelta(hours=9,minutes=30)
    return r.set_index('episode_id')

def smv_path(e, through):
    inp=CFG['inputs']; root=Path(inp['smv6_qmt_root']);hy=Path(inp['smv6_hybrid_root'])
    end=min(pd.Timestamp(through).normalize(),pd.Timestamp('2021-12-31'))
    bound=f"trade_date<=DATE '{end.date()}'"
    d=read_bound(root/'daily'/f'symbol={e.symbol}'/'daily.parquet',bound).sort_values('trade_date')
    d.loc[~d.row_status.eq('VALID'),['pre_adj_open','pre_adj_high','pre_adj_low','pre_adj_close','volume_raw']]=np.nan
    d['ma40']=d.pre_adj_close.rolling(40,min_periods=40).mean()
    p=d.loc[d.trade_date.ge(e.entry_date)&(d.trade_date+pd.Timedelta(hours=16)).le(pd.Timestamp(through))].copy()
    p['age']=np.arange(len(p));price=float(e.entry_price)
    for col in ['open','high','low','close']:p[col]=p['pre_adj_'+col]/price
    p['current_pnl']=p.close-1;p['mae_sofar']=(p.low-1).cummin();p['mfe_sofar']=(p.high-1).cummax();p['giveback']=p.mfe_sofar-p.current_pnl
    p['anchor']=p.ma40/price;p['target']=np.nan
    p['volume_entry']=p.volume_raw/p.volume_raw.iloc[0] if len(p) and p.volume_raw.iloc[0]>0 else np.nan
    p['volume_prior5']=p.volume_raw/p.volume_raw.shift(1).rolling(5,min_periods=3).mean()
    b=read_bound(root/'daily/symbol=000852.SH/daily.parquet',f"trade_date BETWEEN DATE '{pd.Timestamp(e.entry_date).date()}' AND DATE '{end.date()}'").sort_values('trade_date')
    b.loc[~b.row_status.eq('VALID'),['pre_adj_open','pre_adj_close']]=np.nan
    p=p.merge(b[['trade_date','pre_adj_close']].rename(columns={'pre_adj_close':'benchmark_close'}),on='trade_date',validate='one_to_one')
    p['relative_strength']=p.close/(p.benchmark_close/float(b.pre_adj_open.iloc[0]))-1
    m=read_bound(hy/'minute_critical'/f'symbol={e.symbol}'/'critical.parquet',f"trade_date BETWEEN DATE '{pd.Timestamp(e.entry_date).date()}' AND DATE '{end.date()}'")
    # Named source roles, never choose a convenient timestamp based on returns.
    available=pd.to_datetime(m.available_at,utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    valid=m.row_status.eq('VALID')&available.le(pd.to_datetime(m.trade_date)+pd.Timedelta(hours=16))
    m.loc[~valid,['pre_adj_open','pre_adj_close']]=np.nan
    closes=m.pivot(index='trade_date',columns='bar_role',values='pre_adj_close')
    opens=m.pivot(index='trade_date',columns='bar_role',values='pre_adj_open')
    if 'FINAL_CLOSE_BAR' in closes and 'PSEUDO_CLOSE_14_57_OPEN' in opens:
        p['critical_change']=p.trade_date.map(closes.FINAL_CLOSE_BAR/opens.PSEUDO_CLOSE_14_57_OPEN-1)
    else:p['critical_change']=np.nan
    return p

def payload(p, case, obs):
    q=p.loc[p.age.le(obs),SAFE].copy()
    assert len(q) and q.age.max()<=obs
    return dict(case_id=case,observation_age=int(obs),path=json.loads(q.to_json(orient='records')))

def draw(cases, variant, dest, post=False):
    plt.rcParams.update({'font.size':8,'axes.spines.top':False,'axes.spines.right':False})
    n=len(cases);fig,axes=plt.subplots(5,n,figsize=(4.2*n,11),squeeze=False,sharex='col')
    price_lim=(.4,1.6) if post else (.84,1.16);exc_lim=(-.6,.6) if post else (-.2,.2)
    for j,case in enumerate(cases):
        p=pd.DataFrame(case['path']);x=p.age.to_numpy();a=axes[:,j]
        a[0].vlines(x,p.low,p.high,color='#b2bec3',lw=2)
        a[0].plot(x,p.close,'o-',ms=3,color='#126782',label='close')
        a[0].scatter([0],[1],marker='>',color='black',s=30,label='entry')
        if variant=='full' or post:
            a[0].plot(x,p.anchor,'--',color='#b5651d',label='anchor')
            if p.target.notna().any():a[0].plot(x,p.target,':',color='#6a4c93',label='entry-known target')
            a[0].axvline(1,color='#777777',ls=':',lw=.8,label='next-session eligibility')
        a[0].axhline(1,color='black',lw=.6);a[0].set_ylim(price_lim)
        a[0].set_title(case['case_id']+' | age '+str(case['observation_age']))
        for col,color,label in [('current_pnl','#126782','return'),('mae_sofar','#d1495b','MAE so far'),('mfe_sofar','#2a9d8f','MFE so far'),('giveback','#e9a23b','giveback')]:
            a[1].plot(x,p[col],color=color,label=label)
        a[1].set_ylim(exc_lim);a[1].axhline(0,color='black',lw=.6)
        if variant in ['price_volume','full'] or post:
            a[2].bar(x,p.volume_entry,color='#cad2c5',label='volume / entry day')
            a[2].plot(x,p.volume_prior5,'o-',ms=2,color='#52796f',label='volume / prior5')
        else:a[2].text(.5,.5,'VOLUME MASKED',ha='center',transform=a[2].transAxes)
        a[2].set_ylim(0,5);a[2].axhline(1,color='#777',lw=.5)
        if (variant in ['price_rs','full'] or post) and p.relative_strength.notna().any():
            a[3].plot(x,p.relative_strength,color='#6a4c93',label='relative to frozen CSI1000')
        else:a[3].text(.5,.5,'RS MASKED / UNAVAILABLE',ha='center',transform=a[3].transAxes)
        a[3].set_ylim(-.3,.3);a[3].axhline(0,color='#777',lw=.5)
        if (variant=='full' or post) and p.critical_change.notna().any():
            a[4].plot(x,p.critical_change,'o-',ms=2,color='#9c6644',label='final close / 14:57 pseudo-open - 1')
        else:a[4].text(.5,.5,'MINUTE SUMMARY MASKED / UNAVAILABLE',ha='center',fontsize=7,transform=a[4].transAxes)
        a[4].set_ylim(-.03,.03)
        if post:
            ex=case['native_exit_age'];ep=case['native_exit_price']
            a[0].scatter([ex],[ep],marker='x',color='#d1495b',zorder=10,label='native exit')
            a[0].plot([x[-1],ex],[p.close.iloc[-1],ep],color='#d1495b',ls=':')
            a[0].set_title(case['case_id']+'\n'+case['category']+'\nnet '+f"{case['native_return']:+.1%}",fontsize=8)
            ins=a[0].inset_axes([.48,.04,.49,.31]);ins.plot(x,p.close,color='#126782',lw=1);ins.set_xlim(0,20);ins.set_ylim(.4,1.6);ins.set_xticks([0,10,20]);ins.set_yticks([]);ins.tick_params(labelsize=5);ins.set_title('same 0..20 zoom',fontsize=5)
        else:
            for z in a:z.axvspan(case['observation_age']+.05,9,color='#eeeeee',alpha=.7)
        for k,z in enumerate(a):
            z.set_xlim(0,160 if post else 9);z.grid(alpha=.15)
            if j==0:z.set_ylabel(['A  price / entry','B  path excursions','C  relative volume','D  relative strength','E  critical bars'][k])
            handles,labels=z.get_legend_handles_labels()
            if handles:z.legend(loc='upper left',fontsize=5.8,framealpha=.6)
        a[4].set_xlabel('observed holding session')
    fig.suptitle(('FULL-PATH-POSTMORTEM | DISCOVERY ONLY' if post else 'DECISION-TIME SNAPSHOT | anonymous prefix | '+variant)+'\n'+cases[0]['route']+' | fixed axes; clipped values remain in manifest',fontsize=12)
    fig.tight_layout(rect=[0,0,1,.95]);fig.savefig(dest,dpi=150);plt.close(fig)

def prepare():
    if (OUT/'blind_payload.json').exists():raise RuntimeError('Preparation already frozen; do not replace blind cases')
    OUT.mkdir(parents=True,exist_ok=True)
    for x in ['blind','postmortem','private']: (OUT/x).mkdir(exist_ok=True)
    log('PREREGISTERED_BEFORE_SELECTION',contract_sha256=digest(HERE/'visual_contract.json'))
    states=discovery_states();selected,match=select_pairs(states)
    selected.to_parquet(OUT/'private/selected_states.parquet',index=False)
    match.to_csv(HERE/'visual_matching_audit.csv',index=False)
    sources=source_for(selected.episode_id);smv=smv_source(selected.episode_id)
    packets=[];manifest=[];audit=[]
    for r in selected.itertuples(index=False):
        e=(smv if r.route=='SMV6' else sources).loc[r.episode_id].copy();e['episode_id']=r.episode_id
        p=smv_path(e,r.decision_at) if r.route=='SMV6' else stock_path(e,r.decision_at)
        data=payload(p,r.case_id,r.age);data.update(route=r.route,pair_id=r.pair_id)
        packets.append(data)
        manifest.append(dict(route=r.route,period='DISCOVERY',case_id=r.case_id,pair_id=r.pair_id,observation_age=r.age,
            chart_type='DECISION_TIME_BLIND_SNAPSHOT',labels_visible=False,future_path_visible=False,
            payload_fields='|'.join(SAFE),price_clipped_points=int((p.low.lt(.84)|p.high.gt(1.16)).sum()),
            volume_clipped_points=int((p.volume_entry.gt(5)|p.volume_prior5.gt(5)).sum()),
            rs_available=bool(p.relative_strength.notna().any()),minute_available=bool(p.critical_change.notna().any()),
            blinding='CONDITIONAL_ON_PRIOR_RESULT_EXPOSURE',selection='MATCHED_FUTURE_CONTRAST_NOT_PREVALENCE'))
        audit.append(dict(case_id=r.case_id,source_episode=r.episode_id,decision_at=r.decision_at,max_data_date=p.trade_date.max(),
                          latest_chart_available_at=p.trade_date.max()+pd.Timedelta(hours=16),native_time=r.native_time,
                          source_path_hash=hashlib.sha256(p.to_json().encode()).hexdigest()))
    write_json(OUT/'blind_payload.json',packets)
    pd.DataFrame(manifest).to_csv(HERE/'visual_case_manifest.csv',index=False)
    pd.DataFrame(audit).to_parquet(OUT/'private/prefix_audit.parquet',index=False)
    exp=[]
    for route in ROUTES:
        if route=='SMV6':continue
        for period in ['DISCOVERY','TEMPORAL_EVALUATION']:
            exp.append(dict(route=route,period=period,case_ids='AGGREGATE_ONLY',chart_type='PRIOR_FIXED_STOP_RESPONSE',outcome_labels_visible=True,future_path_visible=False,viewed_before_hypothesis_freeze=True,purpose='PRIOR_V2_RESULTS',exposure_status='RESULT_EXPOSED',image_path=str(PARENT/'figures/fixed_stop_response.png')))
    exp.extend([dict(route='MCB',period='TEMPORAL_EVALUATION',case_ids='ACCOUNT_AGGREGATE',chart_type='PRIOR_ACCOUNT_NAV',outcome_labels_visible=True,future_path_visible=True,viewed_before_hypothesis_freeze=True,purpose='PRIOR_V2_RESULTS',exposure_status='RESULT_EXPOSED',image_path=str(PARENT/'figures/mcb_policy_nav_drawdown.png')),
      dict(route='MCB',period='DISCOVERY',case_ids='|'.join(C['matching']['exclusions']),chart_type='PRIOR_FULL_PATH_POSTMORTEM',outcome_labels_visible=True,future_path_visible=True,viewed_before_hypothesis_freeze=True,purpose='PRIOR_V2_FAILURE_ANATOMY_EXCLUDED_FROM_BLIND_POOL',exposure_status='RESULT_EXPOSED',image_path=str(PARENT/'figures/mcb_opposing_paths.png'))])
    for route in ROUTES:
        exp.append(dict(route=route,period='DISCOVERY_AND_TEMPORAL_EVALUATION',case_ids='AGGREGATE_TABLES_AND_PRIOR_CONTEXT',chart_type='PRIOR_NONVISUAL_RESULTS',outcome_labels_visible=True,future_path_visible=False,viewed_before_hypothesis_freeze=True,purpose='EXPOSURE_CONTEXT_NOT_A_NEW_IMAGE_VIEW',exposure_status='RESULT_EXPOSED'))
    pd.DataFrame(exp).to_csv(HERE/'visual_exposure_manifest.csv',index=False)
    log('BLIND_PAYLOAD_SEALED',sha256=digest(OUT/'blind_payload.json'),cases=len(packets))
    print(json.dumps({'anonymous_cases':len(packets),'routes':pd.DataFrame(manifest).groupby('route').size().to_dict(),'output':str(OUT)}))

def render():
    packets=json.loads((OUT/'blind_payload.json').read_text())
    for route in ROUTES:
        cases=[x for x in packets if x['route']==route]
        if not cases:continue
        for v in ['price_only','price_volume','price_rs','full']:
            draw(cases,v,OUT/'blind'/f'{route}_{v}.png')
    log('BLIND_CHARTS_RENDERED',payload_sha256=digest(OUT/'blind_payload.json'))
    print('Rendered standardized anonymous packets; no outcomes printed.')

def mark_view(route,variant):
    packets=json.loads((OUT/'blind_payload.json').read_text());ids=[x['case_id'] for x in packets if x['route']==route]
    p=OUT/'blind'/f'{route}_{variant}.png'
    r=dict(route=route,period='DISCOVERY',case_ids='|'.join(ids),chart_type='DECISION_TIME_BLIND_SNAPSHOT_'+variant.upper(),
           outcome_labels_visible=False,future_path_visible=False,viewed_before_hypothesis_freeze=not (HERE/'visual_hypothesis_freeze.json').exists(),
           purpose='ACTUAL_ASTRA_IMAGE_INSPECTION_BEFORE_REVEAL',exposure_status='CASE_BLINDED_CONDITIONAL_ON_PRIOR_EXPOSURE',image_path=str(p),
           image_sha256=digest(p),viewed_at=datetime.now().astimezone().isoformat())
    prev=pd.read_csv(HERE/'visual_exposure_manifest.csv');pd.concat([prev,pd.DataFrame([r])],ignore_index=True).to_csv(HERE/'visual_exposure_manifest.csv',index=False)

def reveal():
    if (HERE/'visual_outcome_reveal.csv').exists():raise RuntimeError('Outcomes already revealed')
    obs=HERE/'visual_blind_observations.csv'
    if not obs.exists():raise RuntimeError('Persist actual blind observations before reveal')
    d=pd.read_parquet(OUT/'private/selected_states.parquet')
    o=pd.read_csv(obs)
    assert set(o.case_id)==set(d.case_id)
    assert set(o.variant)>= {'price_only','price_volume','full'}
    log('BLIND_OBSERVATIONS_SEALED_BEFORE_REVEAL',sha256=digest(obs))
    cols=['route','case_id','pair_id','episode_id','symbol','entry_date','decision_at','age','current_pnl','mae_sofar','atr_entry_frac','native_time','native_net_return','exit_advantage_normalized','match_tier']
    d[cols].to_csv(HERE/'visual_outcome_reveal.csv',index=False)
    log('DISCOVERY_CASE_OUTCOMES_REVEALED',sha256=digest(HERE/'visual_outcome_reveal.csv'))
    print(d[['route','case_id','pair_id','native_net_return','exit_advantage_normalized']].to_string(index=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','render','reveal','mark-view']);parser.add_argument('--route');parser.add_argument('--variant');a=parser.parse_args()
    if a.action=='mark-view':mark_view(a.route,a.variant)
    else:globals()[a.action]()
