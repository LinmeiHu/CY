# V12 monthly checkpoint + replay-journal prototype: 50-symbol evidence

Date: 2026-08-26  
Scope: offline prototype only; no production schema/code migration and no V13 full-market build.

## Result

The fixed stratified 50-symbol sample passed all exact comparisons. The monthly policy is below the capacity target, so the every-two-month fallback was not run.

- Capacity status: `TARGET_PASS`.
- 5210-symbol annualized durable size: 37.678 GiB.
- Target: no more than 45 GiB; hard failure above 50 GiB.
- Daily exact model comparisons: 36,450; mismatches: 0.
- Lifecycle anchor comparisons: 36,450; mismatches: 0.
- Frozen-oracle snapshot, transition, and feature mismatches: 0/0/0.

The exact checks covered operator digest, full POST-state digest, complete economic inventory identity, exact share IEEE-754 bits, daily feature digest, lineage shares, anchor retention bits, survival result, and destination mapping. No tolerance, rounding, float32, normalization, or relaxed comparison was used.

## Durable storage

All values below are MiB per symbol.

| Artifact | Mean | P50 | P90 | P99 |
|---|---:|---:|---:|---:|
| Opening + 12 month-end checkpoints | 7.244 | 7.181 | 9.278 | 10.847 |
| Minimal daily replay journal | 0.160 | 0.160 | 0.160 | 0.160 |
| Annual total | 7.405 | 7.343 | 9.439 | 11.008 |

The three seller models had 20,150,844 independent identities and 15,118,216 union identities: 24.97% identity overlap. Against physically written separate-model compressed counterfactuals, the shared union representation saved 62.587 MiB across the sample, or 14.73%.

Checkpoints use compressed flat NumPy SoA arrays, string pools, and explicit offsets. They preserve cost bucket, holding days, sensitivity, economic break-even IEEE-754 bits, exact shares, ordered lots, and seller/tracker continuation state. The daily journal contains only registered immutable input references/digests, corporate-action facts, model/transition/runtime hashes, operator digest, full POST digest, and feature digest; it contains no destination vectors, retention vectors, or full daily state.

## Measured timing

Times include the prototype's exact-evidence hashing and lifecycle instrumentation.

| Operation | Mean | P50 | P90 | P99 |
|---|---:|---:|---:|---:|
| Checkpoint load | 220.83 ms | 217.36 ms | 287.33 ms | 404.09 ms |
| Replay 1 trading day | 1.391 s | 1.384 s | 1.741 s | 2.126 s |
| Replay 5 trading days | 5.443 s | 5.378 s | 6.702 s | 8.326 s |
| Replay 10 trading days | 10.728 s | 10.709 s | 13.309 s | 16.266 s |
| Replay 22 trading days | 23.852 s | 23.736 s | 29.833 s | 36.236 s |
| Full-year sequential replay | 338.010 s | 335.478 s | 418.830 s | 447.165 s |
| Peak worker memory | 975.2 MiB | 1070.4 MiB | 1169.2 MiB | 1208.5 MiB |

The complete strict 50-symbol audit took 7,473.46 seconds (2.076 hours) with eight workers. It is intentionally much more expensive than one annual build: each symbol performs opening-state warm-up, a baseline year, independent checkpoint-origin monthly replays, four timing replays, and another full-year replay.

## Full-market runtime interpretation

The instrumented full-year replay mean implies 489.18 aggregate CPU-hours for 5,210 symbols. Ideal lower bounds, before scheduling, I/O, and long-tail allowance, are:

| Workers | Ideal wall time |
|---:|---:|
| 8 | 61.15 h |
| 10 | 48.92 h |
| 12 | 40.76 h |
| 16 | 30.57 h |
| 32 | 15.29 h |

On the current single machine, eight workers are the demonstrated setting and a conservative plan is about 2.5–3.5 days for the fully instrumented annual recomputation. Ten workers need a memory check: the measured per-worker P99 is about 1.21 GiB before coordinator and OS headroom.

This is deliberately separated from an existing V12 artifact-throughput heuristic: 427 completed operator-part files span 2026-08-25 22:18:55 to 23:59:34, which linearly extrapolates to about 20.5 hours for 5,210 symbols at that build's settings. That is not an apples-to-apples benchmark because it does not carry this prototype's validation-only daily identity/share/lifecycle evidence workload.

For a full-market recomputation from the current month's checkpoint, the measured means imply ideal ten-worker lower bounds of about 12 minutes for one day, 47 minutes for five days, 1.55 hours for ten days, and 3.45 hours for 22 days. Individual-symbol on-demand P99 is 2.13/8.33/16.27/36.24 seconds for 1/5/10/22 days.

## Acceleration implemented in the offline runner

- `--fast-validation` runs one 22-day prefix and records the 1/5/10/22 milestones, reuses the checkpoint-producing baseline as annual timing, and retains the complete independent monthly checkpoint-recompute exact comparisons.
- Per-symbol benchmark results are atomically persisted and reused only when the symbol, year, mode, semantic fingerprint, prototype/builder code, registered staged inputs, and frozen oracle all hash identically. Unknown or changed lineage fails closed to recomputation.
- Remaining work is submitted largest-first, using staged/oracle footprint as the scheduling weight, to reduce tail latency.

From the strict run's stage timings, removing duplicate horizons and the final timing-only annual replay eliminates about 379 seconds of work per average symbol. Relative to the observed strict audit CPU work, the expected saving is roughly 30%; this is an engineering estimate, not a rerun benchmark.

These runner changes reduce audit iteration time, not the canonical annual single pass. Further annual-build acceleration should be evaluated separately by profiling the transition kernel, omitting validation-only daily identity/share/lifecycle digests from the normal durable-build path, caching immutable decoded inputs behind exact digests, and horizontally sharding independent symbols. None of those production changes was made here.

## Reproduction

Strict benchmark command:

```bash
.venv/bin/python scripts/prototype_chip_checkpoint_recompute.py \
  --workers 8 \
  --output data/validation/v12_checkpoint_recompute_50_v1
```

Targeted tests:

```bash
.venv/bin/pytest -q tests/test_chip_checkpoint_recompute_prototype.py
```

Result: 4 passed.

Raw machine-readable report: `data/validation/v12_checkpoint_recompute_50_v1/benchmark_report.json`.

