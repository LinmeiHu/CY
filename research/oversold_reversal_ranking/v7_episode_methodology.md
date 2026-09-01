# A-Share Deep-Oversold Portfolio V7 Methodology

## Scope

V7 is the final planned architecture test for translating the frozen deep-oversold event effect
into a finite-capital portfolio. It tests one outcome-blind hypothesis: consecutive high-count
entry dates form one stress episode and should share one cumulative capital envelope.

V7 does not alter the carrier, event stream, stock selection, price chronology, 20-session lot
holding, or execution controls. The V3/V4 risk score is inactive and within-date allocation is
equal weight.

## Frozen upstream contract

V7 imports the exact V5/V6 event and price tables:

- V1 LOW plus causal 60-session adjusted-close drawdown `<= -30%`;
- first deep-carrier observation after no deep-carrier observation in the prior 20 security rows;
- t0-close formation and inherited next listed legal-open entry;
- corporate-action-safe adjusted open `adjusted_close * open / close`;
- normalized adjusted units, daily adjusted-close marks, and true cash/NAV accounting;
- hold t0+1 through t0+20 and sell at the first legal open on or after t0+21; and
- long-only, no leverage, no borrowing, no forced liquidation.

Primary analysis is gross of transaction costs. V5 Equal Gross and V6 Count-Aware Gross are
rerun from the same in-memory inputs and must reproduce their authoritative results exactly.

## Causal intensity

V7 reuses V6's authoritative entry-date normalization. For legal entry date `t`, `N_t` is the
number of frozen events scheduled for that open. All constituents have signal dates strictly
before entry, so the full count is known before allocation. `M_t` is the median positive count
across strictly prior active entry dates. The current count is appended only after its state has
been assigned; zero-count dates are absent.

For fewer than 60 prior active dates, V6's neutral warm-up sets `I_t = 1`. Thereafter
`I_t = N_t / M_t`. A date is high intensity only when `I_t > 1`; warm-up dates therefore cannot
start or consume an episode.

The recorded episode signal-start date is the latest t0 signal date among the events scheduled
for the episode-start entry open. This is the date by which every constituent needed for `N_t`
is known. It is always strictly earlier than the entry session.

## Episode lifecycle

An episode starts on a high-intensity entry date when no episode is active. Its first legal entry
session is lifecycle session 1. It remains active for exactly 20 market-calendar sessions,
through session 20 inclusive. No other episode can start during those sessions. A high-intensity
date on the following market session may start a new episode. Low-intensity dates neither start
an episode nor receive capital.

Delayed legal exits may leave earlier lots open after an episode expires; they do not extend the
episode. True cash and position overlap continue to govern later deployment.

## Frozen episode envelope and deployment

At the episode's first open, before same-open exits, freeze `EpisodeStartNAV`. After legal exits,
record `EpisodeStartCash` as the available cash immediately before the first episode entry.

`EpisodeEnvelope = EpisodeStartNAV`.

For each high-intensity active date:

- `RawRequest_t = 0.05 * EpisodeStartNAV * I_t`;
- `RemainingEnvelope_t = EpisodeEnvelope - cumulative actual deployment`;
- `EpisodeRequest_t = min(RawRequest_t, RemainingEnvelope_t)`;
- `Deployed_t = min(EpisodeRequest_t, available cash)`; and
- deployed capital is split equally among all executable frozen events on that date.

Only actual deployment consumes the envelope. Cash-blocked capital remains conceptually
available for a later high-intensity date in the same episode. Any unused envelope disappears at
episode expiry and never rolls forward. The envelope is a cap, not a second cash account or a
promise to invest.

Low-intensity signals inside or outside an episode receive zero by architecture. These are
reported separately from high-intensity signals that receive zero because true cash is empty.
Partial positive deployment gives every same-date executable event the same positive allocation.

## Frozen diagnostics

Episode P&L is the realized gross P&L of lots entered by that episode, including exits after the
episode lifecycle. Episode gross return is that P&L divided by EpisodeStartNAV. Episode drawdown
is the minimum portfolio NAV drawdown from a running peak over the 20 lifecycle sessions,
anchored by EpisodeStartNAV.

Episode equal-weight forward basket return is the mean authoritative V5 executable gross return
for all high-intensity events assigned to the episode, whether or not cash allowed V7 entry. A
supporting all-active-date episode basket also includes low-intensity events occurring during the
lifecycle.

"Highest intensity" saturation means the descriptive top fifth of high-intensity dates sorted by
`(I_t, entry date)`. It is outcome-blind and never changes allocation. Lifecycle-session tables
for sessions 1-20 are descriptive only.

Episode P&L concentration uses positive realized P&L: shares from the top one, top five, and top
10% of profitable episodes. Broad stability blocks remain `2018-2020`, `2021-2023`, and
`2024-2026`, assigned by episode-start entry date.

## Decision standard

`EPISODE_PORTFOLIO_SURVIVES` requires meaningful gross NAV and risk-adjusted improvement over
both controls, materially better saturation, and gains across broad periods. Coherent episodes
without robust portfolio economics imply `EPISODE_STRUCTURE_EXISTS_BUT_NOT_INVESTABLE`.
Failure to improve the bottleneck or stability implies `EPISODE_ARCHITECTURE_FAILS`.
`INCONCLUSIVE` is reserved for data, chronology, execution, or implementation limitations.

No weak result may trigger an alternative episode length, threshold, envelope, holding period,
leverage rule, or stock selector.
