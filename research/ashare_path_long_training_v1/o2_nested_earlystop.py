"""H2 nested O2 duration experiment; isolated outputs, one resumable trajectory per fold."""
import argparse, ast, fcntl, os, subprocess, sys, time, traceback
import joblib
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, LogisticRegression
from common import HERE, OUT, PANEL, ROOT, sha, now, old, np, json, Path
from train import Data, mature, PathResidual, predict
from sampling import draw

DOC=HERE/'account_diversification_v1'
DEST=OUT/'account_diversification_v1/o2_nested_earlystop_v1'
PROTOCOL=DOC/'O2_NESTED_EARLYSTOP_PROTOCOL.json'
PYTHON='/opt/anaconda3/bin/python'
PASSES=[.25,.5,1.,2.,4.]

def write(path,value,immutable=False):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if immutable and path.exists():
        assert json.loads(path.read_text())==value, f'Immutable identity conflict: {path}'
        return
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,indent=2,default=str)+'\n');tmp.replace(path)

def birth(pid):
    return subprocess.check_output(['ps','-p',str(pid),'-o','lstart='],text=True).strip()

def state(**fields):
    p=DOC/'UNIFIED_DAG_STATE.json';v=json.loads(p.read_text());v.update(at=now(),phase='O2_NESTED_EARLYSTOP_V1',**fields);write(p,v)

def deadline():
    from risk_incrementality import contract
    import datetime
    assert datetime.datetime.now(datetime.timezone.utc)<datetime.datetime.fromisoformat(contract()['hard_deadline']), 'RESOURCE_HARD_DEADLINE'

def fold_spec(year,idx,labels,dates):
    cut=int(np.searchsorted(dates,f'{year-1}-07-01')-1)
    end=int(np.searchsorted(dates,f'{year}-01-01')-1)
    mask=(idx.t.to_numpy()+21<=cut)&np.isfinite(labels[:,1])
    r=idx.loc[mask];first=pd.Timestamp(r.decision_date.min());last=pd.Timestamp(r.decision_date.max());n=len(r)
    assert first+pd.DateOffset(years=12)<=last,(year,first,last)
    assert sorted(r.year.unique())==list(range(first.year,last.year+1))
    steps=[int(np.floor(n*p/256+.5)) for p in PASSES]
    assert len(set(steps))==5 and 0<steps[0]<steps[-1]<32768
    inner=(idx.t.to_numpy()>cut)&(idx.t.to_numpy()<=end)
    imature=inner&(idx.t.to_numpy()+21<=end)&np.isfinite(labels[:,1])
    return dict(outer_year=year,seed=17,gradient_cutoff=str(dates[cut]),cut=cut,internal_end=end,
                internal_start=str(dates[cut+1]),internal_last=str(dates[end]),
                first_supervised=str(first.date()),last_supervised=str(last.date()),
                effective_years=(last-first).days/365.2425,anniversary_gate=True,
                mature_ret20_samples=n,internal_mature_ret20_samples=int(imature.sum()),
                candidate_steps=steps,actual_passes=[s*256/n for s in steps],
                final_step=32768)

