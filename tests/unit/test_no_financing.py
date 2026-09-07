import pytest

from five_strategy_bundle.strategies.smv6 import affordable_lot_quantity


def test_fee_is_reserved_before_buy_affordability():
    assert affordable_lot_quantity(1_000.0, 10.0, 0.002, 100) == 0
    assert affordable_lot_quantity(1_002.0, 10.0, 0.002, 100) == 100


def test_affordability_rounds_down_to_board_lot():
    assert affordable_lot_quantity(1_501.0, 10.0, 0.0, 100) == 100
    assert affordable_lot_quantity(-1.0, 10.0, 0.0, 100) == 0


def test_affordability_rejects_invalid_contract_values():
    with pytest.raises(ValueError):
        affordable_lot_quantity(1_000.0, 0.0, 0.0, 100)
    with pytest.raises(ValueError):
        affordable_lot_quantity(1_000.0, 10.0, 0.0, 0)
