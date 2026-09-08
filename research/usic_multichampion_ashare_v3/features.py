"""Bounded full-universe V3 event generation; per-symbol resumable shards, global ranks."""
import argparse, json, time
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb
from .common import HERE, OUT, CACHE, sha, dump, parquet, rank


def smooth(x, n, wilder=False):
    y=np.full(len(x),np.nan); count=0; total=0.; prev=np.nan
    alpha=1/n if wilder else 2/(n+1)
    for t,v in enumerate(x):
        if not np.isfinite(v):count=0;total=0.;prev=np.nan;continue
        count+=1
        if count<=n:
            total+=v
            if count==n:prev=total/n;y[t]=prev
        else:prev=alpha*v+(1-alpha)*prev;y[t]=prev
    return y


def path_values(c):
    if len(c)!=31 or not np.isfinite(c).all() or (c<=0).any():return np.nan,np.nan
    lr=np.diff(np.log(c));pos=lr[lr>0]
    if not len(pos):return np.nan,np.nan
    return float(np.mean(1-c[1:]/np.maximum.accumulate(c)[1:])),float(np.sort(pos)[-3:].sum()/pos.sum())


def avwap(amount,volume,cash,mult,valid):
    """Affine conversion of actual amount/shares to final-day share and price units."""
    if not np.all(valid) or not np.all(np.isfinite(amount+volume+cash+mult)) or np.any(mult<=0) or np.any(volume<=0):return np.nan
    numerator=0.;denominator=0.
    for i in range(len(amount)):
        if i:numerator-=denominator*cash[i];denominator*=mult[i]
        numerator+=amount[i];denominator+=volume[i]
    return numerator/denominator if denominator>0 and numerator>0 else np.nan


class Features:
    def __init__(self, end=None):
        self.ax=json.loads((CACHE/'axes.json').read_text());self.dates=self.ax['dates'];self.symbols=self.ax['symbols'];self.boards=self.ax['boards']
        self.n=len(self.dates) if end is None else end+1
        self.a={p.stem:np.load(p,mmap_mode='r')[:self.n] for p in CACHE.glob('*.npy')}
        self.market=pd.read_csv(CACHE/'market.csv').iloc[:self.n]
    def symbol(self,j):
        a=self.a;c=np.array(a['coord'][:,j]);factor=np.array(a['factor'][:,j]);h=a['high'][:,j]*factor;l=a['low'][:,j]*factor;o=a['open'][:,j]*factor
        good=(a['hard_valid'][:,j]==1)&(a['corporate_action_blocking'][:,j]==0)&(~(np.isfinite(a['rights_ratio'][:,j]) & (a['rights_ratio'][:,j]!=0)))&np.isfinite(c)&(c>0)
        c[~good]=np.nan;h[~good]=np.nan;l[~good]=np.nan
        prev=np.r_[np.nan,c[:-1]];tr=np.maximum(h-l,np.maximum(abs(h-prev),abs(l-prev)))
        e={n:smooth(c,n) for n in [9,10,20,21,50]};atr=smooth(tr,20,True)
        valid=np.isfinite(a['step'][:,j]);hist=pd.Series(valid.astype(int)).rolling(252).sum().to_numpy()==252
        amount20=pd.Series(a['amount'][:,j]).rolling(20).median().to_numpy()
        return dict(c=c,h=h,l=l,o=o,factor=factor,good=good,hist=hist,e=e,atr=atr,amount20=amount20)


