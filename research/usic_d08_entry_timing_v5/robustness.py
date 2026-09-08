"""Finite robustness set for fixed cooling and the one supported digestion rule."""
import pandas as pd
from .common import HERE,OUT,V3,V4,log
from .market import Market
from .run import run_account

def main():
    m=Market();m.v4state=pd.read_parquet(V4/'confirmation_state_daily.parquet');m.v4state['S1_ORIGIN']=m.v4state.S1.shift(1).fillna('UNKNOWN')
    original=pd.read_parquet(V3/'A_D08_C_10_E10/input_signals.parquet')
    fixed=original[['setup_id','t','decision_at']].copy();fixed['rule']='FIXED_COOLING';fixed['decision_cutoff']=fixed.decision_at;fixed.to_csv(HERE/'entry_decisions_fixed.csv',index=False)
    q=pd.read_csv(HERE/'entry_decisions_quarter.csv');f=original.merge(q[['setup_id','t1_date','allow']],on='setup_id',validate='one_to_one');f=f[f.allow].drop(columns='allow').copy();f['origin_t']=f.t;f['t']=f.t+1;f['decision_at']=f.t1_date+'T15:00:00+08:00';f=f.drop(columns='t1_date')
    common=dict(exit='FIXED10',overlay='NONE',book='ENTRY_ONLY',ranking='V4_FIXED')
    scenarios=[
        (dict(id='E1_FIXED_T2_COST2_C10_E10',mode='C_10',delay=2,cost=2,entry_rule='FIXED_T2',decision_map='entry_decisions_fixed.csv',**common),original,'Cost robustness for fixed cooling','Fixed T+2 remains materially positive after doubled execution costs.','Return improvement over base disappears.'),
        (dict(id='E1_FIXED_T3_C10_E10',mode='C_10',delay=3,cost=1,entry_rule='FIXED_T3_NEIGHBOR',decision_map='entry_decisions_fixed.csv',**common),original,'One time neighbor tests whether T+2 is merely one point on an arbitrary clock.','T+3 does not dominate T+2 across account and years.','T+3 consistently dominates, making the T+2 interpretation incomplete.'),
        (dict(id='E3_QUARTER_COST2_C10_E10',mode='C_10',delay=1,cost=2,entry_rule='S0_LT_T1_CLOSE_LE_U_PLUS_0.25A',decision_map='entry_decisions_quarter.csv',origin_signal_t='origin_t',**common),f,'Cost robustness for the quarter-band candidate','Candidate remains above base under COST2.','Its advantage over matched references disappears.'),
        (dict(id='E3_QUARTER_S1_C10_E10',mode='C_10',delay=1,cost=1,entry_rule='S0_LT_T1_CLOSE_LE_U_PLUS_0.25A',decision_map='entry_decisions_quarter.csv',origin_signal_t='origin_t',state_key='S1_ORIGIN',blocked_states=['LOW_NONIMPROVING','UNKNOWN'],**common),f,'Auxiliary S1 interaction only after the candidate beat base and fixed delay in total return.','S1 adds value relative to the same timing rule without S1.','S1 lowers return or only lowers exposure.'),
        (dict(id='E3_QUARTER_CMAX_E10',mode='C_MAX',delay=1,cost=1,entry_rule='S0_LT_T1_CLOSE_LE_U_PLUS_0.25A',decision_map='entry_decisions_quarter.csv',origin_signal_t='origin_t',**common),f,'One permitted C_MAX pressure reproduction.','C_MAX confirms timing cannot be linearly scaled.','C_MAX improves consistently without concentration or drawdown penalty.'),
    ]
    for sc,frame,evidence,expected,falsifier in scenarios:
        log(sc['id'],evidence,'Test only the named robustness dimension.',sc['id'], 'E3_QUARTER_BAND_C10_E10_CA or B_D08_C_10_DELAY1',expected,falsifier,phase='BEFORE_ACCOUNT')
        run_account(m,sc,frame)

if __name__=='__main__':main()
