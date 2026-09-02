# ASHARE-COLLAPSE-DEFINING-GAP-ZONE-HIGH-PRECISION-PILOT-V3 review instructions

Review the 20 blind charts at `/Volumes/quant/CY_quant_research/ashare_collapse_defining_gap_zone_high_precision_pilot_v3/blind_charts` and fill `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830/research/market_behavior_os_v2/reports/ASHARE-COLLAPSE-DEFINING-GAP-ZONE-HIGH-PRECISION-PILOT-V3_review.csv`.

1. Judge only machine-to-human semantic fidelity. Do not predict returns.
2. View blind charts before the private diagnostic package.
3. `PRIMARY_LABEL` allows `A_EXACT_PATTERN`, `B_CLOSE`, or `C_NOT_PATTERN`.
4. Component fields allow `YES`, `NO`, or `UNCERTAIN`.
5. The orange rectangles are true strict no-trade collapse-defining layers.
6. The light-gray context is explicitly a stack envelope and may contain traded price regions; never judge it as one continuous gap.
7. `REJECTION_REASON` accepts semicolon-separated values from: `NOT_FORMER_STRONG_STOCK`, `RISE_TOO_SLOW`, `RISE_TOO_WEAK`, `COLLAPSE_NOT_MAIN_LEG`, `ZONE_TOO_SMALL`, `ZONE_TOO_LOCAL`, `WRONG_ZONE`, `WRONG_LAYER`, `ZONE_NOT_PERSISTENT`, `NO_DISTINCT_LOWER_REGIME`, `NO_SETTLING_PHASE`, `RETURN_TOO_FAST`, `WRONG_FIRST_RETURN_MARKER`, `OTHER`.
8. Identity, calendar dates, machine scores/classes, and all post-marker bars are hidden.

All numeric gates are semantic retrieval rules only, not strategy parameters. Do not run returns after labeling without separate authorization.