def preflight():
    assert Path('/Volumes/quant').is_mount();deadline();DEST.mkdir(parents=True,exist_ok=True)
    dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates']);assert dates[-1]<'2024'
    idx=pd.read_parquet(OUT/'index.parquet');labels=np.load(OUT/'labels.npy',mmap_mode='r')
    specs=[fold_spec(y,idx,labels,dates) for y in range(2020,2024)]
    manifest=json.loads((HERE/'FEATURES.json').read_text())
    asset=next(a for a in json.loads((HERE/'RESEARCH_REGISTRY.json').read_text())['assets'] if a['asset_id']=='CY-WAVE-LONG-TRAINING-2007-2023')
    assert asset['lineage']['manifest_sha256']==sha(HERE/'FEATURES.json')
    for b in manifest['hashes']:assert sha(b['path'])==b['sha256'],b['path']
    bindings=[]
    entries=json.loads((DOC/'FROZEN_ALPHA_CHECKPOINT_MANIFEST.json').read_text())['checkpoints']
    for yr in range(2020,2024):
        e=next(e for e in entries if e['year']==yr and e['seed']==17)
        cp=Path(e['checkpoint_path']);assert sha(cp)==e['checkpoint_sha256']
        assert sha(e['archived_training_source'])==e['source_hash']
        assert sha(e['archived_model_source'])==sha(HERE.parent/'ashare_wave_adaptive_path_v3/model.py')
        ck=torch.load(cp,map_location='cpu',weights_only=False)
        assert ck['step']==32768 and ck['config']['objective']==2 and ck['config']['batch']==256
        assert sha(OUT/f'M0_CONTEXT_{yr}.joblib')==ck['base_sha256']
        bindings.append(dict(year=yr,path=str(cp),sha256=sha(cp),config=ck['config'],source=e['archived_training_source'],source_sha256=e['source_hash']))
    files=[Path(__file__),HERE/'o2_nested_evaluate.py',HERE/'train.py',HERE/'sampling.py',HERE/'common.py',HERE/'account_daily_inference.py',HERE/'prepare.py',HERE.parent/'ashare_wave_adaptive_path_v3/model.py']
    sources=[dict(path=str(p),sha256=sha(p)) for p in files]
    protocol=dict(version='H2_REVISION_1',folds=specs,seed_stage_a=17,stage_b_seeds=[29,43],batch_size=256,passes=PASSES,
        internal_selector='lowest sample-weighted MSE20 over every mature cached H2 validation row; exact tie earlier step',
        internal_grid='Original registered feature-store decision grid; no random validation probe',
        validation_maturity='Every target ends within internal year; internal H2 contributes no gradient or M0 fitting',
        baseline_fit='Same frozen Ridge/scaler/classifier recipe, fitted only on nested gradient rows; shared by early and matched32k',
        comparisons={'A':'EARLYSTOP minus MATCHED_NESTED_32K: duration','B':'MATCHED_NESTED_32K minus ORIGINAL_INCUMBENT_32K: training-window effect','C':'EARLYSTOP minus ORIGINAL_INCUMBENT_32K: practical deployment'},
        gate=dict(primary_comparison='A',original_practical_comparison='C reported separately',mse_improved_years=3,
                  global_equal_year_average_delta_min=0,tail='Both Top1 and Top5 LocalIC improved in >=3 years OR both K5 and K10 lift improved in >=3 years',
                  catastrophic='Negative yearly paired effect with HAC20 95% upper bound <0, for global IC or both selected tail metrics',
                  isolated_month='Winning tail branch remains positive on equal-year average after removing its single best improvement month',
                  significance='Not required for improvements; adverse interval used only to operationalize undefined catastrophic language before new outer results'),
        incumbent_bindings=bindings,sources=sources,feature_manifest_sha256=sha(HERE/'FEATURES.json'),input_hashes=manifest['hashes'],
        no_account_stage_a=True,sealed_years=[2024,2025,2026],frontier='H20_FIXED_3SEED_PERCENTILE_RANK_CONSENSUS_TOP10',
        resource_deadline_not_reset=True)
    write(PROTOCOL,protocol,immutable=True)
    for b in sources:
        p=Path(b['path']);q=DEST/'source_snapshots'/f"{b['sha256']}_{p.name}";q.parent.mkdir(exist_ok=True);q.write_bytes(p.read_bytes())
    pd.DataFrame(specs).to_csv(DOC/'O2_NESTED_EARLYSTOP_PREFLIGHT.csv',index=False)
    (DOC/'O2_NESTED_EARLYSTOP_PREFLIGHT.md').write_text('# H2 nested early-stopping preflight\n\nPASS: all four folds satisfy the unchanged twelve-anniversary gate.\n\n'+pd.DataFrame(specs)[['outer_year','gradient_cutoff','first_supervised','last_supervised','effective_years','mature_ret20_samples','candidate_steps']].to_markdown(index=False)+'\n\nOne trajectory per fold, batch256, original O2 AdamW constant LR, no schedule added. Early selection uses only H2 mature labels; 32k is excluded from candidate selection. M0 preprocessing/offset is refitted using only the same nested training rows, preventing validation leakage. Full source identities and predeclared gate interpretation: O2_NESTED_EARLYSTOP_PROTOCOL.json.\n\nA isolates duration; B measures withheld-window effect; C measures deployment replacement. Stage A seed17 only; no account or reserved-year evaluation.\n')
    print(pd.DataFrame(specs).to_string(index=False),flush=True)
    return protocol

