from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class CorporateActionType(StrEnum):
    SPLIT = "SPLIT"
    CASH_DIVIDEND = "CASH_DIVIDEND"
    RIGHTS_ISSUE = "RIGHTS_ISSUE"
    UNLOCK = "UNLOCK"
    REPURCHASE_CANCEL = "REPURCHASE_CANCEL"


@dataclass(frozen=True)
class TripleLedger:
    """Transaction cost, economic break-even, and latent-supply ledgers."""

    shares: float
    transaction_cost_total: float
    economic_cost_total: float
    latent_supply_shares: float = 0.0
    cash_distributions: float = 0.0

    def __post_init__(self) -> None:
        if self.shares <= 0 or min(
            self.transaction_cost_total,
            self.economic_cost_total,
            self.latent_supply_shares,
            self.cash_distributions,
        ) < 0:
            raise ValueError("ledger values must be non-negative and shares positive")

    @property
    def transaction_cost_per_share(self) -> float:
        return self.transaction_cost_total / self.shares

    @property
    def economic_break_even_per_share(self) -> float:
        return self.economic_cost_total / self.shares

    def split(self, ratio: float) -> TripleLedger:
        if ratio <= 0:
            raise ValueError("split ratio must be positive")
        return replace(self, shares=self.shares * ratio)

    def cash_dividend(self, cash_per_share: float) -> TripleLedger:
        if cash_per_share < 0:
            raise ValueError("cash dividend cannot be negative")
        cash = cash_per_share * self.shares
        return replace(
            self,
            economic_cost_total=max(0.0, self.economic_cost_total - cash),
            cash_distributions=self.cash_distributions + cash,
        )

    def rights_issue(self, new_shares: float, issue_price: float) -> TripleLedger:
        if new_shares < 0 or issue_price < 0:
            raise ValueError("invalid rights issue")
        issue_cost = new_shares * issue_price
        return replace(
            self,
            shares=self.shares + new_shares,
            transaction_cost_total=self.transaction_cost_total + issue_cost,
            economic_cost_total=self.economic_cost_total + issue_cost,
        )

    def register_locked_supply(self, shares: float) -> TripleLedger:
        if shares < 0:
            raise ValueError("latent supply cannot be negative")
        return replace(self, latent_supply_shares=self.latent_supply_shares + shares)

    def unlock(self, shares: float) -> TripleLedger:
        if shares < 0 or shares > self.latent_supply_shares:
            raise ValueError("unlock exceeds latent supply")
        # Unlock is a risk transition, never an automatic injection into CYQ.
        return replace(self, latent_supply_shares=self.latent_supply_shares - shares)

