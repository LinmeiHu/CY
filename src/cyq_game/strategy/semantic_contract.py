"""Cross-layer semantic versions and fail-closed numeric invariants."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

SEMANTIC_EPOCH = "cyq-semantic-epoch-20260825-v2"
CHIP_STATE_SCHEMA_VERSION = "chip-state-v3-economic-identity"
OPERATOR_LOG_VERSION = "chip-operator-log-v12"
FEATURE_SCHEMA_VERSION = "chip-features-v5-canonical-peak"
PEAK_DEFINITION_VERSION = "canonical-chip-peak-v1"
PEAK_TRACK_VERSION = "temporal-chip-peak-v1"
PRICE_COORDINATE_VERSION = "causal-economic-price-v2"
PANEL_SCHEMA_VERSION = 11
STRATEGY_VERSION = "markup-retest-v2-tracked-peak"
SIGNAL_SCHEMA_VERSION = 3
LABEL_SCHEMA_VERSION = 2
EXECUTION_SEMANTICS_VERSION = "next-legal-window-v2"


class SemanticContractError(ValueError):
    """A value or artifact cannot satisfy the active semantic epoch."""


def finite_number(value: object, field: str) -> float:
    """Return a finite float; bools and implicit sentinels are rejected."""

    if isinstance(value, bool):
        raise SemanticContractError(f"{field} must be numeric, not boolean")
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as error:
        raise SemanticContractError(f"{field} must be numeric") from error
    if not math.isfinite(result):
        raise SemanticContractError(f"{field} must be finite")
    return result


def positive_number(value: object, field: str) -> float:
    result = finite_number(value, field)
    if result <= 0:
        raise SemanticContractError(f"{field} must be positive")
    return result


def non_negative_number(value: object, field: str) -> float:
    result = finite_number(value, field)
    if result < 0:
        raise SemanticContractError(f"{field} must be non-negative")
    return result


def fraction(value: object, field: str) -> float:
    result = finite_number(value, field)
    if not 0.0 <= result <= 1.0:
        raise SemanticContractError(f"{field} must be in [0, 1]")
    return result


def require_active_semantic_epoch(
    manifest: Mapping[str, Any], *, artifact_name: str
) -> None:
    """Reject every artifact not explicitly produced under this semantic epoch."""

    actual = manifest.get("semantic_epoch")
    if actual != SEMANTIC_EPOCH:
        raise SemanticContractError(
            f"{artifact_name} semantic epoch mismatch: "
            f"expected={SEMANTIC_EPOCH}, actual={actual!r}; rebuild from raw inputs"
        )


def semantic_fingerprint_fields() -> dict[str, str | int]:
    """Return fields every derived artifact manifest must fingerprint."""

    return {
        "semantic_epoch": SEMANTIC_EPOCH,
        "chip_state_schema_version": CHIP_STATE_SCHEMA_VERSION,
        "operator_log_version": OPERATOR_LOG_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "peak_definition_version": PEAK_DEFINITION_VERSION,
        "peak_track_version": PEAK_TRACK_VERSION,
        "price_coordinate_version": PRICE_COORDINATE_VERSION,
        "panel_schema_version": PANEL_SCHEMA_VERSION,
        "strategy_version": STRATEGY_VERSION,
        "signal_schema_version": SIGNAL_SCHEMA_VERSION,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "execution_semantics_version": EXECUTION_SEMANTICS_VERSION,
    }
