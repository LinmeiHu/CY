# External strategy prior map — cycle-005 checkpoint classifications

This outcome ledger updates the research status of the immutable pre-outcome
definitions in `STRATEGY_PRIOR_MAP.md`. The frozen map remains byte-stable
because the experiment specification binds its SHA-256. External source
performance is not trusted or reasserted here; classifications apply only to the
disclosed A-share implementation tested on consumed 2018--2023 development data.

| Prior | Local implementation | Coverage | Net screen evidence | Severe-loss evidence | Executability | Classification |
|---|---|---:|---|---|---|---|
| EXT-JT-MOM-001 | Long top-20 12-minus-1-month momentum; monthly; h120 | 1,048 complete positions / 59 dates | -5.183% full; -0.588% / -8.919% blocks | +35.878 pp disadvantage | >=90% next-open | `ADVERSE_LONG_LEG_FORMULATION`; no replay |
| EXT-GH-52W-001 | Long top-20 price/action-coordinate 252-session high; monthly; h120 | 979 / 59 | -4.597%; +0.381% / -8.661% | +29.418 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-MG-INDMOM-001 | PIT leave-one-out equal-weight industry r120; monthly; h120 | 1,055 / 59 | +0.250%; +0.919% / -0.303% | +26.161 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-BCW-MAX-001 | Long top-20 negative prior-20-session MAX; monthly; h20 | 1,175 / 59 | -1.185%; -2.229% / -0.474% | +2.553 pp | >=90% | `ADVERSE_LONG_LEG_FORMULATION`; no replay |
| EXT-MIWA-INTRAREV-001 | Long lowest five-session open-to-close return; weekly; h5 | 4,790 / 241 | -0.070%; -0.192% / +0.011% | +7.265 pp | >=90% | `CHRONOLOGICALLY_MIXED`; no replay |
| EXT-AMIHUD-ILLIQ-001 | Canonical annual illiquidity characteristic not changed to monthly | Not run | Not estimated | Not estimated | Not tested | `CANONICAL_REPLICATION_DEFERRED_NOT_SILENTLY_ADAPTED` |
| EXT-FP-BAB-001 | Canonical beta-neutral leveraged long/short | Not run | Not estimated | Not estimated | Short/leverage conflict | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-GGR-PAIRS-001 | Canonical 12-month formation / six-month long-short pairs | Not run | Not estimated | Not estimated | Short/borrow conflict | `A_SHARE_IMPLEMENTATION_CONFLICT` |
| EXT-BHM-RESMOM-001 | Canonical PIT factor-residual momentum | Not run | Not estimated | Not estimated | Registered factors absent | `DATA_UNAVAILABLE` |
| EXT-CRW-PRCLIM-001 | Existing exact A-share long limit-up-aftermath h5 | Not rerun | Previously adverse | Previously adverse | Previously screened | `EXISTING_EXACT_FORMULATION_ADVERSE_NO_RERUN` |

No result above establishes that the published prior is false. Long-only local
screens omit canonical short legs where disclosed, industry momentum substitutes
equal weighting for value weighting, and the five-test screen is development
replication evidence rather than independent confirmation.

## Cycle-006 fundamental prior readiness

| Prior family | Canonical data requirement | Readiness decision | Economic classification |
|---|---|---|---|
| Book-to-market | Historically published book equity plus causal market capitalization | No revision-aware book-equity history | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Earnings yield | Historically published earnings plus causal market capitalization | Current/restated EPS snapshot cannot establish original values | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Cash-flow yield | Historically published operating cash flow plus causal capitalization | Current/restated OCF snapshot cannot establish original values | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Profitability | Publication-aware gross/operating profitability with consistent periods | ROE/margin fields lack revision and period-unit lineage | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Investment / asset growth | Comparable statement assets from consecutive causal vintages | Balance-sheet values unavailable | `DATA_UNAVAILABLE_NOT_TESTED` |
| Small quality | Profitability, cash quality, and leverage from the same causal statement vintage | Leverage absent and remaining fields not revision-aware | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Accruals | Comparable balance-sheet/income/cash-flow statements from causal vintages | Required statements unavailable | `DATA_UNAVAILABLE_NOT_TESTED` |
| Fundamental growth / improvement | Comparable original-release values across causal report vintages | Current snapshot does not preserve original releases | `PIT_FUNDAMENTAL_DATA_BLOCKED_NOT_TESTED` |
| Quality + value | Standalone quality and value evidence first | Neither standalone component is lawfully testable | `COMBINATION_NOT_AUTHORIZED` |

These are data-readiness outcomes, not adverse or null alpha results. No external
fundamental performance claim, A-share return estimate, or conservative-lag
adaptation exists for cycle 006.

## Cycle-008 long-only-compatible prior/internal batch

