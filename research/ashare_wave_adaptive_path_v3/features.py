"""Outcome-free causal encoders. Fixed-time patches; confirmed-pivot leg prefix."""
import sys,importlib.util
import numpy as np
from numba import njit
from common import HERE,BASES,KS
sys.path.insert(0,str(HERE.parents[1]))
BASE_ARRAY=np.array(BASES,np.int64)
K_ARRAY=np.array(KS,np.float64)
RAW_CHANNELS=['log_price_vs_current','patch_return','range','body','relative_volume','relative_turnover','relative_amount','volatility','market_return','industry_excess','valid_fraction','calendar_span','calendar_position']
LEG_CHANNELS=['direction','atr_normalized_amplitude','log_return','log_duration','slope','normalized_slope','efficiency','internal_drawdown','positive_ratio','relative_volume','relative_turnover','relative_amount','origin_relative_price','end_relative_price','market_excess','volatility','completed','valid']

@njit(cache=True)
def causal_pivots(c,atr,safe,multiple):
    out=np.empty((len(c),5),np.int32);n=0;ext=-1;mode=0;threshold=0.;segment=-1;bottom=-1;top=-1;low_threshold=0.;high_threshold=0.
    for t in range(len(c)):
        if not safe[t] or not np.isfinite(atr[t]) or atr[t]<=0:
            ext=-1;mode=0;continue
        if ext<0:
            ext=t;threshold=multiple*atr[t];segment=t;bottom=t;top=t;low_threshold=threshold;high_threshold=threshold;continue
        if mode==0:
            if c[t]<c[bottom]:bottom=t;low_threshold=multiple*atr[t]
            if c[t]>c[top]:top=t;high_threshold=multiple*atr[t]
            if c[t]>=c[bottom]*(1+low_threshold):
                out[n]=np.array([bottom,t,-1,t-bottom,segment]);n+=1;mode=1;ext=t;threshold=multiple*atr[t]
            elif c[t]<=c[top]*(1-high_threshold):
                out[n]=np.array([top,t,1,t-top,segment]);n+=1;mode=-1;ext=t;threshold=multiple*atr[t]
        elif mode==1:
            if c[t]>c[ext]:ext=t;threshold=multiple*atr[t]
            if c[t]<=c[ext]*(1-threshold):
                out[n]=np.array([ext,t,1,t-ext,segment]);n+=1;mode=-1;ext=t;threshold=multiple*atr[t]
        else:
            if c[t]<c[ext]:ext=t;threshold=multiple*atr[t]
            if c[t]>=c[ext]*(1+threshold):
                out[n]=np.array([ext,t,-1,t-ext,segment]);n+=1;mode=1;ext=t;threshold=multiple*atr[t]
    return out[:n]


@njit(cache=True)
def raw_at(x,safe,t,bases):
 # x columns close,open,high,low,volume,turnover,amount,marketclose,industryreturn
 start=t
 while start>0 and safe[start-1]:start-=1
 out=np.zeros((3,4,32,13),np.float32)
 c=x[t,0]
 recent=x[max(start,t-19):t+1]
 av=np.empty(3)
 for a in range(3):av[a]=max(np.mean(recent[:,4+a]),1e-12)
 for b in range(3):
  for w in range(4):
   window=bases[b,w]
   for p in range(32):
    lo=t-window+1+(p*window)//32;hi=t-window+((p+1)*window)//32;width=hi-lo+1;aa=max(start,lo);bb=min(t,hi)
    if aa>bb:continue
    n=bb-aa+1;v=out[b,w,p]
    v[0]=np.log(x[bb,0]/c);v[1]=np.log(x[bb,0]/x[aa,1]);v[2]=np.log(np.max(x[aa:bb+1,2])/np.min(x[aa:bb+1,3]));v[3]=(x[bb,0]-x[aa,1])/x[aa,1]
    for a in range(3):v[4+a]=np.log(max(np.mean(x[aa:bb+1,4+a]),1e-12)/av[a])
    rets=np.empty(n);ir=0.
    for j in range(n):
     z=aa+j;rets[j]=np.log(x[z,0]/x[max(start,z-1),0]);ir+=x[z,8]
    v[7]=np.std(rets);v[8]=np.log(x[bb,7]/x[max(0,aa-1),7]);v[9]=np.sum(rets)-ir
    v[10]=n/width;v[11]=width/16.;v[12]=(hi-t)/512.
 return out

@njit(cache=True)
def leg(x,atr,a,b,t,complete):
 out=np.zeros(18,np.float32)
 if b<=a:return out
 n=b-a;lr=np.log(x[b,0]/x[a,0]);av=max(atr[a],.0001)
 rets=np.empty(n);high=x[a,0];dd=0.;pos=0
 for q in range(n):
  z=a+q+1;rets[q]=np.log(x[z,0]/x[z-1,0]);high=max(high,x[z,0]);dd=min(dd,x[z,0]/high-1);pos+=rets[q]>0
 out[0]=np.sign(lr);out[1]=lr/av;out[2]=lr;out[3]=np.log1p(n);out[4]=lr/n;out[5]=lr/(av*n);out[6]=abs(lr)/max(np.sum(np.abs(rets)),1e-9);out[7]=dd;out[8]=pos/n
 for k in range(3):out[9+k]=np.log(max(np.mean(x[a+1:b+1,4+k]),1e-12)/max(np.mean(x[max(0,t-19):t+1,4+k]),1e-12))
 out[12]=np.log(x[a,0]/x[t,0]);out[13]=np.log(x[b,0]/x[t,0]);out[14]=lr-np.log(x[b,7]/x[a,7]);out[15]=np.std(rets);out[16]=complete;out[17]=1
 return out

@njit(cache=True)
def leg_at(x,atr,pv,safe,t):
 start=t
 while start>0 and safe[start-1]:start-=1
 end=np.searchsorted(pv[:,1],t,side='right')
 first=end
 while first>0 and pv[first-1,0]>=start:first-=1
 out=np.zeros((16,18),np.float32)
 if end<=first:return out
 # Last unfinished leg ending t is explicit; do not call it confirmed.
 bounds=np.empty(18,np.int32);n=0
 for p in range(max(first,end-16),end):bounds[n]=pv[p,0];n+=1
 if bounds[n-1]<t:bounds[n]=t;n+=1
 for j in range(max(0,n-17),n-1):
  row=16-(n-1)+j
  if row>=0:out[row]=leg(x,atr,bounds[j],bounds[j+1],t,0. if bounds[j+1]==t else 1.)
 return out

@njit(cache=True)
def stock_features(x,atr,safe,ts):
 raws=np.empty((len(ts),3,4,32,13),np.float32);legs=np.zeros((len(ts),8,16,18),np.float32)
 for q,t in enumerate(ts):raws[q]=raw_at(x,safe,t,BASE_ARRAY)
 for k in range(8):
  pv=causal_pivots(x[:,0],atr,safe,K_ARRAY[k])
  for q,t in enumerate(ts):legs[q,k]=leg_at(x,atr,pv,safe,t)
 return raws,legs
