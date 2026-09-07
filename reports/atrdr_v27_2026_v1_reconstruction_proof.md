# ATRDR V27 2026YTD V1 reconstruction proof

Status: **PASS — full registered-input population and end-to-end V1 closure.** V2 and all frozen V1 outputs remain evidence/golden only.

The registered input is QD-010 exact through 2026-08-12, SHA256 `d092206b2c36212cf95ab0540bf6905a3274f1ba4706a50510e7cd24c9e1929c`. The same unchanged market, Fast, Slow, V1/V5 accelerating-Bull, QIG/V24/V19R2 decelerating-Bull, execution, capacity, and portfolio semantics documented in the 2024-2025 proof are used.

The first prior mismatch was 2026-01-05. `atrdr_market_feature_forensics.csv` records the exact frozen and prior median units, price endpoints, lineage, and asset version. Restoring the registered universe/validity/calendar contract makes all 147 market dates exact, including ret20, ret60, both breadths, and regime.

The fixed V1 maturity lag remains 24 global sessions. At the 2026-08-12 authorized data end, the last mature signal index is 3279; 24 later Slow signals remain right-censored and do not enter outcomes.

Exact closure: Market 147/147; Fast 15/15; Slow candidates 38/38 and mature outcomes 14/14; Bull accelerating 9/9; Bull decelerating 2/2; source union 38/38; accepted trades 38/38; NAV 147/147. Missing identities, extra identities, value mismatches, and maximum absolute delta are all zero.

Conclusion: 2026YTD V1 is accepted as an exact outcome-blind behavioral reconstruction from registered inputs.
