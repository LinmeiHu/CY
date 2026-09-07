"""Minimal explicit 4-state share conversion; synthetic until data is resolved.

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

    def record(self, event_id, symbol, ratio, when, available_at):
        when, available_at = self._known_time(when, available_at)
        if available_at > when or event_id in self.events or not isfinite(ratio) or ratio <= 0:
            raise ValueError('invalid/unknown conversion record')
        lots = {eid: deepcopy(lot) for eid,lot in self.account.lots.items() if lot['symbol'] == symbol}
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
                    'nontradable_quantity':0., 'remaining_outlay':basis, 'entitlement_event':event_id}
                account.pending_positions[event['symbol']] = account.pending_positions.get(event['symbol'], 0.) + qty
            account.mark({event['symbol']:ex_price})
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
