# EXP-RTD-001 fail-closed record

The first frozen execution stopped before any output artifact was written.
`index_realized_vol20` was selected from both accepted inputs, the merge suffixed
both copies, and the risk-control stage requested the absent unsuffixed name.

Some calculations had begun in memory, so EXP-RTD-001 is invalidated rather than
repaired or rerun. No estimate was printed or inspected. Bound inputs remain
unchanged and all three output paths remain absent. Continuation requires a new
EXP-RTD-002 runner, spec, integrity snapshot, and output namespace.
