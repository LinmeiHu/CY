"""Reuse admitted daily partitions; coherent coordinates, stock-chunked feature windows."""
import sys
import pandas as pd
import duckdb
from common import *

def mem(name,shape,dtype='float64',fill=np.nan):
    a=np.lib.format.open_memmap(PANEL/(name+'.npy'),mode='w+',shape=shape,dtype=dtype);a[:]=fill;return a

def panel():
    assert json.loads((HERE/'TIME_SPLIT.json').read_text())['role_change']['to']=='SUPERVISED_TRAINING_RESERVE'
    assert json.loads((HERE/'DAILY_BUILD_AUDIT.json').read_text())['gate_pass']
    files=sorted(Path('/Volumes/quant/CY_quant_research/ashare_path_autonomous_v4/early_daily/daily').glob('partition_year=*/*.parquet'))
    files+=sorted((OUT/'middle_daily/daily').glob('partition_year=*/*.parquet'))
    late=json.loads((HERE.parent/'ashare_wave_structure_v1/INPUT_MANIFEST.json').read_text())
    for b in late['source_bindings']:
        if any(f'partition_year={y}' in b['path'] for y in range(2018,2024)):
            assert sha(b['path'])==b['sha256'];files.append(Path(b['path']))
    assert len(files)==17,files
    db=duckdb.connect();db.execute('SET threads=2');fs=[str(p) for p in files]
    dates=db.execute('select distinct trade_date from read_parquet(?) order by 1',[fs]).df().trade_date.dt.strftime('%Y-%m-%d').tolist()
    symbols=db.execute("select distinct symbol from read_parquet(?) where regexp_matches(symbol,'^(60|68|00|30)[0-9]{4}\\.(SH|SZ)$') order by 1",[fs]).df().symbol.tolist()
    shape=(len(dates),len(symbols));di=pd.Index(dates);si=pd.Index(symbols);PANEL.mkdir(exist_ok=True)
    nums=['open','high','low','close','preclose','volume','amount','turnover_fraction','circulating_shares','share_multiplier','cash_per_share','up_limit_price','down_limit_price','limit_pct']
    flags=['hard_valid','corporate_action_blocking','historical_identity_valid','trading_state_valid','buy_blocked_open','sell_blocked_open','is_st']
    a={k:mem(k,shape) for k in nums}
    a.update({k:mem(k,shape,'bool',k in ['corporate_action_blocking','buy_blocked_open','sell_blocked_open','is_st']) for k in flags})
    a['trade_status']=mem('trade_status',shape,'int8',0)
    industry=mem('industry',shape,'int16',-1);market=mem('market',(len(dates),4));industries={};bindings=[]
    for p in files:
        df=db.execute('select * from read_parquet(?)',[str(p)]).df();df=df[df.symbol.isin(si)]
        assert (df.available_at<=df.decision_at).all() and df.snapshot_id.notna().all()
        assert not df.duplicated(['trade_date','symbol']).any()
        ti=di.get_indexer(df.trade_date.dt.strftime('%Y-%m-%d'));ji=si.get_indexer(df.symbol)
        for k in a:a[k][ti,ji]=df[k].to_numpy()
        for v in df.industry.dropna().unique():
            if v not in industries:industries[v]=len(industries)
        industry[ti,ji]=df.industry.map(industries).fillna(-1).astype('int16')
        md=df.groupby(ti)[['market_open','market_high','market_low','market_close']].first();market[md.index]=md.to_numpy()
        bindings.append(dict(path=str(p),sha256=sha(p),rows=len(df)));print('partition',p.parent.name,len(df),flush=True)
    db.close()
    coordinate=module('_long_coordinates',LIFE/'data.py').coordinates
    engine=module('_long_engine',HERE.parent/'ashare_wave_structure_v1/engine.py')
    outputs={k:mem(k,shape,'bool',False) for k in ['safe','coordok','entryok','exitok']}
    outputs.update({k:mem(k,shape) for k in ['factor','adj_volume','adj_open','adj_high','adj_low','adj_close']})
    outputs['history']=mem('history',shape,'int32',0)
    for j in range(0,len(symbols),64):
        sl=np.s_[:,j:j+64];valid=a['hard_valid'][sl]&~a['corporate_action_blocking'][sl]&a['historical_identity_valid'][sl]
        for k in ['open','high','low','close','preclose']:valid &= np.isfinite(a[k][sl])&(a[k][sl]>0)
        factor,sf,ok=coordinate(*[np.ascontiguousarray(a[k][sl]) for k in ['close','open','high','low','preclose','share_multiplier','cash_per_share']],valid,np.ascontiguousarray(a['volume'][sl]))
        safe=ok&a['trading_state_valid'][sl]&(a['trade_status'][sl]==1)&~a['is_st'][sl]
        for k,v in dict(factor=factor,coordok=ok,safe=safe,entryok=safe&~a['buy_blocked_open'][sl],exitok=ok&a['trading_state_valid'][sl]&(a['trade_status'][sl]==1)&~a['sell_blocked_open'][sl],history=engine.streak(safe),adj_volume=a['volume'][sl]/sf).items():outputs[k][sl]=v
        for k in ['open','high','low','close']:outputs['adj_'+k][sl]=a[k][sl]*factor
    for v in [*a.values(),*outputs.values(),industry,market]:v.flush()
    (PANEL/'axes.json').write_text(json.dumps(dict(dates=dates,symbols=symbols,industries=industries,source_bindings=bindings),ensure_ascii=False))
    dump('PANEL_AUDIT.json',dict(at=now(),shape=shape,source_bindings=bindings,coordinate_code_sha256=sha(LIFE/'data.py'),safe_stock_days=int(outputs['safe'].sum()),note='Coordinates recomputed continuously across source partition joins; no adjusted-price concatenation.'))

