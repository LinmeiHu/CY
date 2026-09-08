"""V4 isolation and small atomic research records."""
from pathlib import Path
import json, datetime
from ..usic_multichampion_ashare_v3.common import sha, dump, parquet, fee, quantity
HERE = Path(__file__).resolve().parent
OUT = Path('/Volumes/quant/CY_quant_research/usic_market_router_v4')
V3 = OUT.parent / 'usic_multichampion_ashare_v3'
ROUTES = [f'D{i:02d}' for i in range(10)] + ['H01', 'H02']

def log(hid, kind, evidence, change, baseline, expectation, falsifier, **extra):
    record = dict(hypothesis_id=hid, change_kind=kind, recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        evidence=evidence, economic_sequence='历史结构/收盘市场状态 -> 冻结新订单或降风险意图 -> 下一合法时点 -> 退出及标签成熟',
        formation_at='既有冻结父事件', confirmation_at='T close', decision_at='T close', execution_at='T+1 legal open',
        label_available_at='实际退出及公司行动可得后；未成熟标签不用于拟合', change=change, baseline=baseline,
        expectation=expectation, falsifier=falsifier, sample='2020-2023 CONSUMED_DEVELOPMENT; 2018-2019 warmup', **extra)
    with (HERE/'RESEARCH_LOG.jsonl').open('a') as f: f.write(json.dumps(record,ensure_ascii=False)+'\n')
