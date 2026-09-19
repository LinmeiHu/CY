"""Minimal, exact MASTER core used by the Mac/MPS feasibility gate."""
from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 100):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(max_len, dtype=torch.float32).unsqueeze(1)
        div = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div)
        pe[:, 1::2] = torch.cos(position * div)
        self.register_buffer("pe", pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return x + self.pe[: x.shape[1]]


class Gate(nn.Module):
    def __init__(self, market_dim: int, d_feat: int, beta: float = 2.0):
        super().__init__()
        self.trans = nn.Linear(market_dim, d_feat)
        self.d_feat = d_feat
        self.beta = beta
        # CY predeclared neutral initialization: d_feat * softmax(0) == 1.
        nn.init.zeros_(self.trans.weight)
        nn.init.zeros_(self.trans.bias)

    def forward(self, market: torch.Tensor) -> torch.Tensor:
        return self.d_feat * torch.softmax(self.trans(market) / self.beta, dim=-1)


class TAttention(nn.Module):
    """Official temporal attention: deliberately no 1/sqrt(d_head) scaling."""
    def __init__(self, d_model: int, nhead: int, dropout: float):
        super().__init__()
        self.d_model, self.nhead = d_model, nhead
        self.qtrans = nn.Linear(d_model, d_model, bias=False)
        self.ktrans = nn.Linear(d_model, d_model, bias=False)
        self.vtrans = nn.Linear(d_model, d_model, bias=False)
        self.attn_dropout = nn.ModuleList([nn.Dropout(dropout) for _ in range(nhead)])
        self.norm1 = nn.LayerNorm(d_model, eps=1e-5)
        self.norm2 = nn.LayerNorm(d_model, eps=1e-5)
        self.ffn = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Dropout(dropout),
                                 nn.Linear(d_model, d_model), nn.Dropout(dropout))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm1(x)
        q, k, v = self.qtrans(x), self.ktrans(x), self.vtrans(x)
        d = self.d_model // self.nhead
        pieces = []
        for h in range(self.nhead):
            sl = slice(h * d, None if h == self.nhead - 1 else (h + 1) * d)
            a = torch.softmax(q[:, :, sl] @ k[:, :, sl].transpose(1, 2), dim=-1)
            pieces.append(self.attn_dropout[h](a) @ v[:, :, sl])
        message = torch.cat(pieces, dim=-1)
        y = self.norm2(x + message)
        return y + self.ffn(y)


class SAttention(nn.Module):
    """Exact all-stock attention with optional exact query chunking/checkpointing."""
    def __init__(self, d_model: int, nhead: int, dropout: float, query_chunk: int | None = None,
                 checkpoint_chunks: bool = False, use_sdpa: bool = False):
        super().__init__()
        self.d_model, self.nhead = d_model, nhead
        self.temperature = math.sqrt(d_model / nhead)
        self.query_chunk = query_chunk
        self.checkpoint_chunks = checkpoint_chunks
        self.use_sdpa = use_sdpa
        self.dropout_p = dropout
        self.qtrans = nn.Linear(d_model, d_model, bias=False)
        self.ktrans = nn.Linear(d_model, d_model, bias=False)
        self.vtrans = nn.Linear(d_model, d_model, bias=False)
        self.attn_dropout = nn.Dropout(dropout)
        self.norm1 = nn.LayerNorm(d_model, eps=1e-5)
        self.norm2 = nn.LayerNorm(d_model, eps=1e-5)
        self.ffn = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Dropout(dropout),
                                 nn.Linear(d_model, d_model), nn.Dropout(dropout))

    def _attend(self, q: torch.Tensor, k: torch.Tensor, v: torch.Tensor) -> torch.Tensor:
        # q [T,H,Q,d], k/v [T,H,N,d]. Boolean/padding masks are absent because U_t
        # contains only ex-ante legal context rows; missing labels are loss-mask only.
        if self.use_sdpa:
            return F.scaled_dot_product_attention(
                q, k, v, dropout_p=self.dropout_p if self.training else 0.0,
                is_causal=False, scale=1.0 / self.temperature,
            )
        a = torch.softmax(torch.matmul(q, k.transpose(-1, -2)) / self.temperature, dim=-1)
        return torch.matmul(self.attn_dropout(a), v)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm1(x)
        n, t, _ = x.shape
        d = self.d_model // self.nhead
        def shape(z: torch.Tensor) -> torch.Tensor:
            return z.view(n, t, self.nhead, d).permute(1, 2, 0, 3)
        q, k, v = shape(self.qtrans(x)), shape(self.ktrans(x)), shape(self.vtrans(x))
        chunk = self.query_chunk or n
        pieces = []
        for lo in range(0, n, chunk):
            qc = q[:, :, lo : lo + chunk]
            if self.checkpoint_chunks and self.training:
                out = checkpoint(self._attend, qc, k, v, use_reentrant=False, preserve_rng_state=True)
            else:
                out = self._attend(qc, k, v)
            pieces.append(out)
        message = torch.cat(pieces, dim=2).permute(2, 0, 1, 3).reshape(n, t, self.d_model)
        y = self.norm2(x + message)
        return y + self.ffn(y)


