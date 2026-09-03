# V7 VAP and inventory semantics — code facts

All references are to commit `865bfa9ffb9e281438e10a60ca7f57dd3945658e`. This is an implementation inventory, not an economic verdict.

The cited implementation file is `research/market_behavior_os_v2/scripts/run_ashare_true_gap_v7_overhang_attack_episode_simple_rule_development_v1.py`.

## Observation window and cutoff

`build_vap_date_map` joins each candidate to daily rows from `gap_cal_idx - 120` through `gap_cal_idx + 90`, capped at `2023-12-31` (V7 lines 906-935). Therefore the maximum represented pre-gap history is 120 sessions; the map is not an unlimited lifetime history.

`_inventory_features` then limits the turnover-decayed history to calendar indices strictly before the relevant `attack_start_cal_idx` and appends partial current-session bins (1267-1296). `_partial_attack_start_bins` includes current attack-date minute bars only when `bar_end_time <= attack_start_time` (1346-1359).

Consequently the admission-state VAP cutoff is `ATTACK_START_TIME`, not the later entry-translation decision clock. The same attack-start inventory state is copied onto each translation's decision row at lines 1737-1744.

## Daily versus minute source

- Daily PIT data supplies the candidate/session map, coordinate factor, turnover fraction, daily volume, lineage and validity state (906-935).
- Raw one-minute bars supply price, volume and amount (938-982).
- The primary minute price is `amount / volume` when both are positive; otherwise `(high + low + close) / 3` (960-968).
- That raw price is multiplied by the daily QD-010 coordinate factor before binning (961-968).
- `vap_price_proxy` is set to 1 only when `volume > 0` and `amount` is not positive (962); the fallback expression also applies when volume is zero, while that particular flag remains 0 under the literal condition.

## Price bins and width normalization

The implementation defines:

`z = (coordinate_price - L) / W`, with `W = U - L`.

It uses a bin width of `0.10` in z and integer bins `-20` through `29`, representing `[-2W,+3W)` around L (constants 121-123; SQL 963-978). Out-of-range prices receive sentinel bin `999` and are excluded from the local histogram functions.

Thus bin location and bin width are normalized by each gap's price width W. There is no additional division by absolute currency price width when accumulating volume inside a bin.

## Volume allocation and normalizers

For each candidate-session-bin, `_build_vap_year` stores:

- `raw_volume`: sum of minute volume;
- `raw_amount`: sum of minute amount;
- `allocated_float_turnover`: daily turnover fraction × minute volume / observed session volume, summed by bin (lines 971-978).

The exact-window raw VAP variables divide a region's raw volume by raw volume in all local bins `[-2W,+3W)` (1278-1284). The corresponding `float_vap_*` variables are sums of allocated float turnover; they are not divided again by local turnover.

The turnover-decayed region variables are also sums of decayed allocated float turnover. They are not local-volume shares. `overhang_support_ratio` is a ratio of those same-unit region sums.

## Regions implemented

For the decayed histogram (1297-1309):

- support below L: z bins `-10..-1`, i.e. `[-1W,0)`;
- inside the true gap: z bins `0..9`, i.e. `[0,1W)` = `[L,U)`;
- immediately above U: z bins `10..19`, i.e. `[1W,2W)` = `[U,U+W)`;
- local density universe: all bins `-20..29`, i.e. `[-2W,+3W)`.

There is therefore an explicit local price corridor in the VAP histogram, but no separate variable named `corridor_inventory` and no corridor-based attack-touch rule.

Two post-gap turnover calls use inclusive integer-bin arguments that are worth reading literally (1330-1335):

- `cum_turnover_near_l = _region_sum(post, -5, 6, ...)` includes bins -5 through +5, corresponding to `[-0.5W,+0.6W)` under the implemented bin geometry.
- `cum_turnover_inside_gap = _region_sum(post, 0, 11, ...)` includes bins 0 through 10, corresponding to `[0,+1.1W)`.

These ranges follow directly from `_region_sum`, which selects `between(low, high-1)` inclusively (1254-1255). The frozen feature-dictionary prose describes the intended labels more compactly; the source above is the executed range.

## Turnover decay and half-life

For every represented session, the code computes cumulative allocated float turnover after that session and before the attack clock, then applies:

`survival_weight = exp(-min(future_turnover, 50))`

(1290-1296). The cap of 50 is on the exponent for numerical protection. Turnover itself is not clipped by this function.

There is no fixed calendar or session half-life. Under the implemented formula, weight reaches one half after subsequent cumulative turnover of `ln(2)` (approximately 0.693 in turnover-fraction units).

