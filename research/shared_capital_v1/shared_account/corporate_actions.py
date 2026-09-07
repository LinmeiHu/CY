"""Explicit record, pending, arrival and tradable share conversion.

No date inference, calendar arithmetic, automatic liquidation, or future scan.
Each call is one evidenced transition at its knowledge/effective checkpoint.
"""
from copy import deepcopy
from math import isfinite
import pandas as pd


class ShareConversion:
    def __init__(self, account):
        self.account = account
        self.events = {}

    @staticmethod
    def _known_time(when, available_at):
        when, available_at = pd.Timestamp(when), pd.Timestamp(available_at)
        if pd.isna(when) or pd.isna(available_at) or available_at > when:
            raise ValueError('unknown corporate state timestamp')
        return when, available_at

    def record(self, event_id, symbol, ratio, when, available_at, *, strategy=None):
        when, available_at = self._known_time(when, available_at)
        if available_at > when or event_id in self.events or not isfinite(ratio) or ratio <= 0:
            raise ValueError('invalid/unknown conversion record')
        lots = {eid: deepcopy(lot) for eid,lot in self.account.lots.items() if lot['symbol'] == symbol and (strategy is None or lot['strategy'] == strategy)}
        if any(lot.get('pending_quantity', 0) or lot.get('nontradable_quantity', 0) for lot in lots.values()):
            raise ValueError('overlapping conversions require explicit native contract')
        self.events[event_id] = dict(symbol=symbol, ratio=ratio, lots=lots, entitlements={eid:lot['quantity']*ratio for eid,lot in lots.items()}, phase='RECORD_DATE', last=when)

    def transition(self, event_id, stage, when, available_at, *, ex_price=None):
        when, available_at = self._known_time(when, available_at)
        event = self.events[event_id]
        next_stage = {'RECORD_DATE':'ACCOUNTING_EFFECTIVE_DATE', 'ACCOUNTING_EFFECTIVE_DATE':'SHARE_ARRIVAL_DATE', 'SHARE_ARRIVAL_DATE':'TRADABLE_DATE'}
        if available_at > when or when < event['last'] or next_stage.get(event['phase']) != stage:
            raise ValueError('unknown/out-of-order corporate state transition')
        account = self.account
        if stage == 'ACCOUNTING_EFFECTIVE_DATE':
            if ex_price is None or not isfinite(ex_price) or ex_price <= 0:
                raise ValueError('legally available ex-date mark required')
            if any(eid not in account.lots or account.lots[eid]['quantity'] != lot['quantity'] for eid,lot in event['lots'].items()):
                raise ValueError('record holdings changed before accounting; native basis rule missing')
            for eid, prior in event['lots'].items():
                lot = account.lots[eid]
                qty = prior['quantity'] * event['ratio']
                basis = lot['remaining_outlay'] * event['ratio'] / (1 + event['ratio'])
                lot['remaining_outlay'] -= basis
                key = f'{eid}|CA|{event_id}'
                account.lots[key] = {**deepcopy(prior), 'event_id':key, 'quantity':0., 'pending_quantity':qty,
                    'nontradable_quantity':0., 'remaining_outlay':basis, 'entitlement_event':event_id, 'root_event_id':prior.get('root_event_id',eid)}
                account.pending_positions[event['symbol']] = account.pending_positions.get(event['symbol'], 0.) + qty
            account.mark({event['symbol']:ex_price}, observed_at=when)
        else:
            for lot in account.lots.values():
                if lot.get('entitlement_event') != event_id:
                    continue
                if stage == 'SHARE_ARRIVAL_DATE':
                    qty = lot['pending_quantity']
                    lot.update(quantity=qty, pending_quantity=0., nontradable_quantity=qty)
                    account.pending_positions[event['symbol']] -= qty
                    account.positions[event['symbol']] = account.positions.get(event['symbol'],0.) + qty
                else:
                    lot['nontradable_quantity'] = 0.
            if stage == 'SHARE_ARRIVAL_DATE':
                if abs(account.pending_positions.get(event['symbol'],0.)) < 1e-10:
                    account.pending_positions.pop(event['symbol'],None)
        event.update(phase=stage, last=when)
        return account.checkpoint(when, stage)


class CashDistribution:
    """Record-date entitlements paid at the explicit legal payment checkpoint.

    Only same-ex-date payment is admitted here: delayed receivables need a
    separate evidenced NAV representation, and cannot silently vanish in transit.
    """
    def __init__(self, account):
        self.account = account
        self.events = {}

    def record(self, event_id, symbol, per_share, when, available_at, *, ex_date, payment_date, strategy=None):
        when, _ = ShareConversion._known_time(when, available_at)
        ex_date, payment_date = pd.Timestamp(ex_date), pd.Timestamp(payment_date)
        if pd.isna(ex_date) or ex_date != payment_date or ex_date.normalize() <= when.normalize():
            raise ValueError('unresolved dividend receivable timing')
        if event_id in self.events or not isfinite(per_share) or per_share < 0:
            raise ValueError('invalid dividend identity/amount')
        amounts = {}
        ownership=[]
        for lot in self.account.lots.values():
            if lot['symbol'] == symbol and (strategy is None or lot['strategy'] == strategy):
                if lot.get('pending_quantity',0):
                    raise ValueError('pending dividend basis unresolved')
                amounts[lot['strategy']] = amounts.get(lot['strategy'],0.) + lot['quantity'] * per_share
                ownership.append(dict(strategy=lot['strategy'],root_event_id=lot.get('root_event_id',lot['event_id']),funding_type=lot.get('funding_type','BASE'),amount=lot['quantity']*per_share))
        self.events[event_id] = dict(amounts=amounts,ownership=ownership,payment_date=payment_date,paid=False)

    def pay(self, event_id, when, available_at):
        when, _ = ShareConversion._known_time(when, available_at)
        event = self.events[event_id]
        if event['paid'] or when != event['payment_date']:
            raise ValueError('duplicate/illegal dividend payment')
        for strategy,amount in event['amounts'].items():
            self.account.cash += amount
            self.account.sleeve_cash[strategy] += amount
            self.account.realized[strategy] += amount
        self.account.cash_distributions.extend(dict(item,action_id=event_id,timestamp=when) for item in event['ownership'])
        event['paid'] = True
        return self.account.checkpoint(when,'CASH_PAYMENT_DATE')
