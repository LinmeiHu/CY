import math
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from common import BANKS

class PathModel(nn.Module):
 def __init__(self,c):
  super().__init__();self.c=c;h=c['hidden'];e=c['embedding'];wh=c['wave_hidden']
  self.conditioned=c.get('input_conditioning')=='train_std_and_padding_mask'
  if self.conditioned:
   self.register_buffer('raw_scale',torch.ones(13));self.register_buffer('wave_scale',torch.ones(40))
  self.raw_in=nn.Linear(13,h)
  if c['encoder']=='transformer':
   layer=nn.TransformerEncoderLayer(h,c['heads'],h*2,c['dropout'],batch_first=True,activation='gelu')
   self.raw=nn.TransformerEncoder(layer,c['depth'],enable_nested_tensor=False)
  else:
   self.raw=nn.Sequential(*[nn.Sequential(nn.Conv1d(h,h,3,padding=2**i,dilation=2**i),nn.GELU(),nn.Dropout(c['dropout'])) for i in range(c['depth'])])
  self.path_gate=nn.Linear(h,1)
  # Leg sequence has its own explicit completion/mask and positional chronology.
  self.wave_in=nn.Linear(18+22,wh);self.wave=nn.GRU(wh,wh,batch_first=True);self.wave_gate=nn.Linear(wh,1)
  self.fusion=nn.Sequential(nn.Linear(h+(wh if c['level']>=2 else 0),e),nn.GELU(),nn.Dropout(c['dropout']),nn.Linear(e,e),nn.LayerNorm(e))
  self.pred=nn.Linear(e,6)
  pos=torch.arange(32)[:,None];freq=torch.exp(torch.arange(0,h,2)*(-math.log(10000)/h));pe=torch.zeros(32,h);pe[:,0::2]=torch.sin(pos*freq);pe[:,1::2]=torch.cos(pos*freq);self.register_buffer('pos',pe*.1)

 def relations(self,l):
  prev=torch.roll(l,1,2);prev2=torch.roll(l,2,2);prev3=torch.roll(l,3,2);prev[:,:,0]=0;prev2[:,:,:2]=0;prev3[:,:,:3]=0
  amp=l[...,2].abs();pa=prev[...,2].abs().clamp_min(.001);p2a=prev2[...,2].abs().clamp_min(.001)
  duration=torch.expm1(l[...,3]).clamp_min(1);pd=torch.expm1(prev[...,3]).clamp_min(1)
  ratio=amp/pa;ext=amp/p2a
  relations=[torch.log1p(ratio),torch.log1p(ext),l[...,3]-prev[...,3],l[...,3]-prev2[...,3],torch.log1p(l[...,4].abs()/prev[...,4].abs().clamp_min(.0001)),(torch.minimum(torch.maximum(l[...,12],l[...,13]),torch.maximum(prev[...,12],prev[...,13]))-torch.maximum(torch.minimum(l[...,12],l[...,13]),torch.minimum(prev[...,12],prev[...,13]))).clamp_min(0)/pa,ratio-torch.roll(ratio,2,2),l[...,3]-prev2[...,3],l[...,15]-prev2[...,15],l[...,6]-prev2[...,6],l[...,5]-prev2[...,5],l[...,9]-prev[...,9],l[...,10]-prev[...,10],l[...,11]-prev[...,11]]
  if self.c['amplitude_off']:
   for k in [0,1,4,5,6,10]:relations[k]=torch.zeros_like(amp)
  if self.c['time_off']:
   for k in [2,3,4,7,10]:relations[k]=torch.zeros_like(amp)
  for center in [.382,.5,.618]:relations.append(torch.exp(-.5*((ratio-center)/self.c['fib_sigma'])**2))
  for center in [1.,1.272,1.618,2.,2.618]:relations.append(torch.exp(-.5*((ext-center)/self.c['fib_sigma'])**2))
  r=torch.stack(relations,-1).clamp(-10,10)
  if self.c['level']<3:r=r*0
  elif self.c['level']<4:r[...,14:]=0
  if self.c['amplitude_off']:r[...,14:]=0
  r=r*l[...,17:18]*prev[...,17:18]
  for k in [1,3,7,8,9,10,17,18,19,20,21]:r[...,k]=r[...,k]*prev2[...,17]
  r[...,6]=r[...,6]*prev3[...,17]
  return r

 def forward(self,x,l):
  c=self.c;x=x.clone();l=l.clone();batch=x.shape[0]
  if c['context']==0:x[...,8:10]=0;l[...,14]=0
  elif c['context']==1:x[...,9]=0
  if c['time_off']:x[...,11:13]=0
  mask=x[...,10:11];m=mask.reshape(-1,32,1)
  if self.conditioned:x=(x/self.raw_scale).clamp(-10,10)
  v=self.raw_in(x);v=v.reshape(-1,32,c['hidden'])
  if self.conditioned:v=v*(m>0)
  if not c['time_off']:
   if c['encoder']=='transformer':
    v=self.raw(v+self.pos,src_key_padding_mask=(m.squeeze(-1)<=0)) if self.conditioned else self.raw(v+self.pos)
   elif self.conditioned:
    v=v.transpose(1,2)
    for block in self.raw:v=block(v)*(m.transpose(1,2)>0)
    v=v.transpose(1,2)
   else:v=self.raw(v.transpose(1,2)).transpose(1,2)
  v=(v*m).sum(1)/m.sum(1).clamp_min(1);v=v.reshape(batch,4,-1)
  weights=torch.softmax(self.path_gate(v).squeeze(-1),-1)
  if c['fixed_scale']:weights=torch.zeros_like(weights);weights[:,-1]=1
  p=(v*weights[...,None]).sum(1)
  if c['level']>=2:
   rel=self.relations(l)
   if c['time_off']:l[...,[3,4,5]]=0
   # Relative-amplitude ablation removes explicit ratios, retains raw leg returns (clean incremental test).
   tokens=torch.cat([l,rel],-1)
   if self.conditioned:tokens=(tokens/self.wave_scale).clamp(-10,10)
   w=self.wave_in(tokens)
   if self.conditioned:w=w*l[...,17:18]
   w=w.reshape(-1,c['legs'],c['wave_hidden'])
   if c['time_off']:w=w.mean(1)
   else:w=self.wave(w)[0][:,-1]
   w=w.reshape(batch,4,-1);wm=l[...,17].sum(-1)>0;ww=self.wave_gate(w).squeeze(-1).masked_fill(~wm,-20);ww=ww.softmax(-1);w=(w*ww[...,None]).sum(1);p=torch.cat([p,w],-1)
  z=self.fusion(p);pred=self.pred(z);return pred,z,weights

