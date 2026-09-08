"""Observe authoritative live adapters before funding; never infer demand from fills."""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
from types import MethodType
import numpy as np
import pandas as pd
from research.scaling_regime_v1 import accounts
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.shared_account.p0 import initialize
from research.shared_capital_v1.smv6_physical import PhysicalPlatform

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = Path('/Users/linmei/Documents/CY-worktrees/five-strategy-scaling-regime-v1')
CACHE = SOURCE/'research/scaling_regime_v1/cache'
OUT = HERE/'output'
END = '2026-09-04'


def digest(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write_json(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False, default=str)+'\n')


def freeze():
    contract = dict(version='OPPORTUNITY_SEMANTICS_V2',
        definition='Only causal desired exposure increases before funding; fills never define the population.',
        allowed=['NEW_ENTRY_REQUEST','EXPOSURE_INCREASE_REQUEST'],
        excluded=['REDUCE_POSITION','PARTIAL_SELL','FULL_EXIT','STOP_EXIT','NATIVE_EXIT','CORPORATE_ACTION_ONLY','REBALANCE_REDUCTION','CASH_RELEASE','MARK_TO_MARKET_CHANGE'],
        classification='desired_after - desired_before: positive=increase, negative=reduction, zero=no capital change; both marked at the same causal request price',
        lineage='Native request event_id; target-percent callback order id for requests before execution eligibility/volume filtering; map downstream engine event_id only by synchronous request call. A reduction and later increase have separate ids. Gap OGR/IFCGR share gap_id but are alternate accounts.',
        signal_at='completed native signal information timestamp',
        decision_at='live native desired-position request callback timestamp before funding, with causal sequence ordinal; preserve original intent decision_at as native_signal_decision_at',
        funding_at='native earliest execution timestamp; before-state captured at actual fund invocation',
        capital_state='immediately before the request/funding event; cash and gross at legal existing marks; no EOD substitution; fees included in requested cash bill',
        simultaneous='Exact timestamp legal requests require pro-rata; synchronous callback feedback dependencies must be audited before batching; never silently assign fake times.',
        shadow_notional='Execute independent clone with exact native requested quantity and native execution constraints; normalize economic P&L to 1,000,000 CNY entry cash outlay for comparison. Do not resize actual execution quantities for reporting normalization.',
        cutoff=END, right_censoring='Retain open marked paths; no invented exit',
        tolerances=dict(cash_atol=1e-6,quantity_atol=1e-8,rtol=1e-10),
        experiment='Original portfolio closure design unchanged; freeze selection contract only after all six input gates pass')
    p=HERE/'contracts/opportunity_semantics_v2.json'
    if p.exists() and json.loads(p.read_text())!=contract:
        raise ValueError('frozen semantics changed')
    write_json(p,contract)
    return digest(p)


def capital_state(account, when):
    cash=float(account.cash); mv=float(account.exposure()); nav=cash+mv
    if cash < -1e-8 or mv > nav+1e-8:
        raise ValueError('financed before-event state')
    return dict(decision_at=pd.Timestamp(when), cash_before_event=cash,NAV_before_event=nav,
        long_market_value_before_event=mv,gross_before_event=mv/nav,
        gross_limit_notional=nav,gross_headroom_before_event=nav-mv,
        fees_reserve=0.,actual_cash_fundable=max(0.,cash),actual_gross_fundable=max(0.,nav-mv),
        legal_fundable_notional=max(0.,min(cash,nav-mv)))


def classify(before, after):
    if not math.isfinite(before) or not math.isfinite(after) or min(before,after)<0:
        raise ValueError('invalid desired exposure')
    return 'EXPOSURE_INCREASE' if after>before else 'EXPOSURE_REDUCTION' if after<before else 'NO_CAPITAL_CHANGE'


