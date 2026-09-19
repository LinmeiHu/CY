"""Year/date balanced mature supervision, full fit diagnostics, separate forward development."""
import argparse,time
import pandas as pd
import torch
from torch import nn
from sklearn.linear_model import Ridge,LogisticRegression
from sklearn.preprocessing import StandardScaler
import joblib
from common import *
from sampling import draw as supervised_draw,year_probabilities
from objective_metrics import fixed_metrics
SOURCE_SHA=sha(Path(__file__));SAMPLING_SHA=sha(HERE/'sampling.py');METRICS_SHA=sha(HERE/'objective_metrics.py')

def mature(labels,t,cut):
    y=np.full(labels.shape,np.nan,np.float32)
    for k,h in enumerate([10,20,40]):
        ok=t+1+h<=cut;y[ok,k]=labels[ok,k]
    return y

class Data:
    def __init__(self,year):
        assert year in [2022,2023]
        manifest=json.loads((HERE/'FEATURES.json').read_text())
        registry=json.loads((HERE/'RESEARCH_REGISTRY.json').read_text());asset=next(a for a in registry['assets'] if a['asset_id']=='CY-WAVE-LONG-TRAINING-2007-2023')
        assert asset['lineage']['manifest_sha256']==sha(HERE/'FEATURES.json')
        assert manifest['split_sha256']==sha(HERE/'TIME_SPLIT.json')
        for b in manifest['hashes']:assert sha(b['path'])==b['sha256'],b['path']
        self.idx=pd.read_parquet(OUT/'index.parquet');self.t=self.idx.t.to_numpy();self.dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates'])
        self.cut=np.flatnonzero(self.dates<f'{year}-01-01')[-1];self.end=np.flatnonzero(self.dates<=f'{year}-12-31')[-1]
        self.raw=np.load(OUT/'raw.npy',mmap_mode='r');self.legs=np.load(OUT/'legs.npy',mmap_mode='r');self.factors=np.load(OUT/'factors.npy',mmap_mode='r');self.labels=np.load(OUT/'labels.npy',mmap_mode='r')
        self.y=mature(self.labels,self.t,self.cut);self.eval_y=mature(self.labels,self.t,self.end)
        self.train=np.flatnonzero(np.isfinite(self.y[:,1]));self.fit_rows=np.flatnonzero(self.t<=self.cut);self.dev_rows=np.flatnonzero(self.idx.year==year)
        self.groups={int(y):[g.index.to_numpy() for _,g in z.groupby('t')] for y,z in self.idx.iloc[self.train].groupby('year')}
        self.years=sorted(self.groups);self.offset=None;self.factor_context=None;self.path_risk=False
        self.weights=np.zeros(len(self.idx))
        for year_,groups in self.groups.items():
            for rows in groups:self.weights[rows]=1/len(self.years)/len(groups)/len(rows)
        self.coverage=self.audit(year)
    def audit(self,year):
        rows=self.idx.iloc[self.train];first=pd.Timestamp(rows.decision_date.min());last=pd.Timestamp(rows.decision_date.max())
        assert first+pd.DateOffset(years=12)<=last,(first,last)
        assert self.years==list(range(first.year,last.year+1))
        annual=[]
        for yr,g in rows.groupby('year'):
            eligible=self.idx.index[(self.idx.year==yr)&(self.t<=self.cut)].to_numpy();ii=g.index.to_numpy()
            annual.append(dict(year=int(yr),first=g.decision_date.min(),last=g.decision_date.max(),dates=g.t.nunique(),stocks=g.stock.nunique(),samples=len(g),eligible_decisions=len(eligible),year_loss_weight=float(self.weights[ii].sum()),effective_sample_size=float(self.weights[ii].sum()**2/(self.weights[ii]**2).sum()),mature_heads=[int(np.isfinite(self.y[eligible,k]).sum()) for k in range(3)],main_missing_fraction=float(np.isnan(self.y[eligible,1]).mean()),auxiliary_task='Ret20 sign/up10/down10 share mature Ret20 mask',complete_256_history_samples=int((self.factors[ii,-1]>=1).sum()),actual_draws='NOT_YET_RUN'))
        result=dict(fold=year,fit_cutoff=self.dates[self.cut],first_supervised=str(first.date()),last_supervised=str(last.date()),elapsed_years=(last-first).days/365.2425,anniversary_gate=True,no_missing_years=True,annual=annual,weight_scope='Uniform-year/date reference used by Ridge; actual NN sampling and head loss weights are checkpoint-specific',training_parameters_not_pit_for_fitted_history=True)
        dump(f'SPLIT_AND_TRAINING_COVERAGE_{year}.json',result);return result
    def batch(self,rows,device):
        x=np.array(self.raw[rows],np.float32)
        if self.offset is not None:x=np.concatenate([x,np.broadcast_to(self.offset[rows,None,None,:],(len(rows),4,32,3))],axis=-1)
        if self.factor_context is not None:x=np.concatenate([x,np.broadcast_to(self.factor_context[rows,None,None,:],(len(rows),4,32,28))],axis=-1)
        return torch.tensor(x,device=device),torch.tensor(np.array(self.legs[rows],np.float32),device=device)
    def draw(self,rng,dates=16,stocks=16):
        return np.concatenate([rng.choice((g:=self.groups[self.years[int(rng.integers(len(self.years)))]])[int(rng.integers(len(g)))],stocks,replace=True) for _ in range(dates)])

