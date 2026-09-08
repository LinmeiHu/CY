"""One research cash account and attributed lots, with event-level reconciliation.

Prices/exit decisions must come from native adapters at legal checkpoints.
This engine deliberately has no outcome-table input or automatic exit rule.
"""
from dataclasses import asdict, dataclass
from math import floor, isfinite

import pandas as pd

from .allocator import active_strategies, base_headroom, capped_headroom, exact_confirmation, proportional_cash


def account_timestamp(value):
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError('invalid account timestamp')
    return timestamp


@dataclass(frozen=True)
class Intent:
    strategy: str
    route: str
    family: str
    event_id: str
    parent_event_id: str
    symbol: str
    decision_at: object
    earliest_execution_at: object
    native_priority: tuple
    native_requested_quantity: float
    price: float
    fee_rate: float
    lot_size: int = 0  # zero = explicitly fractional normalized research units
    price_basis: str = "RAW"
    side: str = "BUY"
    reason: str = "NATIVE_ELIGIBLE"
    state_requirements: str = "NATIVE_ADAPTER_ACTUAL_FUNDED_STATE"
    economic_event_definition: str = ""
    board: str = "COMBINED"
    native_base_cash_limit: float | None = None
    native_max_positions: int | None = None
    native_daily_entries: int | None = None

    @property
    def native_requested_notional(self):
        # Match the actual cash bill's unit-cost multiplication exactly. At
        # large native orders, alternate association can falsely reject a fully
        # affordable request by several floating-point ULPs.
        return self.native_requested_quantity * (self.price * (1 + self.fee_rate))

    def identity(self):
        return {**asdict(self), "direction": "LONG", "decision_timestamp": self.decision_at,
                "entry_session": self.earliest_execution_at, "economic_event_definition": self.economic_event_definition}


