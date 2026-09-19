"""Frozen CPU daily inference, prefix features and exhaustive original-grid parity."""
import argparse, ast, fcntl, os
import pandas as pd
import joblib
import torch
from common import *
from prepare import rolling
from train import PathResidual

DEST=OUT/'account_diversification_v1'
DOC='account_diversification_v1/'

def membership(meta):
    dates=np.array(meta['dates']);symbols=np.array(meta['symbols'])
    recs=[r for r in json.loads((HERE/'FEATURES.json').read_text())['membership_records'] if '2019-12-01'<=r['date']<'2024']
    masks=[]
    for r in recs:
        assert sha(r['path'])==r['sha256'];v=json.loads(Path(r['path']).read_text());assert v['error_code']=='0'
        codes=[dict(zip(v['fields'],row))['code'] for row in v['rows']]
        masks.append(np.isin(symbols,[c[3:]+'.'+c[:2].upper() for c in codes]))
    grid=np.searchsorted(dates,[r['date'] for r in recs]);ts=np.flatnonzero((dates>='2020-01-01')&(dates<'2024'))
    g=np.searchsorted(grid,ts,side='right')-1;assert (g>=0).all()
    return ts,np.array(masks)[g],recs,grid

def stock_inputs(j,tt,a,mr,encoder):
    z=a['adj_close'][:,j];hist=a['history'][:,j];prev=np.r_[np.nan,z[:-1]];r=z/prev-1;r[hist<=1]=np.nan
    tr=np.maximum(a['adj_high'][:,j]-a['adj_low'][:,j],np.maximum(abs(a['adj_high'][:,j]-prev),abs(a['adj_low'][:,j]-prev)))/prev
    atr=np.r_[np.nan,rolling(tr,20)[:-1]];past=[]
    for h in [3,20,60]:
        v=np.full(len(z),np.nan);v[h:]=z[h:]/z[:-h]-1;v[hist<=h]=np.nan;past.append(v)
    ir=a['industry_return'][:,j];dd=np.r_[np.nan,z[:-1]/rolling(z,20,'max')[:-1]-1]
    ff=past+[rolling(r,20,'std'),dd,np.log(a['close'][:,j]*a['circulating_shares'][:,j]),a['turnover_fraction'][:,j]]+mr+[np.expm1(rolling(np.log1p(ir),h,'sum')) for h in [3,20,60]]+[hist/256]
    factors=np.column_stack(ff)[tt].astype('float32')
    x=np.column_stack([z,a['adj_open'][:,j],a['adj_high'][:,j],a['adj_low'][:,j],a['adj_volume'][:,j],a['turnover_fraction'][:,j],a['amount'][:,j],a['market'][:,3],np.nan_to_num(ir)])
    rr,ll=encoder.stock_features(x,atr,np.asarray(a['safe'][:,j]),tt)
    assert np.isfinite(rr).all() and np.isfinite(ll).all()
    return np.clip(rr[:,0],-30,30).astype('float16'),np.clip(ll[:,[1,3,5,7],-10:],-30,30).astype('float16'),factors

