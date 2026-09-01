# A-Share Deep-Oversold Portfolio V6

## 1. EXECUTIVE CONCLUSION

V6 finds a real cluster-intensity signal but rejects the preregistered date-by-date capital
translation as a stable repair for V5. Signal count has a positive association with future
date-basket return (Spearman `0.111`; Pearson `0.142`), and the highest descriptive count-rank
fifth contains `97.92%` of summed event return. Its mean basket return is `+1.85%`, versus
negative means in the lowest three fifths.

The count-aware gross portfolio ends at `1.0196`, above the exactly reproduced V5 Equal Gross
control at `1.0016`; max drawdown improves from `-44.35%` to `-39.84%`. That apparent repair is
not historically stable. V6 underperforms in `2018-2020` and `2024-2026`; the entire full-period
advantage is supplied by `2021-2023`. The fixed rule requests far more capital than a 20-session
overlapping portfolio can supply: `71.33%` of desired notional is blocked overall and `87.39%`
is blocked on the highest-count fifth. It enters only `19,479` of `22,357` signals because
`2,878` arrive when cash is zero.

**Verdict: `CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS`.**

## 2. ENVIRONMENT / COMMIT / VALIDATION

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `0850fbc8cc3bdcdb0fdd5acc1abe23117084185b`
- Starting status: clean
- V5 Equal Gross control reproduction: exact, maximum reported-field difference `0.0`
- Certified input hashes: all verified
- Result invariants: all zero
- Primary basis: gross, zero transaction costs
- Checkpoint: created only after the report, machine output, tests, and diff are validated

Chronology checks cover prior-date-only `M_t`, neutral warm-up, next-open entry, legal exit,
fixed holding, cash non-negativity, no leverage, NAV identity, and entry/exit reconciliation.

## 3. FROZEN RESEARCH HISTORY

| Version | Verdict | Authoritative finding |
|---|---|---|
| V1 | `DEPTH_ONLY` | Deep drawdown is the stock-level mean-reversion carrier. |
| V2 | `RISK_FILTER_ONLY` | Reversal confirmation lowers risk but does not add return alpha. |
| V3 | `SIZING_SIGNAL_ONLY` | t0 price state predicts falling-knife risk, but not a hard veto. |
| V4 | `SIZING_SURVIVES` | Risk sizing improves event-level arithmetic. |
| V5 | `EVENT_ALPHA_COLLAPSES` | Event alpha fails finite-capital overlapping NAV translation. |

V6 does not reopen any carrier, stock selector, volume thesis, risk score, entry, or exit rule.
The V3/V4 score is scientifically frozen but inactive; every same-date stock receives an equal
share.

## 4. V5 FAILURE MECHANISM

The reused executable event return remains `+4.3191%` on average, but the equal-date basket mean
is only `+0.2637%`. V5 gives each active date at most approximately 5% new capital, whereas an
event-weighted statistic implicitly gives a date weight proportional to its event count.
Because `74.44%` of events occur on dates with more than 20 signals, the change from event
weighting to date/capital weighting almost eliminates the event-level mean.

V5 Equal Gross ending NAV was already `1.0016`, so costs were not the primary V5 failure. V6
therefore tests the gross allocation mechanism directly.

## 5. V6 HYPOTHESIS

The single hypothesis is that large simultaneous frozen signal counts identify stress dates
with more aggregate forward opportunity. If so, holding total date budget near 5% mechanically
underweights the dates carrying event alpha.

No count threshold, multiplier grid, return conditioning, new feature, alternate holding period,
leverage, or cost scenario is tested.

## 6. CAUSAL CAPITAL-BUDGET CONTRACT

For entry date `t`, `N_t` is the number of frozen events scheduled for that legal entry open.
Every constituent signal was completed at a prior t0 close. `M_t` is the median positive count
across strictly prior active entry dates; zero-count dates and the current date are excluded.

For the first 60 prior active dates, desired capital is neutral at `5% * opening NAV`. Afterward:

`desired_t = 5% * opening_NAV_t * (N_t / M_t)`

`actual_t = min(desired_t, available_cash_t)`

Same-open legal exits update cash before entries, exactly as in V5. Actual capital is split
equally over executable signals. Unused cash remains cash; no borrowing, leverage, forced sale,
or synthetic tranche roll-forward is allowed.

## 7. CONTROL REPRODUCTION

