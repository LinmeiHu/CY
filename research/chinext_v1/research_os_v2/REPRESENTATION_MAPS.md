# Representation maps

`TESTED` means the exact representation has prior evidence. `MAPPED` means it is
an economically distinct representation eligible for outcome-blind construction;
it is not a claim of usefulness. `UNAVAILABLE` means governance or data prevents
formal use today.

## Design lesson from frozen SuperMind V6

Frozen source SHA-256:
`7fa9d715bdf4c352526d556132f8ec8502e9f355876100f357c8bdc5fdc91f33`.

V6 does not treat “consolidation” as one indicator. Its FULL40 setup requires four
different economic measurements over completed pre-signal data:

- range containment: prior-40 high/low width;
- structural convergence: prior-day MA5/10/20/30 dispersion;
- path quality: directional efficiency, endpoint displacement divided by total
  path length;
- volatility structure: 10-day versus 60-day realized-volatility ratio.

It then adds distinct roles: B60 breakout trigger, MINVOL location as a supply-
dry-up location test, full-cross-section 20/60/120 RS as ranking quality, a market
entry gate, and separate exit mechanics. The lesson is not its thresholds. The
lesson is that one behavior should be triangulated by independent dimensions and
roles before combination.

## Trend

| Dimension | Absolute state | PIT historical normalization | Relative state | Prior status |
|---|---|---|---|---|
| Direction | return 20/60/120 | rolling percentile and robust z of each return | 399102 minus 399006/CSI300 return | 60d `TESTED`; others screened |
| Strength | close/MA20/60/120; normalized log slope | rolling percentile/z of distance and slope | slope/return spread versus alternative indices | MA60 and MA20 slope `TESTED` |
| Quality | efficiency 20/60/120; regression R2; path drawdown; upside/downside path asymmetry | rolling percentile/z of quality | quality difference versus alternatives | `MAPPED` |
| Persistence | fraction above MA20/60; current run length; positive-return duration | rolling percentile of run/fraction | persistence advantage versus alternatives | fraction20 `TESTED`; run length `MAPPED` |
| Age | sessions since up-cross/onset; sessions since last state transition | expanding/rolling percentile of age | age difference across indices/styles | `MAPPED` |
| Alignment | sign agreement of 20/60/120 returns; above-MA20/60/120 count | historical percentile of alignment duration | alignment advantage | `MAPPED` |
| Transition | return/slope/efficiency change; acceleration/deceleration; cross event | percentile/z of change | relative strengthening/deterioration | state flips `TESTED`; broader map `MAPPED` |

The first build uses broad horizons only where they are economically distinct. It
does not count every nearby lookback as an independent representation.

## Breadth

| Dimension | Absolute state | PIT historical normalization | Relative/conditional state | Prior status |
|---|---|---|---|---|
| Participation | fraction above MA20/60/120; positive return 20/60 | rolling percentile/z | breadth conditional on trend quality | MA20/return20 supported exploratory |
| Depth | nested MA5/10/20/60/120 participation profile; A/D balance | percentile of profile/depth | participation minus index direction | partly screened |
| Extremes | new-high60, new-low60, upside/downside tail fractions | rolling percentile/z | high-minus-low asymmetry | screened, not family-tested |
| Momentum | change5/change20 | percentile/z of change | change beyond index acceleration | change20 supported exploratory |
| Acceleration | change5 minus scaled change20; second difference | percentile/z | acceleration conditional on level | `MAPPED` |
| Stability | flips20, volatility10, persistence duration | historical extremeness | stability conditional on trend age | flips contradicted simple prediction |
| Divergence | breadth trend minus price trend; new-high breadth versus index high | rolling percentile of divergence | explicit breadth-price relative state | `MAPPED` |
| Leadership concentration | top-N share, industry concentration, effective number of leaders | rolling percentile/z | narrow versus broad leadership | `MAPPED`, data audit needed |

## Breakout and consolidation

