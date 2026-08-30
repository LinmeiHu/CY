# Objective support representation map

Frozen before MKT-SUPPORT-001 reconstructs raw minute paths. The passing
MKT-SUPPORT-DATA-003 coordinate is necessary but not evidence of support,
defense, recovery, or accumulation.

## Scientific question

Can an objective prior daily low be represented through several economically
distinct, cross-year-comparable observations of test opportunity, penetration,
time beyond the level, repeated testing, and recovery—without turning a touch
into “defense” or selecting a favorable proximity threshold?

## Fixed level and session semantics

- Primary objective level: minimum causal action-coordinate daily low over the
  20 completed sessions through t-1.
- Fixed level-definition neighbors: 10 and 40 completed sessions. They are
  robustness challenges, never alternative primaries.
- Primary session path: 240 continuous bars at 09:31..11:30 and 13:01..15:00.
- Fixed auction neighbor: the exact 241-bar path including the separate 09:30
  auction. Auction evidence cannot rescue a failed continuous definition.
- The level is available at t-1 15:00. The completed descriptor is available at
  t 15:30 and permits no t-session action.
- CY-006 supplies the causal daily coordinate scale. QD-004 supplies every raw
  minute OHLCV/amount value. Daily/minute close disagreement remains explicit.

No near-touch band is defined. A tested session has minimum observed low less
than or equal to the objective level. This prevents a post hoc 1%, 2%, or 3%
threshold from increasing support.

## Session representation map

For each level horizon h in {10, 20, 40}, define Lh and the mapped continuous
minute path.

| Role | Frozen representation | Domain | Interpretation boundary |
|---|---|---|---|
| Test geometry | `signed_minimum_distance_h = min(low)/Lh - 1` | All sessions | Negative means penetration; positive means the level was not reached |
| Test occurrence | `tested_h = signed_minimum_distance_h <= 0` | All sessions | Opportunity indicator only, not defense |
| Penetration | `penetration_depth_h = max(0,-signed_minimum_distance_h)` | All sessions | Deterministic one-sided manifestation of test geometry; not a separate latent role |
| Time beyond level | fraction of continuous closes strictly below Lh | All sessions | Duration/acceptance below, not seller identity |
| Test recurrence | number of starts of contiguous `low <= Lh` episodes | All sessions | Repeated observable tests; bar flicker may remain |
| Closing level state | `close_15:00/Lh - 1` | All sessions | Final location relative to level; partly general daily path |
| Recovery completion | any close at/above Lh from the first tested bar through 15:00 | Tested sessions | Binary completion, not trade success |
| Recovery speed | bars from first tested bar to first close at/above Lh; zero if the test bar closes recovered | Tested and recovered sessions | Unrecovered sessions remain separately flagged, never imputed to 240 |
| Recovery amplitude | `(close_15:00 - minimum_low)/Lh` | Tested sessions | End-of-session rebound from observed minimum |
| Recovery volume intensity | volume share from first test through first recovery divided by its continuous-bar share | Tested and recovered sessions with positive volume | Relative activity during recovery; not buyer initiative |

The deterministic penetration transform is retained for audit but cannot count
as distinct from signed test geometry. Internal compression priority is:

1. signed test geometry;
2. time beyond level;
3. test recurrence;
4. closing level state;
5. recovery speed;
6. recovery amplitude;
7. recovery volume intensity.

Later roles with global and median within-cell absolute Spearman at or above
0.85 are descriptive manifestations, not independent engine dimensions.

## Five-session representation map

Only the 240 fixed market sequences enter trajectory construction; the 30
action challenges remain coordinate validation cases.

For signed distance, time below, test-episode count, and closing level state,
construct:

- fixed five-day OLS slope against centered day index -2,-1,0,1,2;
- Day -1 minus Day -5 endpoint change;
- five-day Spearman ordinal progression with average ties.

The slope is primary. Endpoint and ordinal forms are fixed shape challenges, not
window alternatives. A trajectory freezes only if slope-versus-endpoint global
Spearman is at least 0.70 and slope-versus-ordinal is at least 0.60, with the
same qualitative sign in at least five of six years.

Repeated-test behavior is represented separately by number of tested days and
total test episodes over the five sessions. It is a frequency state, not a
slope.

Conditional recovery strengthening/weakening requires at least two tested days
within a sequence. At least 30 such primary sequences are required before any
recovery trajectory estimate. The known prefreeze audit count is 29; therefore
the conditional trajectory is expected to fail support unless exact raw
continuous semantics change the count. It may not be rescued by a near-touch
band, auction inclusion, 10-day level, or reduced support floor.

## Coordinate systems

- **Absolute:** all session roles are dimensionless or counts and retain one
  semantic definition across years.
- **Relative:** same-date/year/view ranks are constructed only for the ten fixed
  sequence symbols, with average ties and exact cell size recorded. They are a
  sampled cross-sectional view, not absolute market state.
- **PIT historical:** unavailable from six isolated five-session blocks. No
  expanding or rolling percentile may be fabricated. Continuous historical
  normalization remains a data/scale backlog item for any promoted role.

## Frozen representation gates

1. Exact 003 sample/coordinate/result, 003 runner, QD-004 inventory, and minute-
   adapter identities.
2. Exactly 1,200 market rows, 240 sequences, 30 action rows, and 1,225 unique
   raw sessions; zero key, grid, lineage, or mapping mismatch.
3. All-session role coverage is 100% and every relative cell has exactly ten
   cohort rows before average ties.
4. Primary conditional session roles require at least 100 tested market rows
   and at least ten in four of six years. Recovered-volume roles require at least
   60 valid primary rows.
5. Primary-versus-10/40 all-session stability: median within-year/view Spearman
   at least 0.70 for each neighbor and at least 18 of 24 nondegenerate cells at
   or above 0.50. Conditional-role intersections require at least 30 observations
   and global Spearman at least 0.60.
6. Continuous-versus-auction-inclusive median within-cell Spearman at least
   0.85. Auction inclusion cannot rescue another failed gate.
7. Five-day unconditional trajectories require all 240 sequences and the fixed
   shape gates above. Conditional recovery trajectories require 30 eligible
   sequences before estimation.
8. Internal redundancy uses the fixed priority and 0.85 pairwise boundary. No
   control deletion or favorable view/year/horizon selection is allowed.

## Falsification and claim boundary

- Report test counts by year/view and the full sequence-frequency distribution.
- Preserve daily/minute source-close difference as an audit control; compare
  role values on the 39 integer-cent mismatch sessions versus the remainder as
  a non-promotional sensitivity diagnostic.
- Independently reconstruct at least five predefined cases spanning no test,
  penetration/recovery, penetration/nonrecovery, repeated test, and action day.
- No outcome, future return, strategy field, post-2023 data, or CY-011 may enter.
- Passing establishes representation quality only. It does not establish
  support, defense, accumulation, prediction, timing, habitat, or a strategy.
