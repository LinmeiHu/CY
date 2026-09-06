# Dead ends and invalid branches

Updated 2026-08-30 after resume integrity reconciliation.

## Scientifically rejected directions

- H-003 continuous trend/persistence within entries already admitted by the V1
  MA20 gate: rejected by EXP-P3-002.
- H-005 fast-rotation/leadership-instability mechanism: rejected with
  contradictory signs by EXP-P3-002.
- Breadth as a severe-loss gate: rejected by EXP-P5-001/EXP-P6-001.
- Breadth as an incremental MFE-to-return capture or exit-giveback signal after
  fixed path/year/exit controls: rejected by EXP-P6-001.
- The prior winner-hold exit adaptation remains rejected by its earlier
  2022-2023 evidence and is not revived by the valid mechanism work.

## Invalid rather than rejected

- EXP-P3-001 and EXP-P4-001 were invalidated before execution after bound input
  artifacts changed for correctness.
- EXP-P7-001 was invalidated before execution by an incorrect development warmup
  identity.
- EXP-P7-002 was invalidated before execution by the legacy whole-registry hash.
- EXP-P7-003 produced persisted outputs, but resume reconciliation invalidated the
  branch: its registry-only compatibility exception cannot accept the non-registry
  `replay_engine` change from `9993b4ab...` to `3136edf9...`. The current wrapper
  reproduces the failure before transient materialization.
- EXP-P8P9-001 and `FINAL_REPORT.md` are downstream-invalid, not negative
  scientific evidence, because they consume EXP-P7-003 ledgers.

Do not delete, overwrite, silently repair, or cite an invalid branch as evidence.