class NestedData(Data):
    def __init__(self,spec):
        self.idx=pd.read_parquet(OUT/'index.parquet');self.t=self.idx.t.to_numpy()
        self.dates=np.array(json.loads((PANEL/'axes.json').read_text())['dates']);assert self.dates[-1]<'2024'
        self.cut=spec['cut'];self.end=spec['internal_end']
        self.raw=np.load(OUT/'raw.npy',mmap_mode='r');self.legs=np.load(OUT/'legs.npy',mmap_mode='r')
        self.factors=np.load(OUT/'factors.npy',mmap_mode='r');self.labels=np.load(OUT/'labels.npy',mmap_mode='r')
        self.y=mature(self.labels,self.t,self.cut);self.eval_y=mature(self.labels,self.t,self.end)
        self.train=np.flatnonzero(np.isfinite(self.y[:,1]));self.dev_rows=np.flatnonzero((self.t>self.cut)&(self.t<=self.end)&np.isfinite(self.eval_y[:,1]))
        assert len(self.train)==spec['mature_ret20_samples'] and len(self.dev_rows)==spec['internal_mature_ret20_samples']
        assert not np.intersect1d(self.train,self.dev_rows).size
        for k,h in enumerate([10,20,40]):assert np.all(self.t[np.isfinite(self.y[:,k])]+1+h<=self.cut)
        self.groups={int(y):[g.index.to_numpy() for _,g in z.groupby('t')] for y,z in self.idx.iloc[self.train].groupby('year')}
        self.years=sorted(self.groups);self.offset=None;self.factor_context=None;self.path_risk=False;self.weights=np.zeros(len(self.idx))
        for groups in self.groups.values():
            for rows in groups:self.weights[rows]=1/len(self.years)/len(groups)/len(rows)

def fit_base(d,dest):
    path=dest/'M0.joblib';proof=dest/'M0.json';off=dest/'offset.npy'
    if proof.exists():
        b=json.loads(proof.read_text());assert sha(path)==b['sha256'] and sha(off)==b['offset_sha256']
        d.offset=np.load(off,mmap_mode='r');return
    # Identical train.baseline recipe; output namespace and diagnostics only differ.
    x=np.nan_to_num(d.factors).astype('float64');scale=StandardScaler().fit(x[d.train],sample_weight=d.weights[d.train]);x=scale.transform(x)
    fits=[];pred=np.zeros((len(x),3),np.float32)
    for k in range(3):
        rows=d.train[np.isfinite(d.y[d.train,k])];w=d.weights[rows];w=w/w.mean()
        f=Ridge(alpha=100).fit(x[rows],d.y[rows,k],sample_weight=w);fits.append(f);pred[:,k]=f.predict(x)
    binary=[];target=d.y[d.train,1];w=d.weights[d.train];w=w/w.mean()
    for y in [target>0,target>.1,target<-.1]:binary.append(LogisticRegression(C=1,max_iter=300).fit(x[d.train],y,sample_weight=w))
    tmp=dest/'M0.tmp.joblib';joblib.dump(dict(scale=scale,fits=fits,probability_fits=binary,cutoff=d.dates[d.cut],feature_sha256=sha(HERE/'FEATURES.json')),tmp);tmp.replace(path)
    tmp=dest/'offset.tmp.npy';np.save(tmp,pred);tmp.replace(off)
    write(proof,dict(sha256=sha(path),offset_sha256=sha(off),cutoff=str(d.dates[d.cut]),samples=len(d.train)))
    d.offset=np.load(off,mmap_mode='r')

