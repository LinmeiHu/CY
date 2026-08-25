"""Sorted SoA and compiled segmented replay for persisted chip operators."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numba import njit  # type: ignore[import-untyped]
from numpy.typing import NDArray


@dataclass(frozen=True)
class InventorySoA:
    local_ids: NDArray[np.uint64]
    shares: NDArray[np.float64]
    economic_bucket_ids: NDArray[np.int32]

    def __post_init__(self) -> None:
        size = self.local_ids.size
        if self.shares.size != size or self.economic_bucket_ids.size != size:
            raise ValueError("inventory SoA columns differ in length")
        if size and np.any(self.local_ids[1:] <= self.local_ids[:-1]):
            raise ValueError("inventory ids must be strictly sorted")
        if np.any(~np.isfinite(self.shares)) or np.any(self.shares < 0.0):
            raise ValueError("inventory shares must be finite and non-negative")


@njit(cache=True)  # type: ignore[misc]
def advance_inventory_and_lineage(
    inventory_ids: NDArray[np.uint64],
    inventory_shares: NDArray[np.float64],
    lineage_shares: NDArray[np.float64],
    source_ids: NDArray[np.uint64],
    destination_ids: NDArray[np.uint64],
    retained_fractions: NDArray[np.float64],
    adjustment_ids: NDArray[np.uint64],
    adjustment_shares: NDArray[np.float64],
) -> tuple[NDArray[np.uint64], NDArray[np.float64], NDArray[np.float64]]:
    """Advance inventory and any number encoded lineage mass in one walk."""

    count = source_ids.size + adjustment_ids.size
    ids = np.empty(count, dtype=np.uint64)
    inventory = np.zeros(count, dtype=np.float64)
    lineage = np.zeros(count, dtype=np.float64)
    used = 0
    for index in range(source_ids.size):
        position = np.searchsorted(inventory_ids, source_ids[index])
        if position >= inventory_ids.size or inventory_ids[position] != source_ids[index]:
            raise ValueError("operator source is missing from sorted inventory")
        retained = retained_fractions[index]
        if retained <= 0.0:
            continue
        ids[used] = destination_ids[index]
        inventory[used] = inventory_shares[position] * retained
        lineage[used] = lineage_shares[position] * retained
        used += 1
    for index in range(adjustment_ids.size):
        ids[used] = adjustment_ids[index]
        inventory[used] = adjustment_shares[index]
        lineage[used] = 0.0
        used += 1
    order = np.argsort(ids[:used])
    sorted_ids = ids[:used][order]
    sorted_inventory = inventory[:used][order]
    sorted_lineage = lineage[:used][order]
    if used == 0:
        return sorted_ids, sorted_inventory, sorted_lineage
    unique_count = 1
    for index in range(1, used):
        if sorted_ids[index] != sorted_ids[index - 1]:
            unique_count += 1
    out_ids = np.empty(unique_count, dtype=np.uint64)
    out_inventory = np.zeros(unique_count, dtype=np.float64)
    out_lineage = np.zeros(unique_count, dtype=np.float64)
    segment = 0
    out_ids[0] = sorted_ids[0]
    for index in range(used):
        if sorted_ids[index] != out_ids[segment]:
            segment += 1
            out_ids[segment] = sorted_ids[index]
        out_inventory[segment] += sorted_inventory[index]
        out_lineage[segment] += sorted_lineage[index]
    keep = out_inventory > 0.0
    return out_ids[keep], out_inventory[keep], out_lineage[keep]
