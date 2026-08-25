from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Any, cast
from uuid import uuid4

from cyq_game.data.events import EventStore
from cyq_game.domain import Action, PlanStatus, StrategyFamily


@dataclass(frozen=True)
class TradingPlan:
    plan_id: str
    version: int
    symbol: str
    family: StrategyFamily
    proposed_action: Action
    created_at: datetime
    valid_from: datetime
    expires_at: datetime
    entry_trigger: str
    invalidation: str
    protective_stop: float
    target_fraction: float
    max_participation: float
    edge_card_digest: str
    status: PlanStatus = PlanStatus.DRAFT
    parent_version: int | None = None

    def __post_init__(self) -> None:
        if self.version < 1 or self.expires_at <= self.valid_from:
            raise ValueError("invalid plan version or validity interval")
        if self.protective_stop <= 0 or not 0.0 <= self.target_fraction <= 1.0:
            raise ValueError("invalid stop or target fraction")
        if not 0.0 < self.max_participation <= 1.0:
            raise ValueError("invalid participation limit")
        if not self.invalidation.strip() or not self.entry_trigger.strip():
            raise ValueError("entry trigger and invalidation are mandatory")

    @classmethod
    def create(
        cls,
        *,
        symbol: str,
        family: StrategyFamily,
        action: Action,
        now: datetime,
        expires_at: datetime,
        entry_trigger: str,
        invalidation: str,
        protective_stop: float,
        target_fraction: float,
        max_participation: float,
        edge_card_digest: str,
        plan_id: str | None = None,
    ) -> TradingPlan:
        return cls(
            plan_id=plan_id or str(uuid4()),
            version=1,
            symbol=symbol,
            family=family,
            proposed_action=action,
            created_at=now,
            valid_from=now,
            expires_at=expires_at,
            entry_trigger=entry_trigger,
            invalidation=invalidation,
            protective_stop=protective_stop,
            target_fraction=target_fraction,
            max_participation=max_participation,
            edge_card_digest=edge_card_digest,
        )

    def revised(self, now: datetime, **changes: object) -> TradingPlan:
        immutable = {
            "plan_id",
            "version",
            "created_at",
            "symbol",
            "family",
            "proposed_action",
            "edge_card_digest",
        }
        changed_identity = immutable.intersection(changes)
        if changed_identity:
            raise ValueError(
                "identity or thesis fields cannot be revised; create a new plan: "
                + ",".join(sorted(changed_identity))
            )
        safe_changes = cast(Any, changes)
        return replace(
            self,
            **safe_changes,
            version=self.version + 1,
            parent_version=self.version,
            created_at=now,
            valid_from=now,
            status=PlanStatus.DRAFT,
        )


class PlanRepository:
    """Append-only plan lifecycle backed by the governance event chain."""

    def __init__(self, events: EventStore, run_id: str) -> None:
        self.events = events
        self.run_id = run_id
        self._plans: dict[str, list[TradingPlan]] = {}

    def append(self, plan: TradingPlan, event_time: datetime) -> None:
        versions = self._plans.setdefault(plan.plan_id, [])
        expected = len(versions) + 1
        if plan.version != expected:
            raise ValueError(f"plan version must be {expected}")
        if versions and plan.parent_version != versions[-1].version:
            raise ValueError("plan parent version mismatch")
        payload = asdict(plan)
        payload["family"] = plan.family.value
        payload["proposed_action"] = plan.proposed_action.value
        payload["status"] = plan.status.value
        for name in ("created_at", "valid_from", "expires_at"):
            payload[name] = getattr(plan, name).isoformat()
        self.events.append(
            event_type="TRADING_PLAN_APPENDED",
            payload=payload,
            run_id=self.run_id,
            occurred_at=event_time,
        )
        versions.append(plan)

    def latest(self, plan_id: str) -> TradingPlan:
        return self._plans[plan_id][-1]

    def rebase_active_for_split(
        self, symbol: str, ratio: float, event_time: datetime
    ) -> list[TradingPlan]:
        """Version active plans into the post-split price coordinate system."""

        if ratio <= 0:
            raise ValueError("split ratio must be positive")
        rebased: list[TradingPlan] = []
        for versions in list(self._plans.values()):
            latest = versions[-1]
            if latest.symbol != symbol or latest.status != PlanStatus.ACTIVE:
                continue
            if not latest.valid_from <= event_time <= latest.expires_at:
                continue
            adjusted = replace(
                latest,
                version=latest.version + 1,
                parent_version=latest.version,
                created_at=event_time,
                valid_from=event_time,
                protective_stop=latest.protective_stop / ratio,
            )
            self.append(adjusted, event_time)
            rebased.append(adjusted)
        return rebased

    def rebase_active_for_cash_dividend(
        self, symbol: str, cash_per_share: float, event_time: datetime
    ) -> list[TradingPlan]:
        """Version active plan stops into the ex-cash price coordinate."""

        if cash_per_share < 0:
            raise ValueError("cash dividend cannot be negative")
        if cash_per_share == 0:
            return []
        rebased: list[TradingPlan] = []
        for versions in list(self._plans.values()):
            latest = versions[-1]
            if latest.symbol != symbol or latest.status != PlanStatus.ACTIVE:
                continue
            if not latest.valid_from <= event_time <= latest.expires_at:
                continue
            protective_stop = latest.protective_stop - cash_per_share
            if protective_stop <= 0:
                raise ValueError("cash dividend creates a non-positive protective stop")
            adjusted = replace(
                latest,
                version=latest.version + 1,
                parent_version=latest.version,
                created_at=event_time,
                valid_from=event_time,
                protective_stop=protective_stop,
            )
            self.append(adjusted, event_time)
            rebased.append(adjusted)
        return rebased