def observed_initialize(gap,states):
    account=initialize(gap,states)
    account.precapital=[]; account.transitions=[]; account.capital_events=[]
    account.callback_requests=[]
    original_fund=account.fund; original_close=account.close
    def fund(self,intents,home,policy,when,**kwargs):
        intents=list(intents)
        state=capital_state(self,when)
        sequence=len(self.capital_events)
        self.capital_events.append(dict(state,sequence=sequence,kind='FUND',
            ids=json.dumps([i.event_id for i in intents]),strategies='|'.join(sorted({i.strategy for i in intents})),
            requested=sum(i.native_requested_notional for i in intents), fills_before=len(self.fills)))
        for i in intents:
            before=sum(l['quantity'] for l in self.lots.values() if l['strategy']==i.strategy and l['symbol']==i.symbol)*i.price
            self.precapital.append(dict(asdict(i),opportunity_id=i.event_id,economic_opportunity_id=i.event_id,
                native_account_id=gap+'__NATIVE_CONTINUOUS',signal_at=i.decision_at,native_signal_decision_at=i.decision_at,
                decision_at=pd.Timestamp(when),funding_at=pd.Timestamp(when),sequence=sequence,
                desired_before=before,desired_after=before+i.native_requested_quantity*i.price,
                requested_increase_notional=i.native_requested_notional,
                eligibility_source='live native adapter before physical funding',producer_source='stock_p0/gap_p0/PhysicalPlatform native callback',
                classification='EXPOSURE_INCREASE',opportunity_type='NEW_ENTRY_REQUEST' if before==0 else 'EXPOSURE_INCREASE_REQUEST'))
        result=original_fund(intents,home,policy,when,**kwargs)
        self.capital_events[-1].update(cash_after=self.cash,funded=state['cash_before_event']-self.cash,
            fills_after=len(self.fills))
        return result
    def close(self,event_id,price,when,fee_rate,**kwargs):
        lot=dict(self.lots[event_id]); qty=kwargs.get('quantity',lot['quantity']-lot.get('nontradable_quantity',0.))
        state=capital_state(self,when)
        self.transitions.append(dict(event_id=event_id,strategy=lot['strategy'],symbol=lot['symbol'],decision_at=when,
            desired_before=lot['quantity']*price,desired_after=(lot['quantity']-qty)*price,
            delta_desired_exposure=-qty*price,classification='EXPOSURE_REDUCTION',source='native close request before fill',
            reason=kwargs.get('reason','NATIVE_EXIT'),sequence=len(self.capital_events)))
        self.capital_events.append(dict(state,sequence=len(self.capital_events),kind='REDUCE',ids=json.dumps([event_id]),
            strategies=lot['strategy'],requested=0.,fills_before=len(self.fills)))
        result=original_close(event_id,price,when,fee_rate,**kwargs)
        self.capital_events[-1].update(cash_after=self.cash,funded=0.,fills_after=len(self.fills))
        return result
    account.fund=MethodType(fund,account);account.close=MethodType(close,account)
    return account


class ObservedPlatform(PhysicalPlatform):
    def order_target_percent(self,symbol,target_weight):
        # This boundary precedes the native availability, volume, and cash filters.
        row=self._current_row(symbol)
        if row is None or not bool(row.executable_09_30):
            # Do not raise in the observer before the authoritative callback has
            # made its own legal holding marks and availability decision.
            return super().order_target_percent(symbol,target_weight)
        try:
            price=self._mark(symbol,'open')
            observed_nav=self.cash+sum(q*self._mark(s,'open') for s,q in self.shares.items() if q)
        except Exception:
            return super().order_target_percent(symbol,target_weight)
        before=self.shares.get(symbol,0)
        desired=math.floor(observed_nav*target_weight/price/self.lot_size)*self.lot_size
        row=dict(callback_id=f'SMV6_TARGET|{self.current_date}|{symbol}|{len(self.physical.callback_requests)}',
            symbol=symbol,decision_at=self._timestamp(),desired_before=before*price,desired_after=desired*price,
            delta_desired_exposure=(desired-before)*price,classification=classify(before*price,desired*price),
            target_weight=target_weight,engine_ids_before=len(self.intent_rows),sequence=len(self.physical.capital_events),
            cash_before=self.cash)
        self.physical.callback_requests.append(row)
        result=super().order_target_percent(symbol,target_weight)
        row['engine_ids']=json.dumps([i['event_id'] for i in self.intent_rows[row['engine_ids_before']:]])
        row['cash_after']=self.cash
        return result


