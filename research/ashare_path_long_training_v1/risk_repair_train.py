"""Frozen return encoder, identical old/repaired heads; no trading-rule changes."""
import argparse, os, time
import pandas as pd
import torch
from torch import nn
from common import *
from train import PathResidual
from local_supervisor import exclusive
from risk_incrementality import contract

STEPS=8192

def deadline():
    if datetime.datetime.now(datetime.timezone.utc)>=datetime.datetime.fromisoformat(contract()['hard_deadline']):raise RuntimeError('RESOURCE_HARD_DEADLINE; checkpoint preserved')

def write_checkpoint(path,ck):
    tmp=path.with_suffix('.tmp.pt');torch.save(ck,tmp);tmp.replace(path)

def main(year):
    with exclusive(OUT/'training.lock'):
        torch.set_num_threads(2);deadline()
        tag=f'RISK_REPAIR_R1_{year}_s17';report=HERE/(tag+'.json');dest=OUT/(tag+'_pred.parquet')
        if report.exists():
            r=json.loads(report.read_text());assert r['code_sha256']==sha(Path(__file__)) and r['pred_sha256']==sha(dest);print('REUSE',tag,flush=True);return
        labelmanifest=json.loads((HERE/'RISK_LABEL_REPAIR_R1.json').read_text());assert labelmanifest['sha256']==sha(labelmanifest['path'])
        registry=json.loads((HERE/'RESEARCH_REGISTRY.json').read_text());asset=next(a for a in registry['assets'] if a['asset_id']==labelmanifest['asset_id']);assert asset['lineage']['manifest_sha256']==sha(HERE/'RISK_LABEL_REPAIR_R1.json')
        manifest=json.loads((HERE/'FEATURES.json').read_text())
        for b in manifest['hashes']:
            if Path(b['path']).name in ['raw.npy','legs.npy','index.parquet','labels.npy']:assert sha(b['path'])==b['sha256']
        idx=pd.read_parquet(OUT/'index.parquet');dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates']);cut=np.searchsorted(dates,f'{year}-01-01')-1;end=np.searchsorted(dates,f'{year}-12-31',side='right')-1
        y=np.load(labelmanifest['path'],mmap_mode='r');oldmae=np.load(OUT/'mae_close20.npy',mmap_mode='r')
        trainrows=np.flatnonzero((idx.t.to_numpy()+21<=cut)&(np.isfinite(y[:,0])|np.isfinite(y[:,5])))
        z=idx.iloc[trainrows];assert pd.Timestamp(z.decision_date.min())+pd.DateOffset(years=12)<=pd.Timestamp(z.decision_date.max())
        groups={int(yr):[g.index.to_numpy() for _,g in zz.groupby('t')] for yr,zz in z.groupby('year')};years=sorted(groups);assert years==list(range(years[0],year))
        devrows=np.flatnonzero(idx.year==year);allrows=np.union1d(trainrows,devrows)
        source=f'M1_OFFSET_{year}_s17_O2_B32768';ckpath=OUT/(source+'.pt');training=json.loads((HERE/(source+'_TRAINING.json')).read_text());assert training['checkpoint_sha256']==sha(ckpath) and training['steps']==32768
        ck=torch.load(ckpath,map_location='cpu',weights_only=False);assert ck['cutoff']==dates[cut] and ck['feature_sha256']==sha(HERE/'FEATURES.json')
        frozen=PathResidual(ck['config']);frozen.load_state_dict(ck['state']);frozen.eval();device='mps' if torch.backends.mps.is_available() else 'cpu';frozen.to(device)
        for p in frozen.parameters():p.requires_grad_(False)
        embfile=OUT/(tag+'_embedding.npy');embmeta=HERE/(tag+'_EMBEDDING.json');dimension=ck['config']['embedding']
        if not embmeta.exists():
            embtmp=embfile.with_suffix('.tmp.npy');emb=np.lib.format.open_memmap(embtmp,mode='w+',dtype='float32',shape=(len(idx),dimension));emb[:]=np.nan
            raw=np.load(OUT/'raw.npy',mmap_mode='r');legs=np.load(OUT/'legs.npy',mmap_mode='r');off=np.load(OUT/f'M0_CONTEXT_{year}_offset.npy',mmap_mode='r')
            frozenpred=pd.read_parquet(OUT/(source+'_FORWARD_DEVELOPMENT_pred.parquet')).set_index(['t','j']);maxdiff=0.;devset=set(devrows)
            with torch.no_grad():
                for start in range(0,len(allrows),512):
                    if start%32768==0:deadline();print(tag,'embedding',start,len(allrows),flush=True)
                    rr=allrows[start:start+512];x=np.concatenate([raw[rr].astype('float32'),np.broadcast_to(off[rr,None,None,:],(len(rr),4,32,3))],axis=-1)
                    p,v,_=frozen(torch.tensor(x,device=device),torch.tensor(legs[rr].astype('float32'),device=device));emb[rr]=v.cpu().numpy()
                    check=np.array([r in devset for r in rr]);dd=rr[check]
                    if len(dd):
                        expected=frozenpred.loc[pd.MultiIndex.from_frame(idx.iloc[dd][['t','j']]),'pred20'].to_numpy();actual=p.cpu().numpy()[check,1]/10;maxdiff=max(maxdiff,float(np.max(abs(actual-expected))))
            assert maxdiff<2e-6,maxdiff
            emb.flush();del emb;embtmp.replace(embfile);dump(embmeta.name,dict(at=now(),path=str(embfile),sha256=sha(embfile),encoder_sha256=sha(ckpath),feature_sha256=sha(HERE/'FEATURES.json'),code_sha256=sha(Path(__file__)),rows=len(allrows),max_frozen_ret20_deviation=maxdiff))
        em=json.loads(embmeta.read_text());assert em['encoder_sha256']==sha(ckpath) and em['sha256']==sha(embfile) and em['code_sha256']==sha(Path(__file__))
        del frozen
        if device=='mps':torch.mps.empty_cache()
        # Lightweight head training on CPU leaves encoder immutable; fixed equal-year/date draws.
        embeddings=np.load(embfile,mmap_mode='r');features=torch.tensor(np.nan_to_num(np.asarray(embeddings)).copy())
        scale=features[trainrows].std(0).clamp_min(1e-6);center=features[trainrows].mean(0);features=(features-center)/scale
        torch.manual_seed(1747);model=nn.Sequential(nn.Linear(dimension,32),nn.GELU(),nn.Linear(32,3));model2=nn.Sequential(nn.Linear(dimension,32),nn.GELU(),nn.Linear(32,3));model2.load_state_dict(model.state_dict());models=[model,model2]
        opts=[torch.optim.AdamW(m.parameters(),lr=.001,weight_decay=.0001) for m in models]
        rng=np.random.default_rng(1747);draws=np.zeros(len(idx),np.int32);history=[];first=1;resume=OUT/(tag+'_resume.pt')
        identity=dict(code_sha256=sha(Path(__file__)),labels_sha256=labelmanifest['sha256'],encoder_sha256=sha(ckpath),embedding_sha256=em['sha256'],old_label_sha256=sha(OUT/'mae_close20.npy'),cutoff=str(dates[cut]),steps=STEPS)
        if resume.exists():
            r=torch.load(resume,map_location='cpu',weights_only=False);assert r['identity']==identity
            for m,o,s,os_ in zip(models,opts,r['models'],r['optimizers']):m.load_state_dict(s);o.load_state_dict(os_)
            rng.bit_generator.state=r['rng'];draws=r['draws'];history=r['history'];first=r['step']+1
        for step in range(first,STEPS+1):
            rows=[]
            for _ in range(8):
                yr=int(rng.choice(years));g=groups[yr][int(rng.integers(len(groups[yr])))];rows.extend(rng.choice(g,32,replace=len(g)<32))
            rr=np.asarray(rows);np.add.at(draws,rr,1);losses=[]
            for k,(m,opt) in enumerate(zip(models,opts)):
                continuous=np.asarray(oldmae[rr] if k==0 else y[rr,0]);event=np.asarray(y[rr,5]);target=torch.tensor(np.c_[continuous,(continuous<-.1).astype(float),event],dtype=torch.float32);valid=torch.isfinite(target);valid[:,1]=torch.isfinite(target[:,0]);target=torch.nan_to_num(target)
                p=m(features[rr]);reg=torch.nn.functional.smooth_l1_loss(p[:,0],target[:,0]*10,reduction='none');bce=torch.nn.functional.binary_cross_entropy_with_logits(p[:,1:],target[:,1:],reduction='none')
                losses_by_head=torch.cat([reg[:,None],bce],1);loss=((losses_by_head*valid).sum(0)/valid.sum(0).clamp_min(1)).mean();opt.zero_grad();loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),1);opt.step();losses.append(float(loss.detach()))
            if step%512==0 or step==STEPS:
                history.append(dict(step=step,old_mask_loss=losses[0],repaired_loss=losses[1]));write_checkpoint(resume,dict(identity=identity,step=step,models=[m.state_dict() for m in models],optimizers=[o.state_dict() for o in opts],rng=rng.bit_generator.state,draws=draws,history=history));deadline();print(tag,history[-1],flush=True)
        actual=idx[draws>0];assert pd.Timestamp(actual.decision_date.min())+pd.DateOffset(years=12)<=pd.Timestamp(actual.decision_date.max())
        assert all(draws[g.index].sum()>0 for _,g in z.groupby('year'))
        pred=pd.read_parquet(OUT/(source+'_FORWARD_DEVELOPMENT_pred.parquet'));lookup=idx[['t','j']].copy();lookup['row']=np.arange(len(idx));pred=pred.merge(lookup,on=['t','j'],validate='one_to_one');rr=pred.row.to_numpy()
        for k,m in enumerate(models):
            m.eval();pp=[]
            with torch.no_grad():
                for start in range(0,len(rr),4096):pp.append(m(features[rr[start:start+4096]]).numpy())
            pp=np.concatenate(pp);prefix='old' if k==0 else 'repaired';pred[prefix+'_mae']=pp[:,0]/10;pred[prefix+'_risk10']=1/(1+np.exp(-np.clip(pp[:,1],-50,50)));pred[prefix+'_cat']=1/(1+np.exp(-np.clip(pp[:,2],-50,50)))
        mature=idx.t.to_numpy()[rr]+21<=end
        for c,k in [('mae',0),('ret20',4),('cat_event',5),('exit_lock',6)]:pred[c]=np.where(mature,y[rr,k],np.nan)
        tmp=dest.with_suffix('.tmp.parquet');pred.to_parquet(tmp,index=False);tmp.replace(dest)
        write_checkpoint(OUT/(tag+'.pt'),dict(identity=identity,models=[m.state_dict() for m in models],center=center,scale=scale,step=STEPS))
        annual=[dict(year=int(yr),actual_draws=int(draws[g.index].sum()),unique_rows=int((draws[g.index]>0).sum()),continuous_repaired_draws=int((draws[g.index]*np.isfinite(y[g.index,0])).sum()),event_draws=int((draws[g.index]*np.isfinite(y[g.index,5])).sum())) for yr,g in z.groupby('year')]
        dump(report.name,dict(at=now(),**identity,pred_sha256=sha(dest),pred_path=str(dest),checkpoint_sha256=sha(OUT/(tag+'.pt')),training_first=actual.decision_date.min(),training_last=actual.decision_date.max(),annual=annual,history=history,contrast='Identical frozen return encoder/head init/draws/budget; old versus repaired continuous masks; both have independent repaired catastrophic-event target',return_model_changed=False,account_rules_changed=False))
        print('RISK_HEAD_COMPLETE',tag,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,required=True,choices=[2020,2021,2022,2023]);main(p.parse_args().year)
