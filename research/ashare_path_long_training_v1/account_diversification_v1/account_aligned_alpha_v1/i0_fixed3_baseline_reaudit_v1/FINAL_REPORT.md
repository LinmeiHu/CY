# I0 fixed3 baseline fresh common-contract replay

## Verdict

The 2020 result is category A: S17, S29, S43 and fixed3 all reproduced at economic-state level. The fresh accounts consumed four distinct keyed score files, one common fixed3 positive gate, one canonical start snapshot, the byte-identical archived H10 source, the same action input and the same account engine. No call to `verify_a0` or archived RESULT/NAV shortcut was made.

The same frozen method then executed all four 2021 arms. The 2021 archived fixed3 NAV and every compared ledger/planning value reproduced exactly. No archived 2021 single-seed ledgers exist, so old-versus-new single-seed parity is not claimed for 2021.

## Resource benchmark

A real ten-session fixed3 replay took 16.65 seconds at about one CPU core and 1.04 GB peak RSS. Main MPS throughput was 4.0357 steps/s in the baseline window and 3.9994 steps/s in the overlapping window, a 0.90% reduction. Because this was below the user-set 10% limit, the full replays continued serially.

## 2020 fresh results

| Arm | Fresh return | Expected return | Fresh MaxDD | Ledger parity |
|---|---:|---:|---:|---|
| I0_S17_REBUILT | -2.126700933680% | -2.126700933680% | 26.579577256283% | PASS |
| I0_S29_REBUILT | -2.111644310400% | -2.111644310400% | 20.160141966677% | PASS |
| I0_S43_REBUILT | 9.537234365440% | 9.537234365440% | 14.018310461451% | PASS |
| I0_FIXED3_REBUILT | 17.439616309080% | 17.439616309080% | 15.313437715077% | PASS |

For all four arms, NAV, orders, lot fills, inventory, cashflows, lot inventory, inventory events, lot actions, lots and planning matched their archived counterparts exactly. There is no first divergence.

Common 2020 identities:

- gate: `435dfc7fcbec254bdfcf1e35c8937317cd6f1e0daf7a15fe5609bb7b735ee0e0`
- canonical start: `b6703e6d0905111345100bdadc2eca4638342afce7f6b9d7682b7cc2598a1f2e`
- exec source: `c8ca7753ab365c856ddf947330d62dce92eff52e61bbab11275e4db406283eb7`

Consumed 2020 score hashes:

- S17: `1d680af0f43360dba81a485a84bfd238a77ce2df3e9bb3e912d6afdbfbe1cf20`
- S29: `96ff4c4cf75601420459c4be6858f8a9565bd534005792f58edde044518aac23`
- S43: `f47f9bd637fe55e4f40efe6169fa34c45b7b85663ef52d4056fe9099817cbf9a`
- fixed3: `af254971afc66997abcc380645bacf8ac7c74e81aab5ed2011038436d63e96a1`

## 2021 same-method replay

| Arm | Fresh return | Fresh MaxDD |
|---|---:|---:|
| I0_S17_REBUILT | 52.182514844840% | 13.614642716027% |
| I0_S29_REBUILT | 39.547658695200% | 15.353428968992% |
| I0_S43_REBUILT | 35.758302839400% | 17.155769975917% |
| I0_FIXED3_REBUILT | 48.436607121040% | 14.345785005145% |

The archived fixed3 value was 48.436607121040% with the same MaxDD; all fixed3 economic ledgers and planning matched exactly.

## Status

FRESH_REPLAY_2020 = PASS
FRESH_REPLAY_2021 = PASS
FIXED3_17_4396_REPRODUCED = YES
SINGLE_SEEDS_REPRODUCED = YES
FOUR_ARMS_COMMON_CONTRACT_VERIFIED = YES
FIRST_DIVERGENCE = NONE
RESULT_CLASS_2020 = A
OLD_I0_CACHE_SHORTCUT_USED_FOR_NEW_RESULT = NO
TRAINING_MODIFIED = NO
2022_CANDIDATE_RESULTS_COMPUTED = NO
2023_RESULTS_OPENED = NO
2024_2026_OPENED = NO
PRODUCTION_APPROVED = NO
