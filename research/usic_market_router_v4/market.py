"""V3 market plus explicit V4 official execution facts; no source-data writes."""
import json
import pandas as pd
from .engine import Market as BaseMarket
from .common import HERE,sha

def apply_facts(m):
    p=HERE/'action_backfill.csv'
    if not p.exists():return m
    f=pd.read_csv(p).set_index('action_id')
    for records in [m.records,m.exdates]:
        for rows in records.values():
            for row in rows:
                if row['event_id'] in f.index:
                    z=f.loc[row['event_id']];row['share_credit_date']=pd.Timestamp(z.tradable_date)
    for i,row in m.actions.iterrows():
        if row.event_id in f.index:m.actions.at[i,'share_credit_date']=pd.Timestamp(f.loc[row.event_id,'tradable_date'])
    m.execution_binding=dict(m.execution_binding,v4_official_facts={'path':str(p),'sha256':sha(p),'sources':sha(HERE/'official_sources.json')})
    return m

class Market(BaseMarket):
    def __init__(self):
        super().__init__();apply_facts(self)
