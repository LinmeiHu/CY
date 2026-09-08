from pathlib import Path
import datetime, hashlib, json

HERE=Path(__file__).resolve().parent
OUT=Path('/Volumes/quant/CY_quant_research/usic_d08_entry_timing_v5')
V3=OUT.parent/'usic_multichampion_ashare_v3'
V4=OUT.parent/'usic_market_router_v4'
OUT.mkdir(parents=True,exist_ok=True)

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def dump(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')

def log(hid,evidence,hypothesis,change,baseline,expected,falsifier,**extra):
    row=dict(hypothesis_id=hid,recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        evidence=evidence,economic_sequence='T日信号与冻结结构 -> T+1开盘或收盘可见信息 -> 预定合法开盘执行 -> 冻结E10退出',
        hypothesis=hypothesis,change=change,baseline=baseline,expected=expected,falsifier=falsifier,
        sample='2020-2023 CONSUMED_DEVELOPMENT; 2018-2019 warmup',**extra)
    with (HERE/'RESEARCH_LOG.jsonl').open('a') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
