# Intraday and five-day minute data contract

This contract extends the accepted QD-004/CY-008 audit to Research OS V2. The
prior audit proved exact signal-session coverage; a fresh outcome-blind audit is
still required for the five sessions before each signal.

## Registered sources

- QD-004: canonical raw/unadjusted A-share one-minute OHLCV/amount, PIT-B,
  `RESEARCH_CONDITIONAL`, exact frozen 2018-2026 file inventory.
- QD-005: deterministic session-aware five-minute derivation from QD-004 only;
  no independent vendor substitution.
- CY-008: QD-004 joined to causal CY-006 daily context, with source,
  `available_at`, `snapshot_id`, `hard_valid`, trading state, action validity,
  and six sequential opening five-minute windows.
- QD-006 and other overlapping minute copies: QA only, never fallback.

## Bar and session semantics

- `bar_end_time` is the completed bar end in Asia/Shanghai local time.
- A valid complete session has 241 unique rows: a separate 09:30 auction row and
  240 continuous rows at 09:31..11:30 and 13:01..15:00.
- The lunch break is a hard boundary. No aggregation may cross 11:30 to 13:01.
- A five-minute bar is first/high/low/last/sum over five consecutive continuous
  one-minute bars inside one morning or afternoon session. A valid full day has
  48 such windows. Volume and amount must conserve exactly.
- Sequential opening windows become available only after their own completed
  endpoints: 09:35, 09:40, ..., 10:00.
- A complete daily minute summary is conservatively available at 15:30.

## Predictor and execution boundary

- A descriptor from Day -5..Day -1 is available only after the close of its own
  day. The complete five-day trajectory is available after Day -1 at 15:30.
- A signal-session full path is available only at signal-session 15:30 and may
  influence T+1 open or later.
- No minute after `decision_at` may enter a predictor. Entry-execution-day bars
  after 09:30 cannot justify an already-completed 09:30 fill.
- Post-entry 5/15/30/60-minute continuation is outcome attribution and must be
  labeled separately from pre-entry prediction.

## Auction, suspension, limits, missing and abnormal bars

- The 09:30 auction is excluded from the primary continuous-session path unless
  explicitly assigned an auction role. Auction-inclusive definitions are fixed
  neighbors, not selection alternatives.
- Suspended, incomplete, duplicate, nonconforming-grid, nonpositive-price,
  negative-volume/amount, unit-invalid, reconciliation-failed, or
  `hard_valid=false` sessions fail closed.
- Flat or limit-locked sessions are retained with a preregistered neutral or
  structural treatment; they are not silently dropped.
- Historical limit prices/rules and trading status come from the causal CY-006/
  CY-008 daily context. Unknown required context fails closed.
- QD-004's source manifest records quarantined anomalies. Only exact inventoried
  canonical files may be read; alternative copies cannot replace a missing row.

## Corporate actions and price coordinates

- QD-004 prices are raw/unadjusted. Within-session ratios avoid cross-action
  coordinate ambiguity.
- Multi-day price-level trajectories may not join raw closes across an action
  without the accepted CY-006 causal share/cash transform and exact
  `coordinate_step_valid` lineage.
- Within-day dimensionless path shapes, ranges relative to the same day's price,
  VWAP-relative measures, and volume shares remain in raw same-session
  coordinates. Cross-day price progression requires action-safe adjusted daily
  anchors or must fail closed.
- Future-adjusted minute prices are prohibited.

## Units and interpretive limits

- Volume is shares; amount is CNY; VWAP is `sum(amount) / sum(volume)` when
  volume is positive.
- Turnover requires a causal join to circulating shares; it is not a free raw
  minute field.
- OHLCV bars cannot identify buyer/seller initiative, queue priority,
  cancellations, hidden liquidity, absorption, or participant identity. Terms
  such as buying pressure or selling exhaustion denote falsifiable OHLCV proxies,
  not observed order flow.

## Required five-day activation audit

Before any five-day feature is frozen, the audit must verify for every proposed
event and Day -5..Day -1 session:

1. exact calendar mapping and no lookahead;
2. exact QD-004/CY-008 inventory hashes;
3. 241 unique bars and the exact session grid;
4. one hard-valid CY-008 daily context row;
5. source resolution, units, session completeness, OHLC validity, volume/amount
   reconciliation, trading status, limit rules, suspension state, and action
   validity;
6. missing/flat/limit-locked/action-session counts;
7. exact five-minute volume/amount conservation and opening-window agreement;
8. feature `available_at` and first potential action timestamps;
9. zero outcome fields read.

Failure of an indispensable gate rejects that experiment's data feasibility. It
does not authorize imputation, another vendor, or a narrower favorable sample.
