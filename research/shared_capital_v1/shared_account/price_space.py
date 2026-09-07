"""Explicit monetary mapping only; does not change frozen signal coordinates."""
from dataclasses import replace
from math import isfinite, isclose


def raw_intent(intent, *, raw_price, coordinate_factor):
    """Coordinate price = raw executable price * contemporaneous factor.

    Preserve requested monetary outlay, priority, clock and costs. Fractional
    native stock quantities remain fractional; no stock lot rounding is added.
    """
    if intent.price_basis != 'NATIVE_COORDINATE' or intent.lot_size != 0:
        raise ValueError('mapping requires fractional native coordinate stock intent')
    if not all(isfinite(v) and v > 0 for v in (raw_price,coordinate_factor,intent.price,intent.native_requested_quantity)):
        raise ValueError('nonfinite/nonpositive price mapping')
    if not isclose(intent.price,raw_price*coordinate_factor,rel_tol=1e-10,abs_tol=1e-12):
        raise ValueError('price/factor identity mismatch')
    result=replace(intent,price=raw_price,native_requested_quantity=intent.native_requested_quantity*coordinate_factor,price_basis='RAW')
    if not isclose(result.native_requested_notional,intent.native_requested_notional,rel_tol=1e-12,abs_tol=1e-8):
        raise ValueError('mapping changed native notional')
    return result