def rolling(a,n,f='mean'):return getattr(pd.Series(a).rolling(n,min_periods=n),f)().to_numpy()

def features():
    meta=json.loads((PANEL/'axes.json').read_text());dates=np.array(meta['dates']);symbols=np.array(meta['symbols']);di=pd.Index(dates)
    prior=json.loads((HERE.parent/'stock_predictability_v1/UNIVERSE_QUALIFIED_MANIFEST.json').read_text())
    late={r['date']:r for r in prior['records'] if r['date']<='2023-12-31'}
    grid=np.r_[np.arange(0,int(np.searchsorted(dates,'2018-01-01')),10),di.get_indexer(sorted(late))]
    members=np.zeros((len(grid),len(symbols)),bool);records=[]
    for g,t in enumerate(grid):
        day=dates[t]
        if day<'2018-01-01':
            p=(Path('/Volumes/quant/CY_quant_research/ashare_path_autonomous_v4/universe_2007_2009') if day<'2010-01-01' else Path('/Users/linmei/Documents/CY/data/discovery/QD-007-BS-2010-2017')/day[:4])/f'snapshot_{day}.json'
            obj=json.loads(p.read_text())
            if obj['metadata']['error_code']!='0' or not obj['rows']:
                p=OUT/'universe_repairs'/f'snapshot_{day}.json';obj=json.loads(p.read_text())
            md=obj['metadata'];assert md['error_code']=='0' and md['trade_date']==day and md['row_count']==len(obj['rows']),p
            digest=md.pop('sha256');body=(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n').encode();assert hashlib.sha256(body).hexdigest()==digest
            codes=[r['code'] for r in obj['rows']]
        else:
            rec=late[day];p=Path(rec['path']);assert sha(p)==rec['sha256'];obj=json.loads(p.read_text());assert obj['error_code']=='0'
            codes=[dict(zip(obj['fields'],r))['code'] for r in obj['rows']]
        assert codes and len(codes)==len(set(codes))
        members[g]=np.isin(symbols,[c[3:]+'.'+c[:2].upper() for c in codes]);records.append(dict(date=day,path=str(p),sha256=sha(p)))
    safe=get('safe');history=get('history');ti,ji=np.where(members&safe[grid]&(history[grid]>=60));ti=grid[ti]
    idx=pd.DataFrame(dict(t=ti,j=ji,decision_date=dates[ti],stock=symbols[ji],year=[int(d[:4]) for d in dates[ti]]));n=len(idx)
    c=get('adj_close');market=get('market')[:,3];industries=get('industry')
    ir=mem('industry_return',c.shape,'float64');mr=[]
    for h in [3,20,60]:
        v=np.full(len(dates),np.nan);v[h:]=market[h:]/market[:-h]-1;mr.append(v)
    for t in range(1,len(dates)):
        g=int(np.searchsorted(grid,t,side='right')-1);r=c[t]/c[t-1]-1
        ok=safe[t]&(history[t]>1)&members[g]&(industries[t]>=0)&np.isfinite(r);ids=industries[t,ok]
        count=np.bincount(ids,minlength=len(meta['industries']));sums=np.bincount(ids,weights=r[ok],minlength=len(meta['industries']));den=count[ids]-1
        ir[t,ok]=np.divide(sums[ids]-r[ok],den,out=np.full(len(ids),np.nan),where=den>0)
    raw=np.lib.format.open_memmap(OUT/'raw.npy',mode='w+',dtype='float16',shape=(n,4,32,13));legs=np.lib.format.open_memmap(OUT/'legs.npy',mode='w+',dtype='float16',shape=(n,4,10,18))
    factors=np.full((n,14),np.nan,np.float32);labels=np.full((n,3),np.nan,np.float32)
    f=old('features');engine=module('_long_engine',HERE.parent/'ashare_wave_structure_v1/engine.py')
    o=get('adj_open');high=get('adj_high');low=get('adj_low');volume=get('adj_volume');turn=get('turnover_fraction');amount=get('amount');close=get('close');shares=get('circulating_shares')
    for j in np.unique(ji):
        rows=np.flatnonzero(ji==j);tt=ti[rows];z=c[:,j];prev=np.r_[np.nan,z[:-1]];r=z/prev-1;r[history[:,j]<=1]=np.nan
        tr=np.maximum(high[:,j]-low[:,j],np.maximum(abs(high[:,j]-prev),abs(low[:,j]-prev)))/prev;atr=np.r_[np.nan,rolling(tr,20)[:-1]]
        past=[]
        for h in [3,20,60]:
            v=np.full(len(z),np.nan);v[h:]=z[h:]/z[:-h]-1;v[history[:,j]<=h]=np.nan;past.append(v)
        dd=np.r_[np.nan,z[:-1]/rolling(z,20,'max')[:-1]-1]
        ff=past+[rolling(r,20,'std'),dd,np.log(close[:,j]*shares[:,j]),turn[:,j]]+mr+[np.expm1(rolling(np.log1p(ir[:,j]),h,'sum')) for h in [3,20,60]]+[history[:,j]/256]
        factors[rows]=np.column_stack(ff)[tt]
        x=np.column_stack([z,o[:,j],high[:,j],low[:,j],volume[:,j],turn[:,j],amount[:,j],market,np.nan_to_num(ir[:,j])])
        rr,ll=f.stock_features(x,atr,np.asarray(safe[:,j]),tt);assert np.isfinite(rr).all() and np.isfinite(ll).all()
        raw[rows]=np.clip(rr[:,0],-30,30).astype('float16');legs[rows]=np.clip(ll[:,[1,3,5,7],-10:],-30,30).astype('float16')
        ret,_,_=engine.labels(*[np.ascontiguousarray(v[:,j:j+1]) for v in [o,high,low,get('coordok'),get('entryok'),get('exitok')]])
        for k,h in enumerate([10,20,40]):
            ok=tt+1+h<len(dates);labels[rows[ok],k]=ret[tt[ok],0,k+1]
        if j%300==0:print('features',j,len(symbols),n,flush=True)
    raw.flush();legs.flush();ir.flush();idx.to_parquet(OUT/'index.parquet',index=False);np.save(OUT/'factors.npy',factors);np.save(OUT/'labels.npy',labels)
    bindings=[dict(path=str(p),sha256=sha(p)) for p in [*sorted(OUT.glob('*.npy')),OUT/'index.parquet',PANEL/'axes.json']]
    dump('FEATURES.json',dict(at=now(),rows=n,membership_records=records,hashes=bindings,label_horizons=[10,20,40],dates=[dates[0],dates[-1]],pit_grade='B',split_sha256=sha(HERE/'TIME_SPLIT.json')))
    print('FEATURES COMPLETE',n,flush=True)

if __name__=='__main__':(panel if sys.argv[1]=='panel' else features)()
