"""Immutable contracts for causal chip inventory and anchor lineage.

The inventory in this module is strategy independent.  Strategy anchors only
reference immutable POST snapshots and replay daily survival operators; newly
traded chips are therefore unable to masquerade as chips from an old anchor.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from enum import StrEnum
from functools import lru_cache
from itertools import pairwise

FLOAT_ABS_TOLERANCE = 1e-6
FLOAT_REL_TOLERANCE = 1e-12


class SnapshotPhase(StrEnum):
    PRE = "PRE"
    POST = "POST"


class AnchorRole(StrEnum):
    ROOT = "ROOT"
    SUPPORT = "SUPPORT"


class TurnoverSensitivity(StrEnum):
    ACTIVE = "ACTIVE"
    NEUTRAL = "NEUTRAL"
    STICKY = "STICKY"


class SellerModel(StrEnum):
    UNIFORM = "UNIFORM"
    DISPOSITION = "DISPOSITION"
    ACTIVE_STICKY = "ACTIVE_STICKY"


class ChipStateContractError(ValueError):
    """A PIT, conservation, lineage, or replay contract was violated."""


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ChipStateContractError(f"{field_name} must be timezone-aware")


def tolerance(reference: float) -> float:
    return max(FLOAT_ABS_TOLERANCE, FLOAT_REL_TOLERANCE * max(1.0, abs(reference)))


def stable_id(prefix: str, payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()}"


@lru_cache(maxsize=131_072)
def stable_cell_id(
    *,
    cost_bucket_id: int | None,
    holding_days: int,
    sensitivity: TurnoverSensitivity,
    economic_break_even: float | None = None,
) -> int:
    """Return the identifier for one causal cost x age x sensitivity state.

    Economic break-even is a causal state coordinate: corporate actions can
    make otherwise identical acquisition lots economically distinct.  It must
    therefore participate in identity; merging it would corrupt both the
    price distribution and the origin-survival operator.
    """

    if not isinstance(holding_days, int) or holding_days < -1:
        raise ChipStateContractError("cell holding_days is outside its valid range")
    if cost_bucket_id is not None and not isinstance(cost_bucket_id, int):
        raise ChipStateContractError("cost bucket id must be an integer or null")
    if economic_break_even is not None and not math.isfinite(economic_break_even):
        raise ChipStateContractError("economic break-even identity must be finite")
    payload: dict[str, object] = {
        "cost_bucket_id": cost_bucket_id,
        "holding_days": holding_days,
        "sensitivity": sensitivity.value,
        "economic_break_even": (
            None if economic_break_even is None else float(economic_break_even).hex()
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


@dataclass(frozen=True)
class InventoryCell:
    """One sparse ``cost x exact holding days x sensitivity`` inventory cell."""

    cell_id: int
    cost_bucket_id: int | None
    holding_days: int
    sensitivity: TurnoverSensitivity
    acquisition_cost: float | None
    economic_break_even: float | None
    shares: float
    initialization_prior_units: float = 0.0

    def __post_init__(self) -> None:
        if self.cell_id < 0:
            raise ChipStateContractError("cell_id must be non-negative")
        if self.holding_days < -1:
            raise ChipStateContractError("holding_days must be -1 (unknown) or non-negative")
        known_cost = self.cost_bucket_id is not None
        if known_cost != (self.acquisition_cost is not None):
            raise ChipStateContractError("known cost bucket and acquisition cost must agree")
        if known_cost != (self.economic_break_even is not None):
            raise ChipStateContractError("known cost bucket and economic cost must agree")
        if self.acquisition_cost is not None and (
            not math.isfinite(self.acquisition_cost) or self.acquisition_cost <= 0
        ):
            raise ChipStateContractError("acquisition cost must be finite and positive")
        if self.economic_break_even is not None and not math.isfinite(
            self.economic_break_even
        ):
            raise ChipStateContractError("economic break-even must be finite")
        if not math.isfinite(self.shares) or self.shares < 0:
            raise ChipStateContractError("shares must be finite and non-negative")
        if (
            not math.isfinite(self.initialization_prior_units)
            or self.initialization_prior_units < 0
        ):
            raise ChipStateContractError(
                "initialization_prior_units must be finite and non-negative"
            )
        expected = stable_cell_id(
            cost_bucket_id=self.cost_bucket_id,
            holding_days=self.holding_days,
            sensitivity=self.sensitivity,
            economic_break_even=self.economic_break_even,
        )
        if self.cell_id != expected:
            raise ChipStateContractError("cell_id does not match its immutable dimensions")

    @classmethod
    def create(
        cls,
        *,
        cost_bucket_id: int | None,
        holding_days: int,
        sensitivity: TurnoverSensitivity,
        acquisition_cost: float | None,
        economic_break_even: float | None,
        shares: float,
        initialization_prior_units: float = 0.0,
    ) -> InventoryCell:
        return cls(
            cell_id=stable_cell_id(
                cost_bucket_id=cost_bucket_id,
                holding_days=holding_days,
                sensitivity=sensitivity,
                economic_break_even=economic_break_even,
            ),
            cost_bucket_id=cost_bucket_id,
            holding_days=holding_days,
            sensitivity=sensitivity,
            acquisition_cost=acquisition_cost,
            economic_break_even=economic_break_even,
            shares=shares,
            initialization_prior_units=initialization_prior_units,
        )

    @property
    def cost_known(self) -> bool:
        return self.cost_bucket_id is not None


@dataclass(frozen=True)
class SparseChipInventory:
    """Canonical sparse inventory measured in absolute free-float shares."""

    cells: tuple[InventoryCell, ...]
    _total_shares: float = field(init=False, repr=False, compare=False)
    _known_cost_shares: float = field(init=False, repr=False, compare=False)
    _unknown_cost_shares: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.cells:
            raise ChipStateContractError("inventory cannot be empty")
        ids = tuple(cell.cell_id for cell in self.cells)
        if ids != tuple(sorted(ids)) or len(set(ids)) != len(ids):
            raise ChipStateContractError("inventory cells must be unique and sorted by cell_id")
        total = math.fsum(cell.shares for cell in self.cells)
        known = math.fsum(cell.shares for cell in self.cells if cell.cost_known)
        unknown = math.fsum(cell.shares for cell in self.cells if not cell.cost_known)
        object.__setattr__(self, "_total_shares", total)
        object.__setattr__(self, "_known_cost_shares", known)
        object.__setattr__(self, "_unknown_cost_shares", unknown)

    @classmethod
    def canonical(cls, cells: tuple[InventoryCell, ...]) -> SparseChipInventory:
        """Aggregate identical dimensions without normalizing any mass."""

        ordered = tuple(
            sorted(
                (cell for cell in cells if cell.shares > 0),
                key=lambda cell: cell.cell_id,
            )
        )
        if not ordered:
            raise ChipStateContractError("inventory cannot be empty after aggregation")
        if all(left.cell_id != right.cell_id for left, right in pairwise(ordered)):
            return cls(ordered)

        grouped: dict[int, list[InventoryCell]] = defaultdict(list)
        for cell in ordered:
            grouped[cell.cell_id].append(cell)
        combined: list[InventoryCell] = []
        for cell_id, parts in sorted(grouped.items()):
            first = parts[0]
            if any(
                (part.cost_bucket_id, part.holding_days, part.sensitivity)
                != (first.cost_bucket_id, first.holding_days, first.sensitivity)
                for part in parts[1:]
            ):
                raise ChipStateContractError(f"cell hash collision for {cell_id}")
            if len(parts) == 1:
                combined.append(first)
                continue
            shares = math.fsum(part.shares for part in parts)
            prior_units = math.fsum(part.initialization_prior_units for part in parts)
            if shares > 0:
                if first.cost_known:
                    acquisition_values: list[float] = []
                    break_even_values: list[float] = []
                    for part in parts:
                        if (
                            part.acquisition_cost is None
                            or part.economic_break_even is None
                        ):
                            raise ChipStateContractError(
                                "known-cost cell contains a missing price"
                            )
                        acquisition_values.append(part.shares * part.acquisition_cost)
                        break_even_values.append(
                            part.shares * part.economic_break_even
                        )
                    acquisition_cost = math.fsum(acquisition_values) / shares
                    economic_break_even = math.fsum(break_even_values) / shares
                else:
                    acquisition_cost = None
                    economic_break_even = None
                combined.append(
                    replace(
                        first,
                        acquisition_cost=acquisition_cost,
                        economic_break_even=economic_break_even,
                        shares=shares,
                        initialization_prior_units=prior_units,
                    )
                )
        if not combined:
            raise ChipStateContractError("inventory cannot be empty after aggregation")
        return cls(tuple(combined))

    @property
    def total_shares(self) -> float:
        return self._total_shares

    @property
    def known_cost_shares(self) -> float:
        return self._known_cost_shares

    @property
    def unknown_cost_shares(self) -> float:
        return self._unknown_cost_shares

    @property
    def initialization_prior_units(self) -> float:
        return math.fsum(cell.initialization_prior_units for cell in self.cells)

    def by_id(self) -> dict[int, InventoryCell]:
        return {cell.cell_id: cell for cell in self.cells}


@dataclass(frozen=True)
class ChipSnapshotV2:
    """Immutable PRE/POST state with PIT lineage and exact supply bridge."""

    symbol: str
    trading_date: date
    decision_at: datetime
    effective_at: datetime
    available_at: datetime
    phase: SnapshotPhase
    snapshot_id: str
    model_version: str
    grid_version: str
    seller_model: SellerModel
    inventory: SparseChipInventory
    free_float_shares: float
    latent_supply_shares: float
    input_snapshot_ids: tuple[str, ...]
    pit_grade: str
    hard_valid: bool
    quality_reason_codes: tuple[str, ...] = ()
    _conservation_error: float = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        for timestamp, name in (
            (self.decision_at, "decision_at"),
            (self.effective_at, "effective_at"),
            (self.available_at, "available_at"),
        ):
            require_aware(timestamp, name)
        if self.trading_date != self.decision_at.date():
            raise ChipStateContractError("trading_date must match decision_at date")
        if self.effective_at > self.decision_at:
            raise ChipStateContractError("effective_at cannot be after decision_at")
        if self.available_at > self.decision_at:
            raise ChipStateContractError("available_at cannot be after decision_at")
        if not math.isfinite(self.free_float_shares) or self.free_float_shares <= 0:
            raise ChipStateContractError("free_float_shares must be finite and positive")
        if not math.isfinite(self.latent_supply_shares) or self.latent_supply_shares < 0:
            raise ChipStateContractError("latent_supply_shares must be finite and non-negative")
        if not all((self.symbol, self.snapshot_id, self.model_version, self.grid_version)):
            raise ChipStateContractError("snapshot identity/version fields cannot be empty")
        if not self.input_snapshot_ids or tuple(sorted(set(self.input_snapshot_ids))) != (
            self.input_snapshot_ids
        ):
            raise ChipStateContractError("input_snapshot_ids must be non-empty, unique, sorted")
        if tuple(sorted(set(self.quality_reason_codes))) != self.quality_reason_codes:
            raise ChipStateContractError("quality_reason_codes must be unique and sorted")
        error = self.inventory.total_shares - self.free_float_shares
        object.__setattr__(self, "_conservation_error", error)
        if abs(error) > tolerance(self.free_float_shares):
            raise ChipStateContractError(
                "free-float conservation failed without normalization: "
                f"inventory({self.inventory.total_shares:.17g}) - "
                f"float({self.free_float_shares:.17g}) = {error:.17g}"
            )
        if self.inventory.initialization_prior_units > 1 + tolerance(1.0):
            raise ChipStateContractError("initialization prior units cannot exceed one")
        if self.hard_valid and self.inventory.unknown_cost_shares > tolerance(
            self.free_float_shares
        ):
            raise ChipStateContractError(
                "strict snapshot cannot contain material UNKNOWN_COST inventory"
            )

    @property
    def conservation_error(self) -> float:
        return self._conservation_error


@dataclass(frozen=True)
class OriginSurvivalTransition:
    """Sparse daily old-chip survival operator; same-day purchases are excluded."""

    transition_id: str
    symbol: str
    trading_date: date
    decision_at: datetime
    effective_at: datetime
    available_at: datetime
    source_snapshot_id: str
    pre_snapshot_id: str
    destination_snapshot_id: str
    model_version: str
    grid_version: str
    source_cell_ids: tuple[int, ...]
    destination_cell_ids: tuple[int, ...]
    retained_fractions: tuple[float, ...]
    fixed_pre_eligible_shares: float
    executed_sell_shares: float
    same_day_resale_shares: float
    input_snapshot_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, name in (
            (self.decision_at, "decision_at"),
            (self.effective_at, "effective_at"),
            (self.available_at, "available_at"),
        ):
            require_aware(value, name)
        if self.trading_date != self.decision_at.date():
            raise ChipStateContractError("transition trading_date must match decision_at")
        if self.effective_at > self.decision_at:
            raise ChipStateContractError("transition effective_at cannot follow decision_at")
        if self.available_at > self.decision_at:
            raise ChipStateContractError("transition available_at cannot follow decision_at")
        length = len(self.source_cell_ids)
        if length == 0 or not (
            length == len(self.destination_cell_ids) == len(self.retained_fractions)
        ):
            raise ChipStateContractError("survival arcs must be non-empty and aligned")
        if not all(
            (
                self.transition_id,
                self.symbol,
                self.source_snapshot_id,
                self.pre_snapshot_id,
                self.destination_snapshot_id,
                self.model_version,
                self.grid_version,
            )
        ):
            raise ChipStateContractError("transition identity/version fields cannot be empty")
        arcs = tuple(zip(self.source_cell_ids, self.destination_cell_ids, strict=True))
        if arcs != tuple(sorted(arcs)) or len(set(arcs)) != length:
            raise ChipStateContractError("survival arcs must be unique and sorted")
        if any(
            not math.isfinite(fraction) or not 0 <= fraction <= 1
            for fraction in self.retained_fractions
        ):
            raise ChipStateContractError("retained fractions must be in [0, 1]")
        totals: dict[int, list[float]] = defaultdict(list)
        for source, fraction in zip(
            self.source_cell_ids, self.retained_fractions, strict=True
        ):
            totals[source].append(fraction)
        for source, fractions in totals.items():
            retained = math.fsum(fractions)
            if retained > 1 + tolerance(1.0):
                raise ChipStateContractError(
                    f"source cell {source} retained fraction exceeds one: {retained}"
                )
        for amount, name in (
            (self.fixed_pre_eligible_shares, "fixed_pre_eligible_shares"),
            (self.executed_sell_shares, "executed_sell_shares"),
            (self.same_day_resale_shares, "same_day_resale_shares"),
        ):
            if not math.isfinite(amount) or amount < 0:
                raise ChipStateContractError(f"{name} must be finite and non-negative")
        if self.executed_sell_shares > self.fixed_pre_eligible_shares + tolerance(
            self.fixed_pre_eligible_shares
        ):
            raise ChipStateContractError("executed sales exceed the fixed PRE eligible pool")
        if self.same_day_resale_shares > tolerance(self.fixed_pre_eligible_shares):
            raise ChipStateContractError("T+1 violated: same-day purchases were sold")
        if not self.input_snapshot_ids or tuple(sorted(set(self.input_snapshot_ids))) != (
            self.input_snapshot_ids
        ):
            raise ChipStateContractError("transition input lineage must be non-empty and sorted")


@dataclass(frozen=True)
class OriginTracer:
    """Dimensionless units belonging to one causally frozen strategy anchor."""

    anchor_id: str
    anchor_date: date
    symbol: str
    root_snapshot_id: str
    current_snapshot_id: str
    model_version: str
    grid_version: str
    root_origin_units: float
    cell_ids: tuple[int, ...]
    origin_units: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.cell_ids or len(self.cell_ids) != len(self.origin_units):
            raise ChipStateContractError("origin tracer cells must be non-empty and aligned")
        if self.cell_ids != tuple(sorted(self.cell_ids)) or len(set(self.cell_ids)) != len(
            self.cell_ids
        ):
            raise ChipStateContractError("origin tracer cells must be unique and sorted")
        if not math.isfinite(self.root_origin_units) or self.root_origin_units <= 0:
            raise ChipStateContractError("root origin units must be finite and positive")
        if any(not math.isfinite(unit) or unit < 0 for unit in self.origin_units):
            raise ChipStateContractError("origin units must be finite and non-negative")
        if self.current_origin_units > self.root_origin_units + tolerance(
            self.root_origin_units
        ):
            raise ChipStateContractError("anchor origin units cannot increase")

    @classmethod
    def from_snapshot(
        cls,
        *,
        anchor_id: str,
        snapshot: ChipSnapshotV2,
        selected_cell_ids: tuple[int, ...] | None = None,
        include_unknown_cost: bool = False,
    ) -> OriginTracer:
        if snapshot.phase != SnapshotPhase.POST:
            raise ChipStateContractError("strategy anchors must reference a POST snapshot")
        inventory = snapshot.inventory.by_id()
        if selected_cell_ids is None:
            selected = tuple(
                cell.cell_id
                for cell in snapshot.inventory.cells
                if include_unknown_cost or cell.cost_known
            )
        else:
            selected = selected_cell_ids
        if not selected or selected != tuple(sorted(set(selected))):
            raise ChipStateContractError("selected anchor cells must be non-empty and sorted")
        missing = tuple(cell_id for cell_id in selected if cell_id not in inventory)
        if missing:
            raise ChipStateContractError(f"anchor cells absent from snapshot: {missing}")
        if not include_unknown_cost and any(
            not inventory[cell_id].cost_known for cell_id in selected
        ):
            raise ChipStateContractError("UNKNOWN_COST cannot be used as structural anchor mass")
        units = tuple(
            inventory[cell_id].shares / snapshot.free_float_shares for cell_id in selected
        )
        root_units = math.fsum(units)
        if root_units <= 0:
            raise ChipStateContractError("selected anchor cells contain no inventory")
        return cls(
            anchor_id=anchor_id,
            anchor_date=snapshot.trading_date,
            symbol=snapshot.symbol,
            root_snapshot_id=snapshot.snapshot_id,
            current_snapshot_id=snapshot.snapshot_id,
            model_version=snapshot.model_version,
            grid_version=snapshot.grid_version,
            root_origin_units=root_units,
            cell_ids=selected,
            origin_units=units,
        )

    @property
    def current_origin_units(self) -> float:
        return math.fsum(self.origin_units)

    @property
    def retention(self) -> float:
        return self.current_origin_units / self.root_origin_units

    def advance(self, transition: OriginSurvivalTransition) -> OriginTracer:
        if transition.symbol != self.symbol:
            raise ChipStateContractError("transition symbol does not match tracer")
        if transition.source_snapshot_id != self.current_snapshot_id:
            raise ChipStateContractError("transition breaks the tracer snapshot chain")
        if transition.model_version != self.model_version:
            raise ChipStateContractError("transition model version does not match tracer")
        if transition.grid_version != self.grid_version:
            raise ChipStateContractError("transition grid version does not match tracer")
        if self.current_origin_units == 0:
            return replace(self, current_snapshot_id=transition.destination_snapshot_id)
        arcs: dict[int, list[tuple[int, float]]] = defaultdict(list)
        for source, destination, fraction in zip(
            transition.source_cell_ids,
            transition.destination_cell_ids,
            transition.retained_fractions,
            strict=True,
        ):
            arcs[source].append((destination, fraction))
        missing = tuple(
            cell_id
            for cell_id, units in zip(self.cell_ids, self.origin_units, strict=True)
            if units > 0 and cell_id not in arcs
        )
        if missing:
            raise ChipStateContractError(f"transition omits traced source cells: {missing}")
        destination_units: dict[int, list[float]] = defaultdict(list)
        for source, units in zip(self.cell_ids, self.origin_units, strict=True):
            for destination, fraction in arcs.get(source, ()):
                destination_units[destination].append(units * fraction)
        aggregated = tuple(
            (cell_id, math.fsum(parts))
            for cell_id, parts in sorted(destination_units.items())
            if math.fsum(parts) > 0
        )
        if not aggregated:
            aggregated = ((transition.destination_cell_ids[0], 0.0),)
        return replace(
            self,
            current_snapshot_id=transition.destination_snapshot_id,
            cell_ids=tuple(cell_id for cell_id, _ in aggregated),
            origin_units=tuple(units for _, units in aggregated),
        )


@dataclass(frozen=True)
class AnchorCandidateRef:
    candidate_id: str
    symbol: str
    anchor_date: date
    started_at: datetime
    source_snapshot_id: str
    model_version: str
    grid_version: str
    selection_rule_version: str

    @classmethod
    def from_snapshot(
        cls, snapshot: ChipSnapshotV2, *, selection_rule_version: str
    ) -> AnchorCandidateRef:
        if snapshot.phase != SnapshotPhase.POST:
            raise ChipStateContractError("anchor candidates require a POST snapshot")
        if not selection_rule_version:
            raise ChipStateContractError("selection_rule_version cannot be empty")
        payload: dict[str, object] = {
            "symbol": snapshot.symbol,
            "anchor_date": snapshot.trading_date.isoformat(),
            "source_snapshot_id": snapshot.snapshot_id,
            "model_version": snapshot.model_version,
            "grid_version": snapshot.grid_version,
            "selection_rule_version": selection_rule_version,
        }
        return cls(
            candidate_id=stable_id("anchor_candidate", payload),
            symbol=snapshot.symbol,
            anchor_date=snapshot.trading_date,
            started_at=snapshot.decision_at,
            source_snapshot_id=snapshot.snapshot_id,
            model_version=snapshot.model_version,
            grid_version=snapshot.grid_version,
            selection_rule_version=selection_rule_version,
        )


@dataclass(frozen=True)
class SupportAnchorEvidence:
    """PIT evidence required before appending a working/support anchor."""

    evidence_id: str
    evaluated_at: datetime
    root_anchor_id: str
    source_snapshot_id: str
    root_origin_retention: float
    cost_migration_atr: float
    concentration_change: float
    peak_split: bool
    structure_broken: bool
    input_snapshot_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_aware(self.evaluated_at, "support evidence evaluated_at")
        if not all((self.evidence_id, self.root_anchor_id, self.source_snapshot_id)):
            raise ChipStateContractError("support evidence identity cannot be empty")
        if not math.isfinite(self.root_origin_retention) or not (
            0 <= self.root_origin_retention <= 1
        ):
            raise ChipStateContractError("root origin retention must be in [0, 1]")
        if not math.isfinite(self.cost_migration_atr):
            raise ChipStateContractError("cost migration must be finite")
        if not math.isfinite(self.concentration_change):
            raise ChipStateContractError("concentration change must be finite")
        if not self.input_snapshot_ids or tuple(
            sorted(set(self.input_snapshot_ids))
        ) != self.input_snapshot_ids:
            raise ChipStateContractError(
                "support evidence input snapshots must be non-empty and sorted"
            )

    @classmethod
    def create(
        cls,
        *,
        evaluated_at: datetime,
        root_anchor_id: str,
        source_snapshot_id: str,
        root_origin_retention: float,
        cost_migration_atr: float,
        concentration_change: float,
        peak_split: bool,
        structure_broken: bool,
        input_snapshot_ids: tuple[str, ...],
    ) -> SupportAnchorEvidence:
        input_ids = tuple(sorted(set(input_snapshot_ids)))
        payload: dict[str, object] = {
            "evaluated_at": evaluated_at.isoformat(),
            "root_anchor_id": root_anchor_id,
            "source_snapshot_id": source_snapshot_id,
            "root_origin_retention": root_origin_retention,
            "cost_migration_atr": cost_migration_atr,
            "concentration_change": concentration_change,
            "peak_split": peak_split,
            "structure_broken": structure_broken,
            "input_snapshot_ids": input_ids,
        }
        return cls(
            evidence_id=stable_id("support_anchor_evidence", payload),
            evaluated_at=evaluated_at,
            root_anchor_id=root_anchor_id,
            source_snapshot_id=source_snapshot_id,
            root_origin_retention=root_origin_retention,
            cost_migration_atr=cost_migration_atr,
            concentration_change=concentration_change,
            peak_split=peak_split,
            structure_broken=structure_broken,
            input_snapshot_ids=input_ids,
        )


@dataclass(frozen=True)
class SupportAnchorPolicy:
    """Versioned rules for a controlled working-anchor update."""

    min_root_origin_retention: float
    min_cost_migration_atr: float
    max_cost_migration_atr: float
    max_concentration_deterioration: float
    policy_version: str

    def __post_init__(self) -> None:
        if not 0 <= self.min_root_origin_retention <= 1:
            raise ChipStateContractError("minimum root retention must be in [0, 1]")
        if not all(
            math.isfinite(value)
            for value in (
                self.min_cost_migration_atr,
                self.max_cost_migration_atr,
                self.max_concentration_deterioration,
            )
        ):
            raise ChipStateContractError("support-anchor policy thresholds must be finite")
        if self.max_cost_migration_atr < self.min_cost_migration_atr:
            raise ChipStateContractError("support-anchor migration interval is inverted")
        if self.max_concentration_deterioration < 0:
            raise ChipStateContractError(
                "maximum concentration deterioration cannot be negative"
            )
        if not self.policy_version:
            raise ChipStateContractError("support-anchor policy version cannot be empty")

    def rejection_reasons(self, evidence: SupportAnchorEvidence) -> tuple[str, ...]:
        reasons: list[str] = []
        if evidence.root_origin_retention < self.min_root_origin_retention:
            reasons.append("ROOT_ORIGIN_RETENTION_TOO_LOW")
        if not (
            self.min_cost_migration_atr
            <= evidence.cost_migration_atr
            <= self.max_cost_migration_atr
        ):
            reasons.append("COST_MIGRATION_OUTSIDE_CONTROLLED_RANGE")
        if evidence.concentration_change < -self.max_concentration_deterioration:
            reasons.append("CONCENTRATION_DETERIORATED")
        if evidence.peak_split:
            reasons.append("PEAK_SPLIT")
        if evidence.structure_broken:
            reasons.append("STRUCTURE_BROKEN")
        return tuple(reasons)


@dataclass(frozen=True)
class LifecycleAnchorRef:
    """Append-only ROOT/SUPPORT chain; ROOT is never overwritten."""

    anchor_id: str
    role: AnchorRole
    symbol: str
    anchor_date: date
    confirmed_at: datetime
    source_snapshot_id: str
    candidate_id: str
    root_anchor_id: str
    parent_anchor_id: str | None
    model_version: str
    grid_version: str
    selection_rule_version: str
    support_evidence_id: str | None
    support_policy_version: str | None

    @classmethod
    def confirm_root(
        cls, candidate: AnchorCandidateRef, *, confirmed_at: datetime
    ) -> LifecycleAnchorRef:
        require_aware(confirmed_at, "confirmed_at")
        if confirmed_at < candidate.started_at:
            raise ChipStateContractError("root confirmation cannot be backdated")
        payload: dict[str, object] = {
            "role": AnchorRole.ROOT.value,
            "candidate_id": candidate.candidate_id,
            "confirmed_at": confirmed_at.isoformat(),
            "source_snapshot_id": candidate.source_snapshot_id,
        }
        anchor_id = stable_id("lifecycle_anchor", payload)
        return cls(
            anchor_id=anchor_id,
            role=AnchorRole.ROOT,
            symbol=candidate.symbol,
            anchor_date=candidate.anchor_date,
            confirmed_at=confirmed_at,
            source_snapshot_id=candidate.source_snapshot_id,
            candidate_id=candidate.candidate_id,
            root_anchor_id=anchor_id,
            parent_anchor_id=None,
            model_version=candidate.model_version,
            grid_version=candidate.grid_version,
            selection_rule_version=candidate.selection_rule_version,
            support_evidence_id=None,
            support_policy_version=None,
        )

    @classmethod
    def create_support(
        cls,
        *,
        root: LifecycleAnchorRef,
        parent: LifecycleAnchorRef,
        snapshot: ChipSnapshotV2,
        confirmed_at: datetime,
        evidence: SupportAnchorEvidence,
        policy: SupportAnchorPolicy,
    ) -> LifecycleAnchorRef:
        require_aware(confirmed_at, "confirmed_at")
        if root.role != AnchorRole.ROOT:
            raise ChipStateContractError("root reference must have ROOT role")
        if parent.root_anchor_id != root.anchor_id:
            raise ChipStateContractError("parent is outside the supplied root chain")
        if not (
            root.symbol == parent.symbol == snapshot.symbol
            and root.model_version == parent.model_version == snapshot.model_version
            and root.grid_version == parent.grid_version == snapshot.grid_version
        ):
            raise ChipStateContractError("support anchor symbol/version lineage disagrees")
        if snapshot.phase != SnapshotPhase.POST:
            raise ChipStateContractError("support anchor requires a POST snapshot")
        if confirmed_at < parent.confirmed_at or confirmed_at < snapshot.decision_at:
            raise ChipStateContractError("support confirmation cannot be backdated")
        if snapshot.trading_date <= parent.anchor_date:
            raise ChipStateContractError("support anchor must advance the anchor chain")
        if evidence.evaluated_at > confirmed_at:
            raise ChipStateContractError("support evidence is unavailable at confirmation")
        if evidence.root_anchor_id != root.anchor_id:
            raise ChipStateContractError("support evidence refers to another root anchor")
        if evidence.source_snapshot_id != snapshot.snapshot_id:
            raise ChipStateContractError("support evidence refers to another snapshot")
        if snapshot.snapshot_id not in evidence.input_snapshot_ids:
            raise ChipStateContractError("support evidence omits its source snapshot")
        rejection_reasons = policy.rejection_reasons(evidence)
        if rejection_reasons:
            joined = ",".join(rejection_reasons)
            raise ChipStateContractError(f"support anchor rejected: {joined}")
        payload: dict[str, object] = {
            "role": AnchorRole.SUPPORT.value,
            "root_anchor_id": root.anchor_id,
            "parent_anchor_id": parent.anchor_id,
            "source_snapshot_id": snapshot.snapshot_id,
            "confirmed_at": confirmed_at.isoformat(),
            "support_evidence_id": evidence.evidence_id,
            "support_policy_version": policy.policy_version,
        }
        return cls(
            anchor_id=stable_id("lifecycle_anchor", payload),
            role=AnchorRole.SUPPORT,
            symbol=root.symbol,
            anchor_date=snapshot.trading_date,
            confirmed_at=confirmed_at,
            source_snapshot_id=snapshot.snapshot_id,
            candidate_id=root.candidate_id,
            root_anchor_id=root.anchor_id,
            parent_anchor_id=parent.anchor_id,
            model_version=root.model_version,
            grid_version=root.grid_version,
            selection_rule_version=root.selection_rule_version,
            support_evidence_id=evidence.evidence_id,
            support_policy_version=policy.policy_version,
        )


@dataclass(frozen=True)
class AnchorTraceCacheKey:
    """Reuse is legal only for the same symbol, anchor day, day and model."""

    symbol: str
    anchor_date: date
    current_date: date
    model_version: str

    def __post_init__(self) -> None:
        if not self.symbol or not self.model_version:
            raise ChipStateContractError("anchor cache identity cannot be empty")
        if self.current_date < self.anchor_date:
            raise ChipStateContractError("anchor cache current date predates anchor date")


class AnchorTraceCache:
    """Small explicit cache; callers persist values in a columnar store if needed."""

    def __init__(self) -> None:
        self._values: dict[AnchorTraceCacheKey, OriginTracer] = {}

    def get(self, key: AnchorTraceCacheKey) -> OriginTracer | None:
        return self._values.get(key)

    def put(self, key: AnchorTraceCacheKey, tracer: OriginTracer) -> None:
        if (
            key.symbol != tracer.symbol
            or key.anchor_date != tracer.anchor_date
            or key.model_version != tracer.model_version
        ):
            raise ChipStateContractError("cache key does not match origin tracer")
        existing = self._values.get(key)
        if existing is not None and existing != tracer:
            raise ChipStateContractError("anchor trace cache is append-only and deterministic")
        self._values[key] = tracer

    def __len__(self) -> int:
        return len(self._values)
