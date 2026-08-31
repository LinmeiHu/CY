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

MKT-BREAKOUT-DIFF-DATA-001 reads only the six registered CY-006 daily
partitions and materializes no security-level durable output. The accepted staged
coordinate plan completes twice in about 30 seconds with peak RSS below 2.51 GB,
temporary usage below 2.33 GB, and 41,230 bytes of durable output. The fixed
1.5-GiB DuckDB, 3-GiB RSS, 8-GiB headroom, 10-GiB temporary, 20-GiB read,
100-MiB output, and ten-minute ceilings all pass.

MKT-BREAKOUT-DIFF-DYN-001 reads only the 11,336-row bound level panel and bound
breadth controls. It reads zero raw security/minute rows and writes 27,507,332
bytes before result/report. Each final run stays below the enforced 3-GiB RSS,
100-MiB durable-output, and five-minute ceilings. Volatile measured peak RSS is
not serialized; the deterministic artifact records the enforced ceiling and
gate result. Two final executions are byte-identical.

MKT-MIN-AD-001 reads only the 11,656-row bound daily minute-descriptor panel and
the bound MKT-MIN-SUPACC score panel. It reopens zero raw minute rows and
completes in seconds with a compact CSV/result/report. Two executions are
byte-identical; no resource expansion or new raw-data scan is authorized.

MKT-MIN-AD-GEO-001 reads three compact bound panels and joins 11,336 exact
completed-session keys. It reads zero raw security/minute rows, completes in
seconds, and produces compact panel/audit/result/report artifacts. Two runs are
byte-identical; no raw-data or resource expansion is authorized.

MKT-BREAKOUT-DIFF-001 reuses the same exact staged daily coordinate and reads no
minute partition. Both full representation runs complete in about 35 seconds,
peak RSS remains below 2.63 GB, and five durable files total 13,845,802 bytes.
The unchanged 1.5/3/8/10-GiB memory/RSS/headroom/spill and ten-minute/100-MiB
ceilings pass.

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

MKT-BREAKOUT-ECON-DATA-001 reads the same six governed CY-006 partitions and the
bound 11,336-row predictor panel. The simultaneous five-way future join correctly
failed at the unchanged 1.5-GiB DuckDB limit. The accepted plan retains and
narrows the exact coordinate table, joins one future step at a time by event year,
and drops each security response table after aggregation. Both complete runs stay
inside the frozen 1.5-GiB DuckDB, 3-GiB RSS, 8-GiB headroom, 10-GiB spill,
20-GiB read, 20-minute, and 100-MiB durable-output ceilings. Durable artifacts are
compact and byte-identical; no security-level response table is retained.

MKT-BREAKOUT-ECON-001 reads only four compact bound panels totaling 11,296 joined
response cells. Fixed level/year/phase, event/match, 200-shift placebo, and
two-control residual audits complete in under the five-minute ceiling and below
3 GiB RSS. Nine durable files remain under 100 MiB and reproduce byte-identically.
No raw security/minute data, strategy outcome, post-2023 row, or CY-011 is read.

HAB-CHX-FORMDEPTH-001 reads three compact bound panels and reuses all 2,436
HAB-CHX-001 rows. Fifteen fixed endpoint estimators and 30,000 deterministic
signal-date cluster bootstrap replicates complete well inside five minutes and
3 GiB RSS. Five durable outputs reproduce byte-identically under 100 MiB. No
source ledger, raw partition, post-2023 data, or CY-011 is opened.

MKT-FORMDEPTH-ATTR-001 reads only three compact bound panels plus their frozen
results. The 11,296-row join, 288 geometry rows, and 200 response-audit rows
complete in under two seconds and remain well below 3 GiB RSS, 8 GiB system
headroom, and 50 MiB durable output. Five artifacts reproduce byte-identically.
No raw security/minute data, strategy field, post-2023 row, or CY-011 is read.

MKT-FORMDEPTH-PROP-DATA-002 reuses the same six governed CY-006 partitions and
accepted action-coordinate builder under the inherited 1.5-GiB DuckDB, 3-GiB RSS,
8-GiB headroom, 10-GiB spill, 20-GiB read, 20-minute, and 100-MiB output ceilings.
The invalid 001 path writes no accepted arm artifact. Two corrected full runs
produce byte-identical compact artifacts and no security-level durable table.

MKT-FORMDEPTH-PROP-001 reads only the 11,336-row topology panel and 6,631-row
complete five-control join. Its 648-row response audit completes in about one
second below 3 GiB RSS and 50 MiB output; four artifacts reproduce byte-identically.
No raw data, strategy field, post-2023 row, or CY-011 is read.

MKT-FORMDEPTH-CLOSE-DATA-001 reuses the same six governed CY-006 partitions and
accepted action-coordinate builder under the inherited 1.5-GiB DuckDB, 3-GiB
RSS, 8-GiB headroom, 10-GiB spill, 20-GiB read, 20-minute, and 100-MiB output
ceilings. Each full build completes in about 42 seconds. The 11,336-row panel,
48-row count audit, and 255-row scalar audit reproduce byte-identically; no
security-level durable table is retained.

MKT-FORMDEPTH-CLOSE-001 reads only the 11,336-row bound closing panel and
6,627-row fixed-control join. Its compact response audit completes in about one
second below 3 GiB RSS and 50 MiB output; all four artifacts reproduce
byte-identically. No raw data, strategy field, post-2023 row, or CY-011 is read.

MKT-FORMDEPTH-PATH-DATA-001 reuses the six bound CY-006 partitions with mapped
open/low construction under the same 1.5/3/8/10/20-GiB DuckDB/RSS/headroom/spill/
read envelope and 20-minute/100-MiB ceilings. Each full build completes in about
58 seconds. Its compact panel/count/scalar/result/report artifacts reproduce
byte-identically and no security-level table is retained.

MKT-FORMDEPTH-PATH-001 reads only the bound 11,336-row component panel and
6,627-row fixed-control join. It completes in about one second under 3 GiB RSS
and 50 MiB output; four artifacts reproduce byte-identically. No raw data,
strategy field, post-2023 row, or CY-011 is read.