def objective(model,x,l,y,t,consistency=0):
 pred,z,_=model(x,l);valid=torch.isfinite(y);target=torch.nan_to_num(y)*10
 reg=F.smooth_l1_loss(pred[:,:3],target,reduction='none');weights=torch.tensor([.25,.5,.25],device=x.device)
 loss=(reg*valid*weights).sum()/(valid*weights).sum().clamp_min(1)
 if model.c['objective']>=2:
  yc=torch.stack([y[:,1]>0,y[:,1]>.1,y[:,1]<-.1],1).float();mask=valid[:,1:2];ce=F.binary_cross_entropy_with_logits(pred[:,3:],yc,reduction='none');loss=loss+.1*(ce*mask).sum()/(mask.sum()*3).clamp_min(1)
 if model.c['objective']>=3:
  idx=torch.roll(torch.arange(len(y),device=x.device),1);ok=valid[:,1]&valid[idx,1]&(t==t[idx]);sgn=torch.sign(target[:,1]-target[idx,1]);rank=F.softplus(-(pred[:,1]-pred[idx,1])*sgn);loss=loss+.1*(rank*ok).sum()/ok.sum().clamp_min(1)
 if consistency:
  if model.conditioned:
   jitter=x.clone();jitter[...,:10]+=torch.randn_like(x[...,:10])*.001*x[...,10:11]
  else:jitter=x+torch.randn_like(x)*.001
  pred2,z2,_=model(jitter,l);loss=loss+consistency*(1-F.cosine_similarity(z,z2)).mean()
 return loss