class PhysicalAccount:
    def __init__(self, gap, *, initial_cash=4_000_000.0):
        if not isfinite(initial_cash) or initial_cash <= 0:
            raise ValueError("invalid initial cash")
        self.strategies = active_strategies(gap)
        self.initial_cash = self.cash = initial_cash
        self.sleeve_cash = {s: initial_cash / 4 for s in self.strategies}
        self.lots, self.positions, self.marks = {}, {}, {}
        self.pending_positions = {}
        self.price_bases = {}
        self.mark_times = {}
        self.account_timeline = []
        self.cash_distributions = []
        self.realized = {s: 0.0 for s in self.strategies}
        self.fees = 0.0
        self.checkpoints, self.fills, self.rejections, self.shortfalls = [], [], [], []
        self.seen = set()
        self.native_failures = {}

    def exposure(self, strategy=None):
        return sum((lot["quantity"] + lot.get("pending_quantity", 0.)) * self.marks[lot["symbol"]] for lot in self.lots.values()
                   if strategy is None or lot["strategy"] == strategy)

    def mark(self, prices, *, basis=None, observed_at=None):
        if any(not isfinite(v) or v <= 0 for v in prices.values()):
            raise ValueError("invalid mark")
        if observed_at is not None:
            observed_at = account_timestamp(observed_at)
            prices = {s:p for s,p in prices.items() if s not in self.mark_times or observed_at >= self.mark_times[s]}
        if basis is not None:
            if any(s in self.price_bases and self.price_bases[s] != basis for s in prices):
                raise ValueError('physical symbol price-unit conflict: raw conversion required')
            self.price_bases.update({s:basis for s in prices})
        if observed_at is not None:
            self.mark_times.update({s:observed_at for s in prices})
        self.marks.update(prices)

    def complete_timestamp(self, when):
        import pandas as pd
        when=pd.Timestamp(when)
        if self.account_timeline and when <= self.account_timeline[-1]['timestamp']:
            raise ValueError('duplicate/backward physical account timestamp')
        row=self.checkpoint(when,'ACCOUNT_TIMESTAMP_COMPLETE')
        self.account_timeline.append(dict(row))
        return row

    def checkpoint(self, when, stage):
        when = account_timestamp(when)
        virtual, pending = {}, {}
        for lot in self.lots.values():
            quantities = (lot['quantity'], lot.get('pending_quantity', 0.), lot.get('nontradable_quantity', 0.), lot['remaining_outlay'])
            if any(not isfinite(v) or v < 0 for v in quantities) or lot.get('nontradable_quantity', 0.) > lot['quantity']:
                raise ValueError('nonfinite/invalid virtual quantities or basis')
            if lot['quantity']:
                virtual[lot["symbol"]] = virtual.get(lot["symbol"], 0.0) + lot["quantity"]
            if lot.get('pending_quantity', 0.):
                pending[lot['symbol']] = pending.get(lot['symbol'], 0.) + lot['pending_quantity']
        if any(not isfinite(v) or v < 0 for v in [*self.positions.values(), *self.pending_positions.values()]):
            raise ValueError('nonfinite/invalid physical quantities')
        if set(pending) != set(self.pending_positions) or any(abs(q-self.pending_positions[s]) > 1e-8 for s,q in pending.items()):
            raise ValueError('physical/virtual pending quantity mismatch')
        if set(virtual) != set(self.positions) or any(abs(q - self.positions[s]) > 1e-8 for s, q in virtual.items()):
            raise ValueError("physical/virtual quantity mismatch")
        gross = sum((q + self.pending_positions.get(s,0.)) * self.marks[s] for s,q in self.positions.items())
        gross += sum(q*self.marks[s] for s,q in self.pending_positions.items() if s not in self.positions)
        if abs(gross - self.exposure()) > 1e-6:
            raise ValueError('physical/virtual marked exposure mismatch')
        nav = self.cash + gross
        unrealized = sum((lot["quantity"] + lot.get("pending_quantity", 0.)) * self.marks[lot["symbol"]] - lot["remaining_outlay"] for lot in self.lots.values())
        pnl_nav = self.initial_cash + sum(self.realized.values()) + unrealized
        if not all(isfinite(v) for v in (self.cash, gross, nav, pnl_nav, self.fees, *self.sleeve_cash.values(), *self.realized.values())) or nav <= 0:
            raise ValueError("nonfinite/invalid account")
        if self.cash < -1e-8 or gross > nav + 1e-8:
            raise ValueError("financed account")
        if abs(pnl_nav - nav) > 1e-6 or abs(sum(self.sleeve_cash.values()) - self.cash) > 1e-6:
            raise ValueError("physical/virtual equity mismatch")
        row = {"checkpoint_id": len(self.checkpoints), "timestamp": when, "stage": stage,
               "cash": self.cash, "gross_exposure": gross, "nav": nav,
               "virtual_nav": pnl_nav, "pnl_delta": pnl_nav - nav, "quantity_delta": 0.0, "fees": self.fees}
        self.checkpoints.append(row)
        return row

    def close(self, event_id, price, when, fee_rate, *, quantity=None, reason="NATIVE_EXIT"):
        when = account_timestamp(when)
        lot = self.lots[event_id]
        tradable = lot["quantity"] - lot.get("nontradable_quantity", 0.)
        qty = tradable if quantity is None else quantity
        if not all(isfinite(v) for v in (qty, price, fee_rate)) or qty <= 0 or qty > tradable or price <= 0 or fee_rate < 0:
            raise ValueError("invalid native exit")
        self.mark({lot["symbol"]: price}, observed_at=when)
        fraction = qty / lot["quantity"]
        basis = lot["remaining_outlay"] * fraction
        fee = qty * price * fee_rate
        proceeds = qty * price - fee
        pnl = proceeds - basis
        self.cash += proceeds
        self.sleeve_cash[lot["strategy"]] += proceeds
        self.realized[lot["strategy"]] += pnl
        self.fees += fee
        self.fills.append({**lot, "side": "SELL", "exit": when, "exit_price": price, "filled_quantity": qty,
                           "pnl": pnl, "fee": fee, "reason": reason})
        lot["quantity"] -= qty
        lot["remaining_outlay"] -= basis
        self.positions[lot["symbol"]] -= qty
        if lot["quantity"] == 0 and not lot.get("pending_quantity", 0.):
            del self.lots[event_id]
        if not any(l['symbol']==lot['symbol'] and l['quantity'] for l in self.lots.values()):
            if abs(self.positions[lot['symbol']]) > 1e-8: raise ValueError('physical exit residual exceeds quantity tolerance')
            del self.positions[lot['symbol']]
        return self.checkpoint(when, "NATIVE_EXIT")

    def credit(self, event_id, per_share, when):
        when = account_timestamp(when)
        if not isfinite(per_share) or per_share < 0:
            raise ValueError("invalid corporate cash credit")
        lot = self.lots[event_id]
        amount = lot["quantity"] * per_share
        self.cash += amount
        self.sleeve_cash[lot["strategy"]] += amount
        self.realized[lot["strategy"]] += amount
        return self.checkpoint(when, "NATIVE_CASH_EVENT")

    def _native_rejection(self,intent,when):
        if intent.native_max_positions is None and intent.native_daily_entries is None:return None
        import pandas as pd
        live=[(eid,l) for eid,l in self.lots.items() if l['strategy']==intent.strategy and l.get('board')==intent.board]
        if any(l['symbol']==intent.symbol for _,l in live):return 'ACTIVE_SYMBOL'
        if intent.native_max_positions is not None and len({l.get('root_event_id',eid) for eid,l in live})>=intent.native_max_positions:return 'MAX_K'
        count=sum(f['side']=='BUY' and f['strategy']==intent.strategy and f.get('board')==intent.board and pd.Timestamp(f['entry']).normalize()==pd.Timestamp(when).normalize() for f in self.fills)
        if intent.native_daily_entries is not None and count>=intent.native_daily_entries:return 'DAILY_CAP'
        return None

    def validate_intents(self, intents, when):
        """Check the native order boundary before either funding path mutates it."""
        when = account_timestamp(when)
        batch_bases = dict(self.price_bases)
        for intent in intents:
            if intent.symbol in batch_bases and batch_bases[intent.symbol] != intent.price_basis:
                raise ValueError("physical symbol price-unit conflict: raw conversion required")
            batch_bases[intent.symbol] = intent.price_basis
            if intent.strategy not in self.strategies or not intent.event_id or intent.side != "BUY":
                raise ValueError("invalid active strategy/intent")
            decision = account_timestamp(intent.decision_at)
            execution = account_timestamp(intent.earliest_execution_at)
            if decision >= execution or execution > when:
                raise ValueError("future or unfinished-bar intent")
            if intent.native_base_cash_limit is not None and (not isfinite(intent.native_base_cash_limit) or intent.native_base_cash_limit < 0):
                raise ValueError('invalid native cash limit')
            if not all(isfinite(v) for v in (intent.price, intent.fee_rate, intent.native_requested_quantity)) or intent.price <= 0 or intent.fee_rate < 0 or intent.native_requested_quantity <= 0:
                raise ValueError("invalid native sizing")
            if not isfinite(intent.lot_size) or intent.lot_size < 0 or int(intent.lot_size) != intent.lot_size:
                raise ValueError('invalid native lot size')
            for limit in (intent.native_max_positions, intent.native_daily_entries):
                if limit is not None and (not isfinite(limit) or limit < 0 or int(limit) != limit):
                    raise ValueError('invalid native capacity')

    def _fill(self, intent, budget, kind, when):
        reason=self._native_rejection(intent,when)
        if reason:
            if intent.event_id not in self.native_failures:
                self.native_failures[intent.event_id]=reason
                self.rejections.append(dict(event_id=intent.event_id,reason=reason))
            return False
        requested = intent.native_requested_notional
        unit = intent.price * (1 + intent.fee_rate)
        budget = min(budget, self.cash, requested)
        if intent.lot_size:
            # Preserve an already integral native request when fully affordable;
            # multiplying then dividing its cost can round 100 shares to 99.999…
            if budget >= requested:
                qty = floor(intent.native_requested_quantity / intent.lot_size) * intent.lot_size
            else:
                qty = floor(max(0.0, budget) / unit / intent.lot_size) * intent.lot_size
        else:
            # Native stock accounts reject a whole slot if its outlay is unavailable.
            qty = intent.native_requested_quantity if budget + 1e-9 >= requested else 0.0
        if qty <= 0:
            return False
        outlay, fee = qty * unit, qty * intent.price * intent.fee_rate
        self.cash -= outlay
        self.sleeve_cash[intent.strategy] -= outlay
        self.fees += fee
        self.mark({intent.symbol: intent.price}, basis=intent.price_basis, observed_at=when)
        lot = {**asdict(intent), "quantity": qty, "funding_type": kind, "entry": when,
               "requested_notional": requested, "funded_notional": outlay, "remaining_outlay": outlay}
        self.lots[intent.event_id] = lot
        self.positions[intent.symbol] = self.positions.get(intent.symbol, 0.0) + qty
        self.fills.append({**lot, "side": "BUY", "fee": fee})
        self.checkpoint(when, kind)
        return True

    def fund(self, intents, home, policy, when, *, gate_multiplier=1.0, mcb_mode="independent", base_only=False, available_capacity=None):
        intents = list(intents)
        when = account_timestamp(when)
        self.validate_intents(intents, when)
        if policy not in ("P0", "P1", "P2", "P3_D4", "P3_D5", "P3_D6"):
            raise ValueError("unknown frozen policy")
        if set(home) != set(self.strategies) or any(not isfinite(v) or v <= 0 for v in home.values()):
            raise ValueError("invalid independent P0 home budget")
        if mcb_mode not in ("independent", "confirmation_tag") or not 0 <= gate_multiplier <= 1:
            raise ValueError("invalid policy state")
        queues={s:sorted((i for i in intents if i.strategy==s),key=lambda i:(i.native_priority,i.event_id,i.symbol)) for s in {i.strategy for i in intents}}
        ordered=[]
        while any(queues.values()):
            strategy=min((s for s in queues if queues[s]),key=lambda s:(queues[s][0].decision_at,s,queues[s][0].event_id,queues[s][0].symbol))
            ordered.append(queues[strategy].pop(0))
        ids = [i.event_id for i in ordered]
        if len(set(ids)) != len(ids) or any(i in self.seen for i in ids):
            raise ValueError("intent duplicate/replay would enlarge funded trade")
        self.seen.update(ids)
        # The contract retains ATRDR's lot/priority in an exact overlap. Resolve
        # its native capacity first; a capacity-rejected ATRDR candidate cannot
        # suppress an otherwise executable MCB-only opportunity.
        pending = ([i for i in ordered if i.strategy=='ATRDR']+[i for i in ordered if i.strategy!='ATRDR']) if mcb_mode=='confirmation_tag' else ordered
        exposure = {s: self.exposure(s) for s in self.strategies}
        remaining_base = {s: base_headroom(home[s], exposure[s]) for s in self.strategies}
        # Freeze each checkpoint's capacity once: repeated orders cannot reset the DD allowance.
        entry_capacity = self.cash * (gate_multiplier if policy.startswith("P3") else 1.0) if available_capacity is None else min(self.cash,available_capacity)
        unfunded = []
        board_remaining={}
        for intent in pending:
            if intent.native_base_cash_limit is not None:
                key=(intent.strategy,intent.board)
                board_remaining[key]=min(board_remaining.get(key,float('inf')),intent.native_base_cash_limit)
        for intent in pending:
            if mcb_mode=='confirmation_tag' and intent.strategy=='MCB' and any(a.event_id not in self.native_failures and exact_confirmation(a.identity(),intent.identity()) for a in pending):
                self.rejections.append(dict(event_id=intent.event_id,reason='EXACT_CONFIRMATION_TAG'))
                continue
            s = intent.strategy
            budget = min(remaining_base[s], self.cash, entry_capacity)
            if policy == "P0":
                budget = min(budget, self.sleeve_cash[s])
            if intent.native_base_cash_limit is not None:
                budget = min(budget, board_remaining[(s,intent.board)])
            if policy not in ("P0", "P1"):
                budget = min(budget, capped_headroom(s, home, {k: self.exposure(k) for k in self.strategies}))
            prior_cash = self.cash
            if self._fill(intent, budget, "BASE", when):
                used = prior_cash - self.cash
                remaining_base[s] -= used
                if (s,intent.board) in board_remaining:board_remaining[(s,intent.board)]-=used
                entry_capacity -= used
            else:
                if intent.event_id in self.native_failures:continue
                unfunded.append(intent)
                if remaining_base[s] >= intent.native_requested_notional and self.cash < intent.native_requested_notional:
                    self.shortfalls.append({"timestamp": when, "strategy": s, "event_id": intent.event_id,
                                            "requested": intent.native_requested_notional, "cash": self.cash,
                                            "reason": "BASE_ENTITLEMENT_SHORTFALL"})
        if base_only and policy != 'P0':
            self.checkpoint(when,'ALL_CURRENT_BASE_DEMANDS_PROCESSED')
            return unfunded
        if policy == "P0":
            if any(v < -1e-8 for v in self.sleeve_cash.values()):
                raise ValueError("P0 cross-sleeve financing")
            for intent in unfunded:
                self.rejections.append({"event_id": intent.event_id, "reason": "SEGMENTATION_IDLE" if self.cash >= intent.native_requested_notional else "GLOBAL_DEMAND_CONFLICT"})
            return self.checkpoint(when, "FUNDING_COMPLETE")
        return self.fund_shared(unfunded,home,policy,when,entry_capacity,gate_multiplier=gate_multiplier)

    def fund_shared(self, unfunded, home, policy, when, entry_capacity, *, gate_multiplier=1.):
        if policy=='P0' or any(i.event_id not in self.seen or i.event_id in self.lots for i in unfunded):
            raise ValueError('shared funding requires previously unfunded native base requests')
        unmet = {s: sum(i.native_requested_notional for i in unfunded if i.strategy == s) for s in self.strategies}
        shares = proportional_cash(min(self.cash, entry_capacity), unmet)
        residual = []
        for intent in unfunded:
            s = intent.strategy
            budget = min(float(shares[s]), entry_capacity)
            if policy not in ("P0", "P1"):
                budget = min(budget, capped_headroom(s, home, {k: self.exposure(k) for k in self.strategies}))
            before = self.cash
            if self._fill(intent, budget, "SHARED", when):
                shares[s] -= type(shares[s])(str(before - self.cash))
                entry_capacity -= before - self.cash
            else:
                if intent.event_id not in self.native_failures:residual.append(intent)
        # One intent may be filled only once. Residual quota cannot top up a
        # base/shared-filled lot. Largest fractional native-unit remainder
        # wins; deterministic native priority resolves equal remainders.
        def remainder(i):
            unit = i.price * (1 + i.fee_rate) * i.lot_size if i.lot_size else i.native_requested_notional
            quota = float(shares[i.strategy]) / unit
            return (-(quota - floor(quota)), i.decision_at, i.strategy, i.native_priority, i.event_id, i.symbol)
        for intent in sorted(residual, key=remainder):
            budget = min(self.cash, entry_capacity)
            if policy != "P1":
                budget = min(budget, capped_headroom(intent.strategy, home, {s: self.exposure(s) for s in self.strategies}))
            before = self.cash
            if self._fill(intent, budget, "SHARED", when):
                entry_capacity -= before - self.cash
                continue
            if intent.event_id in self.native_failures:continue
            reason = "GLOBAL_DEMAND_CONFLICT"
            if self.cash >= intent.native_requested_notional:
                reason = "DRAWDOWN_GATE_BLOCK" if policy.startswith("P3") and gate_multiplier < 1 else "FAMILY_CAP_BLOCK" if policy != "P1" else "NATIVE_LOT_ALLOCATION_BLOCK"
            self.rejections.append({"event_id": intent.event_id, "reason": reason})
        return self.checkpoint(when, "FUNDING_COMPLETE")
