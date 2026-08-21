from __future__ import annotations

import pytest

from cyq_game.chip.ledgers import TripleLedger


def test_transaction_economic_and_latent_supply_ledgers_are_separate() -> None:
    base = TripleLedger(100.0, 1_000.0, 1_000.0)
    dividend = base.cash_dividend(1.0)
    assert dividend.transaction_cost_total == 1_000.0
    assert dividend.economic_cost_total == 900.0
    rights = dividend.rights_issue(20.0, 8.0)
    assert rights.shares == 120.0
    assert rights.transaction_cost_total == 1_160.0
    locked = rights.register_locked_supply(30.0)
    unlocked = locked.unlock(10.0)
    assert unlocked.latent_supply_shares == 20.0
    assert unlocked.shares == 120.0
    assert base.split(2.0).transaction_cost_per_share == pytest.approx(5.0)
