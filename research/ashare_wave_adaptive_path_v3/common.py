from pathlib import Path
import json,hashlib,datetime
import numpy as np
HERE=Path(__file__).resolve().parent
OUT=Path('/Volumes/quant/CY_quant_research/ashare_wave_adaptive_path_v3')
SOURCE=Path('/Volumes/quant/CY_quant_research/ashare_wave_structure_v1')
BASES=[[32,64,128,256],[48,96,192,384],[64,128,256,512]]
KS=[.5,.75,1.,1.5,2.,2.5,3.,4.]
BANKS=[[0,2,4,6],[1,3,5,7],[0,3,4,7]]
COVERAGES=[.2,.1,.05,.02,.01,.005]
def get(k):return np.load(SOURCE/(k+'.npy'),mmap_mode='r')
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def dump(name,value):
 (HERE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str))
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def config_id(c):return hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest()[:12]


def mature_returns(t,j,h,cut):
 """Gather only outcomes mature by each row's cutoff; do not read then mask."""
 t=np.asarray(t);j=np.asarray(j);ok=t+1+h<=cut;out=np.full(t.shape,np.nan,dtype='float32')
 if ok.any():out[ok]=get('returns')[t[ok],j[ok],[5,10,20,40].index(h)]
 return out
