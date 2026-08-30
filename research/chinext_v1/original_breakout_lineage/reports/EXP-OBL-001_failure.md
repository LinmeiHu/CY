# EXP-OBL-001 invalid engineering attempt

EXP-OBL-001 stopped at its first frozen-input validation before any data row,
feature, lineage assignment, or outcome was read or calculated.

The frozen spec contains an incorrect holdout-membership hash:

```text
spec:   1af3577941081fb8354dae5112c08a89ca24c7d7c78f3bb3dd4943c3ead1ee0e
actual: 1af3577941081fb8354dae5112c08a89ca24c7d7c78f3fb3dd4943c3ead1ee0e
```

The actual hash is also the authoritative hash bound by the unchanged Phase-2
outcome-blind helper. The mismatch is a one-character preregistration binding
typo, not a scientific or data mutation.

Status: `INVALID_ENGINEERING_INPUT_BINDING`. No output exists and no scientific
result is attached to EXP-OBL-001. Its spec and runner remain immutable.

Continuation requires fresh EXP-OBL-002 identities and output paths. Every
scientific element remains unchanged; only the corrected binding and fresh
engineering identities are permitted.
