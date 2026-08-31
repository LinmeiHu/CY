# Research OS V2.3 worker registry

Workers may commit only to their isolated branch/worktree and packet namespace.
They cannot edit Director-owned state or integrate themselves.

| WORKER_ID | LANE | BRANCH | WORKTREE | BASE_COMMIT | OWNED_NAMESPACE | STATUS | HEAVY_CLASS | LAST_CHECKPOINT |
|---|---|---|---|---|---|---|---|---|
| DIRECTOR | DIRECTOR/A | `research/chinext-v1-research-os-v2` | `/Users/linmei/Documents/CY-supermind-v6-autonomous-20260830` | `1229079ed63ecc3a88ee4bb0ccb2c8e3d55557cc` | central authoritative OS | ACTIVE | scheduler/director | transition governance in progress |
| WORKER-MINUTE-001 | B | pending | pending | pending Director governance checkpoint | `worker_packets/WORKER-MINUTE-001/` | QUEUED | LIGHT then IO_HEAVY |  |
| WORKER-QA-001 | D | pending | pending | pending Director governance checkpoint | `worker_packets/WORKER-QA-001/` | QUEUED | CPU_HEAVY compact |  |
| WORKER-ARCH-001 | C | pending | pending | pending Director governance checkpoint | `worker_packets/WORKER-ARCH-001/` | QUEUED_AFTER_INITIAL_CAPACITY | CPU_HEAVY compact |  |

The Director integration gate requires ancestry, clean worktree, frozen hashes,
contract, worker handoff, tests, determinism, telemetry, and claim-boundary review.
