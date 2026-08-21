"""Minimal fail-closed entry point for strategy stock states."""

from __future__ import annotations

from dataclasses import replace

from cyq_game.chip.features import ChipFeatures
from cyq_game.data.asof_join import REQUIRED_STRATEGY_DOMAINS, PITJoinResult

from .classifier import StockClassifier, StockEvidence, StockState


def generate_strict_stock_state(
    pit_join: PITJoinResult,
    chip: ChipFeatures,
    evidence: StockEvidence,
    *,
    minimum_quality: float = 0.55,
    classifier: StockClassifier | None = None,
) -> StockState | None:
    """Return no state unless all mandatory PIT and quality gates pass."""

    complete_domains = frozenset(pit_join.request.required_domains) == frozenset(
        REQUIRED_STRATEGY_DOMAINS
    )
    effective_quality = min(
        pit_join.data_quality,
        chip.quality,
        evidence.data_quality,
    )
    if (
        not complete_domains
        or not pit_join.hard_valid
        or effective_quality < minimum_quality
    ):
        return None
    normalized = replace(evidence, data_quality=effective_quality)
    return (classifier or StockClassifier()).classify(chip, normalized)
