# ChinNext V1 Phase 7 — pre-registered exit-module ablation

E0 is frozen and not replayed. Exactly two new formal PIT-B replays were run in order E1 → E2.

Spec SHA256: `dad98d9c21e1ea411b2989d28514a8d0adde20043cd799c3f8b8d551b94e9410`
Strategy SHA256: `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`
PIT manifest: `8b4519ff6cf74aa0ca13b15bd3954cce3a37f6dd19d25f3f77743e9a974e75f7`

| Arm | Return | Max DD | Trades | Win rate | Avg holdings | Avg invested | Top20 concentration | Return ex best20 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E0_FROZEN_PHASE1B | 1.052422 | -0.262272 | 111 | 0.441441 | 4.0515 | 0.403915 | 0.842544 | -0.321953 |
| E1_INDIVIDUAL_EXIT_DISABLED | 0.946773 | -0.253728 | 82 | 0.439024 | 4.1814 | 0.415245 | 0.889176 | -0.312157 |
| E2_MARKET_EXIT_DISABLED | 0.917226 | -0.173911 | 99 | 0.404040 | 5.1546 | 0.515746 | 0.846431 | -0.508574 |

E1 disables individual MA30×2 at its causal source and therefore suppresses its downstream forced-exit membership removal. E2 disables only market/system exit; market entry remains active. All other universe, entry, sizing, cost, execution, and date semantics remain frozen.

E1/E2 differences include portfolio-path effects (holding duration, vacancy, future opportunity) and are not exposure matched.

INDIVIDUAL_EXIT_ROLE: TRADEOFF
INDIVIDUAL_EXIT_EVIDENCE_STRENGTH: MODERATE
MARKET_EXIT_ROLE: TRADEOFF
MARKET_EXIT_EVIDENCE_STRENGTH: MODERATE

PHASE7_RESULT: PASS

## Episode audits

- E1 generic (34): `{"baseline_episode_count": 34, "continued_after_baseline_exit_count": 22, "end_of_test_count": 0, "later_market_exit_count": 22, "not_recaptured_due_to_portfolio_path_count": 12, "recaptured_count": 22}`
- E2 market (77): `{"baseline_episode_count": 77, "continued_after_baseline_exit_count": 54, "end_of_test_count": 0, "later_market_exit_count": 0, "not_recaptured_due_to_portfolio_path_count": 15, "recaptured_count": 62}`

Losers use frozen definition realized_return <= 0. Winner capture uses same symbol + same frozen entry episode. Differences include portfolio-path effects.
