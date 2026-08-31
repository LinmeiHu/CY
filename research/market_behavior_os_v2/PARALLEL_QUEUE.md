# Research OS V2.3 parallel queue

Director transition checkpoint: `1229079ed63ecc3a88ee4bb0ccb2c8e3d55557cc`.
One primary scientific frontier is active. Infrastructure, exploratory archaeology,
and QA do not create additional authoritative scientific frontiers.

| TASK_ID | LANE | SCIENTIFIC_ROLE | RESOURCE_CLASS | DEPENDENCIES | WORKER_BRANCH | EXPECTED_RUNTIME | EXPECTED_RAM | EXPECTED_IO | EXPECTED_OUTPUT_BYTES | STATUS | START_TIME | END_TIME | RESULT_CLASS |
|---|---|---|---|---|---|---:|---:|---|---:|---|---|---|---|
| DIR-V23-TRANSITION-001 | DIRECTOR | Profile host, freeze resource governance, reconstruct portfolio | LIGHT | clean pushed IMMED checkpoint | Director branch | 20 min | <0.5 GiB | metadata only | <1 MiB | COMPLETE | 2026-08-31T10:37:00+08:00 | 2026-08-31T10:45:00+08:00 | ACCEPT_INFRASTRUCTURE |
| A-FORMDEPTH-SUBGROUP-MAP-001 | A | Map own-security/shared-date/subgroup attribution before any response estimate | LIGHT then CPU_HEAVY | Director transition checkpoint; accepted formation chain | Director-owned freeze; worker branch after freeze | 30--120 min | <=1.5 GiB initial | compact panels/CY-006 only unless separately authorized | <100 MiB | QUEUED_PRIMARY |  |  |  |
| B-MIN-PRIMITIVE-DESIGN-001 | B | Audit adapters and design the minimal reusable security-session primitive cache; no alpha search | LIGHT then IO_HEAVY | isolated worktree; QD-004/CY-006/CY-008 hashes | pending isolated worker branch | 30--90 min design | <=1.5 GiB initial | one raw-minute reader maximum after Director approval | <5 MiB packet before cache | QUEUED_INFRASTRUCTURE |  |  |  |
| D-FORMDEPTH-QA-001 | D | Orthogonal hash/PIT/case reconstruction and independent compact-panel replication | CPU_HEAVY | isolated worktree; frozen formation artifacts | pending isolated worker branch | 30--120 min | <=1.5 GiB initial | compact artifacts only | <50 MiB | QUEUED_QA |  |  |  |
| C-CONSUMED-ARCH-001 | C | Pre-2024 winner/failure and candidate-funnel archaeology; hypothesis generation only | CPU_HEAVY | consumed-data lineage audit; slot after initial two workers | pending isolated worker branch | 60--180 min | <=1.5 GiB initial | compact consumed ledgers only | <100 MiB | QUEUED_NOT_STARTED |  |  |  |

At every launch the Director rechecks repository identity, worker isolation,
current RAM/swap/disk state, and aggregate thread declarations. Lane B may not
publish a shared cache until its schema and manifest are accepted.