class StockDisabledControl(nn.Module):
    """Same normalization/residual/FFN semantics with the stock message removed."""
    def __init__(self, d_model: int, dropout: float):
        super().__init__()
        self.norm1 = nn.LayerNorm(d_model, eps=1e-5)
        self.norm2 = nn.LayerNorm(d_model, eps=1e-5)
        self.ffn = nn.Sequential(nn.Linear(d_model, d_model), nn.ReLU(), nn.Dropout(dropout),
                                 nn.Linear(d_model, d_model), nn.Dropout(dropout))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.norm1(x)
        y = self.norm2(x)
        return y + self.ffn(y)


class TemporalPool(nn.Module):
    def __init__(self, d_model: int):
        super().__init__()
        self.trans = nn.Linear(d_model, d_model, bias=False)

    def forward(self, z: torch.Tensor) -> torch.Tensor:
        h = self.trans(z)
        weights = torch.softmax((h @ h[:, -1].unsqueeze(-1)).squeeze(-1), dim=1).unsqueeze(1)
        return (weights @ z).squeeze(1)


@dataclass(frozen=True)
class ModelOptions:
    gate: bool
    stock: bool


ARMS = {
    "M-T": ModelOptions(False, False),
    "M-GT": ModelOptions(True, False),
    "M-TS": ModelOptions(False, True),
    "M-GTS": ModelOptions(True, True),
}


class FullMaster(nn.Module):
    def __init__(self, arm: str = "M-GTS", d_feat: int = 158, market_dim: int = 63,
                 d_model: int = 256, t_nhead: int = 4, s_nhead: int = 2,
                 dropout: float = 0.5, beta: float = 2.0, query_chunk: int | None = None,
                 checkpoint_chunks: bool = False, use_sdpa: bool = False):
        super().__init__()
        options = ARMS[arm]
        self.arm, self.options = arm, options
        self.gate = Gate(market_dim, d_feat, beta) if options.gate else None
        self.input_proj = nn.Linear(d_feat, d_model)
        self.pos = PositionalEncoding(d_model)
        self.temporal = TAttention(d_model, t_nhead, dropout)
        self.stock = (SAttention(d_model, s_nhead, dropout, query_chunk, checkpoint_chunks, use_sdpa)
                      if options.stock else StockDisabledControl(d_model, dropout))
        self.pool = TemporalPool(d_model)
        self.head = nn.Linear(d_model, 1)

    def forward(self, x: torch.Tensor, market: torch.Tensor) -> torch.Tensor:
        if self.gate is not None:
            x = x * self.gate(market).view(1, 1, -1)
        x = self.pos(self.input_proj(x))
        x = self.temporal(x)
        x = self.stock(x)
        return self.head(self.pool(x)).squeeze(-1)

    def active_parameter_count(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)
