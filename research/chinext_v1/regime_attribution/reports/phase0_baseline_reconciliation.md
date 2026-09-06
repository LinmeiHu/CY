# Phase 0 — authoritative CHINEXT V1 baseline reconciliation

## Verdict

**FACT — PASS WITH EXPLICIT LINEAGE LIMITATIONS.** The repository contains one
frozen V1 strategy identity and three authoritative bounded PIT-B baseline blocks
covering 2018-2025. Their configuration objects are equal, their strategy hash is
identical, their transaction cost, board lot, no-replacement, next-open, T+1, and
execution semantics agree, and all frozen ledger hashes match their reports.

No competing strategy is part of the baseline:

- the current-survivor smoke/full-survivor outputs are explicitly non-PIT and are
  excluded from performance attribution;
- Phase 3/4/7/8 and V2 outputs are counterfactual candidates, not V1;
- Phase 9B `O1_WINNER_HOLD` is a rejected candidate; only `O0_BASELINE` is used;
- the PIT 2024-2025 replay supersedes the equal-return current-survivor comparator
  as the authoritative universe lineage.

## Frozen blocks

| Block | Dates | Total return | Max DD | Trades | Win rate | Mean trade | Median trade | Top20 positive-P&L share | Return ex best20 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EXTENDED | 2018-2021 | 64.82% | -20.76% | 194 | 45.36% | 3.05% | -0.97% | 73.52% | -50.16% |
| HOLDOUT O0 | 2022-2023 | -15.52% | -19.34% | 94 | 25.53% | -1.66% | -3.32% | 99.58% | -33.74% |
| DEVELOPMENT | 2024-2025 | 105.24% | -26.23% | 111 | 44.14% | 7.73% | -1.07% | 84.25% | -32.20% |

**EVIDENCE.** The most immediate block-level difference is not merely the median
trade: both profitable blocks still have a negative median. The holdout combines a
much lower win rate, negative mean trade, and near-total dependence on its few
positive trades. This is consistent with right-tail scarcity, but Phase 0 does not
claim market-regime causality.

## Annual portfolio first view

| Year | Portfolio return | Completed cycles | Win rate | Average invested | Source block |
|---:|---:|---:|---:|---:|---|
| 2018 | -3.78% | 11 | 18.18% | 2.88% | EXTENDED |
| 2019 | 23.49% | 47 | 48.94% | 30.13% | EXTENDED |
| 2020 | 5.27% | 74 | 47.30% | 33.74% | EXTENDED |
| 2021 | 31.78% | 62 | 45.16% | 32.83% | EXTENDED |
| 2022 | -17.29% | 37 | 13.51% | 10.74% | HOLDOUT O0 |
| 2023 | 2.14% | 57 | 33.33% | 24.93% | HOLDOUT O0 |
| 2024 | 49.05% | 38 | 31.58% | 23.59% | DEVELOPMENT |
| 2025 | 37.70% | 73 | 50.68% | 57.13% | DEVELOPMENT |

The 2022/2023 trade and exposure rows reuse the existing zero-replay Phase 9C
diagnostic, which reconstructs the frozen O0 ledger. Phase 1 will independently
reconcile all annual metrics from the authoritative ledgers under one fixed
definition.

## Reproduction and integrity evidence

- Strategy SHA-256:
  `dd6198c5169c631c39e906cd6c5f0d9463036e09c15eca69a813df743edfc84a`.
- All nine raw NAV/event/execution hashes matched the frozen reports and are bound
  in `artifacts/baseline_manifest.json`.
- Configuration JSON equality: EXTENDED = HOLDOUT O0 = DEVELOPMENT.
- Filled rows with `execution_date <= signal_date`: `0 / 0 / 0` by block.
- Targeted integrity tests using `PYTHONPATH=src /opt/anaconda3/bin/python`:
  `8 passed in 0.88s`.
- The nested research environment lacked `yaml`, and the root environment lacked
  `pandas`; those two failed collection attempts changed no files or dependencies.

The frozen formal strategies were not rerun or overwritten. Reproducibility here
means byte-identity, manifest/metric integrity, and deterministic reconstruction
contracts, which is the correct treatment for already-consumed one-run artifacts.

## Lineage boundary

**FACT.** These are bounded PIT-B artifacts, not strict archival PIT-A. CY-029,
CY-028, and CY-027 have different authorizations and known-at limitations. The
three NAV blocks also start independently.

**RESEARCH RULE.** Trade records may be pooled only with a `baseline_block` and
source hash. NAV must remain blockwise/calendar-year-specific. An apparent
eight-year compounded return made by chaining the three NAV endpoints would be an
invalid new performance artifact and is forbidden.

## Existing evidence reusable downstream

- 2018-2021 first-view failure decomposition and path/exit lineage;
- 2022-2025 OOS failure attribution and continuation paths;
- 2024-2025 winner attribution and exact entry features;
- 2022-2025 399102 regime audit, temporal matching, and PIT breadth audit;
- existing exit ablations and OOS rejection of winner-hold;
- PIT membership and CY-006 daily facts for new zero-replay derived features,
  subject to each authorization and coverage rule.

These artifacts are inputs/evidence, not permission to copy their conclusions into
the final answer without unified tests.

## Phase 0 conclusion

EXP-P0-001 passes. There is no unresolved baseline conflict. Phase 1 can proceed
without a strategy replay and should locate the first annual differences in trade
tails, ordinary-trade economics, severe losses, holding paths, exits, exposure,
turnover, and concentration.

