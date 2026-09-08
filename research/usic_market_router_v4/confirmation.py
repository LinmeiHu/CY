"""Finite exposure controls, real execution stress, and consumed-data past-only reconstruction."""
import json
import numpy as np
import pandas as pd
from .common import HERE,OUT,V3,log,parquet,dump
from .market import Market
from .experiments import config
from .runner import run,publish

def main():
    m=Market();m.v4state=pd.read_parquet(OUT/'state_daily.parquet');f=pd.read_parquet(V3/'D08_signals.parquet').sort_values(['t','score','symbol'],ascending=[True,False,True])
    simple=['LOW_NONIMPROVING','UNKNOWN'];level=simple+['LOW_IMPROVING']
    log('R3_BUDGET','RISK_VARIANT','D08 high/nonimproving strongest; CMAX loses despite similar win rate; FULL_BOOK level C10 nearly flat',
        '高广度改善中目标50%、高广度不改善100%、低广度0%；与固定25/50/75/100%同路线曲线比较',
        'R1_LEVEL_D08 and fixed D08 budgets','若风险投入有价值，应超越固定降投入的描述性前沿','只是平均敞口降低或投资集合随机漂移')
    for mode in ['C_MAX','C_10']:
        for b in [.25,.5,.75]:run(m,config('FIXED_'+str(int(b*100))+'_D08',mode,fixed_budget=b),f);publish()
        sc=config('R3_HALF_D08',mode,state_key='S1',blocked_states=level,budgets={'HIGH_IMPROVING':.5,'HIGH_NONIMPROVING':1.})
        run(m,sc,f);publish()
    log('CONFIRM_D08','EXECUTION_VARIANT','D08 simple gate C10 +22.04%, DD13.83%; level gate tests incremental breadth-level contribution',
        '只确认S1简单开关及LEVEL两个候选：COST2、冻结原信号的一日延迟、唯一3日坏状态确认邻居；必要C_ONE压力',
        '相同政策原成本及D08原入口','边际改善不应依赖单次开盘/状态抖动','成本延迟后增量消失或反转；集中失败明确限制')
    for policy,blocked in [('R1_S1_D08',simple),('R1_LEVEL_D08',level)]:
        for mode in ['C_MAX','C_10']:
            for stress in ['COST2','DELAY1','C3']:
                sc=config(policy+'_'+stress,mode,state_key='S1',blocked_states=blocked)
                if stress=='COST2':sc['cost']=2
                if stress=='DELAY1':sc['delay']=2
                if stress=='C3':
                    key=policy+'_C3';bad=m.v4state.S1.isin(blocked);m.v4state[key]=np.where(bad.rolling(3,min_periods=3).sum()==3,'BAD','ALLOW');sc.update(state_key=key,blocked_states=['BAD'])
                run(m,sc,f);publish()
        run(m,config(policy,'C_ONE',state_key='S1',blocked_states=blocked),f);publish()
    log('PAST_ONLY_D08','NEW_ROUTER','Static D08 state payoff differs across years; 2020-2023 already consumed, so reconstruction cannot create new OOS',
        '每年末只用已成熟D08同口径事件；至少20独立信号日且3状态片段，均值>0才开放，否则现金；2020用原D08连续运行，2021起评分',
        'D08原入口/S1开关/LEVEL在相同2021-2023评分期；持仓不年初清零',
        '检查过去数据决策程序与迁移，不主张独立验证','历史支持不足回退多或2022/2023仍亏损')
    ev=pd.read_parquet(OUT/'events_D08.parquet').merge(m.v4state[['t','S1','S1_episode']],on='t');mapping=[]
    allowed={};fitrows=[]
    for year in [2021,2022,2023]:
        cutoff=max(t for t,d in enumerate(m.dates) if d<str(year)+'-01-01');train=ev[(ev.label_available_t<=cutoff)&(ev.status=='MATURED')]
        for state in ['HIGH_IMPROVING','HIGH_NONIMPROVING','LOW_IMPROVING','LOW_NONIMPROVING']:
            g=train[train.S1==state];days=g.t.nunique();episodes=g.S1_episode.nunique();mean=g.groupby('t').net_return.mean().mean();accept=days>=20 and episodes>=3 and mean>0
            allowed[(year,state)]=accept;mapping.append(dict(year=year,state=state,fit_cutoff=m.dates[cutoff]+'T15:00:00+08:00',effective_from=str(year)+'-01-01',max_label_available_t=g.label_available_t.max(),fit_cutoff_t=cutoff,signal_dates=days,episodes=episodes,equal_date_return=mean,allow=accept,fallback=not accept))
    mapping=pd.DataFrame(mapping);mapping.to_csv(HERE/'past_only_mapping.csv',index=False)
    assert (mapping.max_label_available_t<=mapping.fit_cutoff_t).all()
    m.v4state['PAST']= ['ALLOW' if d<'2021' or allowed.get((int(d[:4]),s),False) else 'CASH' for d,s in zip(m.dates,m.v4state.S1)]
    f=f.copy();f['fit_cutoff']=[str(int(m.dates[t][:4])-1)+'-12-31T15:00:00+08:00' if m.dates[t]>='2021' else 'WARM_START_FROZEN_D08' for t in f.t]
    for mode in ['C_MAX','C_10']:
        sc=config('PAST_ONLY_D08',mode,state_key='PAST',blocked_states=['CASH']);run(m,sc,f);publish()
    # Policy arrays are inspectable, including derived confirmation and yearly mapping.
    parquet(OUT/'confirmation_state_daily.parquet',m.v4state)
    dump(HERE/'confirmation_contract.json',dict(candidates=['R1_S1_D08','R1_LEVEL_D08'],past_only_grade='PAST_ONLY_RECONSTRUCTION_ON_CONSUMED_DATA',schedule='ANNUAL',support={'dates':20,'state_episodes':3},fallback='CASH',start='2020 continuous native D08',score_start='2021-01-01',independent_oos=False))

if __name__=='__main__':main()
