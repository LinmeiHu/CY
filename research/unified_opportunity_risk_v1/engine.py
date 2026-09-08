"""Unified admission attached to the existing authoritative physical callbacks.

Frozen alpha and native exits are imported unchanged. Only capital sizing and
same-clock request submission are adapted for the explicitly authorized pool.
"""
from collections import defaultdict
from dataclasses import asdict, replace
import json
import math
from types import MethodType
import numpy as np
import pandas as pd
from five_strategy_bundle.strategies import smv6
from research.shared_capital_v1 import stock_p0, gap_p0
from research.shared_capital_v1.smv6_physical import PhysicalPlatform, callback_stream
from research.shared_capital_v1.causal_adapters import corrected_function
from research.shared_capital_v1.shared_account.native_funding import NativeFunding
from research.shared_capital_v1.shared_account.engine import Intent
from research.shared_capital_v1.shared_account.p0 import initialize
from research.shared_capital_v1.common_p0_v06 import replay
from research.portfolio_closure_v1 import repair
from research.unified_opportunity_risk_v1.data import OUT, CONTRACT, Calibration

# This changes only requested capital size. Native legal entries, source order,
# target/time exits, actions, raw price conversion and active state are unchanged.
stock_replay=corrected_function(stock_p0.replay,[
    ('outlay=board_nav[board]/30','outlay=(account.cash+account.exposure())/30'),
])

gap_replay=corrected_function(gap_p0.replay,[
    ("if pd.Timestamp(row['exit_time']).normalize() == day","if pd.notna(row['exit_time']) and pd.Timestamp(row['exit_time']).normalize() == day"),
    ('for row in incoming.itertuples(index=False):','batch=[]; rows={}\n        for row in incoming.itertuples(index=False):'),
    ('outlay = (cash[row.board] + value) / 80','outlay = (account.cash + account.exposure()) / 80'),
    ('native_base_cash_limit=cash[row.board]','native_base_cash_limit=max(0.,cash[row.board])'),
    ('before = account.cash\n            account.fund([intent], home, "P0", when)\n            if row.gap_id in account.lots:\n                cash[row.board] -= account.lots[row.gap_id][\'funded_notional\']\n                active[row.gap_id] = row._asdict()',
     'batch.append(intent);rows[row.gap_id]=row\n        if batch:\n            account.fund(batch, home, "P0", when)\n            for intent in batch:\n                row=rows[intent.event_id]\n                if row.gap_id in account.lots:\n                    cash[row.board] -= account.lots[row.gap_id]["funded_notional"]\n                    active[row.gap_id] = row._asdict()'),
])

