# EXP-OBL-013 engineering failure

Status: `INVALID_ENGINEERING_NULL_RIGHTS_COALESCE`.

The runner stopped during canonical signal-time volume-coordinate reconstruction.
The first differing field was optional `rights_ratio`: no-rights corporate-action
rows store it as null/NaN, while canonical `finite_or_default(..., 0.0)` semantics
coalesce it to zero. EXP-OBL-013 instead compared NaN to zero and failed the
valid-action assertion.

No feature table, assignment, audit, lineage freeze, or report was written. No
future outcome or post-entry field was read, and no scientific result was
accepted. The frozen EXP-OBL-013 runner and spec remain unchanged. EXP-OBL-014 is
the fresh scientifically identical reexecution; only null optional-rights
coalescing and experiment/output identities differ.
