# ATRDR V27 2026YTD V1 reconstruction proof

Status: **FAIL — exact population closure is not yet achieved.** V2 is preserved only as schema, execution-tail, and downstream-contract evidence; it is not treated as the V1 producer.

## Frozen rule evidence and inputs

The same frozen V27 contract and unchanged Fast/Slow rules described in the 2024-2025 proof were applied to the QD-010 exact 2022-2026-08-12 daily panel. Signal decisions are completed-close only. The fixed maturity lag is 24 sessions and the V1 authorized data end is 2026-08-12. No outcome field was used in reconstruction or selection.

## Population comparison

- Market calendar identity: 147/147 dates.
- Direct compact-panel market reconstruction differs in 145 ret20 values, 144 ret60 values, and 9 regime labels, so it is not accepted as an exact replacement.
- With frozen non-outcome market values used only to isolate the downstream rule, reconstructed Slow is exact: 38 new / 38 golden, missing 0, extra 0.
- Reconstructed Fast after worsening-state routing is 18 new / 15 golden, missing 0, extra 3.
- Extra identities: `OAI-20260330-000612.SZ`, `OAI-20260330-000782.SZ`, and `OAI-20260401-002182.SZ`.
- 2026 Bull-accelerating and Bull-decelerating production generation remains unwired.

First difference: the market-feature producer value for `2026-01-05`; downstream Fast first identity difference is `OAI-20260330-000612.SZ`.

Conclusion: this missing producer remains unaccepted. Frozen V1 candidates and the recovered V2 consumer inputs are never used as production signal inputs.
