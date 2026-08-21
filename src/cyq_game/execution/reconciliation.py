"""Read-only shadow-account reconciliation and durable fail-closed control."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cyq_game.data import EventStore


@dataclass(frozen=True)
class AccountPosition:
    quantity: int
    available_quantity: int
    frozen_quantity: int = 0

    def __post_init__(self) -> None:
        if min(self.quantity, self.available_quantity, self.frozen_quantity) < 0:
            raise ValueError("account quantities must be non-negative")
        if self.available_quantity > self.quantity:
            raise ValueError("available quantity cannot exceed total quantity")
        if self.frozen_quantity > self.quantity:
            raise ValueError("frozen quantity cannot exceed total quantity")


@dataclass(frozen=True)
class AccountSnapshot:
    as_of: datetime
    source: str
    snapshot_id: str
    cash: float
    positions: dict[str, AccountPosition]

    def __post_init__(self) -> None:
        if self.as_of.tzinfo is None:
            raise ValueError("account snapshot as_of must include a timezone")
        if not self.source.strip() or not self.snapshot_id.strip():
            raise ValueError("account snapshot source and snapshot_id are required")
        if self.cash < 0:
            raise ValueError("account cash cannot be negative")

    @classmethod
    def from_file(cls, path: str | Path) -> AccountSnapshot:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("account snapshot must be a JSON object")
        raw_positions = raw.get("positions")
        if not isinstance(raw_positions, dict):
            raise ValueError("account snapshot positions must be a mapping")
        positions: dict[str, AccountPosition] = {}
        for symbol, value in raw_positions.items():
            if not isinstance(value, dict):
                raise ValueError(f"position {symbol} must be a mapping")
            positions[str(symbol)] = AccountPosition(
                quantity=_exact_int(value.get("quantity"), f"{symbol}.quantity"),
                available_quantity=_exact_int(
                    value.get("available_quantity"),
                    f"{symbol}.available_quantity",
                ),
                frozen_quantity=_exact_int(
                    value.get("frozen_quantity", 0),
                    f"{symbol}.frozen_quantity",
                ),
            )
        parsed_as_of = datetime.fromisoformat(str(raw["as_of"]))
        return cls(
            as_of=parsed_as_of,
            source=str(raw["source"]),
            snapshot_id=str(raw["snapshot_id"]),
            cash=float(raw["cash"]),
            positions=positions,
        )

    def canonical_digest(self) -> str:
        return _digest(
            {
                "as_of": self.as_of.isoformat(),
                "source": self.source,
                "snapshot_id": self.snapshot_id,
                "cash": self.cash,
                "positions": {
                    symbol: asdict(position)
                    for symbol, position in sorted(self.positions.items())
                },
            }
        )


@dataclass(frozen=True)
class IntendedAccountState:
    run_id: str
    cash: float
    positions: dict[str, int]
    available_quantities: dict[str, int]

    def __post_init__(self) -> None:
        if self.cash < 0:
            raise ValueError("intended cash cannot be negative")
        if set(self.positions) != set(self.available_quantities):
            raise ValueError("intended positions and available quantities must align")
        for symbol, quantity in self.positions.items():
            available = self.available_quantities[symbol]
            if min(quantity, available) < 0 or available > quantity:
                raise ValueError(f"invalid intended quantities for {symbol}")

    def canonical_digest(self) -> str:
        return _digest(asdict(self))


@dataclass(frozen=True)
class ReconciliationMismatch:
    field: str
    expected: float | int | str
    actual: float | int | str
    difference: float | int | None


@dataclass(frozen=True)
class ReconciliationResult:
    run_id: str
    checked_at: datetime
    snapshot_id: str
    account_snapshot_digest: str
    intended_state_digest: str
    passed: bool
    kill_switch_engaged: bool
    mismatches: tuple[ReconciliationMismatch, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "checked_at": self.checked_at.isoformat(),
            "snapshot_id": self.snapshot_id,
            "account_snapshot_digest": self.account_snapshot_digest,
            "intended_state_digest": self.intended_state_digest,
            "passed": self.passed,
            "kill_switch_engaged": self.kill_switch_engaged,
            "mismatches": [asdict(item) for item in self.mismatches],
        }


@dataclass(frozen=True)
class KillSwitchState:
    engaged: bool
    new_risk_allowed: bool
    order_transmission_enabled: bool
    engaged_at: str | None
    reason_codes: tuple[str, ...]
    last_snapshot_id: str | None
    released_at: str | None = None
    release_approval_id: str | None = None
    release_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["reason_codes"] = list(self.reason_codes)
        return value


def reconcile_account(
    intended: IntendedAccountState,
    actual: AccountSnapshot,
    *,
    checked_at: datetime,
    cash_tolerance: float,
    quantity_tolerance: int,
    max_snapshot_age_seconds: int,
) -> ReconciliationResult:
    if checked_at.tzinfo is None:
        raise ValueError("checked_at must include a timezone")
    if min(cash_tolerance, quantity_tolerance) < 0 or max_snapshot_age_seconds <= 0:
        raise ValueError("reconciliation tolerances are invalid")
    checked_at = checked_at.astimezone(UTC)
    snapshot_at = actual.as_of.astimezone(UTC)
    age_seconds = (checked_at - snapshot_at).total_seconds()
    mismatches: list[ReconciliationMismatch] = []
    if age_seconds < 0:
        mismatches.append(
            ReconciliationMismatch(
                "snapshot.as_of",
                "not after checked_at",
                actual.as_of.isoformat(),
                age_seconds,
            )
        )
    elif age_seconds > max_snapshot_age_seconds:
        mismatches.append(
            ReconciliationMismatch(
                "snapshot.age_seconds",
                max_snapshot_age_seconds,
                age_seconds,
                age_seconds - max_snapshot_age_seconds,
            )
        )
    cash_difference = actual.cash - intended.cash
    if abs(cash_difference) > cash_tolerance:
        mismatches.append(
            ReconciliationMismatch(
                "cash",
                intended.cash,
                actual.cash,
                cash_difference,
            )
        )
    symbols = sorted(set(intended.positions) | set(actual.positions))
    for symbol in symbols:
        expected_quantity = intended.positions.get(symbol, 0)
        expected_available = intended.available_quantities.get(symbol, 0)
        actual_position = actual.positions.get(symbol, AccountPosition(0, 0))
        quantity_difference = actual_position.quantity - expected_quantity
        if abs(quantity_difference) > quantity_tolerance:
            mismatches.append(
                ReconciliationMismatch(
                    f"positions.{symbol}.quantity",
                    expected_quantity,
                    actual_position.quantity,
                    quantity_difference,
                )
            )
        available_difference = actual_position.available_quantity - expected_available
        if abs(available_difference) > quantity_tolerance:
            mismatches.append(
                ReconciliationMismatch(
                    f"positions.{symbol}.available_quantity",
                    expected_available,
                    actual_position.available_quantity,
                    available_difference,
                )
            )
    return ReconciliationResult(
        run_id=intended.run_id,
        checked_at=checked_at,
        snapshot_id=actual.snapshot_id,
        account_snapshot_digest=actual.canonical_digest(),
        intended_state_digest=intended.canonical_digest(),
        passed=not mismatches,
        kill_switch_engaged=bool(mismatches),
        mismatches=tuple(mismatches),
    )


class ShadowController:
    """Persist reconciliation evidence and never auto-release an engaged switch."""

    def __init__(self, root: str | Path, run_id: str) -> None:
        self.root = Path(root) / run_id
        self.run_id = run_id
        self.events = EventStore(self.root / "events.jsonl")
        self.state_path = self.root / "kill_switch.json"

    def reconcile(
        self,
        intended: IntendedAccountState,
        actual: AccountSnapshot,
        *,
        checked_at: datetime,
        cash_tolerance: float,
        quantity_tolerance: int,
        max_snapshot_age_seconds: int,
    ) -> tuple[ReconciliationResult, KillSwitchState, Path]:
        if intended.run_id != self.run_id:
            raise ValueError("intended state run_id does not match shadow controller")
        result = reconcile_account(
            intended,
            actual,
            checked_at=checked_at,
            cash_tolerance=cash_tolerance,
            quantity_tolerance=quantity_tolerance,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
        )
        report_path = self._report_path(actual.snapshot_id)
        if report_path.exists():
            existing = json.loads(report_path.read_text(encoding="utf-8"))
            if existing != result.to_dict():
                raise ValueError("snapshot_id already has different reconciliation evidence")
            state = self.status()
            self._ensure_reconciliation_event(result, state)
            return result, state, report_path

        prior = self.status()
        state = self._engage(prior, result) if not result.passed else prior
        self.root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )
        self._ensure_reconciliation_event(result, state)
        return result, state, report_path

    def status(self) -> KillSwitchState:
        if not self.state_path.exists():
            return KillSwitchState(
                engaged=False,
                new_risk_allowed=True,
                order_transmission_enabled=False,
                engaged_at=None,
                reason_codes=(),
                last_snapshot_id=None,
            )
        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        return KillSwitchState(
            engaged=bool(raw["engaged"]),
            new_risk_allowed=bool(raw["new_risk_allowed"]),
            order_transmission_enabled=False,
            engaged_at=raw.get("engaged_at"),
            reason_codes=tuple(str(item) for item in raw.get("reason_codes", [])),
            last_snapshot_id=raw.get("last_snapshot_id"),
            released_at=raw.get("released_at"),
            release_approval_id=raw.get("release_approval_id"),
            release_reason=raw.get("release_reason"),
        )

    def release(
        self,
        *,
        approval_id: str,
        reason: str,
        released_at: datetime,
    ) -> KillSwitchState:
        if released_at.tzinfo is None:
            raise ValueError("released_at must include a timezone")
        if not approval_id.strip() or not reason.strip():
            raise ValueError("human approval_id and reason are required")
        prior = self.status()
        if not prior.engaged:
            raise ValueError("kill switch is not engaged")
        state = KillSwitchState(
            engaged=False,
            new_risk_allowed=True,
            order_transmission_enabled=False,
            engaged_at=prior.engaged_at,
            reason_codes=prior.reason_codes,
            last_snapshot_id=prior.last_snapshot_id,
            released_at=released_at.astimezone(UTC).isoformat(),
            release_approval_id=approval_id,
            release_reason=reason,
        )
        self._write_state(state)
        self.events.append(
            "KILL_SWITCH_RELEASED",
            {
                "approval_id": approval_id,
                "reason": reason,
                "previous_reason_codes": list(prior.reason_codes),
            },
            run_id=self.run_id,
            occurred_at=released_at.astimezone(UTC),
        )
        return state

    def _engage(
        self, prior: KillSwitchState, result: ReconciliationResult
    ) -> KillSwitchState:
        reason_codes = tuple(sorted({item.field for item in result.mismatches}))
        state = KillSwitchState(
            engaged=True,
            new_risk_allowed=False,
            order_transmission_enabled=False,
            engaged_at=prior.engaged_at or result.checked_at.isoformat(),
            reason_codes=tuple(sorted(set(prior.reason_codes) | set(reason_codes))),
            last_snapshot_id=result.snapshot_id,
        )
        self._write_state(state)
        return state

    def _write_state(self, state: KillSwitchState) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True, ensure_ascii=False),
            encoding="utf-8",
        )

    def _ensure_reconciliation_event(
        self,
        result: ReconciliationResult,
        state: KillSwitchState,
    ) -> None:
        event_id = f"shadow-{result.account_snapshot_digest[:24]}"
        payload = {**result.to_dict(), "effective_kill_switch": state.engaged}
        existing = {item.event_id: item for item in self.events.read_all(verify=True)}
        if event_id in existing:
            item = existing[event_id]
            expected_type = (
                "SHADOW_RECONCILIATION_PASSED"
                if result.passed
                else "SHADOW_RECONCILIATION_FAILED"
            )
            if item.event_type != expected_type or any(
                item.payload.get(key) != value
                for key, value in result.to_dict().items()
            ):
                raise ValueError("reconciliation event_id already has different evidence")
            return
        event_type = (
            "SHADOW_RECONCILIATION_PASSED"
            if result.passed
            else "SHADOW_RECONCILIATION_FAILED"
        )
        self.events.append(
            event_type,
            payload,
            run_id=self.run_id,
            occurred_at=result.checked_at,
            event_id=event_id,
        )

    def _report_path(self, snapshot_id: str) -> Path:
        safe_id = hashlib.sha256(snapshot_id.encode()).hexdigest()[:24]
        return self.root / f"reconciliation-{safe_id}.json"


def _exact_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise ValueError(f"{field} must be an integer")
    try:
        parsed_float = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be an integer") from error
    if not parsed_float.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(parsed_float)


def _digest(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()