def prepare_ranks(m):
    dest=OUT/'indicators';dest.mkdir(exist_ok=True)
    if (dest/'identity.json').exists():return
    n,z=m.a['coord'].shape
    for look in [20,60]:
        ret=np.full((n,z),np.nan)
        for j in range(z):
            if m.boards[j]=='UNSUPPORTED':continue
            c=m.a['coord'][:,j];v=np.isfinite(m.a['step'][:,j]);hist=pd.Series(v.astype(int)).rolling(252).sum().to_numpy()==252
            ret[look:,j]=c[look:]/c[:-look]-1
            ret[~(hist&(m.a['is_st'][:,j]==0)&(m.a['hard_valid'][:,j]==1)),j]=np.nan
        ranks=np.full_like(ret,np.nan)
        for b in ['MAIN','CHINEXT','STAR']:
            ids=np.where(np.array(m.boards)==b)[0]
            r=pd.DataFrame(ret[:,ids]).rank(axis=1,pct=True,method='average');count=np.isfinite(ret[:,ids]).sum(axis=1)
            r.loc[count==1]=r.loc[count==1].where(r.loc[count==1].isna(),.5)
            ranks[:,ids]=r.to_numpy()
        np.save(dest/f'rs{look}.npy',ranks)
        print('GLOBAL_RANK',look,n,z,flush=True)
    dump(dest/'identity.json',dict(input_hash=sha(HERE/'INPUT_MANIFEST.json'),source_hash=sha(Path(__file__)),shape=[n,z]))


