"""Capital-only operator attached to the live native chronological account.

Native reference requests define *relative desired size*, never fills or exits.
The native adapters own membership and exit state and receive actual scaled fills.
Unexecuted adjustments are fixed share orders, not a daily rebalancing rule.
"""
from collections import defaultdict
from copy import deepcopy
from dataclasses import replace
import json
from math import floor, isfinite, nextafter

import pandas as pd

from research.shared_capital_v1.shared_account.engine import Intent, account_timestamp
from research.shared_capital_v1.shared_account.allocator import exact_confirmation
from research.shared_capital_v1.shared_account.scheduler import Event
from research.shared_capital_v1.smv6_physical import PhysicalPlatform
from five_strategy_bundle.strategies.smv6 import Position


class ScalingPlatform(PhysicalPlatform):
    """Exact frozen callbacks with capital policy at the native order boundary."""
    def order_target_percent(self, symbol, target_weight):
        if not isfinite(target_weight) or target_weight < 0:
            raise ValueError('invalid native ETF target')
        controller = self.physical.scaling
        self.nav('open')  # same-day future close never enters opening sizing
        row = self._current_row(symbol)
        if self.event_stage != 'open' or row is None or not bool(row.executable_09_30):
            return None
        mark = self._mark(symbol, 'open')
        old = self.shares.get(symbol, 0.)
        root = controller.etf_roots.get(symbol)
        if root is None:
            root = f'SMV6|{self.current_date}|{symbol}|{len(self.intent_rows)}'
        home = controller.home('SMV6', self._timestamp())
        native_qty = floor(home * target_weight / mark / 100) * 100
        if native_qty <= 0:
            return self.order_target(symbol, 0) if old > 0 else None
        intent = Intent('SMV6', 'NATIVE_CALLBACK', 'ETF_TIMING', root, '', symbol,
                        pd.Timestamp(self.current_date), self._timestamp(), (len(self.intent_rows),),
                        native_qty, mark, self.commission_rate, lot_size=100,
                        price_basis='PRE_ADJUSTED_ETF')
        self.intent_rows.append(dict(event_id=root, symbol=symbol, target_weight=target_weight,
                                     native_requested_quantity=native_qty, timestamp=self._timestamp()))
        controller.etf_roots[symbol] = root
        controller.etf_weights[symbol] = target_weight
        controller.set_desired(intent, self._timestamp(), 'NATIVE_TARGET_CHANGE')
        controller.sync_etf()
        actual = self.shares.get(symbol, 0.)
        self._record('BUY_FILLED' if old == 0 and actual else 'REBALANCE_FILLED', symbol,
                     price=mark, target_weight=target_weight, requested_qty=native_qty,
                     filled_delta_qty=actual-old, position_qty=actual)
        return None if actual == 0 else f'scaled-native-target-{root}'

    def order_target(self, symbol, target):
        if target != 0:
            raise ValueError('native liquidation target only')
        controller = self.physical.scaling
        root = controller.etf_roots.get(symbol)
        if root is not None:
            controller.desired.pop(root, None)
            controller.pending.pop(root, None)
        result = super().order_target(symbol, target)
        controller.sync_etf()
        return result


