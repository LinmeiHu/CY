"""An accounting add-back on the observed path, never a zero-cost backtest."""
import pandas as pd
from .audit import HERE
from .economics import KEY


def run():
    d=pd.read_csv(HERE/'output/annual_scaling_metrics.csv')
    d['actual_path_pnl_before_current_year_fees']=d.net_pnl+d.fees
    n=d.loc[d.target.eq('NATIVE'),['gap','mcb_mode','year','net_pnl','fees','actual_path_pnl_before_current_year_fees']]
    bridge=d.merge(n,on=['gap','mcb_mode','year'],suffixes=('_scaled','_native'),validate='many_to_one')
    bridge['incremental_net_pnl']=bridge.net_pnl_scaled-bridge.net_pnl_native
    bridge['incremental_fees']=bridge.fees_scaled-bridge.fees_native
    bridge['incremental_actual_path_pnl_before_current_year_fees']=bridge.actual_path_pnl_before_current_year_fees_scaled-bridge.actual_path_pnl_before_current_year_fees_native
    bridge['interpretation']='Observed-path accounting add-back only. Removing fees would change cash, sizing and future fills; no zero-fee scenario was run.'
    bridge[KEY+['year','net_pnl_scaled','net_pnl_native','fees_scaled','fees_native','incremental_net_pnl','incremental_fees','incremental_actual_path_pnl_before_current_year_fees','interpretation']].to_csv(HERE/'output/fee_accounting_bridge.csv',index=False)


if __name__=='__main__':run()