def new_events(m,j,rs20,rs60,parents02,nrows):
    x=m.symbol(j);c,h,l,o,fac=[x[k] for k in ['c','h','l','o','factor']];e=x['e'];atr=x['atr'];a=m.a
    rows=[];episodes=[];parents=[];used={'D03':set(),'D05':set(),'D06':set()};sym=m.symbols[j]
    def emit(route,t,anchor,A,U,L,S0,score=None,**extra):
        row=dict(route=route,t=t,j=j,symbol=sym,board=m.boards[j],factor=fac[t],U=U/fac[t],limit=L/fac[t],S0=S0/fac[t],a0=A/fac[t],amount20=x['amount20'][t-1],industry=int(a['industry'][t-1,j]),score=score,RS60=float(rs60[t-1,j]),RS20=float(rs20[t-1,j]),formation_t=int(anchor),known_t=t-1,expiry_t=t+1,invalidated_t=-1,setup_id=f'{route}:{sym}:{anchor}',parent_id='',decision_at=m.dates[t]+'T15:00:00+08:00',known_at=m.dates[t-1]+'T15:00:00+08:00')
        row.update(extra);rows.append(row);return row
    def eligible(t):
        return t>=283 and x['hist'][t-31] and x['good'][t] and a['is_st'][t,j]==0 and np.all(x['good'][t-90:t+1]) and np.isfinite(rs20[t-1,j]) and np.isfinite(rs60[t-1,j])
    for t in range(283,m.n):
        if m.dates[t]<'2020-01-01' or not eligible(t):continue
        q=t-1;A=atr[t-21]
        if not np.isfinite(A) or A<=0:continue
        if rs60[q,j]>=.7:
            p=t-20+int(np.argmax(h[t-20:t-2]));P=h[p];depth=(P-np.min(l[p:t]))/A
            if p not in used['D03'] and e[9][q]>e[21][q]>e[50][q] and e[21][q]>e[21][q-5] and c[q]>e[50][q] and 1<=depth<=3 and c[q]<P and l[q]<=e[21][q]+.25*A and c[q]>=e[21][q]-.5*A and c[t]>h[q] and c[t]>e[9][t]:
                used['D03'].add(p);r=emit('D03',t,p,A,h[q],h[q]+.5*A,np.min(l[p:t+1])-.1*A,depth=depth)
                anchors=[b for b in range(t-60,p) if b>=20 and c[b]>np.max(h[b-20:b])]
                r['avwap_status']='NO_VALID_ANCHOR';r['avwap_anchor']=-1;r['avwap_value']=np.nan;r['avwap_pass']=False
                if anchors:
                    b=anchors[-1];sl=slice(b,t)
                    av=avwap(a['amount'][sl,j],a['volume'][sl,j],a['cash_per_share'][sl,j],a['share_multiplier'][sl,j],x['good'][sl])*fac[q]
                    r.update(avwap_status='COMPLETE' if np.isfinite(av) else 'MISSING_ACTION_BRIDGE',avwap_anchor=b,avwap_value=av/fac[q],avwap_pass=bool(np.isfinite(av) and abs(av-e[21][q])<=.5*A and c[q]>=av-.25*A))
                    if r['avwap_pass']:rows.append(dict(r,route='D04',setup_id=r['setup_id'].replace('D03:','D04:')))
            bs=[b for b in range(t-30,t-5) if b>=20 and c[b]>np.max(h[b-20:b])]
            if bs:
                b=bs[-1];B=np.max(h[b-20:b]);tight=abs(B-e[21][q])/A
                if b not in used['D05'] and e[21][q]>e[50][q] and e[21][q]>e[21][q-5] and c[q]>e[50][q] and tight<=.5 and abs(c[q]-B)<=.75*A and l[q]<=B+.25*A and c[t]>max(h[q],B,e[21][t]):
                    used['D05'].add(b);p1,p2=path_values(c[b-31:b]);r=emit('D05',t,b,A,B,max(B,e[21][q],h[q])+.5*A,np.min(l[t-5:t+1])-.1*A,tight=tight,P1=p1,P2=p2,path_status='COMPLETE' if np.isfinite(p2) else 'NO_POSITIVE_PATH_SUPPORT')
                    rows.append(dict(r,route='H02',setup_id=r['setup_id'].replace('D05:','H02:')))
        low=t-20+int(np.argmin(l[t-20:t-5]));U=np.max(h[t-5:t]);FL=np.min(l[t-5:t])
        if low not in used['D06'] and c[low]<e[20][low]-A and np.any(c[low+1:t-5]>=l[low]+A) and U-FL<=2*A and FL>=l[low] and abs(e[10][q]-e[20][q])<=.75*A and c[q]<=max(e[10][q],e[20][q])+.5*A and c[t]>max(U,e[10][t],e[20][t]):
            used['D06'].add(low);p=emit('D06',t,low,A,U,U+.5*A,FL-.1*A,score=float(rs20[q,j]),known_t=t,known_at=m.dates[t]+'T15:00:00+08:00');parents.append(p)
    for p in parents+parents02:
        b=int(p['t']);A=p['a0']*p['factor'];S=p['S0']*p['factor'];is_h=p['route']=='D02';route='H01' if is_h else 'D07';expiry=b+(15 if is_h else 20);extension=None;v=None;trigger=None;invalid=None;why='NO_EXTENSION'
        for t in range(b+1,min(m.n-1,expiry)+1):
            if not x['good'][t]:invalid=t;why='MISSING_REQUIRED_HISTORY';break
            if c[t]<S:invalid=t;why='STRUCTURE_INVALID';break
            if extension is None:
                if c[t]>=(c[b]+.5*A if is_h else e[20][t]+A):extension=t;why='NO_FIRST_RETEST'
                continue
            level=max(p['U']*p['factor'],e[21][t]) if is_h else e[20][t]
            if v is None and t>=b+2 and l[t]<=level+.25*A:v=t;why='RETEST_UNCONFIRMED'
            if v is not None:
                if t>v+5:why='CONFIRMATION_EXPIRED';break
                if c[t]>h[t-1] and c[t]>e[9 if is_h else 10][t] and eligible(t):
                    r=emit(route,t,b,A,h[t-1],h[t-1]+.5*A,np.min(l[v:t+1])-.1*A,score=(.5*p['score']+.5*rs60[t-1,j]) if is_h else float(rs20[t-1,j]),parent_id=p['setup_id'],formation_t=b,known_t=t,known_at=m.dates[t]+'T15:00:00+08:00',expiry_t=expiry,retest_t=v,extension_t=extension)
                    trigger=t;why='TRIGGERED';break
        episodes.append(dict(route=route,parent_id=p['setup_id'],symbol=sym,j=j,formation_t=b,expiry_t=expiry,extension_t=extension,retest_t=v,trigger_t=trigger,invalidated_t=invalid,status=why))
        if is_h:continue
        last_trigger=-1000
        for t in range(b+16,min(m.n,b+61)):
            if not np.all(x['good'][b+1:t+1]) or np.any(c[b+1:t+1]<S):break
            if t-last_trigger<10 or not eligible(t):continue
            q=t-1;U=np.max(h[t-10:t]);FL=np.min(l[t-10:t])
            if c[q]>e[10][q]>e[20][q] and e[20][q]>e[20][q-5] and np.max(c[b:t-10])>=c[b]+2*A and U-FL<=3*A and np.max(h[t-5:t])-np.min(l[t-5:t])<np.max(h[t-10:t-5])-np.min(l[t-10:t-5]) and c[q]>=np.max(h[t-30:t-10])-A and c[t]>U:
                emit('D08',t,b,A,U,U+.5*A,FL-.1*A,score=float(rs60[q,j]),parent_id=p['setup_id'],setup_id=f'D08:{sym}:{b}:{t}',expiry_t=b+60);last_trigger=t
    # All eligible consolidations, including those that never break out, enter the episode ledger.
    active=None
    for nr in nrows:
        t=int(nr['t'])
        if t>=m.n:break
        if not (nr['long'] and nr['VCP_GUARD']):continue
        if active is not None and t<=active['expiry_t']:continue
        A=nr['a0']*nr['factor'];U=nr['U']*nr['factor'];S=nr['S0']*nr['factor'];end=min(m.n-1,t+9)
        active=dict(route='D09_EPISODE',symbol=sym,j=j,formation_t=t-1,known_t=t-1,expiry_t=t+9,setup_id=f'D09:{sym}:{t-1}',advance_t=None,breakout_t=None,invalidated_t=None,U=U,S0=S,A=A)
        for s in range(t,end+1):
            if not x['good'][s]:active['invalidated_t']=s;active['status']='MISSING_HISTORY';break
            if c[s]<S:active['invalidated_t']=s;active['status']='STRUCTURE_INVALID';break
            if active['breakout_t'] is None and c[s]>U:active['breakout_t']=s
            if active['advance_t'] is None and U-.3*A<=c[s]<=U and c[s]>o[s] and l[s]>=S+.1*A and eligible(s):
                active['advance_t']=s
                emit('D09',s,t-1,A,U,U+.1*A,S,score=.5*nr['RS']+.25*nr['Path']+.25*nr['VCP'],setup_id=active['setup_id'],expiry_t=t+9,known_t=t-1,known_at=m.dates[t-1]+'T15:00:00+08:00')
        active.setdefault('status','OBSERVATION_COMPLETE' if end==t+9 else 'END_BOUNDARY');episodes.append(active)
    return rows,episodes


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,default=0);ap.add_argument('--stop',type=int);args=ap.parse_args()
    m=Features();prepare_ranks(m);rs20=np.load(OUT/'indicators/rs20.npy',mmap_mode='r');rs60=np.load(OUT/'indicators/rs60.npy',mmap_mode='r')
    cols=['t','j','symbol','board','factor','U','limit','S0','a0','amount20','industry','long','VCP_GUARD','RS','Path','VCP','breakout','Industry','retA','volatility','MAX','ret60','ret252','beta','V2','legs']
    con=duckdb.connect();con.execute('set threads=1');con.execute("set memory_limit='1GB'")
    inherited=con.execute('select '+','.join('"'+c+'"' for c in cols)+' from read_parquet(?) where long',[str(CACHE/'N_candidates.parquet')]).fetchdf()
    groups={int(j):g.sort_values('t') for j,g in inherited.groupby('j')};shards=OUT/'features';shards.mkdir(exist_ok=True)
    source_hash=sha(Path(__file__));start=time.time()
    for j in range(args.start,min(args.stop or len(m.symbols),len(m.symbols))):
        if m.boards[j]=='UNSUPPORTED':continue
        dest=shards/f'{j:05d}';dest.mkdir(exist_ok=True);ident=dest/'identity.json'
        if ident.exists() and json.loads(ident.read_text()).get('source_hash')==source_hash:continue
        nr=groups.get(j,pd.DataFrame());parents=[];oldrows=[]
        if len(nr):
            for r in nr[nr.breakout].to_dict('records'):
                for route in ['D00','D01','D02']:
                    if route!='D00' and not r['VCP_GUARD']:continue
                    row=dict(r,route=route,score=r['RS'] if route=='D00' else .5*r['RS']+.5*r['VCP'] if route=='D01' else .5*r['RS']+.25*r['Path']+.25*r['VCP'],formation_t=int(r['t'])-30,known_t=int(r['t'])-1,expiry_t=int(r['t'])+1,invalidated_t=-1,setup_id=f"{route}:{r['symbol']}:{r['t']}",parent_id='',decision_at=m.dates[int(r['t'])]+'T15:00:00+08:00',known_at=m.dates[int(r['t'])-1]+'T15:00:00+08:00')
                    oldrows.append(row)
                    if route=='D02':parents.append(row)
        rows,episodes=new_events(m,j,rs20,rs60,parents,nr.to_dict('records') if len(nr) else [])
        parquet(dest/'events.parquet',pd.DataFrame(oldrows+rows));parquet(dest/'episodes.parquet',pd.DataFrame(episodes));dump(ident,dict(source_hash=source_hash,j=j,rows=len(oldrows)+len(rows),episodes=len(episodes)))
        if j%100==0:print('SYMBOLS',j,len(m.symbols),'seconds',round(time.time()-start),flush=True)
    if args.start==0 and args.stop is None:merge(m)


