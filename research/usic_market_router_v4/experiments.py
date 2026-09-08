"""Small staged account contrasts. Each invocation registers evidence before results."""
import argparse,json
import pandas as pd
from .common import HERE,OUT,V3,log,parquet,dump
from .engine import Market
from .runner import run,publish

def pool(frames,routes):
    f=pd.concat([frames[r] for r in routes],ignore_index=True)
    f['original_score']=f.score;f['score']=f.groupby(['t','route']).score.rank(pct=True,method='average')
    f['owner_tie']=f.route.map({r:i for i,r in enumerate(routes)})
    return f.sort_values(['t','score','symbol','owner_tie'],ascending=[True,False,True,True])

def config(name,mode,**kw):
    return dict(id=name+'_'+mode,mode=mode,delay=1,cost=1,exit='FIXED10',overlay='NONE',book='ENTRY_ONLY',**kw)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--stage',choices=['gates','route','confirm'],required=True);args=ap.parse_args()
    m=Market();m.v4state=pd.read_parquet(OUT/'state_daily.parquet')
    frames={r:pd.read_parquet(V3/f'{r}_signals.parquet').sort_values(['t','score','symbol'],ascending=[True,False,True]) for r in ['H02','D05','D08','H01']}
    frames['POOL']=pool(frames,['H02','D08','H01'])
    if args.stage=='gates':
        log('R1_AND_R4','NEW_ROUTER','全十二入口地图完成：LOW_NONIMPROVING并非普遍亏损，H02/H01资金PNL在该状态正；D08主要贡献来自HIGH_NONIMPROVING',
            '检验Prompt简单开关、同公式T时点与坏状态旧仓归零配对；不改策略排名', '四条独立基线/同信号固定共享POOL',
            '开关可能误关H02/H01；FULL_BOOK是否减损独立检验','较低敞口仍损失收益，或退出错过反弹')
        for mode in ['C_MAX','C_10']:
            run(m,config('R0_POOL',mode),frames['POOL'])
            # One native replay establishes unchanged-engine economic parity.
            if mode=='C_10':run(m,config('PARITY_H02',mode),frames['H02'],'VERIFICATION_REPLAY')
            for route in ['H02','D08','H01','POOL']:
                sc=config('R1_S1_'+route,mode,state_key='S1',blocked_states=['LOW_NONIMPROVING','UNKNOWN'])
                run(m,sc,frames[route]);publish()
                if route in ['H02','POOL']:
                    run(m,dict(sc,id='R4_S1_'+route+'_'+mode,book='FULL_BOOK'),frames[route]);publish()
            run(m,config('R1_CURRENT_H02',mode,state_key='S0_CURRENT',blocked_states=['BEAR']),frames['H02']);publish()
    elif args.stage=='route':
        log('R2_D08_PRIORITY','NEW_ROUTER','strategy_state_year.csv: D08 HIGH_NONIMPROVING date-weighted net positive in 2020/2021/2022, negative in 2023; S1 pooled gate loses to static pool',
            '只在HIGH_NONIMPROVING优先D08，其余保持固定共享池排序；同开关同预算同退出',
            'R1_S1_POOL and R0_POOL, each C_MAX/C_10','检验策略选择是否有开关之外增量','不能跨资本模式改善，或强依赖2020')
        f=frames['POOL'].merge(m.v4state[['t','S1']],on='t');f['priority']=((f.S1=='HIGH_NONIMPROVING')&(f.route=='D08')).astype(int)
        f=f.sort_values(['t','priority','score','symbol','owner_tie'],ascending=[True,False,False,True,True])
        for mode in ['C_MAX','C_10']:
            for gate in [True,False]:
                sc=config('R2_PRIORITY_'+('GATE' if gate else 'OPEN'),mode)
                if gate:sc.update(state_key='S1',blocked_states=['LOW_NONIMPROVING','UNKNOWN'])
                run(m,sc,f);publish()
        log('R1_D08_LEVEL','NEW_ROUTER','D08 LOW_IMPROVING date-weighted net negative in 3/4 years; low breadth nonimproving gate improved C10 but CMAX remains negative',
            '只增加LOW_IMPROVING暂停；即B60水平贡献与广度变化贡献分离',
            'R1_S1_D08 same cash/exit; fullbook paired separately','减少D08低广度修复期损失','贡献来自单一年份或低投入可完全解释')
        for mode in ['C_MAX','C_10']:
            sc=config('R1_LEVEL_D08',mode,state_key='S1',blocked_states=['LOW_NONIMPROVING','LOW_IMPROVING','UNKNOWN'])
            run(m,sc,frames['D08']);run(m,dict(sc,id='R4_LEVEL_D08_'+mode,book='FULL_BOOK'),frames['D08']);publish()
    else:raise NotImplementedError('Select at most three supported candidates first')
    publish()

if __name__=='__main__':main()
