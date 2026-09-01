# A-share evidence-backed depth cycle 010

> Consumed 2018–2023 development evidence only. Post-2023 outcomes and CY-011 were not read.

## Shallow versus deep conclusion

The prior JT-style 12-minus-1 Top-20 result remains adverse for that exact formulation. The matched upper-limit-corrected family is `CHRONOLOGICALLY_UNSTABLE`; the correction was tested directly rather than inferred from the old result.

The prior Low-Idio result remains a proxy. Wan canonical IVOL is `CANONICAL_IVOL_DATA_LIMITED` because PIT RMRF/SMB/HML/WML histories are not registered; MAX/MIN standalone evidence is reported without pretending the mechanism matrix was completed.

## Source and execution contract

Liu, Wu, and Zhu (2022) motivate removal of upper-limit closes and their next trading session; Wan (2018) motivates the IVOL-versus-MAX/MIN separation. Full recovered methods and unresolved source details are frozen in `A_SHARE_DEPTH_CYCLE_010_SOURCE_METHOD.md`.

The monthly domain contains 117,464 eligible rows, 4,368 symbols, and 60 decision dates from 2018-12-28 00:00:00 through 2023-11-30 00:00:00. Signals use completed 15:00 data and no fill before the next legal open; historical board/ST price limits, T+1, suspensions, corporate actions, and 20 bps/side are preserved.

## Revised momentum

| formation | period | conventional top | conventional bottom | conventional spread | revised top | revised bottom | revised spread | spread improvement |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 12m | full | -0.508% | -0.115% | -0.393% | 0.029% | -0.325% | 0.353% | 0.747% |
| 12m | early_2018_2020 | 2.029% | 0.534% | 1.495% | 3.004% | -0.225% | 3.230% | 1.735% |
| 12m | late_2021_2023 | -1.860% | -0.460% | -1.400% | -1.556% | -0.378% | -1.178% | 0.222% |
| 6m | full | -0.968% | 0.361% | -1.330% | 0.116% | -0.203% | 0.319% | 1.648% |
| 6m | early_2018_2020 | 1.203% | 0.453% | 0.750% | 2.909% | -0.356% | 3.265% | 2.515% |
| 6m | late_2021_2023 | -2.123% | 0.313% | -2.436% | -1.373% | -0.120% | -1.252% | 1.184% |
| 9m | full | -1.183% | 0.158% | -1.341% | -0.183% | -0.195% | 0.012% | 1.353% |
| 9m | early_2018_2020 | 1.172% | 0.466% | 0.706% | 2.697% | -0.295% | 2.993% | 2.286% |
| 9m | late_2021_2023 | -2.437% | -0.006% | -2.431% | -1.717% | -0.141% | -1.576% | 0.855% |

Promotion gates: `{'revised_top_minus_bottom_positive': True, 'revised_long_excess_positive': False, 'revised_long_excess_nonnegative_both_blocks': False, 'spread_improvement': True, 'severe_loss': False, 'execution': True, 'dates_each_block': True}`.

Evidence ladder: `{'level_a_mechanism': True, 'level_b_construction_robustness': True, 'chronological_stability': False, 'level_c_long_only_value': False, 'level_d_executable': None}`.

Primary revised-top coverage is 11,667 complete stock-months across 60 dates, with 99.85% next-open executability and median breadth 2132.

## Low-risk / lottery mechanisms

| variable | period | low net | high net | low-minus-high | low excess vs control | low severe disadvantage |
|---|---|---:|---:|---:|---:|---:|
| MAX | full | 0.238% | -0.399% | 0.637% | -0.020% | -4.911% |
| MAX | early_2018_2020 | 1.009% | 0.509% | 0.501% | -0.210% | -4.258% |
| MAX | late_2021_2023 | -0.172% | -0.883% | 0.711% | 0.081% | -5.506% |
| MIN | full | 0.227% | 0.186% | 0.041% | -0.038% | 7.210% |
| MIN | early_2018_2020 | 1.364% | 1.436% | -0.072% | 0.139% | 6.157% |
| MIN | late_2021_2023 | -0.379% | -0.478% | 0.099% | -0.133% | 7.526% |

Low-MAX replay gates: `{'long_excess_positive': False, 'both_blocks': False, 'severe_loss': True, 'execution': True, 'dates_each_block': True}`.

Low-MAX has 23,348 complete stock-months across 60 dates, 99.92% next-open executability, and median breadth 2132.

The canonical IVOL × MAX/MIN two-way sort, residual challenge, and mapping of internal defensive leads were not run because canonical IVOL inputs failed the data gate.

## Executable replays

No replay was authorized by the frozen gates.

## Optional third family

Not run. Exact left-tail reversal was not recovered; canonical residual momentum remains factor-data blocked.

## Final classifications

- Revised momentum: `CHRONOLOGICALLY_UNSTABLE`
- Canonical IVOL mechanism matrix: `DATA_BLOCKED`
- MAX standalone: `MECHANISM_CONFIRMED_LONG_LEG_WEAK`
- MIN standalone: `CHRONOLOGICALLY_UNSTABLE`