def merge(m):
    files=sorted((OUT/'features').glob('*/events.parquet'));frames=[pd.read_parquet(p) for p in files];f=pd.concat([x for x in frames if len(x)],ignore_index=True);del frames
    for route,field in [('D03','depth'),('D05','tight')]:
        mask=f.route==route;part=f.loc[mask];scores=.5*part.RS60+.5*part.groupby('t')[field].transform(lambda x:rank(x,True));f.loc[mask,'score']=scores
        if route=='D03':
            scoremap=dict(zip(part.setup_id,scores));mask4=f.route=='D04';f.loc[mask4,'score']=[scoremap[s.replace('D04:','D03:')] for s in f.loc[mask4,'setup_id']]
        else:
            part=f.loc[mask];g=part.groupby(['t','board']);path=(g.P1.transform(lambda x:rank(x,True))+g.P2.transform(lambda x:rank(x,True)))/2;path=path.fillna(.5)
            scoremap=dict(zip(part.setup_id,.5*part.score+.5*path));maskh=f.route=='H02';f.loc[maskh,'score']=[scoremap[s.replace('H02:','D05:')] for s in f.loc[maskh,'setup_id']]
    # Capacity always comes from the full prior 20 sessions, independent of entry delay.
    for j,ix in f.groupby('j').groups.items():
        med=pd.Series(m.a['amount'][:,int(j)]).rolling(20).median().to_numpy();ts=f.loc[ix,'t'].astype(int).to_numpy();f.loc[ix,'amount20']=med[ts-1]
    f=f.sort_values(['t','route','j','formation_t','parent_id','setup_id'])
    f['duplicate_parent_same_day']=f.duplicated(['t','route','j'])
    parquet(OUT/'all_signals_before_dedup.parquet',f)
    f=f[~f.duplicate_parent_same_day].copy();assert f.score.notna().all()
    for route,part in f.groupby('route'):parquet(OUT/f'{route}_signals.parquet',part)
    for route in [f'D{i:02d}' for i in range(10)]+['H01','H02']:
        if not (OUT/f'{route}_signals.parquet').exists():parquet(OUT/f'{route}_signals.parquet',f.iloc[:0])
    f.groupby(['route','t']).size().rename('signals').reset_index().to_csv(HERE/'signal_counts.csv',index=False)
    ep=[pd.read_parquet(p) for p in sorted((OUT/'features').glob('*/episodes.parquet'))];parquet(OUT/'episodes.parquet',pd.concat([p for p in ep if len(p)],ignore_index=True))
    dump(HERE/'FEATURE_MANIFEST.json',dict(source_hash=sha(Path(__file__)),input_hash=sha(HERE/'INPUT_MANIFEST.json'),counts=f.groupby('route').size().to_dict(),symbols_scanned=len(files),universe_symbols=len(m.symbols),dates=[m.dates[0],m.dates[-1]],files=[dict(path=str(p),sha256=sha(p)) for p in sorted(OUT.glob('*_signals.parquet'))]))
    print('FEATURE_COMPLETE',f.groupby('route').size().to_dict(),flush=True)

if __name__=='__main__':main()
