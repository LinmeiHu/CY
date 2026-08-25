"""Compiled private kernels for exact chip-inventory migration.

These functions only replace Python/NumPy loop overhead.  Model parameters,
T+1 boundaries, saturation handling, and the public migration API remain in
``migration_v2``.
"""

from __future__ import annotations

import math

import numpy as np
import numpy.typing as npt
from numba import njit  # type: ignore[import-untyped]

FloatArray = npt.NDArray[np.float64]
BoolArray = npt.NDArray[np.bool_]


@njit(cache=True, nogil=True)  # type: ignore[misc]
def disposition_path_no_saturation(
    original: FloatArray,
    costs: FloatArray,
    known: BoolArray,
    prices: FloatArray,
    volumes: FloatArray,
) -> tuple[FloatArray, bool]:
    """Apply the disposition path while no source lot is exhausted.

    Returning ``False`` delegates the uncommon saturation case to the
    existing bounded water-fill oracle.  This keeps semantics exact while the
    common minute-by-cell loop runs as native code without temporary arrays.
    """

    remaining = original.copy()
    hazards = np.empty(original.size, dtype=np.float64)
    for minute_index in range(prices.size):
        requested = volumes[minute_index]
        if requested == 0.0:
            continue

        price = prices[minute_index]
        total_weight = 0.0
        for cell_index in range(remaining.size):
            hazard = 1.0
            if known[cell_index]:
                pnl_scaled = 1.5 * (
                    (price - costs[cell_index]) / costs[cell_index]
                )
                if pnl_scaled < -2.0:
                    pnl_scaled = -2.0
                elif pnl_scaled > 2.0:
                    pnl_scaled = 2.0
                hazard = math.exp(pnl_scaled)
            hazards[cell_index] = hazard
            total_weight += remaining[cell_index] * hazard

        if total_weight <= 0.0:
            return remaining, False

        scale = requested / total_weight
        for cell_index in range(remaining.size):
            proposal = remaining[cell_index] * hazards[cell_index] * scale
            if proposal > remaining[cell_index]:
                return remaining, False

        for cell_index in range(remaining.size):
            remaining[cell_index] -= remaining[cell_index] * hazards[cell_index] * scale

    return remaining, True


@njit(cache=True, nogil=True)  # type: ignore[misc]
def stable_sum(values: FloatArray) -> float:
    """Compiled compensated sum without Python list materialization."""

    total = 0.0
    compensation = 0.0
    for value in values:
        corrected = value - compensation
        updated = total + corrected
        compensation = (updated - total) - corrected
        total = updated
    return total


@njit(cache=True, nogil=True)  # type: ignore[misc]
def stable_weighted_sum(weights: FloatArray, values: FloatArray) -> float:
    total = 0.0
    compensation = 0.0
    for index in range(weights.size):
        value = weights[index] * values[index]
        corrected = value - compensation
        updated = total + corrected
        compensation = (updated - total) - corrected
        total = updated
    return total
