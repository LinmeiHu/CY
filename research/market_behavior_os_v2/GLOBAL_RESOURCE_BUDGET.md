# Research OS V2.3 global resource budget

Frozen from the measured host profile on 2026-08-31. Existing experiment-specific
contracts remain authoritative when stricter.

## Global envelope

| Resource | Initial rule |
|---|---|
| CPU | target 75--90% useful total utilization only while authorized work exists |
| Reserved CPU | 2 of 10 logical CPUs |
| Research threads | maximum 8 aggregate; default 1 internal thread/process |
| Heavy workloads | 2 initially; increase to 3 only after telemetry proves safety and throughput improvement |
| Heavy RSS | 1.5 GiB declared ceiling per initial worker; aggregate 3 GiB |
| System RAM headroom | at least 8 GiB and at least 25% physical RAM; use stricter rule |
| Swap | no sustained growth; pause new heavy launch at >=128 MiB growth and stop/rebalance at >=256 MiB growth or <256 MiB free |
| Raw-minute I/O | one full QD-004 scanner maximum unless benchmarked otherwise |
| DuckDB | job-specific memory frozen before outcomes; one thread by default |
| Disk | at least 25% free, approximately 231.5 GiB on the measured volume |
| Shared cache | planning ceiling 80 GiB; no unmanifested or duplicate raw data |

## Oversubscription environment

Unless a frozen worker packet assigns a smaller aggregate share, heavy commands
must start with:

```text
OMP_NUM_THREADS=1
OPENBLAS_NUM_THREADS=1
MKL_NUM_THREADS=1
VECLIB_MAXIMUM_THREADS=1
NUMEXPR_NUM_THREADS=1
POLARS_MAX_THREADS=1
```

## Promotion and reduction gates

Promote from two to three heavy workloads only when a telemetry interval shows:

- materially idle CPU after both jobs reach steady state;
- at least 8 GiB system headroom;
- no sustained swap growth;
- disk not saturated by the single raw scan;
- lower aggregate wall-clock per unit of scientific output.

Reduce concurrency immediately on memory-pressure deterioration, swap growth,
disk contention, or worse aggregate throughput. A scientific job that breaches
its frozen envelope fails closed; global capacity cannot rescue it.

## Measured single-job exception: formation-depth stratum construction

After both initial workers exited, the unchanged
`MKT-FORMDEPTH-OWN-DATA-001` attempt measured 2,628,616,192 bytes maximum RSS,
34.40 seconds wall time, and zero swaps. Memory-pressure free percentage was
65%, disk free was 347 GiB, and baseline swap occupancy was flat. This does not
validate or rescue 001. It permits a separately frozen 002 retry with:

- one heavy process total;
- one DuckDB and aggregate numerical thread;
- unchanged 1.5-GiB DuckDB memory limit;
- 3.0-GiB process peak-RSS ceiling;
- unchanged 8-GiB system-headroom and 25% disk-headroom floors;
- no simultaneous raw-minute scanner or other heavy worker.

The exception expires with that exact retry family and does not raise the
default worker ceiling or authorize a third heavy workload.
