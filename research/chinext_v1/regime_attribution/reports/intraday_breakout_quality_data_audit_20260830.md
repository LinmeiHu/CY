# Intraday breakout-quality data availability audit

This outcome-blind audit assesses existing, registered intraday data for the 399
accepted CHINEXT V1 completed cycles. It downloads nothing, reads no outcome
association, and does not authorize a strategy rule.

## Available assets

| Layer | Coverage and fields | Governance | Research use |
|---|---|---|---|
| QD-004 canonical 1-minute | 2000-06-09..2026-08-12; raw unadjusted OHLC, shares, CNY amount; naive Asia/Shanghai `bar_end_time` | PIT-B, `RESEARCH_CONDITIONAL`; exact 2018-2026 inventory and manifest | Event-scoped transformation only after exact inventory, session, daily-context, lineage, and no-same-bar gates |
| QD-005 causal 5-minute | Virtual derivation from QD-004 | `DERIVE_ONLY`; not independently materialized | May be derived session-by-session with frozen transform and conservation checks |
| CY-008 PIT-B minute table | 2018-01-01..2026-08-12; daily aggregates plus six completed 09:31..10:00 five-minute windows; source, `available_at`, snapshot and `hard_valid` | Cross-year gate PASS; exact 27-file inventory | Full-session summary after 15:30 and sequential 09:35..10:00 opening-window research |
| Alternative minute/5-minute copies | QMT, TDX, BaoStock overlaps | `QA_ONLY` | Reconciliation only; never silent fallback |
| Historical ticks/order book | None | `UNAVAILABLE` | No queue, cancellation, hidden-liquidity, or participant claims |

CY-025 extends current data after the frozen historical range, but it is blocked
for prior protocols and is unnecessary for this 2018-2025 experiment.

## Exact V1 coverage

- Entry-signal sessions: 399/399 daily rows present and hard-valid; 399/399 have
  six hard-valid opening windows.
- T+1 entry-execution sessions: the same 399/399 daily and 399/399 six-window
  coverage.
- Every selected source session contains exactly 241 distinct bars: a separate
  09:30 auction row and 240 continuous rows from 09:31..11:30 and 13:01..15:00.
- Full-session CY-008 opening/closing returns, close versus VWAP, last-hour volume
  share, and realized volatility are complete on all 798 audited signal/execution
  sessions.
- An event-scoped reconstruction of all 399 signal sessions contains 96,159 raw
  rows. Raw OHLCV/amount aggregates match all 2,394 CY-008 opening-window fields
  exactly; all relevant QD-004 and CY-008 inventory hashes pass.
- One hard-valid signal session (300377.SZ, 2019-10-28) is flat/limit-locked. It
  is preserved with an explicit neutral mathematical treatment rather than
  dropped.

## Timestamp and execution semantics

The raw one-minute timestamp is the completed bar end in local Shanghai time.
CY-008 exposes the first six five-minute windows only after 09:35, 09:40, ...,
10:00. A complete daily aggregate is conservatively available at 15:30.

The accepted `entry_signal_date` is the V1 retest-confirmation/entry-intent
session. Its full intraday path can therefore be used only at that session's
15:30 decision and applied at T+1 open or later. An entry-execution-day bar after
09:30 cannot retrospectively justify the already-completed 09:30 fill. Full-day
entry-execution information is explanatory or usable only for later actions.

The accepted trade ledger does not preserve the earlier lifecycle `breakout_at`
and frozen breakout reference for all 399 completed cycles. The first experiment
therefore studies entry-signal-session acceptance, not the original breakout
attempt. Recovering the original lifecycle event would require separately
governed trace materialization and is not silently inferred.

## Adjustment, sessions, and market rules

- Prices are raw/unadjusted. The initial experiment uses within-session ratios,
  avoiding cross-action coordinates.
- Volume is shares and amount is CNY, so session VWAP is reconstructable as
  `sum(amount)/sum(volume)`.
- Intraday turnover can be constructed only by joining causal daily circulating
  shares; it is not a free-standing raw field.
- CY-008 joins daily trading status, ST state, limit prices/rules, corporate-action
  validity, float and hard-valid context. All selected sessions pass.
- Suspended or incomplete symbol-days fail closed; none is present in the fixed
  event sample.
- The market-wide source is not a current-survivor list, but the scientific
  population is conditioned on accepted V1 entries and remains bounded PIT-B,
  not strict archival PIT-A.

## Decision

Existing data are sufficient for one minimum-sufficient entry-signal-session
trajectory experiment. They are insufficient for order-flow psychology, queue
behavior, or exact original-breakout anchoring without new governed lineage.
