# Strategy-independent directional-tail and risk-appetite data contract

## Registered source and scientific boundary

- Asset: `CY-006`, daily PIT-B causal research table v2.
- Immutable manifest SHA-256:
  `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.
- Construction reads the exact 2018-2023 partitions already governed by
  MKT-BRTH-002. Files for 2024-2026 are prohibited.
- Observation/decision time is the completed official close at 15:00
  Asia/Shanghai. Every contributing row must have `available_at <= decision_at`.
- The experiment is outcome-blind. It creates no signal, fill, forecast,
  strategy-habitat claim, or future-return label.

The source is bounded PIT-B, not archival PIT-A. Unknown required lineage is
missing and fails closed. `snapshot_id` and the exact source hashes are retained
in the output audit.

## Strategy-independent denominator

MKT-RISK-001 reuses the causal 120-consecutive-session security core from the
frozen breadth design so comparisons with breadth and volatility do not arise
from a changed population. A row must pass the registered hard-valid, bar,
trading-state, corporate-action, market-rule, historical-identity, completed-
close, current-trading, and positive-volume gates. The primary denominator
retains ST securities; `NON_ST` is the fixed sensitivity.

The governed views are `ALL_A`, `SH_A`, `SZ_A`, and `CHINEXT_BOARD`, with
minimum daily counts 1,000/400/400/200. These are exchange/board portability
views, not historical index-constituent claims. No strategy membership,
current-survivor list, liquidity threshold, or outcome-dependent selection is
permitted.

## Limit-relative price coordinate

The absolute security coordinate is constructed from the registered raw close,
raw `preclose`, and the date-effective registered price limits:

```text
u =  (close - preclose) / (up_limit_price - preclose), close >= preclose
u = -(preclose - close) / (preclose - down_limit_price), close < preclose
```

This expresses a move as utilization of the applicable upward or downward
daily price-limit distance. It is comparable across the registered 5%, 10%, and
20% regimes without pretending that a fixed raw-return cutoff has the same
meaning across boards or years.

A security is excluded from this experiment when `preclose`, `close`, or either
limit is missing/nonfinite/nonpositive; the limits do not strictly surround
`preclose`; `limit_pct` is not one of the registered 0.05/0.10/0.20 values; or
the close lies outside the registered limits. The coordinate is never clipped,
rounded, tolerated, inferred, or repaired. The limit-eligible share of the
otherwise valid core must be at least 99% for every governed group/date.

The 120-session core removes unsupported listing-day observations from the
comparable denominator, but this is not treated as proof that all listing-day
limit semantics are known. Rows that remain outside the registered geometry
still fail closed.

## Industry semantics

Industry uses only the causal registered CY-006 label when `industry_valid`,
`source_notice_date <= trade_date`, and the label is nonempty. Industry
representations require at least 80% mapped securities, at least five members
per included industry, and at least ten included industries. No present-day
classification or fallback mapping is allowed.

## Coordinates

Every primary representation preserves:

1. its absolute cross-year-comparable value;
2. a strictly causal expanding percentile, trailing-756-session percentile,
   and trailing-756-session robust z-score after at least 504 observations;
3. the same-date difference from `ALL_A` and rank across governed views where
   at least three views are valid.

Historical coordinates include the current completed close and never any later
date. Absolute, historical, and relative coordinates remain separate.

## Frozen controls and forbidden inputs

Redundancy is measured only against the frozen MKT-BRTH-002 discovery and
leadership roles and the frozen MKT-VOL-001 realized-volatility, intraday-range,
volatility-concentration, and volatility-change roles. The MKT-SHOCK-001 score
is intentionally excluded until directional-tail roles are frozen.

Forbidden inputs include strategy membership, signals, admissions, trades,
fills, returns after decision time, MFE, MAE, exits, outcome classes, current
constituent lists, unregistered participant identity/fund-flow/sentiment data,
all post-2023 partitions, and CY-011.

## Fail-closed conditions

Stop or mark the affected representation missing on source/hash mismatch,
duplicate keys, time travel, invalid registered state, post-2023 reads, invalid
limit geometry, inadequate limit-eligible share, inadequate view/industry
coverage, noncausal normalization, or deterministic rerun failure. No failed
primary may be rescued by a better-looking threshold, quantile, view, or year.
