"""One research cash account and attributed lots, with event-level reconciliation.

Prices/exit decisions must come from native adapters at legal checkpoints.
This engine deliberately has no outcome-table input or automatic exit rule.
"""
from dataclasses import asdict, dataclass
from math import floor, isfinite

from .allocator import active_strategies, base_headroom, capped_headroom, exact_confirmation, proportional_cash


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
    side: str = "BUY"
    reason: str = "NATIVE_ELIGIBLE"
    state_requirements: str = "NATIVE_ADAPTER_ACTUAL_FUNDED_STATE"
    economic_event_definition: str = ""
    board: str = "COMBINED"
    native_base_cash_limit: float | None = None

    @property
    def native_requested_notional(self):
        return self.native_requested_quantity * self.price * (1 + self.fee_rate)

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
        self.realized = {s: 0.0 for s in self.strategies}
        self.fees = 0.0
        self.checkpoints, self.fills, self.rejections, self.shortfalls = [], [], [], []
        self.seen = set()

    def exposure(self, strategy=None):
        return sum(lot["quantity"] * self.marks[lot["symbol"]] for lot in self.lots.values()
                   if strategy is None or lot["strategy"] == strategy)

    def mark(self, prices):
        if any(not isfinite(v) or v <= 0 for v in prices.values()):
            raise ValueError("invalid mark")
        self.marks.update(prices)

    def checkpoint(self, when, stage):
        virtual = {}
        for lot in self.lots.values():
            virtual[lot["symbol"]] = virtual.get(lot["symbol"], 0.0) + lot["quantity"]
        if set(virtual) != set(self.positions) or any(abs(q - self.positions[s]) > 1e-8 for s, q in virtual.items()):
            raise ValueError("physical/virtual quantity mismatch")
        gross = self.exposure()
        nav = self.cash + gross
        unrealized = sum(lot["quantity"] * self.marks[lot["symbol"]] - lot["remaining_outlay"] for lot in self.lots.values())
        pnl_nav = self.initial_cash + sum(self.realized.values()) + unrealized
        if not all(isfinite(v) for v in (self.cash, gross, nav, pnl_nav)) or nav <= 0:
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
        lot = self.lots[event_id]
        qty = lot["quantity"] if quantity is None else quantity
        if not all(isfinite(v) for v in (qty, price, fee_rate)) or qty <= 0 or qty > lot["quantity"] or price <= 0 or fee_rate < 0:
            raise ValueError("invalid native exit")
        self.mark({lot["symbol"]: price})
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
        if lot["quantity"] == 0:
            del self.lots[event_id]
        if abs(self.positions[lot["symbol"]]) < 1e-12:
            del self.positions[lot["symbol"]]
        return self.checkpoint(when, "NATIVE_EXIT")

    def credit(self, event_id, per_share, when):
        if not isfinite(per_share) or per_share < 0:
            raise ValueError("invalid corporate cash credit")
        lot = self.lots[event_id]
        amount = lot["quantity"] * per_share
        self.cash += amount
        self.sleeve_cash[lot["strategy"]] += amount
        self.realized[lot["strategy"]] += amount
        return self.checkpoint(when, "NATIVE_CASH_EVENT")

    def _fill(self, intent, budget, kind, when):
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
        self.mark({intent.symbol: intent.price})
        lot = {**asdict(intent), "quantity": qty, "funding_type": kind, "entry": when,
               "requested_notional": requested, "funded_notional": outlay, "remaining_outlay": outlay}
        self.lots[intent.event_id] = lot
        self.positions[intent.symbol] = self.positions.get(intent.symbol, 0.0) + qty
        self.fills.append({**lot, "side": "BUY", "fee": fee})
        self.checkpoint(when, kind)
        return True

    def fund(self, intents, home, policy, when, *, gate_multiplier=1.0, mcb_mode="independent"):
        if policy not in ("P0", "P1", "P2", "P3_D4", "P3_D5", "P3_D6"):
            raise ValueError("unknown frozen policy")
        if set(home) != set(self.strategies) or any(not isfinite(v) or v <= 0 for v in home.values()):
            raise ValueError("invalid independent P0 home budget")
        if mcb_mode not in ("independent", "confirmation_tag") or not 0 <= gate_multiplier <= 1:
            raise ValueError("invalid policy state")
        ordered = sorted(intents, key=lambda i: (i.decision_at, i.strategy, i.native_priority, i.event_id, i.symbol))
        ids = [i.event_id for i in ordered]
        if len(set(ids)) != len(ids) or any(i in self.seen for i in ids):
            raise ValueError("intent duplicate/replay would enlarge funded trade")
        for intent in ordered:
            if intent.strategy not in self.strategies or not intent.event_id or intent.side != "BUY":
                raise ValueError("invalid active strategy/intent")
            if intent.decision_at >= intent.earliest_execution_at or intent.earliest_execution_at > when:
                raise ValueError("future or unfinished-bar intent")
            if not all(isfinite(v) for v in (intent.price, intent.fee_rate, intent.native_requested_quantity)) or intent.price <= 0 or intent.fee_rate < 0 or intent.native_requested_quantity <= 0:
                raise ValueError("invalid native sizing")
        self.seen.update(ids)
        pending = []
        for intent in ordered:
            if mcb_mode == "confirmation_tag" and intent.strategy == "MCB" and any(exact_confirmation(a.identity(), intent.identity()) for a in ordered):
                self.rejections.append({"event_id": intent.event_id, "reason": "EXACT_CONFIRMATION_TAG"})
            else:
                pending.append(intent)
        exposure = {s: self.exposure(s) for s in self.strategies}
        remaining_base = {s: base_headroom(home[s], exposure[s]) for s in self.strategies}
        # Freeze each checkpoint's capacity once: repeated orders cannot reset the DD allowance.
        entry_capacity = self.cash * (gate_multiplier if policy.startswith("P3") else 1.0)
        unfunded = []
        for intent in pending:
            s = intent.strategy
            budget = min(remaining_base[s], self.cash, entry_capacity)
            if policy == "P0":
                budget = min(budget, self.sleeve_cash[s])
            if intent.native_base_cash_limit is not None:
                budget = min(budget, intent.native_base_cash_limit)
            if policy not in ("P0", "P1"):
                budget = min(budget, capped_headroom(s, home, {k: self.exposure(k) for k in self.strategies}))
            prior_cash = self.cash
            if self._fill(intent, budget, "BASE", when):
                used = prior_cash - self.cash
                remaining_base[s] -= used
                entry_capacity -= used
            else:
                unfunded.append(intent)
                if remaining_base[s] >= intent.native_requested_notional and self.cash < intent.native_requested_notional:
                    self.shortfalls.append({"timestamp": when, "strategy": s, "event_id": intent.event_id,
                                            "requested": intent.native_requested_notional, "cash": self.cash,
                                            "reason": "BASE_ENTITLEMENT_SHORTFALL"})
        if policy == "P0":
            for intent in unfunded:
                self.rejections.append({"event_id": intent.event_id, "reason": "SEGMENTATION_IDLE" if self.cash >= intent.native_requested_notional else "GLOBAL_DEMAND_CONFLICT"})
            return self.checkpoint(when, "FUNDING_COMPLETE")
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
                residual.append(intent)
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
            reason = "GLOBAL_DEMAND_CONFLICT"
            if self.cash >= intent.native_requested_notional:
                reason = "DRAWDOWN_GATE_BLOCK" if policy.startswith("P3") and gate_multiplier < 1 else "FAMILY_CAP_BLOCK" if policy != "P1" else "NATIVE_LOT_ALLOCATION_BLOCK"
            self.rejections.append({"event_id": intent.event_id, "reason": reason})
        return self.checkpoint(when, "FUNDING_COMPLETE")
