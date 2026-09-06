# Phase 1 — Conversion Panel

OC-EXP-P1-001: **PASS**.

Reconstructed and reconciled `399` completed authoritative cycles and `5551` eligible holding-path rows. No strategy replay was run and authoritative V1 was not modified.

## Reconciliation

- Trade IDs: 399/399 unique and one-to-one across inherited ledgers.
- Entry/exit lineage, terminal return, realized P&L, capital, MFE, MAE, timing, giveback, and early returns match the frozen artifacts at 1e-12 tolerance.
- All nine causal stock-level entry features match their persisted evaluation events at 1e-12 tolerance.
- Corporate actions retain the inherited fail-closed total-return coordinates; the exit session uses only actual exit execution.

## Population

| Item | Count |
|---|---:|
| Completed cycles | 399 |
| Opportunity20 | 84 |
| Opportunity50 | 32 |
| False breakouts | 213 |
| Severe losses | 44 |

The new smoothness, pre-MFE adversity, peak timing, and decay fields are path outcomes. They are diagnostic variables and are not eligible entry-time predictors.
