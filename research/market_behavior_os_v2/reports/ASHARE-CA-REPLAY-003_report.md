# Minimum corporate-action execution repair and frozen replays

## Execution contract

QD-010 `known_at` is the conservative next calendar day after announcement. A known share distribution or rights event blocks new risk and triggers an existing-position close decision; the first legal later open must occur strictly before `effective_date`. Cash-only actions retain exact ledger treatment.

The bounded input contains 2,904 risk events; 0 lack a pre-effective decision session and remain fail-closed.

## Frozen portfolio results

| Family | Classification | Total | Annualized | Max DD | Sharpe | Calmar | Severe | Turnover | Trades | Forced exits | Entry coverage |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| industry_diffusion_20 | PROMISING_BUT_MIXED | 54.64% | 8.60% | -29.10% | 0.440 | 0.296 | 18.46% | 165.52x | 2627 | 15 | 99.89% |
| low_idiosyncratic_volatility_20 | PROMISING_BUT_MIXED | 15.73% | 2.80% | -29.11% | 0.239 | 0.096 | 6.09% | 142.22x | 2628 | 11 | 99.92% |

## Comparison

Daily return correlation is 0.671. Industry diffusion mean breadth is 39.4 positions / 12.4 industries; low idiosyncratic volatility is 39.4 / 18.4.

## Research portfolio

1. Open independent stock-level intraday mechanisms for the highest new information gain per unit cost.
2. Preserve Industry Diffusion as mixed return/left-tail evidence requiring genuinely independent confirmation, not a risk-threshold rescue.
3. Preserve Low Idiosyncratic Volatility as a mixed defensive lead requiring independent confirmation.
4. Preserve the existing CHINEXT RS veto; keep dispersion resource-parked and Industry Rotation closed.
5. Close this execution repair: it is sufficient for these replays and should not expand into a general corporate-action platform.

All 2018--2023 data are consumed development history. Post-2023 and CY-011 remain unread; no OOS, validation, live, or strict PIT-A claim is made.

- Spec: `db71f4d03eefcba4f5e2b8c75913ddc1f92d475362a8cd91971ecd325145c90b`
- Equity: `b6bb0d84bf772907da000ae51f323525cf0c8d69ec4e0a006a5b04d9bb2fb3c1`
- Risk exits: `0d4d6e86ff017e52d775ba4cad8f743c78f9b8222c01bfc6af3ea584e5a2cbd8`
