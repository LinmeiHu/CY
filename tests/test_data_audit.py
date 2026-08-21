from __future__ import annotations

from datetime import date, datetime
from types import MappingProxyType

import pytest

from cyq_game.data import (
    AuditStatus,
    DataActivationError,
    NormalizedQuantRecord,
    QuantAssetKind,
    QuantReadScope,
    RecordKey,
    ValidityAssessment,
    ValidityReason,
    audit_normalized_records,
)
from cyq_game.data.quant_adapter import SHANGHAI


def _record(
    symbol: str,
    hour: int,
    *,
    asset_id: str = "TEST-DAILY",
    reasons: tuple[ValidityReason, ...] = (),
) -> NormalizedQuantRecord:
    event_time = datetime(2024, 1, 2, hour, tzinfo=SHANGHAI)
    return NormalizedQuantRecord(
        asset_id=asset_id,
        kind=QuantAssetKind.DAILY_BARS,
        symbol=symbol,
        event_time=event_time,
        available_at=event_time,
        source="fixture",
        snapshot_id="fixture-v1",
        values=MappingProxyType({"close": 10.0}),
        validity=ValidityAssessment(reasons),
    )


def _scope() -> QuantReadScope:
    return QuantReadScope(
        start=date(2024, 1, 2),
        end=date(2024, 1, 2),
        symbols=("000001.SZ", "600000.SH"),
    )


def test_all_required_audits_pass_and_report_is_order_independent() -> None:
    records = (_record("000001.SZ", 15), _record("600000.SH", 15))
    expected = {RecordKey(record.symbol, record.event_time) for record in records}

    first = audit_normalized_records(
        records,
        scope=_scope(),
        expected_keys=expected,
        required_records_by_role={"trading_status": records},
    )
    second = audit_normalized_records(
        reversed(records),
        scope=_scope(),
        expected_keys=expected,
        required_records_by_role={"trading_status": reversed(records)},
    )

    assert first.all_passed
    assert first.content_sha256 == second.content_sha256
    assert first.audit_id == second.audit_id
    assert all(check.status is AuditStatus.PASS for check in first.checks.values())


def test_missing_independent_inputs_remain_not_run_and_fail_closed() -> None:
    report = audit_normalized_records(
        (_record("000001.SZ", 15),),
        scope=_scope(),
    )

    assert report.checks["coverage"].status is AuditStatus.NOT_RUN
    assert report.checks["cross_table"].status is AuditStatus.NOT_RUN
    assert not report.all_passed


def test_coverage_reports_missing_expected_key() -> None:
    record = _record("000001.SZ", 15)
    missing = RecordKey(
        "600000.SH",
        datetime(2024, 1, 2, 15, tzinfo=SHANGHAI),
    )
    report = audit_normalized_records(
        (record,),
        scope=_scope(),
        expected_keys={RecordKey(record.symbol, record.event_time), missing},
        required_records_by_role={"trading_status": (record,)},
    )

    coverage = report.checks["coverage"]
    assert coverage.status is AuditStatus.FAIL
    assert coverage.issue_count == 1
    assert "missing 600000.SH@" in coverage.evidence[0]


def test_duplicate_record_key_is_rejected() -> None:
    record = _record("000001.SZ", 15)
    report = audit_normalized_records(
        (record, record),
        scope=_scope(),
        expected_keys={RecordKey(record.symbol, record.event_time)},
        required_records_by_role={"trading_status": (record,)},
    )

    duplicates = report.checks["duplicates"]
    assert duplicates.status is AuditStatus.FAIL
    assert duplicates.issue_count == 1


def test_modeled_lineage_reason_fails_consistency() -> None:
    record = _record(
        "000001.SZ",
        15,
        reasons=(ValidityReason.MODELED_AVAILABLE_AT,),
    )
    report = audit_normalized_records(
        (record,),
        scope=_scope(),
        expected_keys={RecordKey(record.symbol, record.event_time)},
        required_records_by_role={"trading_status": (record,)},
    )

    consistency = report.checks["consistency"]
    assert consistency.status is AuditStatus.FAIL
    assert "validity=MODELED_AVAILABLE_AT" in consistency.evidence[0]


def test_cross_table_audit_fails_when_a_role_lacks_a_primary_key() -> None:
    first = _record("000001.SZ", 15)
    second = _record("600000.SH", 15)
    report = audit_normalized_records(
        (first, second),
        scope=_scope(),
        expected_keys={
            RecordKey(first.symbol, first.event_time),
            RecordKey(second.symbol, second.event_time),
        },
        required_records_by_role={"trading_status": (first,)},
    )

    cross_table = report.checks["cross_table"]
    assert cross_table.status is AuditStatus.FAIL
    assert cross_table.issue_count == 1
    assert "role=trading_status missing 600000.SH@" in cross_table.evidence[0]


def test_audit_input_is_bounded() -> None:
    records = (_record("000001.SZ", 14), _record("000001.SZ", 15))

    with pytest.raises(DataActivationError, match="exceeds safety limit 1"):
        audit_normalized_records(records, scope=_scope(), max_records=1)
