# HAB-CHX-MINVOLPATH-STRAT-001 — 15:30 minute-path strategy translation

`PARKED_OR_REJECTED_MINUTE_VOLATILITY_PATH_ADMISSION_VETO`.

| Block | Baseline return | Candidate return | Delta | Baseline DD | Candidate DD | Trades |
|---|---:|---:|---:|---:|---:|---:|
| development_2018_2021 | 64.8224% | 82.8733% | 18.0510% | -20.7627% | -15.6259% | 162 / 194 |
| consumed_2022_2023 | -15.5221% | -14.6547% | 0.8673% | -19.3413% | -18.1094% | 89 / 94 |

Compounded block return is 56.0738% versus 39.2385%, a 16.8352% difference.

The market gate becomes available at t 15:30, after the stock signal at t 15:00. It suppresses only new admissions at the existing next-session open; existing positions, exits, allowed-date ranking, T+1 execution, limits, costs, and corporate-action handling remain unchanged.

Both periods are consumed development history for this newly translated rule. No post-2023 or CY-011 data was read.
