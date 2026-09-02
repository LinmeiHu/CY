# ASHARE-COLLAPSE-GAP-ZONE-HIGH-PRECISION-PILOT-V2 review instructions

The V1 120-chart workflow is stopped. Do not finish or summarize it.

Review only the 30 blind charts at `/Volumes/quant/CY_quant_research/ashare_collapse_gap_zone_high_precision_pilot_v2/blind_charts` and fill `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830/research/market_behavior_os_v2/reports/ASHARE-COLLAPSE-GAP-ZONE-HIGH-PRECISION-PILOT-V2_review.csv`.

1. Judge visual semantic fidelity only; do not predict future returns.
2. Identity, dates, and all post-marker information are intentionally hidden.
3. Use `A_EXACT_PATTERN`, `B_CLOSE_BUT_MISSING_SOMETHING`, or `C_NOT_THE_PATTERN` for `PRIMARY_LABEL`.
4. An exact pattern should visibly contain a former strong/leader stock, impulsive run-up, major coherent collapse, meaningful strict-gap/layered zone formed during that collapse, persistence without full fill, material distance below, and a later first return to the lowest meaningful boundary.
5. Use `YES`, `NO`, or `UNCERTAIN` for component questions.
6. `REJECTION_REASON` may contain semicolon-separated values from: `NOT_FORMER_LEADER`, `RUNUP_NOT_IMPULSIVE`, `COLLAPSE_NOT_MAJOR`, `GAP_TOO_SMALL_OR_LOCAL`, `GAP_OUTSIDE_MAIN_COLLAPSE`, `ZONE_NOT_PERSISTENT`, `INSUFFICIENT_DEPTH`, `WRONG_BOUNDARY_OR_REENTRY`, `ORDINARY_SIDEWAYS_GAP`, `OTHER`.
7. Do not open the private mapping during first-pass review.

All numeric construction rules are high-precision audit retrieval rules only, not strategy parameters.
