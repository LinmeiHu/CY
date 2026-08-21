from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from cyq_game.execution import (
    AccountPosition,
    AccountSnapshot,
    IntendedAccountState,
    ShadowController,
    reconcile_account,
)


def _intended() -> IntendedAccountState:
    return IntendedAccountState(
        run_id="run-1",
        cash=10_000.0,
        positions={"600000.SH": 1_000},
        available_quantities={"600000.SH": 800},
    )


def _snapshot(
    *,
    snapshot_id: str,
    at: datetime,
    cash: float = 10_000.0,
    quantity: int = 1_000,
    available: int = 800,
) -> AccountSnapshot:
    return AccountSnapshot(
        as_of=at,
        source="read-only-broker-export",
        snapshot_id=snapshot_id,
        cash=cash,
        positions={
            "600000.SH": AccountPosition(
                quantity=quantity,
                available_quantity=available,
            )
        },
    )


def test_reconciliation_checks_cash_total_available_and_freshness() -> None:
    checked_at = datetime(2026, 8, 18, 8, tzinfo=UTC)
    passed = reconcile_account(
        _intended(),
        _snapshot(snapshot_id="pass", at=checked_at - timedelta(seconds=30)),
        checked_at=checked_at,
        cash_tolerance=0.01,
        quantity_tolerance=0,
        max_snapshot_age_seconds=60,
    )
    assert passed.passed
    assert not passed.kill_switch_engaged

    failed = reconcile_account(
        _intended(),
        _snapshot(
            snapshot_id="fail",
            at=checked_at - timedelta(seconds=61),
            cash=10_001.0,
            quantity=900,
            available=700,
        ),
        checked_at=checked_at,
        cash_tolerance=0.01,
        quantity_tolerance=0,
        max_snapshot_age_seconds=60,
    )
    fields = {item.field for item in failed.mismatches}
    assert fields == {
        "snapshot.age_seconds",
        "cash",
        "positions.600000.SH.quantity",
        "positions.600000.SH.available_quantity",
    }
    assert failed.kill_switch_engaged


def test_shadow_kill_switch_persists_until_human_release(tmp_path: Path) -> None:
    at = datetime(2026, 8, 18, 8, tzinfo=UTC)
    controller = ShadowController(tmp_path, "run-1")
    failed_result, failed_state, report = controller.reconcile(
        _intended(),
        _snapshot(snapshot_id="bad", at=at, cash=9_000.0),
        checked_at=at,
        cash_tolerance=0.01,
        quantity_tolerance=0,
        max_snapshot_age_seconds=60,
    )
    assert not failed_result.passed
    assert failed_state.engaged
    assert not failed_state.new_risk_allowed
    assert not failed_state.order_transmission_enabled
    assert report.is_file()

    passed_result, still_engaged, _ = controller.reconcile(
        _intended(),
        _snapshot(snapshot_id="good", at=at + timedelta(seconds=1)),
        checked_at=at + timedelta(seconds=1),
        cash_tolerance=0.01,
        quantity_tolerance=0,
        max_snapshot_age_seconds=60,
    )
    assert passed_result.passed
    assert still_engaged.engaged

    # An old snapshot remains idempotently readable even after switch state changes.
    _result, current_state, same_report = controller.reconcile(
        _intended(),
        _snapshot(snapshot_id="good", at=at + timedelta(seconds=1)),
        checked_at=at + timedelta(seconds=1),
        cash_tolerance=0.01,
        quantity_tolerance=0,
        max_snapshot_age_seconds=60,
    )
    assert current_state.engaged
    assert same_report.is_file()

    released = controller.release(
        approval_id="OPS-42",
        reason="账户导出延迟已核验",
        released_at=at + timedelta(minutes=1),
    )
    assert not released.engaged
    assert released.release_approval_id == "OPS-42"
    assert not released.order_transmission_enabled

    events = controller.events.read_all(verify=True)
    assert [item.event_type for item in events] == [
        "SHADOW_RECONCILIATION_FAILED",
        "SHADOW_RECONCILIATION_PASSED",
        "KILL_SWITCH_RELEASED",
    ]
