# A-share Oversold Reversal Ranking V2 — Timing Report

## ENVIRONMENT

- Worktree: `/Users/linmei/Documents/CY-oversold-reversal-ranking`
- Branch: `research/oversold-reversal-ranking-v1`
- Starting HEAD: `bdd2c58d66dea7c4a5245031fd5a6002ccc2a047`
- Ending HEAD: the V2 checkpoint commit containing this report; its SHA is in the final
  handoff.
- Initial status: clean. Final status before checkpoint: only V2 research-lane files changed.

## V1 FROZEN FINDING

V1's authoritative verdict is `DEPTH_ONLY`. Large causal drawdown produced meaningful pooled
and de-duplicated mean reversion, while crash speed, market attribution, industry attribution,
and distance to low failed same-date/depth incrementality and daily ranking. V2 therefore
freezes depth as the carrier and studies timing only. It does not reopen stock selection,
volume exhaustion, or double-bottom research.

## FROZEN CARRIER

The exact V1 deepest quintile is retained as a research-faithful reference. Its edge was a
full-sample ex-post feature percentile at approximately `drawdown_60 <= -30.67%`, so it is not
a deployable signal.

The causal deployable V2 carrier was frozen before V2 outcomes as:

- the exact V1 LOW eligibility, liquidity, hard-valid, lineage, and proximity-to-low rules;
- causal adjusted-close drawdown from the trailing 60-session high <= -30% at t0 close.

The fixed -30% boundary was already documented as V1's deep region and closely maps the Q5
feature boundary without using future returns. It captures 168,408 of 184,816 valid deep
observations (91.12%) under the stricter Q5 reference. Because t0 is the first crossing after a
20-session deep-carrier cooldown, 16,468 of 22,543 valid t0 events (73.06%) are already beyond
-30.67% on recognition day; the rest become eligible slightly earlier. This is the intended
cost of causal real-time recognition, not an optimized conversion.

## EVENT COHORT

- Raw fixed-carrier observations: 201,673
- Raw 20-session de-duplicated deep events: 24,179
- Valid observations with legal immediate entry and clean 25-session path: 184,816
- Primary valid de-duplicated events: 22,543 across 4,836 securities and 128 PIT industries
- Primary event range: 2020-01-02 to 2026-07-08

The clean 25-session path ensures that a day-5 trigger can still have a complete 20-session
entry-anchored outcome. This is outcome-availability hygiene; carrier membership itself uses
only data known at t0.

## PRIMARY REVERSAL TRIGGER

The one outcome-blind trigger, frozen in `v2_timing_methodology.md` before the broad run, is
the first session in t0+1 through t0+5 satisfying:

1. `close > preclose`; and
2. `CLV = (close - low) / (high - low) >= 0.70`.

Zero-range days fail closed. The signal is known at trigger-day close and can enter only at
the following listed legal open. It represents a positive day that finishes in the top 30%
of its range—simple observable rejection of lower prices.

## SUPPORTING TRIGGERS

None. V2 deliberately avoids a trigger tournament or post-result combination.

## WAITING POLICY

The waiting window is five trading sessions after t0. Of 22,543 original opportunities:

- 19,375 trigger (85.95%); 19,338 execute (85.78% participation);
- 3,168 never trigger (14.05%); 37 trigger but the inherited next-open rules reject entry;
- mean/median trigger lag is 2.29/2 sessions.

| By session | Cumulative triggers | Executed | Cohort trigger rate |
|---:|---:|---:|---:|
| 1 | 6,823 | 6,810 | 30.27% |
| 2 | 12,330 | 12,309 | 54.70% |
| 3 | 15,480 | 15,453 | 68.67% |
| 4 | 17,900 | 17,866 | 79.40% |
| 5 | 19,375 | 19,338 | 85.95% |

## IMMEDIATE BASELINE

Entry-anchored results start at the next legal open after t0. N=22,543.

| Metric | Ret5 | Ret10 | Ret20 |
|---|---:|---:|---:|
| Mean | 1.13% | 2.28% | 4.41% |
| Median | 1.08% | 1.61% | 2.78% |
| Positive rate | 56.39% | 56.84% | 58.32% |

MFE20 is 15.02%, MAE20 -10.83%, Ret20 Q10 -12.74%, and 42.09% of trades reach MAE <=
-10%.

## FIXED-DELAY CONTROL

The fixed control observes t0+1 and enters at the following legal open irrespective of price
pattern. It executes 22,516 trades (99.88%). Entry-anchored mean/median Ret20 are 4.53%/2.90%,
hit rate 58.44%, MFE20 15.40%, and MAE20 -10.32%. Ret5 and Ret10 means are 1.62% and 2.52%.

