"""Deterministic probe objective in the same units as training, excluding jitter."""
import numpy as np

def fixed_metrics(pred,y,t,objective=2,mae=None):
    assert np.isfinite(pred).all(),'Nonfinite model output on fixed diagnostic probe'
    valid=np.isfinite(y);target=np.nan_to_num(y)*10;delta=np.abs(pred[:,:3]*10-target);w=np.array([.25,.5,.25])
    huber=float((np.where(delta<1,.5*delta**2,delta-.5)*valid*w).sum()/max(1,(valid*w).sum()))
    truth=np.column_stack([y[:,1]>0,y[:,1]>.1,y[:,1]<-.1]);mask=np.repeat(valid[:,1,None],3,axis=1)
    if mae is not None:truth[:,2]=mae<-.1;mask[:,2]=np.isfinite(mae)
    ce=np.logaddexp(0,pred[:,3:])-truth*pred[:,3:]
    aux=float(((ce*mask).sum(0)/np.maximum(1,mask.sum(0))).mean())
    previous=np.roll(np.arange(len(y)),1);paired=valid[:,1]&valid[previous,1]&(t==t[previous]);sign=np.sign(target[:,1]-target[previous,1])
    rank=float((np.logaddexp(0,-(pred[:,1]-pred[previous,1])*10*sign)*paired).sum()/max(1,paired.sum()))
    total=huber+(.1*aux if objective>=2 else 0)+(.1*rank if objective>=3 else 0)
    return dict(fixed_regression_huber=huber,fixed_aux_bce=aux,fixed_same_date_rank=rank,fixed_objective_no_consistency=total)