def annual_metrics(idx,pred,y,mae=None):
    per=[]
    for t,g in idx.groupby('t'):
        ii=g.index.to_numpy();p=pred[ii,1];r=y[ii,1];ok=np.isfinite(r);order=np.lexsort((g.j.to_numpy(),-p))
        out=dict(year=int(g.year.iloc[0]),date=g.decision_date.iloc[0],t=int(t),n=len(g),valid=int(ok.sum()),pool_mean=float(np.nanmean(r)),pred_mean=float(p.mean()),pred_std=float(p.std()),mse20=float(np.nanmean((p-r)**2)),rank_ic=pd.Series(p[ok]).corr(pd.Series(r[ok]),method='spearman'))
        for k in [10,50]:
            selected=order[:k];out[f'top{k}_mean']=float(np.nanmean(r[selected]));out[f'top{k}_label_coverage']=float(np.isfinite(r[selected]).mean());out[f'top{k}_pred_mean']=float(p[selected].mean())
        for k,h in enumerate([10,20,40]):out[f'mse{h}']=float(np.nanmean((pred[ii,k]-y[ii,k])**2))
        for col in ['positive','up10','down10']:
            k=['positive','up10','down10'].index(col);actual=[r>0,r>.1,r<-.1][k]
            observed=ok
            if k==2 and mae is not None:col='path_down10';actual=mae[ii]<-.1;observed=np.isfinite(mae[ii])
            if pred.shape[1]>=6:
                prob=1/(1+np.exp(-np.clip(pred[ii,k+3],-50,50)));out[col+'_brier']=float(np.mean((prob[observed]-actual[observed])**2)) if observed.any() else np.nan
        per.append(out)
    per=pd.DataFrame(per);numeric=per.select_dtypes('number').columns.drop(['year','t']);annual=per.groupby('year')[numeric].mean().reset_index()
    annual['note']='Equal decision date means; select using all predictions BEFORE outcome missingness. Missing outcomes separately disclosed.'
    return annual,per

def save_prediction(name,data,rows,pred,scorecard):
    df=data.idx.iloc[rows].copy().reset_index(drop=True)
    for k,h in enumerate([10,20,40]):df[f'pred{h}']=pred[:,k]
    if pred.shape[1]>=6:
        for k,s in enumerate(['positive','up10','path_down10' if data.path_risk else 'down10']):df[s]=1/(1+np.exp(-np.clip(pred[:,k+3],-50,50)))
    df['scorecard']=scorecard;df.to_parquet(OUT/f'{name}_{scorecard}_pred.parquet',index=False)
    target=(data.y if scorecard=='TRAIN_FITTED_DIAGNOSTIC_ONLY' else data.eval_y)[rows]
    mae=(data.mae if scorecard=='TRAIN_FITTED_DIAGNOSTIC_ONLY' else data.eval_mae)[rows] if data.path_risk else None
    annual,per=annual_metrics(df,pred,target,mae);annual.to_csv(HERE/f'{name}_{scorecard}_ANNUAL.csv',index=False);per.to_parquet(OUT/f'{name}_{scorecard}_metrics.parquet',index=False)
    return annual

