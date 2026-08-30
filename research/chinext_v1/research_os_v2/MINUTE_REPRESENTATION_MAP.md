# Intraday and five-day minute representation map

The primary recent trajectory is Day -5 through Day -1. Day -3 and Day -1 are
fixed neighboring horizons for robustness where scientifically relevant; no
clock-time or lookback sweep is authorized.

## Representation families

| Family | Daily descriptor candidates | Five-day trajectory | Fixed robustness | Mechanism role |
|---|---|---|---|---|
| Price path | open-close return; morning/afternoon/final-30m return; high/low time; close location; directional efficiency; smoothness | slope, monotonicity, dispersion, last-minus-first, reversal | auction-inclusive path; broad half-day boundaries | demand quality / distribution |
| VWAP structure | close-VWAP; time above VWAP; volume share while minute typical price/close is above VWAP; VWAP slope; recovery count; longest below-VWAP run; late acceptance | increasing acceptance, shorter below-VWAP duration, faster recovery | 1m versus deterministic 5m; volume-weighted neighbor | demand acceptance / supply exhaustion |
| Selling pressure | downside excursion; downside realized variance; down-minute volume share; selloff depth/duration; recovery speed | declining depth/volume/duration; improving recovery | raw close versus typical-price path | supply exhaustion |
| Buying pressure | upside excursion; up-minute volume share; positive-minute fraction; repeated highs; afternoon demand; close-near-high | rising upside/afternoon/close strength | high/close and broad segment neighbors | demand strengthening |
| Volatility contraction | intraday range; minute realized vol; pullback depth; VWAP-deviation dispersion; oscillation count | contracting level and variability | Day -3/Day -1; 1m/5m | setup quality |
| Volume/turnover path | opening/afternoon/closing volume share; concentration; dry-up; down-volume decay; up/down asymmetry | declining supply volume or changing concentration | amount-share counterpart; turnover only with causal float | supply/demand confirmation |
| Support/resistance defense | tests, penetration, time beyond level, recovery speed/volume | fewer/decreasing penetrations; faster recovery | only objective frozen levels; low/close neighbors | support defense / veto |
| Breakout acceptance | follow-through, pullback, time below reference, breakout volume, VWAP/closing acceptance | predictor only when reference event predates decision; otherwise post-entry attribution | 5/15/30/60m fixed landmarks | trigger confirmation / failure taxonomy |
| Distribution/accumulation proxy | selloff recovery, rally rejection, close/low/high progression, price-volume asymmetry | rising lows/close strength or repeated rally rejection | matched daily-return/range/volume controls | latent accumulation/distribution proxy |

## Primary shape summaries

Five daily values are not flattened into arbitrary minute columns. Each accepted
descriptor may generate only a minimal interpretable set:

- level: five-day mean or median;
- direction: fixed robust slope across Day -5..Day -1;
- monotonicity: fraction of adjacent changes matching the predicted direction;
- endpoint change: Day -1 minus Day -5;
- stability: dispersion around the fixed slope;
- reversal: sign change between early (Day -5..-3) and late (Day -2..-1) change,
  only when preregistered for a mechanism.

Redundant summaries are not automatically independent hypotheses. Outcome-blind
correlation and neighboring-definition audits determine whether one simple
representative should replace a cluster before outcome reveal.

## Multi-scale architecture

The research sequence is:

`market habitat -> daily/multi-week setup -> recent five-day intraday structure -> signal-session trigger`

Minute incrementality must be tested after frozen daily OHLC/amount, V1 setup,
market, breadth, beta/liquidity, year, and any accepted habitat controls. A minute
feature that only rediscovers daily return, range, close location, or volume is
redundant.

## Predictor versus attribution

- Day -5..Day -1 features are pre-signal predictors if their full sessions end
  before the signal decision.
- Signal-day full-path features are predictors only for T+1 or later and were
  tested narrowly by H-021.
- Entry-day bars after the open and post-entry 5/15/30/60-minute continuation are
  explanatory outcomes for later decisions, never justification of the entry.

## Prior evidence boundary

H-021 rejected one signal-day equal-weight composite of signed path efficiency,
time above full-session VWAP, and 10:00 retention from the opening high. It did
not test Day -5..Day -1 trajectories, selling-pressure decay, volatility
contraction across sessions, support recovery progression, late-day-strength
progression, or matched multi-scale incrementality. The intraday family is
therefore `FAMILY_UNDEREXPLORED`, not closed.
