# Objective-recovery temporal dynamics map

Frozen before MKT-SUPPORT-DYN-001 reconstructs any raw minute path or computes
any progression direction. MKT-SUPPORT-DYN-DATA-004 establishes an adequate,
outcome-blind sample only. MKT-SUPPORT-GEO-001 establishes that completed-
session recovery speed and recovery-volume intensity are externally distinct
observations only. Neither result establishes defense or a temporal process.

## Scientific question

Across five completed sessions, do repeated tests of the same semantic objective
level family exhibit stable recovery-timing progression, recovery-period
activity progression, coupling, or recovery-completion state dependence after
fixed neighboring definitions and generic intraday-path explanations?

The daily L10/L20/L40 coordinates roll through time. Therefore a repeated test
means repeated testing of the same *objective trailing-low definition*, not
necessarily the same physical price. No result may be described as repeated
defense of one unchanged price level without a later level-identity experiment.

## Frozen units, clocks, and domains

- Unit: the 1,920 immutable five-session cohort sequences and 9,600 rows from
  MKT-SUPPORT-DYN-DATA-004. Cohort identity is retained even for the five known
  duplicated physical sequences; a deduplicated physical-sequence result is a
  non-promotional sensitivity only.
- Primary level/path: prior L20 and 240 continuous bars at 09:31..11:30 and
  13:01..15:00. L10/L40 and the exact 241-bar auction-inclusive path are fixed
  challenges and cannot rescue L20 continuous failure.
- Descriptor availability: each completed session at 15:30 Asia/Shanghai. A
  five-session trajectory is available only after Day -1 at 15:30. It cannot
  authorize an action in any constituent session.
- Recovery-trajectory domain: at least two tested-and-recovered days with both
  recovery speed and recovery-volume intensity defined under that exact
  level/path. The known primary count is 269 (107 in 2018--2020 and 162 in
  2021--2023).
- Recovery-transition domain: at least two tested days under the exact
  level/path. The known primary count is 315 (133/182 fixed blocks).
- A test remains `min(low) <= Lh`; there is no near-touch band. An unrecovered
  session is never imputed to 240 bars and is excluded from continuous recovery
  trajectory values while remaining explicit in transition analysis.

## Session observations reconstructed without change

For every h in {10,20,40} and continuous/auction path, reconstruct the frozen
MKT-SUPPORT-001 test, recovery-completion, recovery-speed, and recovery-volume-
intensity semantics. Also construct only the following fixed explanatory
observations from the same mapped session:

| Observation | Definition | Role boundary |
|---|---|---|
| First-test position | first `low <= Lh` bar index divided by `n-1` | censoring/time-of-day opportunity, not support strength |
| Time of low | first minimum-low bar index divided by `n-1` | generic path timing |
| Close location | `(close-min low)/(max high-min low)` | generic path geometry |
| Open-to-close return | final close / first path open minus one | generic return path |
| Minute realized volatility | square root of summed squared log-close changes | generic volatility path |
| Volume Herfindahl | sum of squared minute-volume shares | generic activity concentration |
| Opening/closing 30 shares | first/last 30 path bars divided by session volume | generic time-of-day activity |
| Signed test geometry | minimum low / Lh minus one | rolling-level opportunity geometry |
| Closing level state | final close / Lh minus one | rolling-level closing geometry |

All price observations use the already accepted CY-006 causal coordinate scale
and QD-004 observed raw minute path. OHLCV cannot identify buyers, sellers,
aggressors, absorption, queues, or participant intent.

## Temporal representations

For the ordered recovered days at relative indices in {-5,-4,-3,-2,-1}, build
separately for recovery speed and recovery-volume intensity:

1. **Primary endpoint rate:** `(last value - first value) / elapsed session
   index`.
2. **OLS neighbor:** least-squares slope over every available recovered day and
   its actual relative-day index.
3. **Theil--Sen neighbor:** median of every pairwise slope over available
   recovered days.

Two observations are sufficient because all three operators then equal the same
endpoint rate; support for three-or-more recovered days is reported separately
so this identity cannot be mistaken for rich shape evidence. Recovery-speed
rate below zero means faster later recovery; above zero means slower. Recovery-
volume-intensity rate describes relative activity only; its sign is not assigned
to demand or supply.

For every explanatory observation, construct its endpoint rate over the exact
same recovered days as the target. This matched-day rule prevents different
missingness from creating apparent distinctness.

## Recovery-completion transitions

For each primary transition-domain sequence, order tested days and classify the
first and last tested states as recovered (`R`) or unrecovered (`F`). The four
fixed categories are `R->R`, `R->F`, `F->R`, and `F->F`.

The primary state-dependence estimate is:

`P(last=R | first=R) - P(last=R | first=F)`.

Positive values indicate completion-state persistence and negative values
indicate reversal. `R->F` is descriptive deterioration and `F->R` descriptive
restoration; neither is failure/success in trading terms. First-to-last state is
an endpoint relation, not a per-day transition probability. An adjacent-tested-
pair estimate clustered by sequence is a fixed shape challenge, not a rescue.

## Fixed generic-path compression

The recovery-speed rate is challenged by endpoint rates of:

- first-test position;
- time of low;
- close location;
- minute realized volatility;
- signed test geometry.