def baseline(data,year):
    name=f'M0_CONTEXT_{year}';x=np.nan_to_num(data.factors).astype('float64');scale=StandardScaler().fit(x[data.train],sample_weight=data.weights[data.train]);x=scale.transform(x)
    fits=[];pred=np.zeros((len(x),6),np.float32)
    for k in range(3):
        # Main sample universe retained; missing auxiliary heads contribute zero loss.
        rows=data.train[np.isfinite(data.y[data.train,k])];w=data.weights[rows];w=w/w.mean()
        fit=Ridge(alpha=100).fit(x[rows],data.y[rows,k],sample_weight=w);fits.append(fit);pred[:,k]=fit.predict(x)
    binary=[];target=data.y[data.train,1];w=data.weights[data.train];w=w/w.mean()
    for k,y in enumerate([target>0,target>.1,target<-.1]):
        fit=LogisticRegression(C=1,max_iter=300).fit(x[data.train],y,sample_weight=w);binary.append(fit);pred[:,k+3]=fit.decision_function(x)
    joblib.dump(dict(scale=scale,fits=fits,probability_fits=binary,cutoff=data.dates[data.cut],feature_sha256=sha(HERE/'FEATURES.json')),OUT/(name+'.joblib'))
    np.save(OUT/(name+'_offset.npy'),pred[:,:3])
    for rows,card in [(data.fit_rows,'TRAIN_FITTED_DIAGNOSTIC_ONLY'),(data.dev_rows,'FORWARD_DEVELOPMENT')]:
        a=save_prediction(name,data,rows,pred[rows],card);print(name,card,a[['year','mse20','top10_mean','rank_ic']].to_dict('records'),flush=True)
    dump(name+'_FIT.json',dict(cutoff=data.dates[data.cut],coverage=data.coverage,actual_fit_samples=len(data.train),weighted_loss='equal year / date / stock',checkpoint_sha256=sha(OUT/(name+'.joblib'))))

class PathResidual(nn.Module):
    def __init__(self,c):
        super().__init__();self.c=c;self.conditioned=False;self.core=old('model').PathModel(c)
        with torch.no_grad():self.core.pred.weight[:3].zero_();self.core.pred.bias[:3].zero_()
    def forward(self,x,l):
        p,z,w=self.core(x[...,:13],l);return torch.cat([p[:,:3]+10*x[:,0,0,13:16],p[:,3:]],1),z,w

def predict(model,data,rows,device):
    model.eval();out=np.zeros((len(rows),6),np.float32)
    with torch.no_grad():
        for i in range(0,len(rows),512):
            x,l=data.batch(rows[i:i+512],device);out[i:i+512]=model(x,l)[0].cpu().numpy()
    out[:,:3]/=10;return out

def set_factor_context(data,baseline):
    values=baseline['scale'].transform(np.nan_to_num(data.factors).astype('float64')).astype('float32')
    data.factor_context=np.concatenate([values,(~np.isfinite(data.factors)).astype('float32')],axis=1)
    assert np.isfinite(data.factor_context).all()

