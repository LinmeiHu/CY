"""Tested policy arithmetic only; no claim of an integrated strategy replay."""
from decimal import Decimal, ROUND_FLOOR


def active_strategies(gap):
    if gap not in ("OGR", "IFCGR"):
        raise ValueError("Exactly one Gap strategy required")
    return ("ATRDR", "MCB", gap, "SMV6")


def base_headroom(home_budget, actual_exposure):
    # Shared P&L deliberately cannot be supplied to this entitlement calculation.
    return max(home_budget - actual_exposure, 0)


def capped_headroom(strategy, home, exposure):
    result = max(1.5 * home[strategy] - exposure[strategy], 0)
    if strategy in ("ATRDR", "MCB"):
        result = min(result, max(sum(home[s] - exposure[s] for s in ("ATRDR", "MCB")), 0))
    return result


def proportional_cash(cash, unmet):
    """Exact decimal water allocation; native lot rounding happens after this step."""
    cash = Decimal(str(cash))
    demand = {s: Decimal(str(v)) for s, v in sorted(unmet.items())}
    if cash < 0 or any(v < 0 for v in demand.values()):
        raise ValueError("Nonnegative cash and eligible unmet amounts required")
    total = sum(demand.values(), Decimal(0))
    if not total:
        return {s: Decimal(0) for s in demand}
    return {s: v * min(cash / total, Decimal(1)) for s, v in demand.items()}


def native_lot_floor(budget, requested, unit_outlay):
    """unit_outlay includes one native lot and its once-only execution cost."""
    budget, requested, unit = map(lambda x: Decimal(str(x)), (budget, requested, unit_outlay))
    if min(budget, requested) < 0 or unit <= 0:
        raise ValueError("Invalid native-lot funding request")
    return int((min(budget, requested) / unit).to_integral_value(rounding=ROUND_FLOOR))


def exact_confirmation(atrdr, mcb):
    if atrdr.get("strategy") != "ATRDR" or atrdr.get("route") != "BULL" or mcb.get("strategy") != "MCB":
        return False
    # Even parent matches must not merge conflicting directions/securities.
    if any(not atrdr.get(k) or atrdr.get(k) != mcb.get(k) for k in ("symbol", "direction")):
        return False
    if atrdr.get("parent_event_id") and atrdr["parent_event_id"] == mcb.get("parent_event_id"):
        return True
    keys = ("symbol", "direction", "decision_timestamp", "entry_session", "economic_event_definition")
    return all(atrdr.get(k) is not None and atrdr.get(k) != "" and atrdr.get(k) == mcb.get(k) for k in keys)
