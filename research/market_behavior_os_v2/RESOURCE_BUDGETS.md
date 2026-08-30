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
3. Representative: twenty consecutive full-market exchange dates spanning an
   ordinary and an abnormal/limit-state mix, with resource telemetry.
4. Required scale: every 2018-2023 exchange date under the unchanged scientific
   and resource contract.

No stage may proceed after semantic disagreement, nondeterminism, resource
ceiling breach, or a projection above the full-scale envelope.