class Scaling:
    platform_class = ScalingPlatform

    def __init__(self, selected, target, *, grade='EXECUTION_AWARE_SCALING', mechanic='FULL_BOOK_NORMALIZATION',
                 priority=None, mode='independent'):
        selected = tuple(selected)
        if not selected or len(set(selected)) != len(selected) or not set(selected) <= {'ATRDR', 'MCB', 'OGR', 'IFCGR', 'SMV6'}:
            raise ValueError('invalid scaling strategy selection')
        if priority is not None and priority not in selected:
            raise ValueError('inactive priority strategy')
        if mode not in ('independent', 'confirmation_tag'):
            raise ValueError('invalid MCB mode')
        if target not in (.25, .50, .75, 1.):
            raise ValueError('unregistered gross target')
        if grade not in ('EXECUTION_AWARE_SCALING', 'IDEALIZED_SCALING_BOUND'):
            raise ValueError('execution grade')
        if mechanic != 'FULL_BOOK_NORMALIZATION' and (mechanic != 'ENTRY_ONLY' or target != 1.):
            raise ValueError('entry-only is G100 diagnostic only')
        if {'OGR', 'IFCGR'} <= set(selected):
            raise ValueError('Gap mutual exclusion')
        self.selected, self.target, self.grade = tuple(selected), target, grade
        self.mechanic, self.priority, self.mode = mechanic, priority, mode
        self.desired, self.pending, self.board_cash = {}, {}, {}
        self.etf_roots, self.etf_weights = {}, {}
        self.normalizations, self.orders, self.capacity, self.membership = [], [], [], []
        self.platform = None
        self.dirty = set()
        self.first_pending_at = None
        self.serial = 0

    def bind(self, account, states, data, period, start, end):
        self.account, self.data, self.period = account, data, period
        self.start, self.end = pd.Timestamp(start), pd.Timestamp(end)
        account.scaling = self
        # A standalone uses exactly its validated parent's capital and holdings.
        for s in account.strategies:
            if s not in self.selected:
                account.sleeve_cash[s] = 0.
                account.initial_states[s] = dict(account.initial_states[s], cash=0., nav=0.)
        account.lots = {k: v for k, v in account.lots.items() if v['strategy'] in self.selected}
        account.positions = {}
        for lot in account.lots.values():
            account.positions[lot['symbol']] = account.positions.get(lot['symbol'], 0.) + lot['quantity']
        account.cash = sum(account.sleeve_cash.values())
        account.initial_cash = sum(states[s]['nav'] for s in self.selected)
        account.checkpoints.clear()
        account.checkpoint(start, 'VALIDATED_NATIVE_INITIAL_STATE')
        self.original_fill, self.original_close = account._fill, account.close
        account.fund, account.close = self.fund, self.native_close
        for eid, lot in account.lots.items():
            base = {f: lot[f] for f in Intent.__dataclass_fields__ if f in lot}
            self.desired[eid] = Intent(**dict(base, native_requested_quantity=lot['quantity'], price=account.marks[lot['symbol']]))
        self.initial_desired = deepcopy(self.desired)

    def home(self, strategy, when):
        frame = self.data['native_home'][(self.period, self.data['gap'])]
        n = frame.index.searchsorted(pd.Timestamp(when), side='right') - 1
        return float(frame.iloc[n][strategy+'_nav']) if n >= 0 else self.account.initial_states[strategy]['nav']

    def native_notional(self, event_id, strategy, board, when):
        item = self.data['native_requests'].get((self.period, self.data['gap'], strategy, event_id))
        if item is None:
            # No fabricated native slot; a changed actual membership can expose
            # a candidate the native reference never admitted to capital demand.
            return 0.
        return item['native_requested_notional']

    def roots(self, eid):
        return [(k, l) for k, l in self.account.lots.items() if k == eid or l.get('root_event_id') == eid]

    def root_quantity(self, eid):
        return sum(l['quantity'] + l.get('pending_quantity', 0.) for _, l in self.roots(eid))

    def native_close(self, event_id, price, when, fee_rate, *, quantity=None, reason='NATIVE_EXIT'):
        when = account_timestamp(when)
        lot = self.account.lots[event_id]
        root = lot.get('root_event_id', event_id)
        self.desired.pop(root, None)
        self.pending.pop(root, None)
        self.dirty.add(lot['strategy'])
        tradable = self.tradable(lot, when)
        qty = min(tradable, tradable if quantity is None else quantity)
        if qty <= 0:
            return self.account.checkpoint(when, 'NATIVE_EXIT_PENDING_TRADABLE_INVENTORY')
        row = self.original_close(event_id, price, when, fee_rate, quantity=qty, reason=reason)
        self.orders.append(dict(timestamp=when, event_id=root, symbol=lot['symbol'], strategy=lot['strategy'],
                                side='SELL', quantity=qty, price=price, notional=qty*price, reason=reason,
                                nav=row['nav'], fee=qty*price*fee_rate, native=True))
        return row

    @staticmethod
    def tradable(lot, when):
        quantity = lot['quantity'] - lot.get('nontradable_quantity', 0.)
        if lot['strategy'] != 'SMV6' and pd.Timestamp(lot.get('acquired_at', lot.get('entry'))).normalize() >= pd.Timestamp(when).normalize():
            return 0.
        return quantity

    def prices(self, when):
        when = pd.Timestamp(when)
        values = self.data['quotes'].get(when, {})
        quotes = dict(values)
        if self.platform is not None and (when.hour, when.minute) == (9, 30):
            for symbol in set(self.etf_roots) | set(self.platform.shares):
                row = self.platform._current_row(symbol)
                if row is not None and bool(row.executable_09_30):
                    p = self.platform._minute_price(symbol, 'OPEN_BAR_09_30', 'pre_adj_open')
                    if isfinite(p) and p > 0:
                        quotes[symbol] = dict(price=p, buy=True, sell=True)
        return quotes

    def mark_quotes(self, when, quotes):
        needed = set(self.account.positions) | set(self.account.pending_positions) | {i.symbol for i in self.desired.values()}
        for symbol in needed:
            q = quotes.get(symbol)
            if q is not None:
                self.account.mark({symbol: q['price']}, observed_at=when)

    def _valid_intents(self, intents, when):
        intents = list(intents)
        if any(i.strategy not in self.selected for i in intents):
            raise ValueError('inactive scaling strategy')
        ids = [i.event_id for i in intents]
        if len(set(ids)) != len(ids) or any(eid in self.account.seen for eid in ids):
            raise ValueError('intent duplicate/replay would enlarge funded trade')
        # A missing native reference is a rejected demand, never a fabricated slot.
        eligible = [i for i in intents if not (i.native_requested_quantity <= 0 or
                    (self.period, self.data['gap'], i.strategy, i.event_id) not in self.data['native_requests'])]
        self.account.validate_intents([replace(i, native_base_cash_limit=None) for i in eligible], when)
        self.account.seen.update(ids)
        batch = []
        counts = defaultdict(int)
        for i in sorted(intents, key=lambda x: (x.strategy != 'ATRDR', x.native_priority, x.event_id)):
            if i.native_requested_quantity <= 0 or (self.period, self.data['gap'], i.strategy, i.event_id) not in self.data['native_requests']:
                self.account.native_failures[i.event_id] = 'NO_FROZEN_NATIVE_REFERENCE_REQUEST'
                continue
            live = [(eid, d) for eid, d in self.desired.items() if d.strategy == i.strategy and d.board == i.board]
            actual = [l for l in self.account.lots.values() if l['strategy'] == i.strategy and l.get('board') == i.board]
            native_today = {f.get('root_event_id', f['event_id']) for f in self.account.fills if f['side'] == 'BUY' and f['strategy'] == i.strategy and f.get('board') == i.board and pd.Timestamp(f['entry']).normalize() == pd.Timestamp(when).normalize() and f.get('reason') != 'CAPITAL_SCALE_ADJUSTMENT'}
            reason = None
            if any(d.symbol == i.symbol for _, d in live) or any(l['symbol'] == i.symbol for l in actual):
                reason = 'ACTIVE_SYMBOL'
            elif i.native_max_positions is not None and len(live) >= i.native_max_positions:
                reason = 'MAX_K'
            elif i.native_daily_entries is not None and len(native_today) + counts[(i.strategy, i.board)] >= i.native_daily_entries:
                reason = 'DAILY_CAP'
            elif self.mode == 'confirmation_tag' and i.strategy == 'MCB' and any(exact_confirmation(a.identity(), i.identity()) for a in batch):
                reason = 'EXACT_CONFIRMATION_TAG'
            if reason:
                self.account.native_failures[i.event_id] = reason
                self.account.rejections.append(dict(event_id=i.event_id, reason=reason))
                continue
            counts[(i.strategy, i.board)] += 1
            self.desired[i.event_id] = i
            self.membership.append(dict(timestamp=when, strategy=i.strategy, event_id=i.event_id, symbol=i.symbol, reason='NATIVE_VALID_REQUEST'))
            batch.append(i)
        return batch

    def fund(self, intents, home, policy, when, **kwargs):
        batch = self._valid_intents(intents, when)
        incoming = {i.event_id for i in batch}
        self.normalize(when, {i.strategy for i in batch}, incoming=incoming, reason='NATIVE_ENTRY')
        for i in batch:
            if not self.roots(i.event_id):
                self.desired.pop(i.event_id, None)
                self.pending.pop(i.event_id, None)
                self.account.rejections.append(dict(event_id=i.event_id, reason='CAPITAL_OR_EXECUTION_UNFUNDED'))
        return self.account.checkpoint(when, 'SCALING_FUNDING_COMPLETE')

    def set_desired(self, intent, when, reason):
        if intent.strategy not in self.selected:
            raise ValueError('inactive scaling strategy')
        self.account.validate_intents([intent], when)
        old = self.desired.get(intent.event_id)
        self.desired[intent.event_id] = intent
        self.membership.append(dict(timestamp=when, strategy=intent.strategy, event_id=intent.event_id, symbol=intent.symbol, reason=reason))
        if self.mechanic == 'ENTRY_ONLY' and old is not None and intent.native_requested_quantity < old.native_requested_quantity:
            self.pending[intent.event_id] = self.root_quantity(intent.event_id)*intent.native_requested_quantity/old.native_requested_quantity
            self.first_pending_at = pd.Timestamp(when)
            self.execute(when, self.prices(when))
            return
        self.normalize(when, {intent.strategy}, incoming={intent.event_id}, reason=reason)

    def normalize(self, when, changed, *, incoming=(), reason):
        if not changed:
            return
        quotes = self.prices(when)
        for eid in incoming:
            intent = self.desired[eid]
            quotes.setdefault(intent.symbol, dict(price=intent.price, buy=True, sell=True))
        self.mark_quotes(when, quotes)
        a = self.account
        nav = a.cash + a.exposure()
        amounts = {eid: i.native_requested_quantity * a.marks[i.symbol] for eid, i in self.desired.items()}
        total = sum(amounts.values())
        if not total:
            self.pending.clear()
            return
        if self.mechanic == 'ENTRY_ONLY':
            fresh = {eid: amounts[eid] for eid in incoming if eid in amounts}
            spare = max(0., self.target*nav-a.exposure())
            targets = {eid: self.root_quantity(eid) for eid in amounts}
            for eid, amount in fresh.items():
                targets[eid] += spare * amount / sum(fresh.values()) / a.marks[self.desired[eid].symbol]
        elif self.priority:
            ordinary = {eid: v for eid, v in amounts.items() if self.desired[eid].strategy != self.priority}
            designated = {eid: v for eid, v in amounts.items() if self.desired[eid].strategy == self.priority}
            spare = max(0., self.target*nav-sum(ordinary.values()))
            targets = {eid: v/a.marks[self.desired[eid].symbol] for eid, v in ordinary.items()}
            for eid, value in designated.items():
                scaled = spare*value/sum(designated.values())/a.marks[self.desired[eid].symbol]
                targets[eid] = scaled if self.priority in changed else min(self.root_quantity(eid), scaled)
        else:
            # Solve only transaction-cost accounting. This is not an economic
            # optimizer: weights and gross target are fixed by the contract.
            low, high = 0., self.target*nav
            for _ in range(48):
                gross = (low+high)/2
                costs = 0.
                for eid, value in amounts.items():
                    intent = self.desired[eid]
                    delta = gross*value/total-self.root_quantity(eid)*a.marks[intent.symbol]
                    slip = .0008 if intent.strategy == 'SMV6' else 0.
                    rate = (1+slip)*(1+intent.fee_rate)-1 if delta >= 0 else 1-(1-slip)*(1-intent.fee_rate)
                    costs += abs(delta)*rate
                if gross <= self.target*(nav-costs):
                    low = gross
                else:
                    high = gross
            targets = {eid: low*v/total/a.marks[self.desired[eid].symbol] for eid, v in amounts.items()}
        self.pending = targets
        self.first_pending_at = pd.Timestamp(when)
        before = len(self.orders)
        self.execute(when, quotes, incoming=set(incoming))
        actual = a.exposure()/(a.cash+a.exposure())
        desired_exposure = sum(self.root_quantity(eid)*a.marks[self.desired[eid].symbol] for eid in amounts)
        weight_error = max((abs(self.root_quantity(eid)*a.marks[self.desired[eid].symbol]/desired_exposure - value/total)
                            for eid, value in amounts.items()), default=0.) if desired_exposure else 1.
        self.normalizations.append(dict(timestamp=when, reason=reason, changed='|'.join(sorted(changed)),
                                        native_desired_total=total, desired_count=len(amounts), target_gross=self.target,
                                        actual_gross=actual, achieving_90pct=actual >= .9*self.target,
                                        orders=len(self.orders)-before, remaining_adjustments=len(self.pending),
                                        relative_weight_error=weight_error if self.mechanic == 'FULL_BOOK_NORMALIZATION' and not self.priority else None))

    def execute(self, when, quotes, incoming=()):
        a = self.account
        # Reductions are processed before additions across the complete book.
        for side in ('SELL', 'BUY'):
            for eid in sorted(list(self.pending)):
                intent = self.desired.get(eid)
                if intent is None:
                    self.pending.pop(eid, None)
                    continue
                current = self.root_quantity(eid)
                delta = self.pending[eid]-current
                if delta == 0:
                    self.pending.pop(eid, None)
                    continue
                quote = quotes.get(intent.symbol)
                if quote is None or not quote[side.lower()]:
                    continue
                if abs(delta)*quote['price'] < 1e-7:
                    self.pending.pop(eid, None)
                    continue
                if (side == 'SELL' and delta >= 0) or (side == 'BUY' and delta <= 0):
                    continue
                requested = abs(delta)
                if requested*quote['price'] < 1e-7:
                    self.pending.pop(eid, None)
                    continue
                if intent.strategy == 'SMV6':
                    cap = self.platform._volume_cap(intent.symbol, 'OPEN_BAR_09_30')
                    # Recover lot boundaries lost to the finite normalization
                    # solver; the actual cash bill is still checked below.
                    lot_tolerance = max(1e-9, requested * 2**-47)
                    qty = min(cap, floor((requested+lot_tolerance)/100)*100)
                    if requested > cap:
                        self.capacity.append(dict(timestamp=when, strategy=intent.strategy, symbol=intent.symbol,
                                                  requested=requested, capacity=cap, limited_notional=(requested-cap)*quote['price']))
                else:
                    qty = requested
                market = quote['price']
                slip = .0008 if intent.strategy == 'SMV6' else 0.
                price = market*(1+slip if side == 'BUY' else 1-slip)
                before_cash = a.cash
                if side == 'BUY':
                    unit = price*(1+intent.fee_rate)
                    nav = a.cash+a.exposure()
                    headroom = max(0., self.target*nav-a.exposure())
                    allowed = min(a.cash/unit, headroom/(market+self.target*(unit-market)))
                    if intent.strategy == 'SMV6':
                        qty = min(qty, floor((max(0., allowed)+lot_tolerance)/100)*100)
                        if qty*unit > a.cash:
                            qty -= 100
                    else:
                        qty = min(qty, nextafter(max(0., allowed), 0.))
                    if qty*price <= 1e-7:
                        continue
                    key = eid if eid not in a.lots else f'{eid}|SCALE|{self.serial}'
                    self.serial += 1
                    actual_intent = replace(intent, event_id=key, native_requested_quantity=qty, price=price,
                                            lot_size=0, native_max_positions=None, native_daily_entries=None,
                                            reason='NATIVE_ELIGIBLE' if eid in incoming and key == eid else 'CAPITAL_SCALE_ADJUSTMENT')
                    if not self.original_fill(actual_intent, qty*unit, 'SCALED', when):
                        raise ValueError('deterministic affordable fill rejected')
                    lot = a.lots[key]
                    lot.update(root_event_id=eid, acquired_at=when)
                    a.fills[-1].update(root_event_id=eid, acquired_at=when)
                    # Native new-stock entry callback performs its own debit.
                    if intent.strategy in self.board_cash and not (eid in incoming and key == eid):
                        self.board_cash[intent.strategy][intent.board] -= before_cash-a.cash
                else:
                    remaining = qty
                    for key, lot in sorted(self.roots(eid), key=lambda x: (x[0] == eid, x[0])):
                        sold = min(remaining, self.tradable(lot, when))
                        if sold <= 1e-12:
                            continue
                        self.original_close(key, price, when, intent.fee_rate, quantity=sold, reason='CAPITAL_TARGET_DECREASE')
                        remaining -= sold
                    qty -= remaining
                    if intent.strategy in self.board_cash:
                        self.board_cash[intent.strategy][intent.board] += a.cash-before_cash
                a.mark({intent.symbol: market}, observed_at=when)
                if qty > 1e-12:
                    self.orders.append(dict(timestamp=when, event_id=eid, symbol=intent.symbol, strategy=intent.strategy,
                                            side=side, quantity=qty, price=price, notional=qty*price,
                                            reason='CAPITAL_SCALE_ADJUSTMENT', nav=a.cash+a.exposure(),
                                            fee=qty*price*intent.fee_rate, native=False))
                difference = abs(self.root_quantity(eid)-self.pending[eid])
                if difference*market < 1e-6 or (intent.strategy == 'SMV6' and difference < 100):
                    self.pending.pop(eid, None)
        if (pd.Timestamp(when).hour, pd.Timestamp(when).minute) == (9, 30):
            # Frozen CAP50_SET is one-shot. A volume/rounding remainder does not
            # authorize daily target restoration when membership is unchanged.
            for eid in list(self.pending):
                if self.desired[eid].strategy == 'SMV6' and self.desired[eid].symbol in quotes:
                    self.pending.pop(eid)
        self.sync_etf()
        a.checkpoint(when, 'CAPITAL_ADJUSTMENTS_COMPLETE')

    def sync_etf(self):
        if self.platform is None:
            return
        quantities = defaultdict(float)
        for l in self.account.lots.values():
            if l['strategy'] == 'SMV6':
                quantities[l['symbol']] += l['quantity']
        p = self.platform
        p.shares = dict(quantities)
        for symbol in list(p.positions):
            if symbol not in quantities:
                p.positions.pop(symbol)
                self.etf_roots.pop(symbol, None)
        for symbol in quantities:
            if symbol not in p.positions:
                p.positions[symbol] = Position(symbol, self.etf_weights.get(symbol, 0.), p.current_date, self.account.marks[symbol])
            else:
                p.positions[symbol].target_weight = self.etf_weights.get(symbol, p.positions[symbol].target_weight)

    def wrap_streams(self, streams, calendar, platform):
        self.platform = platform
        extra_times = sorted(t for t in self.data['quotes'] if self.start <= t <= self.end+pd.Timedelta(hours=23))
        def drain(when):
            quotes = self.prices(when)
            self.mark_quotes(when, quotes)
            if self.dirty:
                changed = set(self.dirty)
                self.dirty.clear()
                self.normalize(when, changed, reason='PRIOR_NATIVE_EXIT')
            elif self.pending and when > self.first_pending_at:
                self.execute(when, quotes)
        def extra():
            for t in extra_times:
                yield Event(t, 'SCALING', 'CAPITAL', str(t), lambda t=t: drain(t))
        def wrapped(stream):
            for event in stream:
                callback = event.callback
                def apply(e=event, callback=callback):
                    callback()
                    if e.phase == 'ACTION':
                        # Desired reference shares use the same actual evidenced
                        # conversion ratio; no quantity is inferred from returns.
                        service = self.account.held_actions.get(e.strategy)
                        if service:
                            for action in service.audit:
                                key = (e.strategy, action['action_id'])
                                if action['ex_date'] == pd.Timestamp(e.when).normalize() and key not in applied:
                                    for root, intent in list(self.desired.items()):
                                        if intent.strategy == e.strategy and intent.symbol == action['symbol']:
                                            self.desired[root] = replace(intent, native_requested_quantity=intent.native_requested_quantity*(1+action['share_ratio']))
                                            if root in self.pending:
                                                self.pending[root] *= 1+action['share_ratio']
                                    applied.add(key)
                yield Event(event.when, event.phase, event.strategy, event.identity, apply)
        applied = set()
        return [wrapped(s) for s in streams] + [extra()]

    def completed(self, when):
        # Observe real scaled ownership. Never restore a position from a prior
        # accepted-trade ledger after the native account has exited it.
        live = {l.get('root_event_id', eid) for eid, l in self.account.lots.items()}
        for root in list(self.desired):
            if root not in live:
                self.desired.pop(root)
                self.pending.pop(root, None)
