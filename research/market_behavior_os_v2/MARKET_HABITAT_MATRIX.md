# Strategy x Market Habitat Matrix contract

The target estimand is `P(strategy behavior | market state)` for multiple
archetypes. Trend direction and breadth discovery are now representation-stable,
so one exploratory CHINEXT study may populate only those two coordinates after
its definitions are frozen. Other cells remain empty.

Each populated cell must report:

- opportunity generation and conversion;
- realized return and hit rate;
- right-tail and severe-loss probabilities;
- drawdown, turnover, and capacity;
- execution quality;
- stability by year and independent temporal block;
- exact sample size, uncertainty, PIT grade, and whether evidence is exploratory
  or untouched validation.

State boundaries may not be selected using the same strategy outcomes used to
populate the cell. Sparse cells remain `INSUFFICIENT_EVIDENCE`; intuition is not
imputation. Latent-mechanism redundancy across strategies must be assessed before
claiming habitat diversification.

| Strategy | Trend state | Breadth state | Volatility/liquidity state | Leadership state | Evidence status |
|---|---|---|---|---|---|
| STRAT-CHINEXT-V1 | Opportunity density supported; more-negative MAE; no final-return/right-tail/failure primary | Opportunity density and MFE>=20% supported; strict B-given-A and conversion fail | UNPOPULATED | UNPOPULATED | EXPLORATORY_PARTIAL; NAV/DD/turnover/capacity counterfactuals unpopulated |
| STRAT-SUPERMIND-V6 | UNPOPULATED | UNPOPULATED | UNPOPULATED | UNPOPULATED | PROGRAM_REPLAY_NOT_DONE |

HAB-CHX-001 used frozen source fields, decision timestamps, opportunity
denominator, continuous estimands, diagnostic state boundaries, BASELINE/A/B/A+B,
right-tail and severe-loss definitions, uncertainty, and temporal blocks. The
A_ONLY payoff cell has only 18 cycles and remains `INSUFFICIENT_EVIDENCE`.
Observed process/payoff association does not identify habitat-specific
counterfactual NAV, drawdown, turnover, execution-cost impact, or capacity.
