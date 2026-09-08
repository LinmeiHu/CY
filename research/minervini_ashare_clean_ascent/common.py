from pathlib import Path
import hashlib,json,datetime
import numpy as np
import pandas as pd
HERE=Path(__file__).resolve().parent
OUT=Path('/Volumes/quant/CY_quant_research/minervini_ashare_clean_ascent_v2')
INV=Path('/Users/linmei/Documents/CY/data/input_inventories')

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()
def dump(p,x):
    Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2,default=str)+'\n')
def scenarios():
    rows=[]
    def add(group,v,mode,a=30,w=30,cost=1,delay=1,exit='FIXED10',module=''):
        x=dict(group=group,version=v,mode=mode,a=a,w=w,cost=cost,delay=delay,exit=exit,module=module)
        x['id']='_'.join(map(str,[group,v,mode]+([a,w] if group=='OLD_NEIGHBOR' else [])))
        x['config_hash']=hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest();rows.append(x)
    modes=['MAX_DEPLOYABLE','CAP10']
    for v in ['B0','P','C','PC']:
        for m in modes:add('OLD_MAIN',v,m,w=5)
    for g in ['OLD_COST','OLD_DELAY']:
        for v in ['B0','PC']:
            for m in modes:add(g,v,m,w=5,cost=2 if g=='OLD_COST' else 1,delay=2 if g=='OLD_DELAY' else 1)
    for a,w in [(20,3),(40,8)]:
        for v in ['B0','PC']:add('OLD_NEIGHBOR',v,'CAP10',a=a,w=w)
    for n in range(10):
        for m in modes:add('N_MAIN',f'N{n}',m)
    for g in ['N_COST','N_DELAY','N_EXIT']:
        for v in ['N1','N4','N9']:
            for m in modes:add(g,v,m,cost=2 if g=='N_COST' else 1,delay=2 if g=='N_DELAY' else 1,exit='TREND40' if g=='N_EXIT' else 'FIXED10')
    for mod in ['INDUSTRY','CATALYST','FUNDAMENTALS']:
        for v in ['N4_MATCH','N4_PLUS']:
            for m in modes:add(mod,v,m,module=mod)
    assert len(rows)==70
    return rows

def pivots(h,l,volume=None):
    """As-of W only, including confirmation lag; result retains all chosen legs."""
    seq=[]; ambiguous=[]
    for k in range(2,len(h)-2):
        hi=np.argmax(h[k-2:k+3])==2;lo=np.argmin(l[k-2:k+3])==2
        if hi and lo:ambiguous.append(k);continue
        if not hi and not lo:continue
        typ='H' if hi else 'L';v=h[k] if hi else l[k]
        p=(typ,k,k+2,float(v))
        if seq and seq[-1][0]==typ:
            if (typ=='H' and v>seq[-1][3]) or (typ=='L' and v<seq[-1][3]):seq[-1]=p
        else:seq.append(p)
    legs=[dict(high=s[1],low=t[1],high_confirm=s[2],low_confirm=t[2],depth=(s[3]-t[3])/s[3]) for s,t in zip(seq,seq[1:]) if s[0]=='H' and t[0]=='L'][-3:]
    reason='PASS'
    lows=[p for p in seq if p[0]=='L']
    if len(legs)<2:reason='LESS_THAN_TWO_LEGS'
    elif any(p['depth']<=0 for p in legs):reason='NONPOSITIVE_DEPTH'
    elif any(a['depth']<=b['depth'] for a,b in zip(legs,legs[1:])):reason='NOT_CONTRACTING'
    elif lows and np.any(l[lows[-1][1]+1:]<lows[-1][3]):reason='UNCONFIRMED_LOWER_LOW'
    elif np.any(h[-5:]<=l[-5:]) or (volume is not None and np.any(volume[-5:]<=0)):reason='F_INACTIVE_OR_SINGLE_PRICE'
    return reason,legs,ambiguous

def rank(s,low=False):
    r=s.rank(pct=True,ascending=not low,method='average')
    if s.notna().sum()==1:r[s.notna()]=.5
    return r

def fee(value,day,sell=False,mult=1):
    transfer=.00002 if str(day)[:10]<'2022-04-29' else .00001
    stamp=(.001 if str(day)[:10]<'2023-08-28' else .0005) if sell else 0
    return mult*(max(5.,value*.0003)+value*(transfer+stamp))
def quantity(budget,limit,day,board,mult=1):
    unit=1 if board=='STAR' else 100;minimum=200 if board=='STAR' else 100
    q=min(int(budget/limit)//unit*unit,100000 if board=='STAR' else 1000000)
    while q>=minimum and q*limit+fee(q*limit,day,mult=mult)>budget:q-=unit
    return q if q>=minimum else 0
