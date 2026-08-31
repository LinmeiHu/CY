# WORKER-QA-001 adversarial formation-depth replication

## Decision

`PASS_ORTHOGONAL_REPLICATION`

The accepted formation-depth chain is reproduced from its compact bound
artifacts by an estimator written independently in this packet. No primary
runner was imported or invoked. This is replication evidence only; it creates
no alpha, habitat, strategy, causal, or execution claim.

## Reconstructed chain

| Experiment | Independent classification | Response rows | Max absolute error |
|---|---|---:|---:|
| ATTR | `INCREMENTAL_OBJECTIVE_FORMATION_TAIL_RISK` | 200 | 3.33e-16 |
| PROP | `LOCALIZED_CROSSER_DOWNSIDE_TOPOLOGY` | 648 | 7.77e-16 |
| CLOSE | `ACCEPTED_AND_REJECTED_CROSSER_DOWNSIDE` | 648 | 6.66e-16 |
| PATH | `MIXED_PREOPEN_AND_INTRADAY_DOWNSIDE_PATH` | 680 | 9.99e-16 |
| IMMED | `NO_STABLE_TROUGH_IMMEDIACY_SHIFT` | 184 | 3.33e-16 |

All 2,360 response-audit rows matched their authoritative counts and statistics
within the frozen `5e-12` tolerance. All 288 ATTR pairwise/joint-geometry rows
also matched; their maximum absolute error was 2.22e-16. Every independently
rebuilt headline statistic, gate outcome, and classification agreed.

Selected cell-level h=3 scalar checks also agreed, including ATTR PIT partial
rho, PROP crosser downside, CLOSE rejected-crosser downside, PATH accepted-arm
pre-open path, and IMMED first-trough share. The complete selected cases and all
row-level replays are in `result.json` and the independent audit CSVs.

## Lineage and PIT audit

- Every frozen spec input binding and every result-bound spec/panel/audit/runner
  hash matched; mismatch count was zero.
- Four ignored predecessor control artifacts used only for ATTR lineage hash
  verification were absent from the fresh worktree. Their bytes were verified
  read-only at the Director artifact store, and each alternate physical root is
  explicitly labeled `director_artifact_store` in `result.json`. Their values
  did not enter the response replay.
- All five compact panels have unique `(trade_date, market_view, denominator)`
  keys, exactly eight cells, exact 15:30 availability, and no event year after
  2023.
- Each result declares the joint clock as 15:30 Asia/Shanghai and the response
  start as the next exchange session.
- Raw QD-004/CY-008, raw minute data, CY-011, post-2023 data, and strategy
  outcomes were not read.

## Determinism and resources

Two full runs produced byte-identical `result.json` plus all five independent
audit CSVs. Focused tests passed (`2 passed`) and Ruff passed. The measured full
run took 2.95 seconds, used 158,810,112 bytes maximum RSS (151.45 MiB), incurred
zero swaps and zero page faults, and ran with every configured numerical thread
pool fixed to one. This is well below the 1.5 GiB worker ceiling.

## Artifact identities

- canonical `result.json`: `4153e154ccef627d64f70740f050bd50a5cad25d97fd0624723f05469e7038d8`
- ATTR audit: `b2b0884c365974dd7762fefbfc45447e7d7743bb14286064a32d6e8aa86829a9`
- PROP audit: `90410855133ed1587452cf3aabf87da548c1d1f2bddd032db74e1c6444fa6988`
- CLOSE audit: `9ea547d72bc096942176cdfe535b079b8968a235446083c53ba9e61661eb047e`
- PATH audit: `0f559250843c70a3ebc936397197d2c32e36e1ccadbe5a896c6a73579a30bb86`
- IMMED audit: `0ea1c1aa99ecbacc7e08aef3f1fcfa362d1738830dfafebe60857f55884b4c77`

## QA conclusion

No quarantine trigger remains. The compact evidence independently supports the
accepted chain exactly as bounded: formation depth is incremental objective
tail-risk association; downside is localized to crossers; both accepted and
rejected closing arms carry it; both pre-open and trough-session intraday path
components contribute; and the exact first-trough timing shift is not stable.
