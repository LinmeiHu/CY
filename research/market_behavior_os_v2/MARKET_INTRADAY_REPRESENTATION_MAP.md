# Market Intraday Representation Map

Frozen before MKT-MIN-001 implementation and required-scale minute access.
This map describes the market itself. It does not read future returns, strategy
membership, trades, outcomes, or post-entry paths.

## Market observation and population

For each completed exchange session from 2018 through 2023, construct the 34
accepted same-session dimensionless descriptors for every SH/SZ security whose
raw session and bound CY-006/CY-008 context pass exactly. Aggregate the current
causal cross-section for ALL_A, SH_A, SZ_A, and CHINEXT_BOARD under ALL_STATUS
and NON_ST denominators. The cross-section is the full eligible view, not a
liquidity-selected or outcome-selected sample.

Each descriptor preserves its cross-sectional 40th percentile, median primary,
and 60th percentile. Minimum current counts remain 1,000/400/400/200 for
ALL_A/SH_A/SZ_A/CHINEXT_BOARD. A missing or invalid session is absent from both
numerator and denominator and is explicitly counted; it is never replaced.

## Economic families

| Family | Accepted same-session previews | Scientific boundary |
|---|---|---|
| Price path | open/close, morning, afternoon, final-30 returns; high/low time; close location; signed efficiency; path R2 | Path shape, not cross-day trend |
| VWAP structure | close versus VWAP; time/volume above; half-day VWAP slope; recovery count; longest below; late acceptance | Session VWAP from raw amount/shares only |
| Selling pressure | downside excursion; downside realized volatility; down-minute volume share; selloff duration; recovery speed | OHLCV proxies cannot identify aggressor selling or absorption |
| Buying pressure | upside excursion; up-minute volume share; positive-minute fraction; new-high fraction | Demand proxy, not participant identity |
| Volatility/oscillation | intraday range; minute realized volatility; VWAP-deviation dispersion; VWAP crossings | Contraction is a five-day trajectory hypothesis, not a single level |
| Volume path | opening, afternoon, and closing shares; minute-volume concentration | Shares and CNY units remain separate and conserved |
| Auction relation | auction-to-continuous-open return | Separate 09:30 auction row required |

Objective support/resistance defense and cross-day price-level acceptance are
deferred because no action-safe cross-day minute level is registered. Breakout
acceptance is not a predictor here; any later post-entry analysis must be labeled
attribution.

## Five-day trajectory map

For each absolute median series retain Day -5 through Day -1 and construct:

- five-day endpoint change and per-session endpoint slope;
- five-day OLS slope;
- last-three-session OLS slope;
- signed monotonic-step fraction;
- slope acceleration (last two step mean minus first two step mean);
- reversal indicator only as an outcome-blind shape label when the first-two and
  last-two step means have opposite nonzero signs.

The primary trajectory coordinate is the five-day OLS slope. The endpoint slope
and last-three-session slope are fixed robustness neighbors; none may replace a
failed primary. Trajectories first become available at Day -1 15:30 Asia/Shanghai
and cannot justify an earlier or same-bar action.

## Three coordinates and representation gates

1. Absolute descriptor levels and trajectory shapes.
2. Strict PIT expanding percentile, trailing-756-session percentile, and
   trailing robust z-score, including only observations available by the same
   timestamp and requiring at least 504 observations.
3. Same-date view-minus-ALL_A and governed-view rank.

Each exact descriptor/trajectory representation reports coverage, 40/50/60
cross-sectional-definition stability, endpoint/OLS/three-day trajectory
stability, ALL_STATUS/NON_ST stability, view/year nondegeneracy, portability,
and pairwise absolute Spearman redundancy. Fixed primary gates are 95% raw
coverage, 0.70 worst median neighboring-definition stability, 0.90 denominator
stability, and at least 150 nondegenerate observations per eligible view/year.
Connected components at absolute Spearman 0.85 are redundancy diagnostics, not
proof of latent causality.

Role compression respects economic families before testing combinations.
Supply exhaustion, demand strengthening, accumulation/distribution, volatility
contraction, and intraday trend quality remain falsifiable interpretations until
the surviving representations and later path evidence support them.

The exact outcome-blind minimal-panel priority is the pre-existing accepted
`DESCRIPTOR_COLUMNS` order: price path, VWAP structure, selling pressure, buying
pressure, volatility/oscillation, volume path, then auction relation, preserving
the within-family order in the frozen reference implementation. A passing role
is accepted only when its absolute trajectory Spearman correlation with every
earlier accepted role is at most 0.85. Serialization uses compressed Parquet for
the wide trajectory panel to remain inside the durable-output budget; this does
not change any scientific value.
