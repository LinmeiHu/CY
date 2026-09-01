# Volume Exhaustion Bottom V1 — Final Report

## Environment

- Worktree: `/Users/linmei/Documents/CY-volume-exhaustion-bottom`
- Branch: `research/volume-exhaustion-bottom-v1`
- Starting HEAD: `d0d4fddbddcc1f236f0f2b2b6c5b4ae6bd310381`
- Starting status: clean
- Ending HEAD before the research checkpoint: unchanged from starting HEAD
- All new files are confined to `research/volume_exhaustion_bottom/`.

## Data

- Authority: registered `CY-006` daily PIT-B V2 table, nine frozen Parquet partitions.
- Coverage: 2018-01-02 to 2026-08-12; 9,421,907 rows; 5,682 historical symbols.
- Validity: 9,063,454 `hard_valid` rows; 8,816,183 hard-valid, non-ST trading rows;
  zero aggregate time-travel rows.
- Semantics: unadjusted OHLC, shares, CNY amount, turnover fraction, PIT trading/ST/limit
  state, corporate-action/reference fields, `available_at`, snapshots, and fail-closed reasons.
- Final input authorization: `CAUSAL_RESEARCH`, operation `BACKTEST`, manifest
  `VOLUME-EXHAUSTION-BOTTOM-V1-CY006-20260901`; all nine content hashes verified.
- Limitations: PIT-B rather than PIT-A action revision history; listing age proxied by trading
  history; no minute/L2 fill model; no costs; no separate event-collapse control.

## Definitions

- **LOW (A):** 60-session drawdown <= -15%, adjusted close within 5% of the 60-session
  adjusted intraday low, 120-session age, 20-session median amount >= CNY 10m.
- **DRY-UP (B):** A and 5-session mean amount / 20-session median amount <= 0.55.
- **STABILIZATION (C):** B, 3-session return >= -2%, recent 3-session low no more than 1%
  below the preceding 3-session low, and recent downside-return-per-turnover no worse than
  its 20-session baseline.
- **CONFIRMATION (D):** a C in the previous five sessions followed by close above the prior
  five-session adjusted-close high.
- **SECOND-LOW:** revisit after 10–40 sessions within 97%–105% of the first low, intervening
  rebound >= 8%; contraction ratio <= 0.60 versus explicit no-contraction ratio >= 0.80.

Signals are formed at close and enter only at the next listed session's legal open. Exact
formulas and de-clustering rules are in `methodology.md`.

## Sample

- Eligible signal observations: 6,794,505 across 5,176 securities.
- Raw A/B/C qualifying observations: 886,821 / 24,877 / 4,684.
- De-clustered A/B/C/D events: 97,175 / 9,645 / 2,901 / 1,961.
- Complete legal-entry and 20-session outcome events used below: 94,895 / 9,215 / 2,827 /
  1,901.
- Second-low events: 222,695 across 5,167 securities; 219,442 have complete outcomes.
- Signal range: 2020-01-02 to 2026-08-12; late signals without 20-session outcomes are excluded
  from metric tables.

## Core results

All percentages are gross next-open forward outcomes. MFE and MAE columns are 20-session
means. Every row uses a complete common 20-session sample.

| Stage | N | Mean R5 | Median R5 | Hit R5 | Mean R10 | Median R10 | Hit R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| A LOW | 94,895 | 0.674% | 0.312% | 52.15% | 0.658% | 0.196% | 50.97% | 1.616% | 0.483% | 51.78% | 11.49% | -9.06% |
| B + DRY-UP | 9,215 | 0.121% | -0.031% | 49.29% | 0.571% | 0.062% | 50.34% | 1.521% | 0.046% | 50.16% | 10.98% | -8.94% |
| C + STABILIZATION | 2,827 | -0.435% | -0.523% | 44.11% | -0.244% | -0.758% | 43.83% | 0.162% | -0.821% | 45.84% | 8.91% | -8.17% |
| D + CONFIRMATION | 1,901 | -0.245% | -0.686% | 42.29% | -0.119% | -0.790% | 44.71% | 0.302% | -1.139% | 45.34% | 9.41% | -8.16% |

