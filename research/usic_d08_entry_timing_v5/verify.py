"""Independent exact repeats for the two strongest displayed V5 accounts."""
import hashlib,json
import pandas as pd
from .common import HERE,OUT,V4,sha,dump
from .market import Market
from ..usic_market_router_v4.engine import replay

def main():
    m=Market();m.v4state=pd.read_parquet(V4/'confirmation_state_daily.parquet');m.v4state['S1_ORIGIN']=m.v4state.S1.shift(1).fillna('UNKNOWN');checks=[]
    for sid in ['E3_QUARTER_BAND_C10_E10_CA','E3_QUARTER_S1_C10_E10']:
        d=OUT/'accounts'/sid;r=json.loads((d/'result.json').read_text());f=pd.read_parquet(d/'input_signals.parquet');outputs=replay(m,r['identity']['config'],f);v=OUT/'verification'/sid;v.mkdir(parents=True,exist_ok=True)
        for name,x in zip(['nav','trades','orders','audit','open_positions','holdings'],outputs):
            p=v/(name+'.parquet');x.to_parquet(p,index=False);assert sha(p)==r['artifacts'][name+'.parquet'];checks.append(dict(id=sid,test='EXACT_REPEAT_'+name,passed=True))
        o=outputs[2].merge(f[['setup_id','origin_t','t']],on='setup_id',validate='many_to_one');assert (o.t_x==o.t_y+1).all();checks.append(dict(id=sid,test='T1_CLOSE_DECISION_T2_EXECUTION',passed=True))
        n=outputs[0];assert len(n)==970 and (n.cash>=-1e-7).all() and (n.borrowed_cash==0).all() and (n.margin==0).all();checks.append(dict(id=sid,test='NO_FINANCING_970_DAYS',passed=True))
    bindings=[]
    for p in (OUT/'accounts').glob('*/result.json'):
        r=json.loads(p.read_text());key=r.get('identity',{}).get('config',{}).get('state_key')
        if key:
            payload=m.v4state[['t','date',key]].to_json(orient='records').encode();bindings.append(dict(id=r['id'],state_key=key,state_sequence_sha256=hashlib.sha256(payload).hexdigest(),definition='S1 at original signal T, serialized as S1_ORIGIN at effective T+1 decision row'))
    pd.DataFrame(bindings).to_csv(HERE/'account_state_bindings.csv',index=False)
    dump(HERE/'FINAL_CHECKS.json',dict(checks=checks,all_passed=True,exact_replays=2,state_bindings=len(bindings)))
    print('FINAL_CHECKS',len(checks),'PASS')

if __name__=='__main__':main()