def save_ck(path,ck):
    tmp=path.with_suffix('.tmp.pt');torch.save(ck,tmp);tmp.replace(path)

def train_fold(year,seed=17):
    p=json.loads(PROTOCOL.read_text());assert seed==17,'Stage A only; seed expansion requires separate adjudication'
    for b in p['sources']:assert sha(b['path'])==b['sha256'],b['path']
    spec=next(s for s in p['folds'] if s['outer_year']==year);dest=DEST/f'{year}_s{seed}';dest.mkdir(parents=True,exist_ok=True)
    if (dest/'COMPLETE.json').exists():
        done=json.loads((dest/'COMPLETE.json').read_text());assert sha(dest/'step32768.pt')==done['checkpoint_sha256'];return
    d=NestedData(spec);fit_base(d,dest);deadline()
    torch.set_num_threads(2);device='mps' if torch.backends.mps.is_available() else 'cpu'
    torch.manual_seed(seed);rng=np.random.default_rng(seed);c=next(b['config'] for b in p['incumbent_bindings'] if b['year']==year)
    m=PathResidual(c).to(device);opt=torch.optim.AdamW(m.parameters(),lr=c['lr'],weight_decay=c['weight_decay']);code=old('model')
    yy=torch.tensor(d.y,device=device);tt=torch.tensor(d.t,device=device)
    draws=np.zeros(len(d.idx),np.int32);history=[];first=1;resume=dest/'resume.pt';identity=dict(protocol_sha256=sha(PROTOCOL),base_sha256=sha(dest/'M0.joblib'),year=year,seed=seed)
    if resume.exists():
        ck=torch.load(resume,map_location='cpu',weights_only=False);assert ck['identity']==identity and ck['config']==c
        m.load_state_dict(ck['state']);opt.load_state_dict(ck['optimizer']);rng.bit_generator.state=ck['numpy_rng'];torch.set_rng_state(ck['torch_rng'])
        if device=='mps':torch.mps.set_rng_state(ck['mps_rng'])
        draws=ck['draws'];history=ck['history'];first=ck['step']+1
        for h in history:
            assert sha(dest/f"step{h['step']}.pt")==h['checkpoint_sha256']
    start=time.monotonic();print('TRAIN_START',year,seed,device,first,spec,flush=True)
    for step in range(first,32769):
        if step%128==1:deadline()
        m.train();rows=draw(d,rng);assert len(rows)==256;np.add.at(draws,rows,1)
        x,l=d.batch(rows,device);opt.zero_grad();loss=code.objective(m,x,l,yy[rows],tt[rows],c['consistency']);loss.backward();torch.nn.utils.clip_grad_norm_(m.parameters(),1);opt.step()
        checkpoint=step in spec['candidate_steps'] or step==32768
        if checkpoint or step%512==0:
            if device=='mps':torch.mps.synchronize()
            # Evaluation does not consume training RNG; restore it explicitly even on future inference changes.
            trng=torch.get_rng_state();mrng=torch.mps.get_rng_state() if device=='mps' else None
            mse=None
            if step in spec['candidate_steps']:
                pred=predict(m,d,d.dev_rows,device);mse=float(np.mean((pred[:,1]-d.eval_y[d.dev_rows,1])**2,dtype=np.float64));assert np.isfinite(mse)
            torch.set_rng_state(trng)
            if device=='mps':torch.mps.set_rng_state(mrng)
            ck=dict(identity=identity,config=c,state={k:v.detach().cpu().clone() for k,v in m.state_dict().items()},optimizer=opt.state_dict(),step=step,seed=seed,
                    numpy_rng=rng.bit_generator.state,torch_rng=trng,mps_rng=mrng,draws=draws.copy(),history=list(history),cutoff=str(d.dates[d.cut]),device=device)
            if checkpoint:
                actual=d.idx.loc[draws>0,'decision_date'];assert pd.Timestamp(actual.min())+pd.DateOffset(years=12)<=pd.Timestamp(actual.max())
                path=dest/f'step{step}.pt';save_ck(path,ck)
                if mse is not None:history.append(dict(step=step,effective_pass=step*256/len(d.train),internal_mse20=mse,checkpoint_sha256=sha(path)))
            ck['history']=list(history);save_ck(resume,ck)
            write(dest/'PROGRESS.json',dict(at=now(),step=step,total_draws=int(draws.sum()),loss=float(loss.detach().cpu()),history=history,elapsed=time.monotonic()-start))
            print('CHECKPOINT',year,step,mse,flush=True)
            if len(history)==5 and not (dest/'SELECTION.json').exists():
                best=min(history,key=lambda h:(h['internal_mse20'],h['step']))
                write(dest/'SELECTION.json',dict(identity=identity,fold=spec,internal_validation=history,selected=best,frozen_at=now(),outer_metrics_seen=False),immutable=True)
    selection=json.loads((dest/'SELECTION.json').read_text());assert len(selection['internal_validation'])==5
    write(dest/'COMPLETE.json',dict(at=now(),identity=identity,step=32768,checkpoint_sha256=sha(dest/'step32768.pt'),selection_sha256=sha(dest/'SELECTION.json'),total_draws=int(draws.sum())),immutable=True)

