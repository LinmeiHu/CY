# ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4 — Candidate readiness

## Current conclusion

V4 is the first simple below-gap repair candidate to meet the requested numerical discovery target in both 2017–2021 Development and a frozen 2022–2023 post-observation diagnostic. It is not yet a pristine externally validated strategy because aggregate outcomes from related V1–V3 experiments were already known before V4 was specified.

## Fixed economic rule

1. A downward true gap is `[L,U] = [High_t, Low_{t-1}]`.
2. Exact 120-session minute VAP must show no above-local-average density inside `[L,U]` or its immediate `[L-0.5W,U+0.5W]` corridor.
3. The 20-session coordinate return before gap formation is non-positive.
4. Price subsequently washes out at least 10% below `L`, remains at least 5% below `L`, and its recent low is 2–10 completed sessions old.
5. After recovering at least 3% from that low, the first completed daily MA5 reclaim triggers a signal.
6. Entry is the next legal 1-minute open. The target is `entry + 0.80*(L-entry)`, strictly below `L`. There is no failure stop; the time stop is H20. Round-trip cost is 40 bp.
7. Main and ChiNext have separate 50% sleeves, K20 per sleeve, with no leverage or cross-sleeve transfer.

## Numerical evidence

| Evidence | Selected signals | Executable entries | Portfolio trades | Mean net | Median net | Severe10 | CAGR | MaxDD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2017–2021 Development | 583 | 448 | 311 | 3.37% | 5.45% | 10.61% | 5.31% | -5.30% |
| 2022–2023 fixed diagnostic | 136 | 98 | 93 | 3.12% | 5.16% | 11.83% | 3.65% | -3.08% |

Development portfolio trades averaged 62.2 per year. Diagnostic executable entries averaged 49.0 per year. All seven calendar-year portfolio returns from 2017 through 2023 were positive, but 2023 trade-level mean was only 1.26%, so final validation remains necessary.

The 2022–2023 combined result remained positive after excluding its best five trading days. The top five symbols represented 9.68% of diagnostic trades and the top five entry dates represented 23.66%.

## Completion audit

| Requirement | Evidence | Status |
|---|---|---|
| Clear economic meaning | Clean overhead repair space plus causal washout/reversal | Proven as a coded hypothesis |
| PIT and causal features | Latest feature timestamp at signal; post-signal count zero | Passed |
| Next-bar execution and T+1 | Entry-at/before-signal and T+1 violation counts zero | Passed |
| Mean net trade at least 3% | 3.37% Development; 3.12% diagnostic | Passed numerically |
| Around 50 executable signals per year | 49.0 per year in diagnostic | Passed numerically |
| Tail, drawdown, concentration controlled | Severe10 11.83%, MaxDD -3.08%, concentration below proposed caps | Passed numerically |
| Independent untouched time validation | Requires explicit authority to open 2024–2025 | Not complete |

## Frozen next test

The proposed challenge is 2024-01-01 through 2025-12-31, with 2026 remaining sealed. It must use the exact V4 hashes and pass criteria recorded in `ASHARE-TRUE-GAP-BELOW-L-EARLY-REPAIR-V4_final_challenge_proposal.json`. Creating this proposal neither authorizes nor performs any 2024+ read.