| Family | Mechanism | Screen evidence | Executable evidence | Classification |
|---|---|---|---|---|
| Low return skewness 60 | Avoid lottery-like positive skew | Original +0.127% h5; same-date rho with Low Idio 0.177; residual -0.085%, -0.806%/+0.538% | No standalone replay authorized | `COMPLEMENTARY_DEFENSIVE_INFORMATION` |
| Confirmed L20 breakdown | Avoid new admissions already below objective prior support | Prior -0.344% h5 downside relation | CHINEXT admission veto affected 0/645 candidates; all metrics unchanged | `PARKED_NO_AFFECTED_DECISIONS` |
| Low volatility-of-volatility 60 | Prefer stable rather than episodic realized risk | +0.831% h20; +0.274%/+1.321%; -15.600 pp severe disadvantage | +4.37% total, -20.32% DD, 0.128 Sharpe, 1.07% severe, HHI 0.419 | `PROMISING_BUT_MIXED` |
| Residual Sharpe 60 | Stock-specific return quality per unit residual risk | +0.222% both blocks; +9.250 pp severe losses | No replay | `ECONOMICALLY_NULL` |
| Down/up residual asymmetry 60 | Resilience on market-down versus up days | -1.162%, adverse both blocks | No replay | `ADVERSE` |
| Negative-gap absorption rate 60 | Repeated absorption of negative gaps | +0.335%, -0.476%/+1.028%; +1.822 pp severe | No replay | `CHRONOLOGICALLY_MIXED` |
| Close-location persistence 20 | Repeated close-in-range strength | +0.354%, -0.671%/+1.237%; +6.613 pp severe | No replay | `CHRONOLOGICALLY_MIXED` |

No combination, neighboring definition, second breakdown role, post-2023 data,
or CY-011 input was used. These are consumed-history discovery results, not
independent confirmation.

## Cycle-009 defensive audit and return-engine batch

| Family | Source/mechanism | Complete / dates | Net excess | Early / late | Severe disadvantage | Classification |
|---|---|---:|---:|---:|---:|---|
| Low Vol-of-Vol residual to Low Idio | Frozen defensive distinctness audit | broad top-20 / 66 | -0.194% | +1.395% / -1.599% | diagnostic | `COMPLEMENTARY_LOW_RISK_INFORMATION`; park, no replay |
| FIP continuous good news 60 | Da, Gurun, Warachka continuous information | 1,307 / 66 | -0.786% | -0.173% / -1.334% | +3.966 pp | `ADVERSE` |
| Same-month seasonality 1y | Heston-Sadka recurring calendar-month return | 1,174 / 59 | -1.841% | -2.073% / -1.682% | +3.275 pp | `ADVERSE` |
| Market-relative rank acceleration 20 | Emerging peer-relative demand | 1,289 / 65 | -1.260% | -0.337% / -2.055% | +12.293 pp | `ADVERSE` |
| Industry-follower acceleration 20 | Leader/follower diffusion | 1,286 / 65 | -0.835% | -0.438% / -1.173% | +8.169 pp | `ADVERSE` |
| Overnight/daytime tug-of-war 20 | Repeated positive night / negative day reversals | 1,313 / 66 | -0.002% | +0.522% / -0.468% | -4.366 pp | `CHRONOLOGICALLY_MIXED` |
| Low turnover attention 60 | Lee-Swaminathan neglected/value-like attention | 1,313 / 66 | +0.076% | -0.011% / +0.153% | -16.247 pp | `CHRONOLOGICALLY_MIXED` |

The within-industry Low Vol-of-Vol high-minus-low diagnostic is +1.198% full,
+1.730%/+0.833% by block, with -12.681 pp severe-loss spread. That establishes
a stock-level low-risk manifestation after controlling industry composition,
not independence from Low Idio or strategy usefulness. No Track-B family is
promoted and no executable replay is run. The frozen minute-overlap statistic
is non-identifying; it is not replaced after outcomes.

## Cycle-010 evidence-backed depth

| Family | Source-faithful local definition | Full net ordering | Early / late | Long-leg economics | Classification |
|---|---|---:|---:|---|---|
| Revised momentum 12m/1m | Sum causal log returns excluding historical upper-limit closes and their next stock session; monthly deciles | revised top-minus-bottom +0.353% vs conventional -0.393%; correction +0.747 pp | revised +3.230% / -1.178% | top +0.029% net, -0.218% excess, severe disadvantage +5.236 pp | `CHRONOLOGICALLY_UNSTABLE`; mechanism improvement replicated, no replay |
| Revised momentum 6m/1m | Same correction, paper-specified representative sensitivity | +0.319% vs -1.330%; correction +1.648 pp | +3.265% / -1.252% | full top +0.116% | confirms construction effect, not chronology |
| Revised momentum 9m/1m | Same correction, paper-specified representative sensitivity | +0.012% vs -1.341%; correction +1.353 pp | +2.993% / -1.576% | full top -0.183% | confirms construction effect, not chronology |
| Wan MAX | Prior-20-session maximum causal daily return; monthly quintiles | Low-minus-High +0.637% | +0.501% / +0.711% | Low leg +0.238% net, -0.020% excess, -4.911 pp severe disadvantage | `MECHANISM_CONFIRMED_LONG_LEG_WEAK`; defensive tail benefit, no replay |
| Wan MIN | Prior-20-session minimum causal daily return; monthly quintiles | Low-minus-High +0.041% | -0.072% / +0.099% | Low leg +0.227% net, -0.038% excess | `CHRONOLOGICALLY_UNSTABLE`; no replay |
| Wan canonical IVOL × MAX/MIN | Four-factor residual volatility using PIT RMRF/SMB/HML/WML | Not run | Not run | Not run | `DATA_BLOCKED`; existing Low Idio is not substituted |
| Residual momentum / left-tail reversal | Exact source factor residual / exact published tail construction | Not run | Not run | Not run | `DATA_BLOCKED`; no invented proxy |

The unique paper main-table horizon/weighting was not exposed by accessible
original-source text. The 12m/1m equal-weight cell is therefore labeled a
paper-specified representative primary design, not falsely asserted as the
paper's unique main cell. Existing adverse JT Top-20 and MAX Top-20 results are
preserved unchanged.
