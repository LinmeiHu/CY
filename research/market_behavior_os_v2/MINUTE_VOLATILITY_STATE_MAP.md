# Minute-volatility ordinal state map

Frozen before MKT-MIN-VOL-STATE-001 construction. MKT-MIN-PATH-002 established
one stable continuous/discrete-valued ordinal path representation, and
MKT-MIN-VOL-GEO-002 established that it is not reconstructed by accepted
same-session or daily volatility controls. This map asks the narrower next
question: do exact path-direction states recur and preserve process structure
under both already-accepted ordinal definitions?

## Fixed state semantics

For the primary mean sign of four adjacent Day -5..Day -1 changes and each of
its two frozen definition neighbors:

- `RISING`: value strictly greater than zero;
- `FALLING`: value strictly less than zero;
- `FLAT`: value exactly zero;
- `MISSING`: nonfinite, which fails required coverage and is never imputed.

No percentile or optimized state boundary is introduced. `RISING` and
`FALLING` describe the recent trajectory of the market cross-sectional median
of per-security minute realized volatility. They are not yet economic
`EXPANSION` or `CONTRACTION` mechanisms.

The two fixed neighboring definitions are the mean sign of all ten ordered day
pairs and the rank correlation of day order with the five daily values. They
are robustness definitions, not alternative primaries.

## Daily-volatility context

Use only the accepted MKT-VOL-001 20-session realized-volatility causal
expanding percentile:

- `LOW_LEVEL`: percentile at or below 0.20;
- `HIGH_LEVEL`: percentile at or above 0.80;
- `MIDDLE_LEVEL`: otherwise.

This 3 x 3 path-by-level geometry is contemporaneous and descriptive. It is not
a habitat or trading rule, and sparse cells remain visible.

## Population and PIT boundary

Join the immutable MKT-MIN-PATH-002 and MKT-VOL-001 panels exactly on date,
governed view, and denominator. The common population is 10,696 rows from
2018-07-03 through 2023-12-29, with 1,337 rows in each of eight groups.

Daily level context is available at 15:00; the path uses the completed 15:00
minute bar and is available at 15:30 Asia/Shanghai. Current-state availability
is therefore 15:30. Dwell lengths and transitions use later realized states
only as post-state representation attribution. They are never entry predictors
and cannot authorize an earlier action.

## Fixed representation gates

All gates are evaluated without future returns or strategy outcomes:

1. Every 2019-2023 group/year cell has at least 150 valid observations for the
   primary, both neighbors, and daily level percentile.
2. Each of `RISING`, `FALLING`, and `FLAT` has at least 20 primary observations
   in every group/year cell.
3. For each neighbor, exact three-state Cohen kappa and macro Jaccard have
   median at least 0.60 and minimum group value at least 0.50.
4. Every primary state has at least 20 completed runs in every group. For each
   state/group/neighbor, the neighbor-to-primary median dwell ratio must remain
   within 0.50 through 2.00.
5. For each neighbor, total-variation distance between the nine-cell normalized
   primary and neighbor transition matrices has median at most 0.20 and maximum
   at most 0.30 across groups.
6. Every one of the nine primary path-by-level cells has at least five
   observations in every 2019-2023 group/year cell.

Exact states are frozen only if all gates pass. No favorable state, neighbor,
view, denominator, year, transition, or level cell can rescue failure. Failure
does not revoke the continuous path representation; it rejects only this exact
discrete recurrent-state architecture.

## Claim boundary

Passing establishes portable descriptive path states and their process
geometry. It does not establish volatility forecasting, future returns,
causality, strategy usefulness, a market habitat, entry timing, exit timing, or
an executable contraction/expansion archetype. Economic usefulness requires a
separate preregistered temporal experiment after this representation result.
