# Volume Exhaustion Bottom V2 — Continuous Dry-Up Falsification

## Environment

- Worktree: `/Users/linmei/Documents/CY-volume-exhaustion-bottom`
- Branch: `research/volume-exhaustion-bottom-v1`
- Starting HEAD: `1171d0eb729b0488cbd2b7978cb01cfeee134cb7` (V1 checkpoint)
- Ending HEAD at analysis: V1 checkpoint; the V2 checkpoint is the commit containing this report.
- All V2 changes are confined to `research/volume_exhaustion_bottom/`.

## V1 question being tested

> Does continuous dry-up have incremental predictive information inside comparable LOW observations?

The LOW universe, PIT input, chronology, entry rule, and forward outcomes are the V1 definitions;
V2 does not redefine LOW or search another threshold/shape.

## Sample

- Signal range: 2020-01-02 to 2026-07-15 (the last date with a complete 20-session outcome).
- Complete LOW observations: 867,579 across 5,154 securities and 1,562 signal dates.
- Comparable matched observations: 807,795 across 1,304 dates.
- Matched cells: 20,194 before de-duplication.
- Fixed 20-session de-duplicated LOW events: 58,494; 1,280 matched cells remain.
- Daily cross-sectional rho uses 1,507 dates with at least 10 LOW securities.

## Primary matching design

For each signal date, LOW observations are placed into a minimum-size-10 cell defined by:

- drawdown bucket: <= -30%, (-30%, -20%], or (-20%, -15%];
- distance-to-low bucket: <=1%, (1%, 3%], or (3%, 5%];
- date-relative liquidity tercile of 20-session median amount.

Within each cell, the unchanged V1 activity ratio (`mean amount over 5 sessions / median amount
over 20 sessions`) is ranked into Q1–Q5, where Q1 is most active and Q5 is driest. The reported
cell spread is the equal-weighted mean of each cell's Q5 minus Q1 mean return. PIT industry is
not put into the primary cell because that would make most cells sparse; it is neutralized in a
separate fixed-cell sanity check.

The secondary residualized check demeans dryness within date × PIT industry × the three coarse
drawdown, distance, liquidity, recent-return, and volatility buckets, requiring at least five
observations per group. It is a transparent fixed-cell residual check, not a fitted alpha model.

## Quintile results (matched LOW observations)

Returns are gross from the next legal open. MFE/MAE are 20-session means.

| Dryness quintile | N | Mean Ret5 | Mean Ret10 | Mean Ret20 | Median Ret20 | Positive Ret20 | MFE20 | MAE20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Q1 most active | 169,694 | 0.124% | 0.443% | 1.604% | 0.313% | 51.19% | 11.30% | -9.07% |
| Q2 | 165,393 | 0.251% | 0.584% | 1.746% | 0.441% | 51.70% | 11.30% | -8.97% |
| Q3 | 161,349 | 0.317% | 0.667% | 1.802% | 0.513% | 52.02% | 11.32% | -8.89% |
| Q4 | 157,469 | 0.342% | 0.675% | 1.730% | 0.495% | 51.89% | 11.28% | -8.90% |
| Q5 driest | 153,890 | 0.230% | 0.532% | 1.556% | 0.259% | 50.96% | 11.33% | -9.11% |

The gradient is not monotonic: performance rises through Q3 then falls in the driest quintile.

## Q5 − Q1

Equal-weighted within-cell spreads:

| Sample | Ret5 | Ret10 | Ret20 | Median Ret20 | Hit-rate Ret20 | MFE20 | MAE20 |
|---|---:|---:|---:|---:|---:|---:|---:|
| All matched LOW observations | +0.060% | +0.115% | **−0.058%** | −0.111% | −0.45 pp | +0.160 pp | −0.104 pp |
| Fixed 20-session de-duplicated events | −0.216% | −0.294% | **−0.177%** | −0.529% | −2.12 pp | +0.307 pp | −0.445 pp |

The de-duplicated result is more adverse, so the V1 spread is not repeated-event counting alone.

## Daily cross-section

Dryness rank is oriented so larger rank means lower activity. Across 1,507 dates:

| Horizon | Mean rho | Median rho | Fraction rho > 0 |
|---|---:|---:|---:|
| Ret5 | −0.0099 | −0.0077 | 47.71% |
| Ret10 | −0.0122 | −0.0122 | 45.12% |
| Ret20 | **−0.0063** | −0.0073 | 46.78% |

The expected positive cross-sectional relation is absent and slightly reversed.

## Time blocks

| Period | Matched Q5−Q1 Ret20 | Mean daily rho Ret20 | Positive-rho days |
|---|---:|---:|---:|
| 2020–2022 | +0.490% | −0.0253 | 38.98% |
| 2023–2024 | −0.657% | +0.0191 | 58.97% |
| 2025–2026 | −0.333% | +0.0005 | 47.57% |

The cell spread changes sign across periods; the positive early spread does not persist.

## Control checks

- Drawdown and distance-to-low are controlled directly in every primary cell.
- Liquidity control is weak and mixed: Q5−Q1 Ret20 is −0.002% in the most-liquid tercile,
  −0.186% in the middle tercile, and +0.042% in the least-liquid tercile.
- PIT-industry neutralization leaves mean daily Ret20 rho −0.0049 and a matched spread of only
  +0.021 percentage points with a +0.02-point hit-rate difference.
- The residualized fixed-cell check has 20,490 observations, 503 dates, and 65 industries;
  residual-dryness/Ret20 correlation is 0.0045. Its Q5−Q1 Ret20 difference is only about
  +0.16 points against a high-mean-return selected cell sample, not an economically persuasive
  incremental effect.
- Recent 20-session return and realized volatility are included in that residualized neutralization.

## Repeated-event check

All LOW observations show a −0.058-point matched Ret20 spread. Retaining only the first LOW
observation for a security until a fixed 20-session cooldown produces −0.177 points. Removing
repeated observations therefore does not reveal a hidden positive dry-up effect.

## Verdict

`FAILS`

The continuous dry-up hypothesis fails the required survival criteria: matched Q5−Q1 Ret20 is
near zero or negative, quintiles are non-monotonic with the driest quintile underperforming Q3,
daily rho has the wrong sign on average, the time-block result changes sign, and industry and
liquidity controls leave no economically meaningful spread. The result also worsens after fixed
20-session de-duplication.

## Economic interpretation

The supported phenomenon is **A: oversold mean reversion**, not **B: incremental volume
exhaustion**. LOW observations rebound on average, especially when drawdown is deep and price is
very near the recent low. Lower recent activity does not independently identify stronger rebounds
once those obvious dimensions are held comparable. Dry trading can represent neglect or weak
demand rather than exhausted supply.

## Next action

Close the volume-exhaustion / “地量见地价” research direction. A separate oversold-ranking lane
could eventually study drawdown depth and distance-to-low as the carrier, but that is outside V2
and is not implemented here.

