"""Causal close-directional-change detector. No outcomes are accepted as inputs."""
import numpy as np
from numba import njit

@njit(cache=True)
def swings(close, atr, safe, multiple):
    n=len(close)
    # armed start, peak, low and their confirmation times; pending start/peak for recency.
    trace=np.full((n,8),-1,np.int32)
    piv=np.full((n,4),-1,np.int32); npiv=0
    mode=-1; extreme=-1; threshold=.03
    origin=-1; oc=-1; peak=-1; pc=-1; oldorigin=-1; oldoc=-1
    armed=np.full(6,-1,np.int32)
    for t in range(n):
        if not safe[t] or not np.isfinite(atr[t]):
            mode=-1; extreme=-1; origin=-1; peak=-1; armed[:]=-1
            continue
        if extreme<0:
            extreme=t; threshold=max(.03,multiple*atr[t]); continue
        if mode==-1:
            if close[t]<close[extreme]:
                extreme=t; threshold=max(.03,multiple*atr[t])
            if close[t]>=close[extreme]*(1+threshold):
                piv[npiv]=np.array([extreme,t,-1,t-extreme]); npiv+=1
                if peak>=0 and oldorigin>=0:
                    dur=peak-oldorigin; cd=extreme-peak
                    if 3<=dur<=60 and 3<=cd<=40 and close[peak]/close[oldorigin]-1>=.08 and close[extreme]>close[oldorigin]:
                        armed=np.array([oldorigin,peak,extreme,oldoc,pc,t],np.int32)
                origin=extreme; oc=t; mode=1; extreme=t; threshold=max(.03,multiple*atr[t])
        else:
            if close[t]>close[extreme]:
                extreme=t; threshold=max(.03,multiple*atr[t])
            if close[t]<=close[extreme]*(1-threshold):
                piv[npiv]=np.array([extreme,t,1,t-extreme]); npiv+=1
                oldorigin=origin; oldoc=oc; peak=extreme; pc=t
                armed[:]=-1; mode=-1; extreme=t; threshold=max(.03,multiple*atr[t])
        trace[t,:6]=armed
        if armed[0]>=0:
            trace[t,6]=armed[0]; trace[t,7]=armed[1]
        elif mode==-1 and peak>=0:
            trace[t,6]=oldorigin; trace[t,7]=peak
    return trace,piv[:npiv]

@njit(cache=True)
def streak(mask):
    out=np.zeros(mask.shape,np.int16)
    for j in range(mask.shape[1]):
        for t in range(mask.shape[0]):
            if mask[t,j]: out[t,j]=1+(out[t-1,j] if t else 0)
    return out

@njit(cache=True)
def labels(op,hi,lo,pathok,entryok,exitok):
    n,m=op.shape
    rets=np.full((n,m,4),np.nan,np.float32)
    mfe=rets.copy(); mae=rets.copy()
    horizons=np.array([5,10,20,40])
    for j in range(m):
        for t in range(n-1):
            e=t+1
            if not entryok[e,j]: continue
            base=op[e,j]; mx=-np.inf; mn=np.inf; k=0
            for q in range(41):
                d=e+q
                if d>=n or not pathok[d,j]: break
                if q==horizons[k]:
                    if exitok[d,j]:
                        rets[t,j,k]=op[d,j]/base-1
                        mfe[t,j,k]=mx/base-1; mae[t,j,k]=mn/base-1
                    k+=1
                    if k==4: break
                mx=max(mx,hi[d,j]); mn=min(mn,lo[d,j])
    return rets,mfe,mae