class PoolPlatform(PhysicalPlatform):
    """Same native membership/exit callbacks; collect increases as one open batch."""
    @property
    def cash(self):
        return self.physical.cash if hasattr(self,'physical') else self._initializing_cash
    @cash.setter
    def cash(self,value):
        if hasattr(self,'physical'):raise ValueError('bypassed physical cash')
        self._initializing_cash=value
    def nav(self,stage):
        if not hasattr(self,'physical'):return super().nav(stage)
        self.physical.mark({s:self._mark(s,stage) for s,q in self.shares.items() if q},basis='PRE_ADJUSTED_ETF')
        return self.physical.cash+self.physical.exposure()
    _pool_order=corrected_function(smv6.CashPlatform.order_target_percent,[
        ('delta = min(delta, affordable)','return self.defer_buy(symbol, delta, price, target_weight, desired, volume_cap)'),
        ('self.cash -= delta * price + fee','if delta < 0:\n        self._engine_sell(symbol, -delta, price)'),
    ])
    def order_target_percent(self,symbol,target_weight):
        return self._pool_order(symbol,target_weight)
    def defer_buy(self,symbol,requested,price,target_weight,desired,volume_cap):
        identity=f'SMV6|{self.current_date}|{symbol}|{len(self.intent_rows)}'
        intent=Intent('SMV6','NATIVE_CALLBACK','ETF_TIMING',identity,'',symbol,pd.Timestamp(self.current_date),self._timestamp(),
            (len(self.intent_rows),),requested,price,self.commission_rate,lot_size=self.lot_size,price_basis='PRE_ADJUSTED_ETF',state_requirements=json.dumps(self.shares,sort_keys=True))
        self.intent_rows.append(dict(asdict(intent),native_requested_notional=intent.native_requested_notional))
        self.deferred.append((intent,target_weight,desired,volume_cap))
        return 'DEFERRED_SAME_TIMESTAMP_ADMISSION'
    def flush_increases(self):
        if not self.deferred:return
        self.physical.fund([x[0] for x in self.deferred],{s:1. for s in self.physical.strategies},'P0',self._timestamp())
        for intent,weight,desired,volume in self.deferred:
            lot=self.physical.lots.get(intent.event_id);delta=0 if lot is None else int(lot['quantity']);symbol=intent.symbol
            current=self.shares.get(symbol,0)
            if delta==0:
                self._record('BUY_OR_REBALANCE_NO_FILL',symbol,price=intent.price,target_weight=weight,reject_reason='UNIFIED_ADMISSION',requested_qty=desired)
                continue
            if not current:self.positions[symbol]=smv6.Position(symbol,float(weight),self.current_date,intent.price)
            else:self.positions[symbol].target_weight=float(weight)
            self.shares[symbol]=current+delta
            self._record('BUY_FILLED' if current==0 else 'REBALANCE_FILLED',symbol,price=intent.price,market_price=self._mark(symbol,'open'),target_weight=weight,
                requested_qty=desired,filled_delta_qty=delta,position_qty=current+delta,volume_cap_qty=volume,fee=delta*intent.price*intent.fee_rate,cash_after=self.cash)
        self.deferred=[]
    def record_account(self):
        self.nav('eod');row=self.physical.checkpoint(self._timestamp(),'CLOSE')
        represented=defaultdict(float)
        for l in self.physical.lots.values():
            if l['strategy']=='SMV6':represented[l['symbol']]+=l['quantity']
        if dict(represented)!={s:q for s,q in self.shares.items() if q}:raise ValueError('native/physical SMV6 holdings mismatch')
        self.accounts.append(dict(trade_date=pd.Timestamp(self.current_date),**row))

pool_callbacks=corrected_function(callback_stream,[
    ("namespace['execute_pending_open'](context, platform.bar_dict(), 'LOCAL_09_30')",
     "platform.deferred=[]\n        namespace['execute_pending_open'](context, platform.bar_dict(), 'LOCAL_09_30')\n        platform.flush_increases()")
])


def constrain_pro_rata(requests, constraints):
    """Scale only the members sharing each binding resource, deterministically."""
    allocated=np.asarray(requests,dtype=float).copy()
    for weights,limit in constraints:
        w=np.asarray(weights,dtype=float);use=float(np.dot(w,allocated))
        if use>max(0.,limit) and use>0:allocated[w>0]*=max(0.,limit)/use
    return allocated

class PoolFunding(NativeFunding):
    def run_callbacks(self,events):
        workers=[self._worker(e.callback) for e in events];when=pd.Timestamp(events[0].when)
        try:
            for w in workers:w['thread'].start();self.receive(w)
            heads=[w for w in workers if not w['done']]
            if heads:
                if any(pd.Timestamp(w['request'][2])!=when for w in heads):raise ValueError('clock drift')
                self.account.pool.allocate([i for w in heads for i in w['request'][0]],when)
                for w in heads:w['in'].put(None);self.receive(w)
                if any(not w['done'] for w in workers):raise ValueError('uncollected same-timestamp native request')
        except BaseException:
            for w in workers:
                if w['thread'].ident and not w['done']:w['in'].put(RuntimeError('pool cancelled'));w['thread'].join(timeout=2)
            raise