The recovery-volume-intensity rate is challenged by endpoint rates of:

- volume Herfindahl;
- opening-30-minute volume share;
- closing-30-minute volume share;
- first-test position;
- recovery speed.

All estimators use average-tie ranks. For a temporal role to remain externally
distinct, every target/control absolute Spearman must be below 0.85 globally
and in both fixed blocks, joint adjusted rank R-squared must be below 0.70
globally and below 0.85 in each block, and every control must be complete on the
matched target domain. No control may be deleted after observing its explanatory
power.

## Representation-quality gates

All gates are conjunctive for a retained primary temporal role.

1. Exact bound-input identities, 1,920 sequences, 9,600 cohort rows, 9,575
   unique sessions, 2,307,575 raw rows, exact 241-bar grid, zero coordinate/
   action/lineage failure, and the inherited resource ceilings.
2. Primary recovery domain: exactly the audited 269 sequences, with 107/162
   fixed-block counts and annual counts 40/30/37/39/70/53. Any difference is a
   correctness failure, not a new sample.
3. Endpoint-versus-OLS and endpoint-versus-Theil--Sen Spearman at least 0.70
   globally and 0.60 in each fixed block; sign agreement at least 0.75 globally
   and 0.70 in each block. Zero/zero counts as agreement and is reported.
4. Each L10/L40 intersection contains at least 100 sequences globally and 35 in
   each fixed block. Endpoint-rate Spearman with L20 is at least 0.50 globally
   and 0.30 in each block, with at least 0.60 sign agreement globally. Both
   neighbors must pass.
5. The auction-inclusive intersection contains at least 150 sequences globally
   and 60 in each block. Endpoint-rate Spearman with continuous L20 is at least
   0.70 globally and 0.60 in each block, with at least 0.75 sign agreement.
6. Fixed generic-path compression passes as defined above.
7. Every year retains at least 30 primary recovery trajectories. Report the
   count with at least three recovered days by year/block; do not lower a gate
   or change the operator if that richer subset is small.

Passing these gates establishes a stable absolute temporal representation, not
a common directional process.

## Directional-process, coupling, and transition gates

For each retained trajectory role, a common directional process additionally
requires:

- the median endpoint rate has the same nonzero sign in both fixed blocks;
- among nonzero rates, each block has at least 55% in that direction;
- a 5,000-resample calendar-block bootstrap 95% interval for the median excludes
  zero in both blocks, using seed 20260831; and
- at least five of six annual medians have the same sign.

Coupling between the two primary endpoint rates requires absolute Spearman at
least 0.15 globally, the same sign and absolute Spearman at least 0.10 in both
blocks, the same sign in at least five of six years, and the same sign with
absolute Spearman at least 0.10 for both OLS and Theil--Sen shape pairs. The same
raw gates then apply to residual target ranks after each role's full fixed
generic control set. Failure means no shared recovery process; it does not erase
an individually stable temporal representation.

The primary completion transition requires at least 50 first-R and 50 first-F
sequences globally, at least 20 of each arm in both fixed blocks, and at least
five of each arm in every year. A portable state-dependence claim then requires
absolute risk difference at least 0.10 with the same sign in both blocks, a
5,000-resample calendar-block bootstrap interval excluding zero globally and in
both blocks, at least five of six annual estimates with that sign, and the
adjacent-pair challenge with the same sign and absolute difference from the
primary no greater than 0.15. Each of the four transition categories and its
block/year support is always reported. Unsupported arms produce
`INSUFFICIENT_TRANSITION_SUPPORT`, never smoothing or pooling.

## Coordinates and portability

- **Absolute:** bars per session index and dimensionless activity-rate units use
  one definition across 2018--2023. Raw yearly distributions remain visible.
- **PIT historical:** unavailable from 48 isolated blocks. No rolling percentile,
  expanding percentile, or sampled-block z-score is constructed.
- **Relative:** ten-symbol sampled view cells are too sparse after conditional
  recovery selection to represent a causal market cross-section. Cell support
  is audited, but no relative rank is promoted. A later full eligible same-date
  population is required if the absolute process survives.
- **Portability:** A/B blocks, all six years, L10/L40, auction inclusion, and the
  four governed market views are reported under unchanged semantics. View
  estimates are descriptive because conditional support can be sparse and
  sampled views overlap.

## Falsification, replication, and claim boundary

- Independently reconstruct five sequence cases selected only by the smallest
  SHA-256 of sequence identity among the primary eligible domain. The scalar
  implementation must exactly reproduce every session recovery observation and
  all three temporal operators; it may not call the vectorized descriptor.
- Preserve exact source-close disagreement and corporate-action diagnostics.
- Execute twice and require byte-identical durable outputs.
- No future return, outcome, strategy membership, candidate, entry, exit,
  execution, post-2023 partition, or CY-011 may enter.
- No level, near-touch band, path, window, shape, control, block, support floor,
  direction threshold, coupling threshold, or transition arm may be changed to
  rescue a result.
- Passing representation quality establishes only a completed-history state
  coordinate. Passing a directional/coupling/transition gate establishes only
  an exploratory recurring market-process observation. Neither establishes
  support defense, accumulation, demand, prediction, timing, habitat, payoff,
  execution, synergy, or a strategy.