| Role | Economically distinct representations | Prior boundary |
|---|---|---|
| Reference/trigger | canonical prior-60 close high; breakout margin; close location | canonical trigger frozen; no threshold search |
| Geometry | box width; high/low slopes; higher lows/lower highs; range position | fixed pivot topology unstable; other geometry not thereby rejected |
| Compression quality | MA convergence; directional efficiency; regression R2; realized-vol compression | V1 lacks full V6-style triangulation; fixed RS/compression composite failed |
| Volume/supply | volume dry-up; downside amount/volume decay; minimum-volume location/age; breakout expansion | fixed downside-amount transition and MINVOL support failed |
| Relative quality | stock-market, stock-industry, industry-market RS level/slope/acceleration/persistence | exact tested decompositions rejected; wider map open |
| Supply/demand | overhead supply, chip concentration, trapped-holder structure, migration | one fixed chip composite rejected; locked validation untouched |
| Follow-through/failure | immediate rejection, delayed failure, no follow-through, market/industry-driven failure | completed topology supported; causal taxonomy incomplete |
| Sequence | RS improvement -> compression -> seller exhaustion -> higher lows -> breakout | `MAPPED`; examples are hypotheses, not facts |

## Volatility, dispersion, correlation, and liquidity

| Concept | Absolute state | PIT normalization | Relative/conditional state | Prior status |
|---|---|---|---|---|
| Volatility | realized 10/20/60; ATR%; downside vol | rolling percentile/z | short/long ratio; conditional on trend/breadth | absolute screen only; interaction open |
| Volatility transition | contraction, expansion, vol-of-vol | percentile of change | contraction -> expansion sequence | `MAPPED` |
| Dispersion | cross-sectional std, p90-p10, skew, tails | rolling percentile/z | upside versus downside dispersion | screened; right-tail incrementality rejected |
| Correlation | mean/median stock-market and pairwise/industry correlation | rolling percentile/z | correlation conditional on breadth/dispersion | `MAPPED`, feasibility audit needed |
| Liquidity | total/median amount, amount/MA20, participation | rolling percentile/z | stock/market or leader/follower liquidity | partial screen/control only |
| Risk appetite | limit-up/down and large-move fractions, upside/downside balance | rolling percentile/z | risk state conditional on trend/breadth | partial screen only |

## Relative strength

| Dimension | Stock vs market | Stock vs industry | Industry vs market | Prior status |
|---|---|---|---|---|
| Level | 20/60/120 excess or rank | 20/60/120 residual | 20/60/120 peer return spread | partial tests |
| Slope | change in RS over fixed window | same | same | `MAPPED` |
| Acceleration | change of slope | same | same | `MAPPED` |
| Persistence | duration/fraction of positive RS | same | same | `MAPPED` |
| Age | sessions since RS transition | same | same | `MAPPED` |
| Sequence | RS improvement before compression/breakout | same | leadership before stock strength | fixed T-20/T-1 improvement failed alone |

## Holding path and failure

| Concept | Snapshot | Trajectory/sequence | Prior status |
|---|---|---|---|
| Winner formation | Day-5/10/20 return, MFE | time to MFE, market/stock decomposition | descriptive separation supported; persistence rejected |
| Severe-loss formation | Day-2/3/5 adverse relative return | residual failure after landmark | Day-3 localization supported; persistence rejected |
| False breakout | label and giveback | MFE-before-MAE order, boundary-clean topology | completed-path topology supported |
| Capture | realized/MFE ratio | capture evolution and exit lineage | breadth incrementality rejected |
| Giveback | MFE minus realized; close-peak giveback | early giveback then residual failure | tested persistence rejected |
| Exit | exit reason/duration | counterfactual continuation/stop path | counterfactual path not established |

## Unavailable or governed-deferred representations

- strict PIT-A universe and supplier revision vintages;
- historical full-depth order book, queue, tick, cancellation, and participant
  identity;
- true PIT size and growth/value factors;
- fund flow and sentiment;
- rolling beta until causal implementation and coverage are validated;
- locked CY-011 2024-2026 validation values.
