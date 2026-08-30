# Hypothesis graph

## Supported inherited nodes

- `RIGHT_TAIL_DEPENDENCE` -> annual V1 economics.
- `BREADTH_PARTICIPATION` -> MFE/opportunity formation.
- `FALSE_BREAKOUT_COMPLETED_TOPOLOGY` -> opportunity-before-adversity order.
- `DAY3_LOSS_LOCALIZATION` and `DAY5_WINNER_LOCALIZATION` -> descriptive early
  held-path separation.

## Falsified edges

- tested medium-horizon trend state -> top-winner probability;
- breadth -> severe-loss protection;
- breadth -> incremental conversion/capture/giveback;
- Day-3 adversity -> additional post-Day-3 failure;
- Day-5 strength/giveback -> additional post-Day-5 persistence/failure;
- signal-day acceptance composite -> opportunity20 versus false breakout;
- fixed RS/compression, industry-RS, chip-base, entry-gap, cohort-crowding, and
  selection-pressure mechanisms -> stable outcomes.

## Open representation nodes

- `TREND_QUALITY`, `TREND_AGE`, `TREND_ALIGNMENT`, `TREND_TRANSITION`,
  `PIT_TREND_EXTREMENESS`;
- `BREADTH_DEPTH`, `BREADTH_ACCELERATION`, `BREADTH_DIVERGENCE`,
  `LEADERSHIP_CONCENTRATION`;
- `FIVE_DAY_SELLING_PRESSURE_DECAY`, `FIVE_DAY_VWAP_RECOVERY`,
  `FIVE_DAY_DEMAND_STRENGTHENING`, `FIVE_DAY_INTRADAY_COMPRESSION`;
- `VOLATILITY_CONDITIONAL_STATE`, `LIQUIDITY_STATE`, `RISK_APPETITE_STATE`.

## Candidate causal graph for falsification

`market habitat` -> `opportunity availability`

`daily/multi-week setup` -> `canonical admission`

`recent five-day intraday structure` -> possibly `setup quality or failure risk`

`signal trigger/acceptance` -> `T+1 entry context`

`post-entry demand persistence and exit mechanics` -> `conversion/capture/giveback`

The minute and daily nodes must compete against daily-bar-equivalent controls.
No open edge is treated as true before a frozen experiment.
