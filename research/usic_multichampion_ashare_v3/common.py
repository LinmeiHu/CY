"""V3 local constants and atomic artifacts; no shared-source writes."""
from pathlib import Path
import hashlib, json, os
import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = Path('/Volumes/quant/CY_quant_research/usic_multichampion_ashare_v3')
CACHE = OUT / 'cache'
LEGACY = Path('/Volumes/quant/CY_quant_research/minervini_ashare_clean_ascent_v2')
INV = Path('/Users/linmei/Documents/CY/data/input_inventories')

def sha(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def dump(p, value):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name + f'.tmp.{os.getpid()}')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str, allow_nan=False)+'\n')
    temp.replace(p)

def parquet(p, frame):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name + f'.tmp.{os.getpid()}')
    frame.to_parquet(temp, index=False); temp.replace(p)

def rank(s, low=False):
    r = s.rank(pct=True, ascending=not low, method='average')
    if s.notna().sum() == 1: r[s.notna()] = .5
    return r

def fee(value, day, sell=False, mult=1):
    transfer = .00002 if str(day)[:10] < '2022-04-29' else .00001
    stamp = (.001 if str(day)[:10] < '2023-08-28' else .0005) if sell else 0
    return mult * max(5., value*.0003) + value*(transfer+stamp)

def quantity(budget, limit, day, board, mult=1, maxq=None):
    unit, minimum, ceiling = (1, 200, 100000) if board == 'STAR' else (100, 100, 1000000)
    if not np.isfinite(limit) or limit <= 0 or budget <= 0: return 0
    q = min(int(budget/limit)//unit*unit, ceiling)
    if maxq is not None: q = min(q, int(maxq)//unit*unit)
    while q >= minimum and q*limit + fee(q*limit, day, mult=mult) > budget: q -= unit
    return q if q >= minimum else 0

def scenarios():
    return json.loads((HERE/'SCENARIO_MANIFEST.json').read_text())['scenarios']
