from pathlib import Path
import json, hashlib, datetime, importlib.util, sys, tempfile
import numpy as np
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = HERE.parent / 'ashare_path_autonomous_v4'
OUT = Path('/Volumes/quant/CY_quant_research/ashare_path_long_training_v1')
PANEL = OUT / 'panel'
LIFE = HERE.parent / 'ashare_wave_lifecycle_v2r1'
OUT.mkdir(parents=True, exist_ok=True)
def sha(p):
    with open(p,'rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def dump(name,v):
    p=HERE/name
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=p.parent,prefix=p.name+'.',suffix='.tmp',delete=False) as f:
        tmp=Path(f.name);f.write(json.dumps(v,ensure_ascii=False,indent=2,default=str)+'\n')
    tmp.replace(p)
def get(k): return np.load(PANEL/(k+'.npy'),mmap_mode='r')
def module(name,p):
    if name in sys.modules:return sys.modules[name]
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);sys.modules[name]=m;sys.modules[p.stem]=m
    if p.stem=='features':sys.modules['_v4_readonly_v3_features']=m
    s.loader.exec_module(m);return m
def old(name):
    key='_long_v3_'+name
    if key in sys.modules:return sys.modules[key]
    prior=sys.modules.get('common')
    if name!='common':sys.modules['common']=old('common')
    try:return module(key,HERE.parent/'ashare_wave_adaptive_path_v3'/(name+'.py'))
    finally:sys.modules['common']=prior
def log(event,**kw):
    with open(HERE/'EXPERIMENT_LOG.jsonl','a') as f:f.write(json.dumps(dict(at=now(),event=event,**kw),ensure_ascii=False,default=str)+'\n')
