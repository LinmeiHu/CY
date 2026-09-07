"""Legacy/corrected company-action control, never a production signal source."""
import json
from pathlib import Path
import pandas as pd
from five_strategy_bundle.strategies import ogr
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.gap_p0 import replay
from research.shared_capital_v1.run_shared_capital_v1 import HERE


def run():
    inputs={k:Path(v) for k,v in json.loads((HERE.parent/'five_strategy_exit_risk_v1/input_config.json').read_text())['inputs'].items()}
    parents=pd.read_parquet(HERE/'cache/ogr/signals.parquet').loc[lambda f:f.signal_date.ge('2022-01-01')]
    daily=ogr.load_daily(inputs['daily_hist'],end='2023-12-31')
    old_actions=ogr.load_actions(inputs['qd010_distributions'],inputs['qd010_rights'],parents.symbol.tolist())
    entry=corrected_function(ogr.build_entries,[('range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2023)','range(int(pd.to_datetime(seed.signal_date).dt.year.min()), 2024)'),("r.trade_date<=DATE '2022-03-31'","r.trade_date<=DATE '2023-12-31'")])
    outcome=corrected_function(ogr.build_outcomes,[("range(int(eligible.entry_date.dt.year.min()), 2023)","range(int(eligible.entry_date.dt.year.min()), 2024)"),("r.trade_date<=DATE '2022-03-31'","r.trade_date<=DATE '2023-12-31'")])
    legacy_entries=entry(parents,daily,inputs['raw_minute_root'],old_actions)
    legacy_outcomes=outcome(legacy_entries,daily,inputs['raw_minute_root'],old_actions)
    corrected=pd.read_parquet(HERE/'cache/ogr/outcomes.parquet').loc[lambda f:f.entry_date.ge('2022-01-01')]
    rows=[]
    for strategy in ('OGR','IFCGR'):
        chosen=parents if strategy=='OGR' else pd.read_parquet(HERE/'cache/ifcgr/2022_2023/signals.parquet')
        old=replay(strategy,legacy_outcomes.loc[legacy_outcomes.gap_id.isin(chosen.gap_id)],daily,'2022-01-01','2023-12-31')
        new=replay(strategy,corrected.loc[corrected.gap_id.isin(chosen.gap_id)],daily,'2022-01-01','2023-12-31')
        folder=HERE/'cache'/strategy.lower()/'action_control_v06';folder.mkdir(exist_ok=True)
        old[3].to_parquet(folder/'LEGACY_REFERENCE.parquet',index=False)
        new[3].to_parquet(folder/'CAUSAL_CORRECTED_P0.parquet',index=False)
        joined=old[3].merge(new[3],on='trade_date',suffixes=('_legacy','_corrected'),validate='one_to_one')
        mask=(joined.nav_legacy-joined.nav_corrected).abs().gt(1e-6)|(joined.cash_legacy-joined.cash_corrected).abs().gt(1e-6)
        first=joined.loc[mask].iloc[0]
        rows.append({'strategy':strategy,'period':'2022_2023','first_difference_date':first.trade_date,
            'classification':'corrected company action','reference_kind':'LEGACY_REFERENCE_SAME_RESET_CONTROL',
            'corrected_kind':'CAUSAL_CORRECTED_P0_STANDALONE_SAME_RESET_CONTROL',
            'legacy_first_nav':first.nav_legacy,'corrected_first_nav':first.nav_corrected,
            'legacy_final_nav':joined.nav_legacy.iloc[-1],'corrected_final_nav':joined.nav_corrected.iloc[-1],
            'legacy_intents':len(old[1]),'corrected_intents':len(new[1]),
            'cause':'first: 002727.SZ dividend 0.3/share on 2022-04-29 was omitted by 2022-03-31 action cutoff; later: 301326.SZ 2023-05-18 ex-date blocks entry under native rule',
            'common_p0_validated':False})
    pd.DataFrame(rows).to_csv(HERE/'output/p0_first_differences.csv',index=False)
    print(rows,flush=True)


if __name__=='__main__':run()
