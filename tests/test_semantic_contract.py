from __future__ import annotations

import math

import pytest

from cyq_game.strategy.semantic_contract import (
    SEMANTIC_EPOCH,
    SemanticContractError,
    finite_number,
    fraction,
    positive_number,
    require_active_semantic_epoch,
    semantic_fingerprint_fields,
)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, None, True])
def test_numeric_contract_rejects_nonfinite_and_non_numeric_values(value: object) -> None:
    with pytest.raises(SemanticContractError):
        finite_number(value, "value")


def test_numeric_contract_checks_finite_before_range() -> None:
    with pytest.raises(SemanticContractError, match="finite"):
        positive_number(math.nan, "price")
    with pytest.raises(SemanticContractError, match=r"\[0, 1\]"):
        fraction(1.01, "mass")


def test_old_artifact_without_semantic_epoch_is_invalid() -> None:
    with pytest.raises(SemanticContractError, match="rebuild from raw inputs"):
        require_active_semantic_epoch({}, artifact_name="legacy panel")


def test_semantic_fingerprint_is_complete_and_self_consistent() -> None:
    fields = semantic_fingerprint_fields()

    assert fields["semantic_epoch"] == SEMANTIC_EPOCH
    assert len(fields) == 12
