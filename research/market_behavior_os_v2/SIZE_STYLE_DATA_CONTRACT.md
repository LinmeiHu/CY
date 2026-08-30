# Size/style data contract

Frozen before MKT-STYLE-DATA-001 derives a size value. This contract determines
whether the registered PIT-B daily source can support a narrower
`circulating-market-value size` representation.

## Governed source

- CY-006 daily PIT-B v2, exact 2018--2023 partitions under manifest
  `de8795f2...`.
- QD-009 is the upstream announcement-aware Capital history. Both effective and
  announcement dates must be no later than the decision timestamp; the latest
  causal revision wins and nonpositive values fail closed.
- CY-006 exposes `circulating_shares`. It does not expose QD-009's separate
  `freeFloatCapital` field.
- Price is raw/unadjusted completed-close CNY. Shares are circulating shares.
  Their product is CNY circulating market value.

The product must not be called total market capitalization, true free-float
capitalization, enterprise value, or an investable float weight. No present-day
share count or corporate-action-adjusted future coordinate may replace it.

## PIT and availability semantics

Every contributing row must pass `hard_valid`, `bar_valid`, `float_valid`,
`corporate_action_valid`, `market_rule_valid`, and `historical_identity_valid`.
`available_at <= decision_at` is mandatory. `float_effective_date`,
`float_announced_date`, and `float_available_date` may not exceed the trade date.
Close and circulating shares must be finite and strictly positive.

The derived size becomes available only with the completed session at 15:00
Asia/Shanghai. A later-session application would be required for any eventual
action, but this audit creates no action.

## Exact audit gates

- exact registry, CY-006 manifest/partition, CY-006 audit, and QD-009 manifest
  identities;
- exact 6,155,390 source rows over 2018-01-02..2023-12-29, with zero duplicate
  symbol/date keys and zero `available_at > decision_at` rows;
- zero hard-valid rows with invalid component flags, future float lineage,
  missing/nonpositive/nonfinite close or shares, or invalid circulating value;
- for hard-valid positive-volume rows, turnover fraction must equal
  `volume / circulating_shares` within absolute tolerance 1e-12;
- each market view/denominator/date used by research must meet the frozen
  population minimum (ALL_A 1000, SH_A 400, SZ_A 400, CHINEXT_BOARD 200), or the
  date/view fails closed rather than being imputed;
- no post-2023 partition and no unregistered input.

Passing makes circulating-market-value size available for a representation map.
It does not establish that size matters economically, that it is a complete
style taxonomy, or that any size bucket predicts returns. Growth/value,
profitability, investment, high/low beta, total capitalization, true free-float
capitalization, fund flow, sentiment, strategy outcomes, and CY-011 remain
unavailable or prohibited.

## MKT-STYLE-DATA-001 result

All frozen gates pass. The exact 6,155,390-row source has zero duplicate,
time-travel, component, float-lineage, size-product, turnover-unit, or decision-
time failures. All eight view/denominator groups meet their population floors on
all 1,457 dates. Circulating value spans CNY 218.8 million to 3.267 trillion,
with median CNY 4.042 billion.

Two executions are byte-identical: result `a03954d6...`, report `7c1511fd...`.
This permits a circulating-market-value size representation map only; every
explicit nonclaim above remains in force.
