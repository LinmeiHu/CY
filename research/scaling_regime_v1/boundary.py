"""Observe original SMV6 callbacks at the 2022 boundary; do not alter them."""
import json
from types import SimpleNamespace

import pandas as pd

from five_strategy_bundle.strategies import smv6
from research.shared_capital_v1.smv6_physical import PhysicalPlatform, callback_stream
from research.shared_capital_v1.causal_adapters import corrected_function
from .audit import HERE, ROOT, ROLL, write_json


def load_etf(end):
    daily, minute = {}, {}
    for symbol in [smv6.canonical_symbol(s) for s in smv6.raw_pool()] + ['000852.SH']:
        daily[symbol] = smv6.load_daily(ROLL/'smv6', symbol).loc[:end]
        m = smv6.load_minute(ROLL/'smv6', symbol)
        minute[symbol] = m.loc[pd.to_datetime(m.trade_date).le(end)]
    availability = pd.read_parquet(ROLL/'smv6/availability.parquet')
    availability = availability.loc[pd.to_datetime(availability.trade_date).le(end)].copy()
    availability['trade_date'] = pd.to_datetime(availability.trade_date).dt.date
    return daily, minute, availability


def plain(value):
    if isinstance(value, dict):
        return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value, (set,tuple,list)):
        values = sorted(value) if isinstance(value,set) else value
        return [plain(v) for v in values]
    if isinstance(value,pd.Timestamp):
        return value.isoformat()
    if hasattr(value,'item'):
        return value.item()
    return value


def run_one(data, start, end, label):
    daily,minute,availability = data
    calendar = list(daily['000852.SH'].loc[start:end].dropna(subset=['pre_adj_close']).index)
    p = PhysicalPlatform(daily,minute,availability,calendar,initial_cash=1e6,lot_size=100,fee_bps=0)
    rows,logs = [],[]
    def snapshot(phase):
        context = {k:v for k,v in vars(p.native_context).items() if k!='portfolio'}
        return dict(protocol=label,timestamp=str(p.current_date),phase=phase,cash=p.cash,
                    nav=p.cash+p.physical.exposure('SMV6'),gross=p.physical.exposure('SMV6'),
                    positions=plain(p.shares),pending_positions=plain(p.physical.pending_positions),
                    desired=plain(context.get('pending_desired')),callback_state=plain(context))
    class Log:
        def info(self,message):
            if str(p.current_date)=='2022-01-04':logs.append(str(message))
        warn=info
        error=info
    def namespace(platform):
        ns=smv6.frozen_namespace(platform)
        ns['log']=Log()
        return ns
    stream_fn=corrected_function(callback_stream,[],smv6=SimpleNamespace(frozen_namespace=namespace))
    for event in stream_fn(p,calendar):
        if pd.Timestamp(event.when).date()==pd.Timestamp('2022-01-04').date():
            if event.phase=='PREPARE':
                p.current_date=pd.Timestamp(event.when).date()
                rows.append(snapshot('BEFORE_PREPARE'))
        event.callback()
        day=pd.Timestamp(event.when).date().isoformat()
        if day=='2022-01-04' or (day=='2021-12-31' and event.phase=='CLOSE'):
            rows.append(snapshot('AFTER_'+event.phase))
    nav=pd.DataFrame(p.accounts)
    reference=(ROOT/'research/shared_capital_v1/cache/smv6/2022_2023/CAUSAL_CORRECTED_BASELINE_nav.parquet'
               if start.startswith('2022') else ROLL/'combinations/OGR_independent_NATIVE/daily.parquet')
    ref=pd.read_parquet(reference)
    if 'SMV6_nav' in ref:
        ref=ref[['trade_date','SMV6_nav','SMV6_cash','SMV6_exposure']].rename(columns={'SMV6_nav':'nav','SMV6_cash':'cash','SMV6_exposure':'gross_exposure'})
    for f in (nav,ref):f['trade_date']=pd.to_datetime(f.trade_date)
    both=nav.merge(ref,on='trade_date',suffixes=('_new','_reference'),validate='one_to_one')
    errors={field:float(abs(both[field+'_new']-both[field+'_reference']).max()) for field in ['nav','cash','gross_exposure']}
    if max(errors.values())>1e-6:raise ValueError('SMV6 observed callback replay does not match account')
    print(label,'days',len(nav),'maxdiff',errors,flush=True)
    return dict(protocol=label,rows=rows,logs=logs,shared_days=len(both),reference_max_abs_errors=errors)


def main():
    data=load_etf('2022-01-05')
    continuous=run_one(data,'2018-01-01','2022-01-04','CONTINUOUS_LIVE_PROTOCOL')
    segmented=run_one(data,'2022-01-01','2022-01-04','SEGMENTED_RESEARCH_PROTOCOL')
    write_json(HERE/'output/smv6_boundary_trace.json',dict(continuous=continuous,segmented=segmented))
    rows=[]
    for result in [continuous,segmented]:
        for row in result['rows']:
            rows.append({k:json.dumps(v,sort_keys=True,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})
    pd.DataFrame(rows).to_csv(HERE/'output/smv6_boundary_state.csv',index=False)


if __name__=='__main__':main()
