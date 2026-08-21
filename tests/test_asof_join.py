from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from cyq_game.data.asof_join import (
    PITDomain,
    PITDomainRecord,
    PITJoinRequest,
    join_strategy_inputs,
)
from cyq_game.data.validity import ValidityReason

SHANGHAI = ZoneInfo("Asia/Shanghai")
START = datetime(2020, 1, 1, tzinfo=SHANGHAI)
DECISION = datetime(2020, 1, 10, 15, tzinfo=SHANGHAI)
END = datetime(2020, 2, 1, tzinfo=SHANGHAI)


def _values(domain: PITDomain) -> dict[str, str | int | float | bool | None]:
    return {
        PITDomain.SECURITY_IDENTITY: {"security_type": "A_SHARE", "listed": True},
        PITDomain.SECTOR_MEMBERSHIP: {"sector_id": "SW_801010"},
        PITDomain.FLOAT_SHARES: {"float_shares": 1_000_000.0},
        PITDomain.CORPORATE_ACTION_STATUS: {"coverage_complete": True},
        PITDomain.TRADING_STATUS: {"trade_status": "TRADING", "is_st": False},
        PITDomain.MARKET_RULE: {
            "board": "MAIN",
            "lot_size": 100,
            "t_plus_one": True,
        },
    }[domain]


def _record(
    domain: PITDomain,
    *,
    available_at: datetime | None = None,
    valid_from: datetime = START,
    valid_to: datetime | None = END,
    record_id: str | None = None,
    revision_id: str = "r1",
    strict_pit_eligible: bool = True,
    available_at_observed: bool = True,
    price_coordinate: str | None = None,
    values: dict[str, str | int | float | bool | None] | None = None,
) -> PITDomainRecord:
    return PITDomainRecord(
        domain=domain,
        symbol="000001.sz",
        record_id=record_id or f"{domain.value}-202001",
        revision_id=revision_id,
        valid_from=valid_from,
        valid_to=valid_to,
        available_at=available_at or START,
        source="synthetic-fixture",
        snapshot_id=f"snapshot-{domain.value}",
        values=values or _values(domain),
        strict_pit_eligible=strict_pit_eligible,
        available_at_observed=available_at_observed,
        price_coordinate=price_coordinate,
    )


def _complete_records() -> list[PITDomainRecord]:
    return [_record(domain) for domain in PITDomain]


def test_complete_visible_domains_are_hard_valid() -> None:
    request = PITJoinRequest(
        symbol="000001.SZ",
        decision_at=DECISION,
        observability=0.25,
    )

    result = join_strategy_inputs(reversed(_complete_records()), request)

    assert result.hard_valid is True
    assert result.data_quality == 1.0
    assert result.observability == 0.25
    assert result.max_available_at == START
    assert len(result.snapshot_ids) == len(PITDomain)
    assert len(result.join_id) == 64
    assert result.as_dict()["hard_valid"] is True


def test_future_publication_is_not_visible() -> None:
    records = _complete_records()
    records[1] = _record(
        PITDomain.SECTOR_MEMBERSHIP,
        available_at=DECISION + timedelta(seconds=1),
    )

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert result.domain_flags[PITDomain.SECTOR_MEMBERSHIP] is False
    assert result.validity.reasons == (ValidityReason.MISSING_SECTOR_MEMBERSHIP,)
    assert PITDomain.SECTOR_MEMBERSHIP not in result.selected


def test_modeled_available_at_fails_closed() -> None:
    records = _complete_records()
    records[2] = _record(
        PITDomain.FLOAT_SHARES,
        available_at_observed=False,
    )

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert ValidityReason.MODELED_AVAILABLE_AT in result.validity.reasons
    assert ValidityReason.MISSING_FLOAT_SHARES in result.validity.reasons


def test_missing_version_lineage_fails_closed() -> None:
    records = _complete_records()
    records[3] = _record(
        PITDomain.CORPORATE_ACTION_STATUS,
        strict_pit_eligible=False,
    )

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert ValidityReason.MISSING_RECORD_VERSION_LINEAGE in result.validity.reasons
    assert ValidityReason.MISSING_CORPORATE_ACTION_STATUS in result.validity.reasons


