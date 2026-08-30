# Industry leadership and relative-strength data contract

## Registered source and time boundary

- Asset: registered `CY-006` daily PIT-B causal research table v2.
- Source root:
  `/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily`.
- Manifest SHA-256:
  `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.
- Read only exact registered 2018-2023 partitions; 2024-2026 remain unread.
- Observation/decision timestamp: completed official close, 15:00
  Asia/Shanghai.
- First possible action: a later causally valid session. MKT-INDRS-001 creates
  no action and reads no future outcome.

Runtime must verify the registry, manifest, six partition hashes, duplicate
keys, source row count, OHLC validity, and `available_at <= decision_at` before
construction.

## Causal price coordinate and denominator

Use the exact MKT-BRTH-002 causal action-aware price chain and 120-step core:
raw close steps are rebased only by date-effective, available corporate-action
facts; unknown rights/action lineage, calendar gaps, or invalid steps fail the
entire touched window. No future-adjusted price factor is permitted.

Current rows must also be trading, data-tradable, and positive-volume. The
primary denominator retains ST; `NON_ST` is a fixed sensitivity. Views are
ALL_A, SH_A, SZ_A, and CHINEXT_BOARD with minimum current counts
1,000/400/400/200. There is no liquidity screen, listing-age rule, present-day
survivor list, or strategy membership.

## PIT industry membership

An industry label is eligible only when `industry_valid=true`, nonempty, and
`source_notice_date <= trade_date`. Missing/UNKNOWN or future-known labels are
unmapped; no current label is backfilled into history.

Each included industry must have at least five eligible current members in its
view/denominator. A daily industry representation is valid only when industry
mapping covers at least 80% of the eligible view and at least ten industries are
included.

Same-date industry returns are equal-industry aggregates after the member gate.
Cross-date leadership persistence/rotation compares exact labels known on each
date and uses only industries present on both dates. Membership/classification
churn is reported; labels are never harmonized using future classifications.

## Leave-one-out stock-versus-industry context

For each eligible stock, compare its 20-session causal return with the median
of the other eligible members of its current causal industry in the same view,
denominator, and date. The focal stock must be removed exactly. Industries with
fewer than five total members are absent. No inclusive industry median or
market-wide substitute may silently replace unavailable leave-one-out context.

## Coordinates and fail-closed rules

Every accepted primary preserves:

1. an absolute dimensionless value;
2. causal expanding/trailing-756 percentiles and robust z after 504 prior/current
   observations;
3. same-date view-minus-ALL_A and governed-view rank.

Fail or mark affected representations missing on identity mismatch, invalid
price lineage, inadequate view/industry/mapping/common-industry coverage,
nonfinite arithmetic, nonconserved leave-one-out construction, or noncausal
normalization. Never normalize, clip, round-repair, forward-fill, or relax a
gate to retain a date.

## Forbidden inputs

- the rejected MKT-BRTH MA10/20/60 industry-diffusion or stock-minus-industry
  divergence fields;
- unregistered index/industry/style membership or current-survivor labels;
- future returns, strategy membership, signals, admissions, trades, P&L, MFE,
  MAE, exits, durations, or outcome classes;
- CY-011.
