# Market Behavior Research OS V2 experiment registry

| Experiment | Track | Question | Outcome access | Status | Evidence |
|---|---|---|---|---|---|
| MIGRATION-AUDIT-001 | Governance | Preserve seed evidence while moving the active frontier to market behavior | None | COMPLETE | Scope contract, atlas, family/archetype/library/frontier artifacts |
| MKT-TRND-001-A | MARKET engineering attempt | Execute frozen MKT-TRND-001 through pandas/pyarrow dataset reader | PROHIBITED | INVALID_BEFORE_FEATURE_CONSTRUCTION | Immutable hashes passed; reader raised `OSError: Repetition level histogram size mismatch` on the first source file; no feature, estimate, or output was produced |
| MKT-TRND-001-B | MARKET input-audit attempt | Execute frozen design through DuckDB adapter | PROHIBITED | INVALID_BEFORE_FEATURE_ACCEPTANCE | Reader passed; audit found `csi000852` 2016-08-11 close 8531.691 below recorded low 8532.329 and stopped; no feature accepted |
| MKT-TRND-001-C | MARKET | Freeze independent trend direction, quality, age/persistence, alignment, and transition coordinates across registered broad indices under the unchanged MKT-TRND-001 scientific spec | PROHIBITED | COMPLETE_DIRECTION_ONLY | 19,569 rows, six indices, 2010-06-01..2023-12-29; 21 OHLC rows fail closed. Direction passes coverage/stability and all three coordinates. Quality, age, transition fail neighbor stability; strength/alignment are data-contract-limited by rolling-window coverage. Successful runs byte-identical: panel `fd933284...`, result `784db3a5...`, tracked report `f4cadca6...` with complete quarantine ledger |

Failures, invalid executions, and representation rejections remain in this table;
rows are never deleted to improve the apparent success rate.