class Pool:
    def __init__(self,config,liquidity,native_requests):
        self.config=config;self.cal=Calibration();self.refs=json.loads((OUT/'risk_references_frozen.json').read_text())['references']
        self.liquidity=liquidity;self.native_requests=native_requests;self.admissions=[];self.risk_history=[]
    def bind(self,account):
        self.account=account;account.pool=self
    def holdings(self,nav):
        risk=0.;sec=defaultdict(float);family=defaultdict(float);notional=defaultdict(float);fam_mv=defaultdict(float)
        for eid,l in self.account.lots.items():
            q=self.cal.get(l.get('root_event_id',eid),l['strategy'],l['route']);mv=(l['quantity']+l.get('pending_quantity',0.))*self.account.marks[l['symbol']]
            contribution=mv/nav*q['conservative_tail_loss'];risk+=contribution;sec[l['symbol']]+=contribution;family[q['family']]+=contribution
            notional[l['symbol']]+=mv;fam_mv[q['family']]+=mv
        return risk,sec,family,notional,fam_mv
    def allocate(self,intents,when):
        a=self.account;a.validate_intents(intents,when)
        if any(i.event_id in a.seen for i in intents):raise ValueError('duplicate order')
        a.seen.update(i.event_id for i in intents)
        # Executable entry quotes are known at this clock. Mark before observing
        # allocation state; never substitute the unfinished daily close.
        for i in intents:a.mark({i.symbol:i.price},basis=i.price_basis,observed_at=when)
        state=repair.capital_state(a,when);nav=state['NAV_before_event']
        # Reserve all possible entry fees conservatively when defining post-trade
        # NAV risk caps. This affects only new headroom, not existing positions.
        safe_nav=nav-a.cash*max([i.fee_rate/(1+i.fee_rate) for i in intents],default=0.)
        risk,sec,fam,mv,fam_mv=self.holdings(safe_nav)
        ids={i.event_id for i in intents};ordered=sorted(intents,key=lambda i:(i.strategy,i.native_priority,i.event_id))
        records=[];eligible=[];liquidity_used=defaultdict(float)
        for i in ordered:
            q=self.cal.get(i.event_id,i.strategy,i.route,i.native_priority)
            reason='ECONOMIC_DUPLICATE' if i.event_id in self.cal.pairs and self.cal.pairs[i.event_id] in ids else ''
            if not reason and q['R1']<=0:reason='QUALITY_NONPOSITIVE'
            if not reason and a._native_rejection(i,when):reason=a._native_rejection(i,when)
            tail=q['conservative_tail_loss'];rp=self.config['risk_profile']
            desired=rp*self.refs['opportunity']*safe_nav/tail
            # Stock denominator is strictly prior complete sessions. Native
            # executable fallback is bound to the P0 source request, not current
            # pool target size. Missing new-state SMV6 ids use current native window.
            native=self.native_requests.get((i.strategy,i.event_id),i.native_requested_notional)
            if i.strategy=='SMV6':
                liq=i.native_requested_quantity*i.price;denom=liq/.5;liq_source='REGISTERED_NATIVE_OPEN_WINDOW'
            else:
                denom=self.liquidity.get((i.symbol,when.normalize()),float('nan'))
                liq=.01*denom if np.isfinite(denom) and denom>0 else native/(1+i.fee_rate)
                liq_source='PRIOR_20_COMPLETE_RAW_AMOUNT' if np.isfinite(denom) and denom>0 else 'NATIVE_EXECUTABLE_FALLBACK'
            if q['risk_estimate_insufficient']:liq=min(liq,native/(1+i.fee_rate))
            target=min(desired,liq);rank=0. if self.config['ranking']=='R0' else q[self.config['ranking']]
            rec=dict(state,event_id=i.event_id,strategy=i.strategy,route=i.route,symbol=i.symbol,family=q['family'],economic_id=q['economic_id'],
                rank=rank,R1=q['R1'],tail=tail,bucket=q['bucket'],native_requested=i.native_requested_notional,risk_desired=desired,liquidity_cap=liq,
                liquidity_denominator=denom,liquidity_source=liq_source,target=target,allocated=0.,reason=reason,quality_source='DISCOVERY_FROZEN',strategy_cap='NONE')
            records.append(rec)
            if not reason and target>0:eligible.append((i,q,rec))
        security_liquidity={}
        for symbol in {i.symbol for i,_,_ in eligible}:
            same=[r for i,_,r in eligible if i.symbol==symbol]
            # A validated market window is shared, never repeated per strategy.
            # Without a denominator, the aggregate conservative reference is
            # the sum of the distinct economic Native executable requests.
            security_liquidity[symbol]=(sum(r['liquidity_cap'] for r in same) if all(r['liquidity_source']=='NATIVE_EXECUTABLE_FALLBACK' for r in same)
                                        else min(r['liquidity_cap'] for r in same))
        for rank in sorted({r['rank'] for _,_,r in eligible},reverse=True):
            group=[x for x in eligible if x[2]['rank']==rank];targets=[r['target'] for _,_,r in group]
            constraints=[]
            for symbol in sorted({i.symbol for i,_,_ in group}):
                flags=[float(i.symbol==symbol) for i,_,_ in group]
                constraints.append((flags,security_liquidity[symbol]-liquidity_used[symbol]))
                constraints.append((flags,self.config['security_cap']*safe_nav-mv[symbol]))
                constraints.append(([f*r['tail']/safe_nav for f,(_,_,r) in zip(flags,group)],rp*self.refs['security']-sec[symbol]))
            if self.config['family_cap']:
                for family in sorted({q['family'] for _,q,_ in group}):
                    constraints.append(([r['tail']/safe_nav if q['family']==family else 0. for _,q,r in group],rp*self.refs['family_risk']-fam[family]))
            constraints.append(([r['tail']/safe_nav for _,_,r in group],rp*self.refs['account']-risk))
            constraints.append(([1+i.fee_rate for i,_,_ in group],a.cash))
            allocations=constrain_pro_rata(targets,constraints)
            for (i,q,r),amount in zip(group,allocations):
                quantity=amount/(i.price)
                if i.lot_size:quantity=math.floor(quantity/i.lot_size)*i.lot_size
                if quantity<=1e-12:r['reason']='RISK_OR_CASH_OR_LOT';continue
                scaled=replace(i,native_requested_quantity=quantity,native_base_cash_limit=None)
                if not a._fill(scaled,scaled.native_requested_notional,'UNIFIED',when):r['reason']=a.native_failures.get(i.event_id,'NO_FILL');continue
                allocated=quantity*i.price;liquidity_used[i.symbol]+=allocated;r['allocated']=allocated;r['reason']='FUNDED'
                delta=allocated/safe_nav*r['tail'];risk+=delta;sec[i.symbol]+=delta;fam[q['family']]+=delta;mv[i.symbol]+=allocated
                a.lots[i.event_id]['estimated_tail_loss']=r['tail'];a.lots[i.event_id]['ranking_at_entry']=rank
        a.checkpoint(when,'UNIFIED_JOINT_FUNDING_COMPLETE')
        self.admissions.extend(records)
        self.risk_history.append(dict(timestamp=when,nav=nav,tail_risk=risk,account_budget=rp*self.refs['account'],cash_after=a.cash,batch_requests=len(intents),
            same_timestamp_joint=True,borrowed_cash=0.,margin=0.))
    def observe(self,a,platform,scaling,row):
        nav=row['nav'];risk,sec,fam,mv,fam_mv=self.holdings(nav)
        row['estimated_tail_risk']=risk;row['max_family_exposure']=max(fam_mv.values(),default=0.)
        row['family_exposure_json']=json.dumps(dict(fam_mv),sort_keys=True)
        row['positions_json']=json.dumps(dict(a.positions),sort_keys=True)
        row['lots_json']=json.dumps({eid:{k:l.get(k) for k in ['strategy','route','symbol','root_event_id','quantity','pending_quantity','remaining_outlay','entry','estimated_tail_loss','ranking_at_entry']} for eid,l in a.lots.items()},sort_keys=True,default=str)
        row['callback_state_json']=json.dumps({k:v for k,v in vars(platform.native_context).items() if k!='portfolio'},sort_keys=True,default=str)


def run(data,config,liquidity,native_requests,end):
    pool=Pool(config,liquidity,native_requests)
    def init(gap,states):
        a=initialize(gap,states);pool.bind(a);return a
    fn=corrected_function(replay,[
        ('from .shared_account.native_funding import NativeFunding','NativeFunding = UnifiedFunding'),
        ('daily.append(dict(row,trade_date=when.normalize()))','observe(account,platform,scaling,row)\n            daily.append(dict(row,trade_date=when.normalize()))')],
        initialize=init,UnifiedFunding=PoolFunding,PhysicalPlatform=PoolPlatform,callback_stream=pool_callbacks,
        stock_replay=stock_replay,gap_replay=gap_replay,observe=pool.observe)
    account,nav,results,platform,trace=fn(data,'OGR','UNIFIED_CONTINUOUS_V1','2018-01-01',end)
    return account,nav,pool,platform
