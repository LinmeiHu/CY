# Phase 2 — outcome-blind PIT regime feature library

EXP-P2-001 passed. The artifact contains only completed-close market-state features and lineage fields; no trade outcome, NAV return, P&L, MFE, MAE, exit reason, or holding duration was read.

## Reconciliation and causal boundary

- Daily rows: `1942` (`2018-01-02..2025-12-31`)
- Feature columns: `93`
- V1 basic-eligible count mismatches: `0` across `1942` sessions
- Eligible range: `0..1055`; cross-sectional features fail closed on `184` sessions below 100 names
- Completed-close `t` is available at 15:00 Asia/Shanghai and is applicable only to a later causally valid session.
- The 2018-2021, 2022-2023, and 2024-2025 stock histories reset at their frozen replay warm-up boundaries; no history is carried across evaluation blocks.
- Formal strategy replays: `0`; trade outcomes read: `0`; only `trade_date` and `basic_eligible` were projected from daily NAV for denominator validation.

## Feature families

| Family | Features | Minimum daily coverage |
|---|---:|---:|
| breadth | 16 | 84.96% |
| dispersion_or_volatility | 26 | 90.53% |
| index_trend_or_liquidity | 20 | 100.00% |
| liquidity_participation | 5 | 84.96% |
| risk_appetite | 7 | 90.53% |
| rotation_persistence | 7 | 88.21% |
| style_relative_strength | 4 | 100.00% |
| volatility | 8 | 100.00% |

## Governance

The denominator is the exact frozen V1 basic-eligible universe, not raw membership and not current survivors. Rows must pass all frozen hard-validity, trading-state, corporate-action, availability, age, accumulated-180-valid-observation, 121-session-contiguity, and 20-session liquidity requirements. The daily denominator matches the authoritative V1 ledger on every session.

Security returns use a causal continuous coordinate. On a visible supported action day, the prior close is transformed as `(prior_close - cash_per_share) / share_multiplier`; nonzero rights participation, blocking actions, gaps, or unknown required lineage fail closed. The frozen V1 adapter's normalized null no-rights fields are zero only on rows whose action-validity and nonblocking flags are affirmative. No normalization, clipping, or tolerance relaxation is used.

Cross-sectional features require at least 100 eligible securities and 95% usable observations. Industry features additionally require 80% mapped coverage; rotation rank features require 80% same-symbol matching. Missing requirements produce nulls, not substitutes.

## Explicitly unavailable or limited

- Growth/value and a true PIT market-cap small/large factor are unavailable.
- High-beta/low-beta remains deferred pending a separately validated causal rolling-beta implementation.
- Fund flow, sentiment, and a governed cyclical-sector mapping are unavailable.
- `399102-CSI300` and `399102-399006` are observed index-spread proxies only.
- All inputs are bounded PIT-B rather than strict archival PIT-A.

## Outcome-blind verdict

The library is frozen for Phase 3 attribution. Phase 2 makes no claim about which features explain returns and selects no regime threshold or strategy rule.

Feature artifact SHA-256: `5fe1ec1cb1bdfa922dd838bd1f559de9463d4926f56dfed09427d826c7465bc6`