def test_causal_research_mode_accepts_modeled_lineage_but_not_future_data() -> None:
    records = _complete_records()
    records[2] = _record(
        PITDomain.FLOAT_SHARES,
        available_at_observed=False,
        strict_pit_eligible=False,
    )
    request = PITJoinRequest("000001.SZ", DECISION, strict_archival=False)

    result = join_strategy_inputs(records, request)

    assert result.hard_valid is True
    assert result.as_dict()["pit_mode"] == "B_CAUSAL_RESEARCH"

    records[2] = _record(
        PITDomain.FLOAT_SHARES,
        available_at=DECISION + timedelta(seconds=1),
        available_at_observed=False,
        strict_pit_eligible=False,
    )
    result = join_strategy_inputs(records, request)
    assert result.hard_valid is False
    assert result.validity.reasons == (ValidityReason.MISSING_FLOAT_SHARES,)


def test_overlapping_logical_records_are_not_silently_tie_broken() -> None:
    records = _complete_records()
    records.append(_record(PITDomain.FLOAT_SHARES, record_id="another-float-record"))

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert result.domain_flags[PITDomain.FLOAT_SHARES] is False
    assert result.validity.reasons == (ValidityReason.CROSS_TABLE_INCONSISTENT,)


def test_latest_visible_revision_of_same_logical_record_wins() -> None:
    records = _complete_records()
    old = records[2]
    records.append(
        _record(
            PITDomain.FLOAT_SHARES,
            record_id=old.record_id,
            revision_id="r2",
            available_at=DECISION - timedelta(minutes=1),
            values={"float_shares": 2_000_000.0},
        )
    )

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is True
    assert result.selected[PITDomain.FLOAT_SHARES].revision_id == "r2"
    assert result.selected[PITDomain.FLOAT_SHARES].values["float_shares"] == 2_000_000.0


def test_price_coordinate_mismatch_blocks_the_domain() -> None:
    records = _complete_records()
    records[2] = _record(PITDomain.FLOAT_SHARES, price_coordinate="FORWARD_ADJUSTED")

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert result.domain_flags[PITDomain.FLOAT_SHARES] is False
    assert result.validity.reasons == (ValidityReason.PRICE_COORDINATE_MISMATCH,)


def test_no_action_event_is_not_a_substitute_for_action_coverage() -> None:
    records = [
        record
        for record in _complete_records()
        if record.domain is not PITDomain.CORPORATE_ACTION_STATUS
    ]

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert result.validity.reasons == (ValidityReason.MISSING_CORPORATE_ACTION_STATUS,)


def test_effective_range_is_half_open() -> None:
    boundary = DECISION
    records = [
        record
        for record in _complete_records()
        if record.domain is not PITDomain.TRADING_STATUS
    ]
    records.extend(
        (
            _record(PITDomain.TRADING_STATUS, valid_to=boundary, record_id="status-old"),
            _record(
                PITDomain.TRADING_STATUS,
                valid_from=boundary,
                valid_to=END,
                record_id="status-new",
            ),
        )
    )

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", boundary))

    assert result.hard_valid is True
    assert result.selected[PITDomain.TRADING_STATUS].record_id == "status-new"


def test_incomplete_required_value_fails_closed() -> None:
    records = _complete_records()
    records[5] = _record(PITDomain.MARKET_RULE, values={"board": "MAIN"})

    result = join_strategy_inputs(records, PITJoinRequest("000001.SZ", DECISION))

    assert result.hard_valid is False
    assert result.domain_flags[PITDomain.MARKET_RULE] is False
    assert result.validity.reasons == (ValidityReason.NULL_REQUIRED_FIELD,)


def test_join_is_bounded() -> None:
    request = PITJoinRequest("000001.SZ", DECISION)

    with pytest.raises(ValueError, match="max_records"):
        join_strategy_inputs(_complete_records(), request, max_records=5)
