# CHINEXT V1 regime-attribution research contract

Frozen on 2026-08-30 before any new unified yearly or regime-attribution result.

## Authoritative baseline identity

- Strategy file: `research/chinext_v1/strategy/chinext_v1_exploratory.py`
- Strategy SHA-256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
- Configuration: market 399102.SZ close above MA20 for new-entry permission;
  market MA20 x2 normal exit; close below MA20 x0.96 emergency exit; B60; own
  close above MA20; FULL40; MINVOL; breakout-volume shadow; 20/50/30
  cross-sectional RS; max ten holdings at 10% each; SET_CHANGE_ONLY;
  NO_REPLACEMENT; individual MA30 x2 exit.
- Execution: completed-close signal, no same-bar fill, first valid later open,
  sell before buy, explicit T+1/limit/tradability handling, 100-share buy lot.
- Costs: fixed 10 bps per filled side. No stamp duty or slippage is retroactively
  inserted into frozen V1. Sensitivity scenarios must be labeled counterfactuals.
- Corporate actions: use frozen causal price/volume rebasing and exact share/cash
  ledger semantics. Unsupported/ambiguous events fail closed.

## Authoritative period artifacts

The three blocks are comparable frozen V1 evaluations, but are not one continuous
fund NAV. NAV starts independently in each block and must not be naively chained.

| Block | Dates | Universe/authorization | Authoritative NAV and execution ledgers |
|---|---|---|---|
| EXTENDED | 2018-01-02..2021-12-31 | CY-029 plus separately preregistered Gate C/D and one extended replay; bounded effective-state PIT-B | `output/chinext_v1_extended_2018_2021/` |
| HOLDOUT | 2022-01-04..2023-12-29 | CY-028 / `CYQ-AUTH-CHINEXT-V1-PIT-B-HOLDOUT-2022-2023-V1`; O0 baseline arm only | `output/chinext_v1_phase9b_oos/O0_BASELINE/` |
| DEVELOPMENT | 2024-01-02..2025-12-31 | CY-027 / `CYQ-AUTH-CHINEXT-V1-PIT-B-2024-2025-V1` | `output/chinext_v1_pit_replay/` |

For pooled trade attribution, every observation must retain `baseline_block`,
source-ledger hash, strategy hash, entry signal date, entry execution date, exit
signal date, and exit execution date. Portfolio/NAV statistics remain block- and
calendar-year-specific.

## Trade and outcome definitions

- A trade is one frozen engine completed position cycle reconstructed from the
  initial new-position buy through the completed-round-trip sell, including any
  intermediate resize realized P&L exactly once.
- Trade return, realized P&L, signal/execution dates, and exact exit lineage come
  from the frozen ledger/reconstruction semantics. Do not redefine them for a
  favorable attribution.
- Yearly trade cohorts are primarily assigned by exit execution year for realized
  P&L reconciliation. Entry-year cohorts are a separate diagnostic and must be
  labeled as such.
- Severe loss primary definition: completed-cycle return `<= -10%`. Report a
  sensitivity view at `<= -20%`; do not choose the cutoff after observing regime
  results.
- Top winner primary definitions: return `>= +20%`, `>= +50%`, and annual/global
  Top-10/Top-20 by realized P&L. No single definition may stand alone.
- MFE/MAE use the established observable post-entry path: daily high/low after the
  entry open and only the actual exit open on the exit session; no post-exit data.
- Exposure is end-of-day market-value invested fraction from authoritative NAV.
  Open-exit day attribution follows the existing frozen convention.
- Annual return and max drawdown are computed from the authoritative daily NAV
  subset for the calendar year, preserving the prior close/start value convention.
- Turnover uses authoritative filled notional relative to the matching NAV/capital
  convention and is reported with the exact formula in each experiment.

## Regime timestamp semantics

- Daily regime features are formed only from completed information available at
  or before a declared `decision_at`.
- Default entry attribution timestamp is the entry signal day's completed close.
  It describes information used for the next-session entry, never the later trade
  outcome.
- If a feature uses close `t`, its stored `feature_available_at` is no earlier than
  the completed close and its applicable execution is `t+1` or later.
- Universe-based cross-sectional features use the exact bounded date-specific
  membership applicable to that feature date and fail closed below declared
  coverage. Current survivors and future constituents/classifications are banned.
- Exit/path studies may use state at entry or each historical holding-day decision;
  future path variables are outcomes, never regime inputs.

## Data governance

- Primary daily stock facts: registered CY-006 within its exact frozen manifest,
  enforcing `available_at <= decision_at` and `hard_valid=true` before a row can
  add risk or form a required feature.
- Membership: CY-029 for the bounded 2017-2021 effective-state history, CY-028 for
  2022-2023, and CY-027 for 2024-2025. Their different lineage limitations remain
  explicit. None is strict archival PIT-A.
- Calendar: registered QD-003 exact exchange calendar.
- Corporate actions: QD-010/CY-006 bounded PIT-B causal contract.
- Anchor: exact frozen 399102.SZ completed daily series; no fallback to 399006.SZ,
  000852.SH, or another index.
- Style/industry/external-index inputs require separate registry evidence before
  formal use. If absent, record `UNAVAILABLE`, not a proxy substitution.

## Anti-overfitting and evaluation policy

- Existing 2018-2025 outcomes are already viewed. They may support mechanism
  research, but none is untouched OOS for a newly designed V1-R.
- Every new formal experiment receives an ID and a frozen spec before outcome
  analysis. The registry states whether it predates the relevant result.
- Start with continuous estimates and fixed quantiles/coarse bins. Thresholds must
  show neighboring robustness and cannot be selected solely for CAGR.
- Interactions require prior univariate/economic support; no exhaustive Cartesian
  search.
- Candidate overlays progress from exposure-only to entry gating, then exit
  adaptation only if holding-path evidence supports it.
- Candidate evaluation includes yearly stability, rolling/expanding views,
  leave-one-year-out threshold fitting, walk-forward where feasible, neighboring
  definitions, cost sensitivity, turnover, exposure normalization, top-winner
  capture, ex-best-N economics, and active falsification.
- Because all existing years are consumed, any final claim must distinguish
  resampling/LOYO evidence from genuine future OOS. Lack of untouched OOS caps the
  strength of deployability claims.

