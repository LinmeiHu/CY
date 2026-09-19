"""Same regression/capacity; replace terminal-loss auxiliary target with path risk."""
import torch
from torch.nn import functional as F
from common import sha,Path
SOURCE_SHA=sha(Path(__file__))

def objective(model,x,l,y,t,mae,consistency=0):
    assert model.c['objective']==2
    pred,z,_=model(x,l);valid=torch.isfinite(y);target=torch.nan_to_num(y)*10;weights=torch.tensor([.25,.5,.25],device=x.device)
    reg=F.smooth_l1_loss(pred[:,:3],target,reduction='none');loss=(reg*valid*weights).sum()/(valid*weights).sum().clamp_min(1)
    truth=torch.stack([y[:,1]>0,y[:,1]>.1,mae<-.1],1).float();mask=torch.stack([valid[:,1],valid[:,1],torch.isfinite(mae)],1)
    ce=F.binary_cross_entropy_with_logits(pred[:,3:],truth,reduction='none')
    # Each auxiliary head retains coefficient0.1/3; missing path labels do not
    # increase the weight of the other heads or remove primary supervision.
    loss=loss+(.1/3)*((ce*mask).sum(0)/mask.sum(0).clamp_min(1)).sum()
    if consistency:
        jitter=x+torch.randn_like(x)*.001;_,z2,_=model(jitter,l)
        loss=loss+consistency*(1-F.cosine_similarity(z,z2)).mean()
    return loss
