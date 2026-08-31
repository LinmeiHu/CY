# WORKER-MINUTE-001 specification

## Frozen assignment

- Lane: B, minute/data infrastructure only.
- Base: `fc665b016e2df01e11047a64e88f53905ccdcfdf`.
- Branch/worktree: `research/osv23-minute-001` at
  `/Users/linmei/Documents/CY-supermind-v6-worker-minute-001`.
- Inputs: registered QD-004, CY-006, CY-008 and already accepted minute
  contracts/adapters/artifacts only.
- Outcome access: prohibited.
- Shared-cache publication: prohibited in this worker packet.

## Question

What is the smallest reusable PIT-governed `SECURITY x SESSION` representation
that can prevent repeated multi-billion-row raw-minute reads without fixing an
alpha hypothesis or losing auction, lunch, close, missing-session, limit,
lineage, or corporate-action boundaries?

## Permitted work

1. Inspect manifests, Parquet metadata, accepted contracts, and adapters.
2. Read one frozen MKT-MIN-001 representative date.
3. Deterministically select 128 hard-valid sessions without outcomes.
4. Compare lossless long-row and fixed-array Parquet layouts in a temporary
   directory.
5. Design, but do not create or publish, the shared cache.

## Prohibited work

- Alpha search, return/outcome joins, winner/loser selection, trajectory or
  descriptor optimization.
- Full QD-004 scan, 2024+ scientific use, CY-011, strategy artifacts.
- New minute semantics, tolerance, rounding, adjusted-vendor substitution,
  same-bar fills, or repair of missing sessions.
- Edits outside this worker packet or any Director-owned central file.

## Acceptance gates

- Exact input-manifest hashes and inventoried file sizes.
- Timestamp grid exactly: 09:30 auction; 09:31..11:30 and 13:01..15:00
  continuous completed bar ends; no lunch rows.
- Raw/unadjusted price, shares, CNY; finite valid OHLC envelope.
- CY-006 hard-valid causal context and exact CY-006/CY-008 snapshot binding.
- CY-008 complete 241-row, source-resolution-one-minute, 15:30 session gate.
- Deterministic selection and candidate bytes/hashes.
- One thread and no shared-cache write.

## Required outputs

`WORKER_STATE.md`, `REPORT.md`, `result.json`, `RESOURCE_TELEMETRY.csv`,
`HANDOFF.md`, benchmark code/result, and focused tests.
