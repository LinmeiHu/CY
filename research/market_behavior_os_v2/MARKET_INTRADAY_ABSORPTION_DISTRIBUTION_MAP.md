# Same-session intraday absorption/distribution falsification map

Frozen before MKT-MIN-AD-001 constructs any score. Traditional accumulation
and distribution language is not treated as fact. This experiment asks only
whether two explicit effort-versus-price-response hypotheses form stable,
externally distinct same-session market representations.

## Data and PIT boundary

Use only the frozen MKT-MIN-001 daily market panel. Its descriptors summarize
completed 09:30--15:00 minute bars and become available at 15:30 Asia/Shanghai.
No raw minute row, future session, strategy field, post-2023 row, or CY-011 may
be read. The experiment creates no action, and same-session trading use is
forbidden.

All components are accepted MKT-MIN-001 same-session levels. MKT-MIN-001's
failed selloff-duration and auction-gap roles, failed five-day slopes, and all
post-decision paths remain barred.

## Hypothesis A: selling-effort absorption

A high score requires the conjunction-like alignment of:

- high downside-minute volume share: observable selling-side effort;
- shallow downside excursion: limited price damage for that effort;
- fast recovery from the intraday low;
- repeated recovery above session VWAP.

This is labeled `selling_effort_absorption` only as a falsifiable OHLCV
representation. It does not identify buyer-initiated trades, passive liquidity,
institutions, inventory transfer, or accumulation by any participant. Because
three components overlap the accepted VWAP-defense/recovery representation,
that score is a mandatory external alternative.

## Hypothesis B: rally-effort distribution

A high score requires the alignment of:

- high upside-minute volume share: observable buying-side effort;
- shallow upside excursion: limited price response for that effort;
- weak late-session VWAP acceptance;
- weak final-30-minute return.

This is labeled `rally_effort_distribution` only as a falsifiable mirror
hypothesis. It does not identify sellers, informed supply, distribution by
holders, or future reversal.

## Fixed construction and representation challenges

For every component, cross-sectional definition, market view, and denominator,
construct the exact trailing-756-session causal percentile after 504 valid
observations, including the current completed observation. Positive-aligned
components retain the percentile; negative-aligned components use one minus
the percentile.

The primary score is the equal arithmetic mean of four aligned component
percentiles under the median stock cross-section. Fixed challenges are:

- median and geometric mean across the same four components;
- all four leave-one-component-out arithmetic means;
- p40 and p60 stock cross-sectional definitions;
- ALL_STATUS versus NON_ST;
- all 2021--2023 view/denominator/year cells;
- same-date relative-to-ALL_A and governed-view ranks.

No component, sign, weight, aggregator, quantile, view, denominator, year, or
favorable subset may be chosen after construction.

## External geometry and compression

After internal representation gates pass, compare each score in causal-PIT and
relative-rank coordinates with exactly four fixed alternatives:

1. open-to-close return;
2. downside realized volatility;
3. minute-volume concentration;
4. accepted MKT-MIN-SUPACC-001 VWAP defense/recovery.

Pairwise median absolute Spearman must remain below 0.85. Fixed-control joint
rank reconstruction must remain below 0.70 median and 0.85 maximum adjusted R2.
No control may be removed. If both hypotheses survive, compress them at a 0.85
pairwise edge in the priority order selling-effort absorption, then rally-
effort distribution. Do not create their difference, product, state bin, or a
joint accumulation/distribution oscillator.

## Claim boundary

Passing establishes only a stable, nonredundant same-session OHLCV
representation. It establishes no participant intent, order flow, cross-day
accumulation/distribution process, absorption mechanism, future reversal,
forecast, habitat, entry, execution, payoff, capacity, or strategy archetype.
Failure rejects only these exact score definitions and not the broader research
families.