def run():
    lock=open(DEST/'runner.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    state(status='RUNNING',watcher_pid=os.getpid(),watcher_birth=birth(os.getpid()),child_pid=None,child_birth=None,early_stop_launch_paused=False,blocking_error=None,training_authorized=True,execution_constraint='Stage A seed17 only; H2 validation; source-frozen single trajectories; no reserved years',next='four nested trajectories -> selected/matched/incumbent signal comparison -> Stage A gate')
    for year in range(2020,2024):
        deadline();log=DOC/f'O2_NESTED_{year}_s17.log'
        with open(log,'a') as f:
            child=subprocess.Popen([PYTHON,str(Path(__file__).resolve()),'train','--year',str(year)],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
            state(status='RUNNING',child_pid=child.pid,child_birth=birth(child.pid),current_fold=year,current_task='NESTED_TRAJECTORY',child_log=str(log))
            rc=child.wait()
        write(DEST/f'{year}_s17_EXIT.json',dict(at=now(),pid=child.pid,returncode=rc))
        if rc:raise RuntimeError(f'Fold {year} exited {rc}: {log}')
    with open(DOC/'O2_NESTED_STAGE_A_EVALUATION.log','a') as f:
        child=subprocess.Popen([PYTHON,str(HERE/'o2_nested_evaluate.py')],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
        state(status='RUNNING',child_pid=child.pid,child_birth=birth(child.pid),current_task='STAGE_A_SIGNAL_EVALUATION')
        rc=child.wait()
    if rc:raise RuntimeError(f'Stage A evaluation exited {rc}')
    state(status='STAGE_A_COMPLETE_REQUIRES_EVIDENCE_ADJUDICATION',child_pid=None,child_birth=None,watcher_pid=None,watcher_birth=None,next='Read O2_NESTED_STAGE_A_REPORT.md and apply frozen gate; no automatic seed expansion before adjudication',research_terminal=False)

if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('mode',choices=['preflight','run','train']);a.add_argument('--year',type=int,choices=range(2020,2024));args=a.parse_args()
    try:
        if args.mode=='preflight':preflight()
        elif args.mode=='run':run()
        else:
            lock=open(OUT/'training.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);train_fold(args.year)
    except Exception:
        if args.mode=='run':state(status='NEEDS_AGENT_REPAIR',child_pid=None,child_birth=None,watcher_pid=None,watcher_birth=None,blocking_error=traceback.format_exc(),next='Resume o2_nested_earlystop.py run after resolving recorded failure; never delete checkpoints')
        raise