At the common t0+20 endpoint, fixed delay produces 4.55% mean, 2.81% median, 58.39% positive
events, -10.14% mean MAE, and 38.73% severe-MAE incidence. It slightly improves mean and
downside versus immediate without a pattern filter.

## REVERSAL-TIMING POLICY

### Entry-anchored executed trades

These 19,338 trades are future-conditioned by eventual trigger and are trade-quality
diagnostics, not the primary policy comparison.

| Metric | Ret5 | Ret10 | Ret20 |
|---|---:|---:|---:|
| Mean | 2.23% | 2.26% | 5.18% |
| Median | 1.52% | 1.96% | 3.57% |
| Positive rate | 59.65% | 58.08% | 59.70% |

MFE20 is 15.55% and MAE20 -9.00%. Executed trades look better than immediate trades, but that
conditional comparison cannot establish policy value.

### Event-anchored full cohort

Every one of the 22,543 original t0 events remains. Executed trades exit at the same t0+20
adjusted close as immediate; nonparticipating events earn 0% cash.

The reversal policy produces 3.86% mean Ret20, 0.43% median, 50.99% positive-event rate,
-7.36% mean event MAE, and 27.01% severe-MAE incidence. Waiting therefore lowers full-cohort
return and median but materially reduces downside.

## FAIR POLICY COMPARISON

This is the central causal comparison over the same 22,543 opportunities and common endpoint.

| Policy | Trades | Participation | Mean R20 | Median R20 | Positive events | Q10 R20 | Q25 R20 | Mean MAE | Severe MAE | Mean lag |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Immediate | 22,543 | 100.00% | 4.41% | 2.78% | 58.32% | -12.74% | -5.71% | -10.83% | 42.09% | 0.00 |
| Fixed delay 1 | 22,516 | 99.88% | 4.55% | 2.81% | 58.39% | -12.37% | -5.44% | -10.14% | 38.73% | 1.00 |
| Reversal wait | 19,338 | 85.78% | 3.86% | 0.43% | 50.99% | -10.95% | -3.73% | -7.36% | 27.01% | 2.29 |

Versus immediate, reversal wait sacrifices 0.56 percentage points of mean Ret20 and 2.35
points of median, while improving mean MAE by 3.47 points and severe-MAE incidence by 15.08
points. Severe Ret20 incidence falls from 14.89% to 11.59%. This is downside filtering, not
overall opportunity-return enhancement.

## WAITING COST

Among executed reversal entries:

- delayed entry is 1.28% above the immediate entry on average and 1.68% higher at the median;
- 68.51% enter at a higher price;
- immediate-entry MFE before delayed entry averages 3.67%;
- 25.19% have already offered at least +5% MFE before confirmation;
- the pre-entry move interquartile range is -0.86% to +4.11%.

The trigger usually arrives quickly, but confirmation still pays away a material part of
V-shaped rebounds.

## NO-TRIGGER EVENTS

The 3,168 no-trigger events remain cash under reversal wait. Their immediate-entry
counterfactual is:

| Metric | Ret5 | Ret10 | Ret20 |
|---|---:|---:|---:|
| Mean | -7.75% | -4.91% | -3.64% |
| Median | -5.33% | -5.20% | -4.83% |
| Positive rate | 15.06% | 25.22% | 33.71% |

MFE20 is 8.65%, MAE20 -16.47%, Ret20 Q10 -17.62%, and 69.16% reach MAE <= -10%. Waiting
correctly avoids a materially worse falling-knife cohort. The diagnostic is future-conditioned
and does not replace the full policy comparison.

No-trigger filtering is imperfect: 11.62% would still finish above +10%, and 28.09% offer at
least +10% MFE. Confirmation discards some strong rebounds along with the falling knives.

## FALLING-KNIFE RISK

On the full event cohort, reversal wait improves mean MAE from -10.83% to -7.36%, Q10 return
from -12.74% to -10.95%, severe MAE from 42.09% to 27.01%, and severe terminal loss from
14.89% to 11.59%. Improvements remain when looking only at executed entries: MAE improves to
-9.00% and severe MAE to 34.01%.

Fixed delay provides only modest protection (MAE -10.14%, severe MAE 38.73%). The specific
trigger contains useful downside-filter information even though it does not add expected
opportunity return.

## V-SHAPED REBOUND COST

Confirmation enters after an average 3.67% pre-entry MFE and a median 1.68% price rise. One
quarter of executed events have already shown +5% MFE. This missed left-side convexity explains
why conditional triggered trades improve while full-cohort mean and median deteriorate.