| Metric | Authoritative V5 | V6 reproduction | Difference |
|---|---:|---:|---:|
| Ending NAV | 1.0016248465 | 1.0016248465 | 0.0 |
| CAGR | 0.0256% | 0.0256% | 0.0 pp |
| Annualized volatility | 23.3198% | 23.3198% | 0.0 pp |
| Max drawdown | -44.3500% | -44.3500% | 0.0 pp |
| Average exposure | 76.7385% | 76.7385% | 0.0 pp |
| Entries | 22,357 | 22,357 | 0 |

This exact bridge is the prerequisite for interpreting the treatment.

## 8. SIGNAL-COUNT DISTRIBUTION

The frozen sample runs from signal date `2020-01-02` through `2026-07-08`: `22,357` events,
`4,835` securities, and `1,228` active entry dates.

| Statistic | N_t |
|---|---:|
| Mean | 18.21 |
| Median | 5 |
| p75 | 14 |
| p90 | 36.3 |
| p95 | 77.65 |
| p99 | 234.33 |
| Maximum | 674 |

| Descriptive regime | Active dates | Share of active dates |
|---|---:|---:|
| 1 | 197 | 16.04% |
| 2-5 | 435 | 35.42% |
| 6-10 | 210 | 17.10% |
| 11-20 | 175 | 14.25% |
| >20 | 211 | 17.18% |

Dates above 20 signals are only `17.18%` of active dates but contain `74.44%` of events.

## 9. COUNT -> FORWARD BASKET RETURN

Across `1,228` active dates, `N_t` versus equal-weight executable basket return has Spearman
`0.1110` and Pearson `0.1424`. The overall date-basket mean is `+0.2637%`, median `-0.4506%`, and
positive-date rate `47.96%`; mean date-level basket MAE20 is `-9.98%`.

| Count-rank fifth | Dates | Events | Count range | Mean basket Ret | Median | Positive | Mean MAE20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Q1 | 246 | 295 | 1-2 | -0.342% | -1.626% | 42.68% | -10.10% |
| Q2 | 246 | 641 | 2-4 | -0.500% | -0.948% | 45.93% | -9.29% |
| Q3 | 246 | 1,309 | 4-7 | -0.150% | -1.089% | 44.31% | -9.89% |
| Q4 | 245 | 2,827 | 7-17 | +0.466% | -0.053% | 49.80% | -10.03% |
| Q5 | 245 | 17,285 | 17-674 | +1.851% | +1.417% | 57.14% | -10.56% |

Fifths contain approximately equal numbers of dates; count ties are broken by date only for this
descriptive table. The ordered improvement is concentrated in Q4-Q5, while downside MAE does not
improve—large clusters are higher-return stress baskets, not safer baskets.

## 10. EVENT-ALPHA CONTRIBUTION BRIDGE

The event-weighted executable mean is `+4.3191%`, but the date-weighted mean is `+0.2637%`.
Mathematically, the former weights date `t` by `N_t`; the latter gives every active date weight
`1/1,228`. Q5 contains `77.31%` of events, `97.92%` of summed event return, and `84.84%` of all
positive-event return contribution. The other four fifths together contribute only `2.08%` of
summed event return.

This establishes the proposed cluster-concentration mechanism descriptively. It does not by
itself establish that a finite-capital portfolio can buy the implicit event weights.

## 11. GROSS PORTFOLIO COMPARISON

| Metric | V5 Equal Gross | V6 Count-Aware Gross |
|---|---:|---:|
| Starting NAV | 1.0000 | 1.0000 |
| Ending NAV | 1.0016 | 1.0196 |
| Cumulative return | +0.16% | +1.96% |
| CAGR | +0.03% | +0.31% |
| Annualized volatility | 23.32% | 22.26% |
| Max drawdown | -44.35% | -39.84% |
| Sharpe-like | 0.118 | 0.125 |
| Calmar | 0.0006 | 0.0077 |
| Average exposure | 76.74% | 70.76% |
| Median / max exposure | 84.76% / 100.00% | 85.00% / 100.00% |
| Average / minimum cash ratio | 23.26% / 0.00% | 29.24% / 0.00% |
| Annualized turnover | 19.34x | 17.74x |
| Trades | 22,357 | 19,479 |
| Active entry dates | 1,228 | 1,228 |
| Average / max positions | 280.1 / 3,354 | 244.1 / 3,234 |
| Average largest-position weight | 4.67% | 1.46% |
| Average top-5 concentration | 17.43% | 6.35% |

The treatment gains `1.80` ending-NAV points and reduces max drawdown by `4.51` percentage
points, but its CAGR remains only `0.31%` gross. Lower average exposure and fewer entered trades
explain part of the risk reduction; this is not a stable restoration of the original event mean.

