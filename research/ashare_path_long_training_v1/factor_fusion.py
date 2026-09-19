"""Explicit14-factor residual interface, with a capacity-matched factor ablation."""
import torch
from torch import nn
from common import old,sha,Path
SOURCE_SHA=sha(Path(__file__))

class FullFactorResidual(nn.Module):
    def __init__(self,c):
        super().__init__();assert c['level']==1
        self.c=c;self.conditioned=False;self.core=old('model').PathModel(c)
        e=c['embedding'];self.factor_fusion=nn.Sequential(nn.Linear(e+28,e),nn.GELU(),nn.Dropout(c['dropout']),nn.LayerNorm(e));self.extra_head=nn.Linear(e,6)
        with torch.no_grad():
            self.core.pred.weight[:3].zero_();self.core.pred.bias[:3].zero_();self.extra_head.weight.zero_();self.extra_head.bias.zero_()

    def forward(self,x,l):
        assert x.shape[-1]==44
        p,z,w=self.core(x[...,:13],l);factors=x[:,0,0,16:44]
        if self.c.get('factor_context_off'):factors=torch.zeros_like(factors)
        p=p+self.extra_head(self.factor_fusion(torch.cat([z,factors],1)))
        # Existing consistency penalty still applies to the same raw-path embedding.
        return torch.cat([p[:,:3]+10*x[:,0,0,13:16],p[:,3:]],1),z,w