The current partial attack-start session is appended to history and participates in the same ordering by calendar index. Its allocated turnover is computed from prior completed-session implied free-float shares (1346-1359).

## Exact-history requirements and left truncation

For each requested 20/60/120 pre-gap raw VAP window, the code selects unique sessions with `minute_count == 241` and `hard_valid`, and emits a value only when exactly N sessions exist (1270-1284). Otherwise that N-session variable is NaN; there is no shorter-window substitution.

The all-history decayed proxy has different handling:

- its source map starts at most 120 sessions before gap formation;
- it consumes whatever mapped pre-attack history exists;
- it requires nonempty history and rejects session totals that are NaN or negative (1285-1292);
- it does not impose an explicit minimum number of sessions and does not explicitly require `minute_count == 241` in `_inventory_features` for this decayed path;
- `_build_vap_year` requires hard-valid daily rows and matching lineage but does not use `minute_count == 241` as a SQL filter (948-979);
- there is no binding `left_truncated` or `history_length` feature/flag in the V7 runner.

## Zero, null and aggregation behavior

The code fills absent z bins in the local histogram with 0.0 (1297). It then computes:

`overhang_support_ratio = (inside + above) / max(support, 1e-12)` (1302-1309).

Therefore:

- if support is zero and numerator is positive, the ratio is a large finite value;
- if inside, above and support are all zero, the ratio is finite zero;
- a fixed `RATIO_Q30` or `INSIDE_Q30` rule evaluates such finite zeros as numeric values, subject to its TRAIN quantile threshold.

If the local density mean is zero, `_safe_div` returns NaN for density-relative fields (1258-1259, 1297-1313). `gap_lvn_score` and `above_u_lvn_score` remain NaN in that case. Because `vacuum_score` requires all four components to be finite, this all-zero-density case does not receive a finite vacuum score (1437-1455).

When `_partial_attack_start_bins` lacks prior implied float shares, it sets per-minute `allocated_float_turnover` to NaN before a pandas group-by sum (1350-1359). The source does not pass `min_count=1` to that sum; reviewers should account for pandas' default all-NaN sum behavior when tracing whether a grouped value becomes zero. Similarly, later pandas group-by sums in `_inventory_features` do not specify `min_count` (1290, 1331-1335).

## POC and HVN

`POC_Z` is the center of `density.idxmax()` (1314-1316). Because density is reindexed with zero-filled bins, ties follow pandas index order; if every bin is zero, the first bin is the literal `idxmax` result.

HVN construction (1317-1323):

1. retain only strictly positive-density bins;
2. compute their 70th percentile density;
3. treat bins at or above that cutoff as HVNs;
4. take the nearest eligible bin center above L or above U.

If there is no positive-density bin, the HVN cutoff and both distances are NaN.

## Vacuum score

The four components are (1437-1454):

1. low decayed inventory inside the gap;
2. low decayed inventory above U;
3. high gap LVN score;
4. low overhang/support ratio.

For each board and attack date, the code compares today's values with rows from strictly earlier attack dates. It requires at least 30 historical rows and requires all four current component ranks to be finite. The final score is their equal mean. No fitted weight appears in this function.

## NaN treatment by downstream consumer

- Fixed/generated simple hard conditions: `_condition_mask` coerces numeric values and combines every comparison with `value.notna()`; NaN is false (2382-2398).
- Vote rules: a missing condition contributes false and can pass only if the remaining true votes still meet `minimum_votes` (2401-2413). The targeted test at lines 22-35 demonstrates a two-of-two missing value fails.
- Vacuum score: NaN unless all four components are finite (1437-1455).
- Fixed quantiles: pandas quantiles ignore NaN; a non-finite threshold marks the fitted rule invalid (2416-2443).
- Distilled LightGBM leaf construction: model inputs are median-filled and then remaining NaNs are filled with zero before fitting; the final distilled leaf is applied as ordinary hard conditions, which reject NaN (2537-2552).
- Shallow tree and sparse-logistic diagnostics use median imputation; LightGBM ceiling passes NaN natively (2843-2885).
- Portfolio tie-break sorts NaN rank fields last (3471-3474).

## Economic quantities kept distinct in code

The numerator of `overhang_support_ratio` combines decayed turnover inside `[L,U)` and above U `[U,U+W)`. The denominator is decayed turnover immediately below L `[L-W,L)`. They use the same turnover proxy and decay but represent different price regions (1297-1309).

The code labels these as a proxy and does not claim shareholder identity in `vap_methodology_contract` (395-436). Actual realized selling, holder identity, locked-limit latent supply and order-book depth are not observed by this construction.
