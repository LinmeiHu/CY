"""Determinism trials of existing frozen cells; no additional scenario setting."""
import pandas as pd
from .common_p0_v06 import load_inputs,replay,HERE


def run():
    data=load_inputs();rows=[]
    for period,start,end,mode,policy in [('2018_2021','2018-01-01','2021-12-31','independent','P0'),('2022_2023','2022-01-01','2023-12-31','confirmation_tag','P2')]:
        gap='OGR';p0=HERE/'cache/scenarios'/gap/period/mode/'P0'
        home=pd.read_parquet(p0/'timeline.parquet').set_index('timestamp')
        if policy!='P0':
            baseline,*_=replay(data,gap,period,start,end,mode=mode)
            home=pd.DataFrame(baseline.account_timeline).set_index('timestamp')
            before=pd.DataFrame(baseline.funding.home_history).set_index('timestamp')
            home.loc[before.index,before.columns]=before
        account,daily,*_=replay(data,gap,period,start,end,policy=policy,mode=mode,home_path=home)
        folder=HERE/'cache/scenarios'/gap/period/mode/policy
        golden=pd.read_parquet(folder/'daily.parquet')
        pd.testing.assert_frame_equal(daily,golden[daily.columns])
        fills=pd.DataFrame(account.fills);expected=pd.read_parquet(folder/'fills.parquet')
        for field in ['event_id','side','quantity','funded_notional','remaining_outlay']:
            pd.testing.assert_series_equal(fills[field].reset_index(drop=True),expected[field].reset_index(drop=True),check_dtype=False)
        rows.append(dict(gap=gap,period=period,mcb_mode=mode,policy=policy,status='PASS',daily_rows=len(daily),fills=len(fills),scope='Full daily physical/sleeve state and native fills unchanged after surgical cleanup'))
        print(rows[-1],flush=True)
    pd.DataFrame(rows).to_csv(HERE/'output/post_cleanup_deterministic_rerun.csv',index=False)
    return rows

if __name__=='__main__':run()
