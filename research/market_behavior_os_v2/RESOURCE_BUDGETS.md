# Frozen resource budgets

## Host envelope at MKT-MIN-001 preregistration

- Host: 10 logical/physical CPUs, 32.0 GiB physical RAM.
- Observed available RAM: 10.62 GiB before construction.
- Workspace volume: 349 GiB available.
- Required QD-004 files: 15,570,113,859 compressed bytes and
  1,486,577,999 physical rows across 2018-2023.
- Exchange sessions: 1,457; maximum complete five-day market trajectories:
  1,453 per view/denominator.

## Frozen adapter envelope

| Resource | Budget | Abort rule |
|---|---:|---|
| Batch | one exchange date by default | Never increase until a representative measurement proves the larger batch safe |
| CPU | one Python process; no deliberate multi-process scan | Abort rather than competing for essentially all host CPU |
| Process peak RSS | 2.5 GiB target; 3.0 GiB hard ceiling | Fail closed above the ceiling |
| System RAM headroom | at least 8.0 GiB | Do not start the next batch below the floor |
| Compressed QD-004 read | 15.57 GiB one-pass target; 20 GiB ceiling | A second full raw copy or blind rescan is prohibited |
| Temporary disk | 1 GiB ceiling | No raw-minute materialization; remove bounded temporary outputs after validation |
| Durable experiment output | 100 MiB ceiling | Only daily/trajectory panels, audits, results, and reports |
| Full required-scale wall time | 90 minutes ceiling | Reassess/STOP rather than run indefinitely |

At least 25% of physical RAM and 25% of currently available disk are preserved.
The RAM floor is checked between batches. Representative measured throughput,
not the metadata estimate alone, must approve required scale.

## Frozen scaling ladder

1. Tiny: ten accepted AUDIT-MKT-MIN-001 sessions.
2. Small: all 1,200 accepted mapped sessions and their distinct source sessions.
3. Representative: the twenty consecutive sessions from 2020-02-03 through
   2020-02-28, frozen before their full-market descriptors are read, with
   resource telemetry.
4. Required scale: every 2018-2023 exchange date under the unchanged scientific
   and resource contract.

No stage may proceed after semantic disagreement, nondeterminism, resource
ceiling breach, or a projection above the full-scale envelope.

## MKT-SUPPORT-DYN-DATA-001 bounded sample envelope

- 1,920 sequences, 9,600 cohort rows, and 9,575 unique security-sessions.
- Exactly 2,307,575 planned raw minute rows; annual date/symbol/column pruning.
- One process; 20 GiB compressed-read, 3 GiB RSS, 1 GiB temporary-disk,
  100 MiB durable-output, and ten-minute wall ceilings.
- At least 8 GiB system-memory headroom between annual reads; no raw-minute
  materialization or duplicate raw dataset.
- Prefreeze host check: 349 GiB free disk and more than 8 GiB free memory.

MKT-SUPPORT-DYN-DATA-001 is invalid before minute access: uncapped daily SQL
peaks at 11,135,991,808 bytes RSS; exact 2-GiB-memory SQL peaks at
2,698,985,472 bytes but needs 8,787,951,616 bytes spill. The 002 retry keeps all
ceilings except disposable temporary disk, which is frozen at 10 GiB in an
isolated directory removed before minute reads. This remains below 3% of the
349-GiB prefreeze free disk and preserves the 25% disk-headroom rule.

The 002 first annual minute request materializes 2,849,825 rows for 384,395
required 2018 rows and breaches 3 GiB. The 003 retry preserves the 2-GiB daily
memory/10-GiB disposable-spill settings and batches raw minutes by the frozen
five-session block. Its exact complete raw-row budget is 2,307,575, and every
block table must be released before the next.

The inherited 2-GiB daily setting still leaves insufficient lifetime peak
margin in 003. The final 004 setting is 1.5 GiB: measured daily plus first-block
peak 2,144,124,928 bytes, available memory 12,700,811,264 bytes, and live spill
9,155,805,184 bytes. The existing 3-GiB RSS, 8-GiB headroom, and 10-GiB spill
ceilings do not change.

MKT-SUPPORT-DYN-DATA-004 completes all 48 blocks twice without exceeding those
ceilings. It reads exactly 2,307,575 complete raw rows and produces byte-identical
durable artifacts. Any temporal representation that reuses this sample must
retain the 1.5-GiB daily limit, exact block batching, reference-equivalence gate,
and release-between-block behavior; it may not expand the raw data envelope.

MKT-SUPPORT-DYN-001 reuses the immutable 004 coordinate artifact and block-pruned
raw reads, so no daily spill is recreated. Each final run completes in about 50
seconds, reads exactly 2,307,575 rows, and writes about 15.2 MB. The inherited
3-GiB RSS, 8-GiB system-headroom, 20-GiB read, 100-MiB durable-output, and
ten-minute ceilings all pass.

MKT-SUPPORT-LVL-DATA-001 reads durable panels only, completes in under three
seconds, reads zero raw partition rows, and writes under 1 MB. Its 1-GiB RSS,
8-GiB headroom, 10-MiB output, and one-minute ceilings pass twice.

MKT-BREAKOUT-DATA-001 reuses the exact 1.5-GiB daily-coordinate, 10-GiB
disposable-spill, and fixed `(year, block_id)` minute batching envelope. It reads
exactly 2,307,575 complete raw rows, preserves the 3-GiB RSS/8-GiB headroom/
ten-minute ceilings, and writes 4,742,204 bytes. Two full executions complete
inside the envelope with byte-identical outputs; no raw dataset is materialized.

## Representative measurement and approval

The two frozen 2020-02-03..2020-02-28 runs each processed 18,201,043 raw rows in
about eight seconds. Measured throughput was 2.27-2.31 million rows/second;
median date processing was about 0.21 seconds. Peak RSS was 2.54 GiB or less,
opening reconciliation covered 71,481 sessions exactly, and both durable panel
and opening hashes reproduced.

Conservatively applying 2.0 million rows/second to 1,486,577,999 rows yields
12.4 minutes of raw calculation. Annual causal-context loads, integrity hashing,
serialization, and analysis retain a large margin inside the 90-minute ceiling.
The required scale is approved with the one-date batch, 8 GiB system-headroom,
and 3 GiB hard-RSS rules unchanged.