Raw nested daily conditions tell the same story: mean R20 is 1.586% for A, 1.467% for B,
-0.099% for C, and 1.024% for subsequent D confirmation observations.

## Incremental finding

- **B - A:** mean R5 falls 0.553 percentage points and R20 falls 0.095 points; 20-session
  hit rate falls 1.62 points. Extreme amount dry-up does not add useful threshold information.
- **C - B:** mean R20 falls 1.359 points, median R20 falls 0.867 points, and hit rate falls
  4.31 points. The chosen “selling no longer works” representation is adverse, not additive.
- **D - C:** mean R20 improves only 0.140 points while median R20 worsens 0.318 points and hit
  rate falls 0.50 points. Confirmation modestly improves MFE but does not repair the setup.

The continuous picture is weaker but not completely null. After stratifying LOW events by
time block and drawdown quintile, the driest activity quintile has mean R20 of 1.967% versus
1.382% for the most active quintile, a 0.584-point spread. The relation is broadly monotone,
but too small to validate the hard-threshold structure.

LOW's effect is much stronger along ordinary oversold dimensions: the deepest drawdown
quintile has mean R20 of 2.590% versus 0.736% for the shallowest, and observations closest to
the exact low have 3.788% versus 0.940%. This is evidence that most of the apparent effect is
ordinary oversold/low-price mean reversion.

## Second-low result

| Retest group | N | Mean R5 | Hit R5 | Mean R10 | Hit R10 | Mean R20 | Median R20 | Hit R20 | MFE20 | MAE20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| All | 219,442 | 0.210% | 47.92% | 0.386% | 47.54% | 0.591% | -0.685% | 47.18% | 10.76% | -8.76% |
| Contracted | 44,827 | -0.019% | 46.34% | 0.140% | 45.96% | 0.213% | -1.003% | 45.80% | 10.09% | -8.79% |
| Not contracted | 136,201 | 0.321% | 48.66% | 0.499% | 48.23% | 0.711% | -0.578% | 47.60% | 11.07% | -8.77% |

Contraction underperforms no contraction by 0.499 percentage points at 20 sessions and 1.80
hit-rate points. This classic version of “地量见地价” is not promising in V1.

## Time and segment stability

The LOW mean R20 is 1.73% in 2020–2022, 0.07% in 2023–2024, and 3.37% in 2025–2026.
D is -0.68%, +2.88%, and +0.11% in those blocks. The instability is too large for a robust
mechanism claim. LOW is positive on main board and ChiNext but weaker on STAR; C is negative
on main board and ChiNext. No BSE event survived the fixed eligibility and complete-outcome
sample, so no BSE claim is made.

## Failure modes

- Continued downtrends remain common: C/D median returns and hit rates are negative/under 50%.
- Dry-up can represent neglect and lack of demand, not exhausted supply.
- The strongest rebound occurs after high downside impact, contradicting the stabilization
  mechanism and looking more like capitulation.
- Results are regime-dependent, especially 2023–2024 versus 2025–2026.
- Event-driven collapses are not separately identified; the data is causal but V1 has no
  announcement/fundamental shock classifier.
- Gross outcomes omit costs and queue/impact details; small spreads would shrink in practice.
- PIT-B corporate-action timing is suitable for causal research but not a PIT-A archive claim.

## Verdict

`WEAK`

LOW PRICE is predictive in mean, but the evidence points mainly to ordinary oversold mean
reversion. Extreme volume dry-up fails the incremental ladder, stabilization is adverse,
confirmation does not materially repair it, and second-low contraction underperforms. The
only surviving evidence is a modest 0.58-point continuous dry-up spread after simple
drawdown/time control. That is insufficient for a strategy claim but enough for one narrow
falsification-oriented follow-up.

## Next step

Run one V2 only: test **continuous cross-sectional dry-up rank inside tightly matched LOW
events**, neutralizing time block, drawdown depth, distance to low, liquidity, and PIT
industry, with one frozen out-of-time evaluation. Do not extend the threshold ladder,
double-bottom detector, or confirmation search unless that matched rank survives.