def fit(data,year,seed,steps,objective,weak=False,half_life=None,full_factors=False,factor_off=False,path_risk=False):
    source_sha=SOURCE_SHA;sampling_sha=SAMPLING_SHA
    assert sha(HERE/'train.py')==source_sha, 'Producer source changed between import and fit'
    assert sha(HERE/'objective_metrics.py')==METRICS_SHA
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu';torch.manual_seed(seed);rng=np.random.default_rng(seed)
    base=OUT/f'M0_CONTEXT_{year}.joblib';b=joblib.load(base);assert b['cutoff']==data.dates[data.cut]
    data.offset=np.load(OUT/f'M0_CONTEXT_{year}_offset.npy',mmap_mode='r')
    c=dict(json.loads((HERE.parent/'ashare_wave_adaptive_path_v3/MODEL_SELECTION_FREEZE.json').read_text())['architecture']);c.update(level=1,objective=objective)
    if weak:c.update(dropout=0.05,consistency=0.,lr=.0005,weight_decay=0.)
    if half_life is not None:c['sampling_half_life']=half_life
    assert not factor_off or full_factors
    assert not full_factors or half_life is None, 'Keep initial information and recency contrasts separate'
    model_class=PathResidual;factor_source_sha=None
    if full_factors:
        from factor_fusion import FullFactorResidual,SOURCE_SHA as factor_source_sha
        c.update(full_factors=True,factor_context_off=factor_off);set_factor_context(data,b);model_class=FullFactorResidual
    risk_source_sha=None;risk_manifest_sha=None
    if path_risk:
        assert not (full_factors or weak or half_life) and objective==2
        from risk_labels import attach
        from risk_objective import objective as risk_loss,SOURCE_SHA as risk_source_sha
        attach(data);risk_manifest_sha=sha(HERE/'MAE_LABEL_AUDIT.json');c['auxiliary_downside']='holding_close_mae20_lt_minus10'
        joint=data.idx.iloc[data.train[np.isfinite(data.mae[data.train])]]
        assert pd.Timestamp(joint.decision_date.min())+pd.DateOffset(years=12)<=pd.Timestamp(joint.decision_date.max())
        assert sorted(joint.year.unique())==data.years
        for row in data.coverage['annual']:
            row['auxiliary_task']='Mature Ret20 sign/up10 plus separately masked holding-close-MAE20<-10%; each coefficient0.1/3'
            row['path_risk_joint_primary_mature_samples']=int((joint.year==row['year']).sum())
    family='M1_PATHRISK' if path_risk else 'M1_FULLFACTOR' if full_factors else 'M1_OFFSET'
    name=f'{family}_{year}_s{seed}_O{objective}'+('_WEAK' if weak else '')+(f'_RECENT{half_life:g}' if half_life is not None else '')+('_FACTOROFF' if factor_off else '')
    m=model_class(c).to(device);opt=torch.optim.AdamW(m.parameters(),lr=c['lr'],weight_decay=c['weight_decay']);code=old('model')
    yy=torch.tensor(data.y,device=device);tt=torch.tensor(data.t,device=device)
    if path_risk:mae_target=torch.tensor(data.mae,device=device)
    fixed=np.random.default_rng(1747);probe=data.draw(fixed,256,16)
    devgroups=[g.index.to_numpy() for _,g in data.idx.iloc[data.dev_rows].groupby('t')];devprobe=np.concatenate([fixed.choice(g, min(128,len(g)),replace=False) for g in devgroups])
    draws=np.zeros(len(data.idx),np.int32);hist=[];start=time.monotonic();resume=OUT/(name+'_resume.pt');first=1
    if resume.exists():
        ck=torch.load(resume,map_location='cpu',weights_only=False);assert ck['feature_sha256']==sha(HERE/'FEATURES.json') and ck['config']==c
        m.load_state_dict(ck['state']);opt.load_state_dict(ck['optimizer']);rng.bit_generator.state=ck['numpy_rng'];torch.set_rng_state(ck['torch_rng'])
        if device=='mps':torch.mps.set_rng_state(ck['mps_rng'])
        draws=ck['draws'];hist=ck['history'];first=ck['step']+1
    log('LONG_TRAIN_START',name=name,steps=steps,first_step=first,rows=len(data.train),coverage=data.coverage['elapsed_years'],code_sha256=source_sha,sampling_sha256=sampling_sha)
    archive=OUT/'code_snapshots';archive.mkdir(exist_ok=True)
    for p in [HERE/'train.py',HERE/'common.py',HERE/'sampling.py',HERE/'objective_metrics.py',HERE.parent/'ashare_wave_adaptive_path_v3/model.py']:(archive/(sha(p)+'_'+p.name)).write_bytes(p.read_bytes())
    if full_factors:
        assert sha(HERE/'factor_fusion.py')==factor_source_sha
        (archive/(factor_source_sha+'_factor_fusion.py')).write_bytes((HERE/'factor_fusion.py').read_bytes())
    if path_risk:
        assert sha(HERE/'risk_objective.py')==risk_source_sha
        (archive/(risk_source_sha+'_risk_objective.py')).write_bytes((HERE/'risk_objective.py').read_bytes())
    for step in range(first,steps+1):
        m.train();rows=supervised_draw(data,rng,half_life);np.add.at(draws,rows,1);x,l=data.batch(rows,device);opt.zero_grad()
        loss=risk_loss(m,x,l,yy[rows],tt[rows],mae_target[rows],c['consistency']) if path_risk else code.objective(m,x,l,yy[rows],tt[rows],c['consistency'])
        loss.backward();grad=torch.nn.utils.clip_grad_norm_(m.parameters(),1);opt.step()
        if step in [1,128,512,1024,2048,4096,8192,16384,32768,65536] or step==steps:
            trainp=predict(m,data,probe,device);devp=predict(m,data,devprobe,device)
            hist.append(dict(step=step,batch_loss=float(loss.detach().cpu()),grad=float(grad.cpu()),train_mse20=float(np.nanmean((trainp[:,1]-data.y[probe,1])**2)),dev_mse20=float(np.nanmean((devp[:,1]-data.eval_y[devprobe,1])**2)),wall_seconds=time.monotonic()-start))
            for label,pred,rr,yy_ in [('train',trainp,probe,data.y),('dev',devp,devprobe,data.eval_y)]:
                mae=((data.mae if label=='train' else data.eval_mae)[rr]) if path_risk else None
                hist[-1].update({label+'_'+k:v for k,v in fixed_metrics(pred,yy_[rr],data.t[rr],objective,mae).items()})
            if path_risk:
                for label,pred,rr,yy_mae in [('train',trainp,probe,data.mae),('dev',devp,devprobe,data.eval_mae)]:
                    observed=np.isfinite(yy_mae[rr]);prob=1/(1+np.exp(-np.clip(pred[:,5],-50,50)))
                    hist[-1][label+'_path_risk_brier']=float(np.mean((prob[observed]-(yy_mae[rr][observed]<-.1))**2))
            print(name,hist[-1],flush=True)
            ck=dict(config=c,state={k:v.cpu() for k,v in m.state_dict().items()},optimizer=opt.state_dict(),step=step,seed=seed,numpy_rng=rng.bit_generator.state,torch_rng=torch.get_rng_state(),mps_rng=torch.mps.get_rng_state() if device=='mps' else None,draws=draws,history=hist,cutoff=data.dates[data.cut],feature_sha256=sha(HERE/'FEATURES.json'),code_sha256=source_sha,sampling_sha256=sampling_sha,factor_source_sha256=factor_source_sha,risk_source_sha256=risk_source_sha,risk_label_manifest_sha256=risk_manifest_sha,base_sha256=sha(base))
            ck['metrics_source_sha256']=METRICS_SHA;torch.save(ck,resume)
        elif step%2048==0:
            print(name,dict(step=step,progress_only=True,wall_seconds=time.monotonic()-start),flush=True)
        if step in [8192,32768,65536] or step==steps:
            tag=name+f'_B{step}';torch.save(ck,OUT/(tag+'.pt'))
            for r,card in [(data.fit_rows,'TRAIN_FITTED_DIAGNOSTIC_ONLY'),(data.dev_rows,'FORWARD_DEVELOPMENT')]:
                save_prediction(tag,data,r,predict(m,data,r,device),card)
            annual=[]
            for y,g in data.idx.iloc[data.train].groupby('year'):
                ii=g.index.to_numpy();annual.append(dict(year=int(y),actual_draws=int(draws[ii].sum()),unique_drawn=int((draws[ii]>0).sum()),eligible=len(ii),loss_mass=float(draws[ii].sum()/draws.sum()),dates_drawn=int(g.loc[draws[ii]>0,'t'].nunique()),target_year_sampling_probability=float(year_probabilities(data.years,half_life)[data.years.index(int(y))]) if half_life is not None else 1/len(data.years)))
                if path_risk:annual[-1]['actual_path_risk_draws']=int((draws[ii]*np.isfinite(data.mae[ii])).sum())
            # Actual draws, not merely eligible coverage, must span twelve anniversaries.
            actual=data.idx.loc[draws>0,'decision_date'];assert pd.Timestamp(actual.min())+pd.DateOffset(years=12)<=pd.Timestamp(actual.max())
            assert all(v['actual_draws']>0 for v in annual)
            if path_risk:
                actual_aux=data.idx.loc[(draws>0)&np.isfinite(data.mae),'decision_date']
                assert pd.Timestamp(actual_aux.min())+pd.DateOffset(years=12)<=pd.Timestamp(actual_aux.max())
                assert all(v['actual_path_risk_draws']>0 for v in annual)
            dump(tag+'_TRAINING.json',dict(config=c,steps=step,coverage=data.coverage,actual_annual_sampling=annual,actual_first=actual.min(),actual_last=actual.max(),history=hist,checkpoint_sha256=sha(OUT/(tag+'.pt')),real_task_fit='REQUIRES_FULL_FITTED_ACCOUNT_ADJUDICATION'))
    log('LONG_TRAIN_END',name=name,steps=steps)

if __name__=='__main__':
    import fcntl
    lock=open(OUT/'training.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    p=argparse.ArgumentParser();p.add_argument('--year',type=int,default=2022);p.add_argument('--baseline',action='store_true');p.add_argument('--steps',type=int,default=32768);p.add_argument('--seed',type=int,default=17);p.add_argument('--objective',type=int,choices=[2,3],default=2);p.add_argument('--weak',action='store_true');p.add_argument('--half-life',type=float,choices=[8.]);p.add_argument('--full-factors',action='store_true');p.add_argument('--factor-off',action='store_true');p.add_argument('--path-risk',action='store_true');a=p.parse_args();d=Data(a.year)
    (baseline(d,a.year) if a.baseline else fit(d,a.year,a.seed,a.steps,a.objective,a.weak,a.half_life,a.full_factors,a.factor_off,a.path_risk))
