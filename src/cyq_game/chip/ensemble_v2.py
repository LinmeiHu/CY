"""Cross-model anchor lineage estimates for the PIT chip inventory.

The seller source is latent.  A strategy therefore consumes an interval from
the three registered seller models, never a price-band overlap proxy.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from statistics import median

from cyq_game.chip.state_v2 import (
    AnchorTraceCache,
    AnchorTraceCacheKey,
    ChipStateContractError,
    OriginSurvivalTransition,
    OriginTracer,
    SellerModel,
)

SELLER_MODEL_ORDER = (
    SellerModel.UNIFORM,
    SellerModel.DISPOSITION,
    SellerModel.ACTIVE_STICKY,
)


@dataclass(frozen=True)
class AnchorRetentionEstimate:
    """Causal anchor survival estimate and seller-model uncertainty interval."""

    anchor_id: str
    symbol: str
    anchor_date: date
    current_date: date
    model_retentions: tuple[tuple[SellerModel, float], ...]
    central: float
    lower: float
    upper: float
    disagreement: float
    confidence: float
    ensemble_version: str

    def __post_init__(self) -> None:
        if not self.anchor_id or not self.symbol or not self.ensemble_version:
            raise ChipStateContractError("anchor retention identity cannot be empty")
        if self.current_date < self.anchor_date:
            raise ChipStateContractError("retention date predates anchor date")
        if tuple(model for model, _ in self.model_retentions) != SELLER_MODEL_ORDER:
            raise ChipStateContractError("retention requires all three seller models in order")
        values = tuple(value for _, value in self.model_retentions)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ChipStateContractError("model retention must be finite and in [0, 1]")
        expected_lower = min(values)
        expected_upper = max(values)
        expected_central = median(values)
        expected_disagreement = expected_upper - expected_lower
        expected_confidence = max(0.0, 1.0 - expected_disagreement)
        expected = (
            (self.lower, expected_lower, "lower"),
            (self.upper, expected_upper, "upper"),
            (self.central, expected_central, "central"),
            (self.disagreement, expected_disagreement, "disagreement"),
            (self.confidence, expected_confidence, "confidence"),
        )
        for actual, wanted, name in expected:
            if not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-12):
                raise ChipStateContractError(f"incorrect retention {name}")

    @classmethod
    def from_tracers(
        cls,
        tracers: Mapping[SellerModel, OriginTracer],
        *,
        current_date: date,
        ensemble_version: str,
    ) -> AnchorRetentionEstimate:
        if set(tracers) != set(SELLER_MODEL_ORDER):
            raise ChipStateContractError("exactly three seller-model tracers are required")
        ordered = tuple(tracers[model] for model in SELLER_MODEL_ORDER)
        identity = {
            (tracer.anchor_id, tracer.symbol, tracer.anchor_date) for tracer in ordered
        }
        if len(identity) != 1:
            raise ChipStateContractError("seller-model tracers do not share one anchor")
        anchor_id, symbol, anchor_date = next(iter(identity))
        values = tuple(tracer.retention for tracer in ordered)
        return cls.from_model_retentions(
            anchor_id=anchor_id,
            symbol=symbol,
            anchor_date=anchor_date,
            current_date=current_date,
            model_retentions=dict(zip(SELLER_MODEL_ORDER, values, strict=True)),
            ensemble_version=ensemble_version,
        )

    @classmethod
    def from_model_retentions(
        cls,
        *,
        anchor_id: str,
        symbol: str,
        anchor_date: date,
        current_date: date,
        model_retentions: Mapping[SellerModel | str, float],
        ensemble_version: str,
    ) -> AnchorRetentionEstimate:
        """Rehydrate an estimate from persisted per-model lineage values."""

        normalized: dict[SellerModel, float] = {}
        for raw_model, raw_value in model_retentions.items():
            model = raw_model if isinstance(raw_model, SellerModel) else SellerModel(str(raw_model))
            value = float(raw_value)
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ChipStateContractError(
                    f"invalid {model.value} anchor retention: {raw_value!r}"
                )
            normalized[model] = value
        if set(normalized) != set(SELLER_MODEL_ORDER):
            raise ChipStateContractError("exactly three seller-model retentions are required")
        values = tuple(normalized[model] for model in SELLER_MODEL_ORDER)
        lower = min(values)
        upper = max(values)
        disagreement = upper - lower
        return cls(
            anchor_id=anchor_id,
            symbol=symbol,
            anchor_date=anchor_date,
            current_date=current_date,
            model_retentions=tuple(zip(SELLER_MODEL_ORDER, values, strict=True)),
            central=median(values),
            lower=lower,
            upper=upper,
            disagreement=disagreement,
            confidence=max(0.0, 1.0 - disagreement),
            ensemble_version=ensemble_version,
        )


def trace_to_date(
    tracer: OriginTracer,
    transitions: Iterable[OriginSurvivalTransition],
    *,
    current_date: date,
    cache: AnchorTraceCache,
) -> OriginTracer:
    """Advance one immutable anchor trace, reusing only the exact legal key."""

    key = AnchorTraceCacheKey(
        symbol=tracer.symbol,
        anchor_date=tracer.anchor_date,
        current_date=current_date,
        model_version=tracer.model_version,
    )
    cached = cache.get(key)
    if cached is not None:
        return cached
    current = tracer
    for transition in sorted(transitions, key=lambda item: item.trading_date):
        if transition.trading_date <= tracer.anchor_date:
            continue
        if transition.trading_date > current_date:
            break
        current = current.advance(transition)
    cache.put(key, current)
    return current
