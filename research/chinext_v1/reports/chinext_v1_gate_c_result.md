# ChinNext V1 — Gate C bounded correctness pilot

> Input/materialization correctness only. No strategy signal, trade, NAV, or performance was generated.

- GATE_C: `PASS`
- SPEC_ID: `CHINEXT-V1-GATE-C-BOUNDED-CORRECTNESS-PILOT-V1`
- SPEC_SHA256: `bcd4f2d1f3d8ad185ef8558026386859a3dbe7ab87bf23b9ac438caa78ae4bb6`
- SPEC_COMMIT: `7f3fffa2fe4530f73d63216e2ce6c0db92e6f64d`
- GATE_C_REPAIR_COUNT: `3`
- AUTHORIZATION_CLASS: `BOUNDED_EFFECTIVE_STATE_PIT_B`
- STRICT_PIT_A: `NO`
- REVISION_HISTORY_COMPLETE: `NO`
- INPUT_HASHES_VERIFIED: `23`

## Frozen invariant results

| Invariant | Status |
|---|---|
| C-IDENTITY-001 | PASS |
| C-IDENTITY-002 | PASS |
| C-IDENTITY-003 | PASS |
| C-IDENTITY-004 | PASS |
| C-IDENTITY-005 | PASS |
| C-STATE-001 | PASS |
| C-STATE-002 | PASS |
| C-KNOWN-AT-001 | PASS |
| C-SUSPENSION-001 | PASS |
| C-WARMUP-001 | PASS |
| C-CA-001 | PASS |
| C-CA-002 | PASS |
| C-CA-003 | PASS |
| C-AUTH-001 | PASS |
| C-DETERMINISM-001 | PASS |

## Strict pass counts

- AUTHORIZATION_VIOLATION_COUNT: `0`
- DETERMINISM_MISMATCH_COUNT: `0`
- HASH_FAILURE_COUNT: `0`
- REQUIRED_INVARIANT_MISMATCH_COUNT: `0`
- REQUIRED_UNKNOWN_STATE_COUNT: `0`

The 302132.SZ physical-source projection is normalized to the official historical identity 300114.SZ for the bounded target period. The mapping is derived from the hash-bound security master and official alias event; it is not a source-code hardcode. Rights participation and all tested invalid authorization/event paths fail closed.
