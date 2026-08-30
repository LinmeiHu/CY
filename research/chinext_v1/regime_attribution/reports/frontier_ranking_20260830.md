# CHINEXT V1 independent mechanism-frontier ranking

Frozen before any new stock-trajectory feature was joined to a trade outcome.
The ranking is for information value, not for expected backtest improvement.

## Controlling scientific boundary

H-004 is `PROSPECTIVE_VALIDATION_PENDING`. Its historical conclusion is frozen:
breadth primarily describes opportunity generation, not capture, exit, timing,
severe-loss, or overlay value. EXP-P7-003 remains invalid; Phase 8/9 and
`FINAL_REPORT.md` remain downstream-invalid. None is a future research obligation.

## Candidate frontiers

The qualitative ranks combine expected information gain, importance to V1
economics, PIT-valid availability, falsifiability, independence, reuse value,
implementation cost, and data-mining risk. `1` is the highest executable priority.

| Rank | Frontier | Information/economic value | PIT availability | Independence / falsifiability | Cost and mining risk | Decision |
|---:|---|---|---|---|---|---|
| 1 | Winner/loser pre-entry trajectory archaeology | Directly addresses the 73.6% positive-P&L share from 39 winner20 cycles and the -1.81m from 213 false breakouts | PASS: 399/399 cycles have complete hard-valid T-60..T-1 windows after an outcome-blind audit | High; tests stock-level transitions rather than another market breadth rule | Moderate implementation, low search risk under four frozen transitions | SELECT |
| 2 | Severe-loss pre-entry formation | Important for loss understanding, but 44 severe losses are not the main cross-year economic driver and breadth downside gating is already rejected | Same stock panel is available | High; can be tested as an adverse-outcome falsification in Rank 1 before a separate family | Low incremental cost, but a separate screen would duplicate Rank 1 | EMBED AS FALSIFICATION |
| 3 | Post-entry right-tail path formation | Important because winner50 cycles peak late, but current evidence already rejects breadth exit/timing modification and post-entry states risk outcome conditioning | Frozen holding paths are available; counterfactual post-exit paths are unavailable | Medium; causal interpretation is limited by the strategy's exit rule | Moderate cost and high modification temptation | DEFER |
| 4 | H-006 cross-sectional right-tail/dispersion refinement | One Phase 3 survivor suggests possible opportunity-set information | Existing daily feature family is available | Lower independence from breadth/opportunity and high search-history burden after a 93-feature screen | Low cost but elevated multiple-testing risk | DEFER PENDING NEW MECHANISM |
| 5 | Stock-vs-industry strength and industry leadership | Economically plausible and reusable | Industry labels are usable only where their source notice is PIT-valid; coverage and taxonomy limitations remain | Potentially independent, but classification stability requires a dedicated audit | Moderate/high data-governance cost | DEFER |
| 6 | Execution/portfolio interaction attribution | Could explain portfolio realization differences | Frozen ledgers exist | Less direct for why individual right-tail trades form; no new execution defect is evidenced | Moderate cost | DEFER |
| unavailable | Prospective H-004 confirmation | Highest confirmatory value for the frozen breadth result | No future untouched PIT-A sample exists yet | Cleanly falsifiable when future data arrive | Cannot execute now without opening or inventing data | WAIT FOR FUTURE DATA |

## Selected question

Do extreme winners enter through a repeatable stock-level state transition in
which market-relative strength improves into the signal while volatility, trading
range, and downside-session traded-amount share contracted earlier? The minimum
sufficient experiment will compare fixed outcome groups, use four primary
transition definitions, control for fixed V1 entry features and market/breadth
state, and attack year, block, security, industry, tail, beta, liquidity,
holding-duration, and exit-lineage explanations.

Observed differences will not be converted into filters or strategy rules.
