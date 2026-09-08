import pandas as pd
from .common import HERE,sha
from ..usic_market_router_v4.market import Market as V4Market

class Market(V4Market):
    def __init__(self):
        super().__init__();facts=pd.read_csv(HERE/'action_backfill.csv').set_index('action_id')
        for records in [self.records,self.exdates]:
            for rows in records.values():
                for row in rows:
                    if row['event_id'] in facts.index:row['share_credit_date']=pd.Timestamp(facts.loc[row['event_id'],'tradable_date'])
        for i,row in self.actions.iterrows():
            if row.event_id in facts.index:self.actions.at[i,'share_credit_date']=pd.Timestamp(facts.loc[row.event_id,'tradable_date'])
        self.execution_binding=dict(self.execution_binding,v5_official_facts={'path':str(HERE/'action_backfill.csv'),'sha256':sha(HERE/'action_backfill.csv'),'sources':sha(HERE/'official_sources.json')})
