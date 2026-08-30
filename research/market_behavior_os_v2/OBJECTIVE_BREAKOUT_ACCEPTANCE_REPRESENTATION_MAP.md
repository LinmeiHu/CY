# Objective breakout acceptance and rejection representation map

Frozen before any MKT-BREAKOUT-DATA-001 prior-high coordinate, crossing count,
or post-cross descriptor is constructed. This is a strategy-independent market
representation family. It does not reopen a rejected CHINEXT V1 lineage and it
contains no outcome, prediction, habitat, entry, execution, or payoff test.

## Scientific question

When an observed stock path strictly crosses an objective prior-high coordinate,
what completed-path observations distinguish mere contact, continuation,
acceptance, rejection, and reacquisition without assigning any of those states
economic usefulness in advance?

The first task is semantic and sample feasibility. Only after the event domains
are adequate may a separate frozen experiment test representation stability,
neighboring-definition portability, and compression into a smaller set of
latent path mechanisms.

## Exact non-duplication boundary

The consumed original-breakout lineage studied 399 already-selected CHINEXT V1
signals. Its reference was the maximum adjusted-coordinate **close** over the
prior 60 sessions; every admitted signal closed above that reference. It ranked
three full-session post-cross observations within year, split their composite at
0.50, combined it with a ranked base-repair score, and later rejected the four-
lineage ordering against MFE and non-false-breakout outcomes. That rejection and
all search-history penalties remain authoritative.

This map differs in every population-defining dimension:

- the immutable sample is calendar- and CY-006-eligibility-selected across four
  governed market views, never strategy-selected;
- the objective level is the maximum causal daily **high** over the prior
  10/20/40 completed sessions, not a prior-60 close;
- any strict intraday crossing enters, including sessions that later close at or
  below the level;
- absolute observations remain primary; no within-year rank, favorable label,
  0.50 split, base score, or ordinal lineage is constructed;
- representation quality is assessed before any future or strategy outcome is
  accessible.

Time above the level and closing state are economically necessary members of a
general acceptance map even though related quantities appeared in the rejected
V1 composite. They cannot be recombined into that composite, called favorable,
or tested on its consumed 399-event population here.

## Frozen coordinate, event, and clocks

- Unit before event conditioning: the immutable 1,920 five-session sequences,
  9,600 cohort rows, and 9,575 unique security-sessions from
  MKT-SUPPORT-DYN-DATA-004. Duplicate physical sessions retain each governed
  cohort identity; unique-session counts are also reported.
- Causal coordinate: CY-006 supplies the action-aware continuous close `C_t`
  and raw daily close `D_t`. Daily high is `H*_t = C_t * high_t / D_t` and raw
  QD-004 minute OHLC is mapped as `P*_t,m = P_t,m * C_t / D_t` using exact
  binary-double arithmetic. No vendor-adjusted minute price, future adjustment,
  rounding, tolerance, or source substitution is permitted.
- Objective level `Rh_t`: maximum `H*` over exactly the prior `h` completed,
  valid, consecutive exchange sessions for `h` in {10,20,40}; current session
  is excluded. Primary `h=20`; 10 and 40 are fixed semantic neighbors.
- Primary clock: 240 continuous bars at 09:31..11:30 and 13:01..15:00.
  Auction-inclusive 241 bars with the separate 09:30 row are a fixed challenge.
- Strict crossing: the first path bar whose mapped high is strictly greater than
  `Rh_t`. Equality is a touch, not a crossing. No near-level band is allowed.
- A continuous event does not inherit an auction crossing: its first crossing is
  the first qualifying continuous bar. The auction-inclusive challenge may have
  index zero. Both clocks preserve their own post-cross opportunity set.
- The level is fixed within session. It is not updated after a new high.
- The prior level is knowable after t-1 completes. A crossing bar becomes known
  only at that bar's end. The full descriptor is available at t 15:30
  Asia/Shanghai. No action inside the crossing bar or from later same-session
  bars is implied.

## Representation roles

Every role is first retained separately. Similar names do not establish a
shared mechanism.

| Role | Absolute completed-path observation | Interpretation boundary |
|---|---|---|
| Opportunity geometry | session maximum high / level - 1; first-cross position / (`n-1`) | Event magnitude and time opportunity, not acceptance |
| Immediate continuation | log close at +5/+15/+30/+60 completed bars divided by crossing-bar close | Post-cross attribution only; insufficient remaining bars are censored, never zero |
| Follow-through excursion | maximum high strictly after the crossing bar / level - 1 | Upside opportunity after crossing, not realized demand |
| Pullback/rejection depth | minimum low strictly after the crossing bar / level - 1 | Negative values are penetration; no causal seller identity |
| Level dwell | fraction of post-cross closes strictly above and strictly below the level; longest below-level close run / post-cross bars | Equality is separately neutral; duration is path state, not conviction |
| Loss episodes | number of transitions from a close at/above the level to a close below it | Rejection episodes, not independent trades |
| Reacquisition | after the first below-level close, whether and how many bars until a later close strictly above the level | Conditional path recovery; undefined without a loss and reacquisition |
| Closing acceptance | final close / level - 1 and sign state {above, equal, below} | Absolute closing geometry; no favorable label |
| VWAP acceptance | post-cross fraction of closes above cumulative session VWAP; final close / session VWAP - 1 | QD-004 amount/volume OHLCV proxy, not order flow |
| Breakout activity | post-cross share of session volume divided by post-cross share of bars; crossing-bar volume / median prior continuous-bar volume | Relative observed activity, not aggressor volume |
| Repetition | count of distinct strict crossing episodes after the first, using below-to-above close-state transitions | Path oscillation around one fixed level, not repeated supply depletion |

