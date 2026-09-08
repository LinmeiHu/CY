"""Repair only affected single-event diagnostics after official fact completion."""
import shutil
import pandas as pd
from .common import HERE,OUT,V3,ROUTES,log,parquet
from .market import Market
from .maps import event

def main():
    m=Market();m.action_records_by_symbol={s:[str(x.date()) for x in g.record_date.dropna()] for s,g in m.actions.groupby('symbol')}
    facts=pd.read_csv(HERE/'action_backfill.csv');old=OUT/'diagnostics_before_official_facts';old.mkdir(exist_ok=True);changes=[]
    for route in ROUTES:
        p=OUT/f'events_{route}.parquet';f=pd.read_parquet(p)
        src=OUT/'D09_corrected_signals.parquet' if route=='D09' else V3/f'{route}_signals.parquet';signals=pd.read_parquet(src).set_index('setup_id')
        if 'reason' not in f:continue
        mask=(f.status=='ACTION_DIAGNOSTIC_BLOCKED')&f.reason.fillna('').str.contains('|'.join(facts.action_id),regex=True)
        if not mask.any():continue
        if not (old/p.name).exists():shutil.copy2(p,old/p.name)
        for i in f.index[mask]:
            r=signals.loc[f.at[i,'setup_id']].to_dict();r['setup_id']=f.at[i,'setup_id'];new=event(m,r)
            changes.append(dict(route=route,setup_id=r['setup_id'],old_status=f.at[i,'status'],new_status=new['status'],net_return=new['net_return']))
            for k,v in new.items():f.at[i,k]=v
        parquet(p,f)
    pd.DataFrame(changes).to_csv(HERE/'event_fact_repair.csv',index=False)
    log('EVENT_FACT_REPAIR','BUG_FIX','action_backfill.csv official terms','只恢复原先公司行动缺口事件标签；保留之前诊断快照','Pre-fact maps and exact same event universe','核对地图和过去信息路由是否受缺口影响','非缺口事件改变；标签回填影响过去映射却未披露')

if __name__=='__main__':main()
