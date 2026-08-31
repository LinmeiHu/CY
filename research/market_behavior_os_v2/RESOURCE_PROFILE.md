# Research OS V2.3 resource profile

Measured 2026-08-31 10:37--10:39 Asia/Shanghai on the authoritative Director
worktree at transition checkpoint `1229079ed63ecc3a88ee4bb0ccb2c8e3d55557cc`.
All measurements were read-only and required no privilege escalation.

## Host

| Field | Measured value |
|---|---|
| Model / architecture | `Mac17,2` / `arm64` |
| macOS | 26.5.1 (25F80) |
| Logical CPUs | 10 |
| Physical CPUs | 10 |
| Physical RAM | 34,359,738,368 bytes = 32.0 GiB |
| Baseline CPU | 19.9% user, 14.4% system, 65.7% idle |
| Baseline load average | 4.69 / 4.48 / 4.25 |
| Direct unused RAM | approximately 1.60 GiB |
| Compressor | approximately 7.06 GiB physical compressor footprint |
| Memory-pressure free percentage | 62--63% |
| Swap | 3.00 GiB total; 2.409 GiB used; 0.591 GiB free |
| Data-volume capacity | 926 GiB |
| Data-volume free | 348 GiB (39%) |
| Required 25% disk headroom | approximately 231.5 GiB |

The host has ample CPU and disk capacity, but current swap occupancy is high.
No baseline swap growth occurred during the short telemetry sample. New heavy
work therefore starts conservatively and is promoted only after a longer stable
sample.

## Current material processes

At profiling time:

- Parallels VM: approximately 7.74 GiB RSS and about 85% of one CPU core;
- ChatGPT/Codex renderer: approximately 1.05 GiB RSS and about 9% of one core;
- Chrome renderer: approximately 1.27 GiB RSS;
- other Codex processes: bounded orchestration/UI load;
- no active DuckDB process and no material research Python CPU workload;
- one idle `python -` process at approximately 33 MiB RSS;
- measured disk service was transiently about 0.05--14.8 MiB/s after the
  cumulative boot statistic, not an active saturated raw-minute scan.

External user processes are not terminated or modified by Research OS.

## Minute-data physical layout

### QD-004 raw canonical one-minute bars

- location: `/Users/linmei/Downloads/workspace/quant/data/lake/stock_1min_canonical_none_20260813`;
- physical size: approximately 40 GiB;
- layout: one annual Parquet under `bars/` for 2000--2025 plus 2026 day and QMT
  tail files; separate annual anomaly Parquets and manifest/build metadata;
- active immutable target: 2018-01-01..2026-08-12, nine annual day files plus
  the 2026 QMT tail;
- content-inventory hash: `767298a88618f30d4cc6d5db8a7f609670f88ba32987de6a32994844ad75746c`;
- raw/unadjusted CNY/share, volume shares, amount CNY, completed-bar timestamp;
- PIT grade B: no archival record-level availability, so strict PIT-A claims are
  prohibited.

### CY-008 causal minute PIT-B table

- location: `/Users/linmei/Documents/CY/data/processed/pit_b_minute_2018_2026_v2`;
- physical size: approximately 3.1 GiB;
- 27 files: nine annual `daily` Parquets, nine annual `execution_5m` Parquets,
  and nine annual audit JSON files;
- daily rows: 9,365,043; execution-window rows: 56,190,252;
- content-inventory hash: `5903149da5d8afe37fa18719d17e8a5726856d11e8441d25d51217b05d6adf9f`;
- exact source binding: QD-004 + CY-006; row-level `available_at`, `snapshot_id`,
  and `hard_valid`; same-bar fills remain prohibited.

### CY-006 daily causal context

- location: `/Users/linmei/Documents/CY/data/processed/pit_b_daily_2018_2026_v2/daily`;
- physical size: approximately 439 MiB;
- nine annual Parquets plus audit JSON;
- content-inventory hash: `de8795f2ff78947997930933ad3354c7aa0c208fe0c4d3c09427c0d043e78ae2`.

## Safe initial resource decision

- reserve two logical CPUs for macOS, Codex, Git, filesystem, and recovery;
- research thread budget: eight logical CPUs aggregate, with per-process BLAS,
  OpenMP, NumExpr, and Polars defaults forced to one unless a frozen job assigns
  an explicit share;
- initial heavy concurrency: two, each declared at no more than 1.5 GiB RSS;
- raw-minute scanners: at most one;
- minimum system headroom: 8 GiB and the stricter frozen experiment rule;
- no increase to three heavy jobs until swap used is stable, at least 8 GiB
  headroom remains, and measured total throughput improves;
- estimated safe derived-cache allocation: 80 GiB, subject to a hard 231.5 GiB
  free-disk floor and per-generation size estimate/manifest.

The 80-GiB cache allowance is a planning ceiling, not authorization to build a
large cache. Every generation requires a separate manifest, one writer, temporary
write, validation, and atomic publish.

## Adaptive observation after initial workers

Both initial worker processes had exited before the Director measured the
formation-depth stratum builder. The unchanged one-thread attempt reported
2,628,616,192 bytes maximum RSS, 1,983,744,520 bytes peak memory footprint,
34.40 seconds wall time, and zero swaps. At admission, memory-pressure free
percentage was 65%, swap used was 2,435.31 MiB, and disk free was 347 GiB.

The 1.5-GiB attempt remains invalid. These measurements support only the
single-job, separately frozen 3.0-GiB retry described in
`GLOBAL_RESOURCE_BUDGET.md`; they do not change the default two-worker policy.
