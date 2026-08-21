from __future__ import annotations

from cyq_game.data import ValidityAssessment, ValidityReason, assess_strategy_inputs


def test_strategy_input_validity_is_derived_and_reason_coded() -> None:
    result = assess_strategy_inputs(
        observed_available_at=False,
        record_version_lineage=False,
        security_identity=True,
        sector_membership=False,
        float_shares=False,
        corporate_actions=False,
        trading_status=True,
        market_rules=False,
        cross_table_consistency=True,
        raw_price_coordinate=True,
    )

    assert result.hard_valid is False
    assert set(result.reasons) == {
        ValidityReason.MODELED_AVAILABLE_AT,
        ValidityReason.MISSING_RECORD_VERSION_LINEAGE,
        ValidityReason.MISSING_SECTOR_MEMBERSHIP,
        ValidityReason.MISSING_FLOAT_SHARES,
        ValidityReason.MISSING_CORPORATE_ACTION_STATUS,
        ValidityReason.MISSING_MARKET_RULE,
    }


def test_validity_merge_is_deduplicated_and_cannot_override_failures() -> None:
    first = ValidityAssessment.from_reasons(ValidityReason.MISSING_FLOAT_SHARES)
    second = ValidityAssessment.from_reasons(
        ValidityReason.MISSING_FLOAT_SHARES,
        ValidityReason.MISSING_MARKET_RULE,
    )

    merged = first.merge(second)

    assert merged.reasons == (
        ValidityReason.MISSING_FLOAT_SHARES,
        ValidityReason.MISSING_MARKET_RULE,
    )
    assert merged.hard_valid is False
    assert ValidityAssessment().hard_valid is True
