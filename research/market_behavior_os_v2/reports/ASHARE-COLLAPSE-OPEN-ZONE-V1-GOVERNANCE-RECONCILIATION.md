# A-share Collapse Open-Zone V1 Governance Reconciliation

## Authoritative distinction

The historical V1 programmatic strategy is valid and reproducible. Its strict
no-trade-gap interpretation is not valid.

Canonical descriptive alias:
`ASHARE-FORMER-LEADER-COLLAPSE-OPEN-ZONE-RECLAIM-V1`.

Historical experiment identifiers and artifacts remain unchanged. This note is
additive governance reconciliation, not a rewrite of the historical record.

## What V1 actually calculated

For a downward-discontinuity session `t`, V1 defined:

- `OPEN_ZONE_LOWER = Open_t`
- `OPEN_ZONE_UPPER = Low_{t-1}`
- interval: `[Open_t, Low_{t-1}]`

This is an open-based collapse zone. The portion `[Open_t, High_t]` may have
traded during session `t`; therefore the whole interval is not necessarily a
strict gap or no-trade interval.

## What the user meant

The intended true downward no-trade gap exists only when `High_t < Low_{t-1}`
and is exactly `[High_t, Low_{t-1}]`. V1 used `Open_t` rather than `High_t`, so
the two representations have different lower boundaries, layer hierarchies and
first-return clocks.

## Historical evidence retained

The historical code, executions, PIT/lineage checks, T+1 handling, QD-010
coordinates, trades and returns remain reproducible for the Open-Zone family.
Development's frozen Dual Fresh + E1 + U + H40 + K10 program produced 207
signals, approximately +3.51%/+3.34% mean/median net trade return, 93% historical
Open-Zone target realization, 6.68% CAGR and -3.46% MaxDD during 2017--2021.

The unchanged 2022--2023 historical V1 Validation produced 94 signals,
approximately +2.36%/+2.97% mean/median completed-trade return, 90.80% historical
Open-Zone target realization and +6.22% combined return. Its verdict remains
`DUAL_FRESH_K10_VALIDATION_MIXED`: Main was positive and ChiNext negative.

These are valid historical programmatic and economic facts about the Open-Zone
strategy. They are not evidence that a true no-trade-gap strategy has alpha.

## Why both lanes remain

V1 remains an independent former-leader collapse Open-Zone reclaim family. It
may be researched later only under that explicit interpretation. True-Gap V2
is a new representation with a different price object and must establish
semantic fidelity before any outcome, entry or portfolio research.

The lineage label `V1_SEMANTIC_CONTRACT_INVALID` is retained in its originating
audit but superseded as governance shorthand by the precise status below:

- `V1_PROGRAMMATIC_STRATEGY_VALID = YES`
- `V1_HISTORICAL_RETURN_RESULTS_REPRODUCIBLE = YES`
- `V1_STRICT_GAP_INTERPRETATION_VALID = NO`
- `V1_CAN_BE_INTERPRETED_AS_TRUE_GAP_STRATEGY = NO`
- `TRUE_GAP_ALPHA_EVIDENCE = NO`