The first-cross bar participates in closing-state and activity observations but
not in "strictly after" follow-through excursion or pullback depth. A session
ending on the crossing bar has a valid crossing and closing state but censored
post-cross roles.

## Event-state taxonomy without favorable ordering

For count and later conditional analyses, retain neutral, mutually exclusive
completed-session states:

1. `NO_CROSS` — no strict high crossing on the chosen path;
2. `CROSS_CLOSE_ABOVE` — strict crossing and final close strictly above level;
3. `CROSS_CLOSE_EQUAL` — strict crossing and exact final-close equality;
4. `CROSS_CLOSE_BELOW` — strict crossing and final close strictly below level.

Separately flag `LOSS_NO_REACQUISITION`, `LOSS_REACQUIRED`, and
`NO_CLOSE_LOSS_AFTER_CROSS`. These are path facts, not success/failure labels.
No state is pooled or reordered after counts are observed.

## Generic-path alternatives and latent compression

A later representation experiment must challenge each retained role against
fixed ordinary path explanations from the same completed session:

- open-to-close log return;
- daily high distance from the prior-high level;
- close location within the session range;
- time of session high;
- minute realized volatility;
- continuous-session range;
- volume Herfindahl and closing-30-minute volume share.

Closing acceptance is expected to overlap daily return/high geometry and is not
promoted merely because it is stable. VWAP acceptance is challenged against the
already accepted same-session VWAP-defense/recovery coordinate. Activity is
challenged against minute-volume concentration. Post-cross roles that remain
distinct may then be compressed, in fixed conceptual order, into no more than:

1. continuation;
2. rejection exposure;
3. reacquisition;
4. closing/VWAP acceptance;
5. activity confirmation.

No equal-weight omnibus acceptance score is prespecified. A latent combination
requires stable members and demonstrated redundancy or shared geometry first.

## Five-session trajectory architecture

Five-day research follows, rather than precedes, adequate same-session roles.
Do not flatten minute bars or impute `NO_CROSS` days with a favorable/unfavorable
numeric value. Study separately:

- event incidence and first-cross timing across Day -5..Day -1;
- conditional continuation, rejection depth, below-level dwell, reacquisition,
  closing state, VWAP state, and activity on event days;
- transitions among `NO_CROSS`, close-above/equal/below, loss, and reacquisition
  states;
- leading pre-event daily geometry versus post-cross attribution.

Endpoint rate, ordinal progression, transition probability, or another shape
operator must be frozen only after support counts are known. Neighboring 3-day
and longer horizons are robustness challenges, never alternatives selected for
stronger results.

## Absolute, PIT-historical, and relative coordinates

- **Absolute:** dimensionless level ratios, bar counts/fractions, and activity
  ratios use identical semantics across 2018--2023 and are primary.
- **PIT historical:** a later full calendar population may construct a causal
  trailing-756-session percentile after 504 valid observations. The isolated
  48-block sample cannot stand in for continuous causal history, so no sampled-
  block percentile or year rank is permitted.
- **Relative:** contemporaneous same-date ranks require the full eligible
  cross-section. Ten sampled symbols per block/view are an audit, not a market
  rank. Governed-view counts and distributions may test descriptive portability
  only.

No missing coordinate system is silently replaced by another.

## Representation-quality sequence

The family advances in this fixed order:

1. MKT-BREAKOUT-DATA-001 verifies coordinate identity, PIT/minute semantics,
   event support, censoring support, block/year/view coverage, and resources;
   it computes counts only.
2. If count gates pass, freeze a separate same-session representation contract
   covering L20 continuous primary, L10/L40 and auction challenges, generic-path
   compression, scalar reconstruction, and deterministic replication.
3. Only stable, externally distinct session roles may enter a separately frozen
   five-session trajectory/transition map.
4. Only after representation and process evidence may a future experiment ask
   about daily setup incrementality, habitat, stock outcomes, or strategy use.

Failure of one conditional role does not reject the entire family. Failure of
the primary crossing population or both close-state arms deprioritizes this
exact sample/coordinate branch without authorizing threshold, horizon, or
population search.

## Falsification and claim boundary

- L10/L40 and auction inclusion are neighboring semantic challenges, not rescue
  candidates.
- Source-close disagreement, corporate actions, limit contacts, suspensions,
  missing bars, and late-cross censoring remain explicit.
- At least five scalar cases must reconstruct the coordinate level and first
  crossing without calling the vectorized event implementation.
- Two executions must produce byte-identical durable outputs.
- Future return, future volatility, industry/market outcome, candidate status,
  CHINEXT strategy membership, MFE, MAE, P&L, entry, exit, duration, post-2023
  partitions, and CY-011 are prohibited.
- OHLCV cannot identify orders, queues, aggressors, hidden liquidity,
  absorption, accumulation by participants, or overhead-supply depletion.
- Passing establishes only a defensible completed-path representation. It does
  not establish prediction, causal demand, breakout quality, timing, habitat,
  execution, trading usefulness, or a strategy archetype.