load=corrected_function(accounts.load,[],CACHE=CACHE,ROOT=SOURCE)
replay=corrected_function(accounts.replay,[(
    'daily.append(dict(row,trade_date=when.normalize()))',
    'daily_observation(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],
    initialize=observed_initialize,PhysicalPlatform=ObservedPlatform,daily_observation=accounts.daily_observation)


def run(gap,end):
    freeze()
    dest=OUT/'repair_accounts'/f'{gap}__{end}'
    dest.mkdir(parents=True,exist_ok=True)
    print('LOAD',gap,end,flush=True)
    data=load(end)
    print('REPLAY',gap,end,flush=True)
    account,nav,results,platform,trace=replay(data,gap,accounts.PERIOD,'2018-01-01',end)
    from research.capital_scaling_v1.run import save_account
    save_account(dest,account,nav,None)
    frames={'precapital':pd.DataFrame(account.precapital),'transitions':pd.DataFrame(account.transitions),
        'capital_events':pd.DataFrame(account.capital_events),'callback_requests':pd.DataFrame(account.callback_requests),
        'smv6_intents':pd.DataFrame(platform.intent_rows),'smv6_events':pd.DataFrame(platform.events)}
    for s,result in results.items():frames[s.lower()+'_intents']=result()[0]
    for name,frame in frames.items():
        for c in ['native_priority']:
            if c in frame:frame[c]=frame[c].map(json.dumps)
        frame.to_parquet(dest/(name+'.parquet'),index=False)
    reference=CACHE/'accounts'/f'{gap}__independent__NATIVE__FULL_BOOK_NORMALIZATION__{end}'
    rows=[]
    expected=pd.read_parquet(reference/'daily.parquet')
    for field in ['cash','nav','gross_exposure']:
        j=nav[['trade_date',field]].merge(expected[['trade_date',field]],on='trade_date',how='outer',suffixes=('_new','_old'),indicator=True)
        error=float((j[field+'_new']-j[field+'_old']).abs().max())
        rows.append(dict(gap=gap,end=end,field=field,max_abs_error=error,rows=len(j),status='PASS' if j._merge.eq('both').all() and error<=1e-6 else 'FAIL'))
    actual=pd.read_parquet(dest/'fills.parquet');old=pd.read_parquet(reference/'fills.parquet')
    fields=['event_id','strategy','symbol','side','entry','exit','quantity','filled_quantity','price','exit_price','funded_notional','fee','pnl']
    fields=[f for f in fields if f in actual and f in old]
    try:
        pd.testing.assert_frame_equal(actual[fields].reset_index(drop=True),old[fields].reset_index(drop=True),check_dtype=False,rtol=1e-10,atol=1e-6)
        status='PASS'
    except AssertionError as e:
        (dest/'fill_identity_error.txt').write_text(str(e));status='FAIL'
    rows.append(dict(gap=gap,end=end,field='fills_positions',max_abs_error=0 if status=='PASS' else None,rows=len(actual),status=status))
    pd.DataFrame(rows).to_csv(dest/'reconciliation.csv',index=False)
    write_json(dest/'repair_receipt.json',dict(status='PASS' if all(r['status']=='PASS' for r in rows) else 'FAIL',
        opportunities=len(account.precapital),hashes={p.name:digest(p) for p in sorted(dest.glob('*.parquet'))}))
    print('P0',rows,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--gap',choices=['OGR','IFCGR'],default='IFCGR');p.add_argument('--end',default=END)
    a=p.parse_args();run(a.gap,a.end)