The cost is especially visible in extreme drawdowns: their delayed entry is 2.62% higher on
average and reversal wait loses 2.33 points of event Ret20 versus immediate.

## FIXED-DELAY ATTRIBUTION

The specific trigger does **not** beat simply waiting one session on return. Fixed delay's
common-horizon mean/median are 4.55%/2.81%, versus 3.86%/0.43% for reversal wait. Reversal wait
also trails fixed delay by 0.69 mean-return points.

The trigger does beat fixed delay on risk: mean event MAE improves from -10.14% to -7.36% and
severe-MAE incidence from 38.73% to 27.01%. Passage of time explains the small return benefit
of fixed delay; the pattern's incremental role is aggressive downside selection.

## DEPTH INTERACTION

| Frozen depth subgroup | N | Trigger rate | Reversal-Immediate R20 | Reversal-Fixed R20 | Median difference | MAE improvement | Severe-MAE change | Pre-entry move |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| -30% to -40% | 21,232 | 85.84% | -0.45% | -0.63% | -2.31% | +3.53% | -15.18 pp | 1.19% |
| <= -40% | 1,311 | 87.72% | -2.33% | -1.62% | -3.81% | +2.57% | -13.50 pp | 2.62% |

Risk filtering exists in both frozen subgroups. Return sacrifice is larger in the extreme
group, so V2 does not support waiting only for the deepest events.

## TIME STABILITY

| Period | N | Trigger rate | Reversal-Immediate R20 | Reversal-Fixed R20 | Median difference | Entry R20 difference | Event MAE improvement | Severe-MAE change |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2020 | 2,342 | 85.48% | -1.09% | -0.61% | -0.81% | +0.18% | +1.61% | -7.09 pp |
| 2021-2023 | 9,183 | 85.49% | -0.82% | -0.84% | -2.29% | -0.14% | +2.08% | -9.56 pp |
| 2024-2026 | 11,018 | 86.42% | -0.22% | -0.58% | -1.86% | +1.62% | +5.04% | -21.38 pp |

Reversal wait loses common-horizon return to both immediate and fixed delay in every block.
Downside improves in every block but varies materially in magnitude, becoming strongest after
2024. The stable sign supports risk filtering; the regime-varying size argues against treating
it as a finished overlay.

## LIQUIDITY / INDUSTRY SANITY

Across coarse liquidity thirds, reversal-minus-immediate event Ret20 is +0.22%, -0.83%, and
-1.01%; reversal trails fixed delay in all three. Event MAE improves by 4.88%, 2.95%, and
2.67%, and severe-MAE incidence falls by 19.03, 13.61, and 12.81 points. The risk effect is not
an illiquidity-only artifact, though return sacrifice is weakest in the least-liquid group.

The largest PIT industry is only 4.64% of events. Among 98 industries with at least 50 events,
only 23.47% have positive reversal-minus-immediate event return. The ten largest industries
mostly show negative return differences and positive MAE improvement. No single industry
drives the central result.

The repeated-state supporting sample agrees: reversal event Ret20 is 2.89% versus 3.36% for
immediate, while mean MAE improves from -10.65% to -7.46%. The primary conclusion therefore
survives the economically distinct de-duplicated cohort.

## ECONOMIC INTERPRETATION

**Evidence:** price confirmation identifies a much better conditional trade cohort and filters
events that otherwise suffer severe continued decline. It does not improve full-cohort mean,
median, or hit rate and loses return to a one-session mechanical delay.

**Interpretation:** part of deep-oversold alpha compensates investors for buying before visible
confirmation. Waiting buys meaningful protection from falling knives, but pays for it through
cash nonparticipation and higher entry prices after V-shaped rebounds have begun.

**Speculation:** a staged exposure policy may preserve some left-side convexity while reserving
additional risk for confirmed demand return. V2 does not test sizing, costs, or staged entry.

## VERDICT

`RISK_FILTER_ONLY`

Right-side waiting is not a superior standalone entry policy: it reduces mean and median
opportunity value and does not beat fixed delay on return. Its downside improvement is large,
broad, and economically real, while no-trigger events are demonstrably worse falling knives.
The trigger deserves consideration only as a risk overlay, not as a replacement carrier or
return-enhancing confirmation rule.

## SINGLE NEXT STEP

Test one frozen **staged-entry risk overlay**: take partial immediate exposure at t0 and add the
remaining exposure only after the unchanged V2 trigger, then judge common-horizon return,
downside, and costs. Do not search new triggers or reopen carrier selection.
