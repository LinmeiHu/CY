"""Cooperative native order calls with all currently legal base demands first.

Native callbacks keep their original synchronous order/feedback semantics. Only
one callback runs at a time; it parks immediately before capital filtering. The
driver funds every available base request, resumes successful callbacks to expose
subsequent native requests, then allocates shared cash to the still blocked heads.
No future native request is invented from a hypothetical accepted-trade ledger.
"""
from queue import Queue
from threading import Thread, local
import pandas as pd


class NativeFunding:
    def __init__(self, account, policy='P0', mode='independent', home_path=None, gate=None):
        self.account,self.policy,self.mode,self.home_path,self.gate=account,policy,mode,home_path,gate
        self.original=account.fund
        self.local=local()
        self.demand=[]
        self.home_history=[]
        self.cancelled=False
        account.fund=self.submit

    def submit(self,intents,home,policy,when,**kwargs):
        worker=getattr(self.local,'worker',None)
        if worker is None:raise ValueError('native funding outside chronological entry phase')
        if self.cancelled:raise RuntimeError('native funding cancelled')
        worker['out'].put(('fund',(intents,home,when)))
        response=worker['in'].get()
        if isinstance(response,BaseException):raise response
        return response

    def _worker(self, callback):
        worker={'in':Queue(),'out':Queue(),'request':None,'done':False}
        def run():
            self.local.worker=worker
            try:
                callback()
                worker['out'].put(('done',None))
            except BaseException as error:worker['out'].put(('done',error))
        worker['thread']=Thread(target=run,daemon=True)
        return worker

    @staticmethod
    def receive(worker):
        kind,value=worker['out'].get()
        if kind=='done':
            worker['done']=True;worker['request']=None;worker['thread'].join()
            if value is not None:raise value
        else:worker['request']=value

    def run_callbacks(self, events):
        workers=[self._worker(event.callback) for event in events]
        when=pd.Timestamp(events[0].when)
        multiplier=self.gate.multiplier if self.gate else 1.
        capacity=None
        waiting=[]
        def resume(worker):
            worker['request']=None
            worker['in'].put(None)
            self.receive(worker)
        try:
            for worker in workers:
                worker['thread'].start();self.receive(worker)
            while any(not w['done'] for w in workers):
                heads=[w for w in workers if w['request'] is not None and not any(w is p for p in waiting)]
                if heads:
                    intents=[i for w in heads for i in w['request'][0]]
                    if any(pd.Timestamp(w['request'][2])!=when for w in heads):raise ValueError('native order clock differs from scheduler clock')
                    # P0 retains each native cash account's own current reference.
                    if self.policy=='P0':
                        home={s:self.account.sleeve_cash[s]+self.account.exposure(s) for s in self.account.strategies}
                        for w in heads:
                            for i in w['request'][0]: home[i.strategy]=w['request'][1][i.strategy]
                    else:
                        position=self.home_path.index.searchsorted(when,side='right')-1
                        if position<0:raise ValueError('missing legal P0 HOME_BUDGET')
                        home={s:float(self.home_path.iloc[position][s+'_nav']) for s in self.account.strategies}
                    if capacity is None:
                        capacity=self.account.cash*multiplier
                        self.home_history.append(dict(timestamp=when,**{s+'_nav':home[s] for s in self.account.strategies}))
                    if self.policy == 'P0':
                        # A synchronous native callback may legally sell between
                        # two requests. P0 has no frozen DD allowance to consume;
                        # its next order uses actual current physical/sleeve cash.
                        capacity = self.account.cash
                    before=self.account.cash
                    pending=self.original(intents,home,self.policy,when,mcb_mode=self.mode,base_only=True,available_capacity=capacity)
                    capacity-=before-self.account.cash
                    failed={i.event_id for i in pending} if self.policy!='P0' else set()
                    for intent in intents:
                        self.demand.append(dict(timestamp=when,strategy=intent.strategy,event_id=intent.event_id,symbol=intent.symbol,
                            requested_notional=intent.native_requested_notional,home_budget=home[intent.strategy],gate_multiplier=multiplier))
                    for w in heads:
                        if any(i.event_id in failed for i in w['request'][0]):
                            w['unfunded']=[i for i in w['request'][0] if i.event_id in failed]
                            waiting.append(w)
                        else:resume(w)
                    continue
                if waiting:
                    intents=[i for w in waiting for i in w['unfunded']]
                    before=self.account.cash
                    self.account.fund_shared(intents,home,self.policy,when,capacity,gate_multiplier=multiplier)
                    capacity-=before-self.account.cash
                    old,waiting=waiting,[]
                    for w in old:resume(w)
                else:raise ValueError('native funding callback deadlock')
        except BaseException:
            self.cancelled=True
            for w in workers:
                if w['thread'].ident is not None and not w['done']:
                    w['in'].put(RuntimeError('native funding cancelled'))
                    w['thread'].join(timeout=2)
            raise
