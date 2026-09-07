# ATRDR V27 2024-2025 reconstruction proof

Status: **PASS — full registered-input population and end-to-end closure.** Frozen outputs are golden comparison targets only and are not production inputs.

## First feature difference and upstream cause

The first prior mismatch was 2024-01-02. Its complete price-unit evidence is in `atrdr_market_feature_forensics.csv`. Both sides used coordinate prices from the same registered QD-010 asset; no defining unit had a suspension or corporate action in either return window. The mismatch was not an adjustment or data-version difference.

The frozen market producer restricts the causal source universe to MAIN and CHINEXT while excluding the frozen 22-industry set, computes N-session returns only when the lag row has `lag_cal_idx = cal_idx-N`, and aggregates `current_valid AND NOT is_st` rows. The prior standalone producer used the broader universe, required `hard_valid`, and did not enforce the calendar-index endpoint. Restoring those upstream semantics yields exact market values on all 485 dates: ret20, ret60, both breadths, and regime have zero mismatches and zero maximum absolute delta.

## Frozen rules and production inputs

- Registered daily: QD-010 exact 2022-2026Q1, SHA256 `95ba886707811da9a0514d1d3a9b2ddf9df5debe69eed4e904502f8f3e1cfca9`.
- Fast: exact V17 OAI continuation, 20-session cooldown, breadth-improvement gate, then V27 BEAR-worsening split. Thresholds were unchanged.
- Slow: recovered producer SHA256 `4c4992e333c9f7931ca84454e1f71742cf49bcfa8ff333ba8876cc202f351870`, then the frozen V27 BEAR-stabilizing and deep-market either gate.
- Bull accelerating: V1 inside-day supply contraction plus V5 first valid completed close above the setup coordinate high within five sessions; V27 BULL accelerating route.
- Bull decelerating: QIG mother, V24 market/industry admission, V19R2 immediate confirmation, and V27 BULL decelerating route.
- All signal clocks use completed close; entries start strictly later. Price limits, suspension state, validity, and coordinate lineage fail closed.

The only numeric tolerance is `1e-12` when deciding equality to a frozen coordinate high. This is below one raw-price tick and only removes binary representation noise; no economic threshold crossing is admitted.

## Exact closure

Market 485/485; Fast 151/151; Slow 674/674; Bull accelerating 11/11; Bull decelerating 112/112; source union 917/917; accepted trades 397/397; NAV 541/541. Every identity and compared feature/trade value matches; maximum absolute delta is zero in the final production run.

Conclusion: 2024-2025 V27 is accepted as an exact outcome-blind behavioral reconstruction from registered inputs.