def main(seed=17,limit=None):
    torch.set_num_threads(1);DEST.mkdir(exist_ok=True)
    lock=open(DEST/f'inference_s{seed}.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    meta=json.loads((PANEL/'axes.json').read_text());dates=np.array(meta['dates']);ts,member,recs,grid=membership(meta)
    assert dates[-1]<'2024';models={};bases={};bindings=[]
    for year in range(2020,2024):
        name=f'M1_OFFSET_{year}_s{seed}_O2_B32768';cp=OUT/(name+'.pt');report=json.loads((HERE/(name+'_TRAINING.json')).read_text())
        assert report['checkpoint_sha256']==sha(cp) and report['steps']==32768
        assert pd.Timestamp(report['actual_first'])+pd.DateOffset(years=12)<=pd.Timestamp(report['actual_last'])
        ck=torch.load(cp,map_location='cpu',weights_only=False);assert ck['step']==32768 and ck['cutoff']<f'{year}-01-01'
        archived=OUT/'code_snapshots'/(ck['code_sha256']+'_train.py')
        assert sha(archived)==ck['code_sha256'] and ck['feature_sha256']==sha(HERE/'FEATURES.json')
        # Older folds predate unrelated training additions; verify the used class, not a false whole-file identity.
        residual=lambda p:ast.dump(next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='PathResidual'),include_attributes=False)
        assert residual(archived)==residual(HERE/'train.py')
        bp=OUT/f'M0_CONTEXT_{year}.joblib';assert sha(bp)==ck['base_sha256'];bases[year]=joblib.load(bp)
        m=PathResidual(ck['config']);m.load_state_dict(ck['state']);models[year]=m.eval()
        bindings.append(dict(year=year,checkpoint=str(cp),sha256=sha(cp),baseline_sha256=sha(bp),cutoff=ck['cutoff'],training_source_sha256=ck['code_sha256'],residual_class_ast_equal=True))
    identity=dict(seed=seed,models=bindings,code_sha256=sha(Path(__file__)),protocol_sha256=sha(HERE/DOC/'RESEARCH_PROTOCOL.md'),features_manifest_sha256=sha(HERE/'FEATURES.json'),membership_records=recs)
    seal=DEST/f's{seed}_identity.json'
    if seal.exists():assert json.loads(seal.read_text())==identity
    else:seal.write_text(json.dumps(identity,indent=2))
    a={k:get(k) for k in ['safe','history','adj_close','adj_open','adj_high','adj_low','adj_volume','close','circulating_shares','turnover_fraction','amount','industry_return','market']}
    valid=member&a['safe'][ts]&(a['history'][ts]>=60);eligible=np.flatnonzero(valid.any(axis=0));market=a['market'][:,3];mr=[]
    for h in [3,20,60]:
        v=np.full(len(dates),np.nan);v[h:]=market[h:]/market[:-h]-1;mr.append(v)
    original=pd.read_parquet(OUT/'index.parquet');original=original[original.year.between(2020,2023)]
    saved=pd.concat([pd.read_parquet(OUT/f'M1_OFFSET_{y}_s{seed}_O2_B32768_FORWARD_DEVELOPMENT_pred.parquet') for y in range(2020,2024)]).set_index(['t','j'])
    banks=[np.load(OUT/(k+'.npy'),mmap_mode='r') for k in ['raw','legs','factors']];encoder=old('features')
    shard=DEST/f's{seed}_stocks';shard.mkdir(exist_ok=True);done=0
    for j in eligible:
        from risk_repair_train import deadline
        deadline();p=shard/f'{j:05}.parquet';proof=shard/f'{j:05}.json'
        if p.exists() and proof.exists():done+=1;continue
        tt=ts[valid[:,j]];raw,legs,factors=stock_inputs(j,tt,a,mr,encoder)
        common=original[original.j==j];ii=np.searchsorted(tt,common.t);assert np.array_equal(tt[ii],common.t)
        for bank,v in zip(banks,[raw,legs,factors]):assert np.array_equal(bank[common.index],v[ii],equal_nan=True),(j,'feature parity')
        output=np.empty((len(tt),3),np.float32);off_error=0.
        with torch.no_grad():
            for year in range(2020,2024):
                rows=np.flatnonzero(np.char.startswith(dates[tt],str(year)))
                if not len(rows):continue
                b=bases[year];xx=b['scale'].transform(np.nan_to_num(factors[rows]).astype('float64'))
                offset=np.column_stack([f.predict(xx) for f in b['fits']]).astype('float32')
                oldrows=common[common.year==year];pos=np.searchsorted(tt[rows],oldrows.t)
                oldoff=np.load(OUT/f'M0_CONTEXT_{year}_offset.npy',mmap_mode='r')
                if len(pos):off_error=max(off_error,float(np.max(abs(offset[pos]-oldoff[oldrows.index]))))
                for start in range(0,len(rows),256):
                    take=rows[start:start+256];xx=np.concatenate([raw[take].astype('float32'),np.broadcast_to(offset[start:start+256,None,None,:],(len(take),4,32,3))],axis=-1)
                    output[take]=models[year](torch.from_numpy(xx),torch.from_numpy(legs[take].astype('float32')))[0][:,:3].numpy()/10
        pred_error=float(np.max(abs(output[ii]-saved.loc[list(zip(common.t,common.j)),['pred10','pred20','pred40']].to_numpy()))) if len(ii) else 0.
        assert off_error<=2e-7 and pred_error<=2e-6,(j,off_error,pred_error)
        df=pd.DataFrame(dict(t=tt,j=j,decision_date=dates[tt],stock=meta['symbols'][j],year=[int(d[:4]) for d in dates[tt]],pred10=output[:,0],pred20=output[:,1],pred40=output[:,2]))
        tmp=p.with_suffix('.tmp');df.to_parquet(tmp,index=False);tmp.replace(p)
        proof.write_text(json.dumps(dict(rows=len(df),common_rows=len(ii),feature_parity=True,offset_maxabs=off_error,prediction_maxabs=pred_error,sha256=sha(p))))
        done+=1
        if done%25==0 or done==1:
            dump(DOC+f'INFERENCE_s{seed}_STATE.json',dict(at=now(),pid=os.getpid(),status='CPU_INFERENCE',stocks_done=done,stocks_total=len(eligible),last_stock=int(j),no_retraining=True));print('STOCK',done,len(eligible),int(j),pred_error,flush=True)
        if limit and done>=limit:break
    if done!=len(eligible):return
    parts=[];proofs=[]
    for j in eligible:
        p=shard/f'{j:05}.parquet';v=json.loads(p.with_suffix('.json').read_text());assert sha(p)==v['sha256'];proofs.append(v);parts.append(pd.read_parquet(p))
    allpred=pd.concat(parts,ignore_index=True).sort_values(['t','j']);assert not allpred.duplicated(['t','j']).any()
    common=allpred[allpred.t.isin(original.t.unique())];assert set(zip(common.t,common.j))==set(zip(original.t,original.j))
    target=DEST/f'DAILY_s{seed}.parquet';allpred.to_parquet(target,index=False)
    dump(DOC+f'DAILY_s{seed}_ADMISSION.json',dict(at=now(),status='ADMITTED',rows=len(allpred),common_rows=len(common),features_exact=True,prediction_maxabs=max(v['prediction_maxabs'] for v in proofs),offset_maxabs=max(v['offset_maxabs'] for v in proofs),prediction_path=str(target),sha256=sha(target),identity=identity,anchor0=3166,development_years=[2020,2021,2022,2023],membership_rule='latest snapshot<=decision; current safe/history>=60; unchanged frozen industry path'))
    dump(DOC+f'INFERENCE_s{seed}_STATE.json',dict(at=now(),status='COMPLETE',stocks_done=done,stocks_total=len(eligible)))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seed',type=int,default=17);p.add_argument('--limit',type=int);a=p.parse_args();main(a.seed,a.limit)
