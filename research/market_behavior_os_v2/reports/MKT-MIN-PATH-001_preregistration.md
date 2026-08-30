# MKT-MIN-PATH-001 preregistration

Status: `FROZEN_BEFORE_CONSTRUCTION_RESULT`.

Frozen spec SHA-256:
`bf7e05dcba95c647129638f36cd22684c012edf7aca9b0bcbb5e9355bac62327`.

This outcome-blind experiment binds the exact required-scale MKT-MIN-001 daily
and trajectory artifacts. It reads only median/p40/p60 daily descriptor levels
and Day -5..Day -1 values for twelve frozen descriptors. Raw minute rows and all
old OLS5/OLS3/endpoint/precomputed-shape fields are prohibited.

The twelve descriptors were selected before non-slope results across selling
pressure/recovery, demand/acceptance, volatility contraction/expansion, and
volume concentration. Each is tested under exactly three independent path
operators: adjacent-order progression, signed early/late reversal, and adjacent-
pace curvature. Every operator has two fixed definition neighbors and p40/p60
aggregation neighbors.

Each of 36 primaries separately faces coverage, definition, aggregation,
denominator, view-year, PIT, relative-coordinate, and same-session-level
redundancy gates. Reversal also requires both nonzero signs in every eligible
cell. Stable roles are compressed at absolute Spearman 0.85 under a frozen
priority. No failed descriptor/operator may be rescued by another descriptor,
old endpoint/OLS field, favorable view, or favorable neighbor. A stable path is
not by itself supply exhaustion, demand strengthening, compression usefulness,
accumulation/distribution, or a strategy signal.
