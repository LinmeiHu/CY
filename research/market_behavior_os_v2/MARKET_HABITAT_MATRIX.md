# Strategy x Market Habitat Matrix contract

The target estimand is `P(strategy behavior | market state)` for multiple
archetypes. The matrix is deliberately empty until the Market State Engine has
frozen dimensions and a strategy has timestamp-reconciled opportunities.

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
| STRAT-CHINEXT-V1 | UNPOPULATED | Qualified participation clue only | UNPOPULATED | UNPOPULATED | ENGINE_NOT_FROZEN |
| STRAT-SUPERMIND-V6 | UNPOPULATED | UNPOPULATED | UNPOPULATED | UNPOPULATED | PROGRAM_REPLAY_NOT_DONE |