| Year | Control | V6 |
|---|---:|---:|
| 2020 | -1.40% | -2.65% |
| 2021 | +11.75% | +16.62% |
| 2022 | -19.47% | -16.90% |
| 2023 | +8.36% | +11.93% |
| 2024 | -9.72% | -13.08% |
| 2025 | +23.33% | +27.96% |
| 2026 partial | -6.43% | -13.19% |

The control's largest drawdown (`2020-07-14` to `2024-02-05`) is `-44.35%`; V6 loses `-38.30%`
over the same interval. In the `2026-05-11` to `2026-07-24` control drawdown, however, V6 is
worse (`-24.55%` versus `-22.24%`).

## 12. CAPITAL SATURATION ANALYSIS

V6 wants more than the control budget on `45.28%` of active dates and less on `44.14%`; the
remaining warm-up/equal-median dates are neutral. Cash binds on `35.75%` of active dates.

| Budget diagnostic | All active dates | Highest count-rank fifth |
|---|---:|---:|
| Desired notional sum | 196.184 NAV units | 145.613 |
| Blocked notional sum | 139.934 | 127.250 |
| Fraction requested blocked | 71.33% | 87.39% |
| Cash-constrained date frequency | 35.75% | 86.53% |

Actual deployed notional is only `56.249` NAV units. Zero cash prevents `2,878` signals
(`12.87%`) from entering. The highest count-rank fifth generates `0.2712` gross realized P&L,
while the whole portfolio makes only `0.0196`; its formal P&L share exceeds 100% because lower
count dates lose money. This is economically consistent with the basket bridge, but also shows
why the naive `N_t/M_t` request cannot be interpreted as deployed exposure.

Average opening-NAV allocation per entered stock falls with count: `1.330%` at N=1, `0.958%`
at N=2-5, `0.812%` at N=6-10, `0.571%` at N=11-20, and `0.114%` above 20. Even an aggressive
total desired budget therefore cannot reproduce event weighting during the largest clusters.

## 13. HISTORICAL STABILITY

| Block | Active dates | Signals | Spearman | Control gross | V6 gross | V6-control | V6 exposure | Cash binds |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2018-2020* | 171 | 2,238 | +0.121 | -1.40% | -2.65% | -1.24 pp | 68.44% | 34.50% |
| 2021-2023 | 625 | 9,149 | +0.208 | -2.48% | +8.47% | +10.96 pp | 77.36% | 33.12% |
| 2024-2026 | 432 | 10,970 | -0.005 | +4.18% | -3.45% | -7.63 pp | 64.02% | 40.05% |

\*The frozen V5 cohort begins in 2020, so the first block contains 2020 observations only.

Count-return direction is positive in the first two blocks but absent by Spearman in the latest
block. Portfolio improvement occurs only in 2021-2023. The full-period gain is therefore regime
concentrated, failing the requirement that capital translation not be dominated by one episode.

## 14. FAILURE / SUCCESS MECHANISM

The successful part of the hypothesis is the cross-date diagnosis: deep-oversold events arrive
in highly skewed clusters, and high-count dates carry nearly all positive event contribution.
The failed part is direct daily capital translation. High-count dates are consecutive stress
episodes, not independent opportunities. Existing 20-session lots consume cash before later
dates in the same episode arrive. The rule consequently asks for capital precisely when the
portfolio is saturated, misses some dates entirely, and produces regime-dependent timing bets.

The result does not justify leverage, a shorter hold, count thresholds, or a tuned multiplier.
Those would be new hypotheses. It also does not revive V3/V4 stock sizing, technical indicators,
or volume research.

## 15. EXACT VERDICT

`CLUSTER_SIGNAL_EXISTS_BUT_CAPITAL_TRANSLATION_FAILS`

High count credibly identifies stronger forward date baskets and explains event-alpha
concentration. The preregistered `N_t/M_t` portfolio improves full-period gross NAV and drawdown,
but the improvement is small in absolute compounding terms, absent in two of three broad blocks,
and constrained by severe capital saturation. It therefore does not meet the stability standard
for `CLUSTER_CAPITAL_TRANSLATION_SURVIVES`.

## 16. SINGLE HIGHEST-VALUE NEXT FRONTIER

Run one preregistered cluster-episode portfolio study that aggregates consecutive high-count
entry dates into a single stress episode with one fixed finite-capital envelope, without
leverage, stock selection, or parameter search.

Do not execute it automatically.
